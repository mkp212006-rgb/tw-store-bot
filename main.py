import os
import math
import logging
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "5512997793285")
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY", "")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", "")

QUANTIDADES = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 2000, 3000, 4000, 5000, 10000]

CUSTO_POR_1000 = {
    "Seguidores Instagram": 1.18,
    "Curtidas Instagram": 0.38,
    "Visualizações Instagram": 0.02,
}

DESCRICOES = {
    "Seguidores Instagram": "Catálogo de seguidores para Instagram. Ideal para perfil público. Envie o @ ou link do perfil.",
    "Curtidas Instagram": "Catálogo de curtidas para Instagram. Envie o link da publicação/reels.",
    "Visualizações Instagram": "Catálogo de visualizações para Instagram. Envie o link do vídeo/reels/conteúdo.",
}


def moeda(valor: float) -> str:
    return f"R$ {valor:.2f}".replace(".", ",")


def fmt_qtd(qtd: int) -> str:
    return f"{qtd:,}".replace(",", ".")


def calcular_preco(qtd: int, custo_mil: float) -> tuple[float, float, float]:
    """Retorna custo real, preço para afiliado vender e lucro aproximado.
    Regra: lucro pequeno acima do custo. Para valores muito baixos, mínimo comercial de R$ 0,50.
    """
    custo = qtd / 1000 * custo_mil
    if custo < 0.10:
        venda = 0.50
    else:
        venda = math.ceil((custo * 1.35) * 10) / 10
    lucro = venda - custo
    return round(custo, 2), round(venda, 2), round(lucro, 2)


def montar_catalogo(nome: str) -> list[dict]:
    itens = []
    custo_mil = CUSTO_POR_1000[nome]
    for qtd in QUANTIDADES:
        custo, venda, lucro = calcular_preco(qtd, custo_mil)
        itens.append({"quantidade": qtd, "custo": custo, "venda": venda, "lucro": lucro})
    return itens

CATALOGOS = {nome: montar_catalogo(nome) for nome in CUSTO_POR_1000}


def kb_menu_principal():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Catálogo de Serviços", callback_data="menu_catalogo")],
        [InlineKeyboardButton("📺 IPTV Livestream 4K", callback_data="iptv")],
        [InlineKeyboardButton("🧾 Como Fazer Pedido", callback_data="como_pedir")],
        [InlineKeyboardButton("❓ Dúvidas Frequentes", callback_data="faq")],
        [InlineKeyboardButton("💬 Falar com Atendimento", callback_data="atendimento")],
    ])


def kb_catalogos():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Seguidores Instagram", callback_data="cat|Seguidores Instagram")],
        [InlineKeyboardButton("❤️ Curtidas Instagram", callback_data="cat|Curtidas Instagram")],
        [InlineKeyboardButton("▶️ Visualizações Instagram", callback_data="cat|Visualizações Instagram")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="inicio")],
    ])


def kb_itens(catalogo: str):
    linhas = []
    for item in CATALOGOS[catalogo]:
        q = fmt_qtd(item["quantidade"])
        label = f"{q} - vender por {moeda(item['venda'])}"
        linhas.append([InlineKeyboardButton(label, callback_data=f"item|{catalogo}|{item['quantidade']}")])
    linhas.append([InlineKeyboardButton("⬅️ Voltar aos catálogos", callback_data="menu_catalogo")])
    return InlineKeyboardMarkup(linhas)


def kb_confirmar():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar pedido", callback_data="confirmar_pedido")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="inicio")],
    ])


def resumo_pedido(data: dict, user) -> str:
    return (
        "📦 *NOVO PEDIDO PELO BOT TELEGRAM*\n\n"
        f"👤 Cliente Telegram: {user.full_name}\n"
        f"🆔 Usuário: @{user.username if user.username else 'sem username'}\n\n"
        f"📌 Serviço: {data.get('catalogo')}\n"
        f"🔢 Quantidade: {fmt_qtd(int(data.get('quantidade', 0)))}\n"
        f"💰 Valor para afiliado vender: {moeda(float(data.get('venda', 0)))}\n"
        f"💸 Custo aproximado: {moeda(float(data.get('custo', 0)))}\n"
        f"📈 Lucro aproximado: {moeda(float(data.get('lucro', 0)))}\n"
        f"🔗 Link/@ enviado: {data.get('link', '')}\n"
        f"📱 Contato informado: {data.get('contato', '')}\n"
        f"📝 Observação: {data.get('obs', 'Sem observação')}"
    )


def enviar_whatsapp(texto: str):
    if not CALLMEBOT_APIKEY:
        logging.warning("CALLMEBOT_APIKEY não configurada. WhatsApp automático não enviado.")
        return False
    url = f"https://api.callmebot.com/whatsapp.php?phone={ADMIN_WHATSAPP}&text={quote(texto)}&apikey={CALLMEBOT_APIKEY}"
    try:
        r = requests.get(url, timeout=20)
        return r.status_code == 200
    except Exception as exc:
        logging.exception("Erro ao enviar WhatsApp: %s", exc)
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    texto = (
        "✨ *Bem-vindo(a) à TW STORE!*\n\n"
        "Sou o assistente virtual da loja. Aqui você encontra serviços digitais com atendimento organizado, entrega rápida e suporte dedicado.\n\n"
        "Escolha uma opção abaixo para continuar."
    )
    if update.message:
        await update.message.reply_text(texto, parse_mode="Markdown", reply_markup=kb_menu_principal())
    else:
        await update.callback_query.edit_message_text(texto, parse_mode="Markdown", reply_markup=kb_menu_principal())


async def botoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "inicio":
        await start(update, context)
        return

    if data == "menu_catalogo":
        await query.edit_message_text(
            "📦 *Catálogo TW STORE*\n\nSelecione a categoria desejada para ver todos os pacotes.",
            parse_mode="Markdown",
            reply_markup=kb_catalogos(),
        )
        return

    if data.startswith("cat|"):
        catalogo = data.split("|", 1)[1]
        msg = f"*{catalogo}*\n\n{DESCRICOES[catalogo]}\n\nEscolha a quantidade desejada:"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_itens(catalogo))
        return

    if data.startswith("item|"):
        _, catalogo, qtd_txt = data.split("|")
        qtd = int(qtd_txt)
        item = next(i for i in CATALOGOS[catalogo] if i["quantidade"] == qtd)
        context.user_data["pedido"] = {"catalogo": catalogo, **item}
        await query.edit_message_text(
            f"✅ Você selecionou *{fmt_qtd(qtd)}* em *{catalogo}*.\n\n"
            f"💰 Valor para vender: *{moeda(item['venda'])}*\n"
            f"💸 Custo aproximado: *{moeda(item['custo'])}*\n"
            f"📈 Seu lucro aproximado: *{moeda(item['lucro'])}*\n\n"
            "Agora envie o link ou @ do perfil/publicação/conteúdo.",
            parse_mode="Markdown",
        )
        context.user_data["etapa"] = "aguardando_link"
        return

    if data == "confirmar_pedido":
        pedido = context.user_data.get("pedido", {})
        texto = resumo_pedido(pedido, query.from_user)
        enviar_whatsapp(texto.replace("*", ""))
        if ADMIN_TELEGRAM_ID:
            try:
                await context.bot.send_message(chat_id=int(ADMIN_TELEGRAM_ID), text=texto, parse_mode="Markdown")
            except Exception:
                pass
        await query.edit_message_text(
            "✅ *Pedido enviado com sucesso!*\n\n"
            "A TW STORE agradece pela preferência. Seu pedido será conferido e o atendimento continuará em breve.",
            parse_mode="Markdown",
        )
        context.user_data.clear()
        return

    if data == "iptv":
        await query.edit_message_text(
            "📺 *IPTV Livestream 4K*\n\n"
            "Assinatura com acesso pelo aplicativo.\n\n"
            "✅ Compatível com Android\n✅ Compatível com iPhone\n✅ Compatível com Smart TV\n\n"
            "Para consultar planos e disponibilidade, fale com o atendimento.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Falar com Atendimento", callback_data="atendimento")],[InlineKeyboardButton("⬅️ Voltar", callback_data="inicio")]])
        )
        return

    if data == "como_pedir":
        await query.edit_message_text(
            "🧾 *Como Fazer Pedido*\n\n"
            "1️⃣ Escolha o serviço desejado.\n"
            "2️⃣ Escolha a quantidade.\n"
            "3️⃣ Envie o link ou @ solicitado.\n"
            "4️⃣ Aguarde a conferência.\n"
            "5️⃣ Receba as instruções de pagamento.\n"
            "6️⃣ Envie o comprovante.\n\n"
            "Após isso, seu pedido será encaminhado.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="inicio")]])
        )
        return

    if data == "faq":
        await query.edit_message_text(
            "❓ *Dúvidas Frequentes*\n\n"
            "*Como faço um pedido?*\nEscolha o serviço, quantidade e envie o link/@ necessário.\n\n"
            "*Quanto tempo demora?*\nO prazo varia conforme o serviço e a demanda do momento.\n\n"
            "*Posso tirar dúvidas antes de pagar?*\nSim. A equipe confirma as informações antes da finalização.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="inicio")]])
        )
        return

    if data == "atendimento":
        await query.edit_message_text(
            "💬 *Falar com Atendimento*\n\n"
            "Envie agora:\n"
            "• Serviço desejado\n• Quantidade\n• Link ou @ do perfil\n\n"
            "Um membro da equipe continuará o atendimento assim que possível.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="inicio")]])
        )
        return


async def mensagens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    etapa = context.user_data.get("etapa")
    pedido = context.user_data.get("pedido")
    if not pedido:
        await update.message.reply_text("Use /start para abrir o menu principal.")
        return

    if etapa == "aguardando_link":
        pedido["link"] = update.message.text.strip()
        context.user_data["etapa"] = "aguardando_contato"
        await update.message.reply_text("Perfeito. Agora envie o contato do cliente ou seu WhatsApp para acompanhamento.")
        return

    if etapa == "aguardando_contato":
        pedido["contato"] = update.message.text.strip()
        context.user_data["etapa"] = "aguardando_obs"
        await update.message.reply_text("Deseja adicionar alguma observação? Se não tiver, envie: Sem observação")
        return

    if etapa == "aguardando_obs":
        pedido["obs"] = update.message.text.strip()
        await update.message.reply_text(
            resumo_pedido(pedido, update.effective_user) + "\n\nConfirma o envio desse pedido?",
            parse_mode="Markdown",
            reply_markup=kb_confirmar(),
        )
        context.user_data["etapa"] = "confirmacao"
        return


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Configure TELEGRAM_BOT_TOKEN no arquivo .env")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(botoes))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensagens))
    print("Bot TW STORE rodando...")
    app.run_polling()

if __name__ == "__main__":
    main()
