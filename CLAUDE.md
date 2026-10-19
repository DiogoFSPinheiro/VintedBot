# VintedBot

Bot Telegram que monitoriza pesquisas da Vinted. Código e comentários em português.

## Comandos
- `.venv/Scripts/python.exe -m pytest -q` - testes (usar o venv; o `python` global não tem `curl_cffi`)
- `.venv/Scripts/python.exe -m vintedbot.vinted.client "<url de pesquisa vinted>"` - smoke test real contra a Vinted
- `VintedBot.cmd` - arranca o bot (cria o venv na 1.ª vez; precisa de `.env`)

## API da Vinted (não oficial, muda sem aviso)
- Pesquisa: `GET https://api.<domínio sem www>/svc-catalogue/items`, com os cookies obtidos ao pedir `https://www.<domínio>/`
- Se todas as pesquisas derem 404, o endpoint mudou: ver no bundle JS da página `/catalog` os caminhos `svc-catalogue` e o `baseURL` da gateway
- Endpoints antigos que já dão 404: `/api/v2/catalog/items`, `/web/gateway/svc-catalogue/items`
- 401/403 = token expirado (o cliente limpa os cookies e repete); 403/429 persistentes = bloqueio anti-bot

## Testes
- `tests/fakes.py` (`FakeSession`/`FakeResponse`) simula o HTTP; os testes verificam os URLs exatos chamados
