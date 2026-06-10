import json
import os
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
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
CATALOGO_PATH = BASE_DIR / "catalogo.json"

with open(CATALOGO_PATH, "r", encoding="utf-8") as f:
    CATALOGO = json.load(f)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
PIX_CHAVE = os.getenv("PIX_CHAVE", "ttwovendas@gmail.com").strip()


def md(texto) -> str:
    return escape_markdown(str(texto), version=1)


def money(valor: str) -> str:
    return f"R$ {valor}"


def btn(texto: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(texto, callback_data=data)


def menu_principal() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("🎯 Catálogo de Serviços", "menu:catalogo")],
        [btn("❓ Dúvidas Frequentes", "extra:duvidas")],
        [btn("💬 Falar com Atendimento", "extra:atendimento")],
        [btn("📦 Como Fazer Pedido", "extra:como_fazer_pedido")],
            ]
    return InlineKeyboardMarkup(keyboard)


def menu_catalogos() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("📱 Instagram", "catalogo:instagram")],
        [btn("🎵 TikTok", "catalogo:tiktok")],
        [btn("📺 IPTV Livestream 4K", "catalogo:iptv")],
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
    """Monta a aba de pagamento sempre usando o valor correto vindo do catalogo.json."""
    return (
        "💳 *Pagamento e Finalização*\n\n"
        "Estou analisando as informações enviadas. Enquanto isso, seguem os dados de pagamento:\n\n"
        "*Dados do Pix:*\n"
        f"( 🔑 ) `{md(PIX_CHAVE)}`\n\n"
        f"*Valor:* R$ {md(pedido['valor'])}\n\n"
        "🧾 *Resumo do pedido*\n"
        f"• Catálogo: {md(pedido['catalogo'])}\n"
        f"• Serviço: {md(pedido['servico'])}\n"
        f"• Quantidade: {md(pedido['quantidade'])}\n"
        f"• Link/@ enviado: {md(pedido['link'])}\n\n"
        "Após realizar o pagamento, envie o comprovante em imagem aqui na conversa.\n"
        "O botão de confirmação só aparecerá depois que o comprovante for enviado."
    )


def botoes_pagamento() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [btn("✏️ Alterar link/@", "alterar_link")],
            [btn("🏠 Cancelar / Menu", "voltar:inicio")],
        ]
    )


def botoes_confirmar_pagamento() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [btn("✅ Confirmar pagamento e enviar pedido", "confirmar_pedido")],
            [btn("✏️ Alterar link/@", "alterar_link")],
            [btn("🏠 Cancelar / Menu", "voltar:inicio")],
        ]
    )


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
            await query.message.reply_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
    else:
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        CATALOGO["mensagens"]["inicio"],
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_principal(),
        disable_web_page_preview=True,
    )


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "voltar:inicio":
        context.user_data.clear()
        await safe_edit_or_reply(update, CATALOGO["mensagens"]["inicio"], menu_principal())
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
        servico = CATALOGO["catalogos"]["tiktok"]["servicos"][servico_chave]
        await safe_edit_or_reply(update, servico["mensagem"], menu_itens_tiktok(servico_chave))
        return

    if data.startswith("item_tiktok:"):
        _, servico_chave, quantidade_str = data.split(":")
        quantidade = int(quantidade_str)
        item = get_item_tiktok(servico_chave, quantidade)
        servico = CATALOGO["catalogos"]["tiktok"]["servicos"][servico_chave]

        context.user_data["pedido"] = {
            "catalogo": "TikTok",
            "servico_chave": servico_chave,
            "servico": servico["nome"],
            "quantidade": item["quantidade_texto"],
            "valor": item["valor"],
            "link": None,
            "status": "aguardando_link",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        }

        await safe_edit_or_reply(
            update,
            item["mensagem"],
            InlineKeyboardMarkup([[btn("⬅️ Voltar", f"servico_tiktok:{servico_chave}")]]),
        )
        return

    if data == "catalogo:iptv":
        await safe_edit_or_reply(
            update,
            CATALOGO["catalogos"]["iptv"]["mensagem"],
            InlineKeyboardMarkup([[btn("📞 Falar com atendimento", "extra:atendimento")], [btn("⬅️ Voltar", "menu:catalogo")]]),
        )
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

        context.user_data["pedido"] = {
            "catalogo": "Instagram",
            "servico_chave": servico_chave,
            "servico": servico["nome"],
            "quantidade": item["quantidade_texto"],
            "valor": item["valor"],
            "link": None,
            "status": "aguardando_link",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        }

        await safe_edit_or_reply(
            update,
            item["mensagem"],
            InlineKeyboardMarkup([[btn("⬅️ Voltar", f"servico:{servico_chave}")]]),
        )
        return

    if data == "alterar_link":
        pedido = context.user_data.get("pedido")
        if not pedido:
            await safe_edit_or_reply(update, "Não encontrei um pedido em andamento. Toque em /start para começar novamente.")
            return
        pedido["link"] = None
        pedido["status"] = "aguardando_link"
        await safe_edit_or_reply(update, "✏️ Envie novamente o link ou @ correto para continuar.")
        return

    if data == "confirmar_pedido":
        pedido = context.user_data.get("pedido")
        if not pedido or not pedido.get("link"):
            await safe_edit_or_reply(update, "Não encontrei um pedido completo. Toque em /start para começar novamente.")
            return
        if not pedido.get("comprovante_file_id"):
            await safe_edit_or_reply(update, "Envie primeiro uma imagem do comprovante para liberar a confirmação.")
            return
        await enviar_relatorio_admin(update, context, pedido)
        await safe_edit_or_reply(
            update,
            CATALOGO["mensagens"].get("pedido_confirmado") or "✅ Pedido confirmado!",
            InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
        )
        context.user_data.clear()
        return


async def receber_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pedido = context.user_data.get("pedido")

    if not pedido:
        await update.message.reply_text(
            "Para iniciar um pedido, toque em /start e escolha uma opção do catálogo.",
            reply_markup=menu_principal(),
        )
        return

    texto_usuario = (update.message.text or "").strip()

    if pedido.get("status") == "aguardando_pagamento" and texto_usuario == "1":
        if not pedido.get("comprovante_file_id"):
            await update.message.reply_text(
                "Envie primeiro uma imagem do comprovante para liberar a confirmação.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=botoes_pagamento(),
            )
            return
        await enviar_relatorio_admin(update, context, pedido)
        await update.message.reply_text(
            CATALOGO["mensagens"].get("pedido_confirmado") or "✅ Pedido confirmado!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
        )
        context.user_data.clear()
        return

    if not pedido.get("link"):
        pedido["link"] = texto_usuario
        pedido["status"] = "aguardando_pagamento"
        await update.message.reply_text(
            texto_pagamento(pedido),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=botoes_pagamento(),
            disable_web_page_preview=True,
        )
        return

    await update.message.reply_text(
        "Já recebi o link/@. Agora finalize pela aba de pagamento abaixo.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=botoes_pagamento(),
    )


async def receber_comprovante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pedido = context.user_data.get("pedido")

    if not pedido:
        await update.message.reply_text(
            "Para iniciar um pedido, toque em /start e escolha uma opção do catálogo.",
            reply_markup=menu_principal(),
        )
        return

    if pedido.get("status") != "aguardando_pagamento" or not pedido.get("link"):
        await update.message.reply_text("Recebi a imagem, mas ainda preciso do link/@ do pedido primeiro.")
        return

    if update.message.photo:
        pedido["comprovante_file_id"] = update.message.photo[-1].file_id
    elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
        pedido["comprovante_file_id"] = update.message.document.file_id
    else:
        await update.message.reply_text("Envie o comprovante como imagem para eu anexar ao relatório.")
        return

    await update.message.reply_text(
        "✅ Comprovante recebido! Agora toque no botão abaixo para confirmar e enviar seu pedido.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=botoes_confirmar_pagamento(),
    )


async def enviar_relatorio_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict):
    if not ADMIN_CHAT_ID:
        await update.effective_message.reply_text(CATALOGO["mensagens"].get("erro_admin", "ADMIN_CHAT_ID não configurado."))
        return

    username = f'@{pedido["username"]}' if pedido.get("username") else "Sem username"
    relatorio = (
        "📥 *NOVO PEDIDO RECEBIDO — TW STORE*\n\n"
        f"🗂️ *Catálogo:* {md(pedido['catalogo'])}\n"
        f"📌 *Serviço:* {md(pedido['servico'])}\n"
        f"🔢 *Quantidade:* {md(pedido['quantidade'])}\n"
        f"💰 *Valor:* R$ {md(pedido['valor'])}\n"
        f"🔗 *Link/@:* {md(pedido['link'])}\n\n"
        f"👤 *Cliente:* {md(pedido['usuario'])}\n"
        f"📱 *Telegram:* {md(username)}\n"
        f"🆔 *ID:* `{pedido['user_id']}`\n"
        f"🕒 *Data:* {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    comprovante_file_id = pedido.get("comprovante_file_id")

    if comprovante_file_id:
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=comprovante_file_id,
            caption=relatorio,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=relatorio,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Configure a variável BOT_TOKEN com o token do BotFather.")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.IMAGE), receber_comprovante))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber_texto))
    print("Bot TW STORE iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
