import asyncio
import json
import os
import re
import secrets
import hashlib
import shutil
import logging
import threading
import uuid
import time as time_module
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
from decimal import Decimal, ROUND_UP, InvalidOperation
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

CATALOGO_PATH = BASE_DIR / "catalogo.json"
PAGAMENTO_INSTAGRAM_LAYOUT_PATH = BASE_DIR / "pagamento_instagram_layout.png"
PAGAMENTO_TIKTOK_LAYOUT_PATH = BASE_DIR / "pagamento_tiktok_layout.png"

with open(CATALOGO_PATH, "r", encoding="utf-8") as f:
    CATALOGO = json.load(f)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
# Segundo admin: recebe solicitações de cadastro e pode usar /painel, mas não recebe relatórios de venda/pagamento.
ADMIN2_CHAT_ID = os.getenv("ADMIN2_CHAT_ID", os.getenv("SEGUNDO_ADMIN_CHAT_ID", "")).strip()
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

# Trava antes do pagamento: consulta a plataforma antes de gerar Pix.
# Se estiver sem saldo/sem serviço disponível, o cliente não recebe cobrança.
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

# Catálogos Instagram/TikTok com quantidade livre escolhida pelo cliente.
QUANTIDADE_MINIMA_CLIENTE = 100

# Precificação para revendedores.
# A regra abaixo evita preços absurdos em pedidos grandes e impede pedidos pequenos sem lucro.
PRECO_MINIMO_CLIENTE = Decimal("0.80")
PRECO_MINIMO_CURTIDAS_VISUALIZACOES = Decimal("0.50")
TAXA_OPERACIONAL_CLIENTE = Decimal("0.50")
LIMITE_TAXA_OPERACIONAL_CLIENTE = Decimal("4.00")

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
TOTAIS_SEMANAIS_PATH = DATA_DIR / "totais_semanais.json"
PEDIDOS_PENDENTES_PATH = DATA_DIR / "pedidos_pendentes.json"
COMPROVANTES_USADOS_PATH = DATA_DIR / "comprovantes_usados.json"
PAGAMENTOS_PROCESSADOS_PATH = DATA_DIR / "pagamentos_processados.json"
PEDIDOS_HISTORICO_PATH = DATA_DIR / "pedidos_historico.json"
USUARIOS_REGISTRADOS_PATH = DATA_DIR / "usuarios_registrados.json"
BOT_PERSISTENCE_PATH = DATA_DIR / "bot_persistence.pkl"

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


def agora_br() -> datetime:
    return datetime.now(TZ_BR)


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
    """Cria os arquivos de dados do bot e migra arquivos antigos da pasta raiz.

    Isso mantém cadastros, pedidos e pagamentos salvos mesmo após reiniciar o bot,
    desde que a pasta DATA_DIR não seja apagada pela hospedagem.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for nome, padrao in ARQUIVOS_JSON_RUNTIME.items():
        destino = DATA_DIR / nome
        origem_antiga = BASE_DIR / nome

        if origem_antiga.exists() and origem_antiga.resolve() != destino.resolve() and not destino.exists():
            try:
                shutil.copy2(origem_antiga, destino)
                logging.info("Arquivo de dados migrado: %s -> %s", origem_antiga, destino)
            except Exception as exc:
                logging.warning("Não foi possível migrar %s para %s: %s", origem_antiga, destino, exc)

        if padrao is not None and not destino.exists():
            salvar_json(destino, copiar_padrao_json(padrao))


inicializar_arquivos_json_runtime()


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


def ids_admin_registro() -> list[str]:
    """Admins com acesso ao cadastro e ao /painel.

    ADMIN_CHAT_ID continua sendo o admin principal e único destinatário dos
    relatórios financeiros/de pedidos. ADMIN2_CHAT_ID é usado somente para
    aprovar/negar registros e acessar o painel de usuários.
    """
    ids = []
    for admin_id in (ADMIN_CHAT_ID, ADMIN2_CHAT_ID):
        admin_id = str(admin_id or "").strip()
        if admin_id and admin_id not in ids:
            ids.append(admin_id)
    return ids


def eh_admin(update: Update) -> bool:
    admins = ids_admin_registro()
    if not admins:
        return False
    user_id = str(update.effective_user.id) if update.effective_user else ""
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    return user_id in admins or chat_id in admins


def carregar_usuarios_registrados() -> dict:
    return carregar_json(USUARIOS_REGISTRADOS_PATH, {})


def salvar_usuarios_registrados(dados: dict):
    salvar_json(USUARIOS_REGISTRADOS_PATH, dados)


def obter_usuario_registrado(telegram_id) -> dict | None:
    if telegram_id is None:
        return None
    return carregar_usuarios_registrados().get(str(telegram_id))


def hash_senha_registro(senha: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{senha}".encode("utf-8")).hexdigest()
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
            "Sua conta foi banida de usar este bot.\n"
            f"*Motivo:* {md(motivo)}\n\n"
            f"*Telegram ID:* `{md(user.id if user else '')}`"
        )
    if registro and registro.get("status") == "pendente":
        return (
            "⏳ *Cadastro em análise*\n\n"
            "Seu registro já foi enviado para aprovação do administrador.\n"
            "Aguarde a liberação para utilizar o bot."
        )
    if registro and registro.get("status") == "negado":
        liberado, horario = pode_tentar_registro_novamente(registro)
        if not liberado:
            return (
                "❌ *Cadastro negado*\n\n"
                "O administrador negou sua solicitação.\n"
                f"Você poderá tentar novamente após: `{md(horario)}`"
            )
    return (
        "🔐 *Cadastro obrigatório*\n\n"
        "Antes de acessar o bot, crie um usuário e uma senha.\n"
        "Seu cadastro será enviado ao administrador e só será liberado após aprovação."
    )


def menu_registro(update: Update | None = None) -> InlineKeyboardMarkup:
    keyboard = [[btn("📝 Criar cadastro", "registro:criar")]]
    if update and update.effective_user:
        keyboard.append([btn("📌 Ver status do cadastro", "registro:status")])
    return InlineKeyboardMarkup(keyboard)


async def bloquear_se_sem_acesso(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if eh_admin(update) or registro_aprovado(update):
        return False
    mensagem = update.effective_message
    if mensagem:
        await mensagem.reply_text(
            texto_acesso_bloqueado(update),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_registro(update),
        )
    return True


def texto_solicitacao_registro_admin(telegram_id: str, registro: dict) -> str:
    usuario_tg = registro.get("telegram_username") or "Sem @"
    nome = registro.get("nome_telegram") or "Não informado"
    return (
        "🆕 *Novo cadastro aguardando aprovação*\n\n"
        f"*Nome Telegram:* {md(nome)}\n"
        f"*Username Telegram:* {md(usuario_tg)}\n"
        f"*Telegram ID:* `{md(telegram_id)}`\n"
        f"*Usuário criado:* `{md(registro.get('usuario_login', ''))}`\n"
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
        linha_extra = "O cliente já pode usar o bot normalmente."
    else:
        emoji = "❌"
        titulo = "Registro negado"
        data_decisao = registro.get("negado_em") or agora_br().strftime("%d/%m/%Y %H:%M:%S")
        linha_extra = "O cliente poderá tentar novamente após 30 minutos."

    return (
        f"{emoji} *{titulo}*\n\n"
        f"*Nome Telegram:* {md(nome)}\n"
        f"*Username Telegram:* {md(usuario_tg)}\n"
        f"*Telegram ID:* `{md(telegram_id)}`\n"
        f"*Usuário criado:* `{md(usuario_login)}`\n\n"
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
    registro = obter_usuario_registrado(user.id) if user else None

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
    await safe_edit_or_reply(
        update,
        (
            "📝 *Criar cadastro*\n\n"
            "Envie em uma única mensagem o usuário e a senha separados por espaço.\n\n"
            "Exemplo:\n"
            "`meuusuario minhasenha123`\n\n"
            "Regras:\n"
            "• Usuário: mínimo 4 caracteres, apenas letras, números, ponto, traço ou underline.\n"
            "• Senha: mínimo 6 caracteres."
        ),
        InlineKeyboardMarkup([[btn("⬅️ Voltar", "registro:status")]]),
    )


async def mostrar_status_registro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await safe_edit_or_reply(update, texto_acesso_bloqueado(update), menu_registro(update))


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
    registro = {
        "telegram_id": telegram_id,
        "usuario_login": usuario_login,
        "senha_salt": salt,
        "senha_hash": senha_hash,
        "status": "pendente",
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
        await update.message.reply_text(
            "✅ Cadastro enviado para aprovação.\n\nAssim que o administrador aprovar, você poderá usar o bot normalmente.",
            reply_markup=menu_registro(update),
        )
    else:
        await update.message.reply_text(
            "✅ Cadastro criado, mas não consegui avisar nenhum administrador. Verifique se ADMIN_CHAT_ID ou ADMIN2_CHAT_ID estão configurados.",
            reply_markup=menu_registro(update),
        )
    return True


async def aprovar_registro_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: str):
    query = update.callback_query
    if not eh_admin(update):
        await query.answer("Apenas o administrador pode aprovar cadastros.", show_alert=True)
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
    registro["status"] = "aprovado"
    registro["aprovado_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    registro["aprovado_por"] = admin_nome
    registro.pop("tentar_novamente_em", None)
    usuarios[str(telegram_id)] = registro
    salvar_usuarios_registrados(usuarios)

    await query.answer("Cadastro aprovado.")
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
            text="✅ Seu cadastro foi aprovado! Agora você já pode usar o bot. Toque em /start.",
        )
    except Exception as exc:
        logging.warning("Falha ao avisar cliente sobre aprovação de cadastro: %s", exc)


async def negar_registro_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: str):
    query = update.callback_query
    if not eh_admin(update):
        await query.answer("Apenas o administrador pode negar cadastros.", show_alert=True)
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
    tentar_em = agora_br() + timedelta(minutes=30)
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
            text="❌ Seu cadastro foi negado. Você poderá tentar novamente após 30 minutos.",
        )
    except Exception as exc:
        logging.warning("Falha ao avisar cliente sobre negação de cadastro: %s", exc)



def menu_painel_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("👥 Usuários Registrados", "admin_painel:usuarios")],
        [btn("🚫 Banir ou Desbanir", "admin_painel:banir_desbanir")],
    ])


def menu_banir_desbanir_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("🚫 Banir", "admin_painel:banir")],
        [btn("✅ Desbanir", "admin_painel:desbanir")],
        [btn("⬅️ Voltar ao painel", "admin_painel:inicio")],
    ])


def menu_voltar_painel_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("⬅️ Voltar ao painel", "admin_painel:inicio")]])


def texto_painel_admin() -> str:
    return (
        "🛠️ *Painel do Administrador*\n\n"
        "Escolha uma opção abaixo para gerenciar os usuários do bot."
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

    linhas = ["👥 *Usuários Registrados*\n"]
    for telegram_id, registro in aprovados[:80]:
        usuario_login = registro.get("usuario_login") or "sem usuário"
        nome = registro.get("nome_telegram") or "Nome não informado"
        username = registro.get("telegram_username") or "Sem @"
        linhas.append(
            f"• `{md(telegram_id)}` — `{md(usuario_login)}`\n"
            f"  {md(nome)} | {md(username)}"
        )

    if len(aprovados) > 80:
        linhas.append(f"\nMostrando 80 de {len(aprovados)} usuários aprovados.")

    return "\n".join(linhas)


async def painel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.message.reply_text("Apenas administradores podem abrir este painel.")
        return
    context.user_data.clear()
    mensagem = await update.message.reply_text(
        texto_painel_admin(),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_painel_admin(),
        disable_web_page_preview=True,
    )
    guardar_mensagem_bot(context, mensagem)


async def mostrar_painel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem usar este painel.", show_alert=True)
        return
    context.user_data.clear()
    await safe_edit_or_reply(update, texto_painel_admin(), menu_painel_admin())


async def mostrar_usuarios_aprovados_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eh_admin(update):
        await update.callback_query.answer("Apenas administradores podem ver os usuários.", show_alert=True)
        return
    await safe_edit_or_reply(update, texto_usuarios_aprovados_admin(), menu_voltar_painel_admin())


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


async def banir_telegram_id_pelo_painel(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: str) -> str:
    admin_id = str(update.effective_user.id) if update.effective_user else ""
    if telegram_id == admin_id or telegram_id in ids_admin_registro():
        return "⚠️ Não é permitido banir administradores do bot."

    usuarios = carregar_usuarios_registrados()
    registro = usuarios.get(telegram_id, {"telegram_id": telegram_id})
    registro["status"] = "banido"
    registro["motivo_ban"] = "Banido pelo administrador"
    registro["banido_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    registro["banido_por"] = update.effective_user.full_name if update.effective_user else "Administrador"
    registro.pop("tentar_novamente_em", None)
    usuarios[telegram_id] = registro
    salvar_usuarios_registrados(usuarios)

    try:
        await context.bot.send_message(chat_id=telegram_id, text="🚫 Você foi banido de usar este bot.")
    except Exception:
        pass

    return f"🚫 Usuário `{md(telegram_id)}` banido com sucesso."


async def desbanir_telegram_id_pelo_painel(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: str) -> str:
    usuarios = carregar_usuarios_registrados()
    registro = usuarios.get(telegram_id)
    if not registro:
        return "⚠️ Não encontrei esse Telegram ID no cadastro do bot."

    registro["status"] = "aprovado"
    registro["desbanido_em"] = agora_br().strftime("%d/%m/%Y %H:%M:%S")
    registro["desbanido_por"] = update.effective_user.full_name if update.effective_user else "Administrador"
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

    telegram_id = re.sub(r"\D+", "", texto_usuario)
    if not telegram_id:
        await update.message.reply_text(
            "⚠️ Envie apenas o Telegram ID numérico. Exemplo: `123456789`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[btn("⬅️ Voltar", "admin_painel:banir_desbanir")]]),
        )
        return True

    if acao == "banir":
        resposta = await banir_telegram_id_pelo_painel(update, context, telegram_id)
    elif acao == "desbanir":
        resposta = await desbanir_telegram_id_pelo_painel(update, context, telegram_id)
    else:
        resposta = "⚠️ Ação inválida. Abra o /painel novamente."

    context.user_data.clear()
    await update.message.reply_text(
        resposta,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_banir_desbanir_admin(),
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
    dados = carregar_json(TOTAIS_SEMANAIS_PATH, novo_registro_semanal())
    if "semana_id" not in dados or "clientes" not in dados:
        return novo_registro_semanal()
    return dados


def salvar_totais_semanais(dados: dict):
    salvar_json(TOTAIS_SEMANAIS_PATH, dados)


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

    return "ATENÇÃO NO ENVIO", [
        ("Status", "Falhou ou não configurado"),
        ("Erro", texto_relatorio_valor(pedido.get("plataforma_api_erro"), "Sem retorno da API")),
    ]


def blocos_relatorio_admin(pedido: dict, total_semanal_cliente: str, titulo: str | None = None, data_relatorio: str | None = None):
    data_relatorio = data_relatorio or pedido.get("aprovado_em") or agora_br().strftime("%d/%m/%Y %H:%M:%S")
    api_titulo, api_linhas = status_api_relatorio(pedido)
    mp_id = texto_relatorio_valor(pedido.get("mp_payment_id"), "Não informado")
    origem = texto_relatorio_valor(pedido.get("processado_por"), "Não informado")

    blocos = [
        (
            "DADOS DO PEDIDO",
            [
                ("ID do pedido", texto_relatorio_valor(pedido.get("pedido_id"))),
                ("Catálogo", texto_relatorio_valor(pedido.get("catalogo"))),
                ("Serviço", texto_relatorio_valor(pedido.get("servico"))),
                ("Quantidade", texto_relatorio_valor(pedido.get("quantidade"))),
                ("Link/@", texto_relatorio_valor(pedido.get("link"))),
            ],
        ),
        (
            "PAGAMENTO",
            [
                ("Valor aprovado", valor_relatorio_reais(pedido.get("valor"))),
                ("Total do cliente na semana", valor_relatorio_reais(total_semanal_cliente)),
                ("Mercado Pago ID", mp_id),
                ("Aprovado por", texto_relatorio_valor(pedido.get("aprovado_por"), "Mercado Pago")),
                ("Processamento", origem),
                ("Data", data_relatorio),
            ],
        ),
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
        f"📥 *{md(titulo)}*\n\n"
        f"🆔 *Pedido:* `{md(pedido.get('pedido_id', ''))}`\n"
        f"💳 *Mercado Pago ID:* `{md(pedido.get('mp_payment_id', 'Não informado'))}`\n"
        f"🗂️ *Catálogo:* {md(pedido.get('catalogo', ''))}\n"
        f"📌 *Serviço:* {md(pedido.get('servico', ''))}\n"
        f"🔢 *Quantidade:* {md(pedido.get('quantidade', ''))}\n"
        f"💰 *Valor:* {md(valor_relatorio_reais(pedido.get('valor')))}\n"
        f"📆 *Total do cliente nesta semana:* {md(valor_relatorio_reais(total_semanal_cliente))}\n"
        f"🔗 *Link/@:* {md(pedido.get('link', ''))}\n"
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


def enviar_documento_telegram_sync(chat_id, arquivo: BytesIO, caption: str | None = None, parse_mode: str = "Markdown") -> bool:
    if not BOT_TOKEN or not chat_id or arquivo is None:
        return False

    try:
        arquivo.seek(0)
        payload = {"chat_id": chat_id}
        if caption:
            payload["caption"] = caption
            payload["parse_mode"] = parse_mode
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


def enviar_relatorio_admin_documento_sync(pedido: dict, total_semanal_cliente: str, titulo: str = "NOVO PEDIDO PAGO — TW STORE") -> bool:
    imagem = gerar_imagem_relatorio_admin(pedido, total_semanal_cliente, titulo="RELATÓRIO DE VENDA APROVADA")
    if imagem is None:
        return False
    return enviar_documento_telegram_sync(ADMIN_CHAT_ID, imagem, caption_relatorio_admin(pedido, titulo))


def montar_relatorio_admin_sync(pedido: dict, total_semanal_cliente: str | None = None, titulo: str = "NOVO PEDIDO PAGO — TW STORE") -> str:
    if total_semanal_cliente is None:
        total_semanal_cliente = registrar_pedido_semanal(pedido)
    return montar_relatorio_admin_texto(pedido, total_semanal_cliente, titulo)


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
            total_semanal_cliente = registrar_pedido_semanal(pedido)
            enviado_documento = enviar_relatorio_admin_documento_sync(
                pedido,
                total_semanal_cliente,
                titulo="NOVO PEDIDO PAGO — TW STORE",
            )
            if not enviado_documento:
                relatorio = montar_relatorio_admin_sync(pedido, total_semanal_cliente, titulo="NOVO PEDIDO PAGO — TW STORE")
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


def decimal_plataforma(valor) -> Decimal | None:
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))

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
        return Decimal(texto)
    except (InvalidOperation, ValueError):
        return None


def decimal_para_moeda_br(valor: Decimal) -> str:
    valor = valor.quantize(Decimal("0.01"), rounding=ROUND_UP)
    texto = f"{valor:,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def obter_rate_servico_plataforma(servico: dict) -> Decimal | None:
    return decimal_plataforma(
        servico.get("rate")
        or servico.get("price")
        or servico.get("valor")
        or servico.get("custo")
    )


def markup_por_custo(valor_plataforma: Decimal) -> Decimal:
    """Retorna o multiplicador ideal de acordo com o custo real da plataforma."""
    if valor_plataforma <= Decimal("1.00"):
        return Decimal("3.00")

    if valor_plataforma <= Decimal("3.00"):
        return Decimal("1.78")

    if valor_plataforma <= Decimal("10.00"):
        return Decimal("1.41")

    if valor_plataforma <= Decimal("30.00"):
        return Decimal("1.30")

    return Decimal("1.40")


def markup_visualizacoes_por_custo(valor_plataforma: Decimal) -> Decimal:
    """Retorna o multiplicador específico para serviços de visualizações."""
    if valor_plataforma <= Decimal("1.00"):
        return Decimal("5.00")

    if valor_plataforma <= Decimal("3.00"):
        return Decimal("5.00")

    if valor_plataforma <= Decimal("10.00"):
        return Decimal("5.00")

    if valor_plataforma <= Decimal("30.00"):
        return Decimal("5.00")

    return Decimal("5.00")


def texto_identificacao_servico(servico_chave: str | None = None, servico: dict | None = None) -> str:
    textos = []

    if servico_chave:
        textos.append(str(servico_chave))

    if isinstance(servico, dict):
        for campo in ("name", "nome", "title", "titulo", "service"):
            valor = servico.get(campo)
            if valor:
                textos.append(str(valor))

    return " ".join(textos).lower()


def eh_servico_visualizacoes(servico_chave: str | None = None, servico: dict | None = None) -> bool:
    """Identifica visualizações pela chave do catálogo ou pelo nome retornado pela plataforma."""
    texto = texto_identificacao_servico(servico_chave=servico_chave, servico=servico)
    return any(palavra in texto for palavra in ("visualizacao", "visualizações", "visualizacoes", "views", "view"))


def eh_servico_curtidas(servico_chave: str | None = None, servico: dict | None = None) -> bool:
    """Identifica curtidas pela chave do catálogo ou pelo nome retornado pela plataforma."""
    texto = texto_identificacao_servico(servico_chave=servico_chave, servico=servico)
    return any(palavra in texto for palavra in ("curtida", "curtidas", "likes", "like"))


def preco_minimo_por_servico(servico_chave: str | None = None, servico: dict | None = None) -> Decimal:
    """Retorna o preço mínimo conforme o tipo de serviço."""
    if eh_servico_visualizacoes(servico_chave=servico_chave, servico=servico) or eh_servico_curtidas(servico_chave=servico_chave, servico=servico):
        return PRECO_MINIMO_CURTIDAS_VISUALIZACOES

    return PRECO_MINIMO_CLIENTE


def arredondar_preco_cliente(valor: Decimal) -> Decimal:
    """Arredonda o preço para números mais bonitos para o cliente final."""
    valor = valor.quantize(Decimal("0.01"), rounding=ROUND_UP)

    if valor < Decimal("10.00"):
        passo = Decimal("0.50")
    elif valor < Decimal("50.00"):
        passo = Decimal("1.00")
    else:
        passo = Decimal("5.00")

    return (valor / passo).to_integral_value(rounding=ROUND_UP) * passo


def calcular_valor_cliente_plataforma(
    rate: Decimal,
    quantidade: int,
    servico_chave: str | None = None,
    servico: dict | None = None,
) -> Decimal:
    custo_plataforma = (rate * Decimal(int(quantidade))) / Decimal("1000")
    custo_plataforma = custo_plataforma.quantize(Decimal("0.000001"), rounding=ROUND_UP)

    if eh_servico_visualizacoes(servico_chave=servico_chave, servico=servico):
        markup = markup_visualizacoes_por_custo(custo_plataforma)
    else:
        markup = markup_por_custo(custo_plataforma)

    valor_cliente = custo_plataforma * markup

    if valor_cliente > LIMITE_TAXA_OPERACIONAL_CLIENTE:
        valor_cliente += TAXA_OPERACIONAL_CLIENTE

    preco_minimo_cliente = preco_minimo_por_servico(servico_chave=servico_chave, servico=servico)
    if valor_cliente < preco_minimo_cliente:
        valor_cliente = preco_minimo_cliente

    return arredondar_preco_cliente(valor_cliente)


def detalhes_servico_plataforma_sync(catalogo: str, servico_chave: str, api_service_id: str | None = None) -> dict:
    pedido_base = {
        "catalogo": catalogo,
        "servico_chave": servico_chave,
        "api_service_id": api_service_id,
    }
    service_id = obter_service_id_api(pedido_base)
    servico = buscar_servico_plataforma_sync(service_id)
    if servico is None:
        raise PlataformaEstoqueIndisponivel(
            f"Service ID {service_id} não encontrado na lista de serviços da plataforma."
        )

    minimo = numero_decimal_plataforma(servico.get("min"))
    maximo = numero_decimal_plataforma(servico.get("max"))
    rate = obter_rate_servico_plataforma(servico)
    if rate is None or rate <= 0:
        raise PlataformaEstoqueIndisponivel(
            f"Service ID {service_id} não retornou preço/rate válido na plataforma."
        )

    minimo_cliente = QUANTIDADE_MINIMA_CLIENTE
    if minimo is not None:
        minimo_cliente = max(QUANTIDADE_MINIMA_CLIENTE, int(minimo))

    return {
        "service_id": service_id,
        "servico": servico,
        "minimo": int(minimo) if minimo is not None else None,
        "maximo": int(maximo) if maximo is not None else None,
        "minimo_cliente": minimo_cliente,
        "rate": rate,
    }


def calcular_pedido_dinamico_plataforma_sync(pedido: dict, quantidade: int) -> dict:
    quantidade = int(quantidade)
    detalhes = detalhes_servico_plataforma_sync(
        pedido.get("catalogo"),
        pedido.get("servico_chave"),
        pedido.get("api_service_id"),
    )

    minimo_cliente = int(detalhes.get("minimo_cliente") or QUANTIDADE_MINIMA_CLIENTE)
    maximo = detalhes.get("maximo")

    if quantidade < minimo_cliente:
        raise PlataformaEstoqueIndisponivel(
            f"Quantidade {formatar_inteiro_br(quantidade)} abaixo do mínimo permitido ({formatar_inteiro_br(minimo_cliente)})."
        )
    if maximo is not None and quantidade > int(maximo):
        raise PlataformaEstoqueIndisponivel(
            f"Quantidade {formatar_inteiro_br(quantidade)} acima do limite da plataforma ({formatar_inteiro_br(maximo)})."
        )

    valor_cliente = calcular_valor_cliente_plataforma(
        detalhes["rate"],
        quantidade,
        servico_chave=pedido.get("servico_chave"),
        servico=detalhes.get("servico"),
    )
    valor_plataforma = ((detalhes["rate"] * Decimal(quantidade)) / Decimal("1000")).quantize(Decimal("0.000001"), rounding=ROUND_UP)

    return {
        **detalhes,
        "quantidade": quantidade,
        "quantidade_texto": formatar_inteiro_br(quantidade),
        "valor_cliente": valor_cliente,
        "valor_cliente_texto": decimal_para_moeda_br(valor_cliente),
        "valor_plataforma": valor_plataforma,
    }


async def obter_detalhes_servico_plataforma(catalogo: str, servico_chave: str, servico: dict) -> dict | None:
    try:
        return await asyncio.to_thread(
            detalhes_servico_plataforma_sync,
            catalogo,
            servico_chave,
            servico.get("api_service_id"),
        )
    except (PlataformaAPIConfigError, PlataformaAPIRequestError, PlataformaEstoqueIndisponivel) as exc:
        logging.warning("Não foi possível consultar detalhes do serviço na plataforma: %s", limpar_erro_api(exc))
    except Exception as exc:
        logging.warning("Erro inesperado ao consultar detalhes do serviço na plataforma: %s", limpar_erro_api(exc))
    return None


def mensagem_escolher_quantidade(catalogo: str, servico: dict, detalhes: dict | None = None) -> str:
    minimo = QUANTIDADE_MINIMA_CLIENTE
    maximo = None
    if detalhes:
        minimo = int(detalhes.get("minimo_cliente") or minimo)
        maximo = detalhes.get("maximo")

    linhas = [
        str(servico.get("mensagem") or "").strip(),
        "",
        "🔢 *Escolha a quantidade*",
        f"Envie a quantidade desejada, começando com mínimo de {formatar_inteiro_br(minimo)}.",
    ]
    if maximo:
        linhas.append(f"Limite máximo da plataforma: {formatar_inteiro_br(maximo)}.")
    else:
        linhas.append("O limite máximo será validado automaticamente na plataforma.")
    linhas.extend([
        "",
        "Exemplo: `500`",
        "Depois disso eu peço o link/@ e gero o valor final automaticamente.",
    ])
    return "\n".join(linhas).strip()


async def iniciar_quantidade_dinamica(update: Update, context: ContextTypes.DEFAULT_TYPE, catalogo: str, servico_chave: str, voltar_callback: str):
    catalogo_id = "instagram" if catalogo == "Instagram" else "tiktok"
    servico = CATALOGO["catalogos"][catalogo_id]["servicos"][servico_chave]
    detalhes = await obter_detalhes_servico_plataforma(catalogo, servico_chave, servico)

    context.user_data["pedido"] = {
        "catalogo": catalogo,
        "servico_chave": servico_chave,
        "servico": servico["nome"],
        "api_service_id": servico.get("api_service_id"),
        "link": None,
        "status": "aguardando_quantidade",
        "usuario": update.effective_user.full_name,
        "username": update.effective_user.username,
        "user_id": update.effective_user.id,
    }

    await safe_edit_or_reply(
        update,
        mensagem_escolher_quantidade(catalogo, servico, detalhes),
        InlineKeyboardMarkup([[btn("⬅️ Voltar", voltar_callback)]]),
        parse_mode=ParseMode.MARKDOWN,
    )


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

    linhas = [f"Estoque: {info.get('maximo_texto', '')}"]
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
    padrao_estoque = re.compile(r"(?mi)^\s*Estoque\s*:\s*.*$")
    if padrao_estoque.search(mensagem):
        mensagem = padrao_estoque.sub(texto_estoque, mensagem, count=1)
    else:
        padrao_plataforma = re.compile(r"(?mi)^(\s*Plataforma\s*:\s*.*)$")
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
        return True, "Verificação antes do pagamento desativada."

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
                "Saldo insuficiente na plataforma antes de gerar o Pix. "
                f"Saldo: {saldo:.6f} {moeda}; necessário estimado: {necessario:.6f} {moeda}; "
                f"service_id: {service_id}; quantidade: {quantidade}."
            )
            return False, detalhe

        detalhe = (
            "Saldo confirmado antes do pagamento. "
            f"Saldo: {saldo:.6f} {moeda}; custo estimado: {float(custo):.6f} {moeda}; "
            f"service_id: {service_id}; quantidade: {quantidade}."
        )
        return True, detalhe

    if saldo <= float(MARGEM_SALDO_PLATAFORMA):
        detalhe = (
            "Saldo zerado/insuficiente na plataforma antes de gerar o Pix. "
            f"Saldo: {saldo:.6f} {moeda}; service_id: {service_id}; quantidade: {quantidade}."
        )
        return False, detalhe

    detalhe = (
        "Saldo positivo confirmado antes do pagamento, mas não foi possível estimar o custo do serviço. "
        f"Saldo: {saldo:.6f} {moeda}; service_id: {service_id}; quantidade: {quantidade}."
    )
    return True, detalhe


def mensagem_cliente_sem_reposicao() -> str:
    return (
        "⚠️ *Serviço temporariamente sem reposição de estoque.*\n\n"
        "No momento não consigo liberar esse pedido automaticamente. "
        "Tente novamente mais tarde ou fale com o atendimento.\n\n"
        "✅ Nenhum Pix foi gerado e você não precisa pagar nada agora."
    )


def texto_admin_bloqueio_sem_reposicao(pedido: dict, detalhe: str) -> str:
    username = username_relatorio(pedido)
    return (
        "🚫 *PEDIDO BLOQUEADO ANTES DO PAGAMENTO*\n\n"
        "O cliente tentou iniciar um pedido, mas o bot não gerou Pix porque detectou falta de saldo/reposição na plataforma.\n\n"
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


def menu_itens_tiktok(servico_chave: str) -> InlineKeyboardMarkup:
    servico = CATALOGO["catalogos"]["tiktok"]["servicos"][servico_chave]
    keyboard = []
    for item in servico["itens"]:
        texto = f'{item["quantidade_texto"]} {servico["nome"]} — {money(item["valor"])}'
        keyboard.append([btn(texto, f'item_tiktok:{servico_chave}:{item["quantidade"]}')])
    keyboard.append([btn("⬅️ Voltar", "catalogo:tiktok")])
    return InlineKeyboardMarkup(keyboard)


def get_item_tiktok(servico_chave: str, quantidade: int) -> dict:
    servico = CATALOGO["catalogos"]["tiktok"]["servicos"][servico_chave]
    for item in servico["itens"]:
        if int(item["quantidade"]) == int(quantidade):
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
    servico = CATALOGO["catalogos"]["instagram"]["servicos"][servico_chave]
    keyboard = []
    for item in servico["itens"]:
        texto = f'{item["quantidade_texto"]} {servico["nome"]} — {money(item["valor"])}'
        keyboard.append([btn(texto, f'item:{servico_chave}:{item["quantidade"]}')])
    keyboard.append([btn("⬅️ Voltar", "catalogo:instagram")])
    return InlineKeyboardMarkup(keyboard)


def get_item(servico_chave: str, quantidade: int) -> dict:
    servico = CATALOGO["catalogos"]["instagram"]["servicos"][servico_chave]
    for item in servico["itens"]:
        if int(item["quantidade"]) == int(quantidade):
            return item
    raise KeyError("Item não encontrado")



def texto_pagamento(pedido: dict) -> str:
    # Monta a aba de pagamento usando Pix dinâmico do Mercado Pago quando disponível.
    resumo_pagamento = (
        "💳  PAGAMENTO DO PEDIDO\n\n"
        "✅ Seu pedido já foi separado com sucesso.\n"
        "Agora finalize o pagamento pelo Pix abaixo.\n\n"
        "📋 RESUMO DO PEDIDO\n\n"
        f"• Catálogo: {pedido.get('catalogo', '')}\n"
        f"• Serviço: {pedido.get('servico', '')}\n"
        f"• Quantidade: {pedido.get('quantidade', '')}\n"
        + linha_solicitacoes_possiveis_pagamento(pedido)
        + f"• Link/@ enviado: {pedido.get('link', '')}\n"
        f"• Valor exato: R$ {pedido.get('valor', '')}\n\n"
        "⌛️ Após o pagamento, aguarde alguns segundos.\n"
        "A confirmação é feita automaticamente pelo Mercado Pago, Caso necessário clique Verificar Pagamento."
    )

    if pedido.get("mp_qr_code"):
        return resumo_pagamento

    resumo_pagamento_manual = (
        "💳  PAGAMENTO DO PEDIDO\n\n"
        "✅ Seu pedido já foi separado com sucesso.\n"
        "Agora finalize o pagamento pelo Pix abaixo.\n\n"
        "📋 RESUMO DO PEDIDO\n\n"
        f"• Catálogo: {pedido.get('catalogo', '')}\n"
        f"• Serviço: {pedido.get('servico', '')}\n"
        f"• Quantidade: {pedido.get('quantidade', '')}\n"
        + linha_solicitacoes_possiveis_pagamento(pedido)
        + f"• Link/@ enviado: {pedido.get('link', '')}\n"
        f"• Valor exato: R$ {pedido.get('valor', '')}\n\n"
        "⌛️ Após o pagamento, envie o comprovante aqui na conversa.\n"
        "O pedido será encaminhado para validação e liberado após a aprovação do pagamento."
    )
    return resumo_pagamento_manual

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


async def enviar_pagamento_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict):
    """Troca a aba atual pela aba de pagamento, sem empilhar outra mensagem do bot."""
    if not await verificar_reposicao_antes_pagamento(update, context, pedido):
        return

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

        await enviar_texto_sequencial(update, context, texto_pagamento(pedido), botoes_pagamento(pedido), parse_mode=None)
        return

    imagem = None
    if pedido.get("catalogo") == "Instagram":
        imagem = gerar_imagem_pagamento_instagram(pedido)
    elif pedido.get("catalogo") == "TikTok":
        imagem = gerar_imagem_pagamento_tiktok(pedido)

    if imagem is not None:
        await enviar_foto_sequencial(update, context, imagem, botoes_pagamento(pedido))
        return

    await enviar_texto_sequencial(update, context, texto_pagamento(pedido), botoes_pagamento(pedido), parse_mode=None)


def botoes_pagamento(pedido: dict | None = None) -> InlineKeyboardMarkup:
    pix_copia = (pedido or {}).get("mp_qr_code") or PIX_COPIA_COLA or PIX_CHAVE or "PIX_NAO_CONFIGURADO"
    texto_botao = "📋 Copiar Pix" if (pedido or {}).get("mp_qr_code") else "📋 Copiar chave Pix"
    keyboard = [
        [InlineKeyboardButton(texto_botao, copy_text=CopyTextButton(pix_copia))],
    ]
    if (pedido or {}).get("mp_payment_id"):
        keyboard.append([btn("✅ Verificar Pagamento", "verificar_pagamento")])
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if not registro_aprovado(update):
        mensagem = await update.message.reply_text(
            texto_acesso_bloqueado(update),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_registro(update),
            disable_web_page_preview=True,
        )
        guardar_mensagem_bot(context, mensagem)
        return

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

    if await bloquear_se_sem_acesso(update, context):
        await query.answer("Faça o cadastro e aguarde a aprovação para usar o bot.", show_alert=True)
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
        await safe_edit_or_reply(update, CATALOGO["catalogos"]["instagram"]["mensagem"], menu_instagram())
        return

    if data == "catalogo:tiktok":
        await safe_edit_or_reply(update, CATALOGO["catalogos"]["tiktok"]["mensagem"], menu_tiktok())
        return

    if data.startswith("servico_tiktok:"):
        servico_chave = data.split(":", 1)[1]
        await iniciar_quantidade_dinamica(update, context, "TikTok", servico_chave, "catalogo:tiktok")
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
        await iniciar_quantidade_dinamica(update, context, "Instagram", servico_chave, "catalogo:instagram")
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
        pedido["link"] = None
        if pedido.get("catalogo") in ("IPTV Livestream 4K", "Internet Ilimitada"):
            pedido["status"] = "aguardando_email_iptv"
            await enviar_texto_sequencial(update, context, "✏️ Envie novamente o e-mail correto para continuar.")
        else:
            pedido["status"] = "aguardando_link"
            await enviar_texto_sequencial(update, context, "✏️ Envie novamente o link ou @ correto do cliente para continuar.")
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

    if await processar_texto_admin_painel(update, context, texto_usuario):
        return

    if await processar_texto_registro(update, context, texto_usuario):
        return

    if await bloquear_se_sem_acesso(update, context):
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


    if pedido.get("status") == "aguardando_quantidade" and pedido.get("catalogo") in CATALOGOS_COM_ENVIO_API:
        try:
            quantidade = quantidade_para_api(texto_usuario)
        except Exception:
            await update.message.reply_text(
                "❌ Envie apenas a quantidade desejada. Exemplo: `500`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if quantidade <= 0:
            await update.message.reply_text(
                "❌ Quantidade inválida. Envie um número a partir de `100`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        try:
            calculo = await asyncio.to_thread(calcular_pedido_dinamico_plataforma_sync, pedido, quantidade)
        except (PlataformaAPIConfigError, PlataformaAPIRequestError, PlataformaEstoqueIndisponivel) as exc:
            await update.message.reply_text(
                "❌ Não consegui validar essa quantidade na plataforma.\n\n"
                f"Detalhe: {limpar_erro_api(exc)}\n\n"
                "Envie outra quantidade ou tente novamente em alguns instantes.",
                disable_web_page_preview=True,
            )
            return
        except Exception as exc:
            logging.exception("Erro ao calcular pedido dinâmico")
            await update.message.reply_text(
                "❌ Ocorreu um erro ao calcular o valor desse pedido. Tente novamente em alguns instantes.\n\n"
                f"Detalhe: {limpar_erro_api(exc)}",
                disable_web_page_preview=True,
            )
            return

        pedido.update({
            "quantidade": calculo["quantidade_texto"],
            "quantidade_api": calculo["quantidade"],
            "valor": calculo["valor_cliente_texto"],
            "valor_plataforma": str(calculo.get("valor_plataforma")),
            "api_service_id": calculo.get("service_id") or pedido.get("api_service_id"),
            "plataforma_service_id": calculo.get("service_id"),
            "plataforma_estoque_max": calculo.get("maximo"),
            "plataforma_estoque_max_texto": formatar_inteiro_br(calculo.get("maximo")) if calculo.get("maximo") else "",
            "status": "aguardando_link",
        })

        alvo = "perfil" if str(pedido.get("servico_chave")) == "seguidores" else "publicação"
        await update.message.reply_text(
            (
                "✅ *Quantidade escolhida com sucesso!*\n\n"
                f"📦 *Serviço:* {md(pedido.get('servico', ''))}\n"
                f"🔢 *Quantidade:* {md(pedido.get('quantidade', ''))}\n"
                f"💰 *Valor final:* R$ {md(pedido.get('valor', ''))}\n\n"
                f"Agora envie o link ou @ correto do {alvo} para continuar o pedido."
            ),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
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
                    f"{md(pedido['link'])}\n\n"
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
        "✅ Já recebi o link/@ do cliente. Agora finalize pela aba de pagamento abaixo.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=botoes_pagamento(pedido),
    )


async def receber_comprovante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await bloquear_se_sem_acesso(update, context):
        return

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
    if not ADMIN_CHAT_ID:
        await update.effective_message.reply_text(CATALOGO["mensagens"].get("erro_admin", "ADMIN_CHAT_ID não configurado."))
        return

    await fechar_semana_se_necessario(context.bot)
    total_semanal_cliente = registrar_pedido_semanal(pedido)
    titulo = "NOVO PEDIDO APROVADO — TW STORE"

    imagem = gerar_imagem_relatorio_admin(pedido, total_semanal_cliente, titulo="RELATÓRIO DE VENDA APROVADA")
    if imagem is not None:
        try:
            await context.bot.send_document(
                chat_id=ADMIN_CHAT_ID,
                document=imagem,
                caption=caption_relatorio_admin(pedido, titulo),
                parse_mode=ParseMode.MARKDOWN,
            )

            comprovante_file_id = pedido.get("comprovante_file_id")
            if comprovante_file_id:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID,
                    photo=comprovante_file_id,
                    caption=f"📎 Comprovante do pedido `{md(pedido.get('pedido_id', ''))}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            return
        except Exception as exc:
            logging.warning("Falha ao enviar relatório pós-compra como documento: %s", exc)

    relatorio = montar_relatorio_admin_sync(pedido, total_semanal_cliente, titulo=titulo)
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
    persistence = PicklePersistence(filepath=str(BOT_PERSISTENCE_PATH))
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).post_init(iniciar_rotina_fechamento).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("painel", painel_admin))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.IMAGE), receber_comprovante))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber_texto))
    print("Bot TW STORE iniciado.")
    print(f"Arquivos de dados em: {DATA_DIR}")
    print(f"Cadastros salvos em: {USUARIOS_REGISTRADOS_PATH}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
