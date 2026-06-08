# Bot Telegram TW STORE

Este pacote cria um bot no Telegram com:

- Menu principal TW STORE
- Catálogo de Seguidores Instagram
- Catálogo de Curtidas Instagram
- Catálogo de Visualizações Instagram
- Todos os catálogos com as quantidades: 100, 200, 300, 400, 500, 600, 700, 800, 900, 1.000, 2.000, 3.000, 4.000, 5.000 e 10.000
- Fluxo completo de pedido: serviço, quantidade, link/@, contato, observação e confirmação
- Resumo automático do pedido para WhatsApp configurável

## Valores usados

Seguidores: custo de R$ 1,18 a cada 1.000.  
Curtidas: custo de R$ 0,38 a cada 1.000.  
Visualizações: custo de R$ 0,02 a cada 1.000.  

O preço de venda foi calculado para gerar um lucro pequeno acima do custo, com mínimo comercial de R$ 0,50 quando o custo é muito baixo.

## Como instalar

1. Instale Python 3.10 ou superior.
2. Entre na pasta do bot.
3. Instale as dependências:

```bash
pip install -r requirements.txt
```

4. Copie `.env.example` para `.env` e preencha:

```bash
cp .env.example .env
```

5. No Telegram, fale com @BotFather, crie um bot e cole o token no campo `TELEGRAM_BOT_TOKEN`.

6. Para receber no WhatsApp automaticamente, use uma API. Este pacote já vem preparado para CallMeBot:
   - Cadastre seu número no CallMeBot.
   - Pegue sua API key.
   - Coloque em `CALLMEBOT_APIKEY`.

7. Rode o bot:

```bash
python main.py
```

## Observação importante sobre WhatsApp

O Telegram não consegue enviar mensagens para WhatsApp sozinho. Para o envio automático funcionar, é obrigatório usar uma API externa, como CallMeBot, Z-API, Evolution API, Twilio ou WhatsApp Business Cloud API.

O número configurado para receber resumo é: 12 99779-3285.
