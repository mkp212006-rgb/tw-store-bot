import asyncio
import json
import os
import re
import secrets
import hashlib
import math
import shutil
import logging
import threading
import time as time_module
import requests
import smtplib
import ssl
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None
try:
    from flask import Flask, request, jsonify
except Exception:
    Flask = request = jsonify = None
from io import BytesIO
from email.message import EmailMessage
from email.utils import formataddr
from html import escape as html_escape
from datetime import datetime, timedelta, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.error import BadRequest
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = ImageDraw = ImageFont = None

from database import BotDatabase
from roles import (
    CARGOS,
    CARGO_DONO,
    CARGO_GERENTE,
    CARGO_VENDEDOR,
    CARGO_TESTER,
    PERMISSAO_PAINEL_ADMIN,
    PERMISSAO_APROVAR_CADASTROS,
    PERMISSAO_ATENDER_SUPORTE,
    PERMISSAO_GERENCIAR_CARGOS,
    cargo_tem_permissao,
    nome_cargo,
    normalizar_cargo,
    pode_atribuir_cargo,
    pode_gerenciar_cargo,
)
from validators import validar_destino_pedido

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    PicklePersistence,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BASE_DIR = Path(__file__).resolve().parent
if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env")


def resolver_data_dir() -> Path:
    """Define onde os arquivos gerados pelo bot serão salvos.

    Por padrão fica em ./dados dentro da pasta do bot. Em hospedagens como
    Railway/Render, configure DATA_DIR para o caminho do volume persistente.
    """
    data_dir_env = os.getenv("DATA_DIR", "dados").strip() or "dados"
    data_dir = Path(data_dir_env).expanduser()
    if not data_dir.is_absolute():
        data_dir = BASE_DIR / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


DATA_DIR = resolver_data_dir()
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "bot.sqlite3"))).expanduser()
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = BASE_DIR / DATABASE_PATH
DB = BotDatabase(DATABASE_PATH)

CATALOGO_PATH = BASE_DIR / "catalogo.json"
WELCOME_IMAGE_PATH = BASE_DIR / "tw_store_boas_vindas.png"
CATALOGO_IMAGE_PATH = BASE_DIR / "tw_store_catalogo.png"
ENGAJAMENTOS_IMAGE_PATH = BASE_DIR / "tw_store_engajamentos.png"
INSTAGRAM_IMAGE_PATH = BASE_DIR / "tw_store_instagram.png"
INSTAGRAM_ESTRANGEIROS_IMAGE_PATH = BASE_DIR / "tw_store_instagram_estrangeiros.png"
INSTAGRAM_BRASILEIROS_IMAGE_PATH = BASE_DIR / "tw_store_instagram_brasileiros.png"
TIKTOK_IMAGE_PATH = BASE_DIR / "tw_store_tiktok.png"
TIKTOK_ESTRANGEIROS_IMAGE_PATH = BASE_DIR / "tw_store_tiktok_estrangeiros.png"
KWAI_IMAGE_PATH = BASE_DIR / "tw_store_kwai.png"
KWAI_BRASILEIROS_IMAGE_PATH = BASE_DIR / "tw_store_kwai_brasileiros.png"
IPTV_IMAGE_PATH = BASE_DIR / "xciptv_player.jpg"
SUPORTE_IMAGE_PATH = BASE_DIR / "tw_store_suporte.png"
TICKET_STATUS_IMAGE_PATH = BASE_DIR / "ticket_suporte.jpg"
REGISTRO_IMAGE_PATH = BASE_DIR / "registro_obrigatorio.jpg"
CRIAR_REGISTRO_IMAGE_PATH = BASE_DIR / "criar_usuario.png"
PAGAMENTO_INSTAGRAM_LAYOUT_PATH = BASE_DIR / "pagamento_instagram_layout.png"
PAGAMENTO_TIKTOK_LAYOUT_PATH = BASE_DIR / "pagamento_tiktok_layout.png"
ASSINATURA_IMAGE_PATHS = {
    "netflix": BASE_DIR / "netflix_premium.jpg",
    "prime_video": BASE_DIR / "prime_video_premium.jpg",
    "crunchyroll": BASE_DIR / "crunchyroll_premium.png",
    "spotify": BASE_DIR / "spotify_premium.png",
    "paramount": BASE_DIR / "paramount_premium.png",
}

with open(CATALOGO_PATH, "r", encoding="utf-8") as f:
    CATALOGO = json.load(f)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
PIX_CHAVE = os.getenv("PIX_CHAVE", "").strip()
PIX_COPIA_COLA = os.getenv("PIX_COPIA_COLA", "").strip()
PIX_RECEBEDOR = os.getenv("PIX_RECEBEDOR", "").strip()

# E-mail automático dos relatórios de pedidos concluídos.
# Para Gmail, use uma senha de app (16 caracteres), nunca a senha normal da conta.
EMAIL_SMTP_HOST = (os.getenv("EMAIL_SMTP_HOST") or os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
try:
    EMAIL_SMTP_PORT = int((os.getenv("EMAIL_SMTP_PORT") or os.getenv("SMTP_PORT") or "587").strip())
except ValueError:
    EMAIL_SMTP_PORT = 587
EMAIL_SMTP_USER = (os.getenv("EMAIL_SMTP_USER") or os.getenv("EMAIL_USER") or "").strip()
EMAIL_SMTP_PASSWORD = (
    os.getenv("EMAIL_SMTP_PASSWORD")
    or os.getenv("EMAIL_APP_PASSWORD")
    or ""
).strip().replace(" ", "")
EMAIL_PEDIDOS_DESTINO = (
    os.getenv("EMAIL_PEDIDOS_DESTINO")
    or os.getenv("EMAIL_DESTINO")
    or EMAIL_SMTP_USER
).strip()
EMAIL_REMETENTE_NOME = os.getenv("EMAIL_REMETENTE_NOME", "TW Store").strip() or "TW Store"
EMAIL_SMTP_USE_TLS = os.getenv("EMAIL_SMTP_USE_TLS", "true").strip().lower() not in (
    "0", "false", "nao", "não", "no", "off", "desativado"
)
EMAIL_SMTP_USE_SSL = os.getenv("EMAIL_SMTP_USE_SSL", "false").strip().lower() in (
    "1", "true", "sim", "yes", "on", "ativado"
)
EMAIL_ANEXAR_RELATORIO_PNG = os.getenv("EMAIL_ANEXAR_RELATORIO_PNG", "true").strip().lower() not in (
    "0", "false", "nao", "não", "no", "off", "desativado"
)
try:
    EMAIL_SMTP_TIMEOUT = int(os.getenv("EMAIL_SMTP_TIMEOUT", "30"))
except ValueError:
    EMAIL_SMTP_TIMEOUT = 30

# API da plataforma de pedidos.
# Preencha essas variáveis no .env antes de colocar o bot em produção.
PANEL_API_URL = os.getenv("PANEL_API_URL", "").strip()
PANEL_API_KEY = os.getenv("PANEL_API_KEY", "").strip()
try:
    PANEL_API_TIMEOUT = int(os.getenv("PANEL_API_TIMEOUT", "30"))
except ValueError:
    PANEL_API_TIMEOUT = 30

# Trava antes do débito da carteira: consulta a plataforma antes de liberar o pedido.
# Se estiver sem saldo/sem serviço disponível, o saldo do cliente não é alterado.
CHECK_ESTOQUE_ANTES_PAGAMENTO = os.getenv("CHECK_ESTOQUE_ANTES_PAGAMENTO", "true").strip().lower() not in (
    "0", "false", "nao", "não", "no", "off", "desativado"
)
try:
    MARGEM_SALDO_PLATAFORMA = float(os.getenv("MARGEM_SALDO_PLATAFORMA", "0").strip().replace(",", "."))
except ValueError:
    MARGEM_SALDO_PLATAFORMA = 0.0

try:
    PANEL_SERVICES_CACHE_TTL = int(os.getenv("PANEL_SERVICES_CACHE_TTL", "300"))
except ValueError:
    PANEL_SERVICES_CACHE_TTL = 300
PLATAFORMA_SERVICOS_CACHE = {"expira_em": 0.0, "dados": None}

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
try:
    WEBHOOK_QUEUE_INTERVAL = int(os.getenv("WEBHOOK_QUEUE_INTERVAL", "45"))
except ValueError:
    WEBHOOK_QUEUE_INTERVAL = 45
try:
    WEBHOOK_QUEUE_MAX_ATTEMPTS = int(os.getenv("WEBHOOK_QUEUE_MAX_ATTEMPTS", "8"))
except ValueError:
    WEBHOOK_QUEUE_MAX_ATTEMPTS = 8

# Tempo para limpar automaticamente pedidos que ficaram aguardando pagamento.
# Use 0 para desativar. Padrão: 180 minutos / 3 horas.
try:
    PAGAMENTOS_PENDENTES_EXPIRAR_MINUTOS = int(os.getenv("PAGAMENTOS_PENDENTES_EXPIRAR_MINUTOS", "180"))
except ValueError:
    PAGAMENTOS_PENDENTES_EXPIRAR_MINUTOS = 180
try:
    PAGAMENTOS_PENDENTES_LIMPEZA_INTERVALO = int(os.getenv("PAGAMENTOS_PENDENTES_LIMPEZA_INTERVALO", "300"))
except ValueError:
    PAGAMENTOS_PENDENTES_LIMPEZA_INTERVALO = 300

# Limpa pedidos persistidos em pedidos_pendentes quando o bot inicia.
# Mantido ligado por padrão para impedir que webhooks/pendências antigas sejam
# reenviados para a plataforma após restart/deploy no Railway.
LIMPAR_PEDIDOS_PENDENTES_AO_INICIAR = os.getenv("LIMPAR_PEDIDOS_PENDENTES_AO_INICIAR", "true").strip().lower() not in (
    "0", "false", "nao", "não", "no", "off", "desativado"
)

# Tempo de espera para um cliente tentar novo cadastro após o admin negar.
# Padrão: 5 minutos.
try:
    REGISTRO_NEGADO_TENTAR_NOVAMENTE_MINUTOS = int(os.getenv("REGISTRO_NEGADO_TENTAR_NOVAMENTE_MINUTOS", "5"))
except ValueError:
    REGISTRO_NEGADO_TENTAR_NOVAMENTE_MINUTOS = 5
if REGISTRO_NEGADO_TENTAR_NOVAMENTE_MINUTOS < 1:
    REGISTRO_NEGADO_TENTAR_NOVAMENTE_MINUTOS = 5

# Meta semanal aplicada somente ao cargo Vendedor(a) Tester.
try:
    META_SEMANAL_TESTER_REAIS = float(
        os.getenv("META_SEMANAL_TESTER_REAIS", "20,00").strip().replace(",", ".")
    )
except ValueError:
    META_SEMANAL_TESTER_REAIS = 20.0
if not math.isfinite(META_SEMANAL_TESTER_REAIS) or META_SEMANAL_TESTER_REAIS < 0:
    META_SEMANAL_TESTER_REAIS = 20.0
META_SEMANAL_TESTER_CENTAVOS = int(round(META_SEMANAL_TESTER_REAIS * 100))

SALDO_MINIMO_RECARGA_CENTAVOS = 500
SALDO_MAXIMO_RECARGA_CENTAVOS = 30000
TAXA_RECARGA_PERCENTUAL = 5


TZ_BR = ZoneInfo("America/Sao_Paulo")
TOTAIS_SEMANAIS_PATH = DATA_DIR / "totais_semanais.json"
PEDIDOS_PENDENTES_PATH = DATA_DIR / "pedidos_pendentes.json"
COMPROVANTES_USADOS_PATH = DATA_DIR / "comprovantes_usados.json"
PAGAMENTOS_PROCESSADOS_PATH = DATA_DIR / "pagamentos_processados.json"
PEDIDOS_HISTORICO_PATH = DATA_DIR / "pedidos_historico.json"
USUARIOS_REGISTRADOS_PATH = DATA_DIR / "usuarios_registrados.json"
BOT_PERSISTENCE_PATH = DATA_DIR / "bot_persistence.pkl"

CONFIG_MANUTENCAO_CHAVE = "manutencao"
MENSAGEM_MANUTENCAO_INICIO = (
    "⚙️ Manutenção em andamento\n\n"
    "O bot está entrando em manutenção agora para ajustes e melhorias.\n\n"
    "Durante esse período, o acesso ficará temporariamente bloqueado. "
    "Assim que o serviço for concluído, você receberá uma nova notificação.\n\n"
    "Agradecemos pela compreensão."
)
MENSAGEM_MANUTENCAO_BLOQUEIO = (
    "⚙️ *Bot em manutenção*\n\n"
    "O acesso está temporariamente bloqueado enquanto realizamos ajustes e melhorias.\n\n"
    "Assim que a manutenção for concluída, você receberá uma notificação."
)
MENSAGEM_MANUTENCAO_CONCLUSAO = (
    "✅ Manutenção concluída\n\n"
    "A manutenção foi finalizada com sucesso e o bot já está liberado para uso novamente.\n\n"
    "Toque em /start para continuar."
)

ARQUIVOS_JSON_RUNTIME = {
    "totais_semanais.json": None,
    "pedidos_pendentes.json": {},
    "comprovantes_usados.json": {},
    "pagamentos_processados.json": {},
    "pedidos_historico.json": {},
    "usuarios_registrados.json": {},
}

# Evita processar o mesmo pagamento duas vezes quando o Mercado Pago reenvia
# notificações ou quando cliente toca em "verificar" ao mesmo tempo do webhook.
_MP_PAYMENTS_LOCK = threading.Lock()
_MP_PAYMENTS_EM_PROCESSAMENTO = set()
_FECHAMENTO_SEMANAL_LOCK = asyncio.Lock()
_MANUTENCAO_LOCK = asyncio.Lock()


def agora_br() -> datetime:
    return datetime.now(TZ_BR)


# Momento em que esta instância do bot subiu. Usado para não reenviar
# automaticamente pagamentos aprovados antes do deploy/restart atual.
BOT_PROCESS_STARTED_AT = agora_br()


def formatar_data_expiracao_mercado_pago(data: datetime) -> str:
    """Formata a expiração do Pix no padrão aceito pelo Mercado Pago.

    O Mercado Pago rejeita datas em formato brasileiro/UTC textual, por exemplo:
    02-07-2026T07:31:01UTC.

    O formato correto precisa ficar assim:
    2026-07-02T04:31:01.000-03:00
    """
    if data.tzinfo is None:
        data = data.replace(tzinfo=TZ_BR)

    data = data.astimezone(TZ_BR)
    offset = data.strftime("%z")  # Exemplo: -0300
    offset_formatado = f"{offset[:3]}:{offset[3:]}" if offset else "-03:00"

    return f"{data:%Y-%m-%dT%H:%M:%S}.000{offset_formatado}"


def copiar_padrao_json(padrao):
    if isinstance(padrao, dict):
        return padrao.copy()
    if isinstance(padrao, list):
        return padrao.copy()
    return padrao


def carregar_json(caminho: Path, padrao):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if not caminho.exists():
        return copiar_padrao_json(padrao)
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except Exception as exc:
        backup = caminho.with_suffix(caminho.suffix + f".corrompido-{agora_br():%Y%m%d%H%M%S}.bak")
        try:
            shutil.copy2(caminho, backup)
            logging.warning("JSON corrompido em %s. Backup criado em %s. Erro: %s", caminho, backup, exc)
        except Exception:
            logging.warning("JSON corrompido em %s. Não foi possível criar backup. Erro: %s", caminho, exc)
        return copiar_padrao_json(padrao)
    return dados if isinstance(dados, type(padrao)) else copiar_padrao_json(padrao)


def salvar_json(caminho: Path, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(temporario, caminho)


def inicializar_arquivos_json_runtime():
    """Prepara a pasta de dados e mantém compatibilidade com versões antigas.

    A versão 1.6 usa SQLite. Os arquivos JSON antigos, quando existirem,
    são migrados para o banco na primeira inicialização.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / ".gitkeep").touch(exist_ok=True)

    for nome in ARQUIVOS_JSON_RUNTIME.keys():
        destino = DATA_DIR / nome
        origem_antiga = BASE_DIR / nome
        if origem_antiga.exists() and origem_antiga.resolve() != destino.resolve() and not destino.exists():
            try:
                shutil.copy2(origem_antiga, destino)
                logging.info("Arquivo legado migrado para a pasta dados: %s -> %s", origem_antiga, destino)
            except Exception as exc:
                logging.warning("Não foi possível copiar arquivo legado %s: %s", origem_antiga, exc)


inicializar_arquivos_json_runtime()
DB.migrar_jsons_se_vazio({
    "totais_semanais": TOTAIS_SEMANAIS_PATH,
    "pedidos_pendentes": PEDIDOS_PENDENTES_PATH,
    "comprovantes_usados": COMPROVANTES_USADOS_PATH,
    "pagamentos_processados": PAGAMENTOS_PROCESSADOS_PATH,
    "pedidos_historico": PEDIDOS_HISTORICO_PATH,
    "usuarios_registrados": USUARIOS_REGISTRADOS_PATH,
})


def gerar_pedido_id() -> str:
    return f"TW{agora_br():%Y%m%d%H%M%S}{secrets.token_hex(2).upper()}"


def preparar_pedido(pedido: dict) -> dict:
    pedido.setdefault("pedido_id", gerar_pedido_id())
    pedido.setdefault("criado_em", agora_br().strftime("%d/%m/%Y %H:%M:%S"))
    return pedido


def carregar_pedidos_pendentes() -> dict:
    return DB.carregar_pedidos_pendentes()


def salvar_pedidos_pendentes(dados: dict):
    DB.salvar_pedidos_pendentes(dados)


def salvar_pedido_pendente(pedido: dict):
    pedido_id = str(pedido.get("pedido_id") or gerar_pedido_id())
    pedido["pedido_id"] = pedido_id
    DB.salvar_pedido_pendente(pedido_id, pedido)


def obter_pedido_pendente(pedido_id: str) -> dict | None:
    return carregar_pedidos_pendentes().get(str(pedido_id))


def remover_pedido_pendente(pedido_id: str):
    DB.remover_pedido_pendente(str(pedido_id))


def pagamento_pendente_expiracao_ativa() -> bool:
    return int(PAGAMENTOS_PENDENTES_EXPIRAR_MINUTOS or 0) > 0


def data_base_expiracao_pagamento(pedido: dict) -> datetime | None:
    return parse_data_br(
        pedido.get("pagamento_criado_em")
        or pedido.get("criado_em")
        or pedido.get("atualizado_em")
    )


def calcular_expiracao_pagamento(pedido: dict) -> datetime | None:
    if not pagamento_pendente_expiracao_ativa():
        return None

    # Se o pagamento já nasceu com data de expiração gravada, respeita essa data.
    # Isso evita deixar o cliente usando um Pix/link que o Mercado Pago já expirou.
    expira_em_salvo = parse_data_br(pedido.get("pagamento_expira_em"))
    if expira_em_salvo:
        return expira_em_salvo

    base = data_base_expiracao_pagamento(pedido)
    if not base:
        return None
    return base + timedelta(minutes=int(PAGAMENTOS_PENDENTES_EXPIRAR_MINUTOS))


def pagamento_pendente_expirado(pedido: dict, agora: datetime | None = None) -> bool:
    if not pagamento_pendente_expiracao_ativa():
        return False
    if str(pedido.get("status") or "") != "aguardando_pagamento":
        return False
    expira_em = calcular_expiracao_pagamento(pedido)
    if not expira_em:
        return False
    return (agora or agora_br()) >= expira_em


def fechar_pagamento_expirado(pedido_id: str, pedido: dict, motivo: str = "Tempo limite para pagamento esgotado"):
    registro = dict(pedido or {})
    registro["pedido_id"] = str(pedido_id or registro.get("pedido_id") or "")
    registro["status"] = "pagamento_expirado"
    registro["expirado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    registro["motivo_expiracao"] = motivo
    salvar_pedido_historico(registro)
    remover_pedido_pendente(str(registro.get("pedido_id") or pedido_id))


def fechar_pagamentos_expirados_sync() -> list[dict]:
    """Fecha pedidos que passaram do prazo aguardando pagamento.

    Para Pix automático do Mercado Pago, consulta o status antes de fechar. Se o
    pagamento estiver aprovado, processa o pedido em vez de apagar a pendência.
    """
    if not pagamento_pendente_expiracao_ativa():
        return []

    expirados = []
    agora = agora_br()
    pendentes = carregar_pedidos_pendentes()

    for pedido_id, pedido in list(pendentes.items()):
        if not pagamento_pendente_expirado(pedido, agora):
            continue

        payment_id = str(pedido.get("mp_payment_id") or "").strip()
        motivo = "Pagamento pendente expirado automaticamente"

        if payment_id and mercado_pago_configurado():
            try:
                pagamento = consultar_pagamento_mercado_pago_sync(payment_id)
                status_mp = str(pagamento.get("status") or "").lower()
                if status_mp == "approved":
                    processar_pagamento_aprovado_sync(pedido, pagamento, origem="limpeza_expirados")
                    continue
                if status_mp:
                    motivo = f"Mercado Pago retornou status {status_mp} após o prazo"
                    pedido["mp_status"] = status_mp
                    pedido["mp_status_detail"] = str(pagamento.get("status_detail") or pedido.get("mp_status_detail") or "")
            except Exception as exc:
                logging.warning("Não foi possível verificar pagamento expirado %s no Mercado Pago: %s", payment_id, exc)
                # Para evitar fechar um pagamento que possa ter sido aprovado, tenta novamente no próximo ciclo.
                continue

        fechar_pagamento_expirado(str(pedido_id), pedido, motivo)
        expirados.append({"pedido_id": str(pedido_id), "user_id": pedido.get("user_id"), "motivo": motivo})

    return expirados


def botoes_pedido_expirado() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("🔄 Fazer novo pedido", "voltar:inicio")]])


async def avisar_cliente_pagamento_expirado(bot, pedido_id: str, user_id, motivo: str):
    if not user_id:
        return
    try:
        await bot.send_message(
            chat_id=user_id,
            text=(
                "⌛️ Seu link de pagamento expirou e o pedido foi fechado automaticamente.\n\n"
                f"ID do pedido: `{md(pedido_id)}`\n\n"
                "Para comprar, toque em *Fazer novo pedido* e comece do início."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=botoes_pedido_expirado(),
        )
    except Exception as exc:
        logging.warning("Falha ao avisar cliente sobre pagamento expirado %s: %s", pedido_id, exc)


async def encerrar_interacao_se_pagamento_expirado(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict) -> bool:
    if not pedido or not pagamento_pendente_expirado(pedido):
        return False

    pedido_id = str(pedido.get("pedido_id") or "")
    await asyncio.to_thread(fechar_pagamentos_expirados_sync)

    historico = carregar_pedidos_historico().get(pedido_id) if pedido_id else None
    if historico and historico.get("status") == "pagamento_expirado":
        context.user_data.clear()
        await safe_edit_or_reply(
            update,
            (
                "⌛️ Esse link de pagamento expirou e o pedido foi fechado automaticamente.\n\n"
                f"ID do pedido: `{md(pedido_id)}`\n\n"
                "Para comprar, toque em *Fazer novo pedido* e comece do início."
            ),
            botoes_pedido_expirado(),
        )
        return True

    return False


def carregar_pedidos_historico() -> dict:
    return DB.carregar_pedidos_historico()


def salvar_pedido_historico(pedido: dict):
    if not pedido:
        return
    pedido_id = str(pedido.get("pedido_id") or gerar_pedido_id())
    registro = dict(pedido)
    registro["pedido_id"] = pedido_id
    registro["historico_atualizado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    DB.salvar_pedido_historico(pedido_id, registro)


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
    return DB.carregar_comprovantes_usados()


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
    DB.salvar_comprovantes_usados(usados)


def ids_unicos(*valores: str) -> list[str]:
    ids = []
    for valor in valores:
        admin_id = str(valor or "").strip()
        if admin_id and admin_id not in ids:
            ids.append(admin_id)
    return ids


def ids_admin_registro() -> list[str]:
    """Equipe autorizada a aprovar ou negar novos cadastros."""
    return ids_com_permissao(PERMISSAO_APROVAR_CADASTROS)


def ids_admin_relatorio_semanal() -> list[str]:
    """Donos e gerentes que recebem o fechamento semanal automático."""
    return ids_com_permissao(PERMISSAO_PAINEL_ADMIN)


def ids_admin_relatorio_pedido(pedido: dict | None = None) -> list[str]:
    """Retorna somente o Admin 1, configurado pela variável ADMIN_CHAT_ID."""
    return ids_unicos(ADMIN_CHAT_ID)


def eh_admin(update: Update) -> bool:
    return usuario_tem_permissao_update(update, PERMISSAO_PAINEL_ADMIN)


def carregar_usuarios_registrados() -> dict:
    return DB.carregar_usuarios()


def salvar_usuarios_registrados(dados: dict):
    DB.salvar_usuarios(dados)


def obter_usuario_registrado(telegram_id) -> dict | None:
    if telegram_id is None:
        return None
    return carregar_usuarios_registrados().get(str(telegram_id))


def telegram_id_update(update: Update) -> str:
    if update.effective_user:
        return str(update.effective_user.id)
    if update.effective_chat:
        return str(update.effective_chat.id)
    return ""


def cargo_usuario_id(telegram_id, registro: dict | None = None) -> str:
    """Resolve o cargo efetivo, incluindo o administrador de bootstrap."""
    telegram_id = str(telegram_id or "").strip()
    if telegram_id and telegram_id == str(ADMIN_CHAT_ID or "").strip():
        return CARGO_DONO
    if registro is None and telegram_id:
        registro = obter_usuario_registrado(telegram_id)
    return normalizar_cargo((registro or {}).get("cargo"), CARGO_VENDEDOR)


def cargo_usuario_update(update: Update) -> str:
    return cargo_usuario_id(telegram_id_update(update))


def eh_dono(update: Update) -> bool:
    telegram_id = telegram_id_update(update)
    return cargo_usuario_id(telegram_id) == CARGO_DONO and (
        id_administrador_sistema(telegram_id)
        or bool(
            (obter_usuario_registrado(telegram_id) or {}).get("status")
            == "aprovado"
        )
    )


def carregar_estado_manutencao() -> dict:
    estado = DB.carregar_configuracao(
        CONFIG_MANUTENCAO_CHAVE,
        {"ativa": False},
    )
    estado["ativa"] = bool(estado.get("ativa"))
    return estado


def manutencao_ativa() -> bool:
    return bool(carregar_estado_manutencao().get("ativa"))


def definir_estado_manutencao(
    ativa: bool,
    update: Update | None = None,
) -> dict:
    estado = carregar_estado_manutencao()
    momento = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    responsavel_id = telegram_id_update(update) if update else ""
    responsavel_nome = (
        update.effective_user.full_name
        if update and update.effective_user
        else "Dono"
    )

    estado["ativa"] = bool(ativa)
    estado["atualizado_em"] = momento
    if ativa:
        estado["iniciada_em"] = momento
        estado["iniciada_por_id"] = responsavel_id
        estado["iniciada_por_nome"] = responsavel_nome
        estado.pop("concluida_em", None)
        estado.pop("concluida_por_id", None)
        estado.pop("concluida_por_nome", None)
    else:
        estado["concluida_em"] = momento
        estado["concluida_por_id"] = responsavel_id
        estado["concluida_por_nome"] = responsavel_nome

    DB.salvar_configuracao(CONFIG_MANUTENCAO_CHAVE, estado)
    return estado


def ids_usuarios_notificacao() -> list[str]:
    """Retorna todos os Telegram IDs válidos presentes no cadastro."""
    ids = []
    for telegram_id in carregar_usuarios_registrados().keys():
        telegram_id = str(telegram_id or "").strip()
        if telegram_id and telegram_id.lstrip("-").isdigit():
            ids = ids_unicos(*ids, telegram_id)
    return ids


def definir_cargo_registro(
    registro: dict,
    cargo_novo: str,
    aplicado_por: str,
    origem: str,
) -> str:
    """Atualiza o cargo e os metadados relacionados em um único lugar."""
    cargo_normalizado = normalizar_cargo(cargo_novo)
    agora = agora_br()
    atualizado_em = agora.strftime("%d/%m/%Y %H:%M:%S")
    registro["cargo"] = cargo_normalizado
    registro["cargo_aplicado_em"] = atualizado_em
    registro["cargo_aplicado_por"] = aplicado_por
    registro["cargo_aplicacao_origem"] = origem
    registro["atualizado_em"] = atualizado_em

    if cargo_normalizado == CARGO_TESTER:
        registro["meta_semanal_exigida_centavos"] = META_SEMANAL_TESTER_CENTAVOS
        registro["meta_tester_semana_inicio"] = semana_info(agora)["id"]
    else:
        registro.pop("meta_semanal_exigida_centavos", None)
        registro.pop("meta_tester_semana_inicio", None)

    return cargo_normalizado


def preparar_registro_aprovado(registro: dict, aprovado_por: str) -> dict:
    """Libera o cadastro e aplica o cargo inicial obrigatório de Tester."""
    registro["status"] = "aprovado"
    definir_cargo_registro(
        registro,
        CARGO_TESTER,
        aprovado_por,
        "aprovacao_cadastro",
    )
    registro["aprovado_em"] = registro["atualizado_em"]
    registro["aprovado_por"] = aprovado_por
    registro.pop("tentar_novamente_em", None)
    registro.pop("reaprovacao_obrigatoria", None)
    return registro


def id_administrador_sistema(telegram_id) -> bool:
    telegram_id = str(telegram_id or "").strip()
    return telegram_id == str(ADMIN_CHAT_ID or "").strip()


def usuario_tem_permissao_id(telegram_id, permissao: str) -> bool:
    telegram_id = str(telegram_id or "").strip()
    if not telegram_id:
        return False
    registro = obter_usuario_registrado(telegram_id)
    if not id_administrador_sistema(telegram_id):
        if not registro or registro.get("status") != "aprovado":
            return False
    return cargo_tem_permissao(cargo_usuario_id(telegram_id, registro), permissao)


def usuario_tem_permissao_update(update: Update, permissao: str) -> bool:
    return usuario_tem_permissao_id(telegram_id_update(update), permissao)


def ids_com_permissao(permissao: str) -> list[str]:
    ids = ids_unicos(ADMIN_CHAT_ID)
    for telegram_id, registro in carregar_usuarios_registrados().items():
        if registro.get("status") != "aprovado":
            continue
        cargo = cargo_usuario_id(telegram_id, registro)
        if cargo_tem_permissao(cargo, permissao):
            ids = ids_unicos(*ids, telegram_id)
    return [
        telegram_id
        for telegram_id in ids
        if usuario_tem_permissao_id(telegram_id, permissao)
    ]


def pode_aprovar_cadastros(update: Update) -> bool:
    return usuario_tem_permissao_update(update, PERMISSAO_APROVAR_CADASTROS)


def pode_atender_suporte(update: Update) -> bool:
    return usuario_tem_permissao_update(update, PERMISSAO_ATENDER_SUPORTE)


def hash_senha_registro(senha: str, salt: str | None = None) -> tuple[str, str]:
    """Gera hash de senha sem salvar a senha em texto puro.

    Usa PBKDF2-HMAC-SHA256 com biblioteca padrão do Python, sem dependência extra.
    O formato antigo continua compatível porque ainda salva salt + hash no registro.
    """
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        senha.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
    return salt, digest


def pode_tentar_registro_novamente(registro: dict | None) -> tuple[bool, str | None]:
    if not registro:
        return True, None
    tentar_em = str(registro.get("tentar_novamente_em") or "").strip()
    if not tentar_em:
        return True, None
    try:
        limite = datetime.fromisoformat(tentar_em)
        if limite.tzinfo is None:
            limite = limite.replace(tzinfo=TZ_BR)
    except Exception:
        return True, None
    if agora_br() >= limite:
        return True, None
    return False, limite.strftime("%d/%m/%Y %H:%M")


def registro_aprovado(update: Update) -> bool:
    if eh_admin(update):
        return True
    user = update.effective_user
    if not user:
        return False
    registro = obter_usuario_registrado(user.id)
    return bool(registro and registro.get("status") == "aprovado")


def texto_acesso_bloqueado(update: Update) -> str:
    user = update.effective_user
    registro = obter_usuario_registrado(user.id) if user else None
    if registro and registro.get("status") == "banido":
        motivo = registro.get("motivo_ban") or "Não informado"
        return (
            "🚫 *Acesso bloqueado*\n\n"
            "Sua conta está bloqueada para usar este bot.\n\n"
            "📌 *Motivo*\n"
            f"• {md(motivo)}\n\n"
            f"🆔 *Telegram ID:* `{md(user.id if user else '')}`\n\n"
            "Se você acredita que isso foi um engano, fale com o suporte."
        )
    if registro and registro.get("status") == "pendente":
        return (
            "⏳ *Cadastro em análise*\n\n"
            "Sua solicitação já foi enviada para o administrador.\n\n"
            "📌 *Status*\n"
            "• Cadastro recebido\n"
            "• Aguardando aprovação\n\n"
            "Assim que for aprovado, você receberá um aviso aqui no bot."
        )
    if registro and registro.get("status") == "negado":
        liberado, horario = pode_tentar_registro_novamente(registro)
        if not liberado:
            return (
                "❌ *Cadastro negado*\n\n"
                "Seu cadastro não foi aprovado no momento.\n\n"
                "⏳ *Nova tentativa*\n"
                f"Você poderá tentar novamente em: `{md(horario)}`\n\n"
                "Revise seus dados antes de enviar uma nova solicitação."
            )
    if registro and registro.get("status") == "removido_meta":
        total = int(registro.get("meta_semanal_total_centavos") or 0)
        meta = int(registro.get("meta_semanal_exigida_centavos") or META_SEMANAL_TESTER_CENTAVOS)
        return (
            "📉 *Acesso removido por meta semanal*\n\n"
            "Seu acesso de Vendedor(a) Tester foi removido porque a meta semanal não foi alcançada.\n\n"
            f"💰 *Total da semana:* R$ {md(centavos_para_moeda(total))}\n"
            f"🎯 *Meta exigida:* R$ {md(centavos_para_moeda(meta))}\n\n"
            "Para voltar a usar o bot, solicite um novo cadastro. Sua entrada precisará ser aprovada novamente."
        )
    return (
        "🔐 *Cadastro obrigatório*\n\n"
        "Para usar o bot, solicite acesso criando um usuário e uma senha.\n"
        "Depois disso, o administrador aprova ou nega sua entrada."
    )

def menu_registro(update: Update | None = None) -> InlineKeyboardMarkup:
    keyboard = [[btn("📝 Solicitar acesso", "registro:criar")]]
    if update and update.effective_user:
        keyboard.append([btn("📌 Ver status do cadastro", "registro:status")])
    return InlineKeyboardMarkup(keyboard)


def deve_enviar_imagem_registro(texto: str) -> bool:
    """A arte é usada somente na tela inicial de cadastro obrigatório."""
    return texto.lstrip().startswith("🔐 *Cadastro obrigatório*")


async def enviar_acesso_bloqueado(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia a tela de acesso; no cadastro obrigatório, inclui a arte."""
    texto = texto_acesso_bloqueado(update)
    reply_markup = menu_registro(update)
    chat = update.effective_chat
    if not chat:
        return None

    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception:
            pass

    mensagem = None
    if deve_enviar_imagem_registro(texto) and REGISTRO_IMAGE_PATH.exists():
        try:
            with open(REGISTRO_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
        except Exception as exc:
            logging.warning("Falha ao enviar imagem de cadastro obrigatório: %s", exc)

    if mensagem is None:
        mensagem = await context.bot.send_message(
            chat_id=chat.id,
            text=texto,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )

    # Ao navegar por um botão, substitui a tela anterior para não empilhar mensagens.
    if query and query.message and query.message.message_id != mensagem.message_id:
        try:
            await query.message.delete()
        except Exception:
            pass

    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def bloquear_se_sem_acesso(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if eh_admin(update) or registro_aprovado(update):
        return False
    if update.effective_message:
        await enviar_acesso_bloqueado(update, context)
    return True


async def bloquear_se_manutencao(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Bloqueia qualquer interação durante a manutenção, exceto para donos."""
    if not manutencao_ativa() or eh_dono(update):
        return False

    context.user_data.clear()
    query = update.callback_query
    if query:
        try:
            await query.answer(
                "O bot está em manutenção. Aguarde a notificação de conclusão.",
                show_alert=True,
            )
        except Exception:
            pass
        return True

    if update.effective_message:
        await update.effective_message.reply_text(
            MENSAGEM_MANUTENCAO_BLOQUEIO,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    return True


def texto_solicitacao_registro_admin(telegram_id: str, registro: dict) -> str:
    usuario_tg = registro.get("telegram_username") or "Sem @"
    nome = registro.get("nome_telegram") or "Não informado"
    usuario_login = registro.get("usuario_login") or "Não informado"
    return (
        "🆕 *Novo cadastro aguardando aprovação*\n\n"
        f"*Nome Telegram:* {md(nome)}\n"
        f"*Username Telegram:* {md(usuario_tg)}\n"
        f"*Telegram ID:* `{md(telegram_id)}`\n"
        f"*Usuário escolhido:* `{md(usuario_login)}`\n"
        "*Senha:* salva apenas como hash, não é exibida\n"
        f"*Criado em:* {md(registro.get('criado_em', ''))}\n\n"
        "Aprove ou negue o acesso deste cliente ao bot."
    )

def botoes_aprovacao_registro(telegram_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("✅ Aprovar cadastro", f"admin_registro_aprovar:{telegram_id}")],
        [btn("❌ Negar cadastro", f"admin_registro_negar:{telegram_id}")],
    ])


def nome_admin_decisor(update: Update) -> str:
    """Nome exibido quando um admin aprova ou nega um registro."""
    user = update.effective_user
    if not user:
        return "Administrador"
    nome = user.full_name or f"ID {user.id}"
    if user.username:
        return f"{nome} (@{user.username})"
    return f"{nome} (ID {user.id})"


def mensagens_admin_registro(registro: dict) -> list[dict]:
    """Retorna as mensagens de aprovação enviadas aos admins, sem duplicar."""
    mensagens = registro.get("mensagens_admin_registro") or []
    if not isinstance(mensagens, list):
        return []

    resultado = []
    vistos = set()
    for item in mensagens:
        if not isinstance(item, dict):
            continue
        chat_id = str(item.get("chat_id") or "").strip()
        message_id = item.get("message_id")
        if not chat_id or message_id is None:
            continue
        chave = (chat_id, str(message_id))
        if chave in vistos:
            continue
        vistos.add(chave)
        resultado.append({"chat_id": chat_id, "message_id": message_id})
    return resultado


def texto_resultado_registro_admin(telegram_id: str, registro: dict, acao: str, admin_nome: str) -> str:
    usuario_tg = registro.get("telegram_username") or "Sem @"
    nome = registro.get("nome_telegram") or "Não informado"
    usuario_login = registro.get("usuario_login", "")

    if acao == "aprovado":
        emoji = "✅"
        titulo = "Registro aprovado"
        data_decisao = registro.get("aprovado_em") or agora_br().strftime("%d/%m/%Y %H:%M:%S")
        linha_extra = "O cliente já pode usar o bot com o cargo Vendedor(a) Tester."
    else:
        emoji = "❌"
        titulo = "Registro negado"
        data_decisao = registro.get("negado_em") or agora_br().strftime("%d/%m/%Y %H:%M:%S")
        linha_extra = f"O cliente poderá tentar novamente após {REGISTRO_NEGADO_TENTAR_NOVAMENTE_MINUTOS} minutos."

    return (
        f"{emoji} *{titulo}*\n\n"
        f"*Nome Telegram:* {md(nome)}\n"
        f"*Username Telegram:* {md(usuario_tg)}\n"
        f"*Telegram ID:* `{md(telegram_id)}`\n"
        f"*Identificação interna:* `{md(usuario_login)}`\n\n"
        f"*Decisão feita por:* {md(admin_nome)}\n"
        f"*Data:* {md(data_decisao)}\n\n"
        f"{linha_extra}"
    )


async def substituir_mensagens_registro_admin(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: str,
    registro: dict,
    acao: str,
    admin_nome: str,
    mensagem_origem=None,
):
    """Remove a solicitação antiga dos admins e envia o resultado para todos."""
    texto = texto_resultado_registro_admin(telegram_id, registro, acao, admin_nome)
    mensagens = mensagens_admin_registro(registro)

    if mensagem_origem:
        origem_chat_id = str(mensagem_origem.chat_id)
        origem_message_id = mensagem_origem.message_id
        if not any(str(m.get("chat_id")) == origem_chat_id and str(m.get("message_id")) == str(origem_message_id) for m in mensagens):
            mensagens.append({"chat_id": origem_chat_id, "message_id": origem_message_id})

    chats_notificados = set()

    for item in mensagens:
        chat_id = str(item.get("chat_id") or "").strip()
        message_id = item.get("message_id")
        if not chat_id or message_id is None:
            continue

        # Primeiro tenta apagar a mensagem antiga com os botões.
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as exc:
            logging.warning("Falha ao apagar mensagem de registro no admin %s: %s", chat_id, exc)
            # Se não conseguir apagar, tenta editar para remover os botões e mostrar o resultado.
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=None,
                    disable_web_page_preview=True,
                )
                chats_notificados.add(chat_id)
                continue
            except Exception as exc_edit:
                logging.warning("Falha ao substituir mensagem de registro no admin %s: %s", chat_id, exc_edit)

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=texto,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            chats_notificados.add(chat_id)
        except Exception as exc:
            logging.warning("Falha ao avisar admin %s sobre resultado do registro: %s", chat_id, exc)

    # Garante que admin 1 e admin 2 recebam o resultado mesmo se algum message_id antigo não existir.
    for admin_chat_id in ids_admin_registro():
        admin_chat_id = str(admin_chat_id or "").strip()
        if not admin_chat_id or admin_chat_id in chats_notificados:
            continue
        try:
            await context.bot.send_message(
                chat_id=admin_chat_id,
                text=texto,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logging.warning("Falha ao enviar resultado de registro para admin %s: %s", admin_chat_id, exc)


async def enviar_registro_para_admin(context: ContextTypes.DEFAULT_TYPE, telegram_id: str, registro: dict):
    admins = ids_admin_registro()
    if not admins:
        return False

    enviado = False
    mensagens_enviadas = []
    texto = texto_solicitacao_registro_admin(telegram_id, registro)
    markup = botoes_aprovacao_registro(telegram_id)

    for admin_chat_id in admins:
        try:
            mensagem = await context.bot.send_message(
                chat_id=admin_chat_id,
                text=texto,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            mensagens_enviadas.append({
                "chat_id": str(mensagem.chat.id if mensagem.chat else admin_chat_id),
                "message_id": mensagem.message_id,
            })
            enviado = True
        except Exception as exc:
            logging.warning("Falha ao enviar registro para admin %s: %s", admin_chat_id, exc)

    if mensagens_enviadas:
        registro["mensagens_admin_registro"] = mensagens_enviadas
        usuarios = carregar_usuarios_registrados()
        if str(telegram_id) in usuarios:
            usuarios[str(telegram_id)]["mensagens_admin_registro"] = mensagens_enviadas
            salvar_usuarios_registrados(usuarios)

    return enviado


async def iniciar_registro_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user = update.effective_user
    if not user:
        await safe_edit_or_reply(update, "Não consegui identificar sua conta do Telegram. Toque em /start e tente novamente.")
        return

    usuarios = carregar_usuarios_registrados()
    telegram_id = str(user.id)
    registro = usuarios.get(telegram_id)

    if registro and registro.get("status") == "aprovado":
        await safe_edit_or_reply(update, "✅ Seu cadastro já está aprovado. Use /start para acessar o bot.", menu_principal())
        return
    if registro and registro.get("status") in ("banido", "pendente"):
        await safe_edit_or_reply(update, texto_acesso_bloqueado(update), menu_registro(update))
        return
    if registro and registro.get("status") == "negado":
        liberado, horario = pode_tentar_registro_novamente(registro)
        if not liberado:
            await safe_edit_or_reply(update, texto_acesso_bloqueado(update), menu_registro(update))
            return

    context.user_data.clear()
    context.user_data["registro_em_andamento"] = True

    texto = (
        "📝 *Criar cadastro*\n\n"
        "Envie seu usuário e senha na mesma mensagem, separados por espaço.\n\n"
        "Exemplo:\n"
        "`meuusuario minhasenha123`\n\n"
        "Regras do usuário:\n"
        "• 4 a 30 caracteres\n"
        "• letras, números, ponto, traço ou underline\n\n"
        "A senha precisa ter no mínimo 6 caracteres."
    )
    reply_markup = InlineKeyboardMarkup([[btn("⬅️ Voltar", "voltar:inicio")]])
    chat = update.effective_chat
    mensagem = None

    if chat and CRIAR_REGISTRO_IMAGE_PATH.exists():
        try:
            with open(CRIAR_REGISTRO_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
        except Exception as exc:
            logging.warning("Falha ao enviar imagem da tela Criar cadastro: %s", exc)

    if mensagem is None:
        mensagem = await safe_edit_or_reply(update, texto, reply_markup)
    elif query and query.message and query.message.message_id != mensagem.message_id:
        try:
            await query.message.delete()
        except Exception:
            pass

    return mensagem

async def mostrar_status_registro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await enviar_acesso_bloqueado(update, context)


async def processar_texto_registro(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_usuario: str) -> bool:
    if not context.user_data.get("registro_em_andamento"):
        return False

    user = update.effective_user
    if not user:
        return True

    partes = texto_usuario.split(maxsplit=1)
    if len(partes) != 2:
        await update.message.reply_text(
            "⚠️ Envie usuário e senha na mesma mensagem. Exemplo: `meuusuario minhasenha123`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return True

    usuario_login, senha = partes[0].strip(), partes[1].strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{4,30}", usuario_login):
        await update.message.reply_text(
            "⚠️ Usuário inválido. Use de 4 a 30 caracteres: letras, números, ponto, traço ou underline."
        )
        return True
    if len(senha) < 6:
        await update.message.reply_text("⚠️ A senha precisa ter no mínimo 6 caracteres.")
        return True

    usuarios = carregar_usuarios_registrados()
    telegram_id = str(user.id)
    chat_id_resposta = update.effective_chat.id if update.effective_chat else user.id
    registro_atual = usuarios.get(telegram_id)
    if registro_atual and registro_atual.get("status") == "banido":
        await update.message.reply_text(texto_acesso_bloqueado(update), parse_mode=ParseMode.MARKDOWN)
        return True
    if registro_atual and registro_atual.get("status") == "pendente":
        await update.message.reply_text(texto_acesso_bloqueado(update), parse_mode=ParseMode.MARKDOWN)
        return True
    if registro_atual and registro_atual.get("status") == "negado":
        liberado, horario = pode_tentar_registro_novamente(registro_atual)
        if not liberado:
            await update.message.reply_text(texto_acesso_bloqueado(update), parse_mode=ParseMode.MARKDOWN)
            return True

    for tid, reg in usuarios.items():
        if str(tid) != telegram_id and str(reg.get("usuario_login", "")).lower() == usuario_login.lower() and reg.get("status") != "negado":
            await update.message.reply_text("⚠️ Esse nome de usuário já está em uso. Escolha outro.")
            return True

    salt, senha_hash = hash_senha_registro(senha)
    try:
        await update.message.delete()
    except Exception:
        # Em chats privados normalmente funciona; se o Telegram negar, segue sem interromper o cadastro.
        pass

    registro = {
        "telegram_id": telegram_id,
        "usuario_login": usuario_login,
        "senha_salt": salt,
        "senha_hash": senha_hash,
        "cadastro_com_senha": True,
        "status": "pendente",
        "cargo": (
            cargo_usuario_id(telegram_id, registro_atual)
            if registro_atual and registro_atual.get("status") == "removido_meta"
            else CARGO_VENDEDOR
        ),
        "nome_telegram": user.full_name,
        "telegram_username": f"@{user.username}" if user.username else "",
        "criado_em": agora_br().strftime("%d/%m/%Y %H:%M:%S"),
        "atualizado_em": agora_br().strftime("%d/%m/%Y %H:%M:%S"),
    }
    usuarios[telegram_id] = registro
    salvar_usuarios_registrados(usuarios)
    context.user_data.clear()

    enviado = await enviar_registro_para_admin(context, telegram_id, registro)
    if enviado:
        await context.bot.send_message(
            chat_id=chat_id_resposta,
            text="✅ Cadastro com senha enviado para aprovação.\n\nAssim que o administrador aprovar, você poderá usar o bot normalmente.",
            reply_markup=menu_registro(update),
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id_resposta,
            text="✅ Cadastro criado, mas não consegui avisar o administrador. Verifique se ADMIN_CHAT_ID está configurado.",
            reply_markup=menu_registro(update),
        )
    return True


async def aprovar_registro_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: str):
    query = update.callback_query
    if not pode_aprovar_cadastros(update):
        await query.answer("Seu cargo não pode aprovar cadastros.", show_alert=True)
        return
    usuarios = carregar_usuarios_registrados()
    registro = usuarios.get(str(telegram_id))
    if not registro:
        await query.answer("Cadastro não encontrado.", show_alert=True)
        return
    if registro.get("status") == "banido":
        await query.answer("Este usuário está banido. Desbana antes de aprovar.", show_alert=True)
        return
    if registro.get("status") == "aprovado":
        aprovado_por = registro.get("aprovado_por") or "outro administrador"
        await query.answer(f"Este cadastro já foi aprovado por {aprovado_por}.", show_alert=True)
        await substituir_mensagens_registro_admin(
            context,
            str(telegram_id),
            registro,
            "aprovado",
            aprovado_por,
            query.message,
        )
        return
    if registro.get("status") == "negado":
        negado_por = registro.get("negado_por") or "outro administrador"
        await query.answer(f"Este cadastro já foi negado por {negado_por}.", show_alert=True)
        await substituir_mensagens_registro_admin(
            context,
            str(telegram_id),
            registro,
            "negado",
            negado_por,
            query.message,
        )
        return

    admin_nome = nome_admin_decisor(update)
    preparar_registro_aprovado(registro, admin_nome)
    usuarios[str(telegram_id)] = registro
    salvar_usuarios_registrados(usuarios)

    await query.answer("Cadastro aprovado com o cargo Vendedor(a) Tester.")
    await substituir_mensagens_registro_admin(
        context,
        str(telegram_id),
        registro,
        "aprovado",
        admin_nome,
        query.message,
    )
    try:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                "✅ *Cadastro aprovado*\n\n"
                "Seu acesso foi liberado com sucesso!\n\n"
                "🪪 *Cargo inicial:* Vendedor(a) Tester\n"
                f"🎯 *Meta semanal:* R$ {md(centavos_para_moeda(META_SEMANAL_TESTER_CENTAVOS))}\n\n"
                "Agora você já pode usar o bot normalmente.\n"
                "Toque em /start para abrir o menu principal."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logging.warning("Falha ao avisar cliente sobre aprovação de cadastro: %s", exc)


async def negar_registro_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: str):
    query = update.callback_query
    if not pode_aprovar_cadastros(update):
        await query.answer("Seu cargo não pode negar cadastros.", show_alert=True)
        return
    usuarios = carregar_usuarios_registrados()
    registro = usuarios.get(str(telegram_id))
    if not registro:
        await query.answer("Cadastro não encontrado.", show_alert=True)
        return
    if registro.get("status") == "banido":
        await query.answer("Este usuário já está banido.", show_alert=True)
        return
    if registro.get("status") == "aprovado":
        aprovado_por = registro.get("aprovado_por") or "outro administrador"
        await query.answer(f"Este cadastro já foi aprovado por {aprovado_por}.", show_alert=True)
        await substituir_mensagens_registro_admin(
            context,
            str(telegram_id),
            registro,
            "aprovado",
            aprovado_por,
            query.message,
        )
        return
    if registro.get("status") == "negado":
        negado_por = registro.get("negado_por") or "outro administrador"
        await query.answer(f"Este cadastro já foi negado por {negado_por}.", show_alert=True)
        await substituir_mensagens_registro_admin(
            context,
            str(telegram_id),
            registro,
            "negado",
            negado_por,
            query.message,
        )
        return

    admin_nome = nome_admin_decisor(update)
    tentar_em = agora_br() + timedelta(minutes=REGISTRO_NEGADO_TENTAR_NOVAMENTE_MINUTOS)
    registro["status"] = "negado"
    registro["negado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    registro["negado_por"] = admin_nome
    registro["tentar_novamente_em"] = tentar_em.isoformat()
    usuarios[str(telegram_id)] = registro
    salvar_usuarios_registrados(usuarios)

    await query.answer("Cadastro negado.")
    await substituir_mensagens_registro_admin(
        context,
        str(telegram_id),
        registro,
        "negado",
        admin_nome,
        query.message,
    )
    try:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                "❌ *Cadastro negado*\n\n"
                "Seu cadastro não foi aprovado no momento.\n\n"
                "⏳ *Nova tentativa*\n"
                f"Você poderá tentar novamente após {REGISTRO_NEGADO_TENTAR_NOVAMENTE_MINUTOS} minutos.\n\n"
                "Revise seus dados antes de enviar uma nova solicitação."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logging.warning("Falha ao avisar cliente sobre negação de cadastro: %s", exc)



def menu_painel_admin(update: Update | None = None) -> InlineKeyboardMarkup:
    keyboard = [
        [btn("📒 Relatórios", "admin_painel:relatorios")],
        [btn("📒 Consultar Cadastros", "admin_painel:consultar_cadastros")],
        [btn("📒 Consultar Vendedores", "admin_painel:consultar_vendedores")],
        [btn("🪪 Cargos", "admin_painel:cargos")],
    ]
    if update is not None and eh_dono(update):
        keyboard.append([btn("📢 Notificações", "admin_painel:notificacoes")])
    return InlineKeyboardMarkup(keyboard)


def menu_notificacoes_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("⚙️ Notificar Manutenção.", "admin_notificacoes:manutencao")],
        [btn("⬅️ Voltar ao painel", "admin_painel:inicio")],
    ])


def menu_manutencao_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("⚙️ Notificar Início", "admin_notificacoes:inicio")],
        [btn("⚙️ Notificar Conclusão", "admin_notificacoes:conclusao")],
        [btn("⬅️ Voltar", "admin_painel:notificacoes")],
    ])


def texto_notificacoes_admin() -> str:
    return (
        "📢 *Notificações*\n\n"
        "Escolha o tipo de aviso que deseja enviar aos usuários registrados."
    )


def texto_manutencao_admin() -> str:
    estado = "🔴 Ativa" if manutencao_ativa() else "🟢 Bot liberado"
    return (
        "⚙️ *Notificar Manutenção*\n\n"
        f"*Status atual:* {estado}\n\n"
        "• *Notificar Início:* avisa todos os usuários e bloqueia o bot imediatamente.\n"
        "• *Notificar Conclusão:* avisa todos os usuários e libera o acesso novamente.\n\n"
        "Durante a manutenção, somente usuários com cargo *Dono* podem utilizar o bot."
    )


async def enviar_notificacao_usuarios(bot, texto: str) -> dict:
    """Envia o aviso em ritmo seguro e continua mesmo se um chat falhar."""
    destinatarios = ids_usuarios_notificacao()
    enviadas = 0
    falhas = []

    for indice, telegram_id in enumerate(destinatarios):
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=texto,
                disable_web_page_preview=True,
            )
            enviadas += 1
        except Exception as exc:
            falhas.append(telegram_id)
            logging.warning(
                "Falha ao enviar notificação de manutenção para %s: %s",
                telegram_id,
                exc,
            )

        # Mantém o disparo abaixo do limite global usual do Telegram.
        if indice < len(destinatarios) - 1:
            await asyncio.sleep(0.05)

    return {
        "total": len(destinatarios),
        "enviadas": enviadas,
        "falhas": falhas,
    }


def registrar_resultado_notificacao_manutencao(tipo: str, resultado: dict):
    estado = carregar_estado_manutencao()
    estado[f"ultima_notificacao_{tipo}"] = {
        "em": agora_br().strftime("%d/%m/%Y %H:%M:%S"),
        "total": int(resultado.get("total") or 0),
        "enviadas": int(resultado.get("enviadas") or 0),
        "falhas": len(resultado.get("falhas") or []),
    }
    DB.salvar_configuracao(CONFIG_MANUTENCAO_CHAVE, estado)


async def editar_callback_sem_responder(
    query,
    texto: str,
    reply_markup=None,
):
    """Atualiza uma callback que já foi respondida, sem respondê-la duas vezes."""
    try:
        await query.edit_message_text(
            text=texto,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
        return
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return
    except Exception:
        pass

    if query.message:
        await query.message.reply_text(
            text=texto,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )


def resumo_disparo_manutencao(resultado: dict) -> str:
    total = int(resultado.get("total") or 0)
    enviadas = int(resultado.get("enviadas") or 0)
    falhas = len(resultado.get("falhas") or [])
    linhas = [f"📨 *Notificações enviadas:* {enviadas} de {total}"]
    if falhas:
        linhas.append(f"⚠️ *Falhas de envio:* {falhas}")
    return "\n".join(linhas)


def menu_relatorios_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("📆 Relatório Semanal", "admin_painel:relatorio_semanal")],
        [btn("📆 Relatório Diário", "admin_painel:relatorio_diario")],
        [btn("⬅️ Voltar ao painel", "admin_painel:inicio")],
    ])


def menu_voltar_relatorios_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("⬅️ Voltar", "admin_painel:relatorios")]])


def texto_relatorios_admin() -> str:
    return (
        "📒 *Relatórios*\n\n"
        "Escolha o tipo de relatório que deseja consultar.\n\n"
        "📆 *Relatório Semanal:* acompanha a semana atual e reinicia toda segunda-feira às 00:00.\n"
        "📆 *Relatório Diário:* acompanha o dia atual e reinicia todos os dias após 00:00."
    )


def menu_consultar_vendedores_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("👥 Usuários Registrados", "admin_painel:usuarios")],
        [btn("🔎 Buscar usuário", "admin_painel:buscar_usuario")],
        [btn("💳 Pagamentos Pendentes", "admin_painel:pagamentos_pendentes")],
        [btn("🧾 Últimos pedidos", "admin_painel:ultimos")],
        [btn("⬅️ Voltar ao painel", "admin_painel:inicio")],
    ])


def menu_voltar_consultar_vendedores_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("⬅️ Voltar", "admin_painel:consultar_vendedores")]])


def texto_consultar_vendedores_admin() -> str:
    return (
        "📒 *Consultar Vendedores*\n\n"
        "Escolha uma opção para consultar vendedores, buscar usuários, verificar pagamentos pendentes ou ver últimos pedidos."
    )


def menu_consultar_cadastros_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("⏳ Cadastros Pendentes", "admin_painel:cadastros_pendentes")],
        [btn("✏️ Remover Registro", "admin_painel:remover_registro")],
        [btn("🚫 Banir ou Desbanir", "admin_painel:banir_desbanir")],
        [btn("⬅️ Voltar ao painel", "admin_painel:inicio")],
    ])


def menu_voltar_consultar_cadastros_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("⬅️ Voltar", "admin_painel:consultar_cadastros")]])


def texto_consultar_cadastros_admin() -> str:
    return (
        "📕 *Consultar Cadastros*\n\n"
        "Escolha uma opção para consultar cadastros pendentes, remover registros ou banir/desbanir usuários."
    )


def menu_banir_desbanir_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("🚫 Banir", "admin_painel:banir")],
        [btn("✅ Desbanir", "admin_painel:desbanir")],
        [btn("⬅️ Voltar", "admin_painel:consultar_cadastros")],
    ])


def menu_voltar_painel_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("⬅️ Voltar ao painel", "admin_painel:inicio")]])


def menu_voltar_cargos_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("⬅️ Voltar ao painel", "admin_painel:inicio")]])


def menu_cargos_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("👥 Usuários", "admin_cargos:usuarios:0")],
        [btn("⬅️ Voltar ao painel", "admin_painel:inicio")],
    ])


def texto_painel_admin() -> str:
    return (
        "🛠️ *Painel do Administrador*\n\n"
        "Central de controle da TW STORE para acompanhar resultados, organizar cadastros "
        "e consultar vendedores com praticidade, segurança e agilidade.\n\n"
        "Escolha uma opção abaixo para continuar:"
    )


def texto_gerenciar_cargos_admin() -> str:
    return (
        "🪪 *Cargos*\n\n"
        "Toque em *Usuários* para escolher um cadastro e aplicar ou remover seu cargo.\n\n"
        "*Hierarquia disponível:*\n"
        "• Dono — acesso total\n"
        "• Gerente — painel e recursos administrativos\n"
        "• Secretaria(o) — aprova cadastros e atende suporte\n"
        "• Helper — atende tickets de suporte\n"
        "• Vendedor — uso normal do bot\n"
        "• Vendedor(a) Tester — uso normal com meta semanal\n\n"
        "O Dono pode aplicar qualquer cargo. O Gerente pode aplicar apenas cargos abaixo de Gerente.\n\n"
        "Ao remover um cargo, o usuário volta ao cargo padrão *Vendedor(a) Tester*."
    )


def parse_data_br(texto: str | None) -> datetime | None:
    texto = str(texto or "").strip()
    if not texto:
        return None
    formatos = ["%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]
    for fmt in formatos:
        try:
            dt = datetime.strptime(texto[:19], fmt)
            return dt.replace(tzinfo=TZ_BR)
        except Exception:
            pass
    return None


def parse_data_mercado_pago(texto: str | None) -> datetime | None:
    """Lê datas ISO retornadas pelo Mercado Pago com segurança."""
    texto = str(texto or "").strip()
    if not texto:
        return None

    candidatos = [texto, texto.replace("Z", "+00:00")]
    for candidato in candidatos:
        try:
            dt = datetime.fromisoformat(candidato)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ_BR)
            return dt.astimezone(TZ_BR)
        except Exception:
            pass

    return parse_data_br(texto)


def data_aprovacao_mercado_pago(pagamento: dict) -> datetime | None:
    if not isinstance(pagamento, dict):
        return None
    for chave in ("date_approved", "money_release_date", "date_created", "last_modified"):
        dt = parse_data_mercado_pago(pagamento.get(chave))
        if dt:
            return dt
    return None


def pagamento_aprovado_antes_desta_instancia(pagamento: dict, margem_segundos: int = 0) -> bool:
    """Evita que webhook/pagamento antigo seja reenviado após restart/deploy.

    Se a aprovação aconteceu antes desta instância subir, não dá para saber se
    uma tentativa anterior chegou na plataforma. Por segurança, o pedido vai
    para revisão manual em vez de ser enviado automaticamente de novo.
    """
    aprovado_em = data_aprovacao_mercado_pago(pagamento)
    if not aprovado_em:
        return False
    limite_seguro = BOT_PROCESS_STARTED_AT - timedelta(seconds=max(0, int(margem_segundos)))
    return aprovado_em <= limite_seguro


def formatar_usuario_admin(telegram_id: str, registro: dict) -> str:
    usuario_login = registro.get("usuario_login") or "sem identificação"
    nome = registro.get("nome_telegram") or "Nome não informado"
    username = registro.get("telegram_username") or "Sem @"
    status = registro.get("status") or "sem status"
    cargo = nome_cargo(cargo_usuario_id(telegram_id, registro))
    criado = registro.get("criado_em") or "sem data"
    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *{md(nome)}*\n"
        f"🆔 Telegram ID: `{md(telegram_id)}`\n"
        f"🔐 Login: `{md(usuario_login)}`\n"
        f"📲 Telegram: {md(username)}\n"
        f"🪪 Cargo: *{md(cargo)}*\n"
        f"📌 Status: *{md(status)}*\n"
        f"🗓️ Criado em: {md(criado)}"
    )


def texto_usuarios_aprovados_admin() -> str:
    usuarios = carregar_usuarios_registrados()
    aprovados = [
        (telegram_id, registro)
        for telegram_id, registro in usuarios.items()
        if registro.get("status") == "aprovado"
    ]

    if not aprovados:
        return "👥 *Usuários Registrados*\n\nNenhum usuário aprovado no momento."

    linhas = [f"👥 *Usuários Registrados*\n\nTotal aprovado: *{len(aprovados)}*\n"]
    for telegram_id, registro in aprovados[:80]:
        linhas.append(formatar_usuario_admin(telegram_id, registro))

    if len(aprovados) > 80:
        linhas.append(f"\nMostrando 80 de {len(aprovados)} usuários aprovados.")

    return "\n\n".join(linhas)


def texto_cadastros_pendentes_admin() -> str:
    usuarios = carregar_usuarios_registrados()
    pendentes = [
        (telegram_id, registro)
        for telegram_id, registro in usuarios.items()
        if registro.get("status") == "pendente"
    ]
    if not pendentes:
        return "⏳ *Cadastros Pendentes*\n\nNenhuma solicitação de cadastro pendente."

    linhas = [f"⏳ *Cadastros Pendentes*\n\nTotal: *{len(pendentes)}*\n"]
    for telegram_id, registro in pendentes[:50]:
        linhas.append(formatar_usuario_admin(telegram_id, registro))
    if len(pendentes) > 50:
        linhas.append(f"\nMostrando 50 de {len(pendentes)} cadastros pendentes.")
    return "\n\n".join(linhas)


def texto_pagamentos_pendentes_admin() -> str:
    pedidos = carregar_pedidos_pendentes()
    pendentes = []
    for pedido_id, pedido in pedidos.items():
        status = str(pedido.get("status") or "")
        if status in {"aguardando_pagamento", "aguardando_aprovacao_admin", "aguardando_link", "aguardando_email_iptv"}:
            pendentes.append((pedido_id, pedido))

    if not pendentes:
        return "💳 *Pagamentos/Pedidos Pendentes*\n\nNenhum pedido pendente no momento."

    linhas = [f"💳 *Pagamentos/Pedidos Pendentes*\n\nTotal: *{len(pendentes)}*\n"]
    for pedido_id, pedido in pendentes[:50]:
        linhas.append(
            f"• `{md(pedido_id)}` — *{md(traduzir_status_local(pedido.get('status')))}*\n"
            f"  {md(pedido.get('catalogo', ''))} | {md(pedido.get('servico', ''))}\n"
            f"  Valor: R$ {md(pedido.get('valor', ''))} | Cliente: {md(pedido.get('usuario', ''))}\n"
            f"  Telegram ID: `{md(pedido.get('user_id', ''))}`"
            + (f"\n  Expira em: {md(pedido.get('pagamento_expira_em'))}" if pedido.get('pagamento_expira_em') else "")
        )
    if len(pendentes) > 50:
        linhas.append(f"\nMostrando 50 de {len(pendentes)} pendências.")
    return "\n".join(linhas)


def texto_ultimos_pedidos_admin() -> str:
    historico = carregar_pedidos_historico()
    if not historico:
        return "🧾 *Últimos pedidos*\n\nAinda não há pedidos finalizados no histórico."

    def chave(item):
        pedido = item[1]
        dt = parse_data_br(pedido.get("historico_atualizado_em") or pedido.get("aprovado_em") or pedido.get("criado_em"))
        return dt or datetime.min.replace(tzinfo=TZ_BR)

    itens = sorted(historico.items(), key=chave, reverse=True)[:12]
    linhas = [
        "🧾 *Últimos pedidos finalizados*",
        "",
        f"Mostrando os *{len(itens)}* pedidos mais recentes.",
        "",
    ]

    for pedido_id, pedido in itens:
        data_pedido = (
            pedido.get("historico_atualizado_em")
            or pedido.get("aprovado_em")
            or pedido.get("criado_em")
            or "Não informado"
        )
        linhas.append(
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 *Pedido:* `{md(pedido_id)}`\n"
            f"👤 *Cliente:* {md(pedido.get('usuario') or 'Não informado')}\n"
            f"🆔 *Telegram ID:* `{md(pedido.get('user_id') or 'Não informado')}`\n"
            f"📦 *Serviço:* {md(pedido.get('catalogo') or 'Não informado')} | {md(pedido.get('servico') or 'Não informado')}\n"
            f"💰 *Valor:* R$ {md(pedido.get('valor') or '0,00')}\n"
            f"📌 *Status:* {md(traduzir_status_local(pedido.get('status')))}\n"
            f"🌐 *Pedido plataforma:* `{md(pedido.get('plataforma_order_id') or 'Não informado')}`\n"
            f"🗓️ *Data:* {md(data_pedido)}"
        )

    if len(historico) > len(itens):
        linhas.append(f"\nMostrando 12 de {len(historico)} pedidos no histórico.")

    return "\n\n".join(linhas)


def texto_resumo_admin() -> str:
    usuarios = carregar_usuarios_registrados()
    pedidos_pendentes = carregar_pedidos_pendentes()
    historico = carregar_pedidos_historico()
    hoje = agora_br().date()

    contagem_status = {}
    for registro in usuarios.values():
        status = registro.get("status") or "sem_status"
        contagem_status[status] = contagem_status.get(status, 0) + 1

    pedidos_hoje = 0
    valor_hoje_centavos = 0
    for pedido in historico.values():
        dt = parse_data_br(pedido.get("aprovado_em") or pedido.get("historico_atualizado_em") or pedido.get("criado_em"))
        if dt and dt.date() == hoje:
            pedidos_hoje += 1
            valor_hoje_centavos += valor_para_centavos(pedido.get("valor"))

    webhooks_pendentes = len(DB.listar_webhooks_pendentes(limite=100, max_attempts=WEBHOOK_QUEUE_MAX_ATTEMPTS))

    return (
        "📊 *Resumo do Bot*\n\n"
        f"👥 Usuários aprovados: *{contagem_status.get('aprovado', 0)}*\n"
        f"⏳ Cadastros pendentes: *{contagem_status.get('pendente', 0)}*\n"
        f"🚫 Usuários banidos: *{contagem_status.get('banido', 0)}*\n"
        f"❌ Cadastros negados: *{contagem_status.get('negado', 0)}*\n"
        f"📉 Removidos por meta: *{contagem_status.get('removido_meta', 0)}*\n\n"
        f"💳 Pedidos pendentes: *{len(pedidos_pendentes)}*\n"
        f"🧾 Pedidos finalizados hoje: *{pedidos_hoje}*\n"
        f"💰 Faturamento hoje: *R$ {centavos_para_moeda(valor_hoje_centavos)}*\n"
        f"🔁 Webhooks pendentes/retry: *{webhooks_pendentes}*\n\n"
        f"🗄️ Banco: `{md(DATABASE_PATH.name)}`"
    )


def buscar_usuario_admin(termo: str) -> str:
    termo = str(termo or "").strip()
    if not termo:
        return "⚠️ Envie um Telegram ID, @username, nome ou identificação interna."

    termo_limpo = termo.lower().lstrip("@")
    usuarios = carregar_usuarios_registrados()
    encontrados = []
    for telegram_id, registro in usuarios.items():
        candidatos = [
            str(telegram_id).lower(),
            str(registro.get("usuario_login") or "").lower(),
            str(registro.get("telegram_username") or "").lower().lstrip("@"),
            str(registro.get("nome_telegram") or "").lower(),
        ]
        if any(termo_limpo in c for c in candidatos if c):
            encontrados.append((telegram_id, registro))

    if not encontrados:
        return f"🔎 *Buscar usuário*\n\nNenhum usuário encontrado para: `{md(termo)}`"

    linhas = [f"🔎 *Buscar usuário*\n\nResultado para: `{md(termo)}`\n"]
    for telegram_id, registro in encontrados[:20]:
        linhas.append(formatar_usuario_admin(telegram_id, registro))
    if len(encontrados) > 20:
        linhas.append(f"\nMostrando 20 de {len(encontrados)} resultados.")
    return "\n\n".join(linhas)


async def painel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await bloquear_se_manutencao(update, context):
        return
    if not eh_admin(update):
        await update.message.reply_text("Apenas administradores podem abrir este painel.")
        return
    context.user_data.clear()
    mensagem = await update.message.reply_text(
        texto_painel_admin(),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_painel_admin(update),
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)


async def mostrar_painel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem usar este painel.", show_alert=True)
        return
    context.user_data.clear()
    await safe_edit_or_reply(update, texto_painel_admin(), menu_painel_admin(update))


async def mostrar_notificacoes_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not eh_dono(update):
        await update.callback_query.answer(
            "Somente usuários com cargo Dono podem acessar as notificações.",
            show_alert=True,
        )
        return
    context.user_data.clear()
    await safe_edit_or_reply(
        update,
        texto_notificacoes_admin(),
        menu_notificacoes_admin(),
    )


async def mostrar_manutencao_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not eh_dono(update):
        await update.callback_query.answer(
            "Somente usuários com cargo Dono podem controlar a manutenção.",
            show_alert=True,
        )
        return
    context.user_data.clear()
    await safe_edit_or_reply(
        update,
        texto_manutencao_admin(),
        menu_manutencao_admin(),
    )


async def notificar_inicio_manutencao(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if not eh_dono(update):
        await query.answer(
            "Somente usuários com cargo Dono podem iniciar a manutenção.",
            show_alert=True,
        )
        return

    async with _MANUTENCAO_LOCK:
        if manutencao_ativa():
            await query.answer("A manutenção já está ativa.", show_alert=True)
            await editar_callback_sem_responder(
                query,
                texto_manutencao_admin(),
                menu_manutencao_admin(),
            )
            return

        await query.answer("Ativando manutenção e enviando os avisos...")
        try:
            definir_estado_manutencao(True, update)
        except Exception as exc:
            logging.exception("Falha ao ativar o modo de manutenção: %s", exc)
            await editar_callback_sem_responder(
                query,
                (
                    "❌ *Não foi possível iniciar a manutenção*\n\n"
                    "O estado do bot não foi alterado. Tente novamente."
                ),
                menu_manutencao_admin(),
            )
            return

        await editar_callback_sem_responder(
            query,
            (
                "⏳ *Manutenção ativada*\n\n"
                "O bot já está bloqueado para todos, exceto donos.\n"
                "Enviando a notificação aos usuários registrados..."
            ),
        )
        resultado = await enviar_notificacao_usuarios(
            context.bot,
            MENSAGEM_MANUTENCAO_INICIO,
        )
        try:
            registrar_resultado_notificacao_manutencao("inicio", resultado)
        except Exception as exc:
            logging.warning("Falha ao salvar o resultado da notificação inicial: %s", exc)

        await editar_callback_sem_responder(
            query,
            (
                "✅ *Manutenção iniciada*\n\n"
                "O bot está bloqueado para todos os usuários, exceto quem tem cargo Dono.\n\n"
                f"{resumo_disparo_manutencao(resultado)}"
            ),
            menu_manutencao_admin(),
        )


async def notificar_conclusao_manutencao(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if not eh_dono(update):
        await query.answer(
            "Somente usuários com cargo Dono podem concluir a manutenção.",
            show_alert=True,
        )
        return

    async with _MANUTENCAO_LOCK:
        if not manutencao_ativa():
            await query.answer("O bot já está liberado.", show_alert=True)
            await editar_callback_sem_responder(
                query,
                texto_manutencao_admin(),
                menu_manutencao_admin(),
            )
            return

        await query.answer("Liberando o bot e enviando os avisos...")
        try:
            definir_estado_manutencao(False, update)
        except Exception as exc:
            logging.exception("Falha ao concluir o modo de manutenção: %s", exc)
            await editar_callback_sem_responder(
                query,
                (
                    "❌ *Não foi possível concluir a manutenção*\n\n"
                    "O bot continua bloqueado. Tente novamente."
                ),
                menu_manutencao_admin(),
            )
            return

        await editar_callback_sem_responder(
            query,
            (
                "⏳ *Bot liberado*\n\n"
                "O acesso já foi restaurado.\n"
                "Enviando a notificação de conclusão aos usuários registrados..."
            ),
        )
        resultado = await enviar_notificacao_usuarios(
            context.bot,
            MENSAGEM_MANUTENCAO_CONCLUSAO,
        )
        try:
            registrar_resultado_notificacao_manutencao("conclusao", resultado)
        except Exception as exc:
            logging.warning("Falha ao salvar o resultado da notificação final: %s", exc)

        await editar_callback_sem_responder(
            query,
            (
                "✅ *Manutenção concluída*\n\n"
                "O bot está liberado para todos os usuários registrados.\n\n"
                f"{resumo_disparo_manutencao(resultado)}"
            ),
            menu_manutencao_admin(),
        )


async def mostrar_menu_relatorios_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem consultar relatórios.", show_alert=True)
        return
    context.user_data.clear()
    await safe_edit_or_reply(update, texto_relatorios_admin(), menu_relatorios_admin())


async def mostrar_relatorio_semanal_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem ver relatórios.", show_alert=True)
        return
    await fechar_semana_se_necessario(context.bot)
    await safe_edit_or_reply(update, texto_relatorio_semanal_painel_admin(), menu_voltar_relatorios_admin())


async def mostrar_relatorio_diario_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem ver relatórios.", show_alert=True)
        return
    await safe_edit_or_reply(update, texto_relatorio_diario_admin(), menu_voltar_relatorios_admin())


async def mostrar_menu_consultar_vendedores_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem consultar vendedores.", show_alert=True)
        return
    context.user_data.clear()
    await safe_edit_or_reply(update, texto_consultar_vendedores_admin(), menu_consultar_vendedores_admin())


async def mostrar_consultar_cadastros_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem consultar cadastros.", show_alert=True)
        return
    context.user_data.clear()
    await safe_edit_or_reply(update, texto_consultar_cadastros_admin(), menu_consultar_cadastros_admin())


async def mostrar_usuarios_aprovados_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem ver os usuários.", show_alert=True)
        return
    await safe_edit_or_reply(update, texto_usuarios_aprovados_admin(), menu_voltar_consultar_vendedores_admin())


async def mostrar_resumo_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Compatibilidade com botões antigos que ainda possam estar abertos no Telegram.
    await mostrar_menu_relatorios_admin(update, context)


async def mostrar_cadastros_pendentes_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem ver cadastros.", show_alert=True)
        return
    await safe_edit_or_reply(update, texto_cadastros_pendentes_admin(), menu_voltar_consultar_cadastros_admin())


async def mostrar_pagamentos_pendentes_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem ver pagamentos.", show_alert=True)
        return
    await safe_edit_or_reply(update, texto_pagamentos_pendentes_admin(), menu_voltar_consultar_vendedores_admin())


async def mostrar_ultimos_pedidos_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem ver pedidos.", show_alert=True)
        return
    await safe_edit_or_reply(update, texto_ultimos_pedidos_admin(), menu_voltar_consultar_vendedores_admin())


async def solicitar_busca_usuario_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem buscar usuários.", show_alert=True)
        return
    context.user_data.clear()
    context.user_data["admin_acao_usuario"] = "buscar_usuario"
    await safe_edit_or_reply(
        update,
        (
            "🔎 *Buscar usuário*\n\n"
            "Envie o Telegram ID, @username, nome ou identificação interna do usuário."
        ),
        menu_voltar_consultar_vendedores_admin(),
    )


CARGOS_USUARIOS_POR_PAGINA = 8


def pagina_cargos_segura(pagina) -> int:
    try:
        return max(0, int(pagina))
    except (TypeError, ValueError):
        return 0


def usuarios_cargos_ordenados() -> list[tuple[str, dict]]:
    usuarios = carregar_usuarios_registrados()
    return sorted(
        (
            (str(telegram_id), registro)
            for telegram_id, registro in usuarios.items()
            if isinstance(registro, dict)
        ),
        key=lambda item: (
            str(item[1].get("usuario_login") or "").casefold(),
            str(item[1].get("nome_telegram") or "").casefold(),
            item[0],
        ),
    )


def pagina_usuarios_cargos(pagina=0) -> tuple[list[tuple[str, dict]], int, int, int]:
    usuarios = usuarios_cargos_ordenados()
    total_paginas = max(1, math.ceil(len(usuarios) / CARGOS_USUARIOS_POR_PAGINA))
    pagina_atual = min(pagina_cargos_segura(pagina), total_paginas - 1)
    inicio = pagina_atual * CARGOS_USUARIOS_POR_PAGINA
    fim = inicio + CARGOS_USUARIOS_POR_PAGINA
    return usuarios[inicio:fim], pagina_atual, total_paginas, len(usuarios)


def nome_botao_usuario_cargos(telegram_id: str, registro: dict) -> str:
    usuario_login = str(registro.get("usuario_login") or "").strip()
    nome = str(registro.get("nome_telegram") or "").strip()
    identificacao = usuario_login or nome or f"ID {telegram_id}"
    return identificacao[:40]


def texto_usuarios_cargos_admin(pagina=0) -> str:
    _, pagina_atual, total_paginas, total_usuarios = pagina_usuarios_cargos(pagina)
    if not total_usuarios:
        return (
            "👥 *Usuários*\n\n"
            "Nenhum usuário cadastrado no momento."
        )
    return (
        "👥 *Usuários*\n\n"
        "Selecione o nome de usuário informado no cadastro para gerenciar seu cargo.\n\n"
        f"📋 *Total de cadastros:* {total_usuarios}\n"
        f"📄 *Página:* {pagina_atual + 1} de {total_paginas}"
    )


def menu_usuarios_cargos_admin(pagina=0) -> InlineKeyboardMarkup:
    usuarios, pagina_atual, total_paginas, _ = pagina_usuarios_cargos(pagina)
    keyboard = [
        [
            btn(
                f"👤 {nome_botao_usuario_cargos(telegram_id, registro)}",
                f"admin_cargos:usuario:{telegram_id}:{pagina_atual}",
            )
        ]
        for telegram_id, registro in usuarios
    ]

    navegacao = []
    if pagina_atual > 0:
        navegacao.append(btn("⬅️ Anterior", f"admin_cargos:usuarios:{pagina_atual - 1}"))
    if pagina_atual + 1 < total_paginas:
        navegacao.append(btn("Próxima ➡️", f"admin_cargos:usuarios:{pagina_atual + 1}"))
    if navegacao:
        keyboard.append(navegacao)

    keyboard.append([btn("⬅️ Voltar para Cargos", "admin_painel:cargos")])
    return InlineKeyboardMarkup(keyboard)


def texto_usuario_cargos_admin(telegram_id: str, registro: dict) -> str:
    return (
        "👤 *Gerenciar cargo do usuário*\n\n"
        f"🔐 *Usuário do cadastro:* `{md(registro.get('usuario_login') or 'Não informado')}`\n"
        f"👤 *Nome no Telegram:* {md(registro.get('nome_telegram') or 'Não informado')}\n"
        f"🆔 *Telegram ID:* `{md(telegram_id)}`\n"
        f"📌 *Status:* {md(registro.get('status') or 'Não informado')}\n"
        f"🪪 *Cargo atual:* {md(nome_cargo(cargo_usuario_id(telegram_id, registro)))}\n\n"
        "Escolha se deseja aplicar outro cargo ou remover o cargo atual.\n"
        "Ao remover, o usuário volta para *Vendedor(a) Tester*."
    )


def menu_acoes_cargo_usuario_admin(telegram_id: str, pagina=0) -> InlineKeyboardMarkup:
    pagina_atual = pagina_cargos_segura(pagina)
    return InlineKeyboardMarkup([
        [btn("🪪 Aplicar cargo", f"admin_cargos:aplicar:{telegram_id}:{pagina_atual}")],
        [btn("➖ Remover cargo", f"admin_cargos:remover:{telegram_id}:{pagina_atual}")],
        [btn("⬅️ Voltar para Usuários", f"admin_cargos:usuarios:{pagina_atual}")],
    ])


def menu_voltar_usuario_cargos_admin(telegram_id: str, pagina=0) -> InlineKeyboardMarkup:
    pagina_atual = pagina_cargos_segura(pagina)
    return InlineKeyboardMarkup([
        [btn("⬅️ Voltar ao usuário", f"admin_cargos:usuario:{telegram_id}:{pagina_atual}")],
        [btn("👥 Voltar para Usuários", f"admin_cargos:usuarios:{pagina_atual}")],
    ])


def menu_escolher_cargo_admin(
    telegram_id: str,
    cargo_autor: str,
    pagina=0,
) -> InlineKeyboardMarkup:
    pagina_atual = pagina_cargos_segura(pagina)
    keyboard = []
    for cargo_chave, cargo_info in CARGOS.items():
        if pode_atribuir_cargo(cargo_autor, cargo_chave):
            keyboard.append([
                btn(
                    f"🪪 {cargo_info['nome']}",
                    f"admin_cargo:{cargo_chave}:{telegram_id}:{pagina_atual}",
                )
            ])
    keyboard.append([
        btn(
            "⬅️ Voltar ao usuário",
            f"admin_cargos:usuario:{telegram_id}:{pagina_atual}",
        )
    ])
    return InlineKeyboardMarkup(keyboard)


async def mostrar_gerenciar_cargos_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not usuario_tem_permissao_update(update, PERMISSAO_GERENCIAR_CARGOS):
        await update.callback_query.answer("Seu cargo não pode gerenciar cargos.", show_alert=True)
        return
    context.user_data.clear()
    await safe_edit_or_reply(
        update,
        texto_gerenciar_cargos_admin(),
        menu_cargos_admin(),
    )


async def mostrar_usuarios_cargos_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pagina=0,
):
    if not usuario_tem_permissao_update(update, PERMISSAO_GERENCIAR_CARGOS):
        await update.callback_query.answer("Seu cargo não pode gerenciar cargos.", show_alert=True)
        return
    context.user_data.clear()
    await safe_edit_or_reply(
        update,
        texto_usuarios_cargos_admin(pagina),
        menu_usuarios_cargos_admin(pagina),
    )


async def mostrar_usuario_cargos_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: str,
    pagina=0,
):
    query = update.callback_query
    if not usuario_tem_permissao_update(update, PERMISSAO_GERENCIAR_CARGOS):
        await query.answer("Seu cargo não pode gerenciar cargos.", show_alert=True)
        return

    registro = obter_usuario_registrado(telegram_id)
    if not registro:
        await query.answer("Este cadastro não existe mais.", show_alert=True)
        return

    context.user_data.clear()
    await safe_edit_or_reply(
        update,
        texto_usuario_cargos_admin(str(telegram_id), registro),
        menu_acoes_cargo_usuario_admin(str(telegram_id), pagina),
    )


async def mostrar_escolher_cargo_usuario_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: str,
    pagina=0,
):
    query = update.callback_query
    autor_id = telegram_id_update(update)
    cargo_autor = cargo_usuario_update(update)

    if not usuario_tem_permissao_update(update, PERMISSAO_GERENCIAR_CARGOS):
        await query.answer("Seu cargo não pode aplicar cargos.", show_alert=True)
        return
    if id_administrador_sistema(telegram_id):
        await query.answer("O administrador principal configurado no servidor tem cargo protegido.", show_alert=True)
        return
    if str(telegram_id) == autor_id:
        await query.answer("Você não pode alterar o próprio cargo por este painel.", show_alert=True)
        return

    registro = obter_usuario_registrado(telegram_id)
    if not registro or registro.get("status") != "aprovado":
        await query.answer("O usuário precisa estar registrado e aprovado.", show_alert=True)
        return

    cargo_atual = cargo_usuario_id(telegram_id, registro)
    if not pode_gerenciar_cargo(cargo_autor, cargo_atual):
        await query.answer("Você não pode alterar um usuário de cargo igual ou superior ao seu.", show_alert=True)
        return

    context.user_data.clear()
    await safe_edit_or_reply(
        update,
        (
            "🪪 *Escolha o novo cargo*\n\n"
            f"🔐 *Usuário:* `{md(registro.get('usuario_login') or 'Não informado')}`\n"
            f"👤 *Nome:* {md(registro.get('nome_telegram') or 'Não informado')}\n"
            f"🆔 *Telegram ID:* `{md(telegram_id)}`\n"
            f"📌 *Cargo atual:* {md(nome_cargo(cargo_atual))}"
        ),
        menu_escolher_cargo_admin(str(telegram_id), cargo_autor, pagina),
    )


async def enviar_cadastros_pendentes_para_aprovador(
    context: ContextTypes.DEFAULT_TYPE,
    aprovador_id: str,
):
    """Entrega também os cadastros que já estavam pendentes ao aplicar o cargo."""
    usuarios = carregar_usuarios_registrados()
    alterado = False
    for telegram_id, registro in list(usuarios.items()):
        if registro.get("status") != "pendente":
            continue
        try:
            mensagem = await context.bot.send_message(
                chat_id=aprovador_id,
                text=texto_solicitacao_registro_admin(telegram_id, registro),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=botoes_aprovacao_registro(telegram_id),
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logging.warning(
                "Falha ao enviar cadastro pendente %s ao novo aprovador %s: %s",
                telegram_id,
                aprovador_id,
                exc,
            )
            continue

        referencias = mensagens_admin_registro(registro)
        referencias.append(
            {
                "chat_id": str(mensagem.chat.id if mensagem.chat else aprovador_id),
                "message_id": mensagem.message_id,
            }
        )
        registro["mensagens_admin_registro"] = referencias
        usuarios[str(telegram_id)] = registro
        alterado = True

    if alterado:
        salvar_usuarios_registrados(usuarios)


async def aplicar_cargo_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    cargo_novo: str,
    telegram_id: str,
    pagina=0,
):
    query = update.callback_query
    autor_id = telegram_id_update(update)
    cargo_autor = cargo_usuario_update(update)
    cargo_novo = normalizar_cargo(cargo_novo)

    if not usuario_tem_permissao_update(update, PERMISSAO_GERENCIAR_CARGOS):
        await query.answer("Seu cargo não pode aplicar cargos.", show_alert=True)
        return
    if id_administrador_sistema(telegram_id):
        await query.answer("O administrador principal configurado no servidor tem cargo protegido.", show_alert=True)
        return
    if telegram_id == autor_id:
        await query.answer("Você não pode alterar o próprio cargo por este painel.", show_alert=True)
        return

    usuarios = carregar_usuarios_registrados()
    registro = usuarios.get(str(telegram_id))
    if not registro or registro.get("status") != "aprovado":
        await query.answer("O usuário precisa estar registrado e aprovado.", show_alert=True)
        return

    cargo_atual = cargo_usuario_id(telegram_id, registro)
    if not pode_gerenciar_cargo(cargo_autor, cargo_atual):
        await query.answer("Você não pode alterar um usuário de cargo igual ou superior ao seu.", show_alert=True)
        return
    if not pode_atribuir_cargo(cargo_autor, cargo_novo):
        await query.answer("Você não pode aplicar esse cargo.", show_alert=True)
        return
    if cargo_atual == cargo_novo:
        await query.answer("Esse usuário já possui o cargo selecionado.", show_alert=True)
        return

    aplicado_por = (
        update.effective_user.full_name
        if update.effective_user
        else f"ID {autor_id}"
    )
    definir_cargo_registro(registro, cargo_novo, aplicado_por, "painel_cargos")
    usuarios[str(telegram_id)] = registro
    salvar_usuarios_registrados(usuarios)

    nome_novo = nome_cargo(cargo_novo)
    aviso_meta = ""
    if cargo_novo == CARGO_TESTER:
        aviso_meta = (
            f"\n\nSua meta é de R$ {centavos_para_moeda(META_SEMANAL_TESTER_CENTAVOS)} por semana. "
            "Se ela não for alcançada até o fechamento semanal, seu acesso será removido "
            "e precisará de nova aprovação."
        )
    try:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=f"🪪 Seu cargo no bot agora é: {nome_novo}.{aviso_meta}",
        )
    except Exception as exc:
        logging.warning("Falha ao avisar usuário %s sobre o novo cargo: %s", telegram_id, exc)

    if cargo_tem_permissao(cargo_novo, PERMISSAO_APROVAR_CADASTROS):
        await enviar_cadastros_pendentes_para_aprovador(context, telegram_id)
    if cargo_tem_permissao(cargo_novo, PERMISSAO_ATENDER_SUPORTE):
        for ticket_aberto in DB.listar_tickets_abertos(limite=50):
            await notificar_equipe_novo_ticket(
                context,
                ticket_aberto,
                destinatarios=[telegram_id],
            )

    context.user_data.clear()
    await safe_edit_or_reply(
        update,
        (
            "✅ *Cargo aplicado com sucesso*\n\n"
            f"🆔 *Telegram ID:* `{md(telegram_id)}`\n"
            f"👤 *Usuário:* {md(registro.get('nome_telegram') or 'Não informado')}\n"
            f"🪪 *Cargo anterior:* {md(nome_cargo(cargo_atual))}\n"
            f"🪪 *Novo cargo:* {md(nome_novo)}"
        ),
        menu_voltar_usuario_cargos_admin(str(telegram_id), pagina),
    )


async def remover_cargo_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: str,
    pagina=0,
):
    """Remove o cargo atual e restaura o cargo-base Vendedor(a) Tester."""
    query = update.callback_query
    autor_id = telegram_id_update(update)
    cargo_autor = cargo_usuario_update(update)

    if not usuario_tem_permissao_update(update, PERMISSAO_GERENCIAR_CARGOS):
        await query.answer("Seu cargo não pode remover cargos.", show_alert=True)
        return
    if id_administrador_sistema(telegram_id):
        await query.answer("O administrador principal configurado no servidor tem cargo protegido.", show_alert=True)
        return
    if str(telegram_id) == autor_id:
        await query.answer("Você não pode alterar o próprio cargo por este painel.", show_alert=True)
        return

    usuarios = carregar_usuarios_registrados()
    registro = usuarios.get(str(telegram_id))
    if not registro or registro.get("status") != "aprovado":
        await query.answer("O usuário precisa estar registrado e aprovado.", show_alert=True)
        return

    cargo_atual = cargo_usuario_id(telegram_id, registro)
    if not pode_gerenciar_cargo(cargo_autor, cargo_atual):
        await query.answer("Você não pode alterar um usuário de cargo igual ou superior ao seu.", show_alert=True)
        return
    if cargo_atual == CARGO_TESTER:
        await query.answer("Esse usuário já está com o cargo padrão Vendedor(a) Tester.", show_alert=True)
        return
    if not pode_atribuir_cargo(cargo_autor, CARGO_TESTER):
        await query.answer("Você não pode restaurar o cargo padrão desse usuário.", show_alert=True)
        return

    removido_por = (
        update.effective_user.full_name
        if update.effective_user
        else f"ID {autor_id}"
    )
    definir_cargo_registro(
        registro,
        CARGO_TESTER,
        removido_por,
        "remocao_cargo_painel",
    )
    registro["cargo_removido"] = cargo_atual
    registro["cargo_removido_em"] = registro["cargo_aplicado_em"]
    registro["cargo_removido_por"] = removido_por
    usuarios[str(telegram_id)] = registro
    salvar_usuarios_registrados(usuarios)

    try:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                f"➖ Seu cargo {nome_cargo(cargo_atual)} foi removido.\n\n"
                "Seu cargo agora é Vendedor(a) Tester.\n"
                f"Meta semanal: R$ {centavos_para_moeda(META_SEMANAL_TESTER_CENTAVOS)}."
            ),
        )
    except Exception as exc:
        logging.warning("Falha ao avisar usuário %s sobre a remoção do cargo: %s", telegram_id, exc)

    context.user_data.clear()
    await safe_edit_or_reply(
        update,
        (
            "✅ *Cargo removido com sucesso*\n\n"
            f"🔐 *Usuário:* `{md(registro.get('usuario_login') or 'Não informado')}`\n"
            f"🆔 *Telegram ID:* `{md(telegram_id)}`\n"
            f"➖ *Cargo removido:* {md(nome_cargo(cargo_atual))}\n"
            "🪪 *Cargo atual:* Vendedor(a) Tester"
        ),
        menu_voltar_usuario_cargos_admin(str(telegram_id), pagina),
    )


async def mostrar_menu_banir_desbanir_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem usar esta opção.", show_alert=True)
        return
    context.user_data.clear()
    await safe_edit_or_reply(
        update,
        (
            "🚫 *Banir ou Desbanir*\n\n"
            "Escolha se deseja banir ou desbanir um usuário pelo Telegram ID."
        ),
        menu_banir_desbanir_admin(),
    )


async def solicitar_banimento_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem banir usuários.", show_alert=True)
        return
    context.user_data.clear()
    context.user_data["admin_acao_usuario"] = "banir"
    await safe_edit_or_reply(
        update,
        (
            "🚫 *Banir usuário*\n\n"
            "Envie agora o *Telegram ID* do usuário que será banido.\n\n"
            "Exemplo:\n"
            "`123456789`"
        ),
        InlineKeyboardMarkup([[btn("⬅️ Voltar", "admin_painel:banir_desbanir")]]),
    )


async def solicitar_desbanimento_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem desbanir usuários.", show_alert=True)
        return
    context.user_data.clear()
    context.user_data["admin_acao_usuario"] = "desbanir"
    await safe_edit_or_reply(
        update,
        (
            "✅ *Desbanir usuário*\n\n"
            "Envie agora o *Telegram ID* do usuário que será desbanido.\n\n"
            "Exemplo:\n"
            "`123456789`"
        ),
        InlineKeyboardMarkup([[btn("⬅️ Voltar", "admin_painel:banir_desbanir")]]),
    )


async def solicitar_remover_registro_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem remover registros.", show_alert=True)
        return
    context.user_data.clear()
    context.user_data["admin_acao_usuario"] = "remover_registro"
    await safe_edit_or_reply(
        update,
        (
            "✏️ *Remover Registro*\n\n"
            "Envie agora o *Telegram ID* do usuário que terá o registro removido.\n\n"
            "Depois disso, o cliente terá que passar pelo cadastro novamente para usar o bot.\n\n"
            "Exemplo:\n"
            "`123456789`"
        ),
        menu_voltar_consultar_cadastros_admin(),
    )


async def remover_registro_telegram_id_pelo_painel(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: str) -> str:
    admin_id = str(update.effective_user.id) if update.effective_user else ""
    if telegram_id == admin_id or id_administrador_sistema(telegram_id):
        return "⚠️ Não é permitido remover o registro de administradores do bot."

    usuarios = carregar_usuarios_registrados()
    registro = usuarios.get(telegram_id)
    if not registro:
        return "⚠️ Não encontrei esse Telegram ID no cadastro do bot."
    if not pode_gerenciar_cargo(cargo_usuario_update(update), cargo_usuario_id(telegram_id, registro)):
        return "⚠️ Você não pode remover um usuário de cargo igual ou superior ao seu."

    usuario_login = registro.get("usuario_login") or "sem identificação"
    nome = registro.get("nome_telegram") or "Nome não informado"
    usuarios.pop(telegram_id, None)
    salvar_usuarios_registrados(usuarios)

    try:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                "✏️ Seu registro foi removido pelo administrador.\n\n"
                "Para voltar a usar o bot, toque em /start e faça o cadastro novamente."
            ),
        )
    except Exception:
        pass

    return (
        "✅ Registro removido com sucesso.\n\n"
        f"Telegram ID: `{md(telegram_id)}`\n"
        f"Nome: {md(nome)}\n"
        f"ID interno: `{md(usuario_login)}`\n\n"
        "Quando esse cliente tocar em /start, ele precisará se registrar novamente."
    )


async def banir_telegram_id_pelo_painel(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: str) -> str:
    admin_id = str(update.effective_user.id) if update.effective_user else ""
    if telegram_id == admin_id or id_administrador_sistema(telegram_id):
        return "⚠️ Não é permitido banir administradores do bot."

    usuarios = carregar_usuarios_registrados()
    registro = usuarios.get(telegram_id, {"telegram_id": telegram_id})
    if not pode_gerenciar_cargo(cargo_usuario_update(update), cargo_usuario_id(telegram_id, registro)):
        return "⚠️ Você não pode banir um usuário de cargo igual ou superior ao seu."
    registro["status"] = "banido"
    registro["motivo_ban"] = "Banido pelo administrador"
    registro["banido_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    registro["banido_por"] = update.effective_user.full_name if update.effective_user else "Administrador"
    registro["atualizado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    registro.pop("tentar_novamente_em", None)
    usuarios[telegram_id] = registro
    salvar_usuarios_registrados(usuarios)

    try:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                "🚫 *Acesso bloqueado*\n\n"
                "Você foi banido de usar este bot.\n\n"
                "📌 *Motivo*\n"
                "• Banido pelo administrador\n\n"
                "Se você acredita que isso foi um engano, fale com o suporte."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass

    return f"🚫 Usuário `{md(telegram_id)}` banido com sucesso."


async def desbanir_telegram_id_pelo_painel(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: str) -> str:
    usuarios = carregar_usuarios_registrados()
    registro = usuarios.get(telegram_id)
    if not registro:
        return "⚠️ Não encontrei esse Telegram ID no cadastro do bot."
    if id_administrador_sistema(telegram_id):
        return "⚠️ O administrador principal configurado no servidor tem cargo protegido."
    if not pode_gerenciar_cargo(cargo_usuario_update(update), cargo_usuario_id(telegram_id, registro)):
        return "⚠️ Você não pode desbanir um usuário de cargo igual ou superior ao seu."

    registro["status"] = "aprovado"
    registro["desbanido_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    registro["desbanido_por"] = update.effective_user.full_name if update.effective_user else "Administrador"
    registro["atualizado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    registro.pop("motivo_ban", None)
    registro.pop("tentar_novamente_em", None)
    usuarios[telegram_id] = registro
    salvar_usuarios_registrados(usuarios)

    try:
        await context.bot.send_message(chat_id=telegram_id, text="✅ Seu acesso ao bot foi liberado novamente. Toque em /start.")
    except Exception:
        pass

    return f"✅ Usuário `{md(telegram_id)}` desbanido e aprovado novamente."


async def processar_texto_admin_painel(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_usuario: str) -> bool:
    acao = context.user_data.get("admin_acao_usuario")
    if not acao:
        return False

    if not eh_admin(update):
        context.user_data.pop("admin_acao_usuario", None)
        return False

    if acao == "buscar_usuario":
        resposta = buscar_usuario_admin(texto_usuario)
        context.user_data.clear()
        await update.message.reply_text(
            resposta,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_voltar_consultar_vendedores_admin(),
            disable_web_page_preview=True,
        )
        return True

    telegram_id = re.sub(r"\D+", "", texto_usuario)
    if not telegram_id:
        if acao == "remover_registro":
            voltar_markup = menu_voltar_consultar_cadastros_admin()
        elif acao == "aplicar_cargo":
            voltar_markup = menu_voltar_cargos_admin()
        else:
            voltar_markup = InlineKeyboardMarkup([[btn("⬅️ Voltar", "admin_painel:banir_desbanir")]])
        await update.message.reply_text(
            "⚠️ Envie apenas o Telegram ID numérico. Exemplo: `123456789`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=voltar_markup,
        )
        return True

    if acao == "aplicar_cargo":
        usuarios = carregar_usuarios_registrados()
        registro = usuarios.get(telegram_id)
        if not registro or registro.get("status") != "aprovado":
            await update.message.reply_text(
                "⚠️ Não encontrei um usuário registrado e aprovado com esse Telegram ID.",
                reply_markup=menu_voltar_cargos_admin(),
            )
            return True
        if id_administrador_sistema(telegram_id):
            await update.message.reply_text(
                "⚠️ Esse ID pertence ao administrador configurado no servidor e tem cargo protegido.",
                reply_markup=menu_voltar_cargos_admin(),
            )
            return True

        cargo_autor = cargo_usuario_update(update)
        cargo_atual = cargo_usuario_id(telegram_id, registro)
        if not pode_gerenciar_cargo(cargo_autor, cargo_atual):
            await update.message.reply_text(
                "⚠️ Você não pode alterar um usuário de cargo igual ou superior ao seu.",
                reply_markup=menu_voltar_cargos_admin(),
            )
            return True

        context.user_data.clear()
        await update.message.reply_text(
            (
                "🪪 *Escolha o novo cargo*\n\n"
                f"👤 *Usuário:* {md(registro.get('nome_telegram') or 'Não informado')}\n"
                f"🆔 *Telegram ID:* `{md(telegram_id)}`\n"
                f"📌 *Cargo atual:* {md(nome_cargo(cargo_atual))}"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_escolher_cargo_admin(telegram_id, cargo_autor),
        )
        return True

    if acao == "banir":
        resposta = await banir_telegram_id_pelo_painel(update, context, telegram_id)
        reply_markup = menu_banir_desbanir_admin()
    elif acao == "desbanir":
        resposta = await desbanir_telegram_id_pelo_painel(update, context, telegram_id)
        reply_markup = menu_banir_desbanir_admin()
    elif acao == "remover_registro":
        resposta = await remover_registro_telegram_id_pelo_painel(update, context, telegram_id)
        reply_markup = menu_consultar_cadastros_admin()
    else:
        resposta = "⚠️ Ação inválida. Abra o /painel novamente."
        reply_markup = menu_painel_admin(update)

    context.user_data.clear()
    await update.message.reply_text(
        resposta,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    return True


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
    dados = DB.carregar_totais_semanais() or novo_registro_semanal()
    if "semana_id" not in dados or "clientes" not in dados:
        return novo_registro_semanal()
    return dados


def salvar_totais_semanais(dados: dict):
    DB.salvar_totais_semanais(dados)


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


def saldo_usuario_centavos(user_id) -> int:
    return DB.obter_saldo_centavos(str(user_id or ""))


def parse_valor_recarga_centavos(valor) -> int | None:
    """Aceita valores como 5, 5,50 ou 5.50 sem arredondamentos ambíguos."""
    texto = str(valor or "").strip().replace("R$", "").replace("r$", "").strip()
    texto = re.sub(r"\s+", "", texto)
    if not re.fullmatch(r"\d+(?:[,.]\d{1,2})?", texto):
        return None
    try:
        decimal = Decimal(texto.replace(",", "."))
        centavos = int((decimal * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, OverflowError):
        return None
    return centavos


def calcular_taxa_recarga_centavos(valor_saldo_centavos: int) -> int:
    valor = Decimal(int(valor_saldo_centavos or 0))
    percentual = Decimal(TAXA_RECARGA_PERCENTUAL) / Decimal(100)
    return int((valor * percentual).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def aplicar_taxa_recarga(recarga: dict) -> dict:
    """Define o saldo creditado, a taxa e o total do Pix sem usar float."""
    valor_saldo_centavos = int(recarga.get("valor_centavos") or 0)
    taxa_centavos = calcular_taxa_recarga_centavos(valor_saldo_centavos)
    valor_pagamento_centavos = valor_saldo_centavos + taxa_centavos
    recarga.update(
        {
            "taxa_percentual": TAXA_RECARGA_PERCENTUAL,
            "taxa_centavos": taxa_centavos,
            "valor_pagamento_centavos": valor_pagamento_centavos,
            "valor_saldo": centavos_para_moeda(valor_saldo_centavos),
            "taxa": centavos_para_moeda(taxa_centavos),
            "valor_pagamento": centavos_para_moeda(valor_pagamento_centavos),
        }
    )
    return recarga


def gerar_recarga_saldo_id() -> str:
    return f"RC{agora_br():%Y%m%d%H%M%S}{secrets.token_hex(3).upper()}"


def bloco_cliente_relatorio_admin(cliente: dict, posicao: int | None = None) -> str:
    username = f"@{cliente.get('username')}" if cliente.get("username") else "Sem username"
    total_centavos = int(cliente.get("total_centavos", 0))
    pedidos = int(cliente.get("pedidos", 0))
    cabecalho = "━━━━━━━━━━━━━━━━━━━━"
    if posicao is not None:
        cabecalho = f"━━━━━━━━━━━━━━━━━━━━\n🏅 *Posição:* {posicao}º"

    return (
        f"{cabecalho}\n"
        f"👤 *Cliente:* {md(cliente.get('usuario', 'Cliente'))}\n"
        f"📲 *Telegram:* {md(username)}\n"
        f"🆔 *Telegram ID:* `{md(cliente.get('user_id', ''))}`\n"
        f"💰 *Total usado:* R$ {md(centavos_para_moeda(total_centavos))}\n"
        f"🧾 *Pedidos pagos:* {pedidos}"
    )


def montar_texto_relatorio_clientes_admin(
    titulo: str,
    periodo: str,
    clientes_map: dict,
    observacao_reinicio: str,
    limite_clientes: int = 60,
) -> str:
    clientes = list((clientes_map or {}).values())
    clientes.sort(key=lambda item: int(item.get("total_centavos", 0)), reverse=True)

    total_geral = sum(int(cliente.get("total_centavos", 0)) for cliente in clientes)
    total_pedidos = sum(int(cliente.get("pedidos", 0)) for cliente in clientes)

    linhas = [
        titulo,
        "",
        f"🗓️ *Período:* {md(periodo)}",
        f"💰 *Total geral:* R$ {md(centavos_para_moeda(total_geral))}",
        f"🧾 *Pedidos pagos:* {total_pedidos}",
        f"👥 *Clientes:* {len(clientes)}",
        f"🔄 {md(observacao_reinicio)}",
    ]

    if not clientes:
        linhas.extend(["", "Ainda não há pedidos pagos neste período."])
        return "\n".join(linhas)

    linhas.extend(["", "*Valores usados por cliente:*"])
    for posicao, cliente in enumerate(clientes[:limite_clientes], start=1):
        linhas.append(bloco_cliente_relatorio_admin(cliente, posicao))

    if len(clientes) > limite_clientes:
        linhas.append(f"\nMostrando {limite_clientes} de {len(clientes)} clientes.")

    texto = "\n\n".join(linhas)
    if len(texto) > 3900:
        texto = texto[:3850].rsplit("\n", 1)[0] + "\n\nRelatório muito grande. Mostrando apenas os primeiros registros."
    return texto


def texto_relatorio_semanal_painel_admin() -> str:
    dados = carregar_totais_semanais()
    if "semana_id" not in dados or "clientes" not in dados:
        dados = novo_registro_semanal()

    periodo = f"{dados.get('inicio', '')} até {dados.get('fim', '')}"
    return montar_texto_relatorio_clientes_admin(
        "📆 *RELATÓRIO SEMANAL — TW STORE*",
        periodo,
        dados.get("clientes", {}),
        "Reinicia toda segunda-feira às 00:00.",
    )


def montar_clientes_periodo_por_historico(inicio: datetime, fim: datetime) -> dict:
    historico = carregar_pedidos_historico()
    clientes = {}

    for pedido in historico.values():
        if str(pedido.get("status") or "") != "pagamento_aprovado":
            continue

        data_pedido = parse_data_br(
            pedido.get("aprovado_em")
            or pedido.get("historico_atualizado_em")
            or pedido.get("criado_em")
        )
        if not data_pedido or data_pedido < inicio or data_pedido >= fim:
            continue

        user_id = str(pedido.get("user_id") or "sem_id")
        valor_centavos = valor_para_centavos(pedido.get("valor", "0"))
        cliente = clientes.setdefault(
            user_id,
            {
                "user_id": pedido.get("user_id") or "sem_id",
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

    return clientes


def texto_relatorio_diario_admin() -> str:
    agora = agora_br()
    inicio = datetime.combine(agora.date(), time.min, tzinfo=TZ_BR)
    fim = inicio + timedelta(days=1)
    clientes = montar_clientes_periodo_por_historico(inicio, fim)

    return montar_texto_relatorio_clientes_admin(
        "📆 *RELATÓRIO DIÁRIO — TW STORE*",
        inicio.strftime("%d/%m/%Y"),
        clientes,
        "Reinicia todos os dias após 00:00.",
    )


def pedidos_cliente_periodo(user_id: str, inicio: datetime, fim: datetime) -> list[dict]:
    historico = carregar_pedidos_historico()
    pedidos = []

    for pedido in historico.values():
        if str(pedido.get("status") or "") != "pagamento_aprovado":
            continue
        if str(pedido.get("user_id") or "") != str(user_id):
            continue

        data_pedido = parse_data_br(
            pedido.get("aprovado_em")
            or pedido.get("historico_atualizado_em")
            or pedido.get("criado_em")
        )
        if not data_pedido or data_pedido < inicio or data_pedido >= fim:
            continue

        pedido_copia = dict(pedido)
        pedido_copia["_data_relatorio"] = data_pedido
        pedidos.append(pedido_copia)

    pedidos.sort(key=lambda item: item.get("_data_relatorio") or inicio, reverse=True)
    return pedidos


def bloco_pedido_relatorio_cliente(pedido: dict) -> str:
    data_pedido = pedido.get("_data_relatorio")
    if isinstance(data_pedido, datetime):
        data_texto = data_pedido.strftime("%d/%m/%Y %H:%M:%S")
    else:
        data_texto = pedido.get("aprovado_em") or pedido.get("historico_atualizado_em") or "Não informado"

    pedido_plataforma = pedido.get("plataforma_order_id") or pedido.get("pedido_plataforma") or "Não informado"

    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 *Pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
        f"📦 *Serviço:* {md(pedido.get('servico', 'Não informado'))}\n"
        f"🗂️ *Catálogo:* {md(pedido.get('catalogo', 'Não informado'))}\n"
        f"💰 *Valor:* R$ {md(centavos_para_moeda(valor_para_centavos(pedido.get('valor', '0'))))}\n"
        f"🌐 *Pedido plataforma:* {md(pedido_plataforma)}\n"
        f"🗓️ *Realizado em:* {md(data_texto)}"
    )


def texto_my_profile_cliente(update: Update) -> str:
    user = update.effective_user
    user_id = str(user.id) if user else ""
    nome = user.full_name if user else "Cliente"
    username = f"@{user.username}" if user and user.username else "Sem username"
    registro = obter_usuario_registrado(user_id)
    cargo = cargo_usuario_id(user_id, registro)
    saldo_centavos = saldo_usuario_centavos(user_id)

    agora = agora_br()
    inicio = datetime.combine(agora.date(), time.min, tzinfo=TZ_BR)
    fim = inicio + timedelta(days=1)
    pedidos = pedidos_cliente_periodo(user_id, inicio, fim)

    total_centavos = sum(valor_para_centavos(pedido.get("valor", "0")) for pedido in pedidos)

    linhas = [
        "👤 *Meu Perfil*",
        "",
        "📆 *Relatório Diário*",
        f"🗓️ *Data:* {md(inicio.strftime('%d/%m/%Y'))}",
        f"👤 *Cliente:* {md(nome)}",
        f"📲 *Telegram:* {md(username)}",
        f"🆔 *Telegram ID:* `{md(user_id)}`",
        f"🪪 *Cargo:* {md(nome_cargo(cargo))}",
        f"💳 *Saldo disponível:* R$ {md(centavos_para_moeda(saldo_centavos))}",
        f"💰 *Total usado hoje:* R$ {md(centavos_para_moeda(total_centavos))}",
        f"🧾 *Pedidos realizados hoje:* {len(pedidos)}",
        "🔄 Reinicia todos os dias após 00:00.",
    ]

    if cargo == CARGO_TESTER:
        totais_semana = carregar_totais_semanais()
        cliente_semana = (totais_semana.get("clientes") or {}).get(user_id) or {}
        total_semana = int(cliente_semana.get("total_centavos") or 0)
        restante = max(0, META_SEMANAL_TESTER_CENTAVOS - total_semana)
        linhas.extend(
            [
                "",
                "🎯 *Meta semanal de Tester*",
                f"• Realizado: R$ {md(centavos_para_moeda(total_semana))}",
                f"• Meta: R$ {md(centavos_para_moeda(META_SEMANAL_TESTER_CENTAVOS))}",
                f"• Falta: R$ {md(centavos_para_moeda(restante))}",
                f"• Período: {md(totais_semana.get('inicio', ''))} até {md(totais_semana.get('fim', ''))}",
            ]
        )

    if not pedidos:
        linhas.extend(["", "Você ainda não tem pedidos realizados hoje."])
        return "\n".join(linhas)

    linhas.extend(["", "*Seus pedidos realizados hoje:*"])
    for pedido in pedidos[:12]:
        linhas.append(bloco_pedido_relatorio_cliente(pedido))

    if len(pedidos) > 12:
        linhas.append(f"\nMostrando 12 de {len(pedidos)} pedidos realizados hoje.")

    texto = "\n\n".join(linhas)
    if len(texto) > 3900:
        texto = texto[:3850].rsplit("\n", 1)[0] + "\n\nRelatório muito grande. Mostrando apenas os primeiros registros."
    return texto


def menu_my_profile_cliente() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("⬅️ Voltar", "voltar:inicio")]])


async def enviar_resumo_semanal_admin(bot, dados: dict):
    destinatarios = ids_admin_relatorio_semanal()
    if not destinatarios or not dados.get("clientes"):
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

    for posicao, cliente in enumerate(clientes, start=1):
        linhas.append(bloco_cliente_relatorio_admin(cliente, posicao))

    texto = "\n\n".join(linhas)

    # Evita erro caso o relatório fique muito grande.
    partes = []
    while len(texto) > 3900:
        corte = texto.rfind("\n", 0, 3900)
        if corte == -1:
            corte = 3900
        partes.append(texto[:corte])
        texto = texto[corte:].lstrip()
    partes.append(texto)

    for admin_id in destinatarios:
        for parte in partes:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=parte,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
            except Exception as exc:
                logging.warning("Falha ao enviar fechamento semanal para admin %s: %s", admin_id, exc)


async def aplicar_meta_semanal_testers(bot, dados_semana: dict) -> list[dict]:
    """Remove o acesso de testers abaixo da meta e exige uma nova aprovação."""
    usuarios = carregar_usuarios_registrados()
    clientes = (dados_semana or {}).get("clientes") or {}
    removidos = []

    for telegram_id, registro in list(usuarios.items()):
        if registro.get("status") != "aprovado":
            continue
        if cargo_usuario_id(telegram_id, registro) != CARGO_TESTER:
            continue

        cliente = clientes.get(str(telegram_id)) or {}
        total_centavos = int(cliente.get("total_centavos") or 0)
        if total_centavos >= META_SEMANAL_TESTER_CENTAVOS:
            registro["ultima_meta_semanal_status"] = "atingida"
            registro["ultima_meta_semanal_total_centavos"] = total_centavos
            registro["ultima_meta_semanal_id"] = dados_semana.get("semana_id")
            registro["atualizado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
            continue

        registro["status"] = "removido_meta"
        registro["reaprovacao_obrigatoria"] = True
        registro["meta_semanal_total_centavos"] = total_centavos
        registro["meta_semanal_exigida_centavos"] = META_SEMANAL_TESTER_CENTAVOS
        registro["meta_semanal_id"] = dados_semana.get("semana_id")
        registro["meta_semanal_inicio"] = dados_semana.get("inicio")
        registro["meta_semanal_fim"] = dados_semana.get("fim")
        registro["removido_meta_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
        registro["atualizado_em"] = registro["removido_meta_em"]
        DB.fechar_tickets_usuario(telegram_id, "Acesso removido por meta semanal")
        removidos.append(
            {
                "telegram_id": str(telegram_id),
                "nome": registro.get("nome_telegram") or "Não informado",
                "total_centavos": total_centavos,
            }
        )

    if not removidos:
        if usuarios:
            salvar_usuarios_registrados(usuarios)
        return []

    salvar_usuarios_registrados(usuarios)

    for item in removidos:
        try:
            await bot.send_message(
                chat_id=item["telegram_id"],
                text=(
                    "📉 *Acesso removido por meta semanal*\n\n"
                    "Você não alcançou a meta semanal do cargo Vendedor(a) Tester.\n\n"
                    f"💰 *Total realizado:* R$ {md(centavos_para_moeda(item['total_centavos']))}\n"
                    f"🎯 *Meta exigida:* R$ {md(centavos_para_moeda(META_SEMANAL_TESTER_CENTAVOS))}\n\n"
                    "Seu acesso foi removido automaticamente. Para voltar ao bot, toque em /start, "
                    "faça o cadastro novamente e aguarde uma nova aprovação."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as exc:
            logging.warning("Falha ao avisar tester %s sobre remoção: %s", item["telegram_id"], exc)

    linhas = [
        "📉 *TESTERS REMOVIDOS POR META*",
        "",
        f"🗓️ *Semana:* {md(dados_semana.get('inicio', ''))} até {md(dados_semana.get('fim', ''))}",
        f"🎯 *Meta:* R$ {md(centavos_para_moeda(META_SEMANAL_TESTER_CENTAVOS))}",
        f"👥 *Total removido:* {len(removidos)}",
        "",
    ]
    for item in removidos[:60]:
        linhas.append(
            f"• {md(item['nome'])} — `{md(item['telegram_id'])}` — "
            f"R$ {md(centavos_para_moeda(item['total_centavos']))}"
        )
    resumo = "\n".join(linhas)
    for admin_id in ids_admin_relatorio_semanal():
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=resumo,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as exc:
            logging.warning("Falha ao enviar resumo de testers removidos para %s: %s", admin_id, exc)
    return removidos


async def fechar_semana_se_necessario(bot):
    async with _FECHAMENTO_SEMANAL_LOCK:
        dados = carregar_totais_semanais()
        semana_atual = semana_info()

        if dados.get("semana_id") != semana_atual["id"]:
            await enviar_resumo_semanal_admin(bot, dados)
            await aplicar_meta_semanal_testers(bot, dados)
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


async def rotina_limpeza_pagamentos_expirados(application: Application):
    while True:
        try:
            expirados = await asyncio.to_thread(fechar_pagamentos_expirados_sync)
            for item in expirados:
                await avisar_cliente_pagamento_expirado(
                    application.bot,
                    item.get("pedido_id"),
                    item.get("user_id"),
                    item.get("motivo", ""),
                )
        except Exception as exc:
            logging.warning("Falha na limpeza de pagamentos expirados: %s", exc)

        intervalo = max(60, int(PAGAMENTOS_PENDENTES_LIMPEZA_INTERVALO or 300))
        await asyncio.sleep(intervalo)


async def iniciar_rotinas(application: Application):
    application.create_task(rotina_fechamento_semanal(application))
    application.create_task(rotina_limpeza_pagamentos_expirados(application))



def md(texto) -> str:
    return escape_markdown(str(texto), version=1)


def money(valor: str) -> str:
    return f"R$ {valor}"


CATALOGOS_COM_ENVIO_API = {
    "Instagram",
    "Instagram — Serviços Brasileiros",
    "Instagram_Brasileiros",
    "TikTok",
    "Kwai",
}

CATALOGOS_COM_EMAIL = {
    "IPTV XCIPTV",
    "IPTV Livestream 4K",
    "Internet Ilimitada",
    "Assinaturas",
}


def catalogo_exige_email(pedido_ou_catalogo) -> bool:
    if isinstance(pedido_ou_catalogo, dict):
        if str(pedido_ou_catalogo.get("tipo_destino") or "").strip().lower() == "email":
            return True
        catalogo = str(pedido_ou_catalogo.get("catalogo") or "").strip()
    else:
        catalogo = str(pedido_ou_catalogo or "").strip()

    return catalogo in CATALOGOS_COM_EMAIL or "assinatura" in catalogo.lower()


class PlataformaAPIConfigError(Exception):
    pass


class PlataformaAPIRequestError(Exception):
    pass


class PlataformaEstoqueIndisponivel(Exception):
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
        # Chave fixa por pedido: evita Pix duplicado em retries do mesmo pedido.
        headers["X-Idempotency-Key"] = f"tw-store-{pedido_id}"
    return headers


def criar_pagamento_mercado_pago_sync(pedido: dict) -> dict:
    if not MERCADO_PAGO_ACCESS_TOKEN:
        raise MercadoPagoConfigError("MERCADO_PAGO_ACCESS_TOKEN não configurado.")

    pedido_id = str(pedido.get("pedido_id") or gerar_pedido_id())
    pedido["pedido_id"] = pedido_id

    descricao = f"{pedido.get('catalogo', 'Pedido')} - {pedido.get('servico', '')} - {pedido.get('quantidade', '')}".strip()
    valor_cobranca = (
        pedido.get("valor_pagamento")
        if pedido.get("tipo_pagamento") == "recarga_saldo"
        else pedido.get("valor")
    )
    payload = {
        "transaction_amount": valor_pedido_float(valor_cobranca),
        "description": descricao[:250],
        "payment_method_id": "pix",
        "external_reference": pedido_id,
        "payer": {
            "email": MP_PAYER_EMAIL or "cliente@ttwostore.com",
        },
    }
    if pagamento_pendente_expiracao_ativa():
        expira_em = agora_br() + timedelta(minutes=int(PAGAMENTOS_PENDENTES_EXPIRAR_MINUTOS))
        payload["date_of_expiration"] = formatar_data_expiracao_mercado_pago(expira_em)
        pedido["pagamento_expira_em"] = expira_em.strftime("%d/%m/%Y %H:%M:%S")
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
    if pagamento_pendente_expiracao_ativa() and not pedido.get("pagamento_expira_em"):
        pedido["pagamento_expira_em"] = (
            agora_br() + timedelta(minutes=int(PAGAMENTOS_PENDENTES_EXPIRAR_MINUTOS))
        ).strftime("%d/%m/%Y %H:%M:%S")


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


def preparar_recarga_saldo(update: Update, valor_centavos: int) -> dict:
    valor_centavos = int(valor_centavos or 0)
    if not SALDO_MINIMO_RECARGA_CENTAVOS <= valor_centavos <= SALDO_MAXIMO_RECARGA_CENTAVOS:
        raise ValueError("A recarga deve ficar entre R$ 5,00 e R$ 300,00.")
    user = update.effective_user
    recarga_id = gerar_recarga_saldo_id()
    recarga = {
        "recarga_id": recarga_id,
        # O gerador de Pix usa pedido_id como referência externa. Nesta operação,
        # ele recebe o próprio ID da recarga e nunca entra na tabela de pedidos.
        "pedido_id": recarga_id,
        "tipo_pagamento": "recarga_saldo",
        "catalogo": "Carteira TW Store",
        "servico": "Adicionar saldo",
        "quantidade": "1 recarga",
        "valor": centavos_para_moeda(valor_centavos),
        "valor_centavos": int(valor_centavos),
        "status": "criando_pix",
        "user_id": user.id if user else update.effective_chat.id,
        "usuario": user.full_name if user else "Cliente",
        "username": user.username if user else None,
        "criado_em": agora_br().strftime("%d/%m/%Y %H:%M:%S"),
    }
    return aplicar_taxa_recarga(recarga)


async def garantir_pix_recarga_saldo(recarga: dict) -> tuple[bool, str]:
    valor_centavos = int(recarga.get("valor_centavos") or 0)
    if not SALDO_MINIMO_RECARGA_CENTAVOS <= valor_centavos <= SALDO_MAXIMO_RECARGA_CENTAVOS:
        return False, "A recarga deve ficar entre R$ 5,00 e R$ 300,00."
    # Preserva Pix antigos, gerados antes da cobrança da taxa. A taxa só é
    # calculada quando um novo pagamento será criado.
    if recarga.get("mp_payment_id") and recarga.get("mp_qr_code"):
        DB.salvar_recarga_saldo(recarga.get("recarga_id"), recarga)
        return True, "Pix da recarga já criado."

    aplicar_taxa_recarga(recarga)
    if not mercado_pago_configurado():
        return False, "Mercado Pago não configurado para confirmar recargas automaticamente."

    try:
        pagamento = await asyncio.to_thread(criar_pagamento_mercado_pago_sync, recarga)
    except Exception as exc:
        return False, limpar_erro_api(exc)

    aplicar_pagamento_mercado_pago_no_pedido(recarga, pagamento)
    recarga["recarga_id"] = str(recarga.get("recarga_id") or recarga.get("pedido_id") or "")
    recarga["tipo_pagamento"] = "recarga_saldo"
    DB.salvar_recarga_saldo(recarga["recarga_id"], recarga)
    return True, "Pix da recarga criado."


def pagamento_recarga_aprovado_e_valido(recarga: dict, pagamento: dict) -> tuple[bool, str]:
    if str(pagamento.get("status") or "").lower() != "approved":
        return False, f"Status ainda não aprovado: {pagamento.get('status')}"

    recarga_id = str(recarga.get("recarga_id") or "")
    external_reference = str(pagamento.get("external_reference") or "")
    if external_reference and external_reference != recarga_id:
        return False, "A referência do pagamento não pertence a esta recarga."

    # Recargas antigas, criadas antes da taxa, não possuem valor_pagamento_centavos.
    esperado = int(
        recarga.get("valor_pagamento_centavos")
        or recarga.get("valor_centavos")
        or 0
    )
    try:
        recebido = int(
            (Decimal(str(pagamento.get("transaction_amount") or "0")) * 100).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
    except (InvalidOperation, ValueError, TypeError):
        recebido = 0
    if esperado <= 0 or recebido != esperado:
        return False, f"Valor divergente. Esperado {esperado} centavos, recebido {recebido} centavos."

    payment_id = str(pagamento.get("id") or "").strip()
    if not payment_id:
        return False, "O pagamento aprovado não possui ID."
    return True, "OK"


def marcar_pagamento_recarga_processado(payment_id: str, recarga: dict):
    if not payment_id:
        return
    DB.salvar_pagamento_processado(
        str(payment_id),
        {
            "tipo": "recarga_saldo",
            "recarga_id": recarga.get("recarga_id"),
            "user_id": recarga.get("user_id"),
            "valor": recarga.get("valor"),
            "valor_saldo": recarga.get("valor_saldo") or recarga.get("valor"),
            "taxa_percentual": recarga.get("taxa_percentual"),
            "taxa": recarga.get("taxa"),
            "valor_pagamento": recarga.get("valor_pagamento") or recarga.get("valor"),
            "processado_em": agora_br().strftime("%d/%m/%Y %H:%M:%S"),
        },
    )


def processar_recarga_aprovada_sync(
    recarga: dict,
    pagamento: dict,
    origem: str = "webhook",
) -> bool:
    if not recarga:
        return False

    payment_id = str(pagamento.get("id") or recarga.get("mp_payment_id") or "").strip()
    recarga_id = str(recarga.get("recarga_id") or "").strip()
    if recarga.get("status") == "aprovada":
        if payment_id:
            marcar_pagamento_recarga_processado(payment_id, recarga)
        return True
    if not payment_id or not recarga_id:
        return False
    if not iniciar_processamento_pagamento(payment_id):
        recarga_atual = DB.obter_recarga_saldo(recarga_id)
        return bool(recarga_atual and recarga_atual.get("status") == "aprovada")

    try:
        valido, motivo = pagamento_recarga_aprovado_e_valido(recarga, pagamento)
        if not valido:
            logging.warning("Recarga %s não creditada: %s", recarga_id, motivo)
            return False

        resultado = DB.creditar_recarga_saldo(
            recarga_id,
            payment_id,
            {
                "payment_id": payment_id,
                "status": pagamento.get("status"),
                "external_reference": pagamento.get("external_reference"),
                "transaction_amount": pagamento.get("transaction_amount"),
                "origem": origem,
            },
        )
        recarga_atual = DB.obter_recarga_saldo(recarga_id) or recarga
        marcar_pagamento_recarga_processado(payment_id, recarga_atual)

        if resultado.get("creditada"):
            saldo_centavos = int(resultado.get("saldo_centavos") or 0)
            if origem != "verificacao_cliente":
                enviar_telegram_sync(
                    recarga_atual.get("user_id"),
                    texto_confirmacao_recarga(recarga_atual, saldo_centavos)
                    + "\n\nSeu saldo já pode ser usado nos pedidos.",
                    reply_markup={
                        "inline_keyboard": [
                            [{"text": "🛒 Continuar pedido", "callback_data": "saldo:retomar_pedido"}],
                            [{"text": "💳 Consultar saldo", "callback_data": "saldo:consultar"}],
                            [{"text": "🏠 Menu inicial", "callback_data": "voltar:inicio"}],
                        ]
                    },
                )
            logging.info("Recarga %s creditada via %s.", recarga_id, origem)
        return True
    finally:
        finalizar_processamento_pagamento(payment_id)


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
    return DB.carregar_pagamentos_processados()


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
    DB.salvar_pagamentos_processados(dados)


def obter_pedido_historico_por_pagamento(payment_id: str | None = None, external_reference: str | None = None) -> dict | None:
    """Localiza pagamentos já finalizados no histórico.

    Isso é uma trava importante para restart: se o Mercado Pago reenviar um
    webhook antigo, o bot reconhece que o pedido já saiu dos pendentes e não
    tenta criar outro pedido na plataforma.
    """
    historico = carregar_pedidos_historico()

    if external_reference and str(external_reference) in historico:
        return historico[str(external_reference)]

    for pedido in historico.values():
        if payment_id and str(pedido.get("mp_payment_id") or "") == str(payment_id):
            return pedido
        if external_reference and str(pedido.get("pedido_id") or "") == str(external_reference):
            return pedido
    return None


def reconstruir_pagamentos_processados_do_historico():
    """Recria a trava de pagamentos processados a partir do histórico.

    Em deploys/reinícios onde a tabela/JSON de pagamentos processados ficou
    vazio, os pedidos pagos ainda aparecem no histórico. Esta rotina evita que
    webhooks antigos voltem a acionar o envio automático na plataforma.
    """
    reconstruidos = 0
    for pedido in carregar_pedidos_historico().values():
        payment_id = str(pedido.get("mp_payment_id") or "").strip()
        if not payment_id or pagamento_ja_processado(payment_id):
            continue
        marcar_pagamento_processado(payment_id, pedido)
        reconstruidos += 1
    if reconstruidos:
        logging.info("Trava de pagamentos reconstruída pelo histórico: %s registro(s).", reconstruidos)


def pedido_ja_enviado_para_plataforma(pedido: dict) -> bool:
    if not pedido:
        return False
    if pedido.get("plataforma_api_status") == "enviado":
        return True
    return pedido_tem_id_plataforma(pedido.get("plataforma_order_id"))


def status_envio_plataforma(pedido: dict) -> str:
    return str((pedido or {}).get("plataforma_api_status") or "").strip().lower()


def envio_plataforma_bloqueado_para_auto(pedido: dict) -> bool:
    """Estados que nunca devem chamar a API automaticamente de novo."""
    status_api = status_envio_plataforma(pedido)
    return status_api in {"processando", "revisao_manual", "erro", "ignorado_manual", "resolvido_manual", "ignorado_restart"}


def envio_plataforma_estava_processando(pedido: dict) -> bool:
    """Detecta pedido salvo no meio do envio para a plataforma.

    Se o Railway reiniciar depois que o bot marcou o pedido como
    "processando", mas antes de gravar o ID retornado pela plataforma, não é
    seguro chamar a API novamente: a primeira chamada pode ter criado o pedido
    mesmo sem o bot ter conseguido salvar a resposta. Nessa situação o bot
    finaliza o pagamento e manda para revisão manual, evitando duplicidade.
    """
    if not pedido:
        return False
    return status_envio_plataforma(pedido) == "processando" and not pedido_ja_enviado_para_plataforma(pedido)


def marcar_envio_plataforma_para_revisao_manual(pedido: dict, origem: str = "restart", motivo: str | None = None):
    pedido["plataforma_api_status"] = "revisao_manual"
    pedido["plataforma_api_erro"] = motivo or (
        "Envio automático pausado por segurança: o bot/servidor reiniciou "
        "ou um webhook antigo foi recebido enquanto este pedido podia já ter sido enviado "
        "para a plataforma. Confira no painel da plataforma se o pedido já foi criado "
        "antes de reenviar manualmente."
    )
    pedido["plataforma_revisao_manual_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido["plataforma_revisao_manual_origem"] = origem


def callback_revisao_manual(acao: str, pedido_id: str) -> str:
    pedido_id = re.sub(r"[^A-Za-z0-9_-]+", "", str(pedido_id or ""))[:36]
    return f"admin_revisao_{acao}:{pedido_id}"


def botoes_revisao_manual_admin_dict(pedido_id: str) -> dict:
    return {
        "inline_keyboard": [
            [{"text": "✅ Já foi feito", "callback_data": callback_revisao_manual("feito", pedido_id)}],
            [{"text": "🔁 Reenviar para plataforma", "callback_data": callback_revisao_manual("reenviar", pedido_id)}],
            [{"text": "❌ Ignorar pendência", "callback_data": callback_revisao_manual("ignorar", pedido_id)}],
        ]
    }


def botoes_revisao_manual_admin(pedido_id: str) -> InlineKeyboardMarkup:
    dados = botoes_revisao_manual_admin_dict(pedido_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(botao["text"], callback_data=botao["callback_data"]) for botao in linha]
        for linha in dados["inline_keyboard"]
    ])


def texto_alerta_revisao_manual_admin(pedido: dict, origem: str = "startup") -> str:
    return (
        "⚠️ *PEDIDO EM REVISÃO MANUAL*\n\n"
        "O pagamento foi confirmado, mas o envio automático foi bloqueado para evitar duplicidade.\n\n"
        f"🆔 *Pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
        f"💳 *Mercado Pago ID:* `{md(pedido.get('mp_payment_id', ''))}`\n"
        f"🗂️ *Catálogo:* {md(pedido.get('catalogo', ''))}\n"
        f"📌 *Serviço:* {md(pedido.get('servico', ''))}\n"
        f"🔢 *Quantidade:* {md(pedido.get('quantidade', ''))}\n"
        f"🔗 *Link/@:* {md(pedido.get('link', ''))}\n"
        f"👤 *Cliente:* {md(pedido.get('usuario') or 'Cliente')} — `{md(pedido.get('user_id') or '')}`\n\n"
        f"🚫 *Motivo:* {md(pedido.get('plataforma_api_erro') or 'Envio automático bloqueado por segurança.')}\n\n"
        "Antes de reenviar, confira na plataforma se esse pedido já existe."
    )


def notificar_admin_revisao_manual_sync(pedido: dict, origem: str = "startup"):
    admin_id = str(ADMIN_CHAT_ID or "").strip()
    if not admin_id or not pedido:
        return
    if pedido.get("plataforma_revisao_admin_notificado"):
        return
    enviar_telegram_sync(
        admin_id,
        texto_alerta_revisao_manual_admin(pedido, origem),
        reply_markup=botoes_revisao_manual_admin_dict(str(pedido.get("pedido_id") or "")),
    )
    pedido["plataforma_revisao_admin_notificado"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")


def corrigir_pedidos_com_envio_interrompido():
    """Fecha pedidos que ficaram salvos como processando após queda/restart.

    O objetivo é não reenviar automaticamente um pedido para a plataforma se o
    bot caiu no intervalo entre a chamada da API e a gravação do ID retornado.
    """
    corrigidos = 0
    for pedido_id, pedido in list(carregar_pedidos_pendentes().items()):
        if pedido.get("catalogo") not in CATALOGOS_COM_ENVIO_API:
            continue
        if not envio_plataforma_bloqueado_para_auto(pedido):
            continue
        if pedido_ja_enviado_para_plataforma(pedido):
            continue

        if status_envio_plataforma(pedido) != "revisao_manual":
            marcar_envio_plataforma_para_revisao_manual(pedido, origem="startup")
        if str(pedido.get("status") or "").strip().lower() == "pagamento_aprovado":
            notificar_admin_revisao_manual_sync(pedido, origem="startup")
            salvar_pedido_historico(pedido)
            payment_id = str(pedido.get("mp_payment_id") or "").strip()
            if payment_id:
                marcar_pagamento_processado(payment_id, pedido)
            remover_pedido_pendente(str(pedido_id))
        else:
            salvar_pedido_pendente(pedido)
        corrigidos += 1

    if corrigidos:
        logging.warning(
            "Pedido(s) com envio interrompido movidos para revisão manual: %s",
            corrigidos,
        )



STATUS_PENDENTES_LIMPEZA_STARTUP = {
    "aguardando_link",
    "aguardando_email_iptv",
    "aguardando_pagamento",
    "aguardando_aprovacao_admin",
    "pendente",
}

STATUS_PAGOS_LIMPEZA_STARTUP = {
    "pagamento_aprovado",
    "pago",
    "paid",
    "approved",
}


def pedido_pago_confirmado_local(pedido: dict) -> bool:
    """Detecta pedido já pago usando apenas dados locais salvos."""
    if not pedido:
        return False
    status_local = str(pedido.get("status") or "").strip().lower()
    status_mp = str(pedido.get("mp_status") or "").strip().lower()
    return (
        status_local in STATUS_PAGOS_LIMPEZA_STARTUP
        or status_mp == "approved"
        or bool(pedido.get("aprovado_em"))
    )


def recuperar_pedido_debitado_no_startup(pedido: dict):
    """Avisa equipe e cliente quando um débito foi salvo antes de uma queda."""
    if str(pedido.get("forma_pagamento") or "") != "saldo":
        return
    try:
        total_semanal = registrar_pedido_semanal(pedido)
        enviar_relatorio_admin_documento_sync(
            pedido,
            total_semanal,
            titulo="PEDIDO COM SALDO RECUPERADO APÓS REINÍCIO — TW STORE",
        )
        enviar_telegram_sync(
            pedido.get("user_id"),
            texto_final_pedido(pedido),
            reply_markup={
                "inline_keyboard": [
                    [{"text": "🔎 Consultar Pedido", "callback_data": "pedido:consultar"}],
                    [{"text": "🏠 Menu inicial", "callback_data": "voltar:inicio"}],
                ]
            },
        )
    except Exception as exc:
        logging.exception(
            "Falha ao recuperar pedido debitado %s após reinício: %s",
            pedido.get("pedido_id"),
            exc,
        )


def limpar_persistencia_transiente_no_startup():
    """Remove user_data antigo para botões de pagamento velhos não reprocessarem pedidos."""
    if not LIMPAR_PEDIDOS_PENDENTES_AO_INICIAR:
        return
    if not BOT_PERSISTENCE_PATH.exists():
        return
    backup = BOT_PERSISTENCE_PATH.with_suffix(BOT_PERSISTENCE_PATH.suffix + f".limpo-{agora_br():%Y%m%d%H%M%S}.bak")
    try:
        shutil.move(str(BOT_PERSISTENCE_PATH), str(backup))
        logging.warning("Persistência antiga do bot movida para %s para limpar pedidos antigos em user_data.", backup)
    except Exception as exc:
        logging.warning("Não foi possível limpar a persistência antiga %s: %s", BOT_PERSISTENCE_PATH, exc)


def limpar_pedidos_pendentes_salvos_no_startup():
    """Remove pendências antigas antes de processar webhooks no restart.

    Isso impede que o Railway, ao reiniciar o bot, reenvie para a plataforma
    pedidos que já tinham ficado salvos em pedidos_pendentes.
    Pedidos pagos são movidos para o histórico e o pagamento fica marcado como
    processado; pedidos não pagos são encerrados e removidos da fila de pendentes.
    """
    if not LIMPAR_PEDIDOS_PENDENTES_AO_INICIAR:
        logging.info("Limpeza de pedidos pendentes no startup desativada por configuração.")
        return

    pedidos = carregar_pedidos_pendentes()
    if not pedidos:
        return

    removidos_pendentes = 0
    pagos_bloqueados = 0
    outros_removidos = 0

    for pedido_id, pedido in list(pedidos.items()):
        pedido = dict(pedido or {})
        pedido_id = str(pedido_id or pedido.get("pedido_id") or "").strip()
        if not pedido_id:
            continue
        pedido["pedido_id"] = pedido_id

        status_local = str(pedido.get("status") or "").strip().lower()
        pago = pedido_pago_confirmado_local(pedido)

        if pago:
            pedido["status"] = "pagamento_aprovado"
            pedido.setdefault("aprovado_em", pedido.get("historico_atualizado_em") or agora_br().strftime("%d/%m/%Y %H:%M:%S"))
            if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API and not pedido_ja_enviado_para_plataforma(pedido):
                pedido["plataforma_api_status"] = "ignorado_restart"
                pedido["plataforma_api_erro"] = (
                    "Pedido pago removido da fila de pendentes ao iniciar o bot para impedir "
                    "reenvio automático após restart do Railway. Se precisar, reenvie manualmente."
                )
                pedido["plataforma_resolucao_manual"] = "ignorado_startup"
                pedido["plataforma_resolvido_manual_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
                pagos_bloqueados += 1
            else:
                outros_removidos += 1

            pedido["removido_de_pendentes_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
            pedido["removido_de_pendentes_motivo"] = "Limpeza automática no startup: pagamento já estava aprovado."
            salvar_pedido_historico(pedido)
            payment_id = str(pedido.get("mp_payment_id") or "").strip()
            if payment_id:
                marcar_pagamento_processado(payment_id, pedido)
            remover_pedido_pendente(pedido_id)
            recuperar_pedido_debitado_no_startup(pedido)
            continue

        if status_local in STATUS_PENDENTES_LIMPEZA_STARTUP or not status_local:
            pedido["status"] = "pendente_removido_restart"
            pedido["removido_de_pendentes_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
            pedido["removido_de_pendentes_motivo"] = (
                "Pedido pendente encerrado automaticamente ao iniciar o bot para evitar reprocessamento."
            )
            salvar_pedido_historico(pedido)
            remover_pedido_pendente(pedido_id)
            removidos_pendentes += 1
            continue

        # Qualquer outro registro dentro de pedidos_pendentes também sai da fila,
        # porque manter pendência antiga é o que causa reenvio no restart.
        pedido["removido_de_pendentes_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
        pedido["removido_de_pendentes_motivo"] = (
            f"Removido automaticamente do pending no startup. Status anterior: {status_local or 'sem status'}."
        )
        salvar_pedido_historico(pedido)
        remover_pedido_pendente(pedido_id)
        outros_removidos += 1

    total = removidos_pendentes + pagos_bloqueados + outros_removidos
    if total:
        try:
            salvar_json(PEDIDOS_PENDENTES_PATH, {})
        except Exception as exc:
            logging.warning("Não foi possível limpar JSON legado de pedidos pendentes: %s", exc)

        logging.warning(
            "Limpeza startup: %s pedido(s) removidos de pendentes; %s pendente(s) encerrado(s), %s pago(s) bloqueado(s) contra reenvio, %s outro(s).",
            total,
            removidos_pendentes,
            pagos_bloqueados,
            outros_removidos,
        )


def pagamento_antigo_sem_trava_deve_ir_para_revisao(pedido: dict, pagamento: dict) -> bool:
    if not pedido or pedido.get("catalogo") not in CATALOGOS_COM_ENVIO_API:
        return False
    if pedido_ja_enviado_para_plataforma(pedido) or envio_plataforma_bloqueado_para_auto(pedido):
        return False
    return pagamento_aprovado_antes_desta_instancia(pagamento)


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


def enviar_telegram_sync(chat_id, text: str, reply_markup: dict | None = None, parse_mode: str = "Markdown") -> bool:
    if not BOT_TOKEN or not chat_id:
        return False
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        resposta = requests.post(telegram_api_url("sendMessage"), json=payload, timeout=20)
        if not resposta.ok:
            logging.warning("Falha ao enviar mensagem Telegram via API: %s", resposta.text[:300])
        return resposta.ok
    except Exception as exc:
        logging.warning("Falha ao enviar mensagem Telegram via API: %s", exc)
        return False


def texto_relatorio_valor(valor, padrao: str = "Não informado") -> str:
    texto = str(valor or "").strip()
    return texto if texto else padrao


def valor_relatorio_reais(valor) -> str:
    texto = texto_relatorio_valor(valor, "0,00")
    if texto.upper().startswith("R$"):
        return texto
    return f"R$ {texto}"


def username_relatorio(pedido: dict) -> str:
    username = str(pedido.get("username") or "").strip()
    return f"@{username}" if username else "Sem username"


def status_api_relatorio(pedido: dict) -> tuple[str, list[tuple[str, str]]]:
    if pedido.get("catalogo") not in CATALOGOS_COM_ENVIO_API:
        return "SEM ENVIO AUTOMÁTICO", [
            ("Status", "Catálogo sem integração de envio automático"),
        ]

    if pedido.get("plataforma_api_status") == "enviado":
        return "ENVIADO PARA PLATAFORMA", [
            ("Status", "Enviado com sucesso"),
            ("Pedido na plataforma", texto_relatorio_valor(pedido.get("plataforma_order_id"))),
            ("Service ID", texto_relatorio_valor(pedido.get("plataforma_service_id"))),
            ("Quantidade enviada", texto_relatorio_valor(pedido.get("plataforma_quantidade"), texto_relatorio_valor(pedido.get("quantidade")))),
        ]

    if pedido.get("plataforma_api_status") == "revisao_manual":
        return "REVISÃO MANUAL", [
            ("Status", "Envio automático pausado para evitar duplicidade"),
            ("Motivo", texto_relatorio_valor(pedido.get("plataforma_api_erro"), "Conferir na plataforma antes de reenviar")),
        ]

    return "ATENÇÃO NO ENVIO", [
        ("Status", "Falhou, pausado ou não configurado"),
        ("Erro", texto_relatorio_valor(pedido.get("plataforma_api_erro"), "Sem retorno da API")),
    ]


def blocos_relatorio_admin(pedido: dict, total_semanal_cliente: str, titulo: str | None = None, data_relatorio: str | None = None):
    data_relatorio = data_relatorio or pedido.get("aprovado_em") or agora_br().strftime("%d/%m/%Y %H:%M:%S")
    api_titulo, api_linhas = status_api_relatorio(pedido)
    mp_id = texto_relatorio_valor(pedido.get("mp_payment_id"), "Não informado")
    origem = texto_relatorio_valor(pedido.get("processado_por"), "Não informado")
    destino_label = "E-mail" if catalogo_exige_email(pedido) else "Link/@"
    por_saldo = pedido.get("forma_pagamento") == "saldo"
    if por_saldo:
        titulo_financeiro = "SALDO DA CARTEIRA"
        linhas_financeiras = [
            ("Valor descontado", valor_relatorio_reais(pedido.get("valor"))),
            ("Saldo antes", f"R$ {centavos_para_moeda(int(pedido.get('saldo_antes_centavos') or 0))}"),
            ("Saldo restante", f"R$ {centavos_para_moeda(int(pedido.get('saldo_apos_centavos') or 0))}"),
            ("Total do cliente na semana", valor_relatorio_reais(total_semanal_cliente)),
            ("Confirmado por", texto_relatorio_valor(pedido.get("aprovado_por"), "Saldo da carteira")),
            ("Data", data_relatorio),
        ]
    else:
        titulo_financeiro = "PAGAMENTO"
        linhas_financeiras = [
            ("Valor aprovado", valor_relatorio_reais(pedido.get("valor"))),
            ("Total do cliente na semana", valor_relatorio_reais(total_semanal_cliente)),
            ("Mercado Pago ID", mp_id),
            ("Aprovado por", texto_relatorio_valor(pedido.get("aprovado_por"), "Mercado Pago")),
            ("Processamento", origem),
            ("Data", data_relatorio),
        ]

    blocos = [
        (
            "DADOS DO PEDIDO",
            [
                ("ID do pedido", texto_relatorio_valor(pedido.get("pedido_id"))),
                ("Catálogo", texto_relatorio_valor(pedido.get("catalogo"))),
                ("Serviço", texto_relatorio_valor(pedido.get("servico"))),
                ("Quantidade", texto_relatorio_valor(pedido.get("quantidade"))),
                (destino_label, texto_relatorio_valor(pedido.get("link"))),
            ],
        ),
        (titulo_financeiro, linhas_financeiras),
        (
            "CLIENTE",
            [
                ("Nome", texto_relatorio_valor(pedido.get("usuario"), "Cliente")),
                ("Telegram", username_relatorio(pedido)),
                ("ID Telegram", texto_relatorio_valor(pedido.get("user_id"))),
            ],
        ),
        (api_titulo, api_linhas),
    ]
    return blocos


def montar_relatorio_admin_texto(pedido: dict, total_semanal_cliente: str, titulo: str = "NOVO PEDIDO PAGO — TW STORE") -> str:
    username = username_relatorio(pedido)
    destino_label = "E-mail" if catalogo_exige_email(pedido) else "Link/@"
    destino_emoji = "📧" if catalogo_exige_email(pedido) else "🔗"
    if pedido.get("forma_pagamento") == "saldo":
        linha_financeira = (
            "💳 *Forma:* Saldo da carteira\n"
            f"💰 *Saldo restante:* R$ {md(centavos_para_moeda(int(pedido.get('saldo_apos_centavos') or 0)))}\n"
        )
    else:
        linha_financeira = f"💳 *Mercado Pago ID:* `{md(pedido.get('mp_payment_id', 'Não informado'))}`\n"

    bloco_api = ""
    if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
        if pedido.get("plataforma_api_status") == "enviado":
            bloco_api = (
                f"🚀 *API plataforma:* Enviado\n"
                f"🆔 *Pedido na plataforma:* `{md(pedido.get('plataforma_order_id', 'Não informado'))}`\n"
                f"🔧 *Service ID:* `{md(pedido.get('plataforma_service_id', ''))}`\n"
            )
        elif pedido.get("plataforma_api_status") == "revisao_manual":
            bloco_api = (
                f"⚠️ *API plataforma:* Revisão manual\n"
                f"🚫 *Motivo:* {md(pedido.get('plataforma_api_erro', 'Conferir na plataforma antes de reenviar'))}\n"
            )
        else:
            bloco_api = (
                f"🚀 *API plataforma:* Falhou, pausada ou não configurada\n"
                f"⚠️ *Erro:* {md(pedido.get('plataforma_api_erro', 'Sem retorno da API'))}\n"
            )

    return (
        f"📥 *{md(titulo)}*\n\n"
        f"🆔 *Pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
        f"{linha_financeira}"
        f"🗂️ *Catálogo:* {md(pedido.get('catalogo', ''))}\n"
        f"📌 *Serviço:* {md(pedido.get('servico', ''))}\n"
        f"🔢 *Quantidade:* {md(pedido.get('quantidade', ''))}\n"
        f"💰 *Valor:* {md(valor_relatorio_reais(pedido.get('valor')))}\n"
        f"📆 *Total do cliente nesta semana:* {md(valor_relatorio_reais(total_semanal_cliente))}\n"
        f"{destino_emoji} *{destino_label}:* {md(pedido.get('link', ''))}\n"
        f"{bloco_api}\n"
        f"👤 *Cliente:* {md(pedido.get('usuario', 'Cliente'))}\n"
        f"📱 *Telegram:* {md(username)}\n"
        f"🆔 *ID:* `{pedido.get('user_id', '')}`\n"
        f"✅ *Aprovado por:* {md(pedido.get('aprovado_por', 'Mercado Pago'))}\n"
        f"🕒 *Data:* {md(pedido.get('aprovado_em') or agora_br().strftime('%d/%m/%Y %H:%M:%S'))}"
    )


def quebrar_texto_relatorio(draw, texto: str, fonte, largura_max: int) -> list[str]:
    texto = str(texto or "").strip()
    if not texto:
        return [""]

    linhas: list[str] = []
    for bloco in texto.split("\n"):
        palavras = bloco.split()
        if not palavras:
            linhas.append("")
            continue

        linha = palavras[0]
        for palavra in palavras[1:]:
            teste = f"{linha} {palavra}"
            if texto_largura(draw, teste, fonte) <= largura_max:
                linha = teste
            else:
                linhas.append(linha)
                linha = palavra
        linhas.append(linha)

    linhas_finais: list[str] = []
    for linha in linhas:
        if texto_largura(draw, linha, fonte) <= largura_max:
            linhas_finais.append(linha)
            continue

        atual = ""
        for ch in linha:
            teste = atual + ch
            if atual and texto_largura(draw, teste, fonte) > largura_max:
                linhas_finais.append(atual)
                atual = ch
            else:
                atual = teste
        if atual:
            linhas_finais.append(atual)
    return linhas_finais or [texto]


def altura_texto_relatorio(draw, linhas: list[str], fonte, espacamento: int = 8) -> int:
    altura = 0
    for linha in linhas:
        bbox = draw.textbbox((0, 0), linha or " ", font=fonte)
        altura += bbox[3] - bbox[1]
    if len(linhas) > 1:
        altura += (len(linhas) - 1) * espacamento
    return altura


def gerar_imagem_relatorio_admin(pedido: dict, total_semanal_cliente: str, titulo: str = "RELATÓRIO DE VENDA APROVADA") -> BytesIO | None:
    """Gera o relatório pós-compra como imagem PNG para enviar como documento ao admin."""
    if Image is None or ImageDraw is None or ImageFont is None:
        return None

    largura = 1280
    margem = 70
    largura_card = largura - (margem * 2)

    fonte_titulo = fonte_pagamento(56, True)
    fonte_subtitulo = fonte_pagamento(30, False)
    fonte_secao = fonte_pagamento(31, True)
    fonte_label = fonte_pagamento(24, True)
    fonte_valor = fonte_pagamento(31, False)
    fonte_valor_destaque = fonte_pagamento(40, True)
    fonte_rodape = fonte_pagamento(24, False)

    temp = Image.new("RGB", (largura, 2000), (11, 14, 22))
    draw_temp = ImageDraw.Draw(temp)
    blocos = blocos_relatorio_admin(pedido, total_semanal_cliente, titulo)

    y = 250
    alturas_cards: list[tuple[str, list[tuple[str, str, list[str], int]], int]] = []
    for nome_secao, linhas in blocos:
        itens = []
        altura_card = 34 + 44  # topo + título
        for label, valor in linhas:
            fonte_atual = fonte_valor_destaque if label.lower() == "valor aprovado" else fonte_valor
            linhas_valor = quebrar_texto_relatorio(draw_temp, valor, fonte_atual, largura_card - 80)
            h_valor = altura_texto_relatorio(draw_temp, linhas_valor, fonte_atual, 8)
            h_linha = 31 + 8 + h_valor + 24
            itens.append((label, valor, linhas_valor, h_linha))
            altura_card += h_linha
        altura_card += 22
        alturas_cards.append((nome_secao, itens, altura_card))
        y += altura_card + 28

    altura = max(1150, y + 130)
    img = Image.new("RGB", (largura, altura), (11, 14, 22))
    draw = ImageDraw.Draw(img)

    # Fundo com faixas discretas.
    draw.rectangle([0, 0, largura, 210], fill=(18, 28, 48))
    draw.rectangle([0, 210, largura, 225], fill=(33, 92, 180))
    draw.rounded_rectangle([margem, 48, largura - margem, 178], radius=34, fill=(24, 38, 66), outline=(65, 129, 235), width=3)
    draw.text((margem + 40, 70), "TW STORE", font=fonte_titulo, fill=(255, 255, 255))
    draw.text((margem + 43, 132), titulo, font=fonte_subtitulo, fill=(195, 215, 255))

    valor = valor_relatorio_reais(pedido.get("valor"))
    bbox_valor = draw.textbbox((0, 0), valor, font=fonte_valor_destaque)
    x_valor = largura - margem - 40 - (bbox_valor[2] - bbox_valor[0])
    draw.text((x_valor, 88), valor, font=fonte_valor_destaque, fill=(124, 255, 178))

    y = 260
    for nome_secao, itens, altura_card in alturas_cards:
        x1, y1, x2, y2 = margem, y, largura - margem, y + altura_card
        draw.rounded_rectangle([x1, y1, x2, y2], radius=28, fill=(20, 25, 38), outline=(42, 56, 83), width=2)
        draw.rounded_rectangle([x1 + 24, y1 + 22, x2 - 24, y1 + 76], radius=18, fill=(30, 44, 74))
        draw.text((x1 + 48, y1 + 34), nome_secao, font=fonte_secao, fill=(255, 255, 255))

        row_y = y1 + 98
        for idx, (label, valor, _linhas, h_linha) in enumerate(itens):
            if idx > 0:
                draw.line([x1 + 42, row_y - 12, x2 - 42, row_y - 12], fill=(38, 48, 68), width=2)

            fonte_atual = fonte_valor_destaque if label.lower() == "valor aprovado" else fonte_valor
            linhas_valor = quebrar_texto_relatorio(draw, valor, fonte_atual, largura_card - 80)
            draw.text((x1 + 48, row_y), label.upper(), font=fonte_label, fill=(142, 162, 198))
            valor_y = row_y + 37
            cor_valor = (124, 255, 178) if label.lower() == "valor aprovado" else (244, 247, 255)
            for linha in linhas_valor:
                draw.text((x1 + 48, valor_y), linha, font=fonte_atual, fill=cor_valor)
                bbox = draw.textbbox((0, 0), linha or " ", font=fonte_atual)
                valor_y += (bbox[3] - bbox[1]) + 8
            row_y += h_linha

        y = y2 + 28

    rodape = f"Gerado automaticamente em {agora_br().strftime('%d/%m/%Y %H:%M:%S')} • Relatório pós-compra"
    draw.text((margem, altura - 70), rodape, font=fonte_rodape, fill=(130, 146, 174))

    arquivo = BytesIO()
    img.save(arquivo, format="PNG", optimize=True)
    arquivo.seek(0)
    pedido_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(pedido.get("pedido_id") or "pedido"))
    arquivo.name = f"relatorio_pos_compra_{pedido_id}.png"
    return arquivo


def enviar_documento_telegram_sync(chat_id, arquivo: BytesIO, caption: str | None = None, parse_mode: str = "Markdown", reply_markup: dict | None = None) -> bool:
    if not BOT_TOKEN or not chat_id or arquivo is None:
        return False

    try:
        arquivo.seek(0)
        payload = {"chat_id": chat_id}
        if caption:
            payload["caption"] = caption
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        files = {
            "document": (
                getattr(arquivo, "name", "relatorio_pos_compra.png"),
                arquivo.read(),
                "image/png",
            )
        }
        resposta = requests.post(telegram_api_url("sendDocument"), data=payload, files=files, timeout=30)
        if not resposta.ok:
            logging.warning("Falha ao enviar relatório como documento: %s", resposta.text[:300])
        return resposta.ok
    except Exception as exc:
        logging.warning("Falha ao enviar relatório como documento: %s", exc)
        return False


def caption_relatorio_admin(pedido: dict, titulo: str = "NOVO PEDIDO PAGO — TW STORE") -> str:
    return (
        f"📥 *{md(titulo)}*\n"
        f"🆔 Pedido: `{md(pedido.get('pedido_id', ''))}`\n"
        f"💰 Valor: {md(valor_relatorio_reais(pedido.get('valor')))}\n"
        "📎 Relatório completo enviado em PNG."
    )


def enviar_relatorio_admin_documento_sync(
    pedido: dict,
    total_semanal_cliente: str,
    titulo: str = "NOVO PEDIDO PAGO — TW STORE",
) -> bool:
    """Envia o relatório individual de pedido aprovado somente ao Admin 1."""
    if not pedido:
        return False

    if pedido.get("relatorio_admin_enviado_em"):
        return True

    admins = ids_admin_relatorio_pedido(pedido)
    if not admins:
        logging.error(
            "Relatório do pedido %s não enviado: configure ADMIN_CHAT_ID com o ID do Admin 1.",
            pedido.get("pedido_id"),
        )
        return False

    admin_chat_id = admins[0]
    imagem = gerar_imagem_relatorio_admin(
        pedido,
        total_semanal_cliente,
        titulo="RELATÓRIO DE VENDA APROVADA",
    )

    enviado = False
    if imagem is not None:
        enviado = enviar_documento_telegram_sync(
            admin_chat_id,
            imagem,
            caption=caption_relatorio_admin(pedido, titulo),
        )

    # Se o PNG não puder ser gerado ou enviado, o Admin 1 ainda recebe o
    # relatório completo em texto para que nenhum pedido aprovado fique sem aviso.
    if not enviado:
        enviado = enviar_telegram_sync(
            admin_chat_id,
            montar_relatorio_admin_texto(pedido, total_semanal_cliente, titulo),
        )

    if not enviado:
        logging.error(
            "Falha ao enviar o relatório do pedido %s ao Admin 1 (%s).",
            pedido.get("pedido_id"),
            admin_chat_id,
        )
        return False

    pedido["relatorio_admin_enviado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido["relatorio_admin_chat_id"] = str(admin_chat_id)
    salvar_pedido_historico(pedido)
    logging.info(
        "Relatório do pedido %s enviado ao Admin 1 (%s) pelo Telegram.",
        pedido.get("pedido_id"),
        admin_chat_id,
    )
    return True


def montar_relatorio_admin_sync(pedido: dict, total_semanal_cliente: str | None = None, titulo: str = "NOVO PEDIDO PAGO — TW STORE") -> str:
    if total_semanal_cliente is None:
        total_semanal_cliente = registrar_pedido_semanal(pedido)
    return montar_relatorio_admin_texto(pedido, total_semanal_cliente, titulo)


def destinos_email_pedidos() -> list[str]:
    """Retorna os destinatários configurados, aceitando vírgula ou ponto e vírgula."""
    vistos: list[str] = []
    for item in re.split(r"[,;\n]+", EMAIL_PEDIDOS_DESTINO or ""):
        email = item.strip()
        if email and email not in vistos:
            vistos.append(email)
    return vistos


def email_pedidos_configurado() -> bool:
    return bool(
        EMAIL_SMTP_HOST
        and EMAIL_SMTP_PORT
        and EMAIL_SMTP_USER
        and EMAIL_SMTP_PASSWORD
        and destinos_email_pedidos()
    )


def _valor_html(valor, padrao: str = "Não informado") -> str:
    texto = str(valor if valor not in (None, "") else padrao)
    return html_escape(texto)


def _linha_email(label: str, valor, destaque: bool = False) -> str:
    cor = "#0f766e" if destaque else "#111827"
    peso = "700" if destaque else "600"
    return (
        '<tr>'
        '<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;'
        'color:#6b7280;font-size:13px;width:38%;">'
        f'{html_escape(label)}</td>'
        '<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;'
        f'color:{cor};font-size:14px;font-weight:{peso};word-break:break-word;">'
        f'{_valor_html(valor)}</td>'
        '</tr>'
    )


def montar_email_relatorio_pedido_html(
    pedido: dict,
    total_semanal_cliente: str,
    titulo: str = "NOVO PEDIDO PAGO — TW STORE",
) -> str:
    destino_label = "E-mail do cliente" if catalogo_exige_email(pedido) else "Link/@ informado"
    email_cliente = pedido.get("link") if catalogo_exige_email(pedido) else "Não se aplica"
    status_api = status_envio_plataforma(pedido)
    if pedido.get("catalogo") not in CATALOGOS_COM_ENVIO_API:
        status_api_texto = "Processamento pela equipe"
    elif status_api == "enviado":
        status_api_texto = f"Enviado — pedido {pedido.get('plataforma_order_id') or 'sem ID retornado'}"
    elif status_api == "revisao_manual":
        status_api_texto = f"Revisão manual — {pedido.get('plataforma_api_erro') or 'conferir na plataforma'}"
    else:
        status_api_texto = pedido.get("plataforma_api_erro") or status_api or "Não informado"

    linhas_pedido = "".join([
        _linha_email("ID do pedido", pedido.get("pedido_id")),
        _linha_email("Catálogo", pedido.get("catalogo")),
        _linha_email("Serviço", pedido.get("servico")),
        _linha_email("Quantidade / período", pedido.get("quantidade")),
        _linha_email(destino_label, pedido.get("link"), destaque=catalogo_exige_email(pedido)),
    ])
    linhas_pagamento = "".join([
        _linha_email("Valor aprovado", valor_relatorio_reais(pedido.get("valor")), destaque=True),
        _linha_email("Total do cliente na semana", valor_relatorio_reais(total_semanal_cliente)),
        _linha_email("Mercado Pago ID", pedido.get("mp_payment_id")),
        _linha_email("Aprovado por", pedido.get("aprovado_por") or "Mercado Pago"),
        _linha_email("Data da aprovação", pedido.get("aprovado_em") or agora_br().strftime("%d/%m/%Y %H:%M:%S")),
    ])
    linhas_cliente = "".join([
        _linha_email("Nome no Telegram", pedido.get("usuario") or "Cliente"),
        _linha_email("Usuário", username_relatorio(pedido)),
        _linha_email("Telegram ID", pedido.get("user_id")),
        _linha_email("E-mail informado", email_cliente, destaque=catalogo_exige_email(pedido)),
    ])
    linhas_processamento = "".join([
        _linha_email("Status local", traduzir_status_local(pedido.get("status"))),
        _linha_email("Processamento", pedido.get("processado_por") or "Não informado"),
        _linha_email("Situação do envio", status_api_texto),
    ])

    return f'''<!doctype html>
<html lang="pt-BR">
  <body style="margin:0;padding:0;background:#eef2f7;font-family:Arial,Helvetica,sans-serif;color:#111827;">
    <div style="max-width:680px;margin:0 auto;padding:24px 12px;">
      <div style="background:linear-gradient(135deg,#07162f,#123c7a);padding:28px;border-radius:18px 18px 0 0;color:#fff;">
        <div style="font-size:13px;letter-spacing:2px;font-weight:700;color:#93c5fd;">TW STORE</div>
        <h1 style="margin:8px 0 6px;font-size:26px;line-height:1.25;">{html_escape(titulo)}</h1>
        <p style="margin:0;color:#dbeafe;font-size:14px;">Um pedido foi concluído e já está registrado no histórico do bot.</p>
      </div>

      <div style="background:#fff;padding:24px;border-radius:0 0 18px 18px;box-shadow:0 8px 28px rgba(15,23,42,.10);">
        <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:12px;padding:16px;margin-bottom:20px;">
          <div style="font-size:12px;color:#047857;font-weight:700;text-transform:uppercase;letter-spacing:.8px;">E-mail do cliente</div>
          <div style="font-size:20px;color:#065f46;font-weight:800;margin-top:6px;word-break:break-word;">{_valor_html(email_cliente)}</div>
        </div>

        <h2 style="font-size:17px;margin:0 0 8px;color:#0f172a;">📦 Dados do pedido</h2>
        <table role="presentation" style="width:100%;border-collapse:collapse;background:#f8fafc;border-radius:10px;overflow:hidden;margin-bottom:22px;">{linhas_pedido}</table>

        <h2 style="font-size:17px;margin:0 0 8px;color:#0f172a;">💳 Pagamento</h2>
        <table role="presentation" style="width:100%;border-collapse:collapse;background:#f8fafc;border-radius:10px;overflow:hidden;margin-bottom:22px;">{linhas_pagamento}</table>

        <h2 style="font-size:17px;margin:0 0 8px;color:#0f172a;">👤 Cliente / solicitante</h2>
        <table role="presentation" style="width:100%;border-collapse:collapse;background:#f8fafc;border-radius:10px;overflow:hidden;margin-bottom:22px;">{linhas_cliente}</table>

        <h2 style="font-size:17px;margin:0 0 8px;color:#0f172a;">⚙️ Processamento</h2>
        <table role="presentation" style="width:100%;border-collapse:collapse;background:#f8fafc;border-radius:10px;overflow:hidden;">{linhas_processamento}</table>

        <p style="margin:22px 0 0;color:#64748b;font-size:12px;line-height:1.5;">
          Mensagem automática enviada após a confirmação do pagamento. O relatório individual não é enviado ao ADMIN_CHAT_ID.
        </p>
      </div>
    </div>
  </body>
</html>'''


def montar_email_relatorio_pedido_texto(
    pedido: dict,
    total_semanal_cliente: str,
    titulo: str = "NOVO PEDIDO PAGO — TW STORE",
) -> str:
    destino_label = "E-mail do cliente" if catalogo_exige_email(pedido) else "Link/@ informado"
    return (
        f"{titulo}\n\n"
        f"Pedido: {pedido.get('pedido_id') or 'Não informado'}\n"
        f"Catálogo: {pedido.get('catalogo') or 'Não informado'}\n"
        f"Serviço: {pedido.get('servico') or 'Não informado'}\n"
        f"Quantidade/período: {pedido.get('quantidade') or 'Não informado'}\n"
        f"{destino_label}: {pedido.get('link') or 'Não informado'}\n"
        f"Valor: {valor_relatorio_reais(pedido.get('valor'))}\n"
        f"Total semanal do cliente: {valor_relatorio_reais(total_semanal_cliente)}\n"
        f"Mercado Pago ID: {pedido.get('mp_payment_id') or 'Não informado'}\n"
        f"Cliente: {pedido.get('usuario') or 'Cliente'}\n"
        f"Telegram: {username_relatorio(pedido)}\n"
        f"Telegram ID: {pedido.get('user_id') or 'Não informado'}\n"
        f"Aprovado por: {pedido.get('aprovado_por') or 'Mercado Pago'}\n"
        f"Data: {pedido.get('aprovado_em') or agora_br().strftime('%d/%m/%Y %H:%M:%S')}\n"
    )


def enviar_relatorio_pedido_email_sync(
    pedido: dict,
    total_semanal_cliente: str,
    titulo: str = "NOVO PEDIDO PAGO — TW STORE",
) -> bool:
    """Envia o relatório individual por e-mail, sem encaminhá-lo ao ADMIN_CHAT_ID."""
    if not pedido:
        return False
    if pedido.get("relatorio_email_enviado_em"):
        return True
    if not email_pedidos_configurado():
        logging.error(
            "Relatório do pedido %s não enviado: configure EMAIL_USER, EMAIL_APP_PASSWORD e EMAIL_DESTINO.",
            pedido.get("pedido_id"),
        )
        return False

    destinatarios = destinos_email_pedidos()
    pedido_id = str(pedido.get("pedido_id") or "Não informado")
    servico = str(pedido.get("servico") or pedido.get("catalogo") or "Pedido")

    mensagem = EmailMessage()
    mensagem["Subject"] = f"✅ Pedido concluído {pedido_id} — {servico}"
    mensagem["From"] = formataddr((EMAIL_REMETENTE_NOME, EMAIL_SMTP_USER))
    mensagem["To"] = ", ".join(destinatarios)
    mensagem.set_content(montar_email_relatorio_pedido_texto(pedido, total_semanal_cliente, titulo))
    mensagem.add_alternative(montar_email_relatorio_pedido_html(pedido, total_semanal_cliente, titulo), subtype="html")

    if EMAIL_ANEXAR_RELATORIO_PNG:
        try:
            imagem = gerar_imagem_relatorio_admin(
                pedido,
                total_semanal_cliente,
                titulo="RELATÓRIO DE VENDA APROVADA",
            )
            if imagem is not None:
                imagem.seek(0)
                mensagem.add_attachment(
                    imagem.read(),
                    maintype="image",
                    subtype="png",
                    filename=getattr(imagem, "name", f"relatorio_{pedido_id}.png"),
                )
        except Exception as exc:
            logging.warning("Não foi possível anexar o PNG do pedido %s ao e-mail: %s", pedido_id, exc)

    contexto_ssl = ssl.create_default_context()
    try:
        if EMAIL_SMTP_USE_SSL:
            with smtplib.SMTP_SSL(
                EMAIL_SMTP_HOST,
                EMAIL_SMTP_PORT,
                timeout=EMAIL_SMTP_TIMEOUT,
                context=contexto_ssl,
            ) as servidor:
                servidor.login(EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD)
                servidor.send_message(mensagem)
        else:
            with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=EMAIL_SMTP_TIMEOUT) as servidor:
                servidor.ehlo()
                if EMAIL_SMTP_USE_TLS:
                    servidor.starttls(context=contexto_ssl)
                    servidor.ehlo()
                servidor.login(EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD)
                servidor.send_message(mensagem)
    except Exception as exc:
        logging.error("Falha ao enviar relatório do pedido %s por e-mail: %s", pedido_id, exc)
        return False

    pedido["relatorio_email_enviado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido["relatorio_email_destino"] = ", ".join(destinatarios)
    salvar_pedido_historico(pedido)
    logging.info("Relatório do pedido %s enviado por e-mail para %s.", pedido_id, mensagem["To"])
    return True


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

        status_api_antes = str(pedido.get("plataforma_api_status") or "").strip().lower()

        pedido["status"] = "pagamento_aprovado"
        pedido["mp_payment_id"] = payment_id
        pedido["mp_status"] = str(pagamento.get("status") or "approved")
        pedido["aprovado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
        pedido["aprovado_por"] = "Mercado Pago"
        pedido["processado_por"] = origem

        # Salva o estado aprovado antes de chamar a plataforma.
        # Se o bot cair durante o processamento, o restart não trata o pedido
        # como um pagamento novo sem histórico.
        salvar_pedido_pendente(pedido)

        if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
            if pedido_ja_enviado_para_plataforma(pedido):
                pedido["plataforma_api_status"] = "enviado"
            elif envio_plataforma_bloqueado_para_auto(pedido):
                if status_api_antes != "revisao_manual":
                    marcar_envio_plataforma_para_revisao_manual(
                        pedido,
                        origem=f"{origem}_restart_guard",
                        motivo=(
                            "Envio automático bloqueado: este pedido já tinha uma tentativa de envio "
                            f"registrada como '{status_api_antes or 'desconhecido'}'. Para evitar duplicidade após restart/webhook, "
                            "confira na plataforma antes de reenviar."
                        ),
                    )
                salvar_pedido_pendente(pedido)
            elif pagamento_antigo_sem_trava_deve_ir_para_revisao(pedido, pagamento):
                marcar_envio_plataforma_para_revisao_manual(
                    pedido,
                    origem=f"{origem}_pagamento_antigo",
                    motivo=(
                        "Pagamento aprovado antes desta instância do bot subir. O envio automático foi pausado "
                        "porque pode ser webhook/pedido antigo reprocessado após restart do Railway."
                    ),
                )
                salvar_pedido_pendente(pedido)
            else:
                pedido["plataforma_api_status"] = "processando"
                pedido["plataforma_processando_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
                pedido["plataforma_tentativa_envio_em"] = pedido["plataforma_processando_em"]
                salvar_pedido_pendente(pedido)
                try:
                    resultado = criar_pedido_plataforma_sync(pedido)
                    pedido["plataforma_api_status"] = "enviado"
                    pedido["plataforma_service_id"] = resultado.get("service_id")
                    pedido["plataforma_quantidade"] = resultado.get("quantity")
                    pedido["plataforma_order_id"] = resultado.get("order_id") or "Não informado"
                    pedido["plataforma_resposta"] = resultado.get("response")
                    salvar_pedido_pendente(pedido)
                except Exception as exc:
                    marcar_envio_plataforma_para_revisao_manual(
                        pedido,
                        origem=f"{origem}_erro_api",
                        motivo=(
                            "A tentativa de envio para a plataforma falhou ou não retornou com segurança. "
                            f"Erro: {limpar_erro_api(exc)}. Confira na plataforma antes de tentar novamente."
                        ),
                    )
                    salvar_pedido_pendente(pedido)

        salvar_pedido_historico(pedido)
        marcar_pagamento_processado(payment_id, pedido)
        remover_pedido_pendente(str(pedido.get("pedido_id") or ""))

        total_semanal_cliente = registrar_pedido_semanal(pedido)
        titulo_relatorio = (
            "PEDIDO EM REVISÃO MANUAL — TW STORE"
            if status_envio_plataforma(pedido) == "revisao_manual"
            else "NOVO PEDIDO PAGO — TW STORE"
        )
        enviar_relatorio_admin_documento_sync(
            pedido,
            total_semanal_cliente,
            titulo=titulo_relatorio,
        )

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
    """Consulta o Mercado Pago e processa recargas ou pedidos legados."""
    try:
        pagamento = consultar_pagamento_mercado_pago_sync(payment_id)
        if str(pagamento.get("status")) != "approved":
            logging.info("Pagamento %s recebido no webhook com status %s.", payment_id, pagamento.get("status"))
            return False

        external_reference = pagamento.get("external_reference")
        recarga = DB.obter_recarga_por_pagamento(payment_id, external_reference)
        if recarga:
            return processar_recarga_aprovada_sync(recarga, pagamento, origem=origem)

        pedido = obter_pedido_por_pagamento(payment_id, external_reference)
        if not pedido:
            pedido_historico = obter_pedido_historico_por_pagamento(payment_id, external_reference)
            if pedido_historico:
                marcar_pagamento_processado(payment_id, pedido_historico)
                logging.info("Webhook antigo ignorado: pagamento %s já está no histórico.", payment_id)
                return True

            # Se o pagamento foi aprovado mas não há pedido pendente, reprocessar
            # esse mesmo webhook a cada restart só cria risco de duplicidade.
            logging.warning("Pagamento aprovado sem pedido pendente: %s. Webhook será encerrado para evitar repetição.", payment_id)
            return True

        return processar_pagamento_aprovado_sync(pedido, pagamento, origem=origem)
    except Exception as exc:
        logging.exception("Erro ao processar notificação Mercado Pago: %s", limpar_erro_api(exc))
        return False

def processar_eventos_webhook_pendentes_sync(limite: int = 20):
    """Processa eventos de webhook persistidos no SQLite com retry."""
    eventos = DB.listar_webhooks_pendentes(limite=limite, max_attempts=WEBHOOK_QUEUE_MAX_ATTEMPTS)
    for evento in eventos:
        event_id = int(evento["id"])
        payment_id = str(evento.get("payment_id") or "")
        if not payment_id:
            DB.marcar_webhook_erro(event_id, "payment_id vazio")
            continue
        if pagamento_ja_processado(payment_id):
            DB.marcar_webhook_processado(event_id)
            continue
        if not DB.marcar_webhook_processando(event_id):
            continue
        try:
            ok = processar_notificacao_mercado_pago_sync(payment_id, origem=evento.get("origem") or "webhook_queue")
            if ok or pagamento_ja_processado(payment_id):
                DB.marcar_webhook_processado(event_id)
            else:
                DB.marcar_webhook_erro(event_id, "Pagamento ainda não processado. Será tentado novamente.")
        except Exception as exc:
            DB.marcar_webhook_erro(event_id, limpar_erro_api(exc))


def iniciar_rotina_webhook_queue():
    """Inicia uma rotina leve para reprocessar webhooks pendentes após restart/falha."""
    def worker():
        while True:
            try:
                processar_eventos_webhook_pendentes_sync()
            except Exception as exc:
                logging.warning("Falha na rotina da fila de webhook: %s", exc)
            time_module.sleep(max(15, WEBHOOK_QUEUE_INTERVAL))

    thread = threading.Thread(target=worker, daemon=True, name="webhook-queue")
    thread.start()


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

        DB.enfileirar_webhook(payment_id, payload=dados, origem="webhook")
        thread = threading.Thread(
            target=processar_eventos_webhook_pendentes_sync,
            kwargs={"limite": 5},
            daemon=True,
        )
        thread.start()

        # O Mercado Pago espera HTTP 200/201 rapidamente. O evento fica persistido
        # no SQLite e será reprocessado mesmo se o bot reiniciar.
        return jsonify({"ok": True, "queued": True, "payment_id": payment_id})

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

    catalogo = str(pedido.get("catalogo_api") or pedido.get("catalogo") or "").strip()
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


def numero_decimal_plataforma(valor) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)

    texto = str(valor).strip()
    if not texto:
        return None

    texto = re.sub(r"[^0-9,.-]", "", texto)
    if not texto or texto in {"-", ",", "."}:
        return None

    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")

    try:
        return float(texto)
    except ValueError:
        return None


def requisicao_plataforma_sync(payload: dict):
    if not PANEL_API_URL:
        raise PlataformaAPIConfigError("PANEL_API_URL não configurada no .env.")
    if not PANEL_API_KEY:
        raise PlataformaAPIConfigError("PANEL_API_KEY não configurada no .env.")

    dados_envio = {"key": PANEL_API_KEY}
    dados_envio.update(payload or {})

    try:
        resposta = requests.post(PANEL_API_URL, data=dados_envio, timeout=PANEL_API_TIMEOUT)
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

    return resultado


def consultar_saldo_plataforma_sync() -> dict:
    resultado = requisicao_plataforma_sync({"action": "balance"})
    if not isinstance(resultado, dict):
        raise PlataformaAPIRequestError(f"Retorno inesperado ao consultar saldo: {limpar_erro_api(resultado)}")

    saldo_raw = (
        resultado.get("balance")
        or resultado.get("saldo")
        or resultado.get("amount")
        or resultado.get("funds")
    )
    saldo = numero_decimal_plataforma(saldo_raw)
    if saldo is None:
        raise PlataformaAPIRequestError(f"Não consegui interpretar o saldo da plataforma: {limpar_erro_api(resultado)}")

    return {
        "saldo": saldo,
        "saldo_raw": saldo_raw,
        "moeda": resultado.get("currency") or resultado.get("moeda") or "",
        "raw": resultado,
    }


def consultar_servicos_plataforma_sync() -> list:
    agora_cache = time_module.time()
    dados_cache = PLATAFORMA_SERVICOS_CACHE.get("dados")
    if (
        PANEL_SERVICES_CACHE_TTL > 0
        and isinstance(dados_cache, list)
        and agora_cache < float(PLATAFORMA_SERVICOS_CACHE.get("expira_em") or 0)
    ):
        return dados_cache

    resultado = requisicao_plataforma_sync({"action": "services"})
    if isinstance(resultado, list):
        servicos = resultado
    elif isinstance(resultado, dict):
        servicos = None
        for chave in ("services", "data", "result"):
            if isinstance(resultado.get(chave), list):
                servicos = resultado[chave]
                break
        if servicos is None:
            raise PlataformaAPIRequestError(f"Retorno inesperado ao consultar serviços: {limpar_erro_api(resultado)}")
    else:
        raise PlataformaAPIRequestError(f"Retorno inesperado ao consultar serviços: {limpar_erro_api(resultado)}")

    PLATAFORMA_SERVICOS_CACHE["dados"] = servicos
    PLATAFORMA_SERVICOS_CACHE["expira_em"] = agora_cache + max(0, PANEL_SERVICES_CACHE_TTL)
    return servicos


def buscar_servico_plataforma_sync(service_id: str) -> dict | None:
    service_id = str(service_id or "").strip()
    if not service_id:
        return None

    servicos = consultar_servicos_plataforma_sync()
    for servico in servicos:
        if not isinstance(servico, dict):
            continue
        sid = str(servico.get("service") or servico.get("id") or servico.get("service_id") or "").strip()
        if sid == service_id:
            return servico
    return None


def formatar_inteiro_br(valor) -> str:
    try:
        numero = int(float(valor))
    except (TypeError, ValueError):
        return str(valor or "").strip()
    return f"{numero:,}".replace(",", ".")


def calcular_limite_solicitacoes_plataforma_sync(
    catalogo: str,
    servico_chave: str,
    quantidade,
    api_service_id: str | None = None,
) -> dict | None:
    """Calcula quantas vezes o pacote selecionado cabe no limite máximo do serviço no painel."""
    if not PANEL_API_URL or not PANEL_API_KEY:
        return None

    pedido_base = {
        "catalogo": catalogo,
        "servico_chave": servico_chave,
        "quantidade": quantidade,
        "quantidade_api": quantidade,
        "api_service_id": api_service_id,
    }
    service_id = obter_service_id_api(pedido_base)
    servico = buscar_servico_plataforma_sync(service_id)
    if servico is None:
        return None

    quantidade_pacote = quantidade_para_api(quantidade)
    maximo = numero_decimal_plataforma(servico.get("max"))
    minimo = numero_decimal_plataforma(servico.get("min"))
    if maximo is None or quantidade_pacote <= 0:
        return None

    maximo_int = int(maximo)
    minimo_int = int(minimo) if minimo is not None else None
    solicitacoes_possiveis = maximo_int // quantidade_pacote

    return {
        "service_id": service_id,
        "quantidade_pacote": quantidade_pacote,
        "maximo": maximo_int,
        "minimo": minimo_int,
        "solicitacoes_possiveis": solicitacoes_possiveis,
        "maximo_texto": formatar_inteiro_br(maximo_int),
        "minimo_texto": formatar_inteiro_br(minimo_int) if minimo_int is not None else "",
        "solicitacoes_texto": formatar_inteiro_br(solicitacoes_possiveis),
    }


def aplicar_limite_solicitacoes_no_pedido(pedido: dict, info: dict | None):
    if not pedido or not info:
        return
    pedido["plataforma_estoque_max"] = info.get("maximo")
    pedido["plataforma_estoque_max_texto"] = info.get("maximo_texto")
    pedido["plataforma_solicitacoes_possiveis"] = info.get("solicitacoes_possiveis")
    pedido["plataforma_solicitacoes_possiveis_texto"] = info.get("solicitacoes_texto")


def linha_solicitacoes_possiveis_pagamento(pedido: dict) -> str:
    texto = (pedido or {}).get("plataforma_solicitacoes_possiveis_texto")
    if not texto:
        return ""

    try:
        numero = int(str((pedido or {}).get("plataforma_solicitacoes_possiveis") or texto).replace(".", ""))
    except (TypeError, ValueError):
        numero = None
    vezes = "vez" if numero == 1 else "vezes"
    return f"• Pode solicitar até: {texto} {vezes} este pacote\n"


def texto_limite_solicitacoes(info: dict | None) -> str:
    if not info:
        return ""

    linhas = [f"📊 Limite disponível: {info.get('maximo_texto', '')}"]
    solicitacoes = info.get("solicitacoes_possiveis")
    if solicitacoes is not None:
        vezes = "vez" if int(solicitacoes) == 1 else "vezes"
        linhas.append(f"Pode solicitar até: {info.get('solicitacoes_texto', solicitacoes)} {vezes} este pacote")
    return "\n".join(linhas).strip()


def aplicar_limite_solicitacoes_na_mensagem(mensagem: str, info: dict | None) -> str:
    texto_estoque = texto_limite_solicitacoes(info)
    if not mensagem or not texto_estoque:
        return mensagem

    mensagem = str(mensagem)
    padrao_estoque = re.compile(r"(?mi)^\s*(?:📊\s*)?(?:Estoque|Limite disponível)\s*:\s*.*$")
    if padrao_estoque.search(mensagem):
        mensagem = padrao_estoque.sub(texto_estoque, mensagem, count=1)
    else:
        padrao_plataforma = re.compile(r"(?mi)^(\s*(?:📲\s*)?Plataforma\s*:\s*.*)$")
        if padrao_plataforma.search(mensagem):
            mensagem = padrao_plataforma.sub(r"\1\n" + texto_estoque, mensagem, count=1)
        else:
            mensagem = texto_estoque + "\n\n" + mensagem

    # Evita duplicar a linha caso uma versão antiga do catálogo já tenha essa informação fixa.
    mensagem = re.sub(
        r"(?mi)^\s*(?:🔁\s*)?Pode solicitar até\s*:\s*.*$",
        "",
        mensagem,
    )
    mensagem = re.sub(r"\n{3,}", "\n\n", mensagem).strip()
    if "Pode solicitar até:" not in mensagem:
        linhas = mensagem.splitlines()
        for i, linha in enumerate(linhas):
            if re.match(r"\s*Estoque\s*:", linha, flags=re.IGNORECASE):
                linhas.insert(i + 1, texto_estoque.splitlines()[-1])
                mensagem = "\n".join(linhas)
                break
    return mensagem


async def obter_limite_solicitacoes_item(
    catalogo: str,
    servico_chave: str,
    item: dict,
    servico: dict,
) -> dict | None:
    if catalogo not in CATALOGOS_COM_ENVIO_API:
        return None

    api_service_id = item.get("api_service_id") or servico.get("api_service_id")
    quantidade = item.get("quantidade")
    try:
        return await asyncio.to_thread(
            calcular_limite_solicitacoes_plataforma_sync,
            catalogo,
            servico_chave,
            quantidade,
            api_service_id,
        )
    except (PlataformaAPIConfigError, PlataformaAPIRequestError, PlataformaEstoqueIndisponivel) as exc:
        logging.warning("Não foi possível consultar o estoque/limite da plataforma: %s", limpar_erro_api(exc))
    except Exception as exc:
        logging.warning("Erro inesperado ao consultar estoque/limite da plataforma: %s", limpar_erro_api(exc))
    return None


def estimar_custo_pedido_plataforma_sync(pedido: dict) -> dict:
    service_id = obter_service_id_api(pedido)
    quantidade = quantidade_para_api(pedido.get("quantidade_api") or pedido.get("quantidade"))

    servico = buscar_servico_plataforma_sync(service_id)
    if servico is None:
        raise PlataformaEstoqueIndisponivel(
            f"Service ID {service_id} não encontrado na lista de serviços da plataforma."
        )

    minimo = numero_decimal_plataforma(servico.get("min"))
    maximo = numero_decimal_plataforma(servico.get("max"))
    if minimo is not None and quantidade < int(minimo):
        raise PlataformaEstoqueIndisponivel(
            f"Quantidade {quantidade} abaixo do mínimo permitido pela plataforma ({int(minimo)})."
        )
    if maximo is not None and quantidade > int(maximo):
        raise PlataformaEstoqueIndisponivel(
            f"Quantidade {quantidade} acima do máximo permitido pela plataforma ({int(maximo)})."
        )

    rate = numero_decimal_plataforma(
        servico.get("rate")
        or servico.get("price")
        or servico.get("valor")
        or servico.get("custo")
    )
    custo = None
    if rate is not None:
        custo = round((rate * quantidade) / 1000, 6)

    return {
        "service_id": service_id,
        "quantidade": quantidade,
        "servico": servico,
        "rate": rate,
        "custo_estimado": custo,
    }


def verificar_reposicao_antes_pagamento_sync(pedido: dict) -> tuple[bool, str]:
    if not CHECK_ESTOQUE_ANTES_PAGAMENTO:
        return True, "Verificação de estoque desativada."

    if pedido.get("catalogo") not in CATALOGOS_COM_ENVIO_API:
        return True, "Catálogo sem envio automático para plataforma."

    saldo_info = consultar_saldo_plataforma_sync()
    saldo = float(saldo_info["saldo"])
    moeda = str(saldo_info.get("moeda") or "").strip()

    estimativa = estimar_custo_pedido_plataforma_sync(pedido)
    custo = estimativa.get("custo_estimado")
    service_id = estimativa.get("service_id")
    quantidade = estimativa.get("quantidade")

    if custo is not None:
        necessario = float(custo) + float(MARGEM_SALDO_PLATAFORMA)
        if saldo + 0.000001 < necessario:
            detalhe = (
                "Saldo insuficiente na plataforma antes de liberar o pedido. "
                f"Saldo: {saldo:.6f} {moeda}; necessário estimado: {necessario:.6f} {moeda}; "
                f"service_id: {service_id}; quantidade: {quantidade}."
            )
            return False, detalhe

        detalhe = (
            "Saldo da plataforma confirmado antes do pedido. "
            f"Saldo: {saldo:.6f} {moeda}; custo estimado: {float(custo):.6f} {moeda}; "
            f"service_id: {service_id}; quantidade: {quantidade}."
        )
        return True, detalhe

    if saldo <= float(MARGEM_SALDO_PLATAFORMA):
        detalhe = (
            "Saldo zerado/insuficiente na plataforma antes de liberar o pedido. "
            f"Saldo: {saldo:.6f} {moeda}; service_id: {service_id}; quantidade: {quantidade}."
        )
        return False, detalhe

    detalhe = (
        "Saldo positivo confirmado antes do pedido, mas não foi possível estimar o custo do serviço. "
        f"Saldo: {saldo:.6f} {moeda}; service_id: {service_id}; quantidade: {quantidade}."
    )
    return True, detalhe


def mensagem_cliente_sem_reposicao() -> str:
    return (
        "⚠️ *Serviço temporariamente sem reposição de estoque.*\n\n"
        "No momento não consigo liberar esse pedido automaticamente. "
        "Tente novamente mais tarde ou fale com o atendimento.\n\n"
        "✅ Nenhum valor foi descontado do seu saldo."
    )


def texto_admin_bloqueio_sem_reposicao(pedido: dict, detalhe: str) -> str:
    username = username_relatorio(pedido)
    return (
        "🚫 *PEDIDO BLOQUEADO ANTES DO DÉBITO*\n\n"
        "O cliente tentou iniciar um pedido, mas o bot não descontou a carteira porque detectou falta de saldo/reposição na plataforma.\n\n"
        f"🆔 *Pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
        f"🗂️ *Catálogo:* {md(pedido.get('catalogo', ''))}\n"
        f"📌 *Serviço:* {md(pedido.get('servico', ''))}\n"
        f"🔢 *Quantidade:* {md(pedido.get('quantidade', ''))}\n"
        f"💰 *Valor que seria cobrado:* R$ {md(pedido.get('valor', ''))}\n"
        f"🔗 *Link/@:* {md(pedido.get('link', ''))}\n\n"
        f"👤 *Cliente:* {md(pedido.get('usuario', 'Cliente'))}\n"
        f"📱 *Telegram:* {md(username)}\n"
        f"🆔 *ID Telegram:* `{pedido.get('user_id', '')}`\n\n"
        f"⚠️ *Detalhe interno:* {md(limpar_erro_api(detalhe))}\n\n"
        "Reponha saldo na plataforma ou troque o Service ID do serviço no catálogo."
    )


async def avisar_admin_bloqueio_sem_reposicao(context: ContextTypes.DEFAULT_TYPE, pedido: dict, detalhe: str):
    if not ADMIN_CHAT_ID:
        return
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=texto_admin_bloqueio_sem_reposicao(pedido, detalhe),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logging.warning("Falha ao avisar admin sobre bloqueio sem reposição: %s", exc)


async def verificar_reposicao_antes_pagamento(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict) -> bool:
    if not pedido:
        return False

    try:
        ok, detalhe = await asyncio.to_thread(verificar_reposicao_antes_pagamento_sync, pedido)
    except (PlataformaAPIConfigError, PlataformaAPIRequestError, PlataformaEstoqueIndisponivel) as exc:
        ok = False
        detalhe = limpar_erro_api(exc)
    except Exception as exc:
        ok = False
        detalhe = f"Erro inesperado ao verificar saldo/reposição: {limpar_erro_api(exc)}"

    if ok:
        pedido["ultima_verificacao_reposicao"] = detalhe
        return True

    pedido["status"] = "bloqueado_sem_reposicao"
    pedido["bloqueado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido["motivo_bloqueio"] = detalhe

    await avisar_admin_bloqueio_sem_reposicao(context, pedido, detalhe)
    await enviar_texto_sequencial(
        update,
        context,
        mensagem_cliente_sem_reposicao(),
        InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
    )
    return False



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
        "aguardando_saldo": "Aguardando saldo suficiente",
        "aguardando_pagamento": "Aguardando pagamento",
        "aguardando_aprovacao_admin": "Comprovante em análise",
        "pagamento_aprovado": "Pagamento aprovado",
        "comprovante_reprovado": "Comprovante reprovado",
        "pagamento_expirado": "Pagamento expirado",
        "pendente_removido_restart": "Pendente removido no restart",
    }
    texto = str(status or "").strip()
    return mapa.get(texto, texto or "Não informado")


def texto_status_pedido_local(pedido: dict, origem: str | None = None) -> str:
    plataforma_id = pedido.get("plataforma_order_id")
    status_api = pedido.get("plataforma_api_status")
    status_local = traduzir_status_local(pedido.get("status"))
    if pedido.get("forma_pagamento") == "saldo" and pedido.get("status") == "pagamento_aprovado":
        status_local = "Saldo utilizado / pedido confirmado"
    linhas = [
        "📦 *Resumo do seu pedido*",
        "",
        f"🆔 *ID do pedido:* `{md(pedido.get('pedido_id', ''))}`",
        f"📌 *Status:* {md(status_local)}",
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
            "Esse pedido ainda está no fluxo interno do bot. Assim que ele for enviado para a plataforma, o status atualizado aparecerá aqui.",
        ])

    return "\n".join(linhas)


def texto_status_pedido_plataforma(order_id: str, resultado: dict, pedido_local: dict | None = None) -> str:
    status = resultado.get("status") or resultado.get("Status") or resultado.get("state") or resultado.get("raw") or "desconhecido"
    linhas = [
        "🔎 *Status do pedido*",
        "",
    ]

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
        "✅ Consulta feita diretamente na plataforma.",
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
        "🔄 *Solicitação de reposição enviada*",
        "",
        f"🚀 *ID do pedido na plataforma:* `{md(order_id)}`",
    ]
    if refil_id:
        linhas.append(f"🧾 *ID da solicitação:* `{md(refil_id)}`")
    linhas.extend([
        "",
        "✅ Sua solicitação foi enviada para a plataforma.",
        "Você pode consultar pelo botão *🔎 Consultar Status* usando o mesmo ID.",
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
            keyboard.append([btn("🔄 Solicitar Reposição", f"pedido:refil:{order_id}")])
        else:
            keyboard.append([btn("🔄 Solicitar Reposição", "pedido:solicitar_refil")])
    keyboard.append([btn("📦 Consultar outro pedido", "pedido:consultar_status")])
    keyboard.append([btn("🏠 Menu inicial", "voltar:inicio")])
    return InlineKeyboardMarkup(keyboard)


def menu_consultar_pedido() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("🔎 Consultar Status", "pedido:consultar_status")],
        [btn("🔄 Solicitar Reposição", "pedido:solicitar_refil")],
        [btn("🏠 Voltar ao início", "voltar:inicio")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def enviar_pedido_para_plataforma(pedido: dict):
    if pedido.get("catalogo") not in CATALOGOS_COM_ENVIO_API:
        return

    if pedido_ja_enviado_para_plataforma(pedido):
        pedido["plataforma_api_status"] = "enviado"
        return

    if envio_plataforma_estava_processando(pedido):
        marcar_envio_plataforma_para_revisao_manual(pedido, origem="aprovacao_admin_restart_guard")
        if pedido.get("pedido_id"):
            salvar_pedido_pendente(pedido)
        return

    pedido["plataforma_api_status"] = "processando"
    pedido["plataforma_processando_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    if pedido.get("pedido_id"):
        salvar_pedido_pendente(pedido)

    try:
        resultado = await asyncio.to_thread(criar_pedido_plataforma_sync, pedido)
    except (PlataformaAPIConfigError, PlataformaAPIRequestError) as exc:
        pedido["plataforma_api_status"] = "erro"
        pedido["plataforma_api_erro"] = limpar_erro_api(exc)
        if pedido.get("pedido_id"):
            salvar_pedido_pendente(pedido)
        return
    except Exception as exc:
        pedido["plataforma_api_status"] = "erro"
        pedido["plataforma_api_erro"] = limpar_erro_api(f"Erro inesperado: {exc}")
        if pedido.get("pedido_id"):
            salvar_pedido_pendente(pedido)
        return

    pedido["plataforma_api_status"] = "enviado"
    pedido["plataforma_service_id"] = resultado.get("service_id")
    pedido["plataforma_quantidade"] = resultado.get("quantity")
    pedido["plataforma_order_id"] = resultado.get("order_id") or "Não informado"
    pedido["plataforma_resposta"] = resultado.get("response")
    if pedido.get("pedido_id"):
        salvar_pedido_pendente(pedido)


def btn(texto: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(texto, callback_data=data)


def menu_principal() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("👤 Meu Perfil", "perfil:meu")],
        [btn("💳 consultar saldo", "saldo:consultar")],
        [btn("📖 Catálogo de Serviços", "menu:catalogo")],
        [btn("🔎 Consultar Pedido", "pedido:consultar")],
        [btn("🎟️ Solicitar Suporte", "extra:atendimento")],
    ]
    return InlineKeyboardMarkup(keyboard)


def texto_carteira_saldo(user_id) -> str:
    saldo = saldo_usuario_centavos(user_id)
    return (
        "💳 *Carteira de saldo — TW Store*\n\n"
        f"Seu saldo disponível é de *R$ {md(centavos_para_moeda(saldo))}*.\n\n"
        "*Como funciona*\n"
        "1. Toque em *adicionar saldo*.\n"
        "2. Informe um valor entre *R$ 5,00 e R$ 300,00*.\n"
        f"3. O bot acrescenta a taxa de *{TAXA_RECARGA_PERCENTUAL}%* e gera o Pix com o total.\n"
        "4. Assim que o pagamento for aprovado, o valor escolhido entra integralmente na sua carteira.\n"
        "5. Nos próximos pedidos, o bot desconta o valor diretamente do seu saldo — sem gerar um novo Pix a cada compra.\n\n"
        "🔒 Cada recarga é identificada e creditada uma única vez."
    )


def menu_carteira_saldo() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [btn("💳 adicionar saldo", "saldo:adicionar")],
            [btn("🏠 Voltar ao início", "voltar:inicio")],
        ]
    )


def texto_informar_valor_recarga() -> str:
    return (
        "💳 *Adicionar saldo*\n\n"
        "Digite quanto você quer adicionar à sua carteira.\n\n"
        "• Mínimo: *R$ 5,00*\n"
        "• Máximo: *R$ 300,00*\n\n"
        "Exemplos: `5`, `20,00` ou `150,50`.\n\n"
        f"Será acrescentada uma taxa de *{TAXA_RECARGA_PERCENTUAL}%* ao Pix. "
        "O valor que você escolher será creditado integralmente como saldo.\n\n"
        "Depois que você enviar o valor, vou gerar um Pix exclusivo para esta recarga."
    )


def menu_cancelar_recarga() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [btn("⬅️ Voltar para o saldo", "saldo:consultar")],
            [btn("🏠 Menu inicial", "voltar:inicio")],
        ]
    )


def texto_pix_recarga(recarga: dict) -> str:
    expira_em = recarga.get("pagamento_expira_em")
    linha_expiracao = f"\n⌛ *Válido até:* {md(expira_em)}" if expira_em else ""
    valor_saldo = recarga.get("valor_saldo") or recarga.get("valor") or "0,00"
    taxa = recarga.get("taxa") or "0,00"
    valor_pagamento = recarga.get("valor_pagamento") or recarga.get("valor") or "0,00"
    return (
        "✅ *Pix de recarga gerado*\n\n"
        f"💳 *Saldo que será adicionado:* R$ {md(valor_saldo)}\n"
        f"🧾 *Taxa de {TAXA_RECARGA_PERCENTUAL}%:* R$ {md(taxa)}\n"
        f"💰 *Total do Pix:* R$ {md(valor_pagamento)}\n"
        f"🧾 *ID da recarga:* `{md(recarga.get('recarga_id', ''))}`"
        f"{linha_expiracao}\n\n"
        "Toque em *Copiar Pix*, abra o aplicativo do seu banco e conclua o pagamento.\n\n"
        "Após pagar, aguarde alguns segundos e toque em *Verificar recarga*. "
        "A confirmação também pode acontecer automaticamente."
    )


def texto_confirmacao_recarga(
    recarga: dict,
    saldo_disponivel_centavos: int,
    ja_aprovada: bool = False,
) -> str:
    titulo = "✅ *Recarga já aprovada*" if ja_aprovada else "✅ *Recarga aprovada!*"
    valor_saldo = recarga.get("valor_saldo") or recarga.get("valor") or "0,00"
    linhas = [
        titulo,
        "",
        f"💰 *Valor adicionado:* R$ {md(valor_saldo)}",
    ]
    if recarga.get("taxa_centavos") is not None:
        linhas.extend(
            [
                f"🧾 *Taxa de {TAXA_RECARGA_PERCENTUAL}%:* R$ {md(recarga.get('taxa', '0,00'))}",
                f"💵 *Total pago:* R$ {md(recarga.get('valor_pagamento', valor_saldo))}",
            ]
        )
    linhas.extend(
        [
            f"💳 *Saldo disponível:* R$ {md(centavos_para_moeda(saldo_disponivel_centavos))}",
            f"🧾 *ID da recarga:* `{md(recarga.get('recarga_id', ''))}`",
        ]
    )
    return "\n".join(linhas)


def botoes_pix_recarga(recarga: dict, permitir_retomar: bool = False) -> InlineKeyboardMarkup:
    recarga_id = str(recarga.get("recarga_id") or "")
    pix_copia = recarga.get("mp_qr_code") or "PIX_NAO_CONFIGURADO"
    keyboard = [
        [InlineKeyboardButton("📋 Copiar Pix", copy_text=CopyTextButton(pix_copia))],
        [btn("✅ Verificar recarga", f"saldo:verificar:{recarga_id}")],
    ]
    if permitir_retomar:
        keyboard.append([btn("🛒 Usar saldo no pedido", "saldo:retomar_pedido")])
    keyboard.extend(
        [
            [btn("💳 Consultar saldo", "saldo:consultar")],
            [btn("🏠 Menu inicial", "voltar:inicio")],
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def menu_catalogos() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("🚀 Engajamentos", "catalogo:redes_sociais")],
        [btn("🎫 Assinaturas", "catalogo:assinaturas")],
        [btn("🎞️ IPTV XCIPTV", "catalogo:iptv")],
        [btn("🛜 Internet Ilimitada", "catalogo:internet")],
        [btn("⬅️ Voltar", "voltar:inicio")],
    ]
    return InlineKeyboardMarkup(keyboard)


def menu_redes_sociais() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("🟣 Instagram", "catalogo:instagram")],
        [btn("⚫ TikTok", "catalogo:tiktok")],
        [btn("🟠 Kwai", "catalogo:kwai")],
        [btn("⬅️ Voltar ao catálogo", "menu:catalogo")],
    ]
    return InlineKeyboardMarkup(keyboard)


def menu_instagram() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("🌏 Serviços Estrangeiros", "catalogo_instagram:estrangeiros")],
        [btn("🇧🇷 Serviços Brasileiros", "catalogo_instagram:brasileiros")],
        [btn("⬅️ Voltar aos engajamentos", "catalogo:redes_sociais")],
    ]
    return InlineKeyboardMarkup(keyboard)


def menu_instagram_estrangeiros() -> InlineKeyboardMarkup:
    servicos = CATALOGO["catalogos"]["instagram"]["servicos"]
    nomes_botoes = {
        "seguidores": "👥 Seguidores",
        "curtidas": "❤️ Curtidas",
        "visualizacoes": "👁️‍🗨️ Visualizações",
    }
    keyboard = []
    for chave, servico in servicos.items():
        keyboard.append([btn(nomes_botoes.get(chave, servico["nome"]), f"servico:{chave}")])
    keyboard.append([btn("⬅️ Voltar ao Instagram", "catalogo:instagram")])
    return InlineKeyboardMarkup(keyboard)


def menu_instagram_brasileiros() -> InlineKeyboardMarkup:
    servicos = CATALOGO["catalogos"]["instagram"].get("servicos_brasileiros", {})
    nomes_botoes = {
        "seguidores": "👥 Seguidores",
    }
    keyboard = []
    for chave, servico in servicos.items():
        if chave != "seguidores":
            continue
        keyboard.append([btn(nomes_botoes.get(chave, servico.get("nome", chave.title())), f"servico_instagram_br:{chave}")])
    keyboard.append([btn("⬅️ Voltar ao Instagram", "catalogo:instagram")])
    return InlineKeyboardMarkup(keyboard)


def menu_tiktok() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("🌏 Serviços Estrangeiros", "catalogo_tiktok:estrangeiros")],
        [btn("⬅️ Voltar aos engajamentos", "catalogo:redes_sociais")],
    ]
    return InlineKeyboardMarkup(keyboard)


def menu_tiktok_estrangeiros() -> InlineKeyboardMarkup:
    servicos = CATALOGO["catalogos"]["tiktok"]["servicos"]
    nomes_botoes = {
        "seguidores": "👤 Seguidores",
        "curtidas": "♥️ Curtidas",
        "visualizacoes": "👁️‍🗨️ Visualizações",
    }
    keyboard = []
    for chave, servico in servicos.items():
        keyboard.append([btn(nomes_botoes.get(chave, servico["nome"]), f"servico_tiktok:{chave}")])
    keyboard.append([btn("⬅️ Voltar", "catalogo:tiktok")])
    return InlineKeyboardMarkup(keyboard)


def menu_itens_tiktok(servico_chave: str) -> InlineKeyboardMarkup:
    servico = CATALOGO["catalogos"]["tiktok"]["servicos"][servico_chave]
    keyboard = []
    for item in servico["itens"]:
        texto = f'{item["quantidade_texto"]} {servico["nome"]} — {money(item["valor"])}'
        keyboard.append([btn(texto, f'item_tiktok:{servico_chave}:{item["quantidade"]}')])
    keyboard.append([btn("⬅️ Voltar", "catalogo_tiktok:estrangeiros")])
    return InlineKeyboardMarkup(keyboard)


def get_item_tiktok(servico_chave: str, quantidade: int) -> dict:
    servico = CATALOGO["catalogos"]["tiktok"]["servicos"][servico_chave]
    for item in servico["itens"]:
        if int(item["quantidade"]) == int(quantidade):
            return item
    raise KeyError("Item não encontrado")




def menu_kwai() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("🇧🇷 Serviço Brasileiros", "catalogo_kwai:brasileiros")],
        [btn("⬅️ Voltar aos engajamentos", "catalogo:redes_sociais")],
    ]
    return InlineKeyboardMarkup(keyboard)


def menu_kwai_brasileiros() -> InlineKeyboardMarkup:
    servicos = CATALOGO["catalogos"]["kwai"]["servicos"]
    nomes_botoes = {
        "seguidores": "👤 Seguidores",
        "curtidas": "❤️ Curtidas",
        "visualizacoes": "👁️ Visualizações",
    }
    keyboard = []
    for chave, servico in servicos.items():
        keyboard.append([btn(nomes_botoes.get(chave, servico["nome"]), f"servico_kwai:{chave}")])
    keyboard.append([btn("⬅️ Voltar ao Kwai", "catalogo:kwai")])
    return InlineKeyboardMarkup(keyboard)


def menu_itens_kwai(servico_chave: str) -> InlineKeyboardMarkup:
    servico = CATALOGO["catalogos"]["kwai"]["servicos"][servico_chave]
    keyboard = []
    for item in servico["itens"]:
        texto = f'{item["quantidade_texto"]} {servico["nome"]} — {money(item["valor"])}'
        keyboard.append([btn(texto, f'item_kwai:{servico_chave}:{item["quantidade"]}')])
    keyboard.append([btn("⬅️ Voltar", "catalogo_kwai:brasileiros")])
    return InlineKeyboardMarkup(keyboard)


def get_item_kwai(servico_chave: str, quantidade: int) -> dict:
    servico = CATALOGO["catalogos"]["kwai"]["servicos"][servico_chave]
    for item in servico["itens"]:
        if int(item["quantidade"]) == int(quantidade):
            return item
    raise KeyError("Item Kwai não encontrado")


def menu_assinaturas() -> InlineKeyboardMarkup:
    servicos = CATALOGO["catalogos"]["assinaturas"]["servicos"]
    keyboard = [
        [btn(f'{servico["nome"]} — {money(servico["valor"])}', f"assinatura:{chave}")]
        for chave, servico in servicos.items()
    ]
    keyboard.append([btn("⬅️ Voltar ao catálogo", "menu:catalogo")])
    return InlineKeyboardMarkup(keyboard)


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
            [btn("✅ Confirmar e usar saldo", "confirmar_email_iptv")],
            [btn("✏️ Alterar e-mail", "alterar_email_iptv")],
            [btn("🏠 Cancelar / Menu", "voltar:inicio")],
        ]
    )


def menu_itens(servico_chave: str) -> InlineKeyboardMarkup:
    servico = CATALOGO["catalogos"]["instagram"]["servicos"][servico_chave]
    keyboard = []
    for item in servico["itens"]:
        texto = f'{item["quantidade_texto"]} {servico["nome"]} — {money(item["valor"])}'
        keyboard.append([btn(texto, f'item:{servico_chave}:{item["quantidade"]}')])
    keyboard.append([btn("⬅️ Voltar", "catalogo_instagram:estrangeiros")])
    return InlineKeyboardMarkup(keyboard)


def get_item(servico_chave: str, quantidade: int) -> dict:
    servico = CATALOGO["catalogos"]["instagram"]["servicos"][servico_chave]
    for item in servico["itens"]:
        if int(item["quantidade"]) == int(quantidade):
            return item
    raise KeyError("Item não encontrado")



def menu_itens_instagram_brasileiros(servico_chave: str) -> InlineKeyboardMarkup:
    servico = CATALOGO["catalogos"]["instagram"]["servicos_brasileiros"][servico_chave]
    keyboard = []
    for item in servico.get("itens", []):
        texto = f'{item["quantidade_texto"]} {servico["nome"]} — {money(item["valor"])}'
        keyboard.append([btn(texto, f'item_instagram_br:{servico_chave}:{item["quantidade"]}')])
    keyboard.append([btn("⬅️ Voltar aos serviços brasileiros", "catalogo_instagram:brasileiros")])
    return InlineKeyboardMarkup(keyboard)


def get_item_instagram_brasileiros(servico_chave: str, quantidade: int) -> dict:
    servico = CATALOGO["catalogos"]["instagram"]["servicos_brasileiros"][servico_chave]
    for item in servico.get("itens", []):
        if int(item["quantidade"]) == int(quantidade):
            return item
    raise KeyError("Item não encontrado")


def texto_pagamento(pedido: dict) -> str:
    # Monta a etapa de pagamento usando Pix dinâmico do Mercado Pago quando disponível.
    destino_label = "E-mail informado" if catalogo_exige_email(pedido) else "Link/@ enviado"
    destino_valor = pedido.get("link", "")

    resumo_base = (
        "💳 Etapa 2 de 3 — Pagamento\n\n"
        "✅ Seu pedido já foi separado com sucesso.\n"
        "Finalize o pagamento pelo Pix abaixo.\n\n"
        "📋 Resumo do Pedido\n\n"
        f"• Catálogo: {pedido.get('catalogo', '')}\n"
        f"• Serviço: {pedido.get('servico', '')}\n"
        f"• Quantidade: {pedido.get('quantidade', '')}\n"
        + linha_solicitacoes_possiveis_pagamento(pedido)
        + f"• {destino_label}: {destino_valor}\n"
        f"• Valor exato: R$ {pedido.get('valor', '')}\n\n"
    )

    if pedido.get("mp_qr_code"):
        return (
            resumo_base
            + "⌛️ Após o pagamento, aguarde alguns segundos.\n"
            "A confirmação é feita automaticamente pelo Mercado Pago.\n"
            "Caso necessário, toque em Verificar Pagamento."
        )

    return (
        resumo_base
        + "⌛️ Após o pagamento, envie o comprovante aqui na conversa.\n"
        "O pedido será liberado após a aprovação do pagamento."
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


async def enviar_texto_sequencial(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    await apagar_ultima_mensagem_bot(update, context)
    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode=parse_mode,
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


def botoes_saldo_insuficiente(pedido: dict | None = None) -> InlineKeyboardMarkup:
    texto_alterar = "✏️ Alterar e-mail" if catalogo_exige_email(pedido or {}) else "✏️ Alterar link/@"
    return InlineKeyboardMarkup(
        [
            [btn("💳 adicionar saldo", "saldo:adicionar")],
            [btn("💳 Consultar saldo", "saldo:consultar")],
            [btn(texto_alterar, "alterar_link")],
            [btn("🏠 Cancelar / Menu", "voltar:inicio")],
        ]
    )


def texto_saldo_insuficiente_pedido(pedido: dict, saldo_centavos: int) -> str:
    valor_centavos = valor_para_centavos(pedido.get("valor"))
    faltam = max(0, valor_centavos - int(saldo_centavos or 0))
    return (
        "⚠️ *Saldo insuficiente*\n\n"
        f"💳 *Seu saldo:* R$ {md(centavos_para_moeda(saldo_centavos))}\n"
        f"🛒 *Valor do pedido:* R$ {md(centavos_para_moeda(valor_centavos))}\n"
        f"➕ *Falta adicionar:* R$ {md(centavos_para_moeda(faltam))}\n\n"
        "Adicione saldo à sua carteira para concluir este pedido. Nenhum valor foi descontado."
    )


async def processar_pedido_com_saldo_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pedido: dict,
):
    if not pedido or not pedido.get("link"):
        await safe_edit_or_reply(
            update,
            "Não encontrei um pedido completo. Toque em /start para começar novamente.",
        )
        return

    user_id = str(pedido.get("user_id") or telegram_id_update(update))
    valor_centavos = valor_para_centavos(pedido.get("valor"))
    if valor_centavos <= 0:
        await enviar_texto_sequencial(
            update,
            context,
            "⚠️ Não consegui identificar o valor deste pedido. Escolha o serviço novamente.",
            InlineKeyboardMarkup([[btn("📖 Voltar ao catálogo", "menu:catalogo")]]),
        )
        return

    saldo_atual = saldo_usuario_centavos(user_id)
    if saldo_atual < valor_centavos:
        pedido["status"] = "aguardando_saldo"
        await enviar_texto_sequencial(
            update,
            context,
            texto_saldo_insuficiente_pedido(pedido, saldo_atual),
            botoes_saldo_insuficiente(pedido),
        )
        return

    # Confere a disponibilidade externa antes de mexer na carteira do cliente.
    if not await verificar_reposicao_antes_pagamento(update, context, pedido):
        return

    aprovado_em = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido_debito = dict(pedido)
    pedido_debito.update(
        {
            "status": "pagamento_aprovado",
            "forma_pagamento": "saldo",
            "aprovado_em": aprovado_em,
            "aprovado_por": "Saldo da carteira",
            "saldo_debitado_em": aprovado_em,
            "saldo_debitado_centavos": valor_centavos,
        }
    )

    try:
        resultado = await asyncio.to_thread(
            DB.debitar_saldo_pedido,
            user_id,
            str(pedido_debito.get("pedido_id") or ""),
            valor_centavos,
            pedido_debito,
        )
    except Exception as exc:
        logging.exception("Falha ao debitar saldo do pedido %s", pedido_debito.get("pedido_id"))
        await enviar_texto_sequencial(
            update,
            context,
            f"⚠️ Não consegui reservar o saldo deste pedido: {md(limpar_erro_api(exc))}",
            InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
        )
        return

    if resultado.get("saldo_insuficiente"):
        pedido["status"] = "aguardando_saldo"
        await enviar_texto_sequencial(
            update,
            context,
            texto_saldo_insuficiente_pedido(pedido, int(resultado.get("saldo_centavos") or 0)),
            botoes_saldo_insuficiente(pedido),
        )
        return

    if resultado.get("ja_processado"):
        context.user_data.clear()
        await enviar_texto_sequencial(
            update,
            context,
            (
                "✅ Este pedido já teve o saldo reservado e não será descontado novamente.\n\n"
                "Consulte o pedido pelo menu para acompanhar o andamento."
            ),
            InlineKeyboardMarkup(
                [
                    [btn("🔎 Consultar Pedido", "pedido:consultar")],
                    [btn("🏠 Menu inicial", "voltar:inicio")],
                ]
            ),
        )
        return

    pedido.update(pedido_debito)
    pedido["saldo_antes_centavos"] = int(resultado.get("saldo_antes_centavos") or 0)
    pedido["saldo_apos_centavos"] = int(resultado.get("saldo_centavos") or 0)
    salvar_pedido_pendente(pedido)

    try:
        await enviar_texto_sequencial(
            update,
            context,
            (
                "✅ *Saldo utilizado com sucesso!*\n\n"
                f"💰 *Valor descontado:* R$ {md(centavos_para_moeda(valor_centavos))}\n"
                f"💳 *Saldo restante:* R$ {md(centavos_para_moeda(pedido['saldo_apos_centavos']))}\n\n"
                "Seu pedido está sendo processado."
            ),
        )
    except Exception as exc:
        logging.warning("Saldo debitado, mas não foi possível atualizar a tela do cliente: %s", exc)

    if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
        await enviar_pedido_para_plataforma(pedido)

    salvar_pedido_historico(pedido)
    remover_pedido_pendente(str(pedido.get("pedido_id") or ""))
    await enviar_relatorio_admin(update, context, pedido)
    await enviar_texto_sequencial(
        update,
        context,
        texto_final_pedido(pedido),
        InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
    )
    context.user_data.clear()


async def enviar_pagamento_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict):
    """Compatibilidade: novos pedidos usam somente o saldo da carteira."""
    await processar_pedido_com_saldo_cliente(update, context, pedido)


def botoes_pagamento(pedido: dict | None = None) -> InlineKeyboardMarkup:
    pix_copia = (pedido or {}).get("mp_qr_code") or PIX_COPIA_COLA or PIX_CHAVE or "PIX_NAO_CONFIGURADO"
    texto_botao = "📋 Copiar Pix" if (pedido or {}).get("mp_qr_code") else "📋 Copiar chave Pix"
    texto_alterar = "✏️ Alterar e-mail" if catalogo_exige_email(pedido or {}) else "✏️ Alterar link/@"
    keyboard = [
        [InlineKeyboardButton(texto_botao, copy_text=CopyTextButton(pix_copia))],
    ]
    if (pedido or {}).get("mp_payment_id"):
        keyboard.append([btn("✅ Verificar Pagamento", "verificar_pagamento")])
    keyboard.extend([
        [btn(texto_alterar, "alterar_link")],
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
    destino_label = "E-mail" if catalogo_exige_email(pedido) else "Link/@"
    destino_emoji = "📧" if catalogo_exige_email(pedido) else "🔗"
    return (
        "🧾 *COMPROVANTE AGUARDANDO VALIDAÇÃO*\n\n"
        f"🆔 *Pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
        f"🗂️ *Catálogo:* {md(pedido.get('catalogo', ''))}\n"
        f"📌 *Serviço:* {md(pedido.get('servico', ''))}\n"
        f"🔢 *Quantidade:* {md(pedido.get('quantidade', ''))}\n"
        f"💰 *Valor esperado:* R$ {md(pedido.get('valor', ''))}\n"
        f"{destino_emoji} *{destino_label}:* {md(pedido.get('link', ''))}\n\n"
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


async def safe_edit_or_reply(update: Update, text: str, reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            return query.message
        except BadRequest as exc:
            # Evita duplicar mensagem quando o usuário toca em um botão que
            # tenta abrir exatamente a mesma tela/menu já exibido.
            if "Message is not modified" in str(exc):
                return query.message
            mensagem = await query.message.reply_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            try:
                await query.message.delete()
            except Exception:
                pass
            return mensagem
        except Exception:
            mensagem = await query.message.reply_text(
                text=text,
                parse_mode=parse_mode,
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
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )


async def enviar_catalogo_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia o catálogo com a arte, a mensagem e os botões de categorias."""
    texto = CATALOGO["mensagens"]["catalogo"]
    reply_markup = menu_catalogos()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if CATALOGO_IMAGE_PATH.exists():
        try:
            with open(CATALOGO_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem do catálogo: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_iptv_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia a tela do IPTV XCIPTV com a arte, a mensagem e o botão do plano."""
    texto = CATALOGO["catalogos"]["iptv"]["mensagem"]
    reply_markup = menu_iptv()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if IPTV_IMAGE_PATH.exists():
        try:
            with open(IPTV_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem do IPTV XCIPTV: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_engajamentos_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia a tela de engajamentos com a arte e os botões das plataformas."""
    texto = (
        "🚀 *Engajamentos*\n\n"
        "Escolha abaixo a plataforma que deseja impulsionar.\n\n"
        "✅ Entrega organizada\n"
        "✅ Pedido conferido antes da finalização\n"
        "✅ Suporte caso precise de ajuda\n\n"
        "Toque em uma opção para continuar:"
    )
    reply_markup = menu_redes_sociais()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if ENGAJAMENTOS_IMAGE_PATH.exists():
        try:
            with open(ENGAJAMENTOS_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem de engajamentos: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_instagram_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia a tela do Instagram com a arte e os botões dos serviços."""
    texto = (
        "📸 *Instagram*\n\n"
        "Escolha abaixo o tipo de serviço que deseja contratar.\n\n"
        "Você pode selecionar pacotes para perfil ou publicação, com pedido organizado e conferência antes da finalização.\n\n"
        "Toque em uma opção para continuar:"
    )
    reply_markup = menu_instagram()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if INSTAGRAM_IMAGE_PATH.exists():
        try:
            with open(INSTAGRAM_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem do Instagram: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_instagram_estrangeiros_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia a tela dos serviços estrangeiros do Instagram com a arte e os botões."""
    texto = (
        "🌏 *Instagram — Serviços Estrangeiros*\n\n"
        "Pacotes com entrega gradual para perfis e publicações do Instagram.\n\n"
        "📌 *Opções disponíveis:*\n"
        "• Seguidores para perfil\n"
        "• Curtidas para publicação\n"
        "• Visualizações para publicação\n\n"
        "Escolha o serviço que deseja:"
    )
    reply_markup = menu_instagram_estrangeiros()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if INSTAGRAM_ESTRANGEIROS_IMAGE_PATH.exists():
        try:
            with open(INSTAGRAM_ESTRANGEIROS_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem do Instagram estrangeiros: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_instagram_brasileiros_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia a tela dos serviços brasileiros do Instagram com a arte e os botões."""
    texto = (
        "🇧🇷 *Instagram — Serviços Brasileiros*\n\n"
        "Pacotes com entrega gradual para perfis brasileiros do Instagram.\n\n"
        "📌 *Opção disponível:*\n"
        "• Seguidores brasileiros para perfil\n\n"
        "Escolha o serviço que deseja:"
    )
    reply_markup = menu_instagram_brasileiros()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if INSTAGRAM_BRASILEIROS_IMAGE_PATH.exists():
        try:
            with open(INSTAGRAM_BRASILEIROS_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem do Instagram brasileiros: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_tiktok_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia a tela do TikTok com a arte e os botões dos serviços."""
    texto = (
        "🎵 *TikTok*\n\n"
        "Escolha abaixo o tipo de serviço que deseja contratar.\n\n"
        "Você pode selecionar pacotes para perfil ou publicação, com pedido organizado e conferência antes da finalização.\n\n"
        "Toque em uma opção para continuar:"
    )
    reply_markup = menu_tiktok()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if TIKTOK_IMAGE_PATH.exists():
        try:
            with open(TIKTOK_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem do TikTok: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_tiktok_estrangeiros_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia a tela dos serviços estrangeiros do TikTok com a arte e os botões."""
    texto = (
        "🌏 *TikTok — Serviços Estrangeiros*\n\n"
        "Pacotes com entrega gradual para perfis e publicações do TikTok.\n\n"
        "📌 *Opções disponíveis:*\n"
        "• Seguidores para perfil\n"
        "• Curtidas para publicação\n"
        "• Visualizações para publicação\n\n"
        "Escolha o serviço que deseja:"
    )
    reply_markup = menu_tiktok_estrangeiros()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if TIKTOK_ESTRANGEIROS_IMAGE_PATH.exists():
        try:
            with open(TIKTOK_ESTRANGEIROS_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem do TikTok estrangeiros: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_kwai_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia a tela do Kwai com a arte e os botões dos serviços."""
    texto = (
        "🟠 *Kwai*\n\n"
        "Escolha abaixo o tipo de serviço que deseja contratar.\n\n"
        "Toque em uma opção para continuar:"
    )
    reply_markup = menu_kwai()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if KWAI_IMAGE_PATH.exists():
        try:
            with open(KWAI_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem do Kwai: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_kwai_brasileiros_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Envia a tela de Kwai brasileiros com a arte e os botões dos serviços."""
    texto = (
        "🇧🇷 *Kwai — Serviços Brasileiros*\n\n"
        "Escolha o serviço que deseja contratar:"
    )
    reply_markup = menu_kwai_brasileiros()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if KWAI_BRASILEIROS_IMAGE_PATH.exists():
        try:
            with open(KWAI_BRASILEIROS_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem do Kwai brasileiros: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def enviar_assinatura_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    servico_chave: str,
    texto: str,
    reply_markup=None,
):
    """Exibe a tela da assinatura com sua arte, quando houver uma configurada."""
    imagem_path = ASSINATURA_IMAGE_PATHS.get(servico_chave)
    bot_contexto = getattr(context, "bot", None)
    chat = getattr(update, "effective_chat", None)
    if (
        imagem_path is None
        or not imagem_path.exists()
        or bot_contexto is None
        or chat is None
    ):
        return await safe_edit_or_reply(
            update,
            texto,
            reply_markup,
            parse_mode=None,
        )

    if update.callback_query:
        query = update.callback_query
        responder_callback = getattr(query, "answer", None)
        if callable(responder_callback):
            await responder_callback()
        try:
            await query.message.delete()
        except Exception:
            pass

    try:
        with open(imagem_path, "rb") as photo:
            mensagem = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo,
                caption=texto,
                parse_mode=None,
                reply_markup=reply_markup,
            )
        guardar_mensagem_bot(context, mensagem)
        return mensagem
    except Exception as exc:
        logging.warning(
            "Falha ao enviar imagem da assinatura %s: %s",
            servico_chave,
            exc,
        )

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=None,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


def primeira_imagem_existente(*paths: Path | None) -> Path | None:
    for caminho in paths:
        if caminho and caminho.exists():
            return caminho
    return None


async def enviar_mensagem_com_imagem_chat(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id,
    texto: str,
    reply_markup=None,
    parse_mode=ParseMode.MARKDOWN,
    image_paths: list[Path] | None = None,
):
    imagem_path = primeira_imagem_existente(*(image_paths or []))
    if imagem_path:
        try:
            with open(imagem_path, "rb") as photo:
                return await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=texto,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
        except Exception as exc:
            logging.warning("Falha ao enviar imagem %s: %s", imagem_path.name, exc)

    return await context.bot.send_message(
        chat_id=chat_id,
        text=texto,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


async def enviar_atendimento_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE, texto: str, reply_markup=None):
    """Envia a tela de Fale Conosco com a arte de suporte."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    mensagem = await enviar_mensagem_com_imagem_chat(
        context,
        update.effective_chat.id,
        texto,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
        image_paths=[SUPORTE_IMAGE_PATH, TICKET_STATUS_IMAGE_PATH],
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


def ticket_id_texto(ticket_id) -> str:
    try:
        return f"{int(ticket_id):06d}"
    except (TypeError, ValueError):
        return str(ticket_id or "")


def botoes_ticket(ticket_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("🔒 Fechar ticket", f"ticket:fechar:{int(ticket_id)}")],
    ])


def menu_suporte_cliente() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("🎟️ abrir ticket", "suporte:chat")],
        [btn("⬅️ Voltar", "voltar:inicio")],
    ])


def texto_menu_suporte() -> str:
    return (
        CATALOGO.get("menus_extras", {}).get("atendimento")
        or "🎫 Precisa de ajuda? Fale com o suporte."
    )


def referencia_mensagem_ticket(chat_id, message_id) -> dict | None:
    """Normaliza a referência usada para apagar uma mensagem do ticket."""
    chat_id = str(chat_id or "").strip()
    try:
        message_id = int(message_id)
    except (TypeError, ValueError):
        return None
    if not chat_id or message_id <= 0:
        return None
    return {"chat_id": chat_id, "message_id": message_id}


def referencia_objeto_mensagem_ticket(mensagem, chat_id=None) -> dict | None:
    """Extrai chat/message ID tanto de Message quanto de MessageId."""
    if not mensagem:
        return None
    mensagem_chat_id = getattr(mensagem, "chat_id", None)
    if mensagem_chat_id is None:
        chat = getattr(mensagem, "chat", None)
        mensagem_chat_id = getattr(chat, "id", None)
    return referencia_mensagem_ticket(
        mensagem_chat_id if mensagem_chat_id is not None else chat_id,
        getattr(mensagem, "message_id", None),
    )


def registrar_mensagens_ticket(ticket: dict, *referencias) -> dict:
    """Persiste mensagens do atendimento para removê-las no fechamento."""
    ticket_id = ticket.get("id")
    ticket_atual = DB.obter_ticket(ticket_id) or ticket
    dados = dict(ticket_atual.get("dados") or {})
    mensagens = list(dados.get("mensagens_ticket") or [])
    chaves = {
        (str(item.get("chat_id") or ""), str(item.get("message_id") or ""))
        for item in mensagens
        if isinstance(item, dict)
    }

    for item in referencias:
        if not isinstance(item, dict):
            continue
        referencia = referencia_mensagem_ticket(
            item.get("chat_id"),
            item.get("message_id"),
        )
        if not referencia:
            continue
        chave = (referencia["chat_id"], str(referencia["message_id"]))
        if chave in chaves:
            continue
        mensagens.append(referencia)
        chaves.add(chave)

    dados["mensagens_ticket"] = mensagens
    atualizado = DB.atualizar_dados_ticket(ticket_id, dados)
    return atualizado or {**ticket_atual, "dados": dados}


async def apagar_mensagens_ticket(
    context: ContextTypes.DEFAULT_TYPE,
    ticket: dict,
    *referencias_extras,
) -> dict:
    """Apaga o histórico e os avisos do ticket em todos os chats envolvidos."""
    ticket_atual = DB.obter_ticket(ticket.get("id")) or ticket
    dados = dict(ticket_atual.get("dados") or {})
    referencias = list(dados.get("mensagens_ticket") or [])
    referencias.extend(dados.get("notificacoes") or [])
    status_cliente = dados.get("cliente_status_msg")
    if status_cliente:
        referencias.append(status_cliente)
    referencias.extend(referencias_extras)

    unicas = []
    chaves = set()
    for item in referencias:
        if not isinstance(item, dict):
            continue
        referencia = referencia_mensagem_ticket(
            item.get("chat_id"),
            item.get("message_id"),
        )
        if not referencia:
            continue
        chave = (referencia["chat_id"], referencia["message_id"])
        if chave in chaves:
            continue
        chaves.add(chave)
        unicas.append(referencia)

    falhas = 0
    for item in unicas:
        try:
            await context.bot.delete_message(
                chat_id=item["chat_id"],
                message_id=item["message_id"],
            )
        except Exception:
            falhas += 1

    for chave in ("mensagens_ticket", "notificacoes", "cliente_status_msg"):
        dados.pop(chave, None)
    atualizado = DB.atualizar_dados_ticket(ticket_atual["id"], dados)
    if falhas:
        logging.warning(
            "Não foi possível apagar %s de %s mensagens do ticket %s.",
            falhas,
            len(unicas),
            ticket_id_texto(ticket_atual.get("id")),
        )
    return atualizado or {**ticket_atual, "dados": dados}


async def apagar_status_ticket_cliente(context: ContextTypes.DEFAULT_TYPE, ticket: dict) -> dict:
    dados = dict(ticket.get("dados") or {})
    status_msg = dados.pop("cliente_status_msg", None) or {}
    chat_id = status_msg.get("chat_id")
    message_id = status_msg.get("message_id")
    if chat_id and message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    atualizado = DB.atualizar_dados_ticket(ticket["id"], dados)
    return atualizado or {**ticket, "dados": dados}


async def enviar_status_ticket_cliente(
    context: ContextTypes.DEFAULT_TYPE,
    ticket: dict,
    texto: str,
    reply_markup=None,
) -> dict:
    ticket = await apagar_status_ticket_cliente(context, ticket)
    mensagem = await enviar_mensagem_com_imagem_chat(
        context,
        ticket["usuario_id"],
        texto,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
        image_paths=[TICKET_STATUS_IMAGE_PATH, SUPORTE_IMAGE_PATH],
    )
    dados = dict(ticket.get("dados") or {})
    dados["cliente_status_msg"] = {
        "chat_id": str(mensagem.chat.id if mensagem.chat else ticket["usuario_id"]),
        "message_id": mensagem.message_id,
    }
    atualizado = DB.atualizar_dados_ticket(ticket["id"], dados)
    return atualizado or {**ticket, "dados": dados}


async def enviar_menu_suporte_para_chat(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id,
):
    return await enviar_mensagem_com_imagem_chat(
        context,
        chat_id,
        texto_menu_suporte(),
        reply_markup=menu_suporte_cliente(),
        parse_mode=ParseMode.MARKDOWN,
        image_paths=[SUPORTE_IMAGE_PATH, TICKET_STATUS_IMAGE_PATH],
    )


def texto_ticket_aguardando(ticket: dict) -> str:
    return (
        "🎫 *Ticket de atendimento aberto*\n\n"
        f"🆔 *Ticket:* `#{md(ticket_id_texto(ticket.get('id')))}`\n"
        "📌 *Status:* aguardando um atendente\n\n"
        "Dono, Gerente, Secretaria(o) ou Helper poderá assumir o atendimento. "
        "Assim que isso acontecer, você receberá uma mensagem aqui."
    )


def texto_ticket_em_atendimento(ticket: dict, para_atendente: bool = False) -> str:
    numero = ticket_id_texto(ticket.get("id"))
    if para_atendente:
        pessoa = ticket.get("usuario_nome") or f"ID {ticket.get('usuario_id')}"
        return (
            "💬 *Atendimento iniciado*\n\n"
            f"🆔 *Ticket:* `#{md(numero)}`\n"
            f"👤 *Cliente:* {md(pessoa)}\n\n"
            "Envie mensagens neste chat do bot. Elas serão repassadas ao cliente dentro do ticket."
        )
    atendente = ticket.get("atendente_nome") or "Equipe de suporte"
    return (
        "💬 *Atendimento iniciado*\n\n"
        f"🆔 *Ticket:* `#{md(numero)}`\n"
        f"🧑‍💻 *Atendente:* {md(atendente)}\n\n"
        "Envie mensagens neste chat do bot. Elas serão repassadas ao atendente dentro do ticket."
    )


async def atualizar_notificacoes_ticket(context: ContextTypes.DEFAULT_TYPE, ticket: dict, texto: str):
    dados = ticket.get("dados") or {}
    for item in dados.get("notificacoes") or []:
        try:
            await context.bot.edit_message_text(
                chat_id=item.get("chat_id"),
                message_id=item.get("message_id"),
                text=texto,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=None,
                disable_web_page_preview=True,
            )
        except Exception:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=item.get("chat_id"),
                    message_id=item.get("message_id"),
                    reply_markup=None,
                )
            except Exception:
                pass


async def notificar_equipe_novo_ticket(
    context: ContextTypes.DEFAULT_TYPE,
    ticket: dict,
    destinatarios: list[str] | None = None,
):
    dados = dict(ticket.get("dados") or {})
    notificacoes = list(dados.get("notificacoes") or [])
    usuario_id = str(ticket.get("usuario_id") or "")
    numero = ticket_id_texto(ticket.get("id"))
    nome = ticket.get("usuario_nome") or "Cliente"
    username = ticket.get("usuario_username") or "Sem @"
    texto = (
        "🆕 *Novo atendimento via chat*\n\n"
        f"🆔 *Ticket:* `#{md(numero)}`\n"
        f"👤 *Cliente:* {md(nome)}\n"
        f"📲 *Telegram:* {md(username)}\n"
        f"🆔 *Telegram ID:* `{md(usuario_id)}`\n\n"
        "Toque abaixo para assumir. O primeiro atendente que aceitar ficará responsável pelo ticket."
    )
    markup = InlineKeyboardMarkup([
        [btn("🙋 Assumir atendimento", f"ticket:assumir:{int(ticket['id'])}")],
    ])

    equipe_destino = destinatarios or ids_com_permissao(PERMISSAO_ATENDER_SUPORTE)
    for equipe_id in ids_unicos(*equipe_destino):
        if str(equipe_id) == usuario_id:
            continue
        try:
            mensagem = await context.bot.send_message(
                chat_id=equipe_id,
                text=texto,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            notificacoes.append(
                {
                    "chat_id": str(mensagem.chat.id if mensagem.chat else equipe_id),
                    "message_id": mensagem.message_id,
                }
            )
        except Exception as exc:
            logging.warning("Falha ao notificar suporte %s sobre ticket %s: %s", equipe_id, numero, exc)

    dados["notificacoes"] = notificacoes
    DB.atualizar_dados_ticket(ticket["id"], dados)


async def abrir_ticket_suporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    query = update.callback_query
    if not user:
        if query:
            await query.answer("Não consegui identificar sua conta.", show_alert=True)
        return

    ticket, criado = DB.criar_ticket(
        user.id,
        user.full_name,
        f"@{user.username}" if user.username else "",
    )
    if ticket.get("status") == "em_atendimento":
        texto = texto_ticket_em_atendimento(ticket)
    else:
        texto = texto_ticket_aguardando(ticket)

    if query:
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    ticket = await enviar_status_ticket_cliente(
        context,
        ticket,
        texto,
        botoes_ticket(ticket["id"]),
    )
    if criado:
        await notificar_equipe_novo_ticket(context, ticket)


async def assumir_ticket_suporte(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    ticket_id: str,
):
    query = update.callback_query
    if not pode_atender_suporte(update):
        await query.answer("Seu cargo não pode assumir atendimentos.", show_alert=True)
        return

    atendente = update.effective_user
    if not atendente:
        await query.answer("Não consegui identificar seu usuário.", show_alert=True)
        return

    ticket_atual = DB.obter_ticket(ticket_id)
    if ticket_atual and str(ticket_atual.get("usuario_id")) == str(atendente.id):
        await query.answer("Você não pode assumir o próprio ticket.", show_alert=True)
        return

    ticket, resultado = DB.assumir_ticket(ticket_id, atendente.id, atendente.full_name)
    mensagens_erro = {
        "nao_encontrado": "Ticket não encontrado.",
        "fechado": "Este ticket já foi fechado.",
        "ja_assumido": "Outro atendente já assumiu este ticket.",
        "atendente_ocupado": "Feche seu atendimento atual antes de assumir outro.",
    }
    if resultado in mensagens_erro:
        await query.answer(mensagens_erro[resultado], show_alert=True)
        return

    if resultado == "ja_assumido_por_voce":
        await query.answer("Este ticket já está com você.", show_alert=True)
        mensagem = await context.bot.send_message(
            chat_id=atendente.id,
            text=texto_ticket_em_atendimento(ticket, para_atendente=True),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=botoes_ticket(ticket["id"]),
        )
        registrar_mensagens_ticket(
            ticket,
            referencia_objeto_mensagem_ticket(mensagem, atendente.id),
        )
        return

    await query.answer("Atendimento assumido.")
    numero = ticket_id_texto(ticket.get("id"))
    await atualizar_notificacoes_ticket(
        context,
        ticket,
        (
            "✅ *Atendimento assumido*\n\n"
            f"🆔 *Ticket:* `#{md(numero)}`\n"
            f"🧑‍💻 *Atendente:* {md(atendente.full_name)}"
        ),
    )

    try:
        ticket = await enviar_status_ticket_cliente(
            context,
            ticket,
            texto_ticket_em_atendimento(ticket),
            botoes_ticket(ticket["id"]),
        )
    except Exception as exc:
        logging.warning("Falha ao avisar cliente sobre ticket assumido %s: %s", numero, exc)

    mensagem = await context.bot.send_message(
        chat_id=atendente.id,
        text=texto_ticket_em_atendimento(ticket, para_atendente=True),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=botoes_ticket(ticket["id"]),
    )
    registrar_mensagens_ticket(
        ticket,
        referencia_objeto_mensagem_ticket(mensagem, atendente.id),
    )


async def fechar_ticket_suporte(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    ticket_id: str,
):
    query = update.callback_query
    ticket = DB.obter_ticket(ticket_id)
    if not ticket:
        await query.answer("Ticket não encontrado.", show_alert=True)
        return

    autor_id = telegram_id_update(update)
    participante = autor_id in {
        str(ticket.get("usuario_id") or ""),
        str(ticket.get("atendente_id") or ""),
    }
    if not participante and not eh_dono(update):
        await query.answer("Somente os participantes podem fechar este ticket.", show_alert=True)
        return

    fechado_por = (
        update.effective_user.full_name if update.effective_user else f"ID {autor_id}"
    )
    ticket, resultado = DB.fechar_ticket(ticket_id, fechado_por)
    if resultado == "ja_fechado":
        await query.answer("Este ticket já estava fechado.", show_alert=True)
        return

    await query.answer("Ticket fechado.")

    numero = ticket_id_texto(ticket.get("id"))
    texto = (
        "🔒 *Ticket fechado*\n\n"
        f"🆔 *Ticket:* `#{md(numero)}`\n"
        f"👤 *Fechado por:* {md(fechado_por)}\n\n"
        "Para solicitar outro atendimento, abra o menu de suporte."
    )
    referencia_fechamento = referencia_objeto_mensagem_ticket(query.message)
    ticket = await apagar_mensagens_ticket(
        context,
        ticket,
        referencia_fechamento,
    )

    cliente_id = str(ticket.get("usuario_id") or "")
    atendente_id = str(ticket.get("atendente_id") or "")

    if cliente_id:
        try:
            await enviar_menu_suporte_para_chat(context, cliente_id)
        except Exception as exc:
            logging.warning(
                "Falha ao retornar menu de suporte para %s no ticket %s: %s",
                cliente_id,
                numero,
                exc,
            )

    if atendente_id and atendente_id != str(autor_id or ""):
        try:
            await context.bot.send_message(
                chat_id=atendente_id,
                text=texto,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as exc:
            logging.warning(
                "Falha ao avisar %s sobre fechamento do ticket %s: %s",
                atendente_id,
                numero,
                exc,
            )


def localizar_ticket_remetente(telegram_id: str) -> tuple[dict | None, str | None, str | None]:
    """Retorna ticket, destinatário e tipo do remetente para o relay privado."""
    ticket_usuario = DB.obter_ticket_ativo_usuario(telegram_id)
    if ticket_usuario:
        if ticket_usuario.get("status") == "aberto":
            return ticket_usuario, None, "aguardando"
        return ticket_usuario, str(ticket_usuario.get("atendente_id") or ""), "cliente"

    ticket_atendente = DB.obter_ticket_ativo_atendente(telegram_id)
    if ticket_atendente:
        return ticket_atendente, str(ticket_atendente.get("usuario_id") or ""), "atendente"
    return None, None, None


async def processar_mensagem_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    mensagem = update.effective_message
    remetente_id = telegram_id_update(update)
    if not mensagem or not remetente_id:
        return False

    ticket, destinatario, tipo = localizar_ticket_remetente(remetente_id)
    if not ticket:
        return False
    ticket = registrar_mensagens_ticket(
        ticket,
        referencia_objeto_mensagem_ticket(mensagem, remetente_id),
    )
    if tipo == "aguardando":
        resposta = await mensagem.reply_text(
            "⏳ Seu ticket ainda está aguardando um atendente. "
            "Você receberá um aviso assim que alguém assumir.",
            reply_markup=botoes_ticket(ticket["id"]),
        )
        registrar_mensagens_ticket(
            ticket,
            referencia_objeto_mensagem_ticket(resposta, remetente_id),
        )
        return True
    if not destinatario:
        resposta = await mensagem.reply_text("⚠️ Não encontrei o outro participante deste ticket.")
        registrar_mensagens_ticket(
            ticket,
            referencia_objeto_mensagem_ticket(resposta, remetente_id),
        )
        return True

    numero = ticket_id_texto(ticket.get("id"))
    if tipo == "cliente":
        titulo = f"💬 Ticket #{numero} — mensagem do cliente"
    else:
        titulo = (
            f"💬 Ticket #{numero} — "
            f"{nome_cargo(cargo_usuario_id(remetente_id))}"
        )

    encaminhadas = []
    try:
        if mensagem.text is not None:
            enviada = await context.bot.send_message(
                chat_id=destinatario,
                text=f"{titulo}\n\n{mensagem.text}",
                reply_markup=botoes_ticket(ticket["id"]),
                disable_web_page_preview=True,
            )
            encaminhadas.append(
                referencia_objeto_mensagem_ticket(enviada, destinatario)
            )
        else:
            titulo_enviado = await context.bot.send_message(chat_id=destinatario, text=titulo)
            encaminhadas.append(
                referencia_objeto_mensagem_ticket(titulo_enviado, destinatario)
            )
            copia = await context.bot.copy_message(
                chat_id=destinatario,
                from_chat_id=mensagem.chat_id,
                message_id=mensagem.message_id,
                reply_markup=botoes_ticket(ticket["id"]),
            )
            encaminhadas.append(
                referencia_objeto_mensagem_ticket(copia, destinatario)
            )
    except Exception as exc:
        logging.warning("Falha ao encaminhar mensagem do ticket %s: %s", numero, exc)
        resposta = await mensagem.reply_text(
            "⚠️ Não consegui encaminhar esta mensagem. Tente novamente em alguns instantes."
        )
        encaminhadas.append(
            referencia_objeto_mensagem_ticket(resposta, remetente_id)
        )
    registrar_mensagens_ticket(ticket, *encaminhadas)
    return True


async def enviar_inicio_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envia o menu inicial com a arte de boas-vindas.

    Quando o cliente vem de um botão antigo, a mensagem anterior é apagada
    antes de continuar o fluxo, evitando que a imagem fique poluindo o chat.
    """
    texto = CATALOGO["mensagens"]["inicio"]
    reply_markup = menu_principal()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    if WELCOME_IMAGE_PATH.exists():
        try:
            with open(WELCOME_IMAGE_PATH, "rb") as photo:
                mensagem = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=texto,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            guardar_mensagem_bot(context, mensagem)
            return mensagem
        except Exception as exc:
            logging.warning("Falha ao enviar imagem de boas-vindas: %s", exc)

    mensagem = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)
    return mensagem


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if await bloquear_se_manutencao(update, context):
        return
    if not registro_aprovado(update):
        await enviar_acesso_bloqueado(update, context)
        return

    await enviar_inicio_cliente(update, context)


async def processar_valor_recarga_saldo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto_usuario: str,
):
    valor_centavos = parse_valor_recarga_centavos(texto_usuario)
    if valor_centavos is None:
        await update.message.reply_text(
            "❌ Digite somente o valor. Exemplos: `5`, `20,00` ou `150,50`.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_cancelar_recarga(),
        )
        return

    if not SALDO_MINIMO_RECARGA_CENTAVOS <= valor_centavos <= SALDO_MAXIMO_RECARGA_CENTAVOS:
        await update.message.reply_text(
            "❌ O valor da recarga precisa ficar entre *R$ 5,00 e R$ 300,00*.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_cancelar_recarga(),
        )
        return

    context.user_data.pop("adicionando_saldo", None)
    recarga = preparar_recarga_saldo(update, valor_centavos)
    context.user_data["recarga_saldo_id"] = recarga["recarga_id"]
    DB.salvar_recarga_saldo(recarga["recarga_id"], recarga)

    ok, mensagem = await garantir_pix_recarga_saldo(recarga)
    if not ok:
        recarga["status"] = "erro_ao_gerar_pix"
        recarga["erro"] = mensagem
        recarga["atualizado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
        DB.salvar_recarga_saldo(recarga["recarga_id"], recarga)
        await enviar_texto_sequencial(
            update,
            context,
            (
                "⚠️ Não consegui gerar o Pix da recarga agora.\n\n"
                f"*Motivo:* {md(mensagem)}\n\n"
                "Tente novamente em alguns instantes."
            ),
            menu_cancelar_recarga(),
        )
        return

    await enviar_texto_sequencial(
        update,
        context,
        texto_pix_recarga(recarga),
        botoes_pix_recarga(recarga, permitir_retomar=bool(context.user_data.get("pedido"))),
    )


async def verificar_recarga_saldo_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    recarga_id: str,
):
    query = update.callback_query
    recarga = DB.obter_recarga_saldo(recarga_id)
    user_id = telegram_id_update(update)
    if not recarga or str(recarga.get("user_id") or "") != user_id:
        await query.answer("Recarga não encontrada para esta conta.", show_alert=True)
        return

    if recarga.get("status") == "aprovada":
        await query.answer("Esta recarga já foi aprovada.")
        await enviar_texto_sequencial(
            update,
            context,
            texto_confirmacao_recarga(
                recarga,
                saldo_usuario_centavos(user_id),
                ja_aprovada=True,
            ),
            botoes_pix_recarga(recarga, permitir_retomar=bool(context.user_data.get("pedido"))),
        )
        return

    payment_id = str(recarga.get("mp_payment_id") or "")
    if not payment_id:
        await query.answer("Esta recarga não possui um Pix válido.", show_alert=True)
        return

    await query.answer("Verificando recarga...")
    try:
        pagamento = await asyncio.to_thread(consultar_pagamento_mercado_pago_sync, payment_id)
    except Exception as exc:
        await enviar_texto_sequencial(
            update,
            context,
            f"⚠️ Não consegui consultar a recarga agora: {md(limpar_erro_api(exc))}",
            botoes_pix_recarga(recarga, permitir_retomar=bool(context.user_data.get("pedido"))),
        )
        return

    status_mp = str(pagamento.get("status") or "").lower()
    if status_mp == "approved":
        processado = await asyncio.to_thread(
            processar_recarga_aprovada_sync,
            recarga,
            pagamento,
            "verificacao_cliente",
        )
        recarga_atual = DB.obter_recarga_saldo(recarga_id) or recarga
        if processado and recarga_atual.get("status") == "aprovada":
            await enviar_texto_sequencial(
                update,
                context,
                texto_confirmacao_recarga(
                    recarga_atual,
                    saldo_usuario_centavos(user_id),
                ),
                botoes_pix_recarga(
                    recarga_atual,
                    permitir_retomar=bool(context.user_data.get("pedido")),
                ),
            )
            return

        await enviar_texto_sequencial(
            update,
            context,
            "⚠️ O pagamento foi localizado, mas a recarga não pôde ser validada. Fale com o suporte.",
            menu_carteira_saldo(),
        )
        return

    if status_mp in {"cancelled", "canceled", "expired"}:
        recarga["status"] = "expirada" if status_mp == "expired" else "cancelada"
        recarga["mp_status"] = status_mp
        recarga["atualizado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
        DB.salvar_recarga_saldo(recarga_id, recarga)
        await enviar_texto_sequencial(
            update,
            context,
            "⌛ Este Pix não está mais disponível. Gere uma nova recarga para adicionar saldo.",
            menu_carteira_saldo(),
        )
        return

    await enviar_texto_sequencial(
        update,
        context,
        (
            "⏳ *Recarga aguardando pagamento*\n\n"
            "Ainda não recebemos a confirmação do Pix. Confira no seu banco, aguarde alguns segundos e tente novamente."
        ),
        botoes_pix_recarga(recarga, permitir_retomar=bool(context.user_data.get("pedido"))),
    )


async def retomar_pedido_apos_recarga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pedido = context.user_data.get("pedido")
    if not pedido or not pedido.get("link"):
        await safe_edit_or_reply(
            update,
            "Seu saldo está disponível. Escolha um serviço no catálogo para fazer o pedido.",
            InlineKeyboardMarkup(
                [
                    [btn("📖 Abrir catálogo", "menu:catalogo")],
                    [btn("💳 Consultar saldo", "saldo:consultar")],
                ]
            ),
        )
        return
    pedido["status"] = "aguardando_saldo"
    await processar_pedido_com_saldo_cliente(update, context, pedido)


def texto_final_pedido(pedido: dict) -> str:
    pago_com_saldo = str(pedido.get("forma_pagamento") or "") == "saldo"
    mensagem_confirmacao = (
        "🎉 *Pedido confirmado com o saldo da sua carteira!*"
        if pago_com_saldo
        else "🎉 *Pagamento confirmado com sucesso!*"
    )
    status_confirmacao = "• Saldo utilizado e pedido confirmado" if pago_com_saldo else "• Pagamento aprovado"
    detalhe_saldo = ""
    if pago_com_saldo and pedido.get("saldo_apos_centavos") is not None:
        detalhe_saldo = (
            f"💳 *Saldo restante:* R$ {md(centavos_para_moeda(int(pedido.get('saldo_apos_centavos') or 0)))}\n"
        )

    if pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
        if pedido.get("plataforma_api_status") == "enviado":
            return (
                "✅ *Etapa 3 de 3 — Pedido aprovado*\n\n"
                f"{mensagem_confirmacao}\n\n"
                f"📦 *Produto:* {md(pedido.get('catalogo', ''))}\n"
                f"📌 *Serviço:* {md(pedido.get('servico', ''))}\n"
                f"🔢 *Quantidade:* {md(pedido.get('quantidade', ''))}\n"
                f"{detalhe_saldo}"
                f"🚀 *ID na plataforma:* `{md(pedido.get('plataforma_order_id', 'Não informado'))}`\n\n"
                "📌 *Status do pedido*\n"
                f"{status_confirmacao}\n"
                "• Pedido enviado para a plataforma\n"
                "• Processamento iniciado automaticamente\n\n"
                "⏳ O tempo de conclusão pode variar conforme o volume do serviço.\n\n"
                "🎫 Precisa de ajuda? Fale com o suporte."
            )

        erro = pedido.get("plataforma_api_erro") or "Erro não informado."
        if pedido.get("plataforma_api_status") == "revisao_manual":
            return (
                "✅ *Etapa 3 de 3 — Pedido confirmado*\n\n"
                "⚠️ Para evitar pedido duplicado, o envio automático foi pausado e enviado para revisão manual.\n"
                "O administrador vai conferir se esse pedido já apareceu na plataforma antes de reenviar.\n\n"
                f"*Motivo:* {md(erro)}"
            )

        return (
            "✅ *Etapa 3 de 3 — Pedido confirmado*\n\n"
            "⚠️ O relatório foi enviado para o administrador, mas o envio automático para a plataforma falhou.\n\n"
            f"*Motivo:* {md(erro)}"
        )

    if catalogo_exige_email(pedido):
        return (
            "✅ *Etapa 3 de 3 — Pedido aprovado*\n\n"
            f"{mensagem_confirmacao}\n\n"
            f"📦 *Produto:* {md(pedido.get('catalogo', ''))}\n"
            f"📌 *Serviço:* {md(pedido.get('servico', ''))}\n"
            f"🆔 *Pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
            f"{detalhe_saldo}\n"
            "📌 *Status do pedido*\n"
            f"{status_confirmacao}\n"
            "• Pedido recebido pela equipe\n"
            "• Aguardando ativação/envio dos dados\n\n"
            "🛠️ *Próximo passo*\n"
            "Nossa equipe vai processar seu acesso e enviar as informações assim que estiver tudo pronto.\n\n"
            "🎫 Precisa de ajuda? Fale com o suporte."
        )

    return (
        "✅ *Etapa 3 de 3 — Pedido aprovado*\n\n"
        f"{mensagem_confirmacao}\n\n"
        f"{detalhe_saldo}"
        "📌 *Status do pedido*\n"
        f"{status_confirmacao}\n"
        "• Pedido recebido pela equipe\n"
        "• Aguardando processamento\n\n"
        "🎫 Precisa de ajuda? Fale com o suporte."
    )


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

    if await encerrar_interacao_se_pagamento_expirado(update, context, pedido):
        await query.answer("Pedido expirado.", show_alert=True)
        return

    await query.answer("Verificando pagamento...")
    try:
        pagamento = await asyncio.to_thread(consultar_pagamento_mercado_pago_sync, str(pedido.get("mp_payment_id")))
    except Exception as exc:
        await safe_edit_or_reply(update, f"⚠️ Falha ao consultar Mercado Pago: {md(limpar_erro_api(exc))}", botoes_pagamento(pedido))
        return

    status_pagamento_mp = str(pagamento.get("status") or "").lower()

    if status_pagamento_mp in {"cancelled", "canceled", "expired"}:
        pedido_id = str(pedido.get("pedido_id") or "")
        await asyncio.to_thread(
            fechar_pagamento_expirado,
            pedido_id,
            pedido,
            f"Mercado Pago retornou status {status_pagamento_mp}",
        )
        context.user_data.clear()
        await safe_edit_or_reply(
            update,
            (
                "⌛️ Esse link de pagamento não está mais disponível.\n\n"
                f"ID do pedido: `{md(pedido_id)}`\n\n"
                "Para comprar, toque em *Fazer novo pedido* e comece do início."
            ),
            botoes_pedido_expirado(),
        )
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

    await safe_edit_or_reply(
        update,
        (
            "⏳ *Pagamento em análise*\n\n"
            "Ainda não identificamos a confirmação do seu Pix.\n\n"
            "📌 *O que fazer agora?*\n"
            "• Confira se o pagamento foi concluído no seu banco\n"
            "• Aguarde alguns segundos\n"
            "• Toque novamente em “Verificar pagamento”\n\n"
            "Assim que o pagamento for confirmado, seu pedido continuará automaticamente."
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


def nome_admin(update: Update) -> str:
    return update.effective_user.full_name if update.effective_user else "Administrador"


def salvar_pedido_resolvido_revisao(pedido: dict):
    if not pedido:
        return
    salvar_pedido_historico(pedido)
    remover_pedido_pendente(str(pedido.get("pedido_id") or ""))
    payment_id = str(pedido.get("mp_payment_id") or "").strip()
    if payment_id:
        marcar_pagamento_processado(payment_id, pedido)


def buscar_pedido_revisao_manual(pedido_id: str) -> tuple[dict | None, str | None]:
    pedido, origem = buscar_pedido_local_por_id(pedido_id)
    if not pedido:
        return None, None
    return pedido, origem


async def limpar_botoes_revisao(query):
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


async def admin_revisao_ja_foi(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido_id: str):
    query = update.callback_query
    if not eh_admin(update):
        await query.answer("Somente Dono ou Gerente pode resolver revisão manual.", show_alert=True)
        return

    pedido, _origem = buscar_pedido_revisao_manual(pedido_id)
    if not pedido:
        await query.answer("Pedido não encontrado no histórico/pendentes.", show_alert=True)
        return

    if pedido_ja_enviado_para_plataforma(pedido) and pedido.get("plataforma_resolucao_manual") != "ja_foi_feito":
        await query.answer("Esse pedido já está marcado como enviado.", show_alert=True)
        await limpar_botoes_revisao(query)
        return

    pedido["status"] = pedido.get("status") or "pagamento_aprovado"
    pedido["plataforma_api_status"] = "enviado"
    if not pedido_tem_id_plataforma(pedido.get("plataforma_order_id")):
        pedido["plataforma_order_id"] = "Feito manualmente pelo admin"
    pedido["plataforma_api_erro"] = ""
    pedido["plataforma_resolucao_manual"] = "ja_foi_feito"
    pedido["plataforma_resolvido_manual_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido["plataforma_resolvido_por"] = nome_admin(update)
    salvar_pedido_resolvido_revisao(pedido)

    await query.answer("Marcado como já feito.")
    await limpar_botoes_revisao(query)
    await query.message.reply_text(
        f"✅ Pedido `{md(pedido.get('pedido_id', pedido_id))}` marcado como *já feito*.\n\n"
        "Ele foi salvo como resolvido e não será reenviado após reiniciar o Railway.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def reenviar_pedido_revisao_manual_para_plataforma(pedido: dict, admin_nome: str) -> tuple[bool, str]:
    if pedido.get("catalogo") not in CATALOGOS_COM_ENVIO_API:
        return False, "Esse catálogo não tem envio automático configurado."

    if pedido_ja_enviado_para_plataforma(pedido):
        pedido["plataforma_api_status"] = "enviado"
        salvar_pedido_resolvido_revisao(pedido)
        return True, "Esse pedido já estava marcado como enviado."

    pedido["status"] = pedido.get("status") or "pagamento_aprovado"
    pedido["plataforma_api_status"] = "processando"
    pedido["plataforma_reenvio_manual_por"] = admin_nome
    pedido["plataforma_reenvio_manual_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido["plataforma_processando_em"] = pedido["plataforma_reenvio_manual_em"]
    salvar_pedido_pendente(pedido)

    try:
        resultado = await asyncio.to_thread(criar_pedido_plataforma_sync, pedido)
    except Exception as exc:
        marcar_envio_plataforma_para_revisao_manual(
            pedido,
            origem="botao_reenviar_admin",
            motivo=(
                "Reenvio manual solicitado pelo admin falhou ou não retornou com segurança. "
                f"Erro: {limpar_erro_api(exc)}. Confira na plataforma antes de tentar novamente."
            ),
        )
        pedido["plataforma_ultimo_reenvio_manual_erro_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
        salvar_pedido_resolvido_revisao(pedido)
        return False, str(pedido.get("plataforma_api_erro") or "Falha ao reenviar.")

    pedido["plataforma_api_status"] = "enviado"
    pedido["plataforma_service_id"] = resultado.get("service_id")
    pedido["plataforma_quantidade"] = resultado.get("quantity")
    pedido["plataforma_order_id"] = resultado.get("order_id") or "Não informado"
    pedido["plataforma_resposta"] = resultado.get("response")
    pedido["plataforma_api_erro"] = ""
    pedido["plataforma_resolucao_manual"] = "reenviado"
    pedido["plataforma_resolvido_manual_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido["plataforma_resolvido_por"] = admin_nome
    salvar_pedido_resolvido_revisao(pedido)
    return True, f"Pedido reenviado para a plataforma. ID: {pedido.get('plataforma_order_id', 'Não informado')}"


async def admin_revisao_reenviar(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido_id: str):
    query = update.callback_query
    if not eh_admin(update):
        await query.answer("Somente Dono ou Gerente pode reenviar revisão manual.", show_alert=True)
        return

    pedido, _origem = buscar_pedido_revisao_manual(pedido_id)
    if not pedido:
        await query.answer("Pedido não encontrado no histórico/pendentes.", show_alert=True)
        return

    await query.answer("Reenviando para a plataforma...")
    await query.message.reply_text(
        f"🔁 Reenvio manual iniciado para o pedido `{md(pedido.get('pedido_id', pedido_id))}`...",
        parse_mode=ParseMode.MARKDOWN,
    )
    ok, mensagem = await reenviar_pedido_revisao_manual_para_plataforma(pedido, nome_admin(update))

    if ok:
        await limpar_botoes_revisao(query)
        await query.message.reply_text(
            f"✅ {md(mensagem)}\n\nO pedido foi salvo como enviado e não será reenviado no restart.",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            await context.bot.send_message(
                chat_id=pedido.get("user_id"),
                text=texto_final_pedido(pedido),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logging.warning("Falha ao avisar cliente sobre reenvio manual: %s", exc)
        return

    await query.message.reply_text(
        f"⚠️ Não consegui reenviar o pedido `{md(pedido.get('pedido_id', pedido_id))}`.\n\n"
        f"Motivo: {md(mensagem)}\n\n"
        "Os botões continuam válidos para você tentar novamente, marcar como já feito ou ignorar.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_revisao_ignorar(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido_id: str):
    query = update.callback_query
    if not eh_admin(update):
        await query.answer("Somente Dono ou Gerente pode ignorar revisão manual.", show_alert=True)
        return

    pedido, _origem = buscar_pedido_revisao_manual(pedido_id)
    if not pedido:
        await query.answer("Pedido não encontrado no histórico/pendentes.", show_alert=True)
        return

    pedido["status"] = pedido.get("status") or "pagamento_aprovado"
    pedido["plataforma_api_status"] = "ignorado_manual"
    pedido["plataforma_api_erro"] = "Pendência ignorada manualmente pelo admin. O bot não reenviará este pedido automaticamente."
    pedido["plataforma_resolucao_manual"] = "ignorado"
    pedido["plataforma_resolvido_manual_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    pedido["plataforma_resolvido_por"] = nome_admin(update)
    salvar_pedido_resolvido_revisao(pedido)

    await query.answer("Pendência ignorada.")
    await limpar_botoes_revisao(query)
    await query.message.reply_text(
        f"❌ Pendência do pedido `{md(pedido.get('pedido_id', pedido_id))}` ignorada.\n\n"
        "Ela foi salva no histórico e não será reenviada após reiniciar o Railway.",
        parse_mode=ParseMode.MARKDOWN,
    )


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

    if await bloquear_se_manutencao(update, context):
        return

    if data.startswith("admin_revisao_feito:"):
        pedido_id = data.split(":", 1)[1]
        await admin_revisao_ja_foi(update, context, pedido_id)
        return

    if data.startswith("admin_revisao_reenviar:"):
        pedido_id = data.split(":", 1)[1]
        await admin_revisao_reenviar(update, context, pedido_id)
        return

    if data.startswith("admin_revisao_ignorar:"):
        pedido_id = data.split(":", 1)[1]
        await admin_revisao_ignorar(update, context, pedido_id)
        return

    if data == "registro:criar":
        await iniciar_registro_usuario(update, context)
        return

    if data == "registro:status":
        await mostrar_status_registro(update, context)
        return

    if data.startswith("admin_registro_aprovar:"):
        telegram_id = data.split(":", 1)[1]
        await aprovar_registro_admin(update, context, telegram_id)
        return

    if data.startswith("admin_registro_negar:"):
        telegram_id = data.split(":", 1)[1]
        await negar_registro_admin(update, context, telegram_id)
        return

    if data == "admin_painel:inicio":
        await mostrar_painel_admin(update, context)
        return

    if data == "admin_painel:notificacoes":
        await mostrar_notificacoes_admin(update, context)
        return

    if data == "admin_notificacoes:manutencao":
        await mostrar_manutencao_admin(update, context)
        return

    if data == "admin_notificacoes:inicio":
        await notificar_inicio_manutencao(update, context)
        return

    if data == "admin_notificacoes:conclusao":
        await notificar_conclusao_manutencao(update, context)
        return

    if data == "admin_painel:relatorios":
        await mostrar_menu_relatorios_admin(update, context)
        return

    if data == "admin_painel:relatorio_semanal":
        await mostrar_relatorio_semanal_admin(update, context)
        return

    if data == "admin_painel:relatorio_diario":
        await mostrar_relatorio_diario_admin(update, context)
        return

    if data == "admin_painel:resumo":
        await mostrar_resumo_admin(update, context)
        return

    if data == "admin_painel:ultimos":
        await mostrar_ultimos_pedidos_admin(update, context)
        return

    if data == "admin_painel:consultar_cadastros":
        await mostrar_consultar_cadastros_admin(update, context)
        return

    if data == "admin_painel:cadastros_pendentes":
        await mostrar_cadastros_pendentes_admin(update, context)
        return

    if data == "admin_painel:pagamentos_pendentes":
        await mostrar_pagamentos_pendentes_admin(update, context)
        return

    if data == "admin_painel:consultar_vendedores":
        await mostrar_menu_consultar_vendedores_admin(update, context)
        return

    if data == "admin_painel:buscar_usuario":
        await solicitar_busca_usuario_admin(update, context)
        return

    if data == "admin_painel:remover_registro":
        await solicitar_remover_registro_admin(update, context)
        return

    if data == "admin_painel:usuarios":
        await mostrar_usuarios_aprovados_admin(update, context)
        return

    if data == "admin_painel:banir_desbanir":
        await mostrar_menu_banir_desbanir_admin(update, context)
        return

    if data == "admin_painel:banir":
        await solicitar_banimento_admin(update, context)
        return

    if data == "admin_painel:desbanir":
        await solicitar_desbanimento_admin(update, context)
        return

    if data == "admin_painel:cargos":
        await mostrar_gerenciar_cargos_admin(update, context)
        return

    if data.startswith("admin_cargos:usuarios:"):
        pagina = data.rsplit(":", 1)[1]
        await mostrar_usuarios_cargos_admin(update, context, pagina)
        return

    if data.startswith("admin_cargos:usuario:"):
        partes = data.split(":", 3)
        if len(partes) == 4:
            _, _, telegram_id, pagina = partes
            await mostrar_usuario_cargos_admin(
                update,
                context,
                telegram_id,
                pagina,
            )
        else:
            await query.answer("Ação de usuário inválida.", show_alert=True)
        return

    if data.startswith("admin_cargos:aplicar:"):
        partes = data.split(":", 3)
        if len(partes) == 4:
            _, _, telegram_id, pagina = partes
            await mostrar_escolher_cargo_usuario_admin(
                update,
                context,
                telegram_id,
                pagina,
            )
        else:
            await query.answer("Ação de cargo inválida.", show_alert=True)
        return

    if data.startswith("admin_cargos:remover:"):
        partes = data.split(":", 3)
        if len(partes) == 4:
            _, _, telegram_id, pagina = partes
            await remover_cargo_admin(
                update,
                context,
                telegram_id,
                pagina,
            )
        else:
            await query.answer("Ação de cargo inválida.", show_alert=True)
        return

    if data.startswith("admin_cargo:"):
        partes = data.split(":")
        if len(partes) in (3, 4):
            _, cargo_novo, telegram_id = partes[:3]
            pagina = partes[3] if len(partes) == 4 else 0
            await aplicar_cargo_admin(
                update,
                context,
                cargo_novo,
                telegram_id,
                pagina,
            )
        else:
            await query.answer("Ação de cargo inválida.", show_alert=True)
        return

    if data.startswith("ticket:assumir:"):
        ticket_id = data.split(":", 2)[2]
        await assumir_ticket_suporte(update, context, ticket_id)
        return

    if data.startswith("ticket:fechar:"):
        ticket_id = data.split(":", 2)[2]
        await fechar_ticket_suporte(update, context, ticket_id)
        return

    if await bloquear_se_sem_acesso(update, context):
        await query.answer("Faça o cadastro e aguarde a aprovação para usar o bot.", show_alert=True)
        return

    if data == "saldo:consultar":
        context.user_data.pop("adicionando_saldo", None)
        context.user_data.pop("consulta_pedido", None)
        context.user_data.pop("refil_pedido", None)
        await safe_edit_or_reply(
            update,
            texto_carteira_saldo(telegram_id_update(update)),
            menu_carteira_saldo(),
        )
        return

    if data == "saldo:adicionar":
        context.user_data.pop("consulta_pedido", None)
        context.user_data.pop("refil_pedido", None)
        context.user_data["adicionando_saldo"] = True
        await safe_edit_or_reply(
            update,
            texto_informar_valor_recarga(),
            menu_cancelar_recarga(),
        )
        return

    if data.startswith("saldo:verificar:"):
        recarga_id = data.split(":", 2)[2]
        await verificar_recarga_saldo_cliente(update, context, recarga_id)
        return

    if data == "saldo:retomar_pedido":
        await query.answer("Conferindo saldo e processando pedido...")
        await retomar_pedido_apos_recarga(update, context)
        return

    # Qualquer navegação fora da carteira encerra somente a espera pelo valor,
    # sem apagar um pedido que já esteja sendo montado.
    context.user_data.pop("adicionando_saldo", None)

    if data == "suporte:chat":
        context.user_data.clear()
        await abrir_ticket_suporte(update, context)
        return

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
        await enviar_inicio_cliente(update, context)
        return

    if data == "perfil:meu":
        context.user_data.clear()
        await safe_edit_or_reply(
            update,
            texto_my_profile_cliente(update),
            menu_my_profile_cliente(),
        )
        return

    if data == "pedido:consultar":
        context.user_data.clear()
        await safe_edit_or_reply(
            update,
            (
                "📦 *Central de pedidos*\n\n"
                "Acompanhe seus pedidos de forma rápida e organizada.\n\n"
                "Escolha uma opção abaixo:"
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
                "🔎 *Consultar Status*\n\n"
                "Envie o ID do pedido que você quer consultar.\n\n"
                "Pode ser o *ID do pedido no bot* ou o *ID da plataforma*.\n"
                "Assim eu busco o status certinho para você."
            ),
            InlineKeyboardMarkup([[btn("⬅️ Voltar para pedidos", "pedido:consultar")]]),
        )
        return

    if data == "pedido:solicitar_refil":
        context.user_data.clear()
        context.user_data["refil_pedido"] = True
        await safe_edit_or_reply(
            update,
            (
                "🔄 *Solicitar Reposição*\n\n"
                "Envie o ID do pedido que precisa de reposição.\n\n"
                "Eu vou conferir se o pedido tem ID na plataforma e se esse serviço permite refil.\n"
                "Se estiver tudo certo, envio a solicitação para você."
            ),
            InlineKeyboardMarkup([[btn("⬅️ Voltar para pedidos", "pedido:consultar")]]),
        )
        return

    if data.startswith("pedido:refil:"):
        order_id = data.split(":", 2)[2]
        await processar_solicitacao_refil(update, context, order_id)
        return

    if data == "menu:catalogo":
        await enviar_catalogo_cliente(update, context)
        return

    if data == "catalogo:redes_sociais":
        await enviar_engajamentos_cliente(update, context)
        return

    if data == "catalogo:assinaturas":
        context.user_data.pop("pedido", None)
        await safe_edit_or_reply(
            update,
            CATALOGO["catalogos"]["assinaturas"]["mensagem"],
            menu_assinaturas(),
        )
        return

    if data.startswith("assinatura:"):
        servico_chave = data.split(":", 1)[1]
        servico = CATALOGO["catalogos"]["assinaturas"]["servicos"].get(servico_chave)
        if not servico:
            await safe_edit_or_reply(
                update,
                "❌ Assinatura não encontrada no catálogo.",
                InlineKeyboardMarkup([[btn("⬅️ Voltar às assinaturas", "catalogo:assinaturas")]]),
            )
            return

        context.user_data["pedido"] = preparar_pedido({
            "catalogo": "Assinaturas",
            "servico_chave": servico_chave,
            "servico": servico["nome"],
            "quantidade": "1 assinatura",
            "valor": servico["valor"],
            "link": None,
            "tipo_destino": "email",
            "status": "aguardando_email_iptv",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        })

        await enviar_assinatura_cliente(
            update,
            context,
            servico_chave,
            servico["mensagem"],
            InlineKeyboardMarkup([[btn("⬅️ Voltar às assinaturas", "catalogo:assinaturas")]]),
        )
        return

    if data.startswith("extra:"):
        extra = data.split(":", 1)[1]
        texto = CATALOGO.get("menus_extras", {}).get(extra)
        if not texto:
            context.user_data.clear()
            await enviar_inicio_cliente(update, context)
            return
        keyboard = [[btn("⬅️ Voltar", "voltar:inicio")]]
        if extra == "atendimento":
            await enviar_atendimento_cliente(update, context, texto, menu_suporte_cliente())
            return
        await safe_edit_or_reply(update, texto, InlineKeyboardMarkup(keyboard))
        return


    if data == "catalogo:instagram":
        await enviar_instagram_cliente(update, context)
        return

    if data == "catalogo_instagram:estrangeiros":
        await enviar_instagram_estrangeiros_cliente(update, context)
        return

    if data == "catalogo_instagram:brasileiros":
        await enviar_instagram_brasileiros_cliente(update, context)
        return

    if data.startswith("servico_instagram_br:"):
        servico_chave = data.split(":", 1)[1]
        servico = CATALOGO["catalogos"]["instagram"].get("servicos_brasileiros", {}).get(servico_chave)
        if not servico:
            await safe_edit_or_reply(
                update,
                "❌ Serviço brasileiro não encontrado no catálogo.",
                InlineKeyboardMarkup([[btn("⬅️ Voltar aos serviços brasileiros", "catalogo_instagram:brasileiros")]]),
            )
            return

        if not servico.get("itens"):
            await safe_edit_or_reply(
                update,
                servico.get("mensagem") or (
                    f"🇧🇷 *Instagram — {servico.get('nome', 'Serviço brasileiro')}*\n\n"
                    "Os botões já foram adicionados, mas os valores/pacotes ainda não foram configurados.\n\n"
                    "Quando você adicionar os valores no catálogo, eles aparecem aqui."
                ),
                menu_itens_instagram_brasileiros(servico_chave),
            )
            return

        await safe_edit_or_reply(update, servico["mensagem"], menu_itens_instagram_brasileiros(servico_chave))
        return

    if data.startswith("item_instagram_br:"):
        _, servico_chave, quantidade_str = data.split(":")
        quantidade = int(quantidade_str)
        item = get_item_instagram_brasileiros(servico_chave, quantidade)
        servico = CATALOGO["catalogos"]["instagram"]["servicos_brasileiros"][servico_chave]

        pedido = preparar_pedido({
            "catalogo": "Instagram — Serviços Brasileiros",
            "catalogo_api": "Instagram_Brasileiros",
            "servico_chave": servico_chave,
            "servico": servico["nome"],
            "quantidade": item["quantidade_texto"],
            "quantidade_api": item["quantidade"],
            "api_service_id": item.get("api_service_id") or servico.get("api_service_id"),
            "valor": item["valor"],
            "link": None,
            "status": "aguardando_link",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        })
        info_limite = await obter_limite_solicitacoes_item("Instagram_Brasileiros", servico_chave, item, servico)
        aplicar_limite_solicitacoes_no_pedido(pedido, info_limite)
        context.user_data["pedido"] = pedido
        mensagem_item = aplicar_limite_solicitacoes_na_mensagem(item["mensagem"], info_limite)

        await safe_edit_or_reply(
            update,
            mensagem_item,
            InlineKeyboardMarkup([[btn("⬅️ Voltar", f"servico_instagram_br:{servico_chave}")]]),
            parse_mode=None,
        )
        return

    if data == "catalogo:tiktok":
        await enviar_tiktok_cliente(update, context)
        return

    if data == "catalogo_tiktok:estrangeiros":
        await enviar_tiktok_estrangeiros_cliente(update, context)
        return

    if data.startswith("servico_tiktok:"):
        servico_chave = data.split(":", 1)[1]
        servico = CATALOGO["catalogos"]["tiktok"]["servicos"][servico_chave]
        await safe_edit_or_reply(update, servico["mensagem"], menu_itens_tiktok(servico_chave))
        return

    if data.startswith("item_tiktok:"):
        _, servico_chave, quantidade_str = data.split(":")
        quantidade = int(quantidade_str)
        item = get_item_tiktok(servico_chave, quantidade)
        servico = CATALOGO["catalogos"]["tiktok"]["servicos"][servico_chave]

        pedido = preparar_pedido({
            "catalogo": "TikTok",
            "servico_chave": servico_chave,
            "servico": servico["nome"],
            "quantidade": item["quantidade_texto"],
            "quantidade_api": item["quantidade"],
            "api_service_id": item.get("api_service_id") or servico.get("api_service_id"),
            "valor": item["valor"],
            "link": None,
            "status": "aguardando_link",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        })
        info_limite = await obter_limite_solicitacoes_item("TikTok", servico_chave, item, servico)
        aplicar_limite_solicitacoes_no_pedido(pedido, info_limite)
        context.user_data["pedido"] = pedido
        mensagem_item = aplicar_limite_solicitacoes_na_mensagem(item["mensagem"], info_limite)

        await safe_edit_or_reply(
            update,
            mensagem_item,
            InlineKeyboardMarkup([[btn("⬅️ Voltar", f"servico_tiktok:{servico_chave}")]]),
            parse_mode=None,
        )
        return

    

    if data == "catalogo:kwai":
        context.user_data.pop("pedido", None)
        await enviar_kwai_cliente(update, context)
        return

    if data == "catalogo_kwai:brasileiros":
        context.user_data.pop("pedido", None)
        await enviar_kwai_brasileiros_cliente(update, context)
        return

    if data.startswith("servico_kwai:"):
        context.user_data.pop("pedido", None)
        servico_chave = data.split(":", 1)[1]
        servico = CATALOGO["catalogos"]["kwai"]["servicos"].get(servico_chave)
        if not servico:
            await safe_edit_or_reply(
                update,
                "❌ Serviço Kwai não encontrado no catálogo.",
                InlineKeyboardMarkup([[btn("⬅️ Voltar aos serviços Kwai", "catalogo_kwai:brasileiros")]]),
            )
            return
        await safe_edit_or_reply(update, servico["mensagem"], menu_itens_kwai(servico_chave))
        return

    if data.startswith("item_kwai:"):
        _, servico_chave, quantidade_str = data.split(":")
        quantidade = int(quantidade_str)
        item = get_item_kwai(servico_chave, quantidade)
        servico = CATALOGO["catalogos"]["kwai"]["servicos"][servico_chave]

        pedido = preparar_pedido({
            "catalogo": "Kwai",
            "servico_chave": servico_chave,
            "servico": servico["nome"],
            "quantidade": item["quantidade_texto"],
            "quantidade_api": item["quantidade"],
            "api_service_id": item.get("api_service_id") or servico.get("api_service_id"),
            "valor": item["valor"],
            "link": None,
            "status": "aguardando_link",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        })
        info_limite = await obter_limite_solicitacoes_item("Kwai", servico_chave, item, servico)
        aplicar_limite_solicitacoes_no_pedido(pedido, info_limite)
        context.user_data["pedido"] = pedido
        mensagem_item = aplicar_limite_solicitacoes_na_mensagem(item["mensagem"], info_limite)

        await safe_edit_or_reply(
            update,
            mensagem_item,
            InlineKeyboardMarkup([[btn("⬅️ Voltar", f"servico_kwai:{servico_chave}")]]),
            parse_mode=None,
        )
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
        servico = CATALOGO["catalogos"]["internet_ilimitada"]["servicos"]["1mes"]
        item = servico["itens"][0]
        context.user_data["pedido"] = preparar_pedido({
            "catalogo": "Internet Ilimitada",
            "servico_chave": "1mes",
            "servico": servico.get("nome", "1 mês"),
            "quantidade": item.get("quantidade_texto", "1 mês"),
            "valor": item.get("valor", "15,00"),
            "link": None,
            "status": "aguardando_email_iptv",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        })

        await safe_edit_or_reply(
            update,
            item.get("mensagem") or servico.get("mensagem") or "📧 Envie o e-mail para ativação do serviço.",
            InlineKeyboardMarkup([[btn("⬅️ Voltar", "catalogo:internet")]]),
            parse_mode=None,
        )
        return


    if data == "catalogo:iptv":
        await enviar_iptv_cliente(update, context)
        return

    if data.startswith("item_iptv:"):
        _, servico_chave, quantidade_str = data.split(":")
        servico = CATALOGO["catalogos"]["iptv"]["servicos"][servico_chave]
        item = servico["itens"][0]

        context.user_data["pedido"] = preparar_pedido({
            "catalogo": "IPTV XCIPTV",
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
        pedido.pop("link_validado_antes_pagamento", None)
        pedido.pop("ultima_verificacao_link", None)
        pedido.pop("motivo_bloqueio_link", None)
        pedido["link"] = None
        pedido["status"] = "aguardando_email_iptv"
        await safe_edit_or_reply(update, "✏️ Envie novamente o e-mail correto para continuar.")
        return

    if data == "confirmar_email_iptv":
        pedido = context.user_data.get("pedido")
        if not pedido or not catalogo_exige_email(pedido) or not pedido.get("link"):
            await safe_edit_or_reply(update, "Não encontrei o e-mail do pedido. Envie o e-mail novamente.")
            return
        await query.answer("Conferindo saldo...")
        pedido["status"] = "aguardando_saldo"
        await enviar_pagamento_cliente(update, context, pedido)
        return

    if data.startswith("servico:"):
        servico_chave = data.split(":", 1)[1]
        servico = CATALOGO["catalogos"]["instagram"]["servicos"][servico_chave]
        await safe_edit_or_reply(update, servico["mensagem"], menu_itens(servico_chave))
        return

    if data.startswith("item:"):
        _, servico_chave, quantidade_str = data.split(":")
        quantidade = int(quantidade_str)
        item = get_item(servico_chave, quantidade)
        servico = CATALOGO["catalogos"]["instagram"]["servicos"][servico_chave]

        pedido = preparar_pedido({
            "catalogo": "Instagram",
            "servico_chave": servico_chave,
            "servico": servico["nome"],
            "quantidade": item["quantidade_texto"],
            "quantidade_api": item["quantidade"],
            "api_service_id": item.get("api_service_id") or servico.get("api_service_id"),
            "valor": item["valor"],
            "link": None,
            "status": "aguardando_link",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        })
        info_limite = await obter_limite_solicitacoes_item("Instagram", servico_chave, item, servico)
        aplicar_limite_solicitacoes_no_pedido(pedido, info_limite)
        context.user_data["pedido"] = pedido
        mensagem_item = aplicar_limite_solicitacoes_na_mensagem(item["mensagem"], info_limite)

        await safe_edit_or_reply(
            update,
            mensagem_item,
            InlineKeyboardMarkup([[btn("⬅️ Voltar", f"servico:{servico_chave}")]]),
            parse_mode=None,
        )
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
        pedido.pop("link_validado_antes_pagamento", None)
        pedido.pop("ultima_verificacao_link", None)
        pedido.pop("motivo_bloqueio_link", None)
        pedido["link"] = None
        if catalogo_exige_email(pedido):
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
                [btn("🔁 Enviar outro ID", "pedido:solicitar_refil")],
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
                    "⏳ *Refil ainda não disponível*\n\n"
                    f"🚀 *ID na plataforma:* `{md(order_id)}`\n"
                    f"📌 *Status atual:* {md(traduzir_status_plataforma(status_atual))}\n\n"
                    "Esse pedido ainda está em andamento. Assim que finalizar, você pode pedir a reposição/refil."
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
                [btn("🔎 Consultar Status", "pedido:consultar_status")],
                [btn("🏠 Menu inicial", "voltar:inicio")],
            ]),
        )
        context.user_data.clear()
        return

    except (PlataformaAPIConfigError, PlataformaAPIRequestError) as exc:
        await safe_edit_or_reply(
            update,
            (
                "⚠️ *Não foi possível pedir o refil agora*\n\n"
                f"🚀 *ID na plataforma:* `{md(order_id)}`\n"
                f"*Motivo:* {md(limpar_erro_api(exc))}\n\n"
                "Isso pode acontecer quando o serviço não possui refil, o prazo expirou ou o pedido ainda não está pronto para reposição."
            ),
            botoes_consulta_pedido(order_id),
        )
        context.user_data.clear()
        return


async def responder_consulta_pedido(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_usuario: str):
    consulta_id = normalizar_id_consulta(texto_usuario)
    if not consulta_id:
        await update.message.reply_text(
            "⚠️ Envie um ID de pedido válido para eu consultar.",
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
                    + "\n\n⚠️ Não consegui consultar a plataforma neste momento.\n"
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
                "Confira se o ID está correto e tente novamente em alguns instantes.",
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
        "❌ Não encontrei esse pedido por aqui.\n\n"
        "Confira se o ID foi digitado certinho. Se o pedido já foi enviado para a plataforma, tente enviar o ID da plataforma.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[btn("⬅️ Voltar", "voltar:inicio")]]),
    )


async def receber_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = (update.message.text or "").strip()

    if await bloquear_se_manutencao(update, context):
        return

    if await processar_texto_admin_painel(update, context, texto_usuario):
        return

    if await processar_texto_registro(update, context, texto_usuario):
        return

    if await bloquear_se_sem_acesso(update, context):
        return

    if await processar_mensagem_ticket(update, context):
        return

    if context.user_data.get("adicionando_saldo"):
        await processar_valor_recarga_saldo(update, context, texto_usuario)
        return

    if context.user_data.get("consulta_pedido"):
        await responder_consulta_pedido(update, context, texto_usuario)
        return

    if context.user_data.get("refil_pedido"):
        await processar_solicitacao_refil(update, context, texto_usuario)
        return

    pedido = context.user_data.get("pedido")

    if not pedido:
        await update.message.reply_text(
            "Para iniciar um pedido, toque em /start e escolha uma opção do catálogo.",
            reply_markup=menu_principal(),
        )
        return

    if await encerrar_interacao_se_pagamento_expirado(update, context, pedido):
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
        valido_destino, destino_normalizado, erro_destino = validar_destino_pedido(pedido, texto_usuario)
        if not valido_destino:
            await update.message.reply_text(
                erro_destino,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[btn("⬅️ Alterar serviço", "menu:catalogo")]]),
                disable_web_page_preview=True,
            )
            return

        pedido["link"] = destino_normalizado
        pedido.pop("link_validado_antes_pagamento", None)
        pedido.pop("ultima_verificacao_link", None)
        pedido.pop("motivo_bloqueio_link", None)

        if catalogo_exige_email(pedido) and pedido.get("status") == "aguardando_email_iptv":
            await update.message.reply_text(
                (
                    "📧 *Etapa 1 de 3 — Dados recebidos*\n\n"
                    "Confira o e-mail informado:\n\n"
                    f"`{md(pedido['link'])}`\n\n"
                    "Se estiver correto, toque em *Confirmar e usar saldo*."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=botoes_confirmar_email_iptv(),
                disable_web_page_preview=True,
            )
            return

        pedido["status"] = "aguardando_saldo"
        await enviar_pagamento_cliente(update, context, pedido)
        return

    if pedido.get("status") == "aguardando_saldo":
        await enviar_pagamento_cliente(update, context, pedido)
        return

    destino_recebido = "e-mail" if catalogo_exige_email(pedido) else "link/@"
    await update.message.reply_text(
        f"✅ Já recebi o {destino_recebido}. O pedido será concluído usando o saldo da sua carteira.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=botoes_saldo_insuficiente(pedido),
    )


async def receber_comprovante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await bloquear_se_manutencao(update, context):
        return

    if await bloquear_se_sem_acesso(update, context):
        return

    if await processar_mensagem_ticket(update, context):
        return

    pedido = context.user_data.get("pedido")

    if not pedido:
        await update.message.reply_text(
            "Para iniciar um pedido, toque em /start e escolha uma opção do catálogo.",
            reply_markup=menu_principal(),
        )
        return

    if pedido.get("status") == "aguardando_saldo":
        await update.message.reply_text(
            "💳 Não é necessário enviar comprovante para pedidos. "
            "O valor será descontado automaticamente do saldo da sua carteira.",
            reply_markup=botoes_saldo_insuficiente(pedido),
        )
        return

    if pedido.get("status") not in ("aguardando_pagamento", "aguardando_aprovacao_admin") or not pedido.get("link"):
        destino_necessario = "e-mail" if catalogo_exige_email(pedido) else "link/@"
        await update.message.reply_text(f"Recebi a imagem, mas ainda preciso do {destino_necessario} do pedido primeiro.")
        return

    if await encerrar_interacao_se_pagamento_expirado(update, context, pedido):
        return

    if pedido.get("mp_payment_id"):
        await update.message.reply_text(
            "✅ Neste pedido o pagamento é confirmado automaticamente pelo Mercado Pago. "
            "Não precisa enviar comprovante; pague o Pix e toque em ‘Verificar Pagamento’."
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
    """Envia todo relatório de pedido aprovado ao Admin 1 pelo Telegram."""
    await fechar_semana_se_necessario(context.bot)
    total_semanal_cliente = registrar_pedido_semanal(pedido)
    em_revisao_manual = status_envio_plataforma(pedido) == "revisao_manual"
    titulo = "PEDIDO EM REVISÃO MANUAL — TW STORE" if em_revisao_manual else "NOVO PEDIDO APROVADO — TW STORE"
    enviado = await asyncio.to_thread(
        enviar_relatorio_admin_documento_sync,
        pedido,
        total_semanal_cliente,
        titulo,
    )
    if not enviado:
        logging.error(
            "O pedido %s foi concluído, mas o relatório não pôde ser enviado ao Admin 1.",
            pedido.get("pedido_id"),
        )
    return enviado


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Configure a variável BOT_TOKEN com o token do BotFather.")
    reconstruir_pagamentos_processados_do_historico()
    limpar_pedidos_pendentes_salvos_no_startup()
    limpar_persistencia_transiente_no_startup()
    corrigir_pedidos_com_envio_interrompido()
    webhooks_recuperados = DB.recuperar_webhooks_processando_interrompidos()
    if webhooks_recuperados:
        logging.warning("Webhook(s) travados em processamento foram liberados para rechecagem: %s", webhooks_recuperados)
    iniciar_servidor_web()
    iniciar_rotina_webhook_queue()
    persistence = PicklePersistence(filepath=str(BOT_PERSISTENCE_PATH))
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).post_init(iniciar_rotinas).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("painel", painel_admin))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.ALL), receber_comprovante))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber_texto))
    print("Bot TW STORE iniciado.")
    print(f"Pasta de dados em: {DATA_DIR}")
    print(f"Banco SQLite em: {DATABASE_PATH}")
    # Evita que o Telegram entregue callbacks/mensagens antigas quando o bot reinicia.
    # Sem isso, cliques antigos em botões de pagamento podem ser processados novamente.
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
