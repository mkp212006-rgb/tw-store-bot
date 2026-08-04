import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    requests_stub = types.ModuleType("requests")
    requests_stub.RequestException = Exception
    sys.modules["requests"] = requests_stub

try:
    import telegram  # noqa: F401
except ModuleNotFoundError:
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

import bot
from database import BotDatabase
from roles import CARGO_GERENTE


class FakeBot:
    def __init__(self):
        self.mensagens = []
        self.apagadas = []
        self._message_id = 0

    async def send_message(self, **kwargs):
        self.mensagens.append(kwargs)
        self._message_id += 1
        return SimpleNamespace(
            chat_id=kwargs["chat_id"],
            chat=SimpleNamespace(id=kwargs["chat_id"]),
            message_id=self._message_id,
        )

    async def delete_message(self, **kwargs):
        self.apagadas.append(kwargs)


def fake_update(telegram_id: int, callback_data: str | None = None):
    user = SimpleNamespace(id=telegram_id, full_name=f"Usuário {telegram_id}")
    chat = SimpleNamespace(id=telegram_id)
    if callback_data is None:
        message = SimpleNamespace(reply_text=AsyncMock())
        return SimpleNamespace(
            effective_user=user,
            effective_chat=chat,
            effective_message=message,
            message=message,
            callback_query=None,
        )

    query_message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(
        data=callback_data,
        message=query_message,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(
        effective_user=user,
        effective_chat=chat,
        effective_message=query_message,
        message=None,
        callback_query=query,
    )


class ManutencaoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "manutencao.sqlite3"
        self.db = BotDatabase(self.db_path)
        self.db_original = bot.DB
        self.admin_original = bot.ADMIN_CHAT_ID
        bot.DB = self.db
        bot.ADMIN_CHAT_ID = "100"
        bot.salvar_usuarios_registrados(
            {
                "200": {"status": "aprovado", "cargo": CARGO_GERENTE},
                "300": {"status": "pendente"},
                "400": {"status": "banido"},
            }
        )

    def tearDown(self):
        bot.DB = self.db_original
        bot.ADMIN_CHAT_ID = self.admin_original
        self.db._conn.close()
        self.tmp.cleanup()

    def test_estado_de_manutencao_fica_persistido_no_sqlite(self):
        bot.definir_estado_manutencao(True, fake_update(100))

        outra_conexao = BotDatabase(self.db_path)
        try:
            estado = outra_conexao.carregar_configuracao(
                bot.CONFIG_MANUTENCAO_CHAVE
            )
        finally:
            outra_conexao._conn.close()

        self.assertTrue(estado["ativa"])
        self.assertEqual("100", estado["iniciada_por_id"])

    def test_botao_notificacoes_aparece_somente_para_dono(self):
        textos_dono = [
            botao.text
            for linha in bot.menu_painel_admin(fake_update(100)).inline_keyboard
            for botao in linha
        ]
        textos_gerente = [
            botao.text
            for linha in bot.menu_painel_admin(fake_update(200)).inline_keyboard
            for botao in linha
        ]

        self.assertIn("📢 Notificações", textos_dono)
        self.assertNotIn("📢 Notificações", textos_gerente)

    def test_manutencao_bloqueia_nao_dono_e_libera_dono(self):
        bot.definir_estado_manutencao(True, fake_update(100))
        contexto_gerente = SimpleNamespace(user_data={"pedido": {}}, bot=FakeBot())
        update_gerente = fake_update(200)
        contexto_dono = SimpleNamespace(user_data={}, bot=FakeBot())

        bloqueado = asyncio.run(
            bot.bloquear_se_manutencao(update_gerente, contexto_gerente)
        )
        dono_bloqueado = asyncio.run(
            bot.bloquear_se_manutencao(fake_update(100), contexto_dono)
        )

        self.assertTrue(bloqueado)
        self.assertFalse(dono_bloqueado)
        self.assertEqual({}, contexto_gerente.user_data)
        update_gerente.effective_message.reply_text.assert_awaited_once()

    def test_inicio_e_conclusao_notificam_todos_e_alteram_bloqueio(self):
        fake_bot = FakeBot()
        dados_conversas = {
            200: {"ultima_chat_id_bot": 200, "ultima_mensagem_bot_id": 10, "pedido": {}},
            300: {"ultima_chat_id_bot": 300, "ultima_mensagem_bot_id": 20},
            400: {"ultima_chat_id_bot": 400, "ultima_mensagem_bot_id": 30},
        }
        contexto = SimpleNamespace(
            user_data={},
            bot=fake_bot,
            application=SimpleNamespace(user_data=dados_conversas),
        )
        inicio = fake_update(100, "admin_notificacoes:inicio")
        inicio_repetido = fake_update(100, "admin_notificacoes:inicio")
        conclusao = fake_update(100, "admin_notificacoes:conclusao")

        async def executar():
            await bot.notificar_inicio_manutencao(inicio, contexto)
            self.assertTrue(bot.manutencao_ativa())
            await bot.notificar_inicio_manutencao(inicio_repetido, contexto)
            await bot.notificar_conclusao_manutencao(conclusao, contexto)

        asyncio.run(executar())

        self.assertFalse(bot.manutencao_ativa())
        self.assertEqual(6, len(fake_bot.mensagens))
        ids_inicio = {
            str(item["chat_id"]) for item in fake_bot.mensagens[:3]
        }
        ids_conclusao = {
            str(item["chat_id"]) for item in fake_bot.mensagens[3:]
        }
        self.assertEqual({"200", "300", "400"}, ids_inicio)
        self.assertEqual({"200", "300", "400"}, ids_conclusao)
        self.assertIn("entrando em manutenção", fake_bot.mensagens[0]["text"])
        self.assertIn("inicie o bot novamente", fake_bot.mensagens[-1]["text"])
        self.assertIn("/start", fake_bot.mensagens[-1]["text"])
        self.assertEqual(6, len(fake_bot.apagadas))
        self.assertEqual(
            {"200", "300", "400"},
            {str(item["chat_id"]) for item in fake_bot.apagadas},
        )
        self.assertTrue(all(not dados for dados in dados_conversas.values()))
        self.assertEqual(3, self.db.contar("mensagens_bot"))

    def test_conclusao_apaga_somente_mensagens_registradas_do_bot(self):
        self.db.registrar_mensagem_bot("200", 10)
        self.db.registrar_mensagem_bot("200", 11)
        self.db.registrar_mensagem_bot("300", 20)
        fake_bot = FakeBot()

        resultado = asyncio.run(
            bot.apagar_mensagens_bot_usuarios(fake_bot, ["200", "300"])
        )

        self.assertEqual(3, resultado["mensagens_encontradas"])
        self.assertEqual(3, resultado["mensagens_apagadas"])
        self.assertEqual([], resultado["falhas_exclusao"])
        self.assertEqual(0, self.db.contar("mensagens_bot"))
        self.assertEqual(
            [
                {"chat_id": "200", "message_id": 10},
                {"chat_id": "200", "message_id": 11},
                {"chat_id": "300", "message_id": 20},
            ],
            fake_bot.apagadas,
        )


if __name__ == "__main__":
    unittest.main()
