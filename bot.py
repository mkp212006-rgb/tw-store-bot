import json
import os
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
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


def money(valor: str) -> str:
    return f"R$ {valor}"


def btn(texto: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(texto, callback_data=data)


def menu_principal() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("1️⃣ Catálogo de Serviços", "menu:catalogo")],
        [btn("2️⃣ Dúvidas Frequentes", "extra:duvidas")],
        [btn("3️⃣ Falar com Atendimento", "extra:atendimento")],
        [btn("4️⃣ Como Fazer Pedido", "extra:como_fazer_pedido")],
        [btn("⏰ Prazos e Suporte", "extra:prazos_suporte")],
    ]
    return InlineKeyboardMarkup(keyboard)


def menu_catalogos() -> InlineKeyboardMarkup:
    keyboard = [
        [btn("📱 Instagram", "catalogo:instagram")],
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
            keyboard.insert(0, [btn("💳 Pagamento", "extra_pagamento")])
        await safe_edit_or_reply(update, texto, InlineKeyboardMarkup(keyboard))
        return

    if data == "extra_pagamento":
        await safe_edit_or_reply(
            update,
            CATALOGO["mensagens"]["pagamento"],
            InlineKeyboardMarkup([[btn("✅ Pedido Confirmado", "extra_confirmado")], [btn("⬅️ Voltar", "extra:atendimento")]]),
        )
        return

    if data == "extra_confirmado":
        await safe_edit_or_reply(
            update,
            CATALOGO["mensagens"]["pedido_confirmado"],
            InlineKeyboardMarkup([[btn("🏠 Menu inicial", "voltar:inicio")]]),
        )
        return

    if data == "catalogo:instagram":
        await safe_edit_or_reply(update, CATALOGO["catalogos"]["instagram"]["mensagem"], menu_instagram())
        return

    if data == "catalogo:iptv":
        await safe_edit_or_reply(
            update,
            CATALOGO["catalogos"]["iptv"]["mensagem"],
            InlineKeyboardMarkup([[btn("⬅️ Voltar", "menu:catalogo")]]),
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

    if data == "confirmar_pedido":
        pedido = context.user_data.get("pedido")
        if not pedido:
            await safe_edit_or_reply(update, "Não encontrei um pedido em andamento. Toque em /start para começar novamente.")
            return
        await enviar_relatorio_admin(update, context, pedido)
        await safe_edit_or_reply(
            update,
            CATALOGO["mensagens"]["pedido_confirmado"],
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

    if not pedido.get("link"):
    pedido["link"] = update.message.text.strip()

    await update.message.reply_text(
        "✅ Link recebido!\n\nAgora toque no botão abaixo para finalizar seu pedido.",
        reply_markup=InlineKeyboardMarkup([
            [btn("✅ Confirmar pedido", "confirmar_pedido")]
        ]),
        disable_web_page_preview=True,
    )
        return

    await update.message.reply_text(
        "Já recebi o link/@. Agora toque em *Confirmar pedido* para finalizar.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[btn("✅ Confirmar pedido", "confirmar_pedido")]]),
    )


async def enviar_relatorio_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict):
    if not ADMIN_CHAT_ID:
        await update.effective_message.reply_text(CATALOGO["mensagens"]["erro_admin"])
        return

    username = f'@{pedido["username"]}' if pedido.get("username") else "Sem username"
    relatorio = (
        "📥 *NOVO PEDIDO RECEBIDO — TW STORE*\n\n"
        f'🗂️ *Catálogo:* {pedido["catalogo"]}\n'
        f'📌 *Serviço:* {pedido["servico"]}\n'
        f'🔢 *Quantidade:* {pedido["quantidade"]}\n'
        f'💰 *Valor:* R$ {pedido["valor"]}\n'
        f'🔗 *Link/@:* {pedido["link"]}\n\n'
        f'👤 *Cliente:* {pedido["usuario"]}\n'
        f'📱 *Telegram:* {username}\n'
        f'🆔 *ID:* `{pedido["user_id"]}`\n'
        f'🕒 *Data:* {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}'
    )
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber_texto))
    print("Bot TW STORE iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
