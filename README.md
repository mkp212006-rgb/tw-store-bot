# Bot Telegram TW STORE

Bot com catálogo completo do arquivo enviado: Instagram Seguidores, Curtidas, Visualizações e IPTV Livestream 4K.

## Catálogos incluídos

### Seguidores
100, 200, 250, 500, 700, 900, 1.000, 1.500, 3.000 e 10.000.

### Curtidas
100, 200, 300, 400, 500, 600, 700, 800, 900, 1.000, 2.000, 3.000, 4.000, 5.000 e 10.000.

### Visualizações
100, 200, 300, 400, 500, 600, 700, 800, 900, 1.000, 2.000, 3.000, 4.000, 5.000 e 10.000.

## Como usar

1. Crie um bot no Telegram pelo @BotFather e copie o token.
2. Instale o Python no seu computador ou hospedagem.
3. Abra a pasta do bot e instale as dependências:

```bash
pip install -r requirements.txt
```

4. Renomeie `.env.example` para `.env` e preencha:

```env
TELEGRAM_BOT_TOKEN=seu_token_do_bot
ADMIN_EMAIL=ttwovendas@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=ttwovendas@gmail.com
SMTP_PASSWORD=sua_senha_de_app_do_gmail
```

> Para Gmail, use uma **senha de app**. A senha normal da conta geralmente não funciona para envio SMTP.

5. Rode o bot:

```bash
python bot.py
```

## Notificação por e-mail

Quando a pessoa faz pedido ou envia solicitação de atendimento, o bot envia para `ttwovendas@gmail.com` um resumo com:

- Nome da pessoa
- Username do Telegram
- ID do chat
- Categoria escolhida
- Pacote escolhido
- Valor
- Link/@ enviado
- Comprovante ou observação enviada
