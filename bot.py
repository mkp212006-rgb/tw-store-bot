import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = 8833072850:AAFhQzlZ_SUVVqDqV7Q7wdHS-FK38QZTOlI
WHATSAPP = os.getenv("WHATSAPP_CONTATO", "")

SEGUIDORES = [
    ("100 Seguidores", "R$ 0,30"),
    ("200 Seguidores", "R$ 0,40"),
    ("250 Seguidores", "R$ 0,50"),
    ("500 Seguidores", "R$ 0,90"),
    ("700 Seguidores", "R$ 1,30"),
    ("900 Seguidores", "R$ 1,60"),
    ("1.000 Seguidores", "R$ 1,80"),
    ("1.500 Seguidores", "R$ 2,70"),
    ("3.000 Seguidores", "R$ 5,40"),
    ("10.000 Seguidores", "R$ 17,70"),
]

CURTIDAS = [
    ("100 Curtidas", "R$ 0,10"),
    ("200 Curtidas", "R$ 0,15"),
    ("300 Curtidas", "R$ 0,20"),
    ("400 Curtidas", "R$ 0,25"),
    ("500 Curtidas", "R$ 0,30"),
    ("600 Curtidas", "R$ 0,35"),
    ("700 Curtidas", "R$ 0,45"),
    ("800 Curtidas", "R$ 0,50"),
    ("900 Curtidas", "R$ 0,55"),
    ("1.000 Curtidas", "R$ 0,60"),
    ("2.000 Curtidas", "R$ 1,10"),
    ("3.000 Curtidas", "R$ 1,60"),
    ("4.000 Curtidas", "R$ 2,10"),
    ("5.000 Curtidas", "R$ 2,60"),
    ("10.000 Curtidas", "R$ 5,00"),
]

VISUALIZACOES = [
    ("100 Visualizações", "R$ 0,05"),
    ("200 Visualizações", "R$ 0,05"),
    ("300 Visualizações", "R$ 0,05"),
    ("400 Visualizações", "R$ 0,08"),
    ("500 Visualizações", "R$ 0,10"),
    ("600 Visualizações", "R$ 0,10"),
    ("700 Visualizações", "R$ 0,12"),
    ("800 Visualizações", "R$ 0,15"),
    ("900 Visualizações", "R$ 0,18"),
    ("1.000 Visualizações", "R$ 0,20"),
    ("2.000 Visualizações", "R$ 0,30"),
    ("3.000 Visualizações", "R$ 0,40"),
    ("4.000 Visualizações", "R$ 0,50"),
    ("5.000 Visualizações", "R$ 0,60"),
    ("10.000 Visualizações", "R$ 1,00"),
]

CATALOGOS = {
    "seguidores": ("1️⃣ Seguidores", "Você selecionou o catálogo de Seguidores. Escolha um pacote abaixo:", SEGUIDORES),
    "curtidas": ("2️⃣ Curtidas", "❤️ Curtidas para Instagram\n\nEscolha um pacote abaixo:", CURTIDAS),
    "visualizacoes": ("3️⃣ Visualizações", "👀 Visualizações para Instagram\n\nEscolha um pacote abaixo:", VISUALIZACOES),
}


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Catálogo de Serviços", callback_data="servicos")],
        [InlineKeyboardButton("📱 Instagram", callback_data="instagram")],
        [InlineKeyboardButton("📞 Atendimento", callback_data="atendimento")],
    ])


def instagram_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Seguidores", callback_data="cat:seguidores")],
        [InlineKeyboardButton("2️⃣ Curtidas", callback_data="cat:curtidas")],
        [InlineKeyboardButton("3️⃣ Visualizações", callback_data="cat:visualizacoes")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="inicio")],
    ])


def catalog_keyboard(tipo):
    itens = CATALOGOS[tipo][2]
    rows = []
    for idx, (nome, valor) in enumerate(itens):
        rows.append([InlineKeyboardButton(f"{nome} - {valor}", callback_data=f"item:{tipo}:{idx}")])
    rows.append([InlineKeyboardButton("⬅️ Voltar ao Instagram", callback_data="instagram")])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚀 *Bem-vindo(a) à TW STORE!*\n\n"
        "Sou o assistente virtual da loja. Aqui você encontra serviços digitais com atendimento organizado.\n\n"
        "Escolha uma opção abaixo:"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "inicio":
        await query.edit_message_text(
            "🚀 *Bem-vindo(a) à TW STORE!*\n\nEscolha uma opção abaixo:",
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )
        return

    if data in ("servicos", "instagram"):
        await query.edit_message_text(
            "📱 *Instagram*\n\nÓtima escolha! Aqui estão alguns serviços disponíveis para a plataforma Instagram.\n\nTodos os pedidos passam por conferência antes da finalização.",
            parse_mode="Markdown",
            reply_markup=instagram_keyboard(),
        )
        return

    if data == "atendimento":
        msg = "📞 *Atendimento*\n\nEnvie sua dúvida por aqui ou fale com nossa equipe."
        if WHATSAPP:
            msg += f"\n\nWhatsApp: {WHATSAPP}"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
        return

    if data.startswith("cat:"):
        tipo = data.split(":", 1)[1]
        titulo, descricao, _ = CATALOGOS[tipo]
        await query.edit_message_text(
            f"*{titulo}*\n\n{descricao}",
            parse_mode="Markdown",
            reply_markup=catalog_keyboard(tipo),
        )
        return

    if data.startswith("item:"):
        _, tipo, idx = data.split(":")
        nome, valor = CATALOGOS[tipo][2][int(idx)]
        await query.edit_message_text(
            f"✅ *Pacote selecionado*\n\n{nome}\nValor: *{valor}*\n\nPara finalizar, envie o @ ou link do perfil/publicação/conteúdo e aguarde a conferência do pedido.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Voltar ao catálogo", callback_data=f"cat:{tipo}")],
                [InlineKeyboardButton("🏠 Início", callback_data="inicio")],
            ]),
        )


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Digite /start para abrir o catálogo da TW STORE.",
        reply_markup=main_keyboard(),
    )


def run():
    if not TOKEN:
        raise RuntimeError("Defina a variável TELEGRAM_BOT_TOKEN com o token do BotFather.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    app.run_polling()


if __name__ == "__main__":
    run()
