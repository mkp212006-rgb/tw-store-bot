import json
import logging
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BOT_TOKEN = os.getenv("BOT_TOKEN", "COLOQUE_SEU_TOKEN_AQUI")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "COLOQUE_SEU_CHAT_ID_AQUI")
CATALOGO_PATH = os.getenv("CATALOGO_PATH", "catalogo.json")

with open(CATALOGO_PATH, "r", encoding="utf-8") as f:
    CATALOGO = json.load(f)

USER_STATE = {}


def kb(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in rows])


def main_menu():
    return kb([
        [("1️⃣ Catálogo de Serviços", "menu_catalogo")],
        [("2️⃣ Dúvidas Frequentes", "menu_duvidas")],
        [("3️⃣ Falar com Atendimento", "menu_atendimento")],
        [("4️⃣ Como Fazer Pedido", "menu_como_pedir")],
        [("⏰ Prazos e Suporte", "menu_prazos")],
    ])


def catalog_menu():
    return kb([
        [("📱 Instagram", "cat_instagram")],
        [("📺 IPTV Livestream 4K", "cat_IPTV Livestream 4K")],
        [("⬅️ Voltar", "start")],
    ])


def instagram_menu():
    return kb([
        [("1️⃣ Seguidores", "cat_Seguidores")],
        [("2️⃣ Curtidas", "cat_Curtidas")],
        [("3️⃣ Visualizações", "cat_Visualizações")],
        [("⬅️ Voltar", "menu_catalogo")],
    ])


def items_menu(categoria):
    rows = []
    for item in CATALOGO["catalogos"][categoria]:
        if "quantidade_texto" in item:
            rows.append([(f"{item['quantidade_texto']} {item['item']} — R$ {item['valor']}", f"item|{categoria}|{item['quantidade']}")])
        else:
            rows.append([(f"{item['item']} — {item['valor']}", f"item|{categoria}|0")])
    rows.append([("⬅️ Voltar", "cat_instagram" if categoria != "IPTV Livestream 4K" else "menu_catalogo")])
    return kb(rows)


def find_item(categoria, quantidade):
    for item in CATALOGO["catalogos"][categoria]:
        if int(item.get("quantidade", 0)) == int(quantidade):
            return item
    return CATALOGO["catalogos"][categoria][0]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_STATE.pop(update.effective_user.id, None)
    await update.effective_message.reply_text(CATALOGO["menus"]["boas_vindas"], parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id

    if data == "start":
        USER_STATE.pop(uid, None)
        await q.edit_message_text(CATALOGO["menus"]["boas_vindas"], parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    elif data == "menu_catalogo":
        await q.edit_message_text(CATALOGO["menus"]["catalogo"], parse_mode=ParseMode.MARKDOWN, reply_markup=catalog_menu())
    elif data == "cat_instagram":
        await q.edit_message_text(CATALOGO["menus"]["instagram"], parse_mode=ParseMode.MARKDOWN, reply_markup=instagram_menu())
    elif data in ["cat_Seguidores", "cat_Curtidas", "cat_Visualizações", "cat_IPTV Livestream 4K"]:
        categoria = data.replace("cat_", "")
        texto = CATALOGO["menus"].get(categoria.lower().replace("ções", "coes"), f"Selecione uma opção de {categoria}:")
        if categoria == "Visualizações":
            texto = CATALOGO["menus"].get("visualizacoes", texto)
        if categoria == "IPTV Livestream 4K":
            texto = CATALOGO["menus"].get("iptv", texto)
        await q.edit_message_text(texto, parse_mode=ParseMode.MARKDOWN, reply_markup=items_menu(categoria))
    elif data.startswith("item|"):
        _, categoria, quantidade = data.split("|", 2)
        item = find_item(categoria, quantidade)
        USER_STATE[uid] = {"etapa": "aguardando_link", "categoria": categoria, "item": item}
        await q.edit_message_text(item["mensagem_item"], parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_duvidas":
        await q.edit_message_text(CATALOGO["menus"]["duvidas"], parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    elif data == "menu_atendimento":
        await q.edit_message_text(CATALOGO["menus"]["atendimento"], parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    elif data == "menu_como_pedir":
        await q.edit_message_text(CATALOGO["menus"]["como_pedir"], parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    elif data == "menu_prazos":
        await q.edit_message_text(CATALOGO["menus"]["prazos"], parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if text == "#":
        await start(update, context)
        return

    state = USER_STATE.get(uid)
    if not state:
        await update.message.reply_text("Use /start para abrir o menu principal.")
        return

    item = state["item"]
    categoria = state["categoria"]

    if state["etapa"] == "aguardando_link":
        state["link_ou_user"] = text
        state["etapa"] = "aguardando_comprovante"
        await update.message.reply_text(
            "Estou analisando o link enviado. Enquanto analiso, vou passar as informações para pagamento e finalização do seu pedido.\n\n"
            "Após realizar o pagamento, envie o comprovante aqui.\n\n"
            f"*Dados:* Chave Pix:\n( 🔑 ) {CATALOGO['pix']}\n\n"
            f"*Valor:* R$ {item['valor']}\n\n"
            "*Observação:* Após o envio do comprovante, digite ou envie o comprovante para finalizar seu pedido.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if state["etapa"] == "aguardando_comprovante":
        state["comprovante"] = text
        user = update.effective_user
        resumo = (
            "🧾 *NOVO PEDIDO — TW STORE*\n\n"
            f"👤 *Cliente:* {user.full_name}\n"
            f"🆔 *ID Telegram:* `{user.id}`\n"
            f"🔗 *@:* @{user.username if user.username else 'sem_username'}\n\n"
            f"📦 *Item:* {item.get('quantidade_texto', '')} {item['item']}\n"
            f"📂 *Categoria:* {categoria}\n"
            f"💰 *Valor:* R$ {item['valor']}\n"
            f"🔗 *Link/@ enviado:* {state.get('link_ou_user')}\n"
            f"📎 *Comprovante/Resposta:* {text}\n"
            f"🕒 *Data:* {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
        if OWNER_CHAT_ID and not OWNER_CHAT_ID.startswith("COLOQUE"):
            try:
                await context.bot.send_message(chat_id=OWNER_CHAT_ID, text=resumo, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logging.exception("Erro ao enviar resumo ao dono: %s", e)
        await update.message.reply_text(
            "Tw Store agradece pela preferência!\n\n"
            "Solicitação Concluída ✅\n\n"
            "( ⏰ ) Início de 0 a 2 Horas.\n\n"
            "( ⚠️ ) Caso esteja realizando um serviço após as 02:00, saiba que o tempo de início pode variar de 2h a 7h, podendo ser iniciado após as 09:00.\n\n"
            "( 🛡️ ) Garantia de 24 Horas em casos de problemas técnicos de nossa equipe.\n\n"
            "*Observação:* Para solicitar um novo pedido volte ao menu principal, digitando (#).",
            parse_mode=ParseMode.MARKDOWN,
        )
        USER_STATE.pop(uid, None)


def main():
    if BOT_TOKEN.startswith("COLOQUE"):
        raise RuntimeError("Defina o BOT_TOKEN no arquivo .env ou nas variáveis de ambiente.")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
