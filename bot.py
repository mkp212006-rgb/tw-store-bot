import asyncio
import json
import os
import re
import secrets
import logging
import threading
import uuid
import requests
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None
try:
    from flask import Flask, request, jsonify
except Exception:
    Flask = request = jsonify = None
from io import BytesIO
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = ImageDraw = ImageFont = None

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BASE_DIR = Path(__file__).resolve().parent
if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env")

CATALOGO_PATH = BASE_DIR / "catalogo.json"
PAGAMENTO_INSTAGRAM_LAYOUT_PATH = BASE_DIR / "pagamento_instagram_layout.png"
PAGAMENTO_TIKTOK_LAYOUT_PATH = BASE_DIR / "pagamento_tiktok_layout.png"

with open(CATALOGO_PATH, "r", encoding="utf-8") as f:
    CATALOGO = json.load(f)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
PIX_CHAVE = os.getenv("PIX_CHAVE", "").strip()
PIX_COPIA_COLA = os.getenv("PIX_COPIA_COLA", "").strip()
PIX_RECEBEDOR = os.getenv("PIX_RECEBEDOR", "").strip()

# API da plataforma de pedidos.
# Preencha essas variáveis no .env antes de colocar o bot em produção.
PANEL_API_URL = os.getenv("PANEL_API_URL", "").strip()
PANEL_API_KEY = os.getenv("PANEL_API_KEY", "").strip()
try:
    PANEL_API_TIMEOUT = int(os.getenv("PANEL_API_TIMEOUT", "30"))
except ValueError:
    PANEL_API_TIMEOUT = 30

# Mercado Pago — Pix automático.
# Configure essas variáveis no Railway, nunca direto no código.
MERCADO_PAGO_ACCESS_TOKEN = os.getenv("MERCADO_PAGO_ACCESS_TOKEN", "").strip()
MP_PAYER_EMAIL = os.getenv("MP_PAYER_EMAIL", "cliente@ttwostore.com").strip()
MP_WEBHOOK_URL = os.getenv("MP_WEBHOOK_URL", "").strip()
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "").strip()
try:
    MP_API_TIMEOUT = int(os.getenv("MP_API_TIMEOUT", "30"))
except ValueError:
    MP_API_TIMEOUT = 30


TZ_BR = ZoneInfo("America/Sao_Paulo")
TOTAIS_SEMANAIS_PATH = BASE_DIR / "totais_semanais.json"
PEDIDOS_PENDENTES_PATH = BASE_DIR / "pedidos_pendentes.json"
COMPROVANTES_USADOS_PATH = BASE_DIR / "comprovantes_usados.json"
PAGAMENTOS_PROCESSADOS_PATH = BASE_DIR / "pagamentos_processados.json"
PEDIDOS_HISTORICO_PATH = BASE_DIR / "pedidos_historico.json"

# Evita processar o mesmo pagamento duas vezes quando o Mercado Pago reenvia
# notificações ou quando cliente toca em "verificar" ao mesmo tempo do webhook.
_MP_PAYMENTS_LOCK = threading.Lock()
_MP_PAYMENTS_EM_PROCESSAMENTO = set()


def agora_br() -> datetime:
    return datetime.now(TZ_BR)


def carregar_json(caminho: Path, padrao):
    if not caminho.exists():
        return padrao.copy() if isinstance(padrao, dict) else padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except Exception:
        return padrao.copy() if isinstance(padrao, dict) else padrao
    return dados if isinstance(dados, type(padrao)) else (padrao.copy() if isinstance(padrao, dict) else padrao)


def salvar_json(caminho: Path, dados):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def gerar_pedido_id() -> str:
    return f"TW{agora_br():%Y%m%d%H%M%S}{secrets.token_hex(2).upper()}"


def preparar_pedido(pedido: dict) -> dict:
    pedido.setdefault("pedido_id", gerar_pedido_id())
    pedido.setdefault("criado_em", agora_br().strftime("%d/%m/%Y %H:%M:%S"))
    return pedido


def carregar_pedidos_pendentes() -> dict:
    return carregar_json(PEDIDOS_PENDENTES_PATH, {})


def salvar_pedidos_pendentes(dados: dict):
    salvar_json(PEDIDOS_PENDENTES_PATH, dados)


def salvar_pedido_pendente(pedido: dict):
    pendentes = carregar_pedidos_pendentes()
    pedido_id = str(pedido.get("pedido_id") or gerar_pedido_id())
    pedido["pedido_id"] = pedido_id
    pendentes[pedido_id] = pedido
    salvar_pedidos_pendentes(pendentes)


def obter_pedido_pendente(pedido_id: str) -> dict | None:
    return carregar_pedidos_pendentes().get(str(pedido_id))


def remover_pedido_pendente(pedido_id: str):
    pendentes = carregar_pedidos_pendentes()
    pendentes.pop(str(pedido_id), None)
    salvar_pedidos_pendentes(pendentes)


def carregar_pedidos_historico() -> dict:
    return carregar_json(PEDIDOS_HISTORICO_PATH, {})


def salvar_pedido_historico(pedido: dict):
    if not pedido:
        return
    historico = carregar_pedidos_historico()
    pedido_id = str(pedido.get("pedido_id") or gerar_pedido_id())
    registro = dict(pedido)
    registro["pedido_id"] = pedido_id
    registro["historico_atualizado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    historico[pedido_id] = registro
    salvar_json(PEDIDOS_HISTORICO_PATH, historico)


def normalizar_id_consulta(texto: str) -> str:
    texto = str(texto or "").strip()
    texto = re.sub(r"[^A-Za-z0-9_-]+", "", texto)
    return texto[:80]


def buscar_pedido_local_por_id(consulta_id: str) -> tuple[dict | None, str | None]:
    consulta_id = normalizar_id_consulta(consulta_id)
    if not consulta_id:
        return None, None

    pendentes = carregar_pedidos_pendentes()
    if consulta_id in pendentes:
        return pendentes[consulta_id], "pendente"

    consulta_lower = consulta_id.lower()
    for pedido in pendentes.values():
        candidatos = [
            pedido.get("pedido_id"),
            pedido.get("plataforma_order_id"),
            pedido.get("mp_payment_id"),
        ]
        if any(str(item or "").lower() == consulta_lower for item in candidatos):
            return pedido, "pendente"

    historico = carregar_pedidos_historico()
    if consulta_id in historico:
        return historico[consulta_id], "historico"

    for pedido in historico.values():
        candidatos = [
            pedido.get("pedido_id"),
            pedido.get("plataforma_order_id"),
            pedido.get("mp_payment_id"),
        ]
        if any(str(item or "").lower() == consulta_lower for item in candidatos):
            return pedido, "historico"

    return None, None


def pedido_tem_id_plataforma(order_id) -> bool:
    texto = str(order_id or "").strip()
    if not texto:
        return False
    return texto.lower() not in ("não informado", "nao informado", "none", "null", "0")


def carregar_comprovantes_usados() -> dict:
    return carregar_json(COMPROVANTES_USADOS_PATH, {})


def comprovante_ja_usado(file_unique_id: str | None) -> bool:
    if not file_unique_id:
        return False
    return str(file_unique_id) in carregar_comprovantes_usados()


def marcar_comprovante_usado(file_unique_id: str | None, pedido: dict):
    if not file_unique_id:
        return
    usados = carregar_comprovantes_usados()
    usados[str(file_unique_id)] = {
        "pedido_id": pedido.get("pedido_id"),
        "user_id": pedido.get("user_id"),
        "valor": pedido.get("valor"),
        "registrado_em": agora_br().strftime("%d/%m/%Y %H:%M:%S"),
    }
    salvar_json(COMPROVANTES_USADOS_PATH, usados)


def eh_admin(update: Update) -> bool:
    if not ADMIN_CHAT_ID:
        return False
    user_id = str(update.effective_user.id) if update.effective_user else ""
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    return ADMIN_CHAT_ID in (user_id, chat_id)


def semana_info(dt: datetime | None = None) -> dict:
    dt = dt or agora_br()
    iso_year, iso_week, _ = dt.isocalendar()
    segunda = (dt - timedelta(days=dt.weekday())).date()
    domingo = segunda + timedelta(days=6)
    return {
        "id": f"{iso_year}-W{iso_week:02d}",
        "inicio": segunda.strftime("%d/%m/%Y"),
        "fim": domingo.strftime("%d/%m/%Y"),
    }


def novo_registro_semanal(dt: datetime | None = None) -> dict:
    info = semana_info(dt)
    return {
        "semana_id": info["id"],
        "inicio": info["inicio"],
        "fim": info["fim"],
        "clientes": {},
    }


def carregar_totais_semanais() -> dict:
    if not TOTAIS_SEMANAIS_PATH.exists():
        return novo_registro_semanal()

    try:
        with open(TOTAIS_SEMANAIS_PATH, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except Exception:
        return novo_registro_semanal()

    if "semana_id" not in dados or "clientes" not in dados:
        return novo_registro_semanal()

    return dados


def salvar_totais_semanais(dados: dict):
    with open(TOTAIS_SEMANAIS_PATH, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def valor_para_centavos(valor) -> int:
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    texto = texto.replace(".", "").replace(",", ".")
    try:
        return int(round(float(texto) * 100))
    except ValueError:
        return 0


def centavos_para_moeda(centavos: int) -> str:
    reais = centavos / 100
    texto = f"{reais:,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


async def enviar_resumo_semanal_admin(bot, dados: dict):
    if not ADMIN_CHAT_ID or not dados.get("clientes"):
        return

    clientes = list(dados["clientes"].values())
    clientes.sort(key=lambda item: int(item.get("total_centavos", 0)), reverse=True)

    total_geral = sum(int(cliente.get("total_centavos", 0)) for cliente in clientes)
    linhas = [
        "📊 *FECHAMENTO SEMANAL — TW STORE*",
        "",
        f"🗓️ *Período:* {md(dados.get('inicio', ''))} até {md(dados.get('fim', ''))}",
        f"💰 *Total geral:* R$ {md(centavos_para_moeda(total_geral))}",
        f"👥 *Clientes:* {len(clientes)}",
        "",
        "*Valores usados por cliente:*",
    ]

    for cliente in clientes:
        username = f"@{cliente.get('username')}" if cliente.get("username") else "Sem username"
        linhas.append(
            f"• {md(cliente.get('usuario', 'Cliente'))} | {md(username)} | "
            f"ID: `{cliente.get('user_id', '')}` — "
            f"R$ {md(centavos_para_moeda(int(cliente.get('total_centavos', 0))))} "
            f"({int(cliente.get('pedidos', 0))} pedido(s))"
        )

    texto = "\n".join(linhas)

    # Evita erro caso o relatório fique muito grande.
    partes = []
    while len(texto) > 3900:
        corte = texto.rfind("\n", 0, 3900)
        if corte == -1:
            corte = 3900
        partes.append(texto[:corte])
        texto = texto[corte:].lstrip()
    partes.append(texto)

    for parte in partes:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=parte,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )


async def fechar_semana_se_necessario(bot):
    dados = carregar_totais_semanais()
    semana_atual = semana_info()

    if dados.get("semana_id") != semana_atual["id"]:
        await enviar_resumo_semanal_admin(bot, dados)
        salvar_totais_semanais(novo_registro_semanal())


def registrar_pedido_semanal(pedido: dict) -> str:
    dados = carregar_totais_semanais()
    semana_atual = semana_info()

    if dados.get("semana_id") != semana_atual["id"]:
        dados = novo_registro_semanal()

    user_id = str(pedido.get("user_id"))
    valor_centavos = valor_para_centavos(pedido.get("valor", "0"))

    cliente = dados["clientes"].setdefault(
        user_id,
        {
            "user_id": pedido.get("user_id"),
            "usuario": pedido.get("usuario", "Cliente"),
            "username": pedido.get("username"),
            "total_centavos": 0,
            "pedidos": 0,
        },
    )

    cliente["usuario"] = pedido.get("usuario", cliente.get("usuario", "Cliente"))
    cliente["username"] = pedido.get("username", cliente.get("username"))
    cliente["total_centavos"] = int(cliente.get("total_centavos", 0)) + valor_centavos
    cliente["pedidos"] = int(cliente.get("pedidos", 0)) + 1

    salvar_totais_semanais(dados)
    return centavos_para_moeda(int(cliente["total_centavos"]))


async def rotina_fechamento_semanal(application: Application):
    await fechar_semana_se_necessario(application.bot)

    while True:
        agora = agora_br()
        dias_ate_proxima_segunda = 7 - agora.weekday()
        proxima_segunda = agora.date() + timedelta(days=dias_ate_proxima_segunda)
        proximo_fechamento = datetime.combine(proxima_segunda, time.min, tzinfo=TZ_BR)

        segundos = max(60, (proximo_fechamento - agora).total_seconds())
        await asyncio.sleep(segundos)
        await fechar_semana_se_necessario(application.bot)


async def iniciar_rotina_fechamento(application: Application):
    application.create_task(rotina_fechamento_semanal(application))



def md(texto) -> str:
    return escape_markdown(str(texto), version=1)


def money(valor: str) -> str:
    return f"R$ {valor}"


CATALOGOS_COM_ENVIO_API = {"Instagram", "TikTok"}


class PlataformaAPIConfigError(Exception):
    pass


class PlataformaAPIRequestError(Exception):
    pass


def limpar_erro_api(erro) -> str:
    texto = str(erro or "").strip()
    if PANEL_API_KEY:
        texto = texto.replace(PANEL_API_KEY, "***")
    if MERCADO_PAGO_ACCESS_TOKEN:
        texto = texto.replace(MERCADO_PAGO_ACCESS_TOKEN, "***")

    # Nunca envia para o cliente dados financeiros retornados pelo painel.
    # Alguns painéis retornam campos como charge/currency até em mensagens de erro.
    texto = re.sub(r"(['\"]?charge['\"]?\s*[:=]\s*)['\"]?[^,}\n]+", r"\1***", texto, flags=re.IGNORECASE)
    texto = re.sub(r"(['\"]?currency['\"]?\s*[:=]\s*)['\"]?[^,}\n]+", r"\1***", texto, flags=re.IGNORECASE)
    texto = re.sub(r"valor\s+cobrado\s+no\s+painel\s*[:=]?\s*[^,}\n]+", "valor cobrado no painel: ***", texto, flags=re.IGNORECASE)
    texto = re.sub(r"moeda\s*[:=]\s*[^,}\n]+", "moeda: ***", texto, flags=re.IGNORECASE)

    return texto[:900]


class MercadoPagoConfigError(Exception):
    pass


class MercadoPagoRequestError(Exception):
    pass


def mercado_pago_configurado() -> bool:
    return bool(MERCADO_PAGO_ACCESS_TOKEN)


def valor_pedido_float(valor) -> float:
    centavos = valor_para_centavos(valor)
    if centavos <= 0:
        raise MercadoPagoConfigError("Valor do pedido inválido para gerar Pix.")
    return round(centavos / 100, 2)


def mp_headers(pedido_id: str | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {MERCADO_PAGO_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    if pedido_id:
        headers["X-Idempotency-Key"] = f"tw-store-{pedido_id}-{uuid.uuid4().hex[:8]}"
    return headers


def criar_pagamento_mercado_pago_sync(pedido: dict) -> dict:
    if not MERCADO_PAGO_ACCESS_TOKEN:
        raise MercadoPagoConfigError("MERCADO_PAGO_ACCESS_TOKEN não configurado.")

    pedido_id = str(pedido.get("pedido_id") or gerar_pedido_id())
    pedido["pedido_id"] = pedido_id

    descricao = f"{pedido.get('catalogo', 'Pedido')} - {pedido.get('servico', '')} - {pedido.get('quantidade', '')}".strip()
    payload = {
        "transaction_amount": valor_pedido_float(pedido.get("valor")),
        "description": descricao[:250],
        "payment_method_id": "pix",
        "external_reference": pedido_id,
        "payer": {
            "email": MP_PAYER_EMAIL or "cliente@ttwostore.com",
        },
    }
    if MP_WEBHOOK_URL:
        payload["notification_url"] = MP_WEBHOOK_URL

    try:
        resposta = requests.post(
            "https://api.mercadopago.com/v1/payments",
            headers=mp_headers(pedido_id),
            json=payload,
            timeout=MP_API_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MercadoPagoRequestError(f"Falha de conexão com Mercado Pago: {limpar_erro_api(exc)}") from exc

    try:
        dados = resposta.json()
    except ValueError:
        dados = {"raw": resposta.text[:500]}

    if resposta.status_code not in (200, 201):
        raise MercadoPagoRequestError(
            f"Mercado Pago respondeu HTTP {resposta.status_code}: {limpar_erro_api(dados)}"
        )

    transaction_data = (
        dados.get("point_of_interaction", {})
        .get("transaction_data", {})
    )
    qr_code = transaction_data.get("qr_code") or ""
    qr_code_base64 = transaction_data.get("qr_code_base64") or ""
    ticket_url = transaction_data.get("ticket_url") or ""

    if not qr_code:
        raise MercadoPagoRequestError("Mercado Pago criou o pagamento, mas não retornou Pix copia e cola.")

    return {
        "id": str(dados.get("id")),
        "status": dados.get("status"),
        "status_detail": dados.get("status_detail"),
        "external_reference": dados.get("external_reference"),
        "transaction_amount": dados.get("transaction_amount"),
        "qr_code": qr_code,
        "qr_code_base64": qr_code_base64,
        "ticket_url": ticket_url,
        "raw": dados,
    }


def consultar_pagamento_mercado_pago_sync(payment_id: str) -> dict:
    if not MERCADO_PAGO_ACCESS_TOKEN:
        raise MercadoPagoConfigError("MERCADO_PAGO_ACCESS_TOKEN não configurado.")

    try:
        resposta = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers={"Authorization": f"Bearer {MERCADO_PAGO_ACCESS_TOKEN}"},
            timeout=MP_API_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MercadoPagoRequestError(f"Falha de conexão com Mercado Pago: {limpar_erro_api(exc)}") from exc

    try:
        dados = resposta.json()
    except ValueError:
        dados = {"raw": resposta.text[:500]}

    if not resposta.ok:
        raise MercadoPagoRequestError(
            f"Mercado Pago respondeu HTTP {resposta.status_code}: {limpar_erro_api(dados)}"
        )

    return dados


def aplicar_pagamento_mercado_pago_no_pedido(pedido: dict, pagamento: dict):
    pedido["mp_payment_id"] = str(pagamento.get("id") or "")
    pedido["mp_status"] = str(pagamento.get("status") or "")
    pedido["mp_status_detail"] = str(pagamento.get("status_detail") or "")
    pedido["mp_external_reference"] = str(pagamento.get("external_reference") or "")
    pedido["mp_qr_code"] = pagamento.get("qr_code") or pedido.get("mp_qr_code") or ""
    pedido["mp_ticket_url"] = pagamento.get("ticket_url") or pedido.get("mp_ticket_url") or ""
    pedido["status"] = "aguardando_pagamento"
    pedido["pagamento_criado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")


async def garantir_pagamento_mercado_pago(pedido: dict) -> tuple[bool, str]:
    if not mercado_pago_configurado():
        return False, "Mercado Pago não configurado."

    if pedido.get("mp_payment_id") and pedido.get("mp_qr_code"):
        salvar_pedido_pendente(pedido)
        return True, "Pagamento já criado."

    try:
        pagamento = await asyncio.to_thread(criar_pagamento_mercado_pago_sync, pedido)
    except Exception as exc:
        return False, limpar_erro_api(exc)

    aplicar_pagamento_mercado_pago_no_pedido(pedido, pagamento)
    salvar_pedido_pendente(pedido)
    return True, "Pagamento criado."


def obter_pedido_por_pagamento(payment_id: str | None = None, external_reference: str | None = None) -> dict | None:
    pendentes = carregar_pedidos_pendentes()
    if external_reference and str(external_reference) in pendentes:
        return pendentes[str(external_reference)]

    for pedido in pendentes.values():
        if payment_id and str(pedido.get("mp_payment_id")) == str(payment_id):
            return pedido
        if external_reference and str(pedido.get("pedido_id")) == str(external_reference):
            return pedido
    return None


def carregar_pagamentos_processados() -> dict:
    return carregar_json(PAGAMENTOS_PROCESSADOS_PATH, {})


def pagamento_ja_processado(payment_id: str) -> bool:
    if not payment_id:
        return False
    return str(payment_id) in carregar_pagamentos_processados()


def iniciar_processamento_pagamento(payment_id: str) -> bool:
    """Reserva o pagamento para processamento nesta instância."""
    if not payment_id:
        return True
    payment_id = str(payment_id)
    with _MP_PAYMENTS_LOCK:
        if payment_id in _MP_PAYMENTS_EM_PROCESSAMENTO:
            return False
        if pagamento_ja_processado(payment_id):
            return False
        _MP_PAYMENTS_EM_PROCESSAMENTO.add(payment_id)
        return True


def finalizar_processamento_pagamento(payment_id: str):
    if not payment_id:
        return
    with _MP_PAYMENTS_LOCK:
        _MP_PAYMENTS_EM_PROCESSAMENTO.discard(str(payment_id))


def marcar_pagamento_processado(payment_id: str, pedido: dict):
    if not payment_id:
        return
    dados = carregar_pagamentos_processados()
    dados[str(payment_id)] = {
        "pedido_id": pedido.get("pedido_id"),
        "user_id": pedido.get("user_id"),
        "valor": pedido.get("valor"),
        "processado_em": agora_br().strftime("%d/%m/%Y %H:%M:%S"),
    }
    salvar_json(PAGAMENTOS_PROCESSADOS_PATH, dados)


def pagamento_aprovado_e_valido(pedido: dict, pagamento: dict) -> tuple[bool, str]:
    if str(pagamento.get("status")) != "approved":
        return False, f"Status ainda não aprovado: {pagamento.get('status')}"

    payment_id = str(pagamento.get("id") or "")
    if payment_id and pagamento_ja_processado(payment_id):
        return False, "Pagamento já processado anteriormente."

    external_reference = str(pagamento.get("external_reference") or "")
    pedido_id = str(pedido.get("pedido_id") or "")
    if external_reference and pedido_id and external_reference != pedido_id:
        return False, "Referência externa do pagamento não pertence a este pedido."

    esperado = valor_para_centavos(pedido.get("valor"))
    recebido = int(round(float(pagamento.get("transaction_amount") or 0) * 100))
    if esperado <= 0 or recebido != esperado:
        return False, f"Valor divergente. Esperado {esperado} centavos, recebido {recebido} centavos."

    return True, "OK"


def telegram_api_url(metodo: str) -> str:
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{metodo}"


def enviar_telegram_sync(chat_id, text: str, reply_markup: dict | None = None, parse_mode: str = "Markdown"):
    if not BOT_TOKEN or not chat_id:
        return
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(telegram_api_url("sendMessage"), json=payload, timeout=20)
    except Exception as exc:
        logging.warning("Falha ao enviar mensagem Telegram via API: %s", exc)


def montar_relatorio_admin_sync(pedido: dict) -> str:
    total_semanal_cliente = registrar_pedido_semanal(pedido)
    username = f"@{pedido.get('username')}" if pedido.get("username") else "Sem username"

    bloco_api = ""
    if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
        if pedido.get("plataforma_api_status") == "enviado":
            bloco_api = (
                f"🚀 *API plataforma:* Enviado\n"
                f"🆔 *Pedido na plataforma:* `{md(pedido.get('plataforma_order_id', 'Não informado'))}`\n"
                f"🔧 *Service ID:* `{md(pedido.get('plataforma_service_id', ''))}`\n"
            )
        else:
            bloco_api = (
                f"🚀 *API plataforma:* Falhou ou não configurada\n"
                f"⚠️ *Erro:* {md(pedido.get('plataforma_api_erro', 'Sem retorno da API'))}\n"
            )

    return (
        "📥 *NOVO PEDIDO PAGO — TW STORE*\n\n"
        f"🆔 *Pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
        f"💳 *Mercado Pago ID:* `{md(pedido.get('mp_payment_id', ''))}`\n"
        f"🗂️ *Catálogo:* {md(pedido.get('catalogo', ''))}\n"
        f"📌 *Serviço:* {md(pedido.get('servico', ''))}\n"
        f"🔢 *Quantidade:* {md(pedido.get('quantidade', ''))}\n"
        f"💰 *Valor:* R$ {md(pedido.get('valor', ''))}\n"
        f"📆 *Total do cliente nesta semana:* R$ {md(total_semanal_cliente)}\n"
        f"🔗 *Link/@:* {md(pedido.get('link', ''))}\n"
        f"{bloco_api}\n"
        f"👤 *Cliente:* {md(pedido.get('usuario', 'Cliente'))}\n"
        f"📱 *Telegram:* {md(username)}\n"
        f"🆔 *ID:* `{pedido.get('user_id', '')}`\n"
        f"✅ *Aprovado por:* Mercado Pago\n"
        f"🕒 *Data:* {agora_br().strftime('%d/%m/%Y %H:%M:%S')}"
    )


def processar_pagamento_aprovado_sync(pedido: dict, pagamento: dict, origem: str = "webhook") -> bool:
    if not pedido:
        return False

    payment_id = str(pagamento.get("id") or pedido.get("mp_payment_id") or "")
    if payment_id and not iniciar_processamento_pagamento(payment_id):
        logging.info("Pagamento %s já está em processamento ou já foi processado.", payment_id)
        return False

    try:
        valido, motivo = pagamento_aprovado_e_valido(pedido, pagamento)
        if not valido:
            logging.warning("Pagamento não processado: %s", motivo)
            return False

        pedido["status"] = "pagamento_aprovado"
        pedido["mp_payment_id"] = payment_id
        pedido["mp_status"] = str(pagamento.get("status") or "approved")
        pedido["aprovado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
        pedido["aprovado_por"] = "Mercado Pago"
        pedido["processado_por"] = origem

        if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
            try:
                resultado = criar_pedido_plataforma_sync(pedido)
                pedido["plataforma_api_status"] = "enviado"
                pedido["plataforma_service_id"] = resultado.get("service_id")
                pedido["plataforma_quantidade"] = resultado.get("quantity")
                pedido["plataforma_order_id"] = resultado.get("order_id") or "Não informado"
                pedido["plataforma_resposta"] = resultado.get("response")
            except Exception as exc:
                pedido["plataforma_api_status"] = "erro"
                pedido["plataforma_api_erro"] = limpar_erro_api(exc)

        salvar_pedido_historico(pedido)
        marcar_pagamento_processado(payment_id, pedido)
        remover_pedido_pendente(str(pedido.get("pedido_id") or ""))

        if ADMIN_CHAT_ID:
            relatorio = montar_relatorio_admin_sync(pedido)
            while len(relatorio) > 3900:
                corte = relatorio.rfind("\n", 0, 3900)
                if corte == -1:
                    corte = 3900
                enviar_telegram_sync(ADMIN_CHAT_ID, relatorio[:corte])
                relatorio = relatorio[corte:].lstrip()
            enviar_telegram_sync(ADMIN_CHAT_ID, relatorio)

        teclado_menu = {"inline_keyboard": [[{"text": "🏠 Menu inicial", "callback_data": "voltar:inicio"}]]}
        enviar_telegram_sync(
            pedido.get("user_id"),
            texto_final_pedido(pedido),
            reply_markup=teclado_menu,
        )
        return True
    finally:
        finalizar_processamento_pagamento(payment_id)


def processar_notificacao_mercado_pago_sync(payment_id: str, origem: str = "webhook") -> bool:
    """Consulta o Mercado Pago e processa o pedido fora da resposta HTTP do webhook."""
    try:
        pagamento = consultar_pagamento_mercado_pago_sync(payment_id)
        if str(pagamento.get("status")) != "approved":
            logging.info("Pagamento %s recebido no webhook com status %s.", payment_id, pagamento.get("status"))
            return False

        pedido = obter_pedido_por_pagamento(payment_id, pagamento.get("external_reference"))
        if not pedido:
            logging.warning("Pagamento aprovado sem pedido pendente: %s", payment_id)
            return False

        return processar_pagamento_aprovado_sync(pedido, pagamento, origem=origem)
    except Exception as exc:
        logging.exception("Erro ao processar notificação Mercado Pago: %s", limpar_erro_api(exc))
        return False

def extrair_payment_id_webhook(dados: dict) -> str | None:
    candidatos = [
        dados.get("id"),
        dados.get("data", {}).get("id") if isinstance(dados.get("data"), dict) else None,
        dados.get("resource"),
        request.args.get("id") if request else None,
        request.args.get("data.id") if request else None,
    ]
    for item in candidatos:
        if item is None:
            continue
        texto = str(item).strip()
        match = re.search(r"(\d+)$", texto)
        if match:
            return match.group(1)
    return None


def criar_flask_app():
    if Flask is None:
        return None

    web_app = Flask(__name__)

    @web_app.get("/")
    def home():
        return "TW Store Bot online", 200

    @web_app.get("/health")
    def health():
        return jsonify({"ok": True})

    @web_app.route("/webhook/mercadopago", methods=["GET", "POST"])
    def webhook_mercado_pago():
        if request.method == "GET":
            return jsonify({"ok": True, "route": "/webhook/mercadopago"})

        if MP_WEBHOOK_SECRET:
            segredo_recebido = request.args.get("secret") or request.headers.get("X-Webhook-Secret")
            if segredo_recebido != MP_WEBHOOK_SECRET:
                return jsonify({"ok": False, "error": "unauthorized"}), 401

        dados = request.get_json(silent=True) or {}
        payment_id = extrair_payment_id_webhook(dados)
        if not payment_id:
            logging.info("Webhook Mercado Pago sem payment_id. Dados: %s Args: %s", dados, dict(request.args))
            return jsonify({"ok": True, "ignored": "payment_id_not_found"})

        if pagamento_ja_processado(payment_id):
            return jsonify({"ok": True, "ignored": "already_processed", "payment_id": payment_id})

        thread = threading.Thread(
            target=processar_notificacao_mercado_pago_sync,
            args=(payment_id, "webhook"),
            daemon=True,
        )
        thread.start()

        # O Mercado Pago espera HTTP 200/201 rapidamente. O processamento pesado
        # segue em segundo plano para evitar reenvios por timeout.
        return jsonify({"ok": True, "received": True, "payment_id": payment_id})

    return web_app


def iniciar_servidor_web():
    web_app = criar_flask_app()
    if web_app is None:
        logging.warning("Flask não instalado. Webhook Mercado Pago indisponível.")
        return

    try:
        port = int(os.getenv("PORT", "8080"))
    except ValueError:
        port = 8080

    def run():
        web_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    logging.info("Servidor webhook iniciado na porta %s", port)


def chave_env_service_id(catalogo: str, servico_chave: str) -> str:
    bruto = f"PANEL_SERVICE_ID_{catalogo}_{servico_chave}".upper()
    return re.sub(r"[^A-Z0-9]+", "_", bruto).strip("_")


def quantidade_para_api(valor) -> int:
    texto = str(valor or "").strip()
    texto = texto.replace(".", "").replace(",", "")
    numeros = re.sub(r"[^0-9]", "", texto)
    if not numeros:
        raise PlataformaAPIConfigError("Quantidade do pedido não encontrada para envio à plataforma.")
    return int(numeros)


def obter_service_id_api(pedido: dict) -> str:
    service_id = str(pedido.get("api_service_id") or "").strip()
    if service_id and service_id.lower() not in ("none", "null", "0"):
        return service_id

    catalogo = str(pedido.get("catalogo") or "").strip()
    servico_chave = str(pedido.get("servico_chave") or "").strip()
    if catalogo and servico_chave:
        env_name = chave_env_service_id(catalogo, servico_chave)
        service_id = os.getenv(env_name, "").strip()
        if service_id:
            return service_id

    raise PlataformaAPIConfigError(
        "Service ID da plataforma não configurado. "
        "Preencha api_service_id no catalogo.json ou use a variável "
        f"{chave_env_service_id(catalogo, servico_chave)} no .env."
    )


def extrair_order_id(resultado) -> str:
    if isinstance(resultado, dict):
        for chave in ("order", "order_id", "id"):
            if resultado.get(chave) is not None:
                return str(resultado[chave])
    return ""


def criar_pedido_plataforma_sync(pedido: dict) -> dict:
    if pedido.get("catalogo") not in CATALOGOS_COM_ENVIO_API:
        return {"skipped": True}

    if not PANEL_API_URL:
        raise PlataformaAPIConfigError("PANEL_API_URL não configurada no .env.")
    if not PANEL_API_KEY:
        raise PlataformaAPIConfigError("PANEL_API_KEY não configurada no .env.")

    service_id = obter_service_id_api(pedido)
    quantidade = quantidade_para_api(pedido.get("quantidade_api") or pedido.get("quantidade"))
    link = str(pedido.get("link") or "").strip()
    if not link:
        raise PlataformaAPIConfigError("Link/@ não encontrado no pedido.")

    payload = {
        "key": PANEL_API_KEY,
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantidade,
    }

    try:
        resposta = requests.post(PANEL_API_URL, data=payload, timeout=PANEL_API_TIMEOUT)
    except requests.RequestException as exc:
        raise PlataformaAPIRequestError(f"Falha de conexão com a plataforma: {limpar_erro_api(exc)}") from exc

    try:
        resultado = resposta.json()
    except ValueError:
        resultado = {"raw": resposta.text[:500]}

    if not resposta.ok:
        raise PlataformaAPIRequestError(
            f"A plataforma respondeu HTTP {resposta.status_code}: {limpar_erro_api(resultado)}"
        )

    if isinstance(resultado, dict) and resultado.get("error"):
        raise PlataformaAPIRequestError(f"Erro retornado pela plataforma: {limpar_erro_api(resultado.get('error'))}")

    return {
        "service_id": service_id,
        "quantity": quantidade,
        "response": resultado,
        "order_id": extrair_order_id(resultado),
    }


def consultar_status_pedido_plataforma_sync(order_id: str) -> dict:
    order_id = normalizar_id_consulta(order_id)
    if not order_id:
        raise PlataformaAPIConfigError("ID do pedido não informado.")
    if not PANEL_API_URL:
        raise PlataformaAPIConfigError("PANEL_API_URL não configurada no .env.")
    if not PANEL_API_KEY:
        raise PlataformaAPIConfigError("PANEL_API_KEY não configurada no .env.")

    payload = {
        "key": PANEL_API_KEY,
        "action": "status",
        "order": order_id,
    }

    try:
        resposta = requests.post(PANEL_API_URL, data=payload, timeout=PANEL_API_TIMEOUT)
    except requests.RequestException as exc:
        raise PlataformaAPIRequestError(f"Falha de conexão com a plataforma: {limpar_erro_api(exc)}") from exc

    try:
        resultado = resposta.json()
    except ValueError:
        resultado = {"raw": resposta.text[:500]}

    if not resposta.ok:
        raise PlataformaAPIRequestError(
            f"A plataforma respondeu HTTP {resposta.status_code}: {limpar_erro_api(resultado)}"
        )

    if isinstance(resultado, dict) and resultado.get("error"):
        raise PlataformaAPIRequestError(f"Erro retornado pela plataforma: {limpar_erro_api(resultado.get('error'))}")

    return resultado if isinstance(resultado, dict) else {"raw": resultado}


def solicitar_refil_pedido_plataforma_sync(order_id: str) -> dict:
    order_id = normalizar_id_consulta(order_id)
    if not order_id:
        raise PlataformaAPIConfigError("ID do pedido não informado.")
    if not PANEL_API_URL:
        raise PlataformaAPIConfigError("PANEL_API_URL não configurada no .env.")
    if not PANEL_API_KEY:
        raise PlataformaAPIConfigError("PANEL_API_KEY não configurada no .env.")

    payload = {
        "key": PANEL_API_KEY,
        "action": "refill",
        "order": order_id,
    }

    try:
        resposta = requests.post(PANEL_API_URL, data=payload, timeout=PANEL_API_TIMEOUT)
    except requests.RequestException as exc:
        raise PlataformaAPIRequestError(f"Falha de conexão com a plataforma: {limpar_erro_api(exc)}") from exc

    try:
        resultado = resposta.json()
    except ValueError:
        resultado = {"raw": resposta.text[:500]}

    if not resposta.ok:
        raise PlataformaAPIRequestError(
            f"A plataforma respondeu HTTP {resposta.status_code}: {limpar_erro_api(resultado)}"
        )

    if isinstance(resultado, dict) and resultado.get("error"):
        raise PlataformaAPIRequestError(f"Reposição/refil indisponível: {limpar_erro_api(resultado.get('error'))}")

    return resultado if isinstance(resultado, dict) else {"raw": resultado}


STATUS_PLATAFORMA_PT = {
    "pending": "Pendente",
    "in progress": "Em andamento",
    "inprogress": "Em andamento",
    "processing": "Processando",
    "completed": "Concluído",
    "complete": "Concluído",
    "partial": "Parcial",
    "canceled": "Cancelado",
    "cancelled": "Cancelado",
}


def traduzir_status_plataforma(status) -> str:
    texto = str(status or "desconhecido").strip()
    return STATUS_PLATAFORMA_PT.get(texto.lower(), texto or "desconhecido")


def traduzir_status_local(status) -> str:
    mapa = {
        "aguardando_link": "Aguardando link/@ do cliente",
        "aguardando_email_iptv": "Aguardando e-mail do cliente",
        "aguardando_pagamento": "Aguardando pagamento",
        "aguardando_aprovacao_admin": "Comprovante em análise",
        "pagamento_aprovado": "Pagamento aprovado",
        "comprovante_reprovado": "Comprovante reprovado",
    }
    texto = str(status or "").strip()
    return mapa.get(texto, texto or "Não informado")


def texto_status_pedido_local(pedido: dict, origem: str | None = None) -> str:
    plataforma_id = pedido.get("plataforma_order_id")
    status_api = pedido.get("plataforma_api_status")
    linhas = [
        "🔎 *Consulta do pedido*",
        "",
        f"🆔 *ID do pedido:* `{md(pedido.get('pedido_id', ''))}`",
        f"📌 *Status:* {md(traduzir_status_local(pedido.get('status')))}",
    ]

    if pedido.get("catalogo"):
        linhas.append(f"🗂️ *Catálogo:* {md(pedido.get('catalogo'))}")
    if pedido.get("servico"):
        linhas.append(f"🛒 *Serviço:* {md(pedido.get('servico'))}")
    if pedido.get("quantidade"):
        linhas.append(f"🔢 *Quantidade:* {md(pedido.get('quantidade'))}")
    if pedido_tem_id_plataforma(plataforma_id):
        linhas.append(f"🚀 *ID na plataforma:* `{md(plataforma_id)}`")
    if status_api:
        linhas.append(f"📡 *Envio para plataforma:* {md(status_api)}")
    if pedido.get("plataforma_api_erro"):
        linhas.append(f"⚠️ *Erro no envio:* {md(pedido.get('plataforma_api_erro'))}")

    if origem == "pendente":
        linhas.extend([
            "",
            "Esse pedido ainda está no fluxo interno do bot. Quando for enviado para a plataforma, o status da plataforma aparecerá aqui.",
        ])

    return "\n".join(linhas)


def texto_status_pedido_plataforma(order_id: str, resultado: dict, pedido_local: dict | None = None) -> str:
    status = resultado.get("status") or resultado.get("Status") or resultado.get("state") or resultado.get("raw") or "desconhecido"
    linhas = [
        "🔎 *Consulta do pedido na plataforma*",
        "",
    ]

    if pedido_local and pedido_local.get("pedido_id"):
        linhas.append(f"🆔 *ID do pedido no bot:* `{md(pedido_local.get('pedido_id'))}`")

    linhas.extend([
        f"🚀 *ID na plataforma:* `{md(order_id)}`",
        f"📌 *Status:* {md(traduzir_status_plataforma(status))}",
    ])

    campos = [
        ("start_count", "📈 *Contagem inicial*"),
        ("remains", "⏳ *Restante*"),
    ]
    for chave, rotulo in campos:
        valor = resultado.get(chave)
        if valor not in (None, ""):
            linhas.append(f"{rotulo}: {md(valor)}")

    if pedido_local:
        if pedido_local.get("catalogo"):
            linhas.append(f"🗂️ *Catálogo:* {md(pedido_local.get('catalogo'))}")
        if pedido_local.get("servico"):
            linhas.append(f"🛒 *Serviço:* {md(pedido_local.get('servico'))}")
        if pedido_local.get("quantidade"):
            linhas.append(f"🔢 *Quantidade:* {md(pedido_local.get('quantidade'))}")

    linhas.extend([
        "",
        "Status consultado diretamente na plataforma.",
    ])
    return "\n".join(linhas)


def extrair_refil_id(resultado: dict) -> str:
    if not isinstance(resultado, dict):
        return ""
    for chave in ("refill", "refill_id", "id", "order"):
        valor = resultado.get(chave)
        if valor not in (None, ""):
            return str(valor)
    return ""


def texto_refil_solicitado(order_id: str, resultado: dict) -> str:
    refil_id = extrair_refil_id(resultado)
    linhas = [
        "🔁 *Reposição/refil solicitado*",
        "",
        f"🚀 *ID do pedido na plataforma:* `{md(order_id)}`",
    ]
    if refil_id:
        linhas.append(f"🧾 *ID da solicitação:* `{md(refil_id)}`")
    linhas.extend([
        "",
        "✅ A solicitação foi enviada para a plataforma.",
        "Acompanhe o andamento pelo botão *Consultar Pedido* usando o mesmo ID.",
    ])
    return "\n".join(linhas)


def obter_order_id_para_refil(consulta_id: str) -> tuple[str | None, dict | None, str | None]:
    consulta_id = normalizar_id_consulta(consulta_id)
    pedido_local, origem = buscar_pedido_local_por_id(consulta_id)

    if pedido_local and pedido_tem_id_plataforma(pedido_local.get("plataforma_order_id")):
        return str(pedido_local.get("plataforma_order_id")), pedido_local, origem

    if consulta_id.isdigit() and pedido_tem_id_plataforma(consulta_id):
        return consulta_id, pedido_local, origem

    return None, pedido_local, origem


def botoes_consulta_pedido(plataforma_order_id: str | None = None) -> InlineKeyboardMarkup:
    keyboard = []
    if pedido_tem_id_plataforma(plataforma_order_id):
        order_id = str(plataforma_order_id)
        # O Telegram limita callback_data a 64 bytes. IDs comuns de painel são curtos;
        # se vier um ID grande, o cliente informa manualmente pelo submenu de refil.
        if len(f"pedido:refil:{order_id}".encode("utf-8")) <= 64:
            keyboard.append([btn("🔁 Solicitar reposição/refil", f"pedido:refil:{order_id}")])
        else:
            keyboard.append([btn("🔁 Solicitar reposição/refil", "pedido:solicitar_refil")])
    keyboard.append([btn("🔎 Consultar outro pedido", "pedido:consultar_status")])
    keyboard.append([btn("🏠 Menu inicial", "voltar:inicio")])
    return InlineKeyboardMarkup(keyboard)


def menu_consultar_pedido() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("🔎 Ver status do pedido", "pedido:consultar_status")],
        [btn("🔁 Solicitar reposição/refil", "pedido:solicitar_refil")],
        [btn("⬅️ Voltar", "voltar:inicio")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def enviar_pedido_para_plataforma(pedido: dict):
    if pedido.get("catalogo") not in CATALOGOS_COM_ENVIO_API:
        return

    try:
        resultado = await asyncio.to_thread(criar_pedido_plataforma_sync, pedido)
    except (PlataformaAPIConfigError, PlataformaAPIRequestError) as exc:
        pedido["plataforma_api_status"] = "erro"
        pedido["plataforma_api_erro"] = limpar_erro_api(exc)
        return
    except Exception as exc:
        pedido["plataforma_api_status"] = "erro"
        pedido["plataforma_api_erro"] = limpar_erro_api(f"Erro inesperado: {exc}")
        return

    pedido["plataforma_api_status"] = "enviado"
    pedido["plataforma_service_id"] = resultado.get("service_id")
    pedido["plataforma_quantidade"] = resultado.get("quantity")
    pedido["plataforma_order_id"] = resultado.get("order_id") or "Não informado"
    pedido["plataforma_resposta"] = resultado.get("response")


def btn(texto: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(texto, callback_data=data)


def menu_principal() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("🎯 Catálogo de Serviços", "menu:catalogo")],
        [btn("🔎 Consultar Pedido", "pedido:consultar")],
        [btn("💬 Falar com Atendimento", "extra:atendimento")],
        [btn("📦 Como Fazer Pedido", "extra:como_fazer_pedido")],
            ]
    return InlineKeyboardMarkup(keyboard)


def menu_catalogos() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("📦 Instagram", "catalogo:instagram")],
        [btn("📦 TikTok", "catalogo:tiktok")],
        [btn("📦 IPTV Livestream 4K", "catalogo:iptv")],
        [btn("📶 Internet Ilimitada", "catalogo:internet")],
        [btn("⬅️ Voltar", "voltar:inicio")],
    ]
    return InlineKeyboardMarkup(keyboard)


def menu_instagram() -> InlineKeyboardMarkup:
    servicos = CATALOGO["catalogos"]["instagram"]["servicos"]
    keyboard = []
    for chave, servico in servicos.items():
        keyboard.append([btn(servico["nome"], f"servico:{chave}")])
    keyboard.append([btn("⬅️ Voltar", "menu:catalogo")])
    return InlineKeyboardMarkup(keyboard)


def menu_tiktok() -> InlineKeyboardMarkup:
    servicos = CATALOGO["catalogos"]["tiktok"]["servicos"]
    keyboard = []
    for chave, servico in servicos.items():
        keyboard.append([btn(servico["nome"], f"servico_tiktok:{chave}")])
    keyboard.append([btn("⬅️ Voltar", "menu:catalogo")])
    return InlineKeyboardMarkup(keyboard)


QTD_MINIMA_PEDIDO_API = 100
QTD_MAXIMA_PEDIDO_API = 10000


def formatar_quantidade(quantidade: int) -> str:
    return f"{int(quantidade):,}".replace(",", ".")


def quantidade_manual_para_int(texto: str) -> int | None:
    numeros = re.sub(r"[^0-9]", "", str(texto or ""))
    if not numeros:
        return None
    try:
        return int(numeros)
    except ValueError:
        return None


def margem_percentual_por_quantidade(quantidade: int) -> int:
    quantidade = int(quantidade)
    if 100 <= quantidade <= 400:
        return 80
    if 401 <= quantidade <= 1000:
        return 50
    if 1001 <= quantidade <= 2000:
        return 65
    if 2001 <= quantidade <= 5000:
        return 45
    if 5001 <= quantidade <= 10000:
        return 35
    raise ValueError("Quantidade fora da faixa permitida")


def catalogo_nome_por_chave(catalogo_chave: str) -> str:
    return "TikTok" if catalogo_chave == "tiktok" else "Instagram"


def obter_servico_por_chave(catalogo_chave: str, servico_chave: str) -> dict:
    return CATALOGO["catalogos"][catalogo_chave]["servicos"][servico_chave]


def obter_item_exato(catalogo_chave: str, servico_chave: str, quantidade: int) -> dict | None:
    servico = obter_servico_por_chave(catalogo_chave, servico_chave)
    for item in servico.get("itens", []):
        if int(item.get("quantidade", 0)) == int(quantidade):
            return item
    return None


def custo_plataforma_centavos(catalogo_chave: str, servico_chave: str, quantidade: int) -> int:
    """Calcula o custo base da plataforma usando a tabela atual do catálogo.

    Quando a quantidade existe exatamente no catálogo, usa aquele valor.
    Quando o cliente informa uma quantidade quebrada, calcula proporcionalmente
    pelo pacote mais próximo abaixo. Se não existir pacote abaixo, usa o primeiro acima.
    """
    servico = obter_servico_por_chave(catalogo_chave, servico_chave)
    itens_validos = []
    for item in servico.get("itens", []):
        qtd_item = int(item.get("quantidade", 0) or 0)
        valor_centavos = valor_para_centavos(item.get("valor", "0"))
        if qtd_item > 0 and valor_centavos > 0:
            itens_validos.append((qtd_item, valor_centavos))

    if not itens_validos:
        raise ValueError("Nenhum valor base encontrado no catálogo para esse serviço.")

    itens_validos.sort(key=lambda item: item[0])

    for qtd_item, valor_centavos in itens_validos:
        if qtd_item == quantidade:
            return valor_centavos

    menores_ou_iguais = [item for item in itens_validos if item[0] <= quantidade]
    qtd_ref, valor_ref = menores_ou_iguais[-1] if menores_ou_iguais else itens_validos[0]
    return (valor_ref * int(quantidade) + qtd_ref - 1) // qtd_ref


def calcular_valor_cliente_centavos(catalogo_chave: str, servico_chave: str, quantidade: int) -> tuple[int, int, int]:
    custo_centavos = custo_plataforma_centavos(catalogo_chave, servico_chave, quantidade)
    margem = margem_percentual_por_quantidade(quantidade)
    valor_cliente = (custo_centavos * (100 + margem) + 99) // 100
    return custo_centavos, margem, valor_cliente


def texto_solicitar_quantidade(catalogo_chave: str, servico_chave: str) -> str:
    servico = obter_servico_por_chave(catalogo_chave, servico_chave)
    return (
        f"{servico.get('mensagem', '').strip()}\n\n"
        "🔢 *Informe a quantidade desejada*\n\n"
        f"Envie uma quantidade de *{formatar_quantidade(QTD_MINIMA_PEDIDO_API)}* até "
        f"*{formatar_quantidade(QTD_MAXIMA_PEDIDO_API)}*.\n\n"
        "Exemplo: `500`, `1500` ou `10000`.\n\n"
        "O valor será calculado automaticamente conforme a quantidade informada."
    )


def menu_voltar_quantidade(catalogo_chave: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("⬅️ Voltar", f"catalogo:{catalogo_chave}")]])


def texto_pedir_link_pedido(servico_nome: str, quantidade: int, valor_cliente: str) -> str:
    return (
        f"Você selecionou *{formatar_quantidade(quantidade)} {servico_nome}*.\n\n"
        f"💰 *Valor do pedido:* R$ {md(valor_cliente)}\n\n"
        "*Informações*\n\n"
        "*Início:* 0 a 2 horas após a confirmação de pagamento.\n\n"
        "*Proteção:* Entrega gradual/drip-feed para não acionar o algoritmo.\n\n"
        "*Necessário:* Para prosseguir com seu pedido, envie abaixo o link do perfil, vídeo ou @ informado pelo cliente. "
        "O perfil precisa estar público para ser encontrado. Se estiver privado, peça para deixar público até a conclusão do pedido.\n\n"
        "Depois que você enviar o link/@, o bot vai mostrar a etapa de pagamento."
    )


def preparar_pedido_api_manual(update: Update, catalogo_chave: str, servico_chave: str, quantidade: int) -> dict:
    servico = obter_servico_por_chave(catalogo_chave, servico_chave)
    item_exato = obter_item_exato(catalogo_chave, servico_chave, quantidade) or {}
    custo_centavos, margem, valor_cliente_centavos = calcular_valor_cliente_centavos(catalogo_chave, servico_chave, quantidade)

    return preparar_pedido({
        "catalogo": catalogo_nome_por_chave(catalogo_chave),
        "servico_chave": servico_chave,
        "servico": servico["nome"],
        "quantidade": formatar_quantidade(quantidade),
        "quantidade_api": int(quantidade),
        "api_service_id": item_exato.get("api_service_id") or servico.get("api_service_id"),
        "valor": centavos_para_moeda(valor_cliente_centavos),
        "valor_plataforma": centavos_para_moeda(custo_centavos),
        "margem_percentual": f"{margem}%",
        "link": None,
        "status": "aguardando_link",
        "usuario": update.effective_user.full_name,
        "username": update.effective_user.username,
        "user_id": update.effective_user.id,
    })


async def iniciar_pedido_api_por_quantidade(update: Update, context: ContextTypes.DEFAULT_TYPE, catalogo_chave: str, servico_chave: str, quantidade: int):
    servico = obter_servico_por_chave(catalogo_chave, servico_chave)
    try:
        pedido = preparar_pedido_api_manual(update, catalogo_chave, servico_chave, quantidade)
    except ValueError as exc:
        await safe_edit_or_reply(update, f"⚠️ {md(exc)}", menu_voltar_quantidade(catalogo_chave))
        return

    context.user_data.pop("aguardando_quantidade", None)
    context.user_data["pedido"] = pedido
    await safe_edit_or_reply(
        update,
        texto_pedir_link_pedido(servico["nome"], quantidade, pedido["valor"]),
        InlineKeyboardMarkup([[btn("⬅️ Voltar", f"servico_tiktok:{servico_chave}" if catalogo_chave == "tiktok" else f"servico:{servico_chave}")]]),
    )


async def processar_quantidade_manual(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_usuario: str):
    dados = context.user_data.get("aguardando_quantidade") or {}
    catalogo_chave = dados.get("catalogo_chave")
    servico_chave = dados.get("servico_chave")

    if catalogo_chave not in ("instagram", "tiktok") or not servico_chave:
        context.user_data.pop("aguardando_quantidade", None)
        await update.message.reply_text("Não encontrei o serviço selecionado. Toque em /start para começar novamente.")
        return

    quantidade = quantidade_manual_para_int(texto_usuario)
    if quantidade is None:
        await update.message.reply_text(
            "⚠️ Envie apenas a quantidade em números. Exemplo: `500`.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_voltar_quantidade(catalogo_chave),
        )
        return

    if quantidade < QTD_MINIMA_PEDIDO_API or quantidade > QTD_MAXIMA_PEDIDO_API:
        await update.message.reply_text(
            f"⚠️ Quantidade inválida. Envie um número de *{formatar_quantidade(QTD_MINIMA_PEDIDO_API)}* até *{formatar_quantidade(QTD_MAXIMA_PEDIDO_API)}*.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_voltar_quantidade(catalogo_chave),
        )
        return

    await iniciar_pedido_api_por_quantidade(update, context, catalogo_chave, servico_chave, quantidade)


def menu_itens_tiktok(servico_chave: str) -> InlineKeyboardMarkup:
    return menu_voltar_quantidade("tiktok")


def get_item_tiktok(servico_chave: str, quantidade: int) -> dict:
    item = obter_item_exato("tiktok", servico_chave, quantidade)
    if item:
        return item
    raise KeyError("Item não encontrado")


def menu_iptv() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [btn("1 mês — R$ 15,00", "item_iptv:1mes:1")],
            [btn("⬅️ Voltar", "menu:catalogo")],
        ]
    )


def botoes_confirmar_email_iptv() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [btn("✅ Confirmar e ir para pagamento", "confirmar_email_iptv")],
            [btn("✏️ Alterar e-mail", "alterar_email_iptv")],
            [btn("🏠 Cancelar / Menu", "voltar:inicio")],
        ]
    )


def menu_itens(servico_chave: str) -> InlineKeyboardMarkup:
    return menu_voltar_quantidade("instagram")


def get_item(servico_chave: str, quantidade: int) -> dict:
    item = obter_item_exato("instagram", servico_chave, quantidade)
    if item:
        return item
    raise KeyError("Item não encontrado")


def texto_pagamento(pedido: dict) -> str:
    """Monta a aba de pagamento usando Pix dinâmico do Mercado Pago quando disponível."""
    if pedido.get("mp_qr_code"):
        ticket = pedido.get("mp_ticket_url")
        extra = f"\n🔗 *Link do pagamento:* {md(ticket)}\n" if ticket else ""
        return (
            "💳 *Pagamento Pix automático*\n\n"
            "Confira os dados e pague pelo Pix copia e cola.\n"
            "Depois do pagamento, o bot confirma automaticamente pelo Mercado Pago.\n"
            "Não precisa enviar comprovante.\n\n"
            f"*Valor exato:* R$ {md(pedido['valor'])}\n"
            f"*ID do pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
            f"*ID Mercado Pago:* `{md(pedido.get('mp_payment_id', ''))}`\n"
            f"{extra}\n"
            "🧾 *Resumo do pedido*\n"
            f"• Catálogo: {md(pedido['catalogo'])}\n"
            f"• Serviço: {md(pedido['servico'])}\n"
            f"• Quantidade: {md(pedido['quantidade'])}\n"
            f"• Link/@ enviado: {md(pedido['link'])}\n\n"
            "Toque no botão abaixo para copiar o Pix. Após pagar, aguarde a confirmação automática."
        )

    return (
        "💳 *Pagamento e Finalização*\n\n"
        "Confira os dados antes de pagar. O pedido só será liberado depois da validação do comprovante.\n\n"
        "*Dados do Pix:*\n"
        f"( 🔑 ) `{md(PIX_CHAVE)}`\n\n"
        f"*Valor exato:* R$ {md(pedido['valor'])}\n"
        f"*ID do pedido:* `{md(pedido.get('pedido_id', ''))}`\n\n"
        "🧾 *Resumo do pedido*\n"
        f"• Catálogo: {md(pedido['catalogo'])}\n"
        f"• Serviço: {md(pedido['servico'])}\n"
        f"• Quantidade: {md(pedido['quantidade'])}\n"
        f"• Link/@ enviado: {md(pedido['link'])}\n\n"
        "Após realizar o pagamento, envie o comprovante em imagem aqui na conversa.\n"
        "O bot vai enviar para validação e só libera o pedido depois da aprovação."
    )


def fonte_pagamento(tamanho: int, negrito: bool = False):
    """Carrega uma fonte do sistema para gerar a arte de pagamento."""
    if ImageFont is None:
        return None

    candidatos = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if negrito else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if negrito else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if negrito else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for caminho in candidatos:
        if os.path.exists(caminho):
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default()


def texto_largura(draw, texto: str, fonte) -> int:
    bbox = draw.textbbox((0, 0), texto, font=fonte)
    return bbox[2] - bbox[0]


def normalizar_link_para_exibicao(link: str) -> str:
    texto = str(link or "").strip()
    if not texto:
        return ""

    if texto.startswith("@"):
        return texto

    match = re.search(r"instagram\.com/([A-Za-z0-9._]+)", texto, flags=re.IGNORECASE)
    if match:
        usuario = match.group(1).strip().strip("/")
        if usuario:
            return f"@{usuario}"

    match = re.search(r"tiktok\.com/@?([A-Za-z0-9._]+)", texto, flags=re.IGNORECASE)
    if match:
        usuario = match.group(1).strip().strip("/")
        if usuario:
            return f"@{usuario}"

    return texto


def quebrar_texto_inteligente(draw, texto: str, fonte, largura_max: int) -> list[str]:
    texto = str(texto or "").strip()
    if not texto:
        return [""]

    palavras = texto.split()
    if len(palavras) <= 1:
        if texto_largura(draw, texto, fonte) <= largura_max:
            return [texto]
        partes = []
        atual = ""
        for ch in texto:
            teste = atual + ch
            if atual and texto_largura(draw, teste, fonte) > largura_max:
                partes.append(atual)
                atual = ch
            else:
                atual = teste
        if atual:
            partes.append(atual)
        return partes or [texto]

    linhas = []
    linha = palavras[0]
    for palavra in palavras[1:]:
        teste = f"{linha} {palavra}"
        if texto_largura(draw, teste, fonte) <= largura_max:
            linha = teste
        else:
            linhas.append(linha)
            linha = palavra
    linhas.append(linha)
    return linhas


def ajustar_fonte_e_linhas(draw, texto: str, caixa, tamanho_max: int, tamanho_min: int = 18, negrito: bool = True, max_linhas: int = 1):
    x1, y1, x2, y2 = caixa
    largura_max = max(10, x2 - x1 - 12)
    altura_max = max(10, y2 - y1 - 8)

    for tamanho in range(tamanho_max, tamanho_min - 1, -1):
        fonte = fonte_pagamento(tamanho, negrito)
        linhas = quebrar_texto_inteligente(draw, texto, fonte, largura_max)
        if len(linhas) > max_linhas:
            continue

        alturas = []
        for linha in linhas:
            bbox = draw.textbbox((0, 0), linha, font=fonte)
            alturas.append(bbox[3] - bbox[1])
        altura_total = sum(alturas) + (len(linhas) - 1) * 4
        if altura_total <= altura_max:
            return fonte, linhas

    fonte = fonte_pagamento(tamanho_min, negrito)
    linhas = quebrar_texto_inteligente(draw, texto, fonte, largura_max)[:max_linhas]

    if linhas:
        ultima = linhas[-1]
        while ultima:
            teste = ultima + "…"
            if texto_largura(draw, teste, fonte) <= largura_max:
                linhas[-1] = teste
                break
            ultima = ultima[:-1]
        else:
            linhas[-1] = ""

    return fonte, linhas


def gerar_imagem_pagamento_instagram(pedido: dict) -> BytesIO | None:
    """Preenche o layout original enviado pelo cliente com os dados variáveis do pedido."""
    if Image is None or ImageDraw is None or ImageFont is None:
        return None
    if not PAGAMENTO_INSTAGRAM_LAYOUT_PATH.exists():
        return None

    img = Image.open(PAGAMENTO_INSTAGRAM_LAYOUT_PATH).convert("RGB")
    draw = ImageDraw.Draw(img)

    largura, altura = img.size
    sx = largura / 1024
    sy = altura / 1536

    def escala_caixa(caixa):
        x1, y1, x2, y2 = caixa
        return (
            int(x1 * sx),
            int(y1 * sy),
            int(x2 * sx),
            int(y2 * sy),
        )

    def escrever_caixa(texto: str, caixa_base, tamanho_max: int, tamanho_min: int = 22, cor=(255, 255, 255), negrito: bool = True, max_linhas: int = 1, align: str = "center"):
        caixa = escala_caixa(caixa_base)
        x1, y1, x2, y2 = caixa
        fonte, linhas = ajustar_fonte_e_linhas(
            draw,
            str(texto or "").strip(),
            caixa,
            max(12, int(tamanho_max * min(sx, sy))),
            max(10, int(tamanho_min * min(sx, sy))),
            negrito=negrito,
            max_linhas=max_linhas,
        )

        metricas = []
        for linha in linhas:
            bbox = draw.textbbox((0, 0), linha, font=fonte)
            metricas.append((linha, bbox, bbox[2] - bbox[0], bbox[3] - bbox[1]))

        altura_total = sum(m[3] for m in metricas) + max(0, len(metricas) - 1) * 4
        y = y1 + ((y2 - y1) - altura_total) / 2

        for linha, bbox, tw, th in metricas:
            if align == "left":
                tx = x1 + 10
            else:
                tx = x1 + ((x2 - x1) - tw) / 2
            ty = y - bbox[1]
            draw.text(
                (tx, ty),
                linha,
                font=fonte,
                fill=cor,
                stroke_width=1,
                stroke_fill=(0, 0, 0),
            )
            y += th + 4

    def apagar_area(caixa_base, margem=0):
        caixa = escala_caixa(caixa_base)
        x1, y1, x2, y2 = caixa
        m = int(margem * min(sx, sy))
        draw.rectangle([x1 - m, y1 - m, x2 + m, y2 + m], fill=(0, 0, 0))

    valor = str(pedido.get("valor", "0,00")).replace("R$", "").strip()
    catalogo = str(pedido.get("catalogo", "Instagram")).strip() or "Instagram"
    servico = str(pedido.get("servico", "")).strip()
    quantidade = str(pedido.get("quantidade", "")).strip()
    link = normalizar_link_para_exibicao(pedido.get("link", ""))

    # Campos dinâmicos em fonte maior e mais visível.
    # As caixas foram alargadas para o texto não encolher demais no Telegram.
    escrever_caixa(f"R$ {valor}", (255, 586, 615, 724), 90, 54, cor=(255, 255, 255), negrito=True, max_linhas=1)
    escrever_caixa(catalogo, (275, 850, 705, 980), 90, 54, cor=(255, 255, 255), negrito=True, max_linhas=1)
    escrever_caixa(servico, (275, 940, 705, 1072), 90, 50, cor=(255, 255, 255), negrito=True, max_linhas=2)
    escrever_caixa(quantidade, (275, 1040, 705, 1170), 90, 54, cor=(255, 255, 255), negrito=True, max_linhas=1)
    escrever_caixa(link, (295, 1134, 705, 1264), 90, 50, cor=(255, 255, 255), negrito=True, max_linhas=2)

    if PIX_CHAVE:
        apagar_area((201, 476, 640, 535), margem=2)
        escrever_caixa(PIX_CHAVE, (192, 458, 648, 552), 56, 30, cor=(255, 255, 255), negrito=True, max_linhas=1)

    arquivo = BytesIO()
    img.save(arquivo, format="PNG", optimize=True)
    arquivo.seek(0)
    arquivo.name = "pagamento_instagram.png"
    return arquivo

def gerar_imagem_pagamento_tiktok(pedido: dict) -> BytesIO | None:
    """Preenche o layout do TikTok com os dados variáveis do pedido."""
    if Image is None or ImageDraw is None or ImageFont is None:
        return None
    if not PAGAMENTO_TIKTOK_LAYOUT_PATH.exists():
        return None

    img = Image.open(PAGAMENTO_TIKTOK_LAYOUT_PATH).convert("RGB")
    draw = ImageDraw.Draw(img)

    largura, altura = img.size
    sx = largura / 1024
    sy = altura / 1536

    def escala_caixa(caixa):
        x1, y1, x2, y2 = caixa
        return (
            int(x1 * sx),
            int(y1 * sy),
            int(x2 * sx),
            int(y2 * sy),
        )

    def escrever_caixa(texto: str, caixa_base, tamanho_max: int, tamanho_min: int = 22, cor=(255, 255, 255), negrito: bool = True, max_linhas: int = 1, align: str = "center"):
        caixa = escala_caixa(caixa_base)
        x1, y1, x2, y2 = caixa
        fonte, linhas = ajustar_fonte_e_linhas(
            draw,
            str(texto or "").strip(),
            caixa,
            max(12, int(tamanho_max * min(sx, sy))),
            max(10, int(tamanho_min * min(sx, sy))),
            negrito=negrito,
            max_linhas=max_linhas,
        )

        metricas = []
        for linha in linhas:
            bbox = draw.textbbox((0, 0), linha, font=fonte)
            metricas.append((linha, bbox, bbox[2] - bbox[0], bbox[3] - bbox[1]))

        altura_total = sum(m[3] for m in metricas) + max(0, len(metricas) - 1) * 4
        y = y1 + ((y2 - y1) - altura_total) / 2

        for linha, bbox, tw, th in metricas:
            if align == "left":
                tx = x1 + 10
            else:
                tx = x1 + ((x2 - x1) - tw) / 2
            ty = y - bbox[1]
            draw.text(
                (tx, ty),
                linha,
                font=fonte,
                fill=cor,
                stroke_width=1,
                stroke_fill=(0, 0, 0),
            )
            y += th + 4

    def apagar_area(caixa_base, margem=0):
        caixa = escala_caixa(caixa_base)
        x1, y1, x2, y2 = caixa
        m = int(margem * min(sx, sy))
        draw.rectangle([x1 - m, y1 - m, x2 + m, y2 + m], fill=(0, 0, 0))

    valor = str(pedido.get("valor", "0,00")).replace("R$", "").strip()
    catalogo = str(pedido.get("catalogo", "TikTok")).strip() or "TikTok"
    servico = str(pedido.get("servico", "")).strip()
    quantidade = str(pedido.get("quantidade", "")).strip()
    link = normalizar_link_para_exibicao(pedido.get("link", ""))

    # Campos dinâmicos em fonte maior e mais visível.
    # As caixas foram alargadas para o texto não encolher demais no Telegram.
    escrever_caixa(f"R$ {valor}", (255, 586, 615, 724), 90, 54, cor=(255, 255, 255), negrito=True, max_linhas=1)
    escrever_caixa(catalogo, (275, 850, 705, 980), 90, 54, cor=(255, 255, 255), negrito=True, max_linhas=1)
    escrever_caixa(servico, (275, 940, 705, 1072), 90, 50, cor=(255, 255, 255), negrito=True, max_linhas=2)
    escrever_caixa(quantidade, (275, 1040, 705, 1170), 90, 54, cor=(255, 255, 255), negrito=True, max_linhas=1)
    escrever_caixa(link, (295, 1134, 705, 1264), 90, 50, cor=(255, 255, 255), negrito=True, max_linhas=2)

    if PIX_CHAVE:
        apagar_area((201, 476, 640, 535), margem=2)
        escrever_caixa(PIX_CHAVE, (192, 458, 648, 552), 56, 30, cor=(255, 255, 255), negrito=True, max_linhas=1)

    arquivo = BytesIO()
    img.save(arquivo, format="PNG", optimize=True)
    arquivo.seek(0)
    arquivo.name = "pagamento_tiktok.png"
    return arquivo


def guardar_mensagem_bot(context: ContextTypes.DEFAULT_TYPE, mensagem):
    if not mensagem:
        return
    context.user_data["ultima_chat_id_bot"] = mensagem.chat_id
    context.user_data["ultima_mensagem_bot_id"] = mensagem.message_id


async def apagar_ultima_mensagem_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.user_data.get("ultima_chat_id_bot") or update.effective_chat.id
    message_id = context.user_data.get("ultima_mensagem_bot_id")
    if not chat_id or not message_id:
        return

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass
    finally:
        context.user_data.pop("ultima_mensagem_bot_id", None)
        context.user_data.pop("ultima_chat_id_bot", None)


async def enviar_texto_sequencial(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    await apagar_ultima_mensagem_bot(update, context)
    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_foto_sequencial(update: Update, context: ContextTypes.DEFAULT_TYPE, photo, reply_markup=None, caption: str | None = None):
    await apagar_ultima_mensagem_bot(update, context)
    mensagem = await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=photo,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN if caption else None,
        reply_markup=reply_markup,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_pagamento_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict):
    """Troca a aba atual pela aba de pagamento, sem empilhar outra mensagem do bot."""
    if mercado_pago_configurado():
        ok, mensagem = await garantir_pagamento_mercado_pago(pedido)
        if not ok:
            await enviar_texto_sequencial(
                update,
                context,
                (
                    "⚠️ Não consegui gerar o Pix automático pelo Mercado Pago.\n\n"
                    f"*Erro:* {md(mensagem)}\n\n"
                    "Verifique se a variável `MERCADO_PAGO_ACCESS_TOKEN` está configurada no Railway."
                ),
                InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
            )
            return

        await enviar_texto_sequencial(update, context, texto_pagamento(pedido), botoes_pagamento(pedido))
        return

    imagem = None
    if pedido.get("catalogo") == "Instagram":
        imagem = gerar_imagem_pagamento_instagram(pedido)
    elif pedido.get("catalogo") == "TikTok":
        imagem = gerar_imagem_pagamento_tiktok(pedido)

    if imagem is not None:
        await enviar_foto_sequencial(update, context, imagem, botoes_pagamento(pedido))
        return

    await enviar_texto_sequencial(update, context, texto_pagamento(pedido), botoes_pagamento(pedido))


def botoes_pagamento(pedido: dict | None = None) -> InlineKeyboardMarkup:
    pix_copia = (pedido or {}).get("mp_qr_code") or PIX_COPIA_COLA or PIX_CHAVE or "PIX_NAO_CONFIGURADO"
    texto_botao = "📋 Copiar Pix copia e cola" if (pedido or {}).get("mp_qr_code") else "📋 Copiar chave Pix"
    keyboard = [
        [InlineKeyboardButton(texto_botao, copy_text=CopyTextButton(pix_copia))],
    ]
    if (pedido or {}).get("mp_payment_id"):
        keyboard.append([btn("🔄 Já paguei / verificar", "verificar_pagamento")])
    keyboard.extend([
        [btn("✏️ Alterar link/@", "alterar_link")],
        [btn("🏠 Cancelar / Menu", "voltar:inicio")],
    ])
    return InlineKeyboardMarkup(keyboard)


def botoes_confirmar_pagamento() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [btn("⏳ Comprovante em análise", "aguardando_aprovacao")],
            [btn("✏️ Alterar link/@", "alterar_link")],
            [btn("🏠 Cancelar / Menu", "voltar:inicio")],
        ]
    )


def botoes_aprovacao_admin(pedido_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [btn("✅ Aprovar e enviar pedido", f"admin_aprovar_pagamento:{pedido_id}")],
            [btn("❌ Reprovar comprovante", f"admin_reprovar_pagamento:{pedido_id}")],
        ]
    )


def texto_pedido_pendente_admin(pedido: dict) -> str:
    username = f'@{pedido["username"]}' if pedido.get("username") else "Sem username"
    return (
        "🧾 *COMPROVANTE AGUARDANDO VALIDAÇÃO*\n\n"
        f"🆔 *Pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
        f"🗂️ *Catálogo:* {md(pedido.get('catalogo', ''))}\n"
        f"📌 *Serviço:* {md(pedido.get('servico', ''))}\n"
        f"🔢 *Quantidade:* {md(pedido.get('quantidade', ''))}\n"
        f"💰 *Valor esperado:* R$ {md(pedido.get('valor', ''))}\n"
        f"🔗 *Link/@:* {md(pedido.get('link', ''))}\n\n"
        f"👤 *Cliente:* {md(pedido.get('usuario', 'Cliente'))}\n"
        f"📱 *Telegram:* {md(username)}\n"
        f"🆔 *ID Telegram:* `{pedido.get('user_id', '')}`\n"
        f"🕒 *Enviado em:* {md(pedido.get('comprovante_recebido_em', ''))}\n\n"
        "Confira se o comprovante é real, se o valor bate e se é deste pedido. "
        "O envio para a plataforma só acontece ao aprovar."
    )


async def enviar_para_aprovacao_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict) -> bool:
    if not ADMIN_CHAT_ID:
        return False

    texto = texto_pedido_pendente_admin(pedido)
    comprovante_file_id = pedido.get("comprovante_file_id")
    markup = botoes_aprovacao_admin(str(pedido.get("pedido_id")))

    if comprovante_file_id:
        try:
            if len(texto) <= 1000:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID,
                    photo=comprovante_file_id,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup,
                )
            else:
                await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=comprovante_file_id)
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )
            return True
        except Exception as exc:
            logging.warning("Falha ao enviar comprovante como foto para aprovação: %s", exc)

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    return True


async def safe_edit_or_reply(update: Update, text: str, reply_markup=None):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        except Exception:
            mensagem = await query.message.reply_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            try:
                await query.message.delete()
            except Exception:
                pass
            return mensagem
    else:
        return await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    mensagem = await update.message.reply_text(
        CATALOGO["mensagens"]["inicio"],
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_principal(),
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)


def texto_final_pedido(pedido: dict) -> str:
    if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
        if pedido.get("plataforma_api_status") == "enviado":
            return (
                "✅ *Pedido confirmado e enviado para a plataforma!*\n\n"
                f"🆔 *ID na plataforma:* `{md(pedido.get('plataforma_order_id', 'Não informado'))}`\n"
                "O administrador também recebeu o relatório do pedido."
            )

        erro = pedido.get("plataforma_api_erro") or "Erro não informado."
        return (
            "✅ *Pagamento confirmado!*\n\n"
            "⚠️ O relatório foi enviado para o administrador, mas o envio automático para a plataforma falhou.\n"
            f"*Motivo:* {md(erro)}"
        )

    return CATALOGO["mensagens"].get("pedido_confirmado") or "✅ Pedido confirmado!"


async def finalizar_pedido_confirmado(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict):
    if not pedido or not pedido.get("link"):
        await safe_edit_or_reply(update, "Não encontrei um pedido completo. Toque em /start para começar novamente.")
        return

    if not pedido.get("comprovante_file_id"):
        await safe_edit_or_reply(update, "Envie primeiro uma imagem do comprovante para liberar a confirmação.")
        return

    if pedido.get("status") != "pagamento_aprovado":
        await safe_edit_or_reply(
            update,
            "⏳ Seu comprovante precisa ser validado antes de liberar o pedido. "
            "A confirmação automática pelo cliente foi bloqueada por segurança.",
        )
        return

    if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
        await enviar_texto_sequencial(
            update,
            context,
            "⏳ Pagamento confirmado. Enviando pedido diretamente para a plataforma...",
        )
        await enviar_pedido_para_plataforma(pedido)

    salvar_pedido_historico(pedido)
    await enviar_relatorio_admin(update, context, pedido)
    await enviar_texto_sequencial(
        update,
        context,
        texto_final_pedido(pedido),
        InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
    )
    context.user_data.clear()


async def verificar_pagamento_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pedido = context.user_data.get("pedido")
    if not pedido or not pedido.get("mp_payment_id"):
        await query.answer("Não encontrei pagamento Mercado Pago neste pedido.", show_alert=True)
        return

    await query.answer("Verificando pagamento...")
    try:
        pagamento = await asyncio.to_thread(consultar_pagamento_mercado_pago_sync, str(pedido.get("mp_payment_id")))
    except Exception as exc:
        await safe_edit_or_reply(update, f"⚠️ Falha ao consultar Mercado Pago: {md(limpar_erro_api(exc))}", botoes_pagamento(pedido))
        return

    if str(pagamento.get("status")) == "approved":
        payment_id = str(pagamento.get("id") or pedido.get("mp_payment_id") or "")
        if payment_id and pagamento_ja_processado(payment_id):
            context.user_data.clear()
            await safe_edit_or_reply(
                update,
                "✅ Pagamento já confirmado e pedido já processado. Verifique a mensagem de confirmação enviada pelo bot.",
                InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
            )
            return

        processado = await asyncio.to_thread(processar_pagamento_aprovado_sync, pedido, pagamento, "verificacao_cliente")
        if processado:
            context.user_data.clear()
            try:
                await query.message.delete()
            except Exception:
                pass
        else:
            await safe_edit_or_reply(update, "⚠️ Pagamento encontrado, mas não foi possível validar valor/referência. Fale com o atendimento.", botoes_pagamento(pedido))
        return

    status = md(pagamento.get("status") or "desconhecido")
    detalhe = md(pagamento.get("status_detail") or "")
    await safe_edit_or_reply(
        update,
        (
            "⏳ *Pagamento ainda não aprovado.*\n\n"
            f"Status Mercado Pago: `{status}`\n"
            f"Detalhe: `{detalhe}`\n\n"
            "Depois de pagar, aguarde alguns segundos e toque em verificar novamente."
        ),
        botoes_pagamento(pedido),
    )


async def aprovar_pagamento_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido_id: str):
    query = update.callback_query
    if not eh_admin(update):
        await query.answer("Apenas o administrador pode aprovar este pedido.", show_alert=True)
        return

    pedido = obter_pedido_pendente(pedido_id)
    if not pedido:
        await query.answer("Pedido pendente não encontrado ou já processado.", show_alert=True)
        return

    file_unique_id = pedido.get("comprovante_unique_id")
    if comprovante_ja_usado(file_unique_id):
        remover_pedido_pendente(pedido_id)
        await query.answer("Este comprovante já foi usado em outro pedido.", show_alert=True)
        await query.message.reply_text(
            f"🚫 Pedido `{md(pedido_id)}` bloqueado: comprovante já utilizado anteriormente.",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            await context.bot.send_message(
                chat_id=pedido.get("user_id"),
                text=(
                    "🚫 Seu comprovante não foi aprovado porque este arquivo já apareceu em outro pedido.\n\n"
                    "Envie um comprovante válido ou fale com o atendimento."
                ),
            )
        except Exception as exc:
            logging.warning("Falha ao avisar cliente sobre comprovante duplicado: %s", exc)
        return

    pedido["status"] = "pagamento_aprovado"
    pedido["aprovado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido["aprovado_por"] = update.effective_user.full_name if update.effective_user else "Administrador"

    await query.answer("Pagamento aprovado. Processando pedido...")
    await query.message.reply_text(
        f"✅ Pagamento do pedido `{md(pedido_id)}` aprovado. Processando envio...",
        parse_mode=ParseMode.MARKDOWN,
    )

    if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
        await enviar_pedido_para_plataforma(pedido)

    salvar_pedido_historico(pedido)
    marcar_comprovante_usado(file_unique_id, pedido)
    remover_pedido_pendente(pedido_id)

    await enviar_relatorio_admin(update, context, pedido)

    try:
        await context.bot.send_message(
            chat_id=pedido.get("user_id"),
            text=texto_final_pedido(pedido),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logging.warning("Falha ao avisar cliente sobre aprovação: %s", exc)


async def reprovar_pagamento_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido_id: str):
    query = update.callback_query
    if not eh_admin(update):
        await query.answer("Apenas o administrador pode reprovar este pedido.", show_alert=True)
        return

    pedido = obter_pedido_pendente(pedido_id)
    if not pedido:
        await query.answer("Pedido pendente não encontrado ou já processado.", show_alert=True)
        return

    pedido["status"] = "comprovante_reprovado"
    pedido["reprovado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido["reprovado_por"] = update.effective_user.full_name if update.effective_user else "Administrador"
    salvar_pedido_historico(pedido)
    remover_pedido_pendente(pedido_id)
    await query.answer("Comprovante reprovado.")
    await query.message.reply_text(
        f"❌ Comprovante do pedido `{md(pedido_id)}` reprovado. O pedido não foi enviado.",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        await context.bot.send_message(
            chat_id=pedido.get("user_id"),
            text=(
                "❌ Seu comprovante não foi aprovado. O pedido não foi enviado.\n\n"
                f"ID do pedido: `{md(pedido_id)}`\n"
                "Verifique se o valor, destinatário e data estão corretos e envie um novo comprovante."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logging.warning("Falha ao avisar cliente sobre reprovação: %s", exc)


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if query and query.message:
        guardar_mensagem_bot(context, query.message)

    if data.startswith("admin_aprovar_pagamento:"):
        pedido_id = data.split(":", 1)[1]
        await aprovar_pagamento_admin(update, context, pedido_id)
        return

    if data.startswith("admin_reprovar_pagamento:"):
        pedido_id = data.split(":", 1)[1]
        await reprovar_pagamento_admin(update, context, pedido_id)
        return

    if data == "aguardando_aprovacao":
        await query.answer("O comprovante já foi enviado para validação. Aguarde a aprovação.", show_alert=True)
        return

    if data == "verificar_pagamento":
        await verificar_pagamento_cliente(update, context)
        return

    if data == "voltar:inicio":
        context.user_data.clear()
        await safe_edit_or_reply(update, CATALOGO["mensagens"]["inicio"], menu_principal())
        return

    if data == "pedido:consultar":
        context.user_data.clear()
        await safe_edit_or_reply(
            update,
            (
                "🔎 *Consultar Pedido*\n\n"
                "Escolha uma opção abaixo."
            ),
            menu_consultar_pedido(),
        )
        return

    if data == "pedido:consultar_status":
        context.user_data.clear()
        context.user_data["consulta_pedido"] = True
        await safe_edit_or_reply(
            update,
            (
                "🔎 *Ver status do pedido*\n\n"
                "Envie o ID do pedido que deseja consultar.\n\n"
                "Pode ser o *ID do pedido do bot* ou o *ID da plataforma*."
            ),
            InlineKeyboardMarkup([[btn("⬅️ Voltar", "pedido:consultar")]]),
        )
        return

    if data == "pedido:solicitar_refil":
        context.user_data.clear()
        context.user_data["refil_pedido"] = True
        await safe_edit_or_reply(
            update,
            (
                "🔁 *Solicitar reposição/refil*\n\n"
                "Envie o ID do pedido que deseja repor/refilar.\n\n"
                "A reposição só será solicitada se o pedido tiver ID na plataforma e se a plataforma permitir refil para esse serviço."
            ),
            InlineKeyboardMarkup([[btn("⬅️ Voltar", "pedido:consultar")]]),
        )
        return

    if data.startswith("pedido:refil:"):
        order_id = data.split(":", 2)[2]
        await processar_solicitacao_refil(update, context, order_id)
        return

    if data == "menu:catalogo":
        context.user_data.clear()
        await safe_edit_or_reply(update, CATALOGO["mensagens"]["catalogo"], menu_catalogos())
        return

    if data.startswith("extra:"):
        extra = data.split(":", 1)[1]
        texto = CATALOGO["menus_extras"][extra]
        keyboard = [[btn("⬅️ Voltar", "voltar:inicio")]]
        if extra == "atendimento":
            keyboard.insert(0, [InlineKeyboardButton("📲 WhatsApp", url="https://wa.me/5512997793285")])
        await safe_edit_or_reply(update, texto, InlineKeyboardMarkup(keyboard))
        return


    if data == "catalogo:instagram":
        context.user_data.clear()
        await safe_edit_or_reply(update, CATALOGO["catalogos"]["instagram"]["mensagem"], menu_instagram())
        return

    if data == "catalogo:tiktok":
        context.user_data.clear()
        await safe_edit_or_reply(update, CATALOGO["catalogos"]["tiktok"]["mensagem"], menu_tiktok())
        return

    if data.startswith("servico_tiktok:"):
        servico_chave = data.split(":", 1)[1]
        context.user_data.clear()
        context.user_data["aguardando_quantidade"] = {
            "catalogo_chave": "tiktok",
            "servico_chave": servico_chave,
        }
        await safe_edit_or_reply(update, texto_solicitar_quantidade("tiktok", servico_chave), menu_voltar_quantidade("tiktok"))
        return

    if data.startswith("item_tiktok:"):
        _, servico_chave, quantidade_str = data.split(":")
        quantidade = int(quantidade_str)
        await iniciar_pedido_api_por_quantidade(update, context, "tiktok", servico_chave, quantidade)
        return

    
    if data == "catalogo:internet":
        await safe_edit_or_reply(
            update,
            CATALOGO["catalogos"]["internet_ilimitada"]["mensagem"],
            InlineKeyboardMarkup([
                [btn("1 mês — R$ 15,00", "internet:1mes")],
                [btn("⬅️ Voltar", "menu:catalogo")]
            ]),
        )
        return

    if data == "internet:1mes":
        context.user_data["pedido"] = preparar_pedido({
            "catalogo": "Internet Ilimitada",
            "servico": "1 mês",
            "quantidade": "1 mês",
            "valor": "15,00",
            "link": None,
            "status": "aguardando_email_iptv",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        })

        await safe_edit_or_reply(
            update,
            "📶 *Internet Ilimitada - 1 mês*\n\n💰 Valor: R$ 15,00\n\nAgora envie o e-mail para ativação do serviço.",
            InlineKeyboardMarkup([[btn("⬅️ Voltar", "catalogo:internet")]]),
        )
        return

    if data == "catalogo:iptv":
        await safe_edit_or_reply(update, CATALOGO["catalogos"]["iptv"]["mensagem"], menu_iptv())
        return

    if data.startswith("item_iptv:"):
        _, servico_chave, quantidade_str = data.split(":")
        servico = CATALOGO["catalogos"]["iptv"]["servicos"][servico_chave]
        item = servico["itens"][0]

        context.user_data["pedido"] = preparar_pedido({
            "catalogo": "IPTV Livestream 4K",
            "servico_chave": servico_chave,
            "servico": servico["nome"],
            "quantidade": item["quantidade_texto"],
            "valor": item["valor"],
            "link": None,
            "status": "aguardando_email_iptv",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        })

        await safe_edit_or_reply(
            update,
            item["mensagem"],
            InlineKeyboardMarkup([[btn("⬅️ Voltar", "catalogo:iptv")]]),
        )
        return

    if data == "alterar_email_iptv":
        pedido = context.user_data.get("pedido")
        if not pedido:
            await safe_edit_or_reply(update, "Não encontrei um pedido em andamento. Toque em /start para começar novamente.")
            return
        if pedido.get("pedido_id"):
            remover_pedido_pendente(str(pedido.get("pedido_id")))
        pedido.pop("comprovante_file_id", None)
        pedido.pop("comprovante_unique_id", None)
        pedido["link"] = None
        pedido["status"] = "aguardando_email_iptv"
        await safe_edit_or_reply(update, "✏️ Envie novamente o e-mail correto para continuar.")
        return

    if data == "confirmar_email_iptv":
        pedido = context.user_data.get("pedido")
        if not pedido or pedido.get("catalogo") not in ("IPTV Livestream 4K", "Internet Ilimitada") or not pedido.get("link"):
            await safe_edit_or_reply(update, "Não encontrei o e-mail do pedido. Envie o e-mail novamente.")
            return
        pedido["status"] = "aguardando_pagamento"
        await enviar_pagamento_cliente(update, context, pedido)
        return

    if data.startswith("servico:"):
        servico_chave = data.split(":", 1)[1]
        context.user_data.clear()
        context.user_data["aguardando_quantidade"] = {
            "catalogo_chave": "instagram",
            "servico_chave": servico_chave,
        }
        await safe_edit_or_reply(update, texto_solicitar_quantidade("instagram", servico_chave), menu_voltar_quantidade("instagram"))
        return

    if data.startswith("item:"):
        _, servico_chave, quantidade_str = data.split(":")
        quantidade = int(quantidade_str)
        await iniciar_pedido_api_por_quantidade(update, context, "instagram", servico_chave, quantidade)
        return

    if data == "alterar_link":
        pedido = context.user_data.get("pedido")
        if not pedido:
            await safe_edit_or_reply(update, "Não encontrei um pedido em andamento. Toque em /start para começar novamente.")
            return
        if pedido.get("pedido_id"):
            remover_pedido_pendente(str(pedido.get("pedido_id")))
        pedido.pop("comprovante_file_id", None)
        pedido.pop("comprovante_unique_id", None)
        pedido["link"] = None
        if pedido.get("catalogo") in ("IPTV Livestream 4K", "Internet Ilimitada"):
            pedido["status"] = "aguardando_email_iptv"
            await enviar_texto_sequencial(update, context, "✏️ Envie novamente o e-mail correto para continuar.")
        else:
            pedido["status"] = "aguardando_link"
            await enviar_texto_sequencial(update, context, "✏️ Envie novamente o link ou @ correto para continuar.")
        return

    if data == "confirmar_pedido":
        pedido = context.user_data.get("pedido")
        await finalizar_pedido_confirmado(update, context, pedido)
        return


async def processar_solicitacao_refil(update: Update, context: ContextTypes.DEFAULT_TYPE, consulta_id: str):
    order_id, pedido_local, origem = obter_order_id_para_refil(consulta_id)

    if not order_id:
        texto = (
            "❌ Não foi possível solicitar reposição/refil para esse ID.\n\n"
            "O pedido precisa ter um *ID na plataforma* para que o refil seja solicitado."
        )
        if pedido_local:
            texto += "\n\n" + texto_status_pedido_local(pedido_local, origem)
        await safe_edit_or_reply(
            update,
            texto,
            InlineKeyboardMarkup([
                [btn("🔁 Tentar outro ID", "pedido:solicitar_refil")],
                [btn("🏠 Menu inicial", "voltar:inicio")],
            ]),
        )
        context.user_data.clear()
        return

    try:
        # Antes de enviar o refil, consulta o status para evitar solicitar em pedido ainda em andamento.
        status_resultado = await asyncio.to_thread(consultar_status_pedido_plataforma_sync, order_id)
        status_atual = str(
            status_resultado.get("status")
            or status_resultado.get("Status")
            or status_resultado.get("state")
            or ""
        ).strip().lower()
        if status_atual in {"pending", "in progress", "inprogress", "processing"}:
            await safe_edit_or_reply(
                update,
                (
                    "⏳ *Reposição/refil ainda não disponível*\n\n"
                    f"🚀 *ID na plataforma:* `{md(order_id)}`\n"
                    f"📌 *Status atual:* {md(traduzir_status_plataforma(status_atual))}\n\n"
                    "Aguarde o pedido finalizar para solicitar reposição/refil."
                ),
                botoes_consulta_pedido(order_id),
            )
            context.user_data.clear()
            return

        resultado = await asyncio.to_thread(solicitar_refil_pedido_plataforma_sync, order_id)

        if pedido_local:
            pedido_local["ultimo_refil_solicitado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
            pedido_local["ultimo_refil_resposta"] = resultado
            refil_id = extrair_refil_id(resultado)
            if refil_id:
                pedido_local["ultimo_refil_id"] = refil_id
            salvar_pedido_historico(pedido_local)

        await safe_edit_or_reply(
            update,
            texto_refil_solicitado(order_id, resultado),
            InlineKeyboardMarkup([
                [btn("🔎 Consultar pedido", "pedido:consultar_status")],
                [btn("🏠 Menu inicial", "voltar:inicio")],
            ]),
        )
        context.user_data.clear()
        return

    except (PlataformaAPIConfigError, PlataformaAPIRequestError) as exc:
        await safe_edit_or_reply(
            update,
            (
                "⚠️ *Reposição/refil indisponível agora*\n\n"
                f"🚀 *ID na plataforma:* `{md(order_id)}`\n"
                f"*Motivo:* {md(limpar_erro_api(exc))}\n\n"
                "Isso pode acontecer quando o serviço não possui refil, o prazo de reposição expirou ou o pedido ainda não está apto."
            ),
            botoes_consulta_pedido(order_id),
        )
        context.user_data.clear()
        return


async def responder_consulta_pedido(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_usuario: str):
    consulta_id = normalizar_id_consulta(texto_usuario)
    if not consulta_id:
        await update.message.reply_text(
            "⚠️ Envie um ID de pedido válido para consultar.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[btn("⬅️ Voltar", "voltar:inicio")]]),
        )
        return

    pedido_local, origem = buscar_pedido_local_por_id(consulta_id)
    plataforma_order_id = None
    if pedido_local and pedido_tem_id_plataforma(pedido_local.get("plataforma_order_id")):
        plataforma_order_id = str(pedido_local.get("plataforma_order_id"))
    elif consulta_id.isdigit() and pedido_tem_id_plataforma(consulta_id):
        plataforma_order_id = consulta_id

    if plataforma_order_id:
        try:
            resultado = await asyncio.to_thread(consultar_status_pedido_plataforma_sync, plataforma_order_id)
            await update.message.reply_text(
                texto_status_pedido_plataforma(plataforma_order_id, resultado, pedido_local),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=botoes_consulta_pedido(plataforma_order_id),
                disable_web_page_preview=True,
            )
            context.user_data.clear()
            return
        except (PlataformaAPIConfigError, PlataformaAPIRequestError) as exc:
            if pedido_local:
                await update.message.reply_text(
                    texto_status_pedido_local(pedido_local, origem)
                    + "\n\n⚠️ Não consegui consultar a plataforma agora.\n"
                    + f"*Motivo:* {md(limpar_erro_api(exc))}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=botoes_consulta_pedido(pedido_local.get("plataforma_order_id") if pedido_local else None),
                    disable_web_page_preview=True,
                )
                context.user_data.clear()
                return

            await update.message.reply_text(
                "⚠️ Não consegui consultar esse ID na plataforma.\n\n"
                f"*Motivo:* {md(limpar_erro_api(exc))}\n\n"
                "Confira se o ID está correto e tente novamente.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[btn("⬅️ Voltar", "voltar:inicio")]]),
                disable_web_page_preview=True,
            )
            return

    if pedido_local:
        await update.message.reply_text(
            texto_status_pedido_local(pedido_local, origem),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=botoes_consulta_pedido(pedido_local.get("plataforma_order_id") if pedido_local else None),
            disable_web_page_preview=True,
        )
        context.user_data.clear()
        return

    await update.message.reply_text(
        "❌ Não encontrei esse pedido.\n\n"
        "Confira se você enviou o ID correto. Se o pedido já foi enviado à plataforma, envie o ID da plataforma.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[btn("⬅️ Voltar", "voltar:inicio")]]),
    )


async def receber_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = (update.message.text or "").strip()

    if context.user_data.get("consulta_pedido"):
        await responder_consulta_pedido(update, context, texto_usuario)
        return

    if context.user_data.get("refil_pedido"):
        await processar_solicitacao_refil(update, context, texto_usuario)
        return

    if context.user_data.get("aguardando_quantidade"):
        await processar_quantidade_manual(update, context, texto_usuario)
        return

    pedido = context.user_data.get("pedido")

    if not pedido:
        await update.message.reply_text(
            "Para iniciar um pedido, toque em /start e escolha uma opção do catálogo.",
            reply_markup=menu_principal(),
        )
        return


    if pedido.get("status") == "aguardando_pagamento" and texto_usuario == "1":
        await finalizar_pedido_confirmado(update, context, pedido)
        return

    if pedido.get("status") == "aguardando_aprovacao_admin":
        await update.message.reply_text(
            "⏳ Seu comprovante já está em validação. O pedido só será liberado depois da aprovação.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not pedido.get("link"):
        pedido["link"] = texto_usuario

        if pedido.get("catalogo") in ("IPTV Livestream 4K", "Internet Ilimitada") and pedido.get("status") == "aguardando_email_iptv":
            await update.message.reply_text(
                (
                    "📧 *Confirme o e-mail informado:*\n\n"
                    f"`{md(pedido['link'])}`\n\n"
                    "Se estiver correto, toque no botão abaixo para ir para o pagamento."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=botoes_confirmar_email_iptv(),
                disable_web_page_preview=True,
            )
            return

        pedido["status"] = "aguardando_pagamento"
        await enviar_pagamento_cliente(update, context, pedido)
        return

    if pedido.get("catalogo") == "Instagram" and pedido.get("status") == "aguardando_pagamento":
        await enviar_pagamento_cliente(update, context, pedido)
        return

    await update.message.reply_text(
        "Já recebi o link/@. Agora finalize pela aba de pagamento abaixo.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=botoes_pagamento(pedido),
    )


async def receber_comprovante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pedido = context.user_data.get("pedido")

    if not pedido:
        await update.message.reply_text(
            "Para iniciar um pedido, toque em /start e escolha uma opção do catálogo.",
            reply_markup=menu_principal(),
        )
        return

    if pedido.get("status") not in ("aguardando_pagamento", "aguardando_aprovacao_admin") or not pedido.get("link"):
        await update.message.reply_text("Recebi a imagem, mas ainda preciso do link/@ do pedido primeiro.")
        return

    if pedido.get("mp_payment_id"):
        await update.message.reply_text(
            "✅ Neste pedido o pagamento é confirmado automaticamente pelo Mercado Pago. "
            "Não precisa enviar comprovante; pague o Pix e toque em ‘Já paguei / verificar’."
        )
        return

    file_id = None
    file_unique_id = None
    if update.message.photo:
        arquivo = update.message.photo[-1]
        file_id = arquivo.file_id
        file_unique_id = arquivo.file_unique_id
    elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
        arquivo = update.message.document
        file_id = arquivo.file_id
        file_unique_id = arquivo.file_unique_id
    else:
        await update.message.reply_text("Envie o comprovante como imagem para eu anexar ao relatório.")
        return

    if comprovante_ja_usado(file_unique_id):
        await update.message.reply_text(
            "🚫 Esse mesmo arquivo de comprovante já foi usado em outro pedido. "
            "Envie um comprovante válido e exclusivo deste pedido."
        )
        return

    pedido["comprovante_file_id"] = file_id
    pedido["comprovante_unique_id"] = file_unique_id
    pedido["status"] = "aguardando_aprovacao_admin"
    pedido["comprovante_recebido_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")

    salvar_pedido_pendente(pedido)
    enviado_admin = await enviar_para_aprovacao_admin(update, context, pedido)

    if not enviado_admin:
        await update.message.reply_text(
            "⚠️ Comprovante recebido, mas o ADMIN_CHAT_ID não está configurado. "
            "Configure o administrador antes de liberar pedidos."
        )
        return

    await enviar_texto_sequencial(
        update,
        context,
        (
            "✅ Comprovante recebido e enviado para validação.\n\n"
            f"🆔 *ID do pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
            "O pedido só será enviado para a plataforma depois que o administrador aprovar o comprovante."
        ),
        InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
    )


async def enviar_relatorio_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict):
    if not ADMIN_CHAT_ID:
        await update.effective_message.reply_text(CATALOGO["mensagens"].get("erro_admin", "ADMIN_CHAT_ID não configurado."))
        return

    await fechar_semana_se_necessario(context.bot)
    total_semanal_cliente = registrar_pedido_semanal(pedido)

    username = f'@{pedido["username"]}' if pedido.get("username") else "Sem username"

    bloco_api = ""
    if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
        if pedido.get("plataforma_api_status") == "enviado":
            bloco_api = (
                f"🚀 *API plataforma:* Enviado\n"
                f"🆔 *Pedido na plataforma:* `{md(pedido.get('plataforma_order_id', 'Não informado'))}`\n"
                f"🔧 *Service ID:* `{md(pedido.get('plataforma_service_id', ''))}`\n"
            )
        else:
            bloco_api = (
                f"🚀 *API plataforma:* Falhou ou não configurada\n"
                f"⚠️ *Erro:* {md(pedido.get('plataforma_api_erro', 'Sem retorno da API'))}\n"
            )

    relatorio = (
        "📥 *NOVO PEDIDO APROVADO — TW STORE*\n\n"
        f"🆔 *Pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
        f"🗂️ *Catálogo:* {md(pedido['catalogo'])}\n"
        f"📌 *Serviço:* {md(pedido['servico'])}\n"
        f"🔢 *Quantidade:* {md(pedido['quantidade'])}\n"
        f"💰 *Valor:* R$ {md(pedido['valor'])}\n"
        f"📆 *Total do cliente nesta semana:* R$ {md(total_semanal_cliente)}\n"
        f"🔗 *Link/@:* {md(pedido['link'])}\n"
        f"{bloco_api}\n"
        f"👤 *Cliente:* {md(pedido['usuario'])}\n"
        f"📱 *Telegram:* {md(username)}\n"
        f"🆔 *ID:* `{pedido['user_id']}`\n"
        f"✅ *Aprovado por:* {md(pedido.get('aprovado_por', 'Administrador'))}\n"
        f"🕒 *Data:* {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    comprovante_file_id = pedido.get("comprovante_file_id")

    if comprovante_file_id:
        try:
            if len(relatorio) <= 1000:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID,
                    photo=comprovante_file_id,
                    caption=relatorio,
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=comprovante_file_id)
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=relatorio,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
            return
        except Exception as exc:
            logging.warning("Falha ao enviar relatório com comprovante: %s", exc)

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=relatorio,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Configure a variável BOT_TOKEN com o token do BotFather.")
    iniciar_servidor_web()
    app = Application.builder().token(BOT_TOKEN).post_init(iniciar_rotina_fechamento).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.IMAGE), receber_comprovante))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber_texto))
    print("Bot TW STORE iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
