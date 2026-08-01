import sys
import types
import unittest


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


class CalculoPrecoDinamicoTests(unittest.TestCase):
    def test_exemplos_definidos_para_precificacao(self):
        self.assertEqual("3,20", bot.calcular_preco_dinamico("1.88")["valor"])
        self.assertEqual("30,00", bot.calcular_preco_dinamico("18.80")["valor"])

    def test_valor_minimo_cobrado_e_099(self):
        calculo = bot.calcular_preco_dinamico("0")

        self.assertEqual("0,99", calculo["valor"])

    def test_quantidade_livre_respeita_intervalo(self):
        self.assertEqual((100, ""), bot.normalizar_quantidade_dinamica("100"))
        self.assertEqual((1250, ""), bot.normalizar_quantidade_dinamica("1.250"))
        self.assertEqual((100000, ""), bot.normalizar_quantidade_dinamica("100.000"))
        self.assertIsNone(bot.normalizar_quantidade_dinamica("99")[0])
        self.assertIsNone(bot.normalizar_quantidade_dinamica("100001")[0])
        self.assertIsNone(bot.normalizar_quantidade_dinamica("100,5")[0])

    def test_todos_engajamentos_disponiveis_usam_fluxo_dinamico(self):
        servicos_por_origem = {
            "instagram": {"seguidores", "curtidas", "visualizacoes"},
            "instagram_brasileiros": {"seguidores"},
            "tiktok": {"seguidores", "curtidas", "visualizacoes"},
            "kwai": {"seguidores", "curtidas", "visualizacoes"},
        }

        for origem, servicos in servicos_por_origem.items():
            for servico in servicos:
                with self.subTest(origem=origem, servico=servico):
                    configuracao = bot.configuracao_servico_dinamico(origem, servico)
                    self.assertIsNotNone(configuracao)
                    self.assertEqual(servico, configuracao["servico_chave"])

    def test_pedido_dinamico_ignora_preco_fixo_do_catalogo(self):
        configuracao = bot.configuracao_servico_dinamico("instagram", "seguidores")
        estimar_original = bot.estimar_custo_pedido_plataforma_sync
        valor_catalogo_original = configuracao["servico"]["itens"][0]["valor"]
        consulta_forcada = []

        def estimar_pela_plataforma(pedido, forcar_atualizacao=False):
            consulta_forcada.append(forcar_atualizacao)
            return {
                "service_id": "123",
                "quantidade": pedido["quantidade_api"],
                "servico": {"service": "123"},
                "rate": 1.88,
                "custo_estimado": 1.88,
            }

        configuracao["servico"]["itens"][0]["valor"] = "9999,99"
        bot.estimar_custo_pedido_plataforma_sync = estimar_pela_plataforma
        try:
            pedido = bot.criar_pedido_quantidade_dinamica_sync(
                configuracao,
                1000,
                {"full_name": "Cliente", "username": "cliente", "id": 10},
            )
        finally:
            bot.estimar_custo_pedido_plataforma_sync = estimar_original
            configuracao["servico"]["itens"][0]["valor"] = valor_catalogo_original

        self.assertEqual("1.000", pedido["quantidade"])
        self.assertEqual(1000, pedido["quantidade_api"])
        self.assertEqual("3,20", pedido["valor"])
        self.assertTrue(pedido["preco_dinamico"])
        self.assertEqual("plataforma_api", pedido["fonte_preco"])
        self.assertEqual("123", pedido["plataforma_service_id"])
        self.assertEqual([True], consulta_forcada)

    def test_consulta_forcada_ignora_cache_e_busca_tarifa_da_plataforma(self):
        requisicao_original = bot.requisicao_plataforma_sync
        cache_original = dict(bot.PLATAFORMA_SERVICOS_CACHE)
        chamadas = []
        bot.PLATAFORMA_SERVICOS_CACHE.clear()
        bot.PLATAFORMA_SERVICOS_CACHE.update({
            "expira_em": float("inf"),
            "dados": [{"service": "123", "rate": "999", "min": "100", "max": "100000"}],
        })

        def requisicao_atual(payload):
            chamadas.append(payload)
            return [{"service": "123", "rate": "1.88", "min": "100", "max": "100000"}]

        bot.requisicao_plataforma_sync = requisicao_atual
        try:
            estimativa = bot.estimar_custo_pedido_plataforma_sync(
                {
                    "catalogo": "Instagram",
                    "servico_chave": "seguidores",
                    "api_service_id": "123",
                    "quantidade_api": 1000,
                },
                forcar_atualizacao=True,
            )
        finally:
            bot.requisicao_plataforma_sync = requisicao_original
            bot.PLATAFORMA_SERVICOS_CACHE.clear()
            bot.PLATAFORMA_SERVICOS_CACHE.update(cache_original)

        self.assertEqual([{"action": "services"}], chamadas)
        self.assertEqual(1.88, estimativa["rate"])
        self.assertEqual(1.88, estimativa["custo_estimado"])

    def test_preco_e_atualizado_antes_do_primeiro_pagamento(self):
        pedido = {
            "catalogo": "Instagram",
            "servico_chave": "seguidores",
            "quantidade": "10.000",
            "quantidade_api": 10000,
            "valor": "1,00",
            "preco_dinamico": True,
        }
        estimar_original = bot.estimar_custo_pedido_plataforma_sync
        verificar_original = bot.CHECK_ESTOQUE_ANTES_PAGAMENTO
        bot.estimar_custo_pedido_plataforma_sync = lambda _pedido, forcar_atualizacao=False: {
            "service_id": "123",
            "quantidade": 10000,
            "servico": {"service": "123"},
            "rate": 1.88,
            "custo_estimado": 18.80,
        }
        bot.CHECK_ESTOQUE_ANTES_PAGAMENTO = False
        try:
            ok, _ = bot.verificar_reposicao_antes_pagamento_sync(pedido)
        finally:
            bot.estimar_custo_pedido_plataforma_sync = estimar_original
            bot.CHECK_ESTOQUE_ANTES_PAGAMENTO = verificar_original

        self.assertTrue(ok)
        self.assertEqual("30,00", pedido["valor"])


if __name__ == "__main__":
    unittest.main()
