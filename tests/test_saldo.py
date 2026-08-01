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


def fake_update(user_id: int = 123):
    user = SimpleNamespace(
        id=user_id,
        full_name="Cliente Teste",
        username="cliente_teste",
    )
    message = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=user,
        effective_chat=SimpleNamespace(id=user_id),
        effective_message=message,
        message=message,
        callback_query=None,
    )


class SaldoDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = BotDatabase(Path(self.tmp.name) / "saldo.sqlite3")

    def tearDown(self):
        self.db._conn.close()
        self.tmp.cleanup()

    def criar_e_creditar_recarga(self, user_id="123", valor=2000, payment_id="MP-1"):
        recarga = {
            "recarga_id": "RC-1",
            "pedido_id": "RC-1",
            "user_id": user_id,
            "valor": bot.centavos_para_moeda(valor),
            "valor_centavos": valor,
            "status": "aguardando_pagamento",
            "mp_payment_id": payment_id,
            "criado_em": "01/08/2026 12:00:00",
        }
        self.db.salvar_recarga_saldo("RC-1", recarga)
        return recarga, self.db.creditar_recarga_saldo("RC-1", payment_id, {"id": payment_id})

    def test_credito_e_debito_sao_idempotentes(self):
        self.assertEqual(0, self.db.obter_saldo_centavos("123"))
        _, credito = self.criar_e_creditar_recarga()
        self.assertTrue(credito["creditada"])
        self.assertEqual(2000, self.db.obter_saldo_centavos("123"))

        repetido = self.db.creditar_recarga_saldo("RC-1", "MP-1", {"id": "MP-1"})
        self.assertTrue(repetido["ja_processada"])
        self.assertEqual(2000, self.db.obter_saldo_centavos("123"))

        pedido = {
            "pedido_id": "PED-1",
            "user_id": "123",
            "valor": "15,00",
            "status": "pagamento_aprovado",
            "forma_pagamento": "saldo",
        }
        debito = self.db.debitar_saldo_pedido("123", "PED-1", 1500, pedido)
        self.assertTrue(debito["debitado"])
        self.assertEqual(500, self.db.obter_saldo_centavos("123"))

        repetido = self.db.debitar_saldo_pedido("123", "PED-1", 1500, pedido)
        self.assertTrue(repetido["ja_processado"])
        self.assertEqual(500, self.db.obter_saldo_centavos("123"))
        self.assertEqual(2, self.db.contar("movimentacoes_saldo"))

    def test_saldo_insuficiente_nao_cria_debito(self):
        self.criar_e_creditar_recarga(valor=500)
        pedido = {"pedido_id": "PED-2", "user_id": "123", "valor": "8,00"}
        resultado = self.db.debitar_saldo_pedido("123", "PED-2", 800, pedido)

        self.assertTrue(resultado["saldo_insuficiente"])
        self.assertEqual(500, self.db.obter_saldo_centavos("123"))
        self.assertEqual(1, self.db.contar("movimentacoes_saldo"))
        self.assertIsNone(self.db.carregar_pedidos_pendentes().get("PED-2"))


class SaldoBotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = BotDatabase(Path(self.tmp.name) / "bot-saldo.sqlite3")
        self.db_original = bot.DB
        bot.DB = self.db
        bot._MP_PAYMENTS_EM_PROCESSAMENTO.clear()

    def tearDown(self):
        bot._MP_PAYMENTS_EM_PROCESSAMENTO.clear()
        bot.DB = self.db_original
        self.db._conn.close()
        self.tmp.cleanup()

    def creditar(self, valor=2000):
        recarga = {
            "recarga_id": "RC-TESTE",
            "pedido_id": "RC-TESTE",
            "user_id": "123",
            "valor": bot.centavos_para_moeda(valor),
            "valor_centavos": valor,
            "status": "aguardando_pagamento",
            "mp_payment_id": "MP-TESTE",
            "criado_em": "01/08/2026 12:00:00",
        }
        self.db.salvar_recarga_saldo(recarga["recarga_id"], recarga)
        self.db.creditar_recarga_saldo(recarga["recarga_id"], "MP-TESTE", {"id": "MP-TESTE"})

    def test_menu_e_perfil_exibem_saldo(self):
        self.creditar(2050)
        linhas = bot.menu_principal().inline_keyboard
        self.assertEqual("👤 Meu Perfil", linhas[0][0].text)
        self.assertEqual("💳 consultar saldo", linhas[1][0].text)
        self.assertEqual("saldo:consultar", linhas[1][0].callback_data)

        texto = bot.texto_my_profile_cliente(fake_update())
        self.assertIn("Saldo disponível", texto)
        self.assertIn("R$ 20,50", texto)

    def test_parser_de_valor_de_recarga(self):
        self.assertEqual(500, bot.parse_valor_recarga_centavos("5"))
        self.assertEqual(2050, bot.parse_valor_recarga_centavos("R$ 20,50"))
        self.assertEqual(30000, bot.parse_valor_recarga_centavos("300.00"))
        self.assertIsNone(bot.parse_valor_recarga_centavos("cinco"))
        self.assertIsNone(bot.parse_valor_recarga_centavos("5,999"))

    def test_taxa_de_cinco_por_cento_e_arredondada_em_centavos(self):
        self.assertEqual(25, bot.calcular_taxa_recarga_centavos(500))
        self.assertEqual(100, bot.calcular_taxa_recarga_centavos(2000))
        self.assertEqual(753, bot.calcular_taxa_recarga_centavos(15050))

        recarga = bot.preparar_recarga_saldo(fake_update(), 15050)
        self.assertEqual(15050, recarga["valor_centavos"])
        self.assertEqual(753, recarga["taxa_centavos"])
        self.assertEqual(15803, recarga["valor_pagamento_centavos"])
        self.assertEqual("150,50", recarga["valor_saldo"])
        self.assertEqual("7,53", recarga["taxa"])
        self.assertEqual("158,03", recarga["valor_pagamento"])

    def test_valor_informado_cria_recarga_e_tela_pix(self):
        update = fake_update()
        context = SimpleNamespace(user_data={"adicionando_saldo": True}, bot=SimpleNamespace())
        garantir_original = bot.garantir_pix_recarga_saldo
        enviar_original = bot.enviar_texto_sequencial
        enviar_mock = AsyncMock()

        async def gerar_pix_falso(recarga):
            recarga["mp_payment_id"] = "MP-NOVO"
            recarga["mp_qr_code"] = "PIX-COPIA-E-COLA"
            recarga["status"] = "aguardando_pagamento"
            self.db.salvar_recarga_saldo(recarga["recarga_id"], recarga)
            return True, "Pix criado"

        bot.garantir_pix_recarga_saldo = gerar_pix_falso
        bot.enviar_texto_sequencial = enviar_mock
        try:
            asyncio.run(bot.processar_valor_recarga_saldo(update, context, "5,00"))
        finally:
            bot.garantir_pix_recarga_saldo = garantir_original
            bot.enviar_texto_sequencial = enviar_original

        recarga_id = context.user_data["recarga_saldo_id"]
        recarga = self.db.obter_recarga_saldo(recarga_id)
        self.assertEqual(500, recarga["valor_centavos"])
        self.assertEqual(25, recarga["taxa_centavos"])
        self.assertEqual(525, recarga["valor_pagamento_centavos"])
        self.assertEqual("PIX-COPIA-E-COLA", recarga["mp_qr_code"])
        self.assertNotIn("adicionando_saldo", context.user_data)
        texto_pix = enviar_mock.await_args.args[2]
        self.assertIn("Pix de recarga gerado", texto_pix)
        self.assertIn("Taxa de 5%", texto_pix)
        self.assertIn("R$ 5,25", texto_pix)

    def test_pix_da_recarga_usa_valor_e_referencia_corretos(self):
        recarga = bot.preparar_recarga_saldo(fake_update(), 500)
        capturado = {}

        class Resposta:
            status_code = 201
            ok = True
            text = ""

            @staticmethod
            def json():
                return {
                    "id": "MP-PIX",
                    "status": "pending",
                    "external_reference": recarga["recarga_id"],
                    "transaction_amount": 5.25,
                    "point_of_interaction": {
                        "transaction_data": {
                            "qr_code": "PIX-COPIA-E-COLA",
                            "qr_code_base64": "",
                            "ticket_url": "",
                        }
                    },
                }

        def post_falso(url, headers=None, json=None, timeout=None):
            capturado.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return Resposta()

        token_original = bot.MERCADO_PAGO_ACCESS_TOKEN
        webhook_original = bot.MP_WEBHOOK_URL
        post_original = getattr(bot.requests, "post", None)
        bot.MERCADO_PAGO_ACCESS_TOKEN = "token-teste"
        bot.MP_WEBHOOK_URL = ""
        bot.requests.post = post_falso
        try:
            resultado = bot.criar_pagamento_mercado_pago_sync(recarga)
        finally:
            bot.MERCADO_PAGO_ACCESS_TOKEN = token_original
            bot.MP_WEBHOOK_URL = webhook_original
            if post_original is None:
                delattr(bot.requests, "post")
            else:
                bot.requests.post = post_original

        self.assertEqual("PIX-COPIA-E-COLA", resultado["qr_code"])
        self.assertEqual(5.25, capturado["json"]["transaction_amount"])
        self.assertEqual(recarga["recarga_id"], capturado["json"]["external_reference"])
        self.assertIn("Adicionar saldo", capturado["json"]["description"])

    def test_recarga_aprovada_so_credita_uma_vez(self):
        recarga = bot.aplicar_taxa_recarga({
            "recarga_id": "RC-WEBHOOK",
            "pedido_id": "RC-WEBHOOK",
            "user_id": "123",
            "valor": "10,00",
            "valor_centavos": 1000,
            "status": "aguardando_pagamento",
            "mp_payment_id": "MP-WEBHOOK",
            "criado_em": "01/08/2026 12:00:00",
        })
        pagamento = {
            "id": "MP-WEBHOOK",
            "status": "approved",
            "external_reference": "RC-WEBHOOK",
            "transaction_amount": 10.5,
        }
        self.db.salvar_recarga_saldo(recarga["recarga_id"], recarga)
        enviar_original = bot.enviar_telegram_sync
        bot.enviar_telegram_sync = lambda *args, **kwargs: True
        try:
            self.assertTrue(bot.processar_recarga_aprovada_sync(recarga, pagamento))
            self.assertTrue(bot.processar_recarga_aprovada_sync(recarga, pagamento))
        finally:
            bot.enviar_telegram_sync = enviar_original

        self.assertEqual(1000, self.db.obter_saldo_centavos("123"))
        self.assertEqual("aprovada", self.db.obter_recarga_saldo("RC-WEBHOOK")["status"])
        self.assertEqual(1, self.db.contar("movimentacoes_saldo"))

    def test_webhook_identifica_recarga_antes_de_pedidos(self):
        recarga = bot.aplicar_taxa_recarga({
            "recarga_id": "RC-ROTA",
            "pedido_id": "RC-ROTA",
            "user_id": "123",
            "valor": "5,00",
            "valor_centavos": 500,
            "status": "aguardando_pagamento",
            "mp_payment_id": "MP-ROTA",
            "criado_em": "01/08/2026 12:00:00",
        })
        pagamento = {
            "id": "MP-ROTA",
            "status": "approved",
            "external_reference": "RC-ROTA",
            "transaction_amount": 5.25,
        }
        self.db.salvar_recarga_saldo(recarga["recarga_id"], recarga)
        consultar_original = bot.consultar_pagamento_mercado_pago_sync
        enviar_original = bot.enviar_telegram_sync
        bot.consultar_pagamento_mercado_pago_sync = lambda _payment_id: pagamento
        bot.enviar_telegram_sync = lambda *args, **kwargs: True
        try:
            processado = bot.processar_notificacao_mercado_pago_sync("MP-ROTA")
        finally:
            bot.consultar_pagamento_mercado_pago_sync = consultar_original
            bot.enviar_telegram_sync = enviar_original

        self.assertTrue(processado)
        self.assertEqual(500, self.db.obter_saldo_centavos("123"))

    def test_pix_antigo_sem_taxa_continua_valido(self):
        recarga = {
            "recarga_id": "RC-ANTIGA",
            "pedido_id": "RC-ANTIGA",
            "user_id": "123",
            "valor": "5,00",
            "valor_centavos": 500,
            "status": "aguardando_pagamento",
            "mp_payment_id": "MP-ANTIGO",
            "mp_qr_code": "PIX-ANTIGO",
        }
        pagamento = {
            "id": "MP-ANTIGO",
            "status": "approved",
            "external_reference": "RC-ANTIGA",
            "transaction_amount": 5,
        }

        valido, _ = bot.pagamento_recarga_aprovado_e_valido(recarga, pagamento)

        self.assertTrue(valido)
        self.assertNotIn("taxa_centavos", recarga)

    def test_pedido_desconta_saldo_sem_gerar_pix(self):
        self.creditar(2000)
        update = fake_update()
        pedido = {
            "pedido_id": "PED-SALDO",
            "catalogo": "Internet Ilimitada",
            "servico": "1 mês",
            "quantidade": "1 mês",
            "valor": "15,00",
            "link": "cliente@email.com",
            "tipo_destino": "email",
            "status": "aguardando_saldo",
            "usuario": "Cliente Teste",
            "username": "cliente_teste",
            "user_id": 123,
        }
        context = SimpleNamespace(user_data={"pedido": pedido}, bot=SimpleNamespace())

        estoque_original = bot.verificar_reposicao_antes_pagamento
        enviar_texto_original = bot.enviar_texto_sequencial
        relatorio_original = bot.enviar_relatorio_admin
        pagamento_original = bot.garantir_pagamento_mercado_pago
        estoque_mock = AsyncMock(return_value=True)
        texto_mock = AsyncMock()
        relatorio_mock = AsyncMock(return_value=True)
        pagamento_mock = AsyncMock(side_effect=AssertionError("Pedido não deve gerar Pix"))
        bot.verificar_reposicao_antes_pagamento = estoque_mock
        bot.enviar_texto_sequencial = texto_mock
        bot.enviar_relatorio_admin = relatorio_mock
        bot.garantir_pagamento_mercado_pago = pagamento_mock
        try:
            asyncio.run(bot.processar_pedido_com_saldo_cliente(update, context, pedido))
        finally:
            bot.verificar_reposicao_antes_pagamento = estoque_original
            bot.enviar_texto_sequencial = enviar_texto_original
            bot.enviar_relatorio_admin = relatorio_original
            bot.garantir_pagamento_mercado_pago = pagamento_original

        self.assertEqual(500, self.db.obter_saldo_centavos("123"))
        historico = self.db.carregar_pedidos_historico()["PED-SALDO"]
        self.assertEqual("saldo", historico["forma_pagamento"])
        self.assertEqual("pagamento_aprovado", historico["status"])
        self.assertNotIn("PED-SALDO", self.db.carregar_pedidos_pendentes())
        self.assertEqual({}, context.user_data)
        pagamento_mock.assert_not_awaited()

    def test_pedido_sem_saldo_nao_debita(self):
        update = fake_update()
        pedido = {
            "pedido_id": "PED-SEM-SALDO",
            "catalogo": "Internet Ilimitada",
            "servico": "1 mês",
            "valor": "15,00",
            "link": "cliente@email.com",
            "user_id": 123,
        }
        context = SimpleNamespace(user_data={"pedido": pedido}, bot=SimpleNamespace())
        texto_original = bot.enviar_texto_sequencial
        texto_mock = AsyncMock()
        bot.enviar_texto_sequencial = texto_mock
        try:
            asyncio.run(bot.processar_pedido_com_saldo_cliente(update, context, pedido))
        finally:
            bot.enviar_texto_sequencial = texto_original

        self.assertEqual("aguardando_saldo", pedido["status"])
        self.assertEqual(0, self.db.obter_saldo_centavos("123"))
        self.assertEqual(0, self.db.contar("movimentacoes_saldo"))
        self.assertIn("Saldo insuficiente", texto_mock.await_args.args[2])


if __name__ == "__main__":
    unittest.main()
