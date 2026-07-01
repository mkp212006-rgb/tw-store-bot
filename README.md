# Bot Telegram TW STORE — Railway + Mercado Pago Pix

Esta versão foi ajustada para gerar **Pix automático pelo Mercado Pago**, receber confirmação por **webhook** e liberar o pedido somente quando o pagamento estiver com status `approved`.

## Arquivos principais

- `bot.py` — código principal do bot + servidor Flask para webhook.
- `catalogo.json` — catálogo de produtos/serviços.
- `requirements.txt` — dependências do Railway.
- `.env.example` — modelo das variáveis que devem ser cadastradas no Railway.

## Fluxo do pagamento automático

1. Cliente entra no bot e escolhe o serviço.
2. Cliente envia o link/@ ou e-mail do pedido.
3. O bot cria uma cobrança Pix no Mercado Pago.
4. O bot envia o Pix copia e cola no Telegram.
5. Cliente paga.
6. Mercado Pago chama a rota `/webhook/mercadopago` no Railway.
7. O bot consulta o pagamento na API do Mercado Pago.
8. Se o status for `approved` e o valor bater, o pedido é liberado.
9. Para Instagram/TikTok, o bot tenta enviar automaticamente para a API da plataforma SMM.


## Como deixar funcionando

1. Suba este projeto no Railway com o start command `python bot.py` ou use o `Procfile` incluído.
2. Em **Railway → Variables**, cadastre as variáveis obrigatórias.
3. Depois do deploy, abra no navegador:

```txt
https://SEU-PROJETO.up.railway.app/health
https://SEU-PROJETO.up.railway.app/webhook/mercadopago
```

As duas URLs devem responder com `ok: true`.

4. No Mercado Pago Developers, cadastre a URL:

```txt
https://SEU-PROJETO.up.railway.app/webhook/mercadopago
```

Evento: **Pagamentos**.

5. Faça um pedido de teste no Telegram. O bot deve gerar Pix copia e cola.
6. Após o pagamento aprovado, o Mercado Pago chama o webhook e o bot processa o pedido.

## Correção importante desta versão

O webhook agora responde rapidamente ao Mercado Pago e processa o pagamento em segundo plano. Isso evita reenvio por timeout, porque o Mercado Pago espera resposta HTTP 200/201 em poucos segundos.

Também foi adicionado controle para não processar o mesmo pagamento duas vezes caso o webhook e o botão **Verificar Pagamento** sejam acionados quase ao mesmo tempo.



## Persistência de cadastros

Esta versão salva os cadastros em arquivo permanente dentro da pasta:

```txt
dados/usuarios_registrados.json
```

Quando o cliente cria cadastro, o registro fica salvo nesse arquivo com o status `pendente`. Quando o admin aprova, o mesmo arquivo é atualizado para `aprovado`. Ao reiniciar o bot, ele lê esse arquivo novamente e o cliente aprovado não precisa refazer o cadastro.

Também foi adicionada persistência do estado interno do bot em:

```txt
dados/bot_persistence.pkl
```

Por padrão, a pasta de dados é `./dados`. Se estiver usando Railway/Render com volume persistente, configure a variável:

```env
DATA_DIR=/caminho/do/volume
```

Importante: se a hospedagem apagar o sistema de arquivos a cada deploy/restart e você não usar volume persistente, qualquer arquivo local também será perdido. Nesse caso, use `DATA_DIR` apontando para o volume persistente da hospedagem.

## Cadastro, segundo admin e painel administrativo

Esta versão também possui bloqueio de acesso antes do cliente usar o bot:

1. O cliente cria usuário e senha pelo botão de cadastro.
2. O cadastro fica pendente.
3. Os administradores configurados para cadastro recebem uma solicitação com botões para aprovar ou negar.
4. Se negar, o cliente só pode tentar novamente após 30 minutos.
5. Usuários banidos pelo Telegram ID não conseguem usar o bot naquela conta.

Agora existem dois níveis de admin:

- `ADMIN_CHAT_ID` — admin principal. Recebe relatórios de venda/pagamento, solicitações de cadastro e pode usar `/painel`.
- `ADMIN2_CHAT_ID` — segundo admin. Não recebe relatórios. Recebe apenas solicitações de cadastro e pode usar `/painel`.

Para gerenciar usuários, os administradores usam apenas:

```txt
/painel
```

No painel existem os botões:

- **Usuários Registrados** — mostra somente usuários aprovados. Usuário banido sai automaticamente dessa lista.
- **Banir ou Desbanir** — permite escolher banir ou desbanir e depois informar o Telegram ID.


### Arquivo `.env` incluído neste pacote

Este pacote também inclui um `.env` e um `.env.example` já adaptados para a versão 1.4.

- Para rodar localmente, edite o arquivo `.env` e coloque seus dados reais.
- Para Railway, copie as mesmas chaves para **Project → Variables**.
- A variável nova da 1.4 é `ADMIN2_CHAT_ID`. Ela libera o segundo admin para aprovar/negar cadastros e acessar `/painel`, mas os relatórios financeiros continuam indo somente para `ADMIN_CHAT_ID`.

## Variáveis obrigatórias no Railway

Cadastre em **Railway → seu projeto → Variables**:

```env
BOT_TOKEN=TOKEN_DO_BOTFATHER
ADMIN_CHAT_ID=SEU_ID_DO_TELEGRAM_PRINCIPAL
ADMIN2_CHAT_ID=ID_DO_SEGUNDO_ADMIN_SE_TIVER
MERCADO_PAGO_ACCESS_TOKEN=APP_USR-xxxxxxxxxxxxxxxx
MP_WEBHOOK_URL=https://SEU-PROJETO.up.railway.app/webhook/mercadopago
```

Não coloque essas chaves diretamente no código.

## Variáveis opcionais

```env
MP_PAYER_EMAIL=cliente@ttwostore.com
MP_API_TIMEOUT=30
MP_WEBHOOK_SECRET=
```

Se você usar `MP_WEBHOOK_SECRET`, configure no Mercado Pago a URL assim:

```txt
https://SEU-PROJETO.up.railway.app/webhook/mercadopago?secret=SUA_SENHA_SECRETA
```

## Webhook no Mercado Pago

No painel do Mercado Pago Developers:

```txt
Sua aplicação
→ Notificações Webhooks
→ Modo de produção
→ URL: https://SEU-PROJETO.up.railway.app/webhook/mercadopago
→ Evento: Pagamentos
→ Salvar
```

Marque somente **Pagamentos**.

## Railway

O código sobe um servidor Flask na porta informada pela variável `PORT` do Railway. As rotas disponíveis são:

```txt
GET  /health
POST /webhook/mercadopago
```

A URL final do webhook será:

```txt
https://SEU-PROJETO.up.railway.app/webhook/mercadopago
```

## API da plataforma SMM

Para Instagram e TikTok, configure também:

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

Também é possível configurar `api_service_id` diretamente no `catalogo.json`. Se existir `api_service_id`, ele tem prioridade.

## Segurança

- Não envie print do `Access Token`.
- Não coloque `.env` no GitHub.
- Gere uma nova key se alguma chave já foi exposta.
- O bot só libera o pedido com `status = approved`.
- O valor recebido é comparado com o valor do pedido antes de liberar.
