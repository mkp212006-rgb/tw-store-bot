# Bot Telegram TW STORE — Versão Profissional

Bot de vendas digitais com catálogo, pagamento Pix, consulta de pedido, reposição/refil e painel administrativo básico.

## O que esta versão entrega

- Menu inicial mais limpo e profissional.
- Catálogo organizado por categorias.
- Cliente escolhe serviço, digita quantidade, envia @/link/e-mail e recebe a tela de pagamento.
- Pagamento Pix automático com botão para copiar o Pix.
- Consulta de pedido pelo ID do bot ou ID da plataforma.
- Solicitação de reposição/refil quando o pedido possui ID da plataforma.
- Relatório automático para o administrador quando o pedido é aprovado.
- Comando `/admin` com resumo de pendentes, histórico e total semanal.
- Validação simples de e-mail, @ e links antes de gerar pagamento.

## Arquivos principais

- `bot.py` — código principal do bot e servidor Flask para webhook.
- `catalogo.json` — catálogo, textos do menu, serviços, quantidades e valores.
- `env.txt` — dados de configuração informados no arquivo original.
- `Procfile` — comando de inicialização para deploy.
- `requirements.txt` — dependências do projeto.
- `runtime.txt` — versão do Python.

## Como rodar

1. Instale as dependências:

```bash
pip install -r requirements.txt
```

2. Configure as variáveis necessárias no ambiente ou no arquivo `.env`.

3. Inicie o bot:

```bash
python bot.py
```

## Fluxo do cliente

1. `/start`
2. Comprar serviço
3. Escolher categoria
4. Escolher serviço
5. Digitar quantidade disponível
6. Enviar @, link ou e-mail
7. Copiar Pix e pagar
8. Consultar pedido pelo ID

## Comandos

- `/start` — abre o menu principal.
- `/admin` — abre o painel administrativo para o administrador configurado.

## Observação

Os produtos, valores, quantidades e configurações informadas no arquivo original foram mantidos. As alterações foram focadas em apresentação, fluxo, textos, validação básica e organização para uso profissional.
