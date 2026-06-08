import json
import os
from pathlib import Path
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

BASE_DIR = Path(__file__).resolve().parent
DATA = json.loads((BASE_DIR / "catalogos.json").read_text(encoding="utf-8"))
ITEMS = DATA["items"]
ROOT_ID = DATA["root_id"]
BY_ID = {item["id"]: item for item in ITEMS}
BY_KEY = {item["key"]: item for item in ITEMS}
CHILDREN = {item["id"]: [] for item in ITEMS}
for item in ITEMS:
    parent = item.get("parentId")
    if parent and parent in CHILDREN and parent != item["id"]:
        CHILDREN[parent].append(item)
for value in CHILDREN.values():
    value.sort(key=lambda item: int(item["key"]))

FOOTER = "\n\nDigite /start para voltar ao menu principal."

def keyboard_for(item_id: str) -> InlineKeyboardMarkup | None:
    buttons = []
    for child in CHILDREN.get(item_id, []):
        title = child["title"].replace("\n", " ").strip()
        if not title:
            title = "Abrir"
        buttons.append([InlineKeyboardButton(title[:64], callback_data=f"open:{child['key']}")])
    item = BY_ID.get(item_id)
    if item and item_id != ROOT_ID:
        parent_id = item.get("parentId")
        if parent_id and parent_id in BY_ID:
            buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"open:{BY_ID[parent_id]['key']}"), InlineKeyboardButton("🏠 Menu", callback_data=f"open:{BY_ID[ROOT_ID]['key']}")])
    return InlineKeyboardMarkup(buttons) if buttons else None

async def send_item(update: Update, context: ContextTypes.DEFAULT_TYPE, item) -> None:
    text = item.get("message", "").strip() or item.get("title", "")
    markup = keyboard_for(item["id"])
    # O Telegram limita mensagens a 4096 caracteres.
    if len(text) > 3900:
        text = text[:3900] + "\n\n..."
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text=text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_item(update, context, BY_ID[ROOT_ID])

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith("open:"):
        key = data.split(":", 1)[1]
        item = BY_KEY.get(key, BY_ID[ROOT_ID])
        await send_item(update, context, item)

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (update.message.text or "").strip()
    if msg == "#":
        await start(update, context)
        return
    # Se o cliente enviar link/comprovante, mantém um retorno organizado.
    await update.message.reply_text(
        "✅ Informação recebida.\n\nUse os botões do menu para continuar ou digite /start para voltar ao início."
    )

def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Coloque o token do bot na variável TELEGRAM_BOT_TOKEN.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    print("Bot TW STORE rodando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
