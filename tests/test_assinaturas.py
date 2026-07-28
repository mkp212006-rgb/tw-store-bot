import asyncio
import sys
import types
import unittest


REQUESTS_STUBBED = False
TELEGRAM_STUBBED = False

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    REQUESTS_STUBBED = True
    requests_stub = types.ModuleType("requests")
    requests_stub.RequestException = Exception
    sys.modules["requests"] = requests_stub

try:
    import telegram  # noqa: F401
except ModuleNotFoundError:
    TELEGRAM_STUBBED = True
    telegram_stub = types.ModuleType("telegram")
    telegram_stub.__path__ = []

    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None, url=None, copy_text=None):
            self.text = text
            self.callback_data = callback_data
            self.url = url
            self.copy_text = copy_text

    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    class CopyTextButton:
        def __init__(self, text):
            self.text = text

    class Update:
        ALL_TYPES = []

    telegram_stub.InlineKeyboardButton = InlineKeyboardButton
    telegram_stub.InlineKeyboardMarkup = InlineKeyboardMarkup
    telegram_stub.CopyTextButton = CopyTextButton
    telegram_stub.Update = Update
    sys.modules["telegram"] = telegram_stub

    constants_stub = types.ModuleType("telegram.constants")
    constants_stub.ParseMode = types.SimpleNamespace(MARKDOWN="Markdown")
    sys.modules["telegram.constants"] = constants_stub

    helpers_stub = types.ModuleType("telegram.helpers")
    helpers_stub.escape_markdown = lambda texto, version=1: str(texto)
    sys.modules["telegram.helpers"] = helpers_stub

    error_stub = types.ModuleType("telegram.error")
    error_stub.BadRequest = Exception
    sys.modules["telegram.error"] = error_stub

    ext_stub = types.ModuleType("telegram.ext")
    ext_stub.Application = type("Application", (), {})
    ext_stub.CommandHandler = type("CommandHandler", (), {})
    ext_stub.CallbackQueryHandler = type("CallbackQueryHandler", (), {})
    ext_stub.MessageHandler = type("MessageHandler", (), {})
    ext_stub.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
    ext_stub.filters = types.SimpleNamespace()
    ext_stub.PicklePersistence = type("PicklePersistence", (), {})
    sys.modules["telegram.ext"] = ext_stub

from validators import validar_destino_pedido

try:
    import bot
except ModuleNotFoundError as exc:
    bot = None
    BOT_IMPORT_ERROR = str(exc)
else:
    BOT_IMPORT_ERROR = ""

if TELEGRAM_STUBBED:
    sys.modules.pop("bot", None)
    for nome_modulo in (
        "telegram.ext",
        "telegram.error",
        "telegram.helpers",
        "telegram.constants",
        "telegram",
    ):
        sys.modules.pop(nome_modulo, None)

if REQUESTS_STUBBED:
    sys.modules.pop("requests", None)


class AssinaturasValidationTests(unittest.TestCase):
    def test_assinatura_exige_email_valido(self):
        pedido = {"catalogo": "Assinaturas", "tipo_destino": "email"}

        valido, email, erro = validar_destino_pedido(pedido, "Cliente@Email.com")
        self.assertTrue(valido)
        self.assertEqual("cliente@email.com", email)
        self.assertEqual("", erro)

        valido, _, erro = validar_destino_pedido(pedido, "email-invalido")
        self.assertFalse(valido)
        self.assertIn("e-mail válido", erro)


@unittest.skipIf(bot is None, f"Dependências de runtime não instaladas: {BOT_IMPORT_ERROR}")
class AssinaturasMenuTests(unittest.TestCase):
    def test_categoria_aparece_abaixo_de_engajamentos(self):
        linhas = bot.menu_catalogos().inline_keyboard
        self.assertEqual("🚀 Engajamentos", linhas[0][0].text)
        self.assertEqual("🎫 Assinaturas", linhas[1][0].text)
        self.assertEqual("catalogo:assinaturas", linhas[1][0].callback_data)

    def test_imagens_das_assinaturas_estao_configuradas(self):
        self.assertTrue(bot.ASSINATURA_IMAGE_PATHS["netflix"].exists())
        self.assertTrue(bot.ASSINATURA_IMAGE_PATHS["prime_video"].exists())
        self.assertTrue(bot.ASSINATURA_IMAGE_PATHS["crunchyroll"].exists())
        self.assertTrue(bot.ASSINATURA_IMAGE_PATHS["spotify"].exists())
        self.assertTrue(bot.ASSINATURA_IMAGE_PATHS["paramount"].exists())

    def test_menu_mostra_servicos_e_valores(self):
        textos = [linha[0].text for linha in bot.menu_assinaturas().inline_keyboard[:-1]]
        self.assertEqual(
            [
                "Netflix — R$ 8,00",
                "Prime Video — R$ 5,00",
                "Crunchyroll — R$ 5,00",
                "Spotify — R$ 8,00",
                "Paramount — R$ 6,00",
            ],
            textos,
        )

    def test_pagamento_e_confirmacao_tratam_destino_como_email(self):
        pedido = {
            "catalogo": "Assinaturas",
            "servico": "Netflix",
            "quantidade": "1 assinatura",
            "valor": "8,00",
            "link": "cliente@email.com",
            "tipo_destino": "email",
            "pedido_id": "TWTESTE",
        }

        self.assertIn("E-mail informado: cliente@email.com", bot.texto_pagamento(pedido))
        self.assertEqual(
            "✏️ Alterar e-mail",
            bot.botoes_pagamento(pedido).inline_keyboard[-2][0].text,
        )
        self.assertIn("Aguardando ativação/envio dos dados", bot.texto_final_pedido(pedido))

    def test_selecao_cria_pedido_pronto_para_receber_email(self):
        update = types.SimpleNamespace(
            callback_query=types.SimpleNamespace(data="assinatura:netflix", message=None),
            effective_user=types.SimpleNamespace(
                full_name="Cliente Teste",
                username="cliente",
                id=12345,
            ),
        )
        context = types.SimpleNamespace(user_data={})
        mensagens = []

        async def acesso_liberado(_update, _context):
            return False

        async def capturar_mensagem(_update, texto, reply_markup=None, parse_mode=None):
            mensagens.append((texto, reply_markup, parse_mode))

        bloquear_original = bot.bloquear_se_sem_acesso
        responder_original = bot.safe_edit_or_reply
        bot.bloquear_se_sem_acesso = acesso_liberado
        bot.safe_edit_or_reply = capturar_mensagem
        try:
            asyncio.run(bot.callbacks(update, context))
        finally:
            bot.bloquear_se_sem_acesso = bloquear_original
            bot.safe_edit_or_reply = responder_original

        pedido = context.user_data["pedido"]
        self.assertEqual("Assinaturas", pedido["catalogo"])
        self.assertEqual("Netflix", pedido["servico"])
        self.assertEqual("8,00", pedido["valor"])
        self.assertEqual("email", pedido["tipo_destino"])
        self.assertEqual("aguardando_email_iptv", pedido["status"])
        self.assertIn("Envie o e-mail", mensagens[0][0])


if __name__ == "__main__":
    unittest.main()
