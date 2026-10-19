# VintedBot

Bot pessoal que monitoriza pesquisas da Vinted e envia um alerta no Telegram por cada artigo novo.

> ⚠️ Usa a API interna (não oficial) da Vinted (`https://api.vinted.<tld>/svc-catalogue/items`). Os Termos de Serviço proíbem automação: usa com moderação (intervalos ≥ 60 s) e por tua conta e risco. Se a Vinted mudar a API, o bot deixa de funcionar até ser adaptado.

## Setup (Windows)

1. Instalar o Python 3.12: `winget install -e --id Python.Python.3.12`
2. `python -m venv .venv` e `.venv\Scripts\Activate.ps1`
3. `python -m pip install -r requirements.txt`
4. Criar o bot no Telegram com o [@BotFather](https://t.me/BotFather) e copiar o token.
5. `copy .env.example .env` e preencher `TELEGRAM_TOKEN`.
6. `python -m vintedbot.main`, enviar `/id` ao bot, pôr o número em `ALLOWED_CHAT_ID` no `.env` e reiniciar.

## Utilização

1. Na Vinted, faz a pesquisa com os filtros que quiseres (marca, tamanho, preço, estado…).
2. Copia o URL e envia `/add <url> [nome]` ao bot.
3. A partir daí recebes um alerta por cada artigo novo (no máximo 10 por ciclo; o resto vem resumido).

Comandos: `/add`, `/list`, `/pause <id>`, `/resume <id>`, `/remove <id>`, `/status`, `/id`.

**Avaliar preço:** se o [Claude Code](https://claude.com/claude-code) (`claude`) estiver instalado e com sessão iniciada, cada alerta tem um botão «💡 Avaliar preço». O bot pesquisa na Vinted anúncios com o mesmo título e pede ao Claude um veredicto (bom negócio / preço justo / caro) com o intervalo de preço justo. Demora 10–30 s, gasta da tua conta Claude e só funciona para alertas recebidos desde o último arranque do bot. Desliga com `PRICE_CHECK=0` no `.env`.

Para testar a ligação à Vinted sem o Telegram:
`python -m vintedbot.vinted.client "<url da pesquisa>"`

## Testes

`python -m pytest`
