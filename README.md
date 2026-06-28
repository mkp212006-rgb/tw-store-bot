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
$env:PIX_CHAVE="ttwovendas@gmail.com"
python bot.py
```

No Linux/Termux:

```bash
export BOT_TOKEN="SEU_TOKEN_AQUI"
export ADMIN_CHAT_ID="SEU_ID_DO_TELEGRAM_AQUI"
export PIX_CHAVE="ttwovendas@gmail.com"
python bot.py
```

`PIX_CHAVE` é opcional. Se não configurar, o bot usa `ttwovendas@gmail.com`.

## Como funciona

- O cliente entra em `/start`.
- Escolhe catálogo, serviço e quantidade.
- O bot pede link ou @.
- Depois do link/@, o bot abre a aba de pagamento com Pix e o valor correto do `catalogo.json`.
- O cliente toca em **Confirmar pagamento e enviar pedido** ou digita `1`.
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

## Envio automático para a plataforma API

Esta versão também envia automaticamente pedidos dos catálogos **Instagram** e **TikTok** para a plataforma quando o cliente confirmar o pagamento.

Fluxo atualizado:

1. Cliente escolhe Instagram ou TikTok.
2. Cliente escolhe serviço e pacote.
3. Cliente envia link/@.
4. Bot mostra pagamento.
5. Cliente envia comprovante.
6. Cliente toca em **Confirmar pagamento e enviar pedido**.
7. O bot chama a API da plataforma com `action=add`.
8. O relatório enviado ao administrador mostra se o pedido foi enviado e o ID retornado pela plataforma.

Configure no `.env`:

```env
PANEL_API_URL=https://sua-plataforma.com/api/v2
PANEL_API_KEY=SUA_KEY_NOVA_AQUI
PANEL_API_TIMEOUT=30

PANEL_SERVICE_ID_INSTAGRAM_SEGUIDORES=ID_REAL
PANEL_SERVICE_ID_INSTAGRAM_CURTIDAS=ID_REAL
PANEL_SERVICE_ID_INSTAGRAM_VISUALIZACOES=ID_REAL
PANEL_SERVICE_ID_TIKTOK_SEGUIDORES=ID_REAL
PANEL_SERVICE_ID_TIKTOK_CURTIDAS=ID_REAL
PANEL_SERVICE_ID_TIKTOK_VISUALIZACOES=ID_REAL
```

Também é possível configurar diretamente no `catalogo.json`, dentro de cada serviço de Instagram/TikTok:

```json
"api_service_id": "ID_REAL_DA_PLATAFORMA"
```

Se existir `api_service_id` no `catalogo.json`, ele tem prioridade sobre as variáveis `PANEL_SERVICE_ID_...` do `.env`.

### Atenção sobre segurança

Não coloque a API key direto dentro do `bot.py`. Use sempre o `.env`. Se a key já foi enviada em conversa ou print, gere outra key na plataforma antes de usar em produção.
