import asyncio
import json
import os
import re
import logging
from io import BytesIO
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BASE_DIR = Path(__file__).resolve().parent
CATALOGO_PATH = BASE_DIR / "catalogo.json"
PAGAMENTO_INSTAGRAM_LAYOUT_PATH = BASE_DIR / "pagamento_instagram_layout.png"

with open(CATALOGO_PATH, "r", encoding="utf-8") as f:
    CATALOGO = json.load(f)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
PIX_CHAVE = os.getenv("PIX_CHAVE", "ttwovendas@gmail.com").strip()
PIX_RECEBEDOR = os.getenv("PIX_RECEBEDOR", "EMANUEL HENRIQUE DOS SANTOS LTDA").strip()


TZ_BR = ZoneInfo("America/Sao_Paulo")
TOTAIS_SEMANAIS_PATH = BASE_DIR / "totais_semanais.json"


def agora_br() -> datetime:
    return datetime.now(TZ_BR)


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
    if not TOTAIS_SEMANAIS_PATH.exists():
        return novo_registro_semanal()

    try:
        with open(TOTAIS_SEMANAIS_PATH, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except Exception:
        return novo_registro_semanal()

    if "semana_id" not in dados or "clientes" not in dados:
        return novo_registro_semanal()

    return dados


def salvar_totais_semanais(dados: dict):
    with open(TOTAIS_SEMANAIS_PATH, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


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

    escrever_caixa(f"R$ {valor}", (292, 602, 555, 705), 66, 36, cor=(255, 255, 255), negrito=True, max_linhas=1)
    escrever_caixa(catalogo, (316, 870, 636, 962), 58, 32, cor=(255, 255, 255), negrito=True, max_linhas=1)
    escrever_caixa(servico, (314, 962, 639, 1058), 52, 28, cor=(255, 255, 255), negrito=True, max_linhas=2)
    escrever_caixa(quantidade, (316, 1058, 632, 1152), 62, 34, cor=(255, 255, 255), negrito=True, max_linhas=1)
    escrever_caixa(link, (338, 1151, 644, 1246), 48, 26, cor=(255, 255, 255), negrito=True, max_linhas=2)

    if PIX_CHAVE and PIX_CHAVE != "ttwovendas@gmail.com":
        apagar_area((201, 476, 640, 535), margem=2)
        escrever_caixa(PIX_CHAVE, (196, 462, 644, 548), 48, 24, cor=(255, 255, 255), negrito=True, max_linhas=1)

    arquivo = BytesIO()
    img.save(arquivo, format="PNG", optimize=True)
    arquivo.seek(0)
    arquivo.name = "pagamento_instagram.png"
    return arquivo

async def enviar_pagamento_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE, pedido: dict):
    """Envia pagamento como imagem para Instagram e como texto para as demais categorias."""
    if pedido.get("catalogo") == "Instagram":
        imagem = gerar_imagem_pagamento_instagram(pedido)
        if imagem is not None:
            await update.effective_message.reply_document(
                document=imagem,
                filename="pagamento_instagram.png",
                caption="Envie o comprovante em imagem aqui na conversa para liberar a confirmação do pedido.",
                reply_markup=botoes_pagamento(),
            )
            return

    await update.effective_message.reply_text(
        texto_pagamento(pedido),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=botoes_pagamento(),
        disable_web_page_preview=True,
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
        context.user_data["pedido"] = {
            "catalogo": "Internet Ilimitada",
            "servico": "1 mês",
            "quantidade": "1 mês",
            "valor": "15,00",
            "link": None,
            "status": "aguardando_email_iptv",
            "usuario": update.effective_user.full_name,
            "username": update.effective_user.username,
            "user_id": update.effective_user.id,
        }

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

        context.user_data["pedido"] = {
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
        }

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
        await safe_edit_or_reply(update, texto_pagamento(pedido), botoes_pagamento())
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
        if pedido.get("catalogo") in ("IPTV Livestream 4K", "Internet Ilimitada"):
            pedido["status"] = "aguardando_email_iptv"
            await safe_edit_or_reply(update, "✏️ Envie novamente o e-mail correto para continuar.")
        else:
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

        if pedido.get("catalogo") in ("IPTV Livestream 4K", "Internet Ilimitada") and pedido.get("status") == "aguardando_email_iptv":
            await update.message.reply_text(
                (
                    "📧 *Confirme o e-mail informado:*\n\n"
                    f"`{md(pedido['link'])}`\n\n"
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

    await fechar_semana_se_necessario(context.bot)
    total_semanal_cliente = registrar_pedido_semanal(pedido)

    username = f'@{pedido["username"]}' if pedido.get("username") else "Sem username"
    relatorio = (
        "📥 *NOVO PEDIDO RECEBIDO — TW STORE*\n\n"
        f"🗂️ *Catálogo:* {md(pedido['catalogo'])}\n"
        f"📌 *Serviço:* {md(pedido['servico'])}\n"
        f"🔢 *Quantidade:* {md(pedido['quantidade'])}\n"
        f"💰 *Valor:* R$ {md(pedido['valor'])}\n"
        f"📆 *Total do cliente nesta semana:* R$ {md(total_semanal_cliente)}\n"
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
    app = Application.builder().token(BOT_TOKEN).post_init(iniciar_rotina_fechamento).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.IMAGE), receber_comprovante))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber_texto))
    print("Bot TW STORE iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
