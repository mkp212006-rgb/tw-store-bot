# Bot Telegram TW STORE

Projeto criado a partir do arquivo `.allautoresponder` enviado.

## Arquivos

- `bot.py` — código principal do bot.
- `catalogo.json` — catálogo separado e organizado.
- `requirements.txt` — dependência do projeto.

## Como configurar

1. Crie um bot no Telegram pelo **@BotFather**.
2. Copie o token do bot.
3. Descubra seu ID do Telegram. Uma forma simples é falar com **@userinfobot**.
4. Instale as dependências:

```bash
pip install -r requirements.txt
```

5. Configure as variáveis:

No Windows PowerShell:

```powershell
$env:BOT_TOKEN="SEU_TOKEN_AQUI"
$env:ADMIN_CHAT_ID="SEU_ID_DO_TELEGRAM_AQUI"
python bot.py
```

No Linux/Termux:

```bash
export BOT_TOKEN="SEU_TOKEN_AQUI"
export ADMIN_CHAT_ID="SEU_ID_DO_TELEGRAM_AQUI"
python bot.py
```

## Como funciona

- O cliente entra em `/start`.
- Escolhe catálogo, serviço e quantidade.
- O bot pede link ou @.
- O cliente confirma.
- O bot envia um relatório para o Telegram do administrador com:
  - catálogo
  - serviço
  - quantidade
  - valor
  - link/@
  - nome, username e ID do cliente

## Observação importante

No arquivo original, Curtidas e Visualizações já tinham todas as quantidades solicitadas.
Em Seguidores, algumas quantidades pedidas não existiam no arquivo original: 300, 400, 600, 800, 2.000, 4.000 e 5.000.
Essas foram incluídas no `catalogo.json` com valor proporcional calculado com base nos valores existentes do próprio arquivo.
