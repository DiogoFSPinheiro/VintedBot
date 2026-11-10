# VintedBot

Bot Telegram que monitoriza pesquisas da Vinted. Código e comentários em português.

## Comandos
- `.venv/Scripts/python.exe -m pytest -q` - testes (usar o venv; o `python` global não tem `curl_cffi`)
- `.venv/Scripts/python.exe -m vintedbot.vinted.client "<url de pesquisa vinted>"` - smoke test real contra a Vinted
- `VintedBot.cmd` - arranca o bot (cria o venv na 1.ª vez; precisa de `.env`)

## API para a Wintermute (`vintedbot/api.py`)
- `python -m vintedbot.api listar|criar --texto=…|pausar|retomar|apagar --id=N`, no diretório do bot: uma linha de JSON (`{"erro"}` + código 1 quando falha). É por aqui que a Wintermute escreve nas pesquisas; não mudar o formato sem mudar o `vinted.py` dela
- Cria pesquisas em vinted.pt só com texto e preços; ficam por "primar" (o `Monitor` não alerta os artigos que já lá estavam)

## API da Vinted (não oficial, muda sem aviso)
- Pesquisa: `GET https://api.<domínio sem www>/svc-catalogue/items`, com os cookies obtidos ao pedir `https://www.<domínio>/`
- A gateway precisa do header `Locale: <cookie anonymous-iso-locale>` (ex.: pt-PT); sem ele os textos vêm em francês
- País do vendedor: `GET https://www.<domínio>/api/v2/users/<id>` (`country_title_local`, `country_iso_code`)
- Se todas as pesquisas derem 404, o endpoint mudou: ver no bundle JS da página `/catalog` os caminhos `svc-catalogue` e o `baseURL` da gateway
- Endpoints antigos que já dão 404: `/api/v2/catalog/items`, `/web/gateway/svc-catalogue/items`
- 401/403 = token expirado (o cliente limpa os cookies e repete); 403/429 persistentes = bloqueio anti-bot

## Avaliação de preços (`vintedbot/pricing.py`)
- Corre `claude -p --output-format json --json-schema ...` com o prompt no stdin; a resposta vem em `structured_output`
- Corre numa thread (`asyncio.to_thread` + `subprocess.run`): o event loop Selector do Windows não suporta subprocessos asyncio
- Pesquisa web nas lojas (preço novo / usado em loja) é obrigatória no prompt; os resultados do WebSearch variam entre corridas, `WebFetch` não trouxe ganhos
- `--bare` não serve (exige ANTHROPIC_API_KEY); para tornar a chamada leve usa-se `--tools WebSearch --strict-mcp-config --setting-sources ""`

## Testes
- `tests/fakes.py` (`FakeSession`/`FakeResponse`) simula o HTTP; os testes verificam os URLs exatos chamados
