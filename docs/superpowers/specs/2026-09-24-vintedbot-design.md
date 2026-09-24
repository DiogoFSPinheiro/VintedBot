# VintedBot — Design

## Contexto
Repo vazio (só README). Objetivo: um bot pessoal que monitoriza pesquisas da Vinted e envia um alerta no Telegram assim que aparece um artigo novo que cumpra os filtros, para apanhar pechinchas primeiro. A compra é sempre manual (a compra automática fica de fora por risco de ban).

**Decisões do utilizador:** alertas de artigos novos · Telegram · correr no PC Windows (mais tarde num Pi/servidor) · pesquisas geridas colando o URL da Vinted · Python.

**Viabilidade:** a Vinted não tem API pública, mas o site usa `GET https://www.vinted.<tld>/web/gateway/svc-catalogue/items` (JSON; filtros em `attribute_ids[brand|size|status|catalog|…]`), autenticado com o cookie de sessão anónimo (`access_token_web`) obtido ao pedir a homepage. (Atualizado na implementação: o antigo `/api/v2/catalog/items` devolve 404.) Risco: os ToS proíbem scraping; há anti-bot (Cloudflare/Datadome → 403/429). Mitigação: poucos pedidos (intervalo ≥ 60–120 s por pesquisa, com jitter), impressão TLS de browser (`curl_cffi`), IP residencial e backoff.

## Arquitetura (Python 3.12, asyncio, um só processo)

```
vintedbot/
  config.py        # .env: TELEGRAM_TOKEN, ALLOWED_CHAT_ID, VINTED_DOMAIN, POLL_INTERVAL
  vinted/
    client.py      # sessão curl_cffi (impersonate="chrome"), obtém/renova cookie, GET catalog/items, trata 401/403/429
    url_parser.py  # URL de pesquisa da Vinted -> params da API (search_text, catalog[]->catalog_ids, brand_ids, size_ids, price_from/to, status_ids, order=newest_first)
    models.py      # dataclass Item (id, title, price, currency, size, brand, url, photo_url, created_ts)
  storage.py       # SQLite: searches(id, chat_id, name, url, params_json, active), seen_items(search_id, item_id)
  monitor.py       # loop: para cada pesquisa ativa -> fetch -> filtra os não vistos -> notifica -> marca como vistos
  telegram_bot.py  # python-telegram-bot v21: /add <url> [nome], /list, /remove <id>, /pause, /resume; envia sendPhoto com legenda + botão "Abrir"
  main.py          # arranca o bot Telegram e o monitor (JobQueue) no mesmo event loop
tests/
```

## Fluxo de dados
1. `/add <url>` → `url_parser` valida e converte → grava em `searches` → **primeira execução "silenciosa"**: marca todos os resultados atuais como vistos (sem spam inicial).
2. JobQueue a cada `POLL_INTERVAL` (+ jitter) → `client.search(params)` → itens ordenados `newest_first` → os que não estão em `seen_items` → mensagem Telegram (foto, título, preço, tamanho, marca, link) → insere em `seen_items`.
3. Pesquisas processadas sequencialmente, com uma pausa curta entre elas (para não rebentar o rate limit).

## Tratamento de erros
- 401 ou cookie expirado → renovar a sessão (GET à homepage) e repetir uma vez.
- 403/429 → backoff exponencial (até ~15 min) e aviso no Telegram se persistir.
- Erros de rede ou de JSON → log e continuar no ciclo seguinte; o bot nunca morre.
- Só o `ALLOWED_CHAT_ID` pode usar comandos.
- Limpeza periódica de `seen_items` com mais de 30 dias.

## Dependências
`curl_cffi`, `python-telegram-bot[job-queue]`, `python-dotenv`, `pytest`, `pytest-asyncio`. SQLite através de `sqlite3` (stdlib).

## Testes
- `url_parser`: URLs reais da Vinted → params esperados (pure functions, TDD).
- `storage`: SQLite em memória (dedup, primeira execução silenciosa).
- `monitor`: client e notifier falsos → só notifica itens novos.
- `client`: parsing a partir de uma fixture JSON gravada; sem chamadas reais nos testes unitários.

## Verificação end-to-end
1. `python -m vintedbot.vinted.client "<url>"` (smoke script) → imprime os 5 artigos mais recentes (confirma que o cookie e a API funcionam).
2. Correr `python -m vintedbot.main`, fazer `/add <url de pesquisa ampla>` no Telegram, confirmar que não há spam inicial e que chega um alerta quando surge um artigo novo (pesquisa popular, ~minutos).
3. `pytest` verde.

## Próximos passos após aprovação
1. Escrever esta spec em `docs/superpowers/specs/2026-09-24-vintedbot-design.md` e fazer commit.
2. O utilizador revê a spec.
3. Skill writing-plans → plano de implementação detalhado (TDD).

## Fora de âmbito (YAGNI)
Compra ou ofertas automáticas, proxies, várias contas, dashboard web, análise de preços.
