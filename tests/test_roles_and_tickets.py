import asyncio
import tempfile
import unittest
from pathlib import Path

from database import BotDatabase
from roles import (
    CARGO_DONO,
    CARGO_GERENTE,
    CARGO_HELPER,
    CARGO_SECRETARIA,
    CARGO_TESTER,
    CARGO_VENDEDOR,
    PERMISSAO_APROVAR_CADASTROS,
    PERMISSAO_ATENDER_SUPORTE,
    PERMISSAO_PAINEL_ADMIN,
    cargo_tem_permissao,
    pode_atribuir_cargo,
    pode_gerenciar_cargo,
)

try:
    import bot
except ModuleNotFoundError as exc:
    bot = None
    BOT_IMPORT_ERROR = str(exc)
else:
    BOT_IMPORT_ERROR = ""


class FakeBot:
    def __init__(self):
        self.mensagens = []

    async def send_message(self, **kwargs):
        self.mensagens.append(kwargs)


class RolesTests(unittest.TestCase):
    def test_permissoes_por_cargo(self):
        self.assertTrue(cargo_tem_permissao(CARGO_DONO, "qualquer_permissao"))
        self.assertTrue(cargo_tem_permissao(CARGO_GERENTE, PERMISSAO_PAINEL_ADMIN))
        self.assertTrue(cargo_tem_permissao(CARGO_SECRETARIA, PERMISSAO_APROVAR_CADASTROS))
        self.assertTrue(cargo_tem_permissao(CARGO_SECRETARIA, PERMISSAO_ATENDER_SUPORTE))
        self.assertTrue(cargo_tem_permissao(CARGO_HELPER, PERMISSAO_ATENDER_SUPORTE))
        self.assertFalse(cargo_tem_permissao(CARGO_HELPER, PERMISSAO_PAINEL_ADMIN))
        self.assertFalse(cargo_tem_permissao(CARGO_VENDEDOR, PERMISSAO_PAINEL_ADMIN))
        self.assertFalse(cargo_tem_permissao(CARGO_TESTER, PERMISSAO_PAINEL_ADMIN))

    def test_hierarquia_de_atribuicao(self):
        self.assertTrue(pode_atribuir_cargo(CARGO_DONO, CARGO_DONO))
        self.assertTrue(pode_atribuir_cargo(CARGO_DONO, CARGO_GERENTE))
        self.assertTrue(pode_atribuir_cargo(CARGO_GERENTE, CARGO_SECRETARIA))
        self.assertFalse(pode_atribuir_cargo(CARGO_GERENTE, CARGO_GERENTE))
        self.assertFalse(pode_atribuir_cargo(CARGO_GERENTE, CARGO_DONO))
        self.assertFalse(pode_atribuir_cargo(CARGO_HELPER, CARGO_VENDEDOR))
        self.assertTrue(pode_gerenciar_cargo(CARGO_GERENTE, CARGO_HELPER))
        self.assertFalse(pode_gerenciar_cargo(CARGO_GERENTE, CARGO_GERENTE))


class TicketDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = BotDatabase(Path(self.tmp.name) / "teste.sqlite3")

    def tearDown(self):
        self.db._conn.close()
        self.tmp.cleanup()

    def test_ticket_unico_assuncao_e_fechamento(self):
        ticket, criado = self.db.criar_ticket("100", "Cliente", "@cliente")
        self.assertTrue(criado)

        repetido, criado_novamente = self.db.criar_ticket("100", "Cliente", "@cliente")
        self.assertFalse(criado_novamente)
        self.assertEqual(ticket["id"], repetido["id"])

        assumido, resultado = self.db.assumir_ticket(ticket["id"], "200", "Helper")
        self.assertEqual("assumido", resultado)
        self.assertEqual("em_atendimento", assumido["status"])

        _, resultado_outro = self.db.assumir_ticket(ticket["id"], "201", "Outro Helper")
        self.assertEqual("ja_assumido", resultado_outro)

        ticket_dois, _ = self.db.criar_ticket("101", "Outro cliente", "@outro")
        _, resultado_ocupado = self.db.assumir_ticket(ticket_dois["id"], "200", "Helper")
        self.assertEqual("atendente_ocupado", resultado_ocupado)

        fechado, resultado_fechado = self.db.fechar_ticket(ticket["id"], "Cliente")
        self.assertEqual("fechado", resultado_fechado)
        self.assertEqual("fechado", fechado["status"])

        novo, criado_depois = self.db.criar_ticket("100", "Cliente", "@cliente")
        self.assertTrue(criado_depois)
        self.assertNotEqual(ticket["id"], novo["id"])


@unittest.skipIf(bot is None, f"Dependências de runtime não instaladas: {BOT_IMPORT_ERROR}")
class TesterWeeklyGoalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = BotDatabase(Path(self.tmp.name) / "meta.sqlite3")
        self.db_original = bot.DB
        bot.DB = self.db

    def tearDown(self):
        bot.DB = self.db_original
        self.db._conn.close()
        self.tmp.cleanup()

    def test_tester_abaixo_da_meta_perde_acesso(self):
        bot.salvar_usuarios_registrados(
            {
                "991001": {
                    "telegram_id": "991001",
                    "nome_telegram": "Tester abaixo",
                    "status": "aprovado",
                    "cargo": CARGO_TESTER,
                },
                "991002": {
                    "telegram_id": "991002",
                    "nome_telegram": "Tester aprovado",
                    "status": "aprovado",
                    "cargo": CARGO_TESTER,
                },
                "991003": {
                    "telegram_id": "991003",
                    "nome_telegram": "Vendedor comum",
                    "status": "aprovado",
                    "cargo": CARGO_VENDEDOR,
                },
            }
        )
        semana = {
            "semana_id": "2026-W31",
            "inicio": "27/07/2026",
            "fim": "02/08/2026",
            "clientes": {
                "991001": {"total_centavos": bot.META_SEMANAL_TESTER_CENTAVOS - 1},
                "991002": {"total_centavos": bot.META_SEMANAL_TESTER_CENTAVOS},
            },
        }
        fake_bot = FakeBot()

        removidos = asyncio.run(bot.aplicar_meta_semanal_testers(fake_bot, semana))
        usuarios = bot.carregar_usuarios_registrados()

        self.assertEqual(["991001"], [item["telegram_id"] for item in removidos])
        self.assertEqual("removido_meta", usuarios["991001"]["status"])
        self.assertTrue(usuarios["991001"]["reaprovacao_obrigatoria"])
        self.assertEqual("aprovado", usuarios["991002"]["status"])
        self.assertEqual("atingida", usuarios["991002"]["ultima_meta_semanal_status"])
        self.assertEqual("aprovado", usuarios["991003"]["status"])
        self.assertTrue(
            any(str(item.get("chat_id")) == "991001" for item in fake_bot.mensagens)
        )


@unittest.skipIf(bot is None, f"Dependências de runtime não instaladas: {BOT_IMPORT_ERROR}")
class BotPermissionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = BotDatabase(Path(self.tmp.name) / "permissoes.sqlite3")
        self.db_original = bot.DB
        self.admin_original = bot.ADMIN_CHAT_ID
        self.admin2_original = bot.ADMIN2_CHAT_ID
        bot.DB = self.db
        bot.ADMIN_CHAT_ID = "880001"
        bot.ADMIN2_CHAT_ID = "880002"
        bot.salvar_usuarios_registrados(
            {
                "880003": {"status": "aprovado", "cargo": CARGO_SECRETARIA},
                "880004": {"status": "aprovado", "cargo": CARGO_HELPER},
                "880005": {"status": "aprovado", "cargo": CARGO_VENDEDOR},
                "880006": {"status": "pendente", "cargo": CARGO_SECRETARIA},
            }
        )

    def tearDown(self):
        bot.DB = self.db_original
        bot.ADMIN_CHAT_ID = self.admin_original
        bot.ADMIN2_CHAT_ID = self.admin2_original
        self.db._conn.close()
        self.tmp.cleanup()

    def test_equipes_sao_montadas_por_permissao_e_status(self):
        self.assertEqual(
            {"880001", "880002", "880003"},
            set(bot.ids_com_permissao(PERMISSAO_APROVAR_CADASTROS)),
        )
        self.assertEqual(
            {"880001", "880002", "880003", "880004"},
            set(bot.ids_com_permissao(PERMISSAO_ATENDER_SUPORTE)),
        )
        self.assertEqual(
            {"880001", "880002"},
            set(bot.ids_com_permissao(PERMISSAO_PAINEL_ADMIN)),
        )


if __name__ == "__main__":
    unittest.main()
