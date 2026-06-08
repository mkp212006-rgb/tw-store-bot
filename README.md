# Bot Telegram — TW STORE

Arquivos principais:
- `bot.py`: código do bot Telegram.
- `catalogo.json`: catálogos, valores, mensagens e passo a passo separados para organização.
- `.env.example`: modelo para colocar sua API key do Telegram e seu chat ID.
- `requirements.txt`: dependências.

## Como configurar

1. Crie um bot no Telegram pelo @BotFather e copie o token/API key.
2. Descubra seu `OWNER_CHAT_ID` usando um bot como @userinfobot ou enviando mensagem ao seu bot e consultando logs.
3. Renomeie `.env.example` para `.env` ou configure as variáveis no painel de hospedagem.
4. Instale as dependências:

```bash
pip install -r requirements.txt
```

5. Execute:

```bash
BOT_TOKEN="SEU_TOKEN" OWNER_CHAT_ID="SEU_CHAT_ID" python bot.py
```

## Fluxo incluído

O bot mantém o passo a passo do arquivo:
1. Escolha do serviço.
2. Envio do link ou @.
3. Conferência.
4. Dados de pagamento Pix.
5. Envio do comprovante.
6. Confirmação e envio de resumo para o dono pelo Telegram.

## Observação importante

No arquivo original, Curtidas e Visualizações já tinham todas as quantidades pedidas. Em Seguidores, algumas quantidades não existiam no arquivo; elas foram incluídas no `catalogo.json` com valor proporcional e marcadas com `valor_observacao`.
