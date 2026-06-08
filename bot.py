
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

load_dotenv()
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

CATALOG = json.loads(Path("catalog.json").read_text(encoding="utf-8"))
ORDERS_FILE = Path("orders.jsonl")

WAITING_INFO = "waiting_info"

def fmt_money(value: str) -> str:
    return f"R$ {value}"

def main_keyboard():
    rows = [[InlineKeyboardButton("📦 Catálogo de Serviços", callback_data="menu:catalog")],
            [InlineKeyboardButton("❓ Dúvidas Frequentes", callback_data="menu:faq")],
            [InlineKeyboardButton("👤 Falar com Atendimento", callback_data="menu:support")]]
    return InlineKeyboardMarkup(rows)

def categories_keyboard():
    rows = []
    for c in CATALOG["categories"]:
        rows.append([InlineKeyboardButton(c["name"], callback_data=f"cat:{c['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu:start")])
    return InlineKeyboardMarkup(rows)

def items_keyboard(cat_id: str):
    cat = get_category(cat_id)
    rows = []
    for item in cat["items"]:
        rows.append([InlineKeyboardButton(f"{item['label']} — {fmt_money(item['price'])}", callback_data=f"item:{cat_id}:{item['quantity']}")])
    rows.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu:catalog")])
    return InlineKeyboardMarkup(rows)

def get_category(cat_id: str):
    return next(c for c in CATALOG["categories"] if c["id"] == cat_id)

def get_item(cat_id: str, quantity: int):
    cat = get_category(cat_id)
    return next(i for i in cat["items"] if int(i["quantity"]) == int(quantity))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"👋 *Bem-vindo(a) à {CATALOG['store_name']}!*\n\n"
        "Sou o assistente virtual da loja. Aqui você encontra serviços digitais com atendimento organizado, entrega rápida e suporte dedicado.\n\n"
        "Escolha uma opção abaixo para continuar."
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu:start":
        await start(update, context)
        return
    if data == "menu:catalog":
        await query.edit_message_text("📦 *Catálogo TW STORE*\n\nSelecione a categoria desejada:", parse_mode="Markdown", reply_markup=categories_keyboard())
        return
    if data == "menu:faq":
        faq = "❓ *Dúvidas Frequentes*\n\n" + "\n\n".join([f"*{x['q']}*\n{x['a']}" for x in CATALOG["faq"]])
        await query.edit_message_text(faq, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="menu:start")]]))
        return
    if data == "menu:support":
        await query.edit_message_text(
            "👤 *Atendimento TW STORE*\n\nEnvie sua dúvida aqui no chat com:\n• Serviço desejado\n• Quantidade\n• Link ou @\n\nUm resumo será enviado para o atendimento.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="menu:start")]])
        )
        context.user_data[WAITING_INFO] = {"type":"support"}
        return
    if data.startswith("cat:"):
        cat_id = data.split(":",1)[1]
        cat = get_category(cat_id)
        await query.edit_message_text(f"*{cat['name']}*\n\n{cat['description']}\n\nSelecione a quantidade:", parse_mode="Markdown", reply_markup=items_keyboard(cat_id))
        return
    if data.startswith("item:"):
        _, cat_id, qty = data.split(":")
        cat = get_category(cat_id)
        item = get_item(cat_id, int(qty))
        context.user_data[WAITING_INFO] = {"type":"order", "cat_id":cat_id, "quantity":int(qty)}
        await query.edit_message_text(
            f"✅ Você selecionou:\n\n*{item['label']}*\n*Valor:* {fmt_money(item['price'])}\n\n{cat['ask']}\n\nDepois disso, o resumo do pedido será enviado para o atendimento.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancelar", callback_data=f"cat:{cat_id}")]])
        )
        return

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    waiting = context.user_data.get(WAITING_INFO)
    user = update.effective_user
    msg = update.message.text.strip()

    if not waiting:
        await update.message.reply_text("Para começar, use /start e escolha uma opção do menu.")
        return

    if waiting.get("type") == "support":
        summary = (
            "📩 *Nova mensagem de atendimento*\n"
            f"Cliente: {user.full_name} (@{user.username or 'sem usuário'})\n"
            f"Telegram ID: {user.id}\n\n"
            f"Mensagem:\n{msg}"
        )
        save_order({"type":"support","user_id":user.id,"username":user.username,"name":user.full_name,"message":msg})
        await notify_owner(context, summary)
        await update.message.reply_text("✅ Sua mensagem foi enviada para o atendimento. Aguarde o retorno.", reply_markup=main_keyboard())
        context.user_data.pop(WAITING_INFO, None)
        return

    cat = get_category(waiting["cat_id"])
    item = get_item(waiting["cat_id"], waiting["quantity"])
    order = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "type":"order",
        "user_id":user.id,
        "username":user.username,
        "name":user.full_name,
        "category":cat["name"],
        "item":item["label"],
        "price":item["price"],
        "customer_info":msg,
    }
    save_order(order)
    summary = (
        "🛒 *Novo pedido no bot Telegram*\n"
        f"Cliente: {user.full_name} (@{user.username or 'sem usuário'})\n"
        f"Telegram ID: {user.id}\n\n"
        f"Categoria: {cat['name']}\n"
        f"Pacote: {item['label']}\n"
        f"Valor: R$ {item['price']}\n\n"
        f"Link/@ enviado:\n{msg}"
    )
    await notify_owner(context, summary)
    await update.message.reply_text(
        f"✅ Pedido recebido!\n\n*{item['label']}*\nValor: *R$ {item['price']}*\n\nAguarde a conferência do atendimento.",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    context.user_data.pop(WAITING_INFO, None)

def save_order(order):
    with ORDERS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(order, ensure_ascii=False) + "\n")

async def notify_owner(context: ContextTypes.DEFAULT_TYPE, summary: str):
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if admin_id:
        try:
            await context.bot.send_message(chat_id=int(admin_id), text=summary, parse_mode="Markdown")
        except Exception as e:
            print("Erro ao notificar Telegram admin:", e)
    send_whatsapp(summary)

def send_whatsapp(text: str):
    provider = os.getenv("WHATSAPP_PROVIDER", "").lower().strip()
    to = os.getenv("OWNER_WHATSAPP", CATALOG.get("owner_whatsapp", "5512997793285"))

    if provider == "callmebot":
        api_key = os.getenv("CALLMEBOT_APIKEY")
        if not api_key:
            print("CALLMEBOT_APIKEY não configurada.")
            return
        url = f"https://api.callmebot.com/whatsapp.php?phone={to}&text={quote_plus(text)}&apikey={api_key}"
        try:
            requests.get(url, timeout=15)
        except Exception as e:
            print("Erro CallMeBot:", e)
        return

    if provider == "cloud":
        token = os.getenv("WHATSAPP_CLOUD_TOKEN")
        phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        if not token or not phone_number_id:
            print("WHATSAPP_CLOUD_TOKEN/WHATSAPP_PHONE_NUMBER_ID não configurados.")
            return
        url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
        payload = {"messaging_product":"whatsapp","to":to,"type":"text","text":{"body":text.replace("*","")}}
        headers = {"Authorization": f"Bearer {token}", "Content-Type":"application/json"}
        try:
            requests.post(url, headers=headers, json=payload, timeout=15)
        except Exception as e:
            print("Erro WhatsApp Cloud:", e)
        return

    print("WhatsApp não enviado: configure WHATSAPP_PROVIDER=callmebot ou WHATSAPP_PROVIDER=cloud.")

def run():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Configure TELEGRAM_BOT_TOKEN no arquivo .env ou nas variáveis de ambiente.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("Bot TW STORE rodando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    run()
