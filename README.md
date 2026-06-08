# Bot Telegram TW STORE

Bot criado com todos os catálogos do arquivo e quantidades completas:
100, 200, 300, 400, 500, 600, 700, 800, 900, 1.000, 2.000, 3.000, 4.000 e 5.000.

## Catálogos incluídos

- Seguidores Instagram
- Curtidas Instagram
- Visualizações Instagram
- IPTV Livestream 4K
- Dúvidas Frequentes
- Atendimento

## Como usar

1. Crie um bot no Telegram pelo @BotFather.
2. Copie o token do bot.
3. Instale Python 3.10 ou superior.
4. Instale as dependências:

```bash
pip install -r requirements.txt
```

5. Copie `.env.example` para `.env` e preencha o token:

```bash
cp .env.example .env
```

6. Rode o bot:

```bash
export $(cat .env | xargs)
python bot.py
```

No Windows, você pode configurar as variáveis pelo terminal ou editar o ambiente da hospedagem.

## Notificação no WhatsApp

O bot já está programado para enviar um resumo de cada pedido para:

`55 12 99779-3285`

Para isso funcionar automaticamente, você precisa configurar um serviço de envio de WhatsApp.

### Opção simples: CallMeBot

1. Cadastre seu número no CallMeBot.
2. Pegue sua API key.
3. No `.env`, deixe:

```env
WHATSAPP_PROVIDER=callmebot
CALLMEBOT_APIKEY=SUA_APIKEY
OWNER_WHATSAPP=5512997793285
```

### Opção oficial: WhatsApp Cloud API

Use as variáveis:

```env
WHATSAPP_PROVIDER=cloud
WHATSAPP_CLOUD_TOKEN=SEU_TOKEN
WHATSAPP_PHONE_NUMBER_ID=SEU_PHONE_NUMBER_ID
OWNER_WHATSAPP=5512997793285
```

## Resumo enviado no pedido

Cada pedido envia:

- Nome do cliente
- Usuário do Telegram
- ID do Telegram
- Categoria escolhida
- Pacote escolhido
- Valor
- Link ou @ enviado pelo cliente

Os pedidos também ficam salvos no arquivo `orders.jsonl`.
