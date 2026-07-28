import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
        bot.DB = self.db
        bot.ADMIN_CHAT_ID = "880001"
        bot.salvar_usuarios_registrados(
            {
                "880002": {"status": "aprovado", "cargo": CARGO_GERENTE},
                "880003": {"status": "aprovado", "cargo": CARGO_SECRETARIA},
                "880004": {"status": "aprovado", "cargo": CARGO_HELPER},
                "880005": {"status": "aprovado", "cargo": CARGO_VENDEDOR},
                "880006": {"status": "pendente", "cargo": CARGO_SECRETARIA},
            }
        )

    def tearDown(self):
        bot.DB = self.db_original
        bot.ADMIN_CHAT_ID = self.admin_original
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
        self.assertFalse(
            bot.usuario_tem_permissao_id("880099", PERMISSAO_PAINEL_ADMIN)
        )


@unittest.skipIf(bot is None, f"Dependências de runtime não instaladas: {BOT_IMPORT_ERROR}")
class CargoManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = BotDatabase(Path(self.tmp.name) / "cargos.sqlite3")
        self.db_original = bot.DB
        self.admin_original = bot.ADMIN_CHAT_ID
        self.safe_edit_original = bot.safe_edit_or_reply
        bot.DB = self.db
        bot.ADMIN_CHAT_ID = "770001"

    def tearDown(self):
        bot.safe_edit_or_reply = self.safe_edit_original
        bot.DB = self.db_original
        bot.ADMIN_CHAT_ID = self.admin_original
        self.db._conn.close()
        self.tmp.cleanup()

    def test_aprovacao_aplica_tester_e_meta_semanal(self):
        registro = {
            "telegram_id": "770010",
            "usuario_login": "novo_vendedor",
            "status": "pendente",
            "cargo": CARGO_VENDEDOR,
            "reaprovacao_obrigatoria": True,
        }

        resultado = bot.preparar_registro_aprovado(registro, "Administrador")

        self.assertIs(registro, resultado)
        self.assertEqual("aprovado", resultado["status"])
        self.assertEqual(CARGO_TESTER, resultado["cargo"])
        self.assertEqual(
            bot.META_SEMANAL_TESTER_CENTAVOS,
            resultado["meta_semanal_exigida_centavos"],
        )
        self.assertEqual(bot.semana_info()["id"], resultado["meta_tester_semana_inicio"])
        self.assertEqual("aprovacao_cadastro", resultado["cargo_aplicacao_origem"])
        self.assertNotIn("reaprovacao_obrigatoria", resultado)

    def test_lista_usa_login_do_cadastro_e_paginacao(self):
        usuarios = {}
        for indice in range(10):
            telegram_id = str(770100 + indice)
            usuarios[telegram_id] = {
                "telegram_id": telegram_id,
                "usuario_login": f"usuario_{indice:02d}",
                "nome_telegram": f"Nome {indice}",
                "status": "aprovado" if indice % 2 == 0 else "pendente",
                "cargo": CARGO_TESTER,
            }
        bot.salvar_usuarios_registrados(usuarios)

        primeira, pagina, total_paginas, total = bot.pagina_usuarios_cargos(0)
        segunda, pagina_dois, _, _ = bot.pagina_usuarios_cargos(1)

        self.assertEqual(8, len(primeira))
        self.assertEqual(2, len(segunda))
        self.assertEqual(0, pagina)
        self.assertEqual(1, pagina_dois)
        self.assertEqual(2, total_paginas)
        self.assertEqual(10, total)

        menu = bot.menu_usuarios_cargos_admin(0)
        botoes_usuarios = [linha[0] for linha in menu.inline_keyboard[:8]]
        self.assertEqual("👤 usuario_00", botoes_usuarios[0].text)
        self.assertEqual(
            "admin_cargos:usuario:770100:0",
            botoes_usuarios[0].callback_data,
        )

    def test_menu_do_usuario_oferece_aplicar_e_remover(self):
        menu = bot.menu_acoes_cargo_usuario_admin("770010", 2)
        textos = [linha[0].text for linha in menu.inline_keyboard[:2]]
        callbacks = [linha[0].callback_data for linha in menu.inline_keyboard[:2]]

        self.assertEqual(["🪪 Aplicar cargo", "➖ Remover cargo"], textos)
        self.assertEqual(
            [
                "admin_cargos:aplicar:770010:2",
                "admin_cargos:remover:770010:2",
            ],
            callbacks,
        )

    def test_remover_cargo_restaura_tester(self):
        bot.salvar_usuarios_registrados(
            {
                "770010": {
                    "telegram_id": "770010",
                    "usuario_login": "helper_teste",
                    "nome_telegram": "Helper Teste",
                    "status": "aprovado",
                    "cargo": CARGO_HELPER,
                }
            }
        )
        query = SimpleNamespace(answer=AsyncMock())
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=770001, full_name="Dono Teste"),
            effective_chat=SimpleNamespace(id=770001),
        )
        context = SimpleNamespace(bot=FakeBot(), user_data={"temporario": True})
        bot.safe_edit_or_reply = AsyncMock()

        asyncio.run(bot.remover_cargo_admin(update, context, "770010", 0))
        registro = bot.obter_usuario_registrado("770010")

        self.assertEqual(CARGO_TESTER, registro["cargo"])
        self.assertEqual(CARGO_HELPER, registro["cargo_removido"])
        self.assertEqual("remocao_cargo_painel", registro["cargo_aplicacao_origem"])
        self.assertEqual({}, context.user_data)
        bot.safe_edit_or_reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
                
