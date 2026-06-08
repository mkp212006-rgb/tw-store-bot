# Bot Telegram TW STORE

Este pacote contém um bot de Telegram com todos os catálogos extraídos do arquivo `.allautoresponder`.

## Arquivos

- `bot_twstore.py` — código principal do bot.
- `catalogos.json` — todos os menus, catálogos, pacotes, valores e mensagens.
- `requirements.txt` — dependência necessária.

## Como usar

1. Crie um bot no Telegram pelo BotFather e copie o token.
2. Instale o Python no celular/PC/servidor.
3. Instale as dependências:

```bash
pip install -r requirements.txt
```

4. Configure o token:

No Windows PowerShell:
```powershell
$env:TELEGRAM_BOT_TOKEN="COLE_SEU_TOKEN_AQUI"
python bot_twstore.py
```

No Linux/Termux:
```bash
export TELEGRAM_BOT_TOKEN="COLE_SEU_TOKEN_AQUI"
python bot_twstore.py
```

5. Abra o bot no Telegram e envie `/start`.

## Observação

O bot usa botões para navegar pelos catálogos. O comando `#` também volta ao menu principal.
