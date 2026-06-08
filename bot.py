import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "ttwovendas@gmail.com")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
PIX_KEY = "ttwovendas@gmail.com"

CATALOGS = {
    "seguidores": {
        "title": "📈 Seguidores Instagram",
        "need": "link ou @ do perfil",
        "delivery": "Início: 0 a 2 horas após a confirmação do pagamento. Entrega gradual/drip-feed para proteção do perfil.",
        "items": [('100 Seguidores', '0,30'), ('200 Seguidores', '0,40'), ('250 Seguidores', '0,50'), ('500 Seguidores', '0,90'), ('700 Seguidores', '1,30'), ('900 Seguidores', '1,60'), ('1.000 Seguidores', '1,80'), ('1.500 Seguidores', '2,70'), ('3.000 Seguidores', '5,40'), ('10.000 Seguidores', '17,70')],
    },
    "curtidas": {
        "title": "❤️ Curtidas Instagram",
        "need": "link da publicação",
        "delivery": "Início: 0 a 2 horas após a confirmação do pagamento. Perfil/publicação precisa estar público.",
        "items": [('100 Curtidas', '0,10'), ('200 Curtidas', '0,15'), ('300 Curtidas', '0,20'), ('400 Curtidas', '0,25'), ('500 Curtidas', '0,30'), ('600 Curtidas', '0,35'), ('700 Curtidas', '0,45'), ('800 Curtidas', '0,50'), ('900 Curtidas', '0,55'), ('1.000 Curtidas', '0,60'), ('2.000 Curtidas', '1,10'), ('3.000 Curtidas', '1,60'), ('4.000 Curtidas', '2,10'), ('5.000 Curtidas', '2,60'), ('10.000 Curtidas', '5,00')],
    },
    "visualizacoes": {
        "title": "👁️ Visualizações Instagram",
        "need": "link do vídeo/reels",
        "delivery": "Início: 0 a 2 horas após a confirmação do pagamento. Conteúdo precisa estar público.",
        "items": [('100 Visualizações', '0,05'), ('200 Visualizações', '0,05'), ('300 Visualizações', '0,05'), ('400 Visualizações', '0,08'), ('500 Visualizações', '0,10'), ('600 Visualizações', '0,10'), ('700 Visualizações', '0,12'), ('800 Visualizações', '0,15'), ('900 Visualizações', '0,18'), ('1.000 Visualizações', '0,20'), ('2.000 Visualizações', '0,30'), ('3.000 Visualizações', '0,40'), ('4.000 Visualizações', '0,50'), ('5.000 Visualizações', '0,60'), ('10.000 Visualizações', '1,00')],
    },
    "iptv": {
        "title": "📺 IPTV Livestream 4K",
        "need": "modelo do aparelho e plano desejado",
        "delivery": "Compatível com Android, iPhone e Smart TV. A disponibilidade será confirmada no atendimento.",
        "items": [("Assinatura IPTV Livestream 4K", "Consultar")],
    },
}

FAQ_TEXT = """❓ *Dúvidas Frequentes*

*Como faço um pedido?*
Escolha o serviço desejado, envie o link/@ solicitado e aguarde a conferência.

*Quanto tempo demora?*
O prazo varia conforme o serviço e a demanda do momento. Em geral, o início é de 0 a 2 horas após confirmação.

*Posso tirar dúvidas antes de pagar?*
Sim. A equipe confirma as informações antes da finalização.
"""

HOW_TO_ORDER = """🧾 *Como fazer seu pedido*

1️⃣ Escolha o serviço
2️⃣ Escolha a quantidade
3️⃣ Envie o link ou @ solicitado
4️⃣ Confira os dados de pagamento
5️⃣ Envie o comprovante

Após isso, seu pedido será encaminhado para atendimento.
"""

SUPPORT_TEXT = """⏰ *Prazos e Suporte*

Cada serviço possui prazo diferente de início e conclusão.
Caso precise de ajuda, envie uma mensagem explicando sua dúvida que a equipe TW STORE recebe o resumo por e-mail.
"""


def money(value: str) -> str:
    return f"R$ {value}" if value != "Consultar" else "Consultar"


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Catálogo de Serviços", callback_data="menu:catalogos")],
        [InlineKeyboardButton("2️⃣ Dúvidas Frequentes", callback_data="info:faq")],
        [InlineKeyboardButton("3️⃣ Falar com Atendimento", callback_data="support")],
        [InlineKeyboardButton("4️⃣ Como Fazer Pedido", callback_data="info:how")],
    ])


def catalog_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Instagram", callback_data="menu:instagram")],
        [InlineKeyboardButton("📺 IPTV Livestream 4K", callback_data="catalog:iptv")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="start")],
    ])


def instagram_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Seguidores", callback_data="catalog:seguidores")],
        [InlineKeyboardButton("2️⃣ Curtidas", callback_data="catalog:curtidas")],
        [InlineKeyboardButton("3️⃣ Visualizações", callback_data="catalog:visualizacoes")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu:catalogos")],
    ])


def items_keyboard(catalog_key: str, page: int = 0) -> InlineKeyboardMarkup:
    items = CATALOGS[catalog_key]["items"]
    per_page = 8
    start = page * per_page
    end = start + per_page
    rows = []
    for idx, (name, price) in enumerate(items[start:end], start=start):
        rows.append([InlineKeyboardButton(f"{name} — {money(price)}", callback_data=f"item:{catalog_key}:{idx}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"catalog:{catalog_key}:{page-1}"))
    if end < len(items):
        nav.append(InlineKeyboardButton("Próxima ➡️", callback_data=f"catalog:{catalog_key}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu:instagram" if catalog_key != "iptv" else "menu:catalogos")])
    return InlineKeyboardMarkup(rows)


def send_order_email(order: dict) -> bool:
    if not SMTP_USER or not SMTP_PASSWORD:
        print("SMTP_USER ou SMTP_PASSWORD não configurado. Resumo do pedido:", order)
        return False

    subject = f"Novo pedido no bot TW STORE - {order.get('item', 'Atendimento')}"
    body = f"""
Novo pedido recebido pelo bot do Telegram.

Data/Hora: {order.get('datetime')}
Nome: {order.get('name')}
Usuário Telegram: {order.get('username')}
ID do chat: {order.get('chat_id')}

Categoria: {order.get('category')}
Item: {order.get('item')}
Valor: {order.get('price')}

Conteúdo enviado pelo cliente:
{order.get('content')}

Observação/Comprovante:
{order.get('proof') or 'Ainda não enviado'}
""".strip()

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = ADMIN_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, ADMIN_EMAIL, msg.as_string())
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = """🤖 *Bem-vindo(a) à TW STORE!*

Sou o assistente virtual da loja. Aqui você encontra serviços digitais com atendimento organizado, entrega rápida e suporte dedicado.

Escolha uma opção abaixo para continuar."""
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "start":
        await start(update, context)
        return

    if data == "menu:catalogos":
        await query.edit_message_text("🛍️ *Catálogo TW STORE*\n\nSelecione a categoria desejada:", parse_mode="Markdown", reply_markup=catalog_keyboard())
        return

    if data == "menu:instagram":
        await query.edit_message_text("📱 *Instagram*\n\nEscolha o catálogo desejado:", parse_mode="Markdown", reply_markup=instagram_keyboard())
        return

    if data == "info:faq":
        await query.edit_message_text(FAQ_TEXT, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="start")]]))
        return

    if data == "info:how":
        await query.edit_message_text(HOW_TO_ORDER, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="start")]]))
        return

    if data == "support":
        context.user_data["awaiting_support"] = True
        await query.edit_message_text("📞 *Atendimento TW STORE*\n\nEnvie agora sua dúvida ou solicitação. Eu vou encaminhar um resumo para a equipe.", parse_mode="Markdown")
        return

    if data.startswith("catalog:"):
        parts = data.split(":")
        catalog_key = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 0
        catalog = CATALOGS[catalog_key]
        lines = [f"{catalog['title']}", "", "Escolha uma opção:"]
        await query.edit_message_text("\n".join(lines), reply_markup=items_keyboard(catalog_key, page))
        return

    if data.startswith("item:"):
        _, catalog_key, idx_raw = data.split(":")
        idx = int(idx_raw)
        item, price = CATALOGS[catalog_key]["items"][idx]
        catalog = CATALOGS[catalog_key]
        context.user_data["order"] = {
            "category": catalog["title"],
            "item": item,
            "price": money(price),
            "need": catalog["need"],
            "datetime": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        }
        context.user_data["awaiting_order_content"] = True
        text = f"""✅ Você selecionou: *{item}*
💰 Valor: *{money(price)}*

{catalog['delivery']}

Para prosseguir, envie agora o *{catalog['need']}*.
"""
        await query.edit_message_text(text, parse_mode="Markdown")
        return


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or update.message.caption or "[Arquivo/mídia enviada]"

    if context.user_data.get("awaiting_support"):
        order = {
            "datetime": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "name": user.full_name,
            "username": f"@{user.username}" if user.username else "Sem username",
            "chat_id": update.effective_chat.id,
            "category": "Atendimento",
            "item": "Solicitação de atendimento",
            "price": "Não informado",
            "content": text,
            "proof": "Não enviado",
        }
        ok = send_order_email(order)
        context.user_data.clear()
        await update.message.reply_text("✅ Solicitação recebida! A equipe TW STORE foi notificada por e-mail." if ok else "✅ Solicitação recebida! O resumo ficou registrado no servidor, mas o e-mail precisa ser configurado no .env.", reply_markup=main_keyboard())
        return

    if context.user_data.get("awaiting_order_content"):
        context.user_data["order"]["content"] = text
        context.user_data["awaiting_order_content"] = False
        context.user_data["awaiting_proof"] = True
        price = context.user_data["order"].get("price", "Consultar")
        await update.message.reply_text(f"""💳 *Finalização do pedido*

Dados recebidos. Confira o pagamento:

Chave Pix: `{PIX_KEY}`
Valor: *{price}*

Após realizar o pagamento, envie o comprovante aqui na conversa. Caso ainda queira falar com a equipe antes de pagar, envie sua observação.""", parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_proof"):
        order = context.user_data.get("order", {})
        order.update({
            "name": user.full_name,
            "username": f"@{user.username}" if user.username else "Sem username",
            "chat_id": update.effective_chat.id,
            "proof": text,
        })
        ok = send_order_email(order)
        context.user_data.clear()
        await update.message.reply_text("✅ Pedido confirmado! A TW STORE agradece pela preferência. O resumo do pedido foi enviado para a equipe." if ok else "✅ Pedido confirmado! O pedido ficou registrado no servidor, mas o e-mail precisa ser configurado no .env.", reply_markup=main_keyboard())
        return

    await update.message.reply_text("Use /start para abrir o catálogo da TW STORE.")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Configure TELEGRAM_BOT_TOKEN no arquivo .env")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    print("Bot TW STORE rodando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
