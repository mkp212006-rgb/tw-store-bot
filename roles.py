"""Cargos e permissões do bot.

Este módulo não depende do Telegram nem do banco de dados. Isso mantém a
hierarquia centralizada e permite testar as regras sem iniciar o bot.
"""

CARGO_DONO = "dono"
CARGO_GERENTE = "gerente"
CARGO_SECRETARIA = "secretaria"
CARGO_HELPER = "helper"
CARGO_VENDEDOR = "vendedor"
CARGO_TESTER = "vendedor_tester"

PERMISSAO_PAINEL_ADMIN = "painel_admin"
PERMISSAO_APROVAR_CADASTROS = "aprovar_cadastros"
PERMISSAO_ATENDER_SUPORTE = "atender_suporte"
PERMISSAO_GERENCIAR_CARGOS = "gerenciar_cargos"
PERMISSAO_USAR_BOT = "usar_bot"


CARGOS = {
    CARGO_DONO: {
        "nome": "Dono",
        "nivel": 60,
        "permissoes": {
            PERMISSAO_PAINEL_ADMIN,
            PERMISSAO_APROVAR_CADASTROS,
            PERMISSAO_ATENDER_SUPORTE,
            PERMISSAO_GERENCIAR_CARGOS,
            PERMISSAO_USAR_BOT,
        },
    },
    CARGO_GERENTE: {
        "nome": "Gerente",
        "nivel": 50,
        "permissoes": {
            PERMISSAO_PAINEL_ADMIN,
            PERMISSAO_APROVAR_CADASTROS,
            PERMISSAO_ATENDER_SUPORTE,
            PERMISSAO_GERENCIAR_CARGOS,
            PERMISSAO_USAR_BOT,
        },
    },
    CARGO_SECRETARIA: {
        "nome": "Secretaria(o)",
        "nivel": 40,
        "permissoes": {
            PERMISSAO_APROVAR_CADASTROS,
            PERMISSAO_ATENDER_SUPORTE,
            PERMISSAO_USAR_BOT,
        },
    },
    CARGO_HELPER: {
        "nome": "Helper",
        "nivel": 30,
        "permissoes": {
            PERMISSAO_ATENDER_SUPORTE,
            PERMISSAO_USAR_BOT,
        },
    },
    CARGO_VENDEDOR: {
        "nome": "Vendedor",
        "nivel": 20,
        "permissoes": {PERMISSAO_USAR_BOT},
    },
    CARGO_TESTER: {
        "nome": "Vendedor(a) Tester",
        "nivel": 20,
        "permissoes": {PERMISSAO_USAR_BOT},
    },
}


_ALIASES = {
    "owner": CARGO_DONO,
    "admin": CARGO_DONO,
    "administrador": CARGO_DONO,
    "manager": CARGO_GERENTE,
    "secretario": CARGO_SECRETARIA,
    "secretaria(o)": CARGO_SECRETARIA,
    "secretária": CARGO_SECRETARIA,
    "secretário": CARGO_SECRETARIA,
    "vendedora": CARGO_VENDEDOR,
    "vendedor(a) tester": CARGO_TESTER,
    "tester": CARGO_TESTER,
}


def normalizar_cargo(cargo, padrao: str = CARGO_VENDEDOR) -> str:
    valor = str(cargo or "").strip().lower().replace(" ", "_")
    valor = _ALIASES.get(str(cargo or "").strip().lower(), valor)
    return valor if valor in CARGOS else padrao


def nome_cargo(cargo) -> str:
    return CARGOS[normalizar_cargo(cargo)]["nome"]


def nivel_cargo(cargo) -> int:
    return int(CARGOS[normalizar_cargo(cargo)]["nivel"])


def cargo_tem_permissao(cargo, permissao: str) -> bool:
    cargo_normalizado = normalizar_cargo(cargo)
    if cargo_normalizado == CARGO_DONO:
        return True
    return permissao in CARGOS[cargo_normalizado]["permissoes"]


def pode_atribuir_cargo(cargo_autor, cargo_novo) -> bool:
    """Dono atribui qualquer cargo; gerente atribui somente cargos inferiores."""
    autor = normalizar_cargo(cargo_autor)
    novo = normalizar_cargo(cargo_novo)
    if autor == CARGO_DONO:
        return True
    if autor == CARGO_GERENTE:
        return nivel_cargo(novo) < nivel_cargo(autor)
    return False


def pode_gerenciar_cargo(cargo_autor, cargo_atual_alvo) -> bool:
    """Impede que um gerente altere outro gerente ou um dono."""
    autor = normalizar_cargo(cargo_autor)
    atual = normalizar_cargo(cargo_atual_alvo)
    if autor == CARGO_DONO:
        return True
    if autor == CARGO_GERENTE:
        return nivel_cargo(atual) < nivel_cargo(autor)
    return False
