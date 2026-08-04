import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


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

    def test_historico_semanal_perfil_isola_usuario_e_apaga_semana_antiga(self):
        pedido = {
            "pedido_id": "PED-PERFIL",
            "user_id": "123",
            "status": "pagamento_aprovado",
        }
        self.db.salvar_pedido_perfil_semanal(
            "PED-PERFIL",
            "123",
            "2026-W32",
            "9001",
            "aprovado",
            pedido,
        )
        self.db.salvar_pedido_perfil_semanal(
            "PED-ANTIGO",
            "123",
            "2026-W31",
            "8001",
            "negado",
            {**pedido, "pedido_id": "PED-ANTIGO"},
        )

        self.assertEqual(1, len(self.db.listar_pedidos_perfil_semanais("123", "2026-W32")))
        self.assertIsNone(
            self.db.obter_pedido_perfil_semanal("PED-PERFIL", "999", "2026-W32")
        )
        self.assertEqual(1, self.db.limpar_pedidos_perfil_semanais("2026-W32"))
        self.assertEqual(0, self.db.contar("pedidos_perfil_semanais", "semana_id = ?", ("2026-W31",)))


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

    def test_menu_remove_meu_perfil_e_novo_perfil_exibe_saldo(self):
        self.creditar(2050)
        linhas = bot.menu_principal().inline_keyboard
        textos = [linha[0].text for linha in linhas]
        callbacks = [linha[0].callback_data for linha in linhas]
        self.assertNotIn("👤 Meu Perfil", textos)
        self.assertNotIn("perfil:meu", callbacks)
        self.assertEqual("💳 consultar saldo", linhas[0][0].text)
        self.assertEqual("saldo:consultar", linhas[0][0].callback_data)
        self.assertFalse(hasattr(bot, "texto_my_profile_cliente"))

        texto = bot.texto_perfil_vendedor(fake_update())
        self.assertIn("Vendedor:* Cliente Teste", texto)
        self.assertIn("Cargo:* Vendedor", texto)
        self.assertIn("Saldo disponível", texto)
        self.assertIn("R$ 20,50", texto)
        self.assertIn("Pedidos realizados hoje:* 0", texto)
        self.assertEqual("🗒️ Meus Pedidos", bot.menu_perfil_vendedor().inline_keyboard[0][0].text)

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
        relatorio_original = bot.enviar_relatorio_admin_documento_sync
        pagamento_original = bot.garantir_pagamento_mercado_pago
        estoque_mock = AsyncMock(return_value=True)
        texto_mock = AsyncMock()
        relatorio_mock = Mock(side_effect=AssertionError("Relatório individual não deve ser enviado"))
        pagamento_mock = AsyncMock(side_effect=AssertionError("Pedido não deve gerar Pix"))
        bot.verificar_reposicao_antes_pagamento = estoque_mock
        bot.enviar_texto_sequencial = texto_mock
        bot.enviar_relatorio_admin_documento_sync = relatorio_mock
        bot.garantir_pagamento_mercado_pago = pagamento_mock
        try:
            asyncio.run(bot.processar_pedido_com_saldo_cliente(update, context, pedido))
        finally:
            bot.verificar_reposicao_antes_pagamento = estoque_original
            bot.enviar_texto_sequencial = enviar_texto_original
            bot.enviar_relatorio_admin_documento_sync = relatorio_original
            bot.garantir_pagamento_mercado_pago = pagamento_original

        self.assertEqual(500, self.db.obter_saldo_centavos("123"))
        historico = self.db.carregar_pedidos_historico()["PED-SALDO"]
        self.assertEqual("saldo", historico["forma_pagamento"])
        self.assertEqual("pagamento_aprovado", historico["status"])
        self.assertNotIn("PED-SALDO", self.db.carregar_pedidos_pendentes())
        self.assertEqual({}, context.user_data)
        relatorio_mock.assert_not_called()
        pagamento_mock.assert_not_awaited()

    def test_funcao_legada_de_relatorio_individual_ao_admin_nao_envia(self):
        documento_original = bot.enviar_documento_telegram_sync
        telegram_original = bot.enviar_telegram_sync
        documento_mock = Mock(side_effect=AssertionError("Não deve enviar documento ao admin"))
        telegram_mock = Mock(side_effect=AssertionError("Não deve enviar texto ao admin"))
        bot.enviar_documento_telegram_sync = documento_mock
        bot.enviar_telegram_sync = telegram_mock
        try:
            resultado = bot.enviar_relatorio_admin_documento_sync(
                {"pedido_id": "PED-SEM-RELATORIO"},
                "15,00",
            )
        finally:
            bot.enviar_documento_telegram_sync = documento_original
            bot.enviar_telegram_sync = telegram_original

        self.assertFalse(resultado)
        documento_mock.assert_not_called()
        telegram_mock.assert_not_called()

    def test_falta_de_estoque_exibe_novo_layout_sem_avisar_admin(self):
        pedido = {
            "pedido_id": "TW-SEM-ESTOQUE",
            "catalogo": "Instagram",
            "servico": "Seguidores",
            "quantidade": 500,
            "valor": "15,00",
            "link": "@cliente",
            "user_id": 123,
        }
        update = fake_update()
        context = SimpleNamespace(user_data={"pedido": pedido}, bot=SimpleNamespace())

        verificar_original = bot.verificar_reposicao_antes_pagamento_sync
        enviar_texto_original = bot.enviar_texto_sequencial
        avisar_admin_original = bot.avisar_admin_bloqueio_sem_reposicao
        texto_mock = AsyncMock()
        admin_mock = AsyncMock(side_effect=AssertionError("Admin só pode ser avisado após o clique"))
        bot.verificar_reposicao_antes_pagamento_sync = lambda _pedido: (
            False,
            "Saldo insuficiente na plataforma.",
        )
        bot.enviar_texto_sequencial = texto_mock
        bot.avisar_admin_bloqueio_sem_reposicao = admin_mock
        try:
            resultado = asyncio.run(bot.verificar_reposicao_antes_pagamento(update, context, pedido))
        finally:
            bot.verificar_reposicao_antes_pagamento_sync = verificar_original
            bot.enviar_texto_sequencial = enviar_texto_original
            bot.avisar_admin_bloqueio_sem_reposicao = avisar_admin_original

        self.assertFalse(resultado)
        self.assertEqual("bloqueado_sem_reposicao", pedido["status"])
        admin_mock.assert_not_awaited()
        texto_mock.assert_awaited_once()
        self.assertEqual(
            (
                "📦 *Produto sem estoque*\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "No momento não consigo liberar esse pedido automaticamente. "
                "Tente novamente mais tarde ou fale com o atendimento.\n\n"
                "ℹ️ Nenhum valor foi descontado do seu saldo.\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            texto_mock.await_args.args[2],
        )
        teclado = texto_mock.await_args.args[3].inline_keyboard
        self.assertEqual("📦 Solcitar Reposição", teclado[0][0].text)
        self.assertEqual("estoque:solicitar:TW-SEM-ESTOQUE", teclado[0][0].callback_data)

    def test_verificacao_guarda_valor_necessario_para_solicitacao(self):
        pedido = {
            "catalogo": "Instagram",
            "servico": "Seguidores",
            "quantidade": 500,
        }
        saldo_original = bot.consultar_saldo_plataforma_sync
        estimar_original = bot.estimar_custo_pedido_plataforma_sync
        margem_original = bot.MARGEM_SALDO_PLATAFORMA
        bot.consultar_saldo_plataforma_sync = lambda: {"saldo": 0.25, "moeda": "BRL"}
        bot.estimar_custo_pedido_plataforma_sync = lambda _pedido: {
            "custo_estimado": 1.25,
            "service_id": 9001,
            "quantidade": 500,
        }
        bot.MARGEM_SALDO_PLATAFORMA = 0
        try:
            disponivel, _detalhe = bot.verificar_reposicao_antes_pagamento_sync(pedido)
        finally:
            bot.consultar_saldo_plataforma_sync = saldo_original
            bot.estimar_custo_pedido_plataforma_sync = estimar_original
            bot.MARGEM_SALDO_PLATAFORMA = margem_original

        self.assertFalse(disponivel)
        self.assertEqual(1.25, pedido["plataforma_valor_necessario"])
        self.assertEqual("R$ 1,25", bot.valor_necessario_estoque_texto(pedido))

    def test_clique_em_reposicao_avisa_admin_uma_unica_vez(self):
        pedido = {
            "pedido_id": "TW-SEM-ESTOQUE",
            "catalogo": "Instagram",
            "servico": "Seguidores",
            "quantidade": 500,
            "valor": "15,00",
            "user_id": 123,
            "status": "bloqueado_sem_reposicao",
            "plataforma_valor_necessario": 1.25,
            "plataforma_moeda": "BRL",
        }
        bot.salvar_pedido_historico(pedido)

        update = fake_update()
        update.callback_query = SimpleNamespace(
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
        )
        enviar_admin = AsyncMock()
        context = SimpleNamespace(user_data={}, bot=SimpleNamespace(send_message=enviar_admin))
        admin_original = bot.ADMIN_CHAT_ID
        bot.ADMIN_CHAT_ID = "999"
        try:
            asyncio.run(
                bot.solicitar_reposicao_estoque_cliente(
                    update,
                    context,
                    "TW-SEM-ESTOQUE",
                )
            )
            asyncio.run(
                bot.solicitar_reposicao_estoque_cliente(
                    update,
                    context,
                    "TW-SEM-ESTOQUE",
                )
            )
        finally:
            bot.ADMIN_CHAT_ID = admin_original

        enviar_admin.assert_awaited_once()
        self.assertEqual(
            (
                "📦 *Pedido Reposição de Estoque.*\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "📦 *Produto:* Seguidores\n"
                "📁 *Categoria:* Instagram\n"
                "🗂️ *Quantidade:* 500\n"
                "💲 *Cobrado:* R$ 15,00\n"
                "💱 *Valor Necessário:* R$ 1,25\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            enviar_admin.await_args.kwargs["text"],
        )
        salvo = self.db.carregar_pedidos_historico()["TW-SEM-ESTOQUE"]
        self.assertTrue(salvo.get("reposicao_estoque_solicitada_em"))
        self.assertEqual("123", salvo.get("reposicao_estoque_solicitada_por"))

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

    def test_relatorio_produto_enviado_para_plataforma(self):
        pedido = {
            "catalogo": "Instagram",
            "servico": "Seguidores",
            "forma_pagamento": "saldo",
            "plataforma_api_status": "enviado",
            "plataforma_order_id": "98765",
            "plataforma_quantidade": 500,
            "saldo_apos_centavos": 1250,
        }

        self.assertEqual(
            (
                "✅ *Etapa 3 de 3 — Relatório do Produto.*\n\n"
                "━━━━━━━━━━━━━━━━━\n\n"
                "📦 *Produto:* Seguidores\n"
                "🔖 *Código/ID:* \"98765\"\n"
                "📁 *Categoria:* Instagram\n"
                "🏢 *Fornecedor:* Tw Store\n\n"
                "━━━━━━━━━━━━━━━━━\n\n"
                "📦 *ESTOQUE E VENDAS*\n\n"
                "🔹 *Saldo Restante:* R$ 12,50\n"
                "🔹 *Quantidade vendida:* 500\n\n"
                "━━━━━━━━━━━━━━━━━\n\n"
                "⏳ O tempo de conclusão pode variar conforme a demanda de pedidos.\n\n"
                "🎫 Precisa de ajuda? Fale com o suporte.\n\n"
                "━━━━━━━━━━━━━━━━━"
            ),
            bot.texto_final_pedido(pedido),
        )

    def test_perfil_cria_botoes_semanais_e_mostra_pedido_do_vendedor(self):
        agora = bot.agora_br().strftime("%d/%m/%Y %H:%M:%S")
        aprovado = {
            "pedido_id": "PED-APROVADO",
            "user_id": "123",
            "status": "pagamento_aprovado",
            "aprovado_em": agora,
            "plataforma_order_id": "98765",
            "plataforma_quantidade": 500,
            "servico": "Seguidores",
            "catalogo": "Instagram",
            "link": "@cliente",
        }
        negado = {
            "pedido_id": "PED-NEGADO",
            "user_id": "123",
            "status": "comprovante_reprovado",
            "reprovado_em": agora,
            "quantidade": 100,
            "servico": "Curtidas",
            "catalogo": "Instagram",
            "link": "https://instagram.com/p/teste",
        }
        outro_vendedor = {
            **aprovado,
            "pedido_id": "PED-OUTRO",
            "user_id": "999",
            "plataforma_order_id": "77777",
        }

        bot.salvar_pedido_historico(aprovado)
        bot.salvar_pedido_historico(negado)
        bot.salvar_pedido_historico(outro_vendedor)

        pedidos = bot.pedidos_perfil_vendedor("123")
        self.assertEqual(2, len(pedidos))
        menu = bot.menu_meus_pedidos_vendedor(pedidos)
        textos = [linha[0].text for linha in menu.inline_keyboard[:-1]]
        self.assertIn('🔖 ID: "98765"', textos)
        self.assertIn('🔖 ID: "PED-NEGADO"', textos)

        detalhe_aprovado = bot.texto_pedido_perfil_vendedor(aprovado)
        self.assertIn("Tw Store - Pedido ID:98765 aprovado", detalhe_aprovado)
        self.assertIn("Produto:* Seguidores", detalhe_aprovado)
        self.assertIn("Quantidade:* 500", detalhe_aprovado)

        detalhe_negado = bot.texto_pedido_perfil_vendedor(negado)
        self.assertIn("Tw Store - Pedido ID:PED-NEGADO negado", detalhe_negado)
        self.assertIsNone(
            self.db.obter_pedido_perfil_semanal(
                "PED-APROVADO",
                "999",
                bot.semana_info()["id"],
            )
        )
        self.assertEqual(
            "negado",
            bot.status_pedido_perfil({"status": "bloqueado_sem_reposicao"}),
        )

    def test_meus_pedidos_tem_paginacao_de_oito_botoes(self):
        pedidos = [
            {
                "pedido_id": f"PED-{indice}",
                "user_id": "123",
                "status": "pagamento_aprovado",
                "plataforma_order_id": str(9000 + indice),
            }
            for indice in range(9)
        ]

        primeira = bot.menu_meus_pedidos_vendedor(pedidos, 0).inline_keyboard
        segunda = bot.menu_meus_pedidos_vendedor(pedidos, 1).inline_keyboard

        self.assertEqual(8, sum(linha[0].text.startswith("🔖 ID:") for linha in primeira))
        self.assertEqual(1, sum(linha[0].text.startswith("🔖 ID:") for linha in segunda))
        self.assertEqual("perfil:pedidos:1", primeira[-2][-1].callback_data)
        self.assertEqual("perfil:pedidos:0", segunda[-2][0].callback_data)

    def test_comando_perfil_exibe_layout_e_botao(self):
        self.db.salvar_usuarios({
            "123": {
                "telegram_id": "123",
                "status": "aprovado",
                "cargo": "vendedor",
                "nome_telegram": "Cliente Teste",
            }
        })
        update = fake_update()
        context = SimpleNamespace(user_data={"estado_antigo": True}, bot=SimpleNamespace())

        asyncio.run(bot.perfil_vendedor(update, context))

        update.message.reply_text.assert_awaited_once()
        chamada = update.message.reply_text.await_args.kwargs
        self.assertIn("👤 *Vendedor:* Cliente Teste", chamada["text"])
        self.assertEqual("🗒️ Meus Pedidos", chamada["reply_markup"].inline_keyboard[0][0].text)
        self.assertEqual({}, context.user_data)


if __name__ == "__main__":
    unittest.main()
