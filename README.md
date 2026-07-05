# Bot Telegram TW STORE — versão 1.6

Versão com Mercado Pago Pix, webhook persistente, cadastro com usuário/senha + aprovação, painel admin ampliado e banco SQLite.

## Arquivos principais

- `bot.py` — arquivo principal do bot e servidor Flask.
- `database.py` — camada SQLite para cadastros, pedidos, pagamentos, histórico e fila de webhook.
- `validators.py` — validação de Instagram, TikTok e e-mail.
- `catalogo.json` — catálogo de serviços.
- `.env.example` — modelo das variáveis de ambiente.
- `MELHORIAS_1.6.txt` — resumo das alterações feitas.

## Banco de dados

A partir desta versão, os dados de execução ficam em SQLite:

```txt
dados/bot.sqlite3
```

Por padrão:

```env
DATA_DIR=dados
DATABASE_PATH=dados/bot.sqlite3
```

Se existirem JSONs antigos em `dados/`, o bot tenta migrar automaticamente para o SQLite na primeira inicialização.

## Cadastro

O cadastro continua usando usuário e senha:

1. O cliente toca em **Solicitar acesso**.
2. O bot pede usuário e senha na mesma mensagem.
3. A senha é salva apenas como hash com salt, não em texto puro.
4. O bot tenta apagar a mensagem original do cliente para reduzir exposição da senha.
5. O admin recebe nome, @username, Telegram ID e usuário escolhido para aprovar ou negar.
6. O cliente aprovado usa o bot normalmente.

## Painel administrativo

Comando:

```txt
/painel
```

Opções disponíveis:

- Resumo do bot.
- Últimos pedidos.
- Cadastros pendentes.
- Usuários registrados.
- Pagamentos pendentes.
- Buscar usuário.
- Banir ou desbanir.

## Webhook Mercado Pago

Rotas:

```txt
GET  /health
GET  /webhook/mercadopago
POST /webhook/mercadopago
```

O webhook agora grava o `payment_id` em fila SQLite antes de responder ao Mercado Pago. Isso reduz risco de perder pagamento caso o bot reinicie ou falhe durante o processamento.

Variáveis novas:

```env
WEBHOOK_QUEUE_INTERVAL=45
WEBHOOK_QUEUE_MAX_ATTEMPTS=8
```

## Validação de dados do pedido

Antes de gerar pagamento, o bot valida:

- Instagram: `@usuario` ou link `instagram.com/...`
- TikTok: `@usuario`, `tiktok.com/...`, `vm.tiktok.com/...` ou `vt.tiktok.com/...`
- IPTV/Internet: e-mail válido.

## Variáveis obrigatórias

Copie `.env.example` para `.env` localmente ou cadastre no Railway:

```env
BOT_TOKEN=
ADMIN_CHAT_ID=
ADMIN2_CHAT_ID=
MERCADO_PAGO_ACCESS_TOKEN=
MP_WEBHOOK_URL=
PANEL_API_URL=
PANEL_API_KEY=
```

Observação: `ADMIN2_CHAT_ID` também recebe o relatório semanal automático. Os relatórios individuais de venda/pagamento, inclusive pedidos em `revisao_manual`, são enviados somente ao `ADMIN_CHAT_ID`.

## Segurança

Por solicitação do usuário, o `.env` real foi mantido neste pacote. Não publique este ZIP em GitHub, grupos, prints ou hospedagens públicas.

## Rodando localmente

```bash
pip install -r requirements.txt
python bot.py
```

No Railway, use o `Procfile` já incluído:

```txt
web: python bot.py
```

## Revisão manual com botões

Quando um pedido pago cair em `revisao_manual`, o relatório enviado ao `ADMIN_CHAT_ID` agora mostra botões de ação:

- `✅ Já foi feito`: marca o pedido como resolvido/enviado no histórico, sem reenviar para a plataforma.
- `🔁 Reenviar para plataforma`: tenta enviar novamente pela API somente após ação manual do admin principal.
- `❌ Ignorar pendência`: fecha a pendência sem reenviar e salva no histórico como `ignorado_manual`.

Essas ações evitam que o Railway reenvie o mesmo pedido depois de restart/redeploy. O `ADMIN2_CHAT_ID` não recebe relatório individual de revisão manual.
