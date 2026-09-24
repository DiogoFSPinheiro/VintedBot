# VintedBot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bot pessoal que monitoriza pesquisas da Vinted (coladas como URL no Telegram) e envia um alerta no Telegram por cada artigo novo.

**Architecture:** Um processo Python asyncio. `vinted/` fala com a API interna da Vinted (via `curl_cffi`, a imitar o Chrome). `storage.py` guarda as pesquisas e os artigos vistos em SQLite. `monitor.py` decide o que é novo e trata o backoff. `commands.py` tem a lógica dos comandos, sem dependências do Telegram. `telegram_bot.py` liga tudo ao `python-telegram-bot` (handlers + JobQueue).

**Tech Stack:** Python 3.12, curl_cffi, python-telegram-bot[job-queue] v21+, python-dotenv, sqlite3 (stdlib), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-24-vintedbot-design.md`

## Global Constraints

- Python 3.12. Sistema operativo alvo: Windows 11 (PowerShell). Os comandos abaixo assumem que o venv `.venv` está ativo.
- Intervalo de polling mínimo: 60 s (default 120 s), mais um jitter aleatório de até 25 % (máx. 30 s).
- Pesquisas processadas sequencialmente, com uma pausa de 3 s entre elas.
- 401 → renovar a sessão (GET à homepage) e repetir uma vez. 403/429 → backoff exponencial: 60 s, que duplica até ao máximo de 900 s (15 min).
- Aviso no Telegram após 3 bloqueios seguidos (uma só vez) e mensagem quando a Vinted volta a responder.
- Máximo de 10 alertas por pesquisa por ciclo; o excedente é resumido numa só mensagem.
- Primeira verificação de uma pesquisa é silenciosa (marca tudo como visto).
- Só o `ALLOWED_CHAT_ID` pode usar comandos; `/id` é livre (serve para descobrir o chat id).
- Os `seen_items` com mais de 30 dias são apagados uma vez por dia.
- Os testes unitários nunca fazem pedidos reais à Vinted nem ao Telegram.
- Textos para o utilizador em português (PT-PT).
- Mensagens de commit terminam com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Desvio face à spec: `VINTED_DOMAIN` não existe em config. O domínio vem do URL colado, por isso funciona com vinted.pt, .fr, .es, etc. `Item.created_ts` também foi omitido (YAGNI).

## Review Focus

1. **URL errado colado no `/add`** (página de artigo, outro site, `vinted.pt` sem `www`, `[]` codificado como `%5B%5D`): mensagem de erro clara ou normalização, sem gravar lixo. Testes na Task 2 e na Task 6.
2. **PC acorda de suspensão e há dezenas de artigos novos:** no máximo 10 alertas + 1 resumo, sem flood nem rate limit do Telegram. Teste na Task 5.
3. **Artigo sem foto, foto rejeitada pelo Telegram, ou título com `<`/`&`:** o alerta chega na mesma, com o texto escapado. Testes na Task 7.
4. **Artigo que continua na pesquisa há mais de 30 dias:** não volta a ser alertado depois da limpeza, porque o `seen_at` é renovado a cada ciclo. Testes na Task 3 e na Task 5.
5. **Vinted a bloquear durante horas:** exatamente um aviso, sem spam, e uma mensagem de recuperação. Teste na Task 5.

---

## File Structure

```
pyproject.toml            # só a configuração do pytest
requirements.txt
.gitignore
.env.example
README.md
vintedbot/
  __init__.py
  config.py               # Settings + load_settings()
  storage.py              # Storage (SQLite), dataclass Search
  monitor.py              # Monitor: check_search, run_cycle, backoff
  commands.py             # Commands: add/list/remove/set_active -> texto de resposta
  telegram_bot.py         # format_caption, TelegramNotifier, build_application
  main.py                 # entrypoint
  vinted/
    __init__.py
    models.py             # dataclass Item + Item.from_api
    url_parser.py         # SearchQuery, InvalidSearchUrl, parse_search_url
    client.py             # VintedClient, VintedError, VintedBlockedError, smoke CLI
tests/
  __init__.py
  fakes.py                # make_item, FakeSession/Response, FakeClient, FakeNotifier, FakeMonitor, FakeBot
  fixtures/catalog_items.json
  test_models.py  test_url_parser.py  test_storage.py  test_client.py
  test_monitor.py test_commands.py    test_config.py   test_telegram_bot.py
```

---

### Task 1: Setup do projeto + modelo `Item`

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.gitignore`, `.env.example`, `vintedbot/__init__.py`, `vintedbot/vinted/__init__.py`, `vintedbot/vinted/models.py`, `tests/__init__.py`, `tests/fakes.py`, `tests/fixtures/catalog_items.json`, `tests/test_models.py`

**Interfaces:**
- Produces: `vintedbot.vinted.models.Item(id: int, title: str, price: str, currency: str, size: str, brand: str, url: str, photo_url: str | None)`, frozen; `Item.from_api(data: dict) -> Item`; `tests.fakes.make_item(item_id: int, **overrides) -> Item`.

- [ ] **Step 1: Instalar o Python 3.12 (não está instalado nesta máquina)**

Run (PowerShell): `winget install -e --id Python.Python.3.12`
Depois abrir um terminal novo e correr `python --version` → `Python 3.12.x`.
Se o `python` abrir a Microsoft Store, desativar o alias em Definições → Aplicações → Definições avançadas → Aliases de execução de aplicações.

- [ ] **Step 2: Criar o venv e os ficheiros de setup**

`requirements.txt`:
```
curl_cffi>=0.7
python-telegram-bot[job-queue]>=21.0,<23
python-dotenv>=1.0
pytest>=8.0
pytest-asyncio>=0.23
```

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
testpaths = ["tests"]
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.env
*.db
.pytest_cache/
```

`.env.example`:
```
# Token do @BotFather
TELEGRAM_TOKEN=
# O teu chat id (envia /id ao bot para o descobrir)
ALLOWED_CHAT_ID=
# Segundos entre ciclos (mínimo 60)
POLL_INTERVAL=120
DB_PATH=vintedbot.db
```

Os ficheiros `vintedbot/__init__.py`, `vintedbot/vinted/__init__.py` e `tests/__init__.py` ficam vazios.

Run:
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```
Expected: instalação sem erros.

- [ ] **Step 3: Criar a fixture e o teste do modelo (a falhar)**

`tests/fixtures/catalog_items.json`:
```json
{
  "items": [
    {
      "id": 5001,
      "title": "Sapatilhas Nike Air <novo> & bonito",
      "price": {"amount": "25.0", "currency_code": "EUR"},
      "brand_title": "Nike",
      "size_title": "42",
      "url": "https://www.vinted.pt/items/5001-sapatilhas",
      "photo": {"url": "https://images1.vinted.net/t/5001.jpeg"}
    },
    {
      "id": 5000,
      "title": "Casaco",
      "price": "12.5",
      "currency": "EUR",
      "brand_title": "",
      "size_title": "M",
      "url": "https://www.vinted.pt/items/5000-casaco",
      "photo": null
    }
  ],
  "pagination": {"current_page": 1}
}
```

`tests/fakes.py`:
```python
from vintedbot.vinted.models import Item


def make_item(item_id: int, **overrides) -> Item:
    fields = dict(
        id=item_id,
        title=f"Item {item_id}",
        price="10.0",
        currency="EUR",
        size="M",
        brand="Nike",
        url=f"https://www.vinted.pt/items/{item_id}",
        photo_url=None,
    )
    fields.update(overrides)
    return Item(**fields)
```

`tests/test_models.py`:
```python
import json
from pathlib import Path

from vintedbot.vinted.models import Item

FIXTURE = Path(__file__).parent / "fixtures" / "catalog_items.json"


def _raw_items():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]


def test_from_api_with_price_object():
    item = Item.from_api(_raw_items()[0])
    assert item == Item(
        id=5001,
        title="Sapatilhas Nike Air <novo> & bonito",
        price="25.0",
        currency="EUR",
        size="42",
        brand="Nike",
        url="https://www.vinted.pt/items/5001-sapatilhas",
        photo_url="https://images1.vinted.net/t/5001.jpeg",
    )


def test_from_api_with_legacy_price_and_no_photo():
    item = Item.from_api(_raw_items()[1])
    assert item.price == "12.5"
    assert item.currency == "EUR"
    assert item.brand == ""
    assert item.photo_url is None


def test_from_api_tolerates_missing_optional_fields():
    item = Item.from_api({"id": "7"})
    assert item.id == 7
    assert item.title == ""
    assert item.price == ""
    assert item.photo_url is None
```

- [ ] **Step 4: Correr o teste e confirmar que falha**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'vintedbot.vinted.models'`.

- [ ] **Step 5: Implementar `vintedbot/vinted/models.py`**

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    id: int
    title: str
    price: str
    currency: str
    size: str
    brand: str
    url: str
    photo_url: str | None

    @classmethod
    def from_api(cls, data: dict) -> Item:
        price = data.get("price")
        if isinstance(price, dict):
            amount = str(price.get("amount") or "")
            currency = price.get("currency_code") or ""
        else:
            amount = str(price or "")
            currency = data.get("currency") or ""
        photo = data.get("photo") or {}
        return cls(
            id=int(data["id"]),
            title=data.get("title") or "",
            price=amount,
            currency=currency,
            size=data.get("size_title") or "",
            brand=data.get("brand_title") or "",
            url=data.get("url") or "",
            photo_url=photo.get("url"),
        )
```

- [ ] **Step 6: Correr os testes e confirmar que passam**

Run: `python -m pytest tests/test_models.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```powershell
git add .gitignore .env.example requirements.txt pyproject.toml vintedbot tests
git commit -m "feat: project scaffold and Item model"
```

---

### Task 2: Parser de URLs de pesquisa

**Files:**
- Create: `vintedbot/vinted/url_parser.py`, `tests/test_url_parser.py`

**Interfaces:**
- Produces: `SearchQuery(domain: str, params: dict[str, str])` (frozen dataclass); `InvalidSearchUrl(ValueError)`, cuja mensagem é mostrada ao utilizador; `parse_search_url(url: str) -> SearchQuery`. O `domain` inclui sempre `www.` e `params["order"]` é sempre `"newest_first"`.

- [ ] **Step 1: Escrever os testes (a falhar)**

`tests/test_url_parser.py`:
```python
import pytest

from vintedbot.vinted.url_parser import InvalidSearchUrl, SearchQuery, parse_search_url


def test_full_search_url_maps_to_api_params():
    q = parse_search_url(
        "https://www.vinted.pt/catalog?search_text=nike%20air&catalog[]=1206"
        "&brand_ids[]=53&brand_ids[]=14&size_ids[]=207&price_from=5&price_to=30"
        "&currency=EUR&status_ids[]=6&order=relevance&time=1727180000&page=2"
    )
    assert q == SearchQuery(
        domain="www.vinted.pt",
        params={
            "search_text": "nike air",
            "catalog_ids": "1206",
            "brand_ids": "53,14",
            "size_ids": "207",
            "price_from": "5",
            "price_to": "30",
            "currency": "EUR",
            "status_ids": "6",
            "order": "newest_first",
        },
    )


def test_url_encoded_brackets_are_understood():
    q = parse_search_url("https://www.vinted.fr/catalog?brand_ids%5B%5D=53&catalog%5B%5D=5")
    assert q.domain == "www.vinted.fr"
    assert q.params["brand_ids"] == "53"
    assert q.params["catalog_ids"] == "5"


def test_category_path_sets_catalog_ids():
    q = parse_search_url("https://www.vinted.pt/catalog/1206-men?search_text=casaco")
    assert q.params["catalog_ids"] == "1206"
    assert q.params["search_text"] == "casaco"


def test_host_without_www_is_normalised_and_multi_part_tld_accepted():
    assert parse_search_url("https://vinted.pt/catalog?search_text=x").domain == "www.vinted.pt"
    assert parse_search_url("https://www.vinted.co.uk/catalog?search_text=x").domain == "www.vinted.co.uk"


def test_whitespace_around_url_is_ignored():
    assert parse_search_url("  https://www.vinted.pt/catalog?search_text=x \n").params["search_text"] == "x"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.olx.pt/catalog?search_text=x",
        "https://www.vinted.pt.evil.com/catalog?search_text=x",
        "ftp://www.vinted.pt/catalog",
        "nike air",
    ],
)
def test_non_vinted_urls_are_rejected(url):
    with pytest.raises(InvalidSearchUrl, match="Vinted"):
        parse_search_url(url)


@pytest.mark.parametrize(
    "url",
    ["https://www.vinted.pt/items/123-casaco", "https://www.vinted.pt/member/99-joana"],
)
def test_non_search_pages_are_rejected(url):
    with pytest.raises(InvalidSearchUrl, match="pesquisa"):
        parse_search_url(url)
```

- [ ] **Step 2: Correr e confirmar que falha**

Run: `python -m pytest tests/test_url_parser.py -v`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `vintedbot/vinted/url_parser.py`**

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

_HOST_RE = re.compile(r"(?:www\.)?vinted\.[a-z]{2,3}(?:\.[a-z]{2})?")
_PATH_RE = re.compile(r"/catalog(?:/(\d+)(?:-[^/]*)?)?/?")
_IGNORED = {"page", "per_page", "order", "time", "search_id", "disabled_personalization"}
_RENAMES = {"catalog": "catalog_ids"}


class InvalidSearchUrl(ValueError):
    pass


@dataclass(frozen=True)
class SearchQuery:
    domain: str
    params: dict[str, str]


def parse_search_url(url: str) -> SearchQuery:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not _HOST_RE.fullmatch(host):
        raise InvalidSearchUrl("Isto não é um URL da Vinted.")
    path_match = _PATH_RE.fullmatch(parts.path)
    if not path_match:
        raise InvalidSearchUrl("Cola o URL de uma pesquisa (página /catalog), não de um artigo ou perfil.")
    if not host.startswith("www."):
        host = "www." + host

    lists: dict[str, list[str]] = {}
    params: dict[str, str] = {}
    for key, value in parse_qsl(parts.query):
        if key.endswith("[]"):
            base = key[:-2]
            lists.setdefault(_RENAMES.get(base, base), []).append(value)
        elif key not in _IGNORED:
            params[key] = value
    if path_match.group(1) and "catalog_ids" not in lists:
        lists["catalog_ids"] = [path_match.group(1)]
    for key, values in lists.items():
        params[key] = ",".join(values)
    params["order"] = "newest_first"
    return SearchQuery(domain=host, params=params)
```

- [ ] **Step 4: Correr e confirmar que passa**

Run: `python -m pytest tests/test_url_parser.py -v`
Expected: todos passam.

- [ ] **Step 5: Commit**

```powershell
git add vintedbot/vinted/url_parser.py tests/test_url_parser.py
git commit -m "feat: parse Vinted search URLs into API params"
```

---

### Task 3: Armazenamento SQLite

**Files:**
- Create: `vintedbot/storage.py`, `tests/test_storage.py`

**Interfaces:**
- Consumes: `SearchQuery` (Task 2).
- Produces:
  - `Search(id: int, chat_id: int, name: str, url: str, domain: str, params: dict[str, str], active: bool, primed: bool)`, frozen, com a propriedade `query -> SearchQuery`.
  - `Storage(path: str = ":memory:")` com os métodos: `add_search(chat_id: int, name: str, url: str, query: SearchQuery) -> Search`, `get_search(search_id: int) -> Search | None`, `list_searches(chat_id: int | None = None, active_only: bool = False) -> list[Search]`, `remove_search(chat_id: int, search_id: int) -> bool`, `set_active(chat_id: int, search_id: int, active: bool) -> bool`, `mark_primed(search_id: int) -> None`, `filter_unseen(search_id: int, item_ids: list[int]) -> list[int]` (mantém a ordem), `mark_seen(search_id: int, item_ids: list[int], now: float | None = None) -> None` (faz upsert e renova `seen_at`), `purge_seen(older_than_s: float, now: float | None = None) -> int` e `close()`.

- [ ] **Step 1: Escrever os testes (a falhar)**

`tests/test_storage.py`:
```python
from vintedbot.storage import Storage
from vintedbot.vinted.url_parser import parse_search_url

URL = "https://www.vinted.pt/catalog?search_text=nike&brand_ids[]=53"
DAY = 86400


def _add(storage, chat_id=1, name="nike"):
    return storage.add_search(chat_id, name, URL, parse_search_url(URL))


def test_add_and_get_search_roundtrip():
    storage = Storage()
    search = _add(storage)
    assert search.id == 1
    assert search.active and not search.primed
    assert search.query == parse_search_url(URL)
    assert storage.get_search(1) == search
    assert storage.get_search(99) is None


def test_list_filters_by_chat_and_active():
    storage = Storage()
    a = _add(storage, chat_id=1)
    b = _add(storage, chat_id=2)
    storage.set_active(1, a.id, False)
    assert [s.id for s in storage.list_searches()] == [a.id, b.id]
    assert [s.id for s in storage.list_searches(chat_id=1)] == [a.id]
    assert [s.id for s in storage.list_searches(active_only=True)] == [b.id]


def test_remove_and_set_active_only_touch_own_chat():
    storage = Storage()
    search = _add(storage, chat_id=1)
    assert storage.set_active(2, search.id, False) is False
    assert storage.remove_search(2, search.id) is False
    assert storage.set_active(1, search.id, False) is True
    assert storage.get_search(search.id).active is False
    assert storage.remove_search(1, search.id) is True
    assert storage.get_search(search.id) is None


def test_mark_primed():
    storage = Storage()
    search = _add(storage)
    storage.mark_primed(search.id)
    assert storage.get_search(search.id).primed is True


def test_filter_unseen_keeps_order_and_is_per_search():
    storage = Storage()
    a = _add(storage)
    b = _add(storage)
    storage.mark_seen(a.id, [2, 4])
    assert storage.filter_unseen(a.id, [5, 4, 3, 2, 1]) == [5, 3, 1]
    assert storage.filter_unseen(b.id, [4, 2]) == [4, 2]
    assert storage.filter_unseen(a.id, []) == []


def test_removing_search_deletes_its_seen_items():
    storage = Storage()
    a = _add(storage)
    storage.mark_seen(a.id, [1])
    storage.remove_search(1, a.id)
    b = _add(storage)
    assert storage.filter_unseen(b.id, [1]) == [1]


def test_purge_removes_old_items():
    storage = Storage()
    s = _add(storage)
    storage.mark_seen(s.id, [1], now=0)
    storage.mark_seen(s.id, [2], now=35 * DAY)
    assert storage.purge_seen(30 * DAY, now=36 * DAY) == 1
    assert storage.filter_unseen(s.id, [1, 2]) == [1]


def test_mark_seen_again_refreshes_timestamp_so_item_survives_purge():
    storage = Storage()
    s = _add(storage)
    storage.mark_seen(s.id, [1], now=0)
    storage.mark_seen(s.id, [1], now=40 * DAY)
    assert storage.purge_seen(30 * DAY, now=41 * DAY) == 0
    assert storage.filter_unseen(s.id, [1]) == []


def test_data_persists_in_file(tmp_path):
    path = str(tmp_path / "bot.db")
    storage = Storage(path)
    s = _add(storage)
    storage.mark_seen(s.id, [9])
    storage.close()
    reopened = Storage(path)
    assert reopened.get_search(s.id).name == "nike"
    assert reopened.filter_unseen(s.id, [9]) == []
    reopened.close()
```

- [ ] **Step 2: Correr e confirmar que falha**

Run: `python -m pytest tests/test_storage.py -v`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `vintedbot/storage.py`**

```python
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass

from vintedbot.vinted.url_parser import SearchQuery

_SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    params_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    primed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS seen_items (
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL,
    seen_at REAL NOT NULL,
    PRIMARY KEY (search_id, item_id)
);
"""


@dataclass(frozen=True)
class Search:
    id: int
    chat_id: int
    name: str
    url: str
    domain: str
    params: dict[str, str]
    active: bool
    primed: bool

    @property
    def query(self) -> SearchQuery:
        return SearchQuery(domain=self.domain, params=self.params)


def _to_search(row: sqlite3.Row) -> Search:
    return Search(
        id=row["id"],
        chat_id=row["chat_id"],
        name=row["name"],
        url=row["url"],
        domain=row["domain"],
        params=json.loads(row["params_json"]),
        active=bool(row["active"]),
        primed=bool(row["primed"]),
    )


class Storage:
    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def add_search(self, chat_id: int, name: str, url: str, query: SearchQuery) -> Search:
        with self._db:
            cur = self._db.execute(
                "INSERT INTO searches (chat_id, name, url, domain, params_json) VALUES (?, ?, ?, ?, ?)",
                (chat_id, name, url, query.domain, json.dumps(query.params)),
            )
        return self.get_search(cur.lastrowid)

    def get_search(self, search_id: int) -> Search | None:
        row = self._db.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
        return _to_search(row) if row else None

    def list_searches(self, chat_id: int | None = None, active_only: bool = False) -> list[Search]:
        sql = "SELECT * FROM searches WHERE 1 = 1"
        args: list[object] = []
        if chat_id is not None:
            sql += " AND chat_id = ?"
            args.append(chat_id)
        if active_only:
            sql += " AND active = 1"
        sql += " ORDER BY id"
        return [_to_search(row) for row in self._db.execute(sql, args)]

    def remove_search(self, chat_id: int, search_id: int) -> bool:
        with self._db:
            cur = self._db.execute("DELETE FROM searches WHERE id = ? AND chat_id = ?", (search_id, chat_id))
        return cur.rowcount > 0

    def set_active(self, chat_id: int, search_id: int, active: bool) -> bool:
        with self._db:
            cur = self._db.execute(
                "UPDATE searches SET active = ? WHERE id = ? AND chat_id = ?",
                (int(active), search_id, chat_id),
            )
        return cur.rowcount > 0

    def mark_primed(self, search_id: int) -> None:
        with self._db:
            self._db.execute("UPDATE searches SET primed = 1 WHERE id = ?", (search_id,))

    def filter_unseen(self, search_id: int, item_ids: list[int]) -> list[int]:
        if not item_ids:
            return []
        placeholders = ",".join("?" * len(item_ids))
        rows = self._db.execute(
            f"SELECT item_id FROM seen_items WHERE search_id = ? AND item_id IN ({placeholders})",
            (search_id, *item_ids),
        )
        seen = {row[0] for row in rows}
        return [item_id for item_id in item_ids if item_id not in seen]

    def mark_seen(self, search_id: int, item_ids: list[int], now: float | None = None) -> None:
        ts = time.time() if now is None else now
        with self._db:
            self._db.executemany(
                "INSERT INTO seen_items (search_id, item_id, seen_at) VALUES (?, ?, ?) "
                "ON CONFLICT (search_id, item_id) DO UPDATE SET seen_at = excluded.seen_at",
                [(search_id, item_id, ts) for item_id in item_ids],
            )

    def purge_seen(self, older_than_s: float, now: float | None = None) -> int:
        ts = time.time() if now is None else now
        with self._db:
            cur = self._db.execute("DELETE FROM seen_items WHERE seen_at < ?", (ts - older_than_s,))
        return cur.rowcount
```

- [ ] **Step 4: Correr e confirmar que passa**

Run: `python -m pytest tests/test_storage.py -v`
Expected: todos passam.

- [ ] **Step 5: Commit**

```powershell
git add vintedbot/storage.py tests/test_storage.py
git commit -m "feat: SQLite storage for searches and seen items"
```

---

### Task 4: Cliente da API da Vinted + smoke test real

**Files:**
- Create: `vintedbot/vinted/client.py`, `tests/test_client.py`
- Modify: `tests/fakes.py` (acrescentar `FakeResponse` e `FakeSession`)

**Interfaces:**
- Consumes: `Item.from_api` (Task 1), `SearchQuery` e `parse_search_url` (Task 2).
- Produces: `VintedError(Exception)`; `VintedBlockedError(VintedError)` com o atributo `.status: int`; `VintedClient(session=None)` com `async search(query: SearchQuery) -> list[Item]` (mais recentes primeiro) e `async close()`. Constante `PER_PAGE = 30`. CLI: `python -m vintedbot.vinted.client "<url>"`.

- [ ] **Step 1: Acrescentar os fakes a `tests/fakes.py`**

```python
class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Devolve respostas por ordem. Um item Exception na lista é lançado em vez de devolvido."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append((url, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        pass
```

- [ ] **Step 2: Escrever os testes (a falhar)**

`tests/test_client.py`:
```python
import json
from pathlib import Path

import pytest

from tests.fakes import FakeResponse, FakeSession
from vintedbot.vinted.client import PER_PAGE, VintedBlockedError, VintedClient, VintedError
from vintedbot.vinted.url_parser import parse_search_url

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "catalog_items.json").read_text(encoding="utf-8"))
QUERY = parse_search_url("https://www.vinted.pt/catalog?search_text=nike")
API = "https://www.vinted.pt/api/v2/catalog/items"


async def test_first_search_warms_up_then_fetches_items():
    session = FakeSession([FakeResponse(200), FakeResponse(200, PAYLOAD)])
    items = await VintedClient(session).search(QUERY)
    assert [i.id for i in items] == [5001, 5000]
    assert session.calls[0] == ("https://www.vinted.pt/", None)
    url, params = session.calls[1]
    assert url == API
    assert params == {"search_text": "nike", "order": "newest_first", "page": "1", "per_page": str(PER_PAGE)}


async def test_second_search_reuses_session():
    session = FakeSession([FakeResponse(200), FakeResponse(200, PAYLOAD), FakeResponse(200, PAYLOAD)])
    client = VintedClient(session)
    await client.search(QUERY)
    await client.search(QUERY)
    assert [c[0] for c in session.calls] == ["https://www.vinted.pt/", API, API]


async def test_401_renews_session_and_retries_once():
    session = FakeSession([FakeResponse(200), FakeResponse(401), FakeResponse(200), FakeResponse(200, PAYLOAD)])
    items = await VintedClient(session).search(QUERY)
    assert len(items) == 2
    assert [c[0] for c in session.calls] == ["https://www.vinted.pt/", API, "https://www.vinted.pt/", API]


async def test_401_twice_is_an_error():
    session = FakeSession([FakeResponse(200), FakeResponse(401), FakeResponse(200), FakeResponse(401)])
    with pytest.raises(VintedError):
        await VintedClient(session).search(QUERY)


@pytest.mark.parametrize("status", [403, 429])
async def test_blocked_statuses_raise_blocked_error(status):
    session = FakeSession([FakeResponse(200), FakeResponse(status)])
    with pytest.raises(VintedBlockedError) as exc:
        await VintedClient(session).search(QUERY)
    assert exc.value.status == status


async def test_blocked_on_warm_up():
    session = FakeSession([FakeResponse(403)])
    with pytest.raises(VintedBlockedError):
        await VintedClient(session).search(QUERY)


async def test_server_error_and_bad_json_raise_vinted_error():
    with pytest.raises(VintedError):
        await VintedClient(FakeSession([FakeResponse(200), FakeResponse(500)])).search(QUERY)
    with pytest.raises(VintedError):
        await VintedClient(FakeSession([FakeResponse(200), FakeResponse(200, None)])).search(QUERY)


async def test_network_failure_is_wrapped():
    session = FakeSession([FakeResponse(200), ConnectionError("dns")])
    with pytest.raises(VintedError) as exc:
        await VintedClient(session).search(QUERY)
    assert not isinstance(exc.value, VintedBlockedError)
```

- [ ] **Step 3: Correr e confirmar que falha**

Run: `python -m pytest tests/test_client.py -v`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 4: Implementar `vintedbot/vinted/client.py`**

```python
from __future__ import annotations

import asyncio
import sys

from vintedbot.vinted.models import Item
from vintedbot.vinted.url_parser import SearchQuery, parse_search_url

PER_PAGE = 30
_BLOCKED = {403, 429}


class VintedError(Exception):
    pass


class VintedBlockedError(VintedError):
    def __init__(self, status: int) -> None:
        super().__init__(f"bloqueado pela Vinted (HTTP {status})")
        self.status = status


class VintedClient:
    def __init__(self, session=None) -> None:
        if session is None:
            from curl_cffi.requests import AsyncSession

            session = AsyncSession(impersonate="chrome", timeout=20)
        self._session = session
        self._warm: set[str] = set()

    async def search(self, query: SearchQuery) -> list[Item]:
        if query.domain not in self._warm:
            await self._warm_up(query.domain)
        response = await self._get_items(query)
        if response.status_code == 401:
            self._warm.discard(query.domain)
            await self._warm_up(query.domain)
            response = await self._get_items(query)
        if response.status_code in _BLOCKED:
            raise VintedBlockedError(response.status_code)
        if response.status_code != 200:
            raise VintedError(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise VintedError("resposta inválida da Vinted") from exc
        return [Item.from_api(raw) for raw in data.get("items", [])]

    async def close(self) -> None:
        await self._session.close()

    async def _warm_up(self, domain: str) -> None:
        response = await self._get(f"https://{domain}/")
        if response.status_code in _BLOCKED:
            raise VintedBlockedError(response.status_code)
        self._warm.add(domain)

    async def _get_items(self, query: SearchQuery):
        params = {**query.params, "page": "1", "per_page": str(PER_PAGE)}
        return await self._get(f"https://{query.domain}/api/v2/catalog/items", params)

    async def _get(self, url: str, params: dict[str, str] | None = None):
        try:
            return await self._session.get(url, params=params)
        except Exception as exc:
            raise VintedError(f"erro de rede: {exc}") from exc


async def _smoke(url: str) -> None:
    client = VintedClient()
    try:
        items = await client.search(parse_search_url(url))
        print(f"{len(items)} artigos")
        for item in items[:5]:
            print(f"{item.id} | {item.title} | {item.price} {item.currency} | {item.url}")
    finally:
        await client.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_smoke(sys.argv[1]))
```

- [ ] **Step 5: Correr e confirmar que passa**

Run: `python -m pytest tests/test_client.py -v`
Expected: todos passam.

- [ ] **Step 6: Smoke test real (valida a viabilidade)**

Run: `python -m vintedbot.vinted.client "https://www.vinted.pt/catalog?search_text=nike&order=newest_first"`
Expected: `30 artigos` seguido de 5 linhas `id | título | preço EUR | https://www.vinted.pt/items/...`.
Se der `VintedBlockedError` ou um JSON sem `items`: PARAR e reportar ao utilizador (o endpoint ou o anti-bot mudou). Não avançar com as tasks seguintes sem decisão.

- [ ] **Step 7: Commit**

```powershell
git add vintedbot/vinted/client.py tests/test_client.py tests/fakes.py
git commit -m "feat: Vinted catalog API client with session renewal"
```

---

### Task 5: Monitor (deteção de artigos novos + backoff)

**Files:**
- Create: `vintedbot/monitor.py`, `tests/test_monitor.py`
- Modify: `tests/fakes.py` (acrescentar `FakeClient` e `FakeNotifier`)

**Interfaces:**
- Consumes: `Storage` e `Search` (Task 3), `VintedError` e `VintedBlockedError` (Task 4), `Item` (Task 1).
- Produces:
  - `Notifier` (Protocol) com `async send_item(chat_id: int, search: Search, item: Item) -> None` e `async send_text(chat_id: int, text: str) -> None`.
  - `Monitor(storage, client, notifier, *, clock=time.monotonic, sleep=asyncio.sleep, pause_between_s=3.0)` com `async check_search(search: Search) -> int` (devolve o número de alertas enviados; propaga `VintedError`) e `async run_cycle() -> None` (nunca lança exceções).
  - Constantes: `MAX_ALERTS_PER_CYCLE = 10`, `BASE_BACKOFF_S = 60`, `MAX_BACKOFF_S = 900`, `WARN_AFTER_FAILURES = 3`.

- [ ] **Step 1: Acrescentar os fakes a `tests/fakes.py`**

```python
class FakeClient:
    """Cada chamada a search() consome a próxima resposta: list[Item] ou Exception."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    async def search(self, query):
        self.queries.append(query)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeNotifier:
    def __init__(self, fail_item_ids=()):
        self.items = []  # (chat_id, search, item)
        self.texts = []  # (chat_id, text)
        self.fail_item_ids = set(fail_item_ids)

    async def send_item(self, chat_id, search, item):
        if item.id in self.fail_item_ids:
            raise RuntimeError("telegram down")
        self.items.append((chat_id, search, item))

    async def send_text(self, chat_id, text):
        self.texts.append((chat_id, text))
```

- [ ] **Step 2: Escrever os testes (a falhar)**

`tests/test_monitor.py`:
```python
from tests.fakes import FakeClient, FakeNotifier, make_item
from vintedbot.monitor import (
    BASE_BACKOFF_S,
    MAX_ALERTS_PER_CYCLE,
    MAX_BACKOFF_S,
    WARN_AFTER_FAILURES,
    Monitor,
)
from vintedbot.storage import Storage
from vintedbot.vinted.client import VintedBlockedError, VintedError
from vintedbot.vinted.url_parser import parse_search_url


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


async def _no_sleep(_seconds):
    return None


def _setup(responses, notifier=None):
    storage = Storage()
    client = FakeClient(responses)
    notifier = notifier or FakeNotifier()
    clock = Clock()
    monitor = Monitor(storage, client, notifier, clock=clock, sleep=_no_sleep)
    return storage, client, notifier, clock, monitor


def _add(storage, chat_id=1, text="nike"):
    url = f"https://www.vinted.pt/catalog?search_text={text}"
    return storage.add_search(chat_id, text, url, parse_search_url(url))


async def test_first_check_primes_silently():
    storage, _, notifier, _, monitor = _setup([[make_item(3), make_item(2)]])
    search = _add(storage)
    assert await monitor.check_search(search) == 0
    assert notifier.items == []
    assert storage.get_search(search.id).primed
    assert storage.filter_unseen(search.id, [2, 3]) == []


async def test_new_items_alerted_oldest_first_and_only_once():
    page = [make_item(4), make_item(3), make_item(2)]
    storage, _, notifier, _, monitor = _setup([[make_item(2)], page, page])
    _add(storage)
    await monitor.run_cycle()  # primes
    await monitor.run_cycle()
    assert [item.id for _, _, item in notifier.items] == [3, 4]
    await monitor.run_cycle()
    assert len(notifier.items) == 2


async def test_burst_is_capped_and_summarised():
    burst = [make_item(i) for i in range(100 + MAX_ALERTS_PER_CYCLE + 5, 100, -1)]
    storage, _, notifier, _, monitor = _setup([[make_item(1)], burst])
    search = _add(storage)
    await monitor.run_cycle()
    await monitor.run_cycle()
    assert len(notifier.items) == MAX_ALERTS_PER_CYCLE
    assert notifier.items[-1][2].id == burst[0].id  # o mais recente chega em último
    assert len(notifier.texts) == 1
    assert "mais 5" in notifier.texts[0][1]
    assert storage.filter_unseen(search.id, [i.id for i in burst]) == []


async def test_failed_send_is_retried_next_cycle():
    page = [make_item(4), make_item(3), make_item(2)]
    notifier = FakeNotifier(fail_item_ids={3})
    storage, _, notifier, _, monitor = _setup([[make_item(2)], page, page], notifier)
    search = _add(storage)
    await monitor.run_cycle()
    await monitor.run_cycle()  # item 3 falha -> nada marcado como visto
    assert storage.filter_unseen(search.id, [4, 3]) == [4, 3]
    notifier.fail_item_ids.clear()
    await monitor.run_cycle()
    assert [item.id for _, _, item in notifier.items] == [3, 4]


async def test_items_still_listed_have_seen_at_refreshed():
    storage, _, _, _, monitor = _setup([[make_item(1)], [make_item(1)]])
    search = _add(storage)
    await monitor.run_cycle()
    storage.mark_seen(search.id, [1], now=0)  # simula visto há muito tempo
    await monitor.run_cycle()
    assert storage.purge_seen(30 * 86400) == 0


async def test_paused_searches_are_skipped():
    storage, client, _, _, monitor = _setup([])
    search = _add(storage)
    storage.set_active(1, search.id, False)
    await monitor.run_cycle()
    assert client.queries == []


async def test_error_in_one_search_does_not_stop_others():
    storage, _, _, _, monitor = _setup([VintedError("boom"), [make_item(1)]])
    _add(storage, text="a")
    second = _add(storage, text="b")
    await monitor.run_cycle()
    assert storage.get_search(second.id).primed


async def test_blocked_backs_off_warns_once_and_recovers():
    blocked = [VintedBlockedError(429) for _ in range(WARN_AFTER_FAILURES)]
    storage, client, notifier, clock, monitor = _setup(blocked + [[make_item(1)]])
    _add(storage)

    await monitor.run_cycle()
    assert len(client.queries) == 1
    await monitor.run_cycle()  # ainda em backoff
    assert len(client.queries) == 1

    wait = BASE_BACKOFF_S
    for _ in range(WARN_AFTER_FAILURES - 1):
        clock.now += wait
        await monitor.run_cycle()
        wait = min(wait * 2, MAX_BACKOFF_S)

    assert len(client.queries) == WARN_AFTER_FAILURES
    assert len(notifier.texts) == 1
    assert "bloquear" in notifier.texts[0][1]

    clock.now += wait
    await monitor.run_cycle()
    assert len(notifier.texts) == 2
    assert "voltou" in notifier.texts[1][1]
```

- [ ] **Step 3: Correr e confirmar que falha**

Run: `python -m pytest tests/test_monitor.py -v`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 4: Implementar `vintedbot/monitor.py`**

```python
from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol

from vintedbot.storage import Search, Storage
from vintedbot.vinted.client import VintedBlockedError
from vintedbot.vinted.models import Item

log = logging.getLogger(__name__)

MAX_ALERTS_PER_CYCLE = 10
BASE_BACKOFF_S = 60
MAX_BACKOFF_S = 900
WARN_AFTER_FAILURES = 3


class Notifier(Protocol):
    async def send_item(self, chat_id: int, search: Search, item: Item) -> None: ...

    async def send_text(self, chat_id: int, text: str) -> None: ...


class Monitor:
    def __init__(
        self,
        storage: Storage,
        client,
        notifier: Notifier,
        *,
        clock=time.monotonic,
        sleep=asyncio.sleep,
        pause_between_s: float = 3.0,
    ) -> None:
        self._storage = storage
        self._client = client
        self._notifier = notifier
        self._clock = clock
        self._sleep = sleep
        self._pause_between_s = pause_between_s
        self._blocked_until = 0.0
        self._backoff = 0
        self._failures = 0

    async def check_search(self, search: Search) -> int:
        items = await self._client.search(search.query)
        ids = [item.id for item in items]
        if not search.primed:
            self._storage.mark_seen(search.id, ids)
            self._storage.mark_primed(search.id)
            return 0

        unseen = set(self._storage.filter_unseen(search.id, ids))
        new_items = [item for item in items if item.id in unseen]
        to_send = new_items[:MAX_ALERTS_PER_CYCLE]
        overflow = new_items[MAX_ALERTS_PER_CYCLE:]
        for item in reversed(to_send):
            await self._notifier.send_item(search.chat_id, search, item)
            self._storage.mark_seen(search.id, [item.id])
        if overflow:
            await self._notifier.send_text(
                search.chat_id,
                f"… e mais {len(overflow)} artigos novos em «{search.name}»: {search.url}",
            )
        self._storage.mark_seen(search.id, ids)
        return len(to_send)

    async def run_cycle(self) -> None:
        if self._clock() < self._blocked_until:
            log.info("Em backoff; ciclo ignorado")
            return
        searches = self._storage.list_searches(active_only=True)
        for index, search in enumerate(searches):
            if index:
                await self._sleep(self._pause_between_s)
            try:
                await self.check_search(search)
            except VintedBlockedError as exc:
                await self._on_blocked(exc, searches)
                return
            except Exception:
                log.exception("Falha ao verificar a pesquisa #%s", search.id)
        await self._on_healthy(searches)

    async def _on_blocked(self, exc: VintedBlockedError, searches: list[Search]) -> None:
        self._failures += 1
        self._backoff = BASE_BACKOFF_S if self._backoff == 0 else min(self._backoff * 2, MAX_BACKOFF_S)
        self._blocked_until = self._clock() + self._backoff
        log.warning("Vinted bloqueou (HTTP %s); a aguardar %ss", exc.status, self._backoff)
        if self._failures == WARN_AFTER_FAILURES:
            await self._broadcast(
                searches,
                f"⚠️ A Vinted está a bloquear os pedidos (HTTP {exc.status}). "
                f"Vou continuar a tentar com pausas até {MAX_BACKOFF_S // 60} min.",
            )

    async def _on_healthy(self, searches: list[Search]) -> None:
        if self._failures >= WARN_AFTER_FAILURES:
            await self._broadcast(searches, "✅ A Vinted voltou a responder. Alertas retomados.")
        self._failures = 0
        self._backoff = 0

    async def _broadcast(self, searches: list[Search], text: str) -> None:
        for chat_id in sorted({search.chat_id for search in searches}):
            try:
                await self._notifier.send_text(chat_id, text)
            except Exception:
                log.exception("Falha ao enviar aviso para %s", chat_id)
```

- [ ] **Step 5: Correr e confirmar que passa**

Run: `python -m pytest tests/test_monitor.py -v`
Expected: todos passam.

- [ ] **Step 6: Commit**

```powershell
git add vintedbot/monitor.py tests/test_monitor.py tests/fakes.py
git commit -m "feat: monitor with silent priming, alert cap and backoff"
```

---

### Task 6: Lógica dos comandos

**Files:**
- Create: `vintedbot/commands.py`, `tests/test_commands.py`
- Modify: `tests/fakes.py` (acrescentar `FakeMonitor`)

**Interfaces:**
- Consumes: `Storage` (Task 3), `parse_search_url` e `InvalidSearchUrl` (Task 2), `VintedError` (Task 4), `Monitor.check_search` (Task 5).
- Produces: `Commands(storage, monitor)` com `async add(chat_id: int, args: list[str]) -> str`, `list(chat_id: int) -> str`, `remove(chat_id: int, args: list[str]) -> str` e `set_active(chat_id: int, args: list[str], active: bool) -> str`. Constante `HELP: str`.

- [ ] **Step 1: Acrescentar o `FakeMonitor` a `tests/fakes.py`**

```python
class FakeMonitor:
    def __init__(self, error=None):
        self.checked = []
        self.error = error

    async def check_search(self, search):
        self.checked.append(search.id)
        if self.error:
            raise self.error
        return 0
```

- [ ] **Step 2: Escrever os testes (a falhar)**

`tests/test_commands.py`:
```python
from tests.fakes import FakeMonitor
from vintedbot.commands import Commands
from vintedbot.storage import Storage
from vintedbot.vinted.client import VintedBlockedError

URL = "https://www.vinted.pt/catalog?search_text=nike+air&price_to=30"


def _commands(monitor=None):
    storage = Storage()
    return storage, Commands(storage, monitor or FakeMonitor())


async def test_add_stores_search_and_primes_it():
    monitor = FakeMonitor()
    storage, commands = _commands(monitor)
    reply = await commands.add(1, [URL])
    assert "#1" in reply and "nike air" in reply
    assert storage.get_search(1).name == "nike air"
    assert monitor.checked == [1]


async def test_add_uses_custom_name():
    storage, commands = _commands()
    await commands.add(1, [URL, "Sapatilhas", "baratas"])
    assert storage.get_search(1).name == "Sapatilhas baratas"


async def test_add_without_args_shows_usage():
    _, commands = _commands()
    assert "Uso" in await commands.add(1, [])


async def test_add_invalid_url_stores_nothing():
    storage, commands = _commands()
    reply = await commands.add(1, ["https://www.vinted.pt/items/1-casaco"])
    assert reply.startswith("❌")
    assert storage.list_searches() == []


async def test_add_when_vinted_fails_still_stores():
    storage, commands = _commands(FakeMonitor(error=VintedBlockedError(429)))
    reply = await commands.add(1, [URL])
    assert "próximo ciclo" in reply
    assert len(storage.list_searches()) == 1


async def test_list_shows_status():
    storage, commands = _commands()
    assert "Ainda não tens" in commands.list(1)
    await commands.add(1, [URL])
    await commands.add(1, [URL, "outra"])
    commands.set_active(1, ["2"], False)
    assert commands.list(1) == "#1 ▶️ nike air\n#2 ⏸ outra"


async def test_remove():
    storage, commands = _commands()
    await commands.add(1, [URL])
    assert "Uso" in commands.remove(1, [])
    assert "Uso" in commands.remove(1, ["abc"])
    assert "não existe" in commands.remove(2, ["1"])  # pesquisa de outro chat
    assert "removida" in commands.remove(1, ["1"])
    assert storage.list_searches() == []


async def test_pause_and_resume():
    storage, commands = _commands()
    await commands.add(1, [URL])
    assert "pausa" in commands.set_active(1, ["1"], False)
    assert storage.get_search(1).active is False
    assert "retomada" in commands.set_active(1, ["#1"], True)
    assert storage.get_search(1).active is True
    assert "não existe" in commands.set_active(1, ["9"], True)
```

- [ ] **Step 3: Correr e confirmar que falha**

Run: `python -m pytest tests/test_commands.py -v`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 4: Implementar `vintedbot/commands.py`**

```python
from __future__ import annotations

from vintedbot.storage import Storage
from vintedbot.vinted.client import VintedError
from vintedbot.vinted.url_parser import InvalidSearchUrl, parse_search_url

HELP = (
    "Olá! Faz uma pesquisa na Vinted com os filtros que quiseres e cola aqui o URL.\n\n"
    "/add <url> [nome] – monitorizar uma pesquisa\n"
    "/list – ver as pesquisas\n"
    "/pause <id> – pausar\n"
    "/resume <id> – retomar\n"
    "/remove <id> – apagar\n"
    "/id – mostrar o chat id"
)


def _parse_id(args: list[str]) -> int | None:
    if len(args) != 1:
        return None
    raw = args[0].lstrip("#")
    return int(raw) if raw.isdigit() else None


class Commands:
    def __init__(self, storage: Storage, monitor) -> None:
        self._storage = storage
        self._monitor = monitor

    async def add(self, chat_id: int, args: list[str]) -> str:
        if not args:
            return "Uso: /add <url da pesquisa na Vinted> [nome]"
        url = args[0]
        try:
            query = parse_search_url(url)
        except InvalidSearchUrl as exc:
            return f"❌ {exc}"
        name = " ".join(args[1:]).strip() or query.params.get("search_text") or "Pesquisa"
        search = self._storage.add_search(chat_id, name, url, query)
        try:
            await self._monitor.check_search(search)
        except VintedError as exc:
            return (
                f"✅ Pesquisa #{search.id} «{name}» guardada, mas a Vinted não respondeu agora ({exc}). "
                "Tento de novo no próximo ciclo."
            )
        return f"✅ Pesquisa #{search.id} «{name}» adicionada. Aviso-te quando aparecerem artigos novos."

    def list(self, chat_id: int) -> str:
        searches = self._storage.list_searches(chat_id=chat_id)
        if not searches:
            return "Ainda não tens pesquisas. Usa /add <url>."
        return "\n".join(f"#{s.id} {'▶️' if s.active else '⏸'} {s.name}" for s in searches)

    def remove(self, chat_id: int, args: list[str]) -> str:
        search_id = _parse_id(args)
        if search_id is None:
            return "Uso: /remove <id>"
        if not self._storage.remove_search(chat_id, search_id):
            return f"A pesquisa #{search_id} não existe."
        return f"🗑 Pesquisa #{search_id} removida."

    def set_active(self, chat_id: int, args: list[str], active: bool) -> str:
        search_id = _parse_id(args)
        if search_id is None:
            return f"Uso: /{'resume' if active else 'pause'} <id>"
        if not self._storage.set_active(chat_id, search_id, active):
            return f"A pesquisa #{search_id} não existe."
        return f"▶️ Pesquisa #{search_id} retomada." if active else f"⏸ Pesquisa #{search_id} em pausa."
```

- [ ] **Step 5: Correr e confirmar que passa**

Run: `python -m pytest tests/test_commands.py -v`
Expected: todos passam.

- [ ] **Step 6: Commit**

```powershell
git add vintedbot/commands.py tests/test_commands.py tests/fakes.py
git commit -m "feat: bot command logic (add/list/remove/pause/resume)"
```

---

### Task 7: Config, Telegram e entrypoint

**Files:**
- Create: `vintedbot/config.py`, `vintedbot/telegram_bot.py`, `vintedbot/main.py`, `tests/test_config.py`, `tests/test_telegram_bot.py`
- Modify: `tests/fakes.py` (acrescentar `FakeBot`), `README.md`

**Interfaces:**
- Consumes: tudo o que foi feito antes.
- Produces:
  - `ConfigError(Exception)`, `Settings(telegram_token: str, allowed_chat_id: int | None, poll_interval: int, db_path: str)` e `load_settings(env: Mapping[str, str] | None = None) -> Settings`.
  - `format_caption(search: Search, item: Item) -> str` (HTML), `TelegramNotifier(bot)` (implementa `Notifier`) e `build_application(settings, storage, client) -> telegram.ext.Application`.
  - `python -m vintedbot.main`.

- [ ] **Step 1: Escrever os testes de config (a falhar)**

`tests/test_config.py`:
```python
import pytest

from vintedbot.config import ConfigError, load_settings


def test_defaults():
    s = load_settings({"TELEGRAM_TOKEN": "t"})
    assert s.telegram_token == "t"
    assert s.allowed_chat_id is None
    assert s.poll_interval == 120
    assert s.db_path == "vintedbot.db"


def test_values_are_parsed_and_poll_interval_clamped():
    s = load_settings({"TELEGRAM_TOKEN": "t", "ALLOWED_CHAT_ID": "-100123", "POLL_INTERVAL": "30", "DB_PATH": "x.db"})
    assert s.allowed_chat_id == -100123
    assert s.poll_interval == 60
    assert s.db_path == "x.db"


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"TELEGRAM_TOKEN": ""},
        {"TELEGRAM_TOKEN": "t", "ALLOWED_CHAT_ID": "abc"},
        {"TELEGRAM_TOKEN": "t", "POLL_INTERVAL": "rápido"},
    ],
)
def test_invalid_config_raises(env):
    with pytest.raises(ConfigError):
        load_settings(env)
```

- [ ] **Step 2: Correr e confirmar que falha**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `vintedbot/config.py`**

```python
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

MIN_POLL_INTERVAL = 60


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    allowed_chat_id: int | None
    poll_interval: int
    db_path: str


def _int(env: Mapping[str, str], key: str, default: int | None) -> int | None:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} tem de ser um número inteiro (recebi {raw!r}).") from exc


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        from dotenv import load_dotenv

        load_dotenv()
        env = os.environ
    token = (env.get("TELEGRAM_TOKEN") or "").strip()
    if not token:
        raise ConfigError("Falta TELEGRAM_TOKEN no .env (cria o bot no @BotFather).")
    return Settings(
        telegram_token=token,
        allowed_chat_id=_int(env, "ALLOWED_CHAT_ID", None),
        poll_interval=max(MIN_POLL_INTERVAL, _int(env, "POLL_INTERVAL", 120)),
        db_path=(env.get("DB_PATH") or "vintedbot.db").strip(),
    )
```

- [ ] **Step 4: Correr e confirmar que passa**

Run: `python -m pytest tests/test_config.py -v`
Expected: todos passam.

- [ ] **Step 5: Acrescentar o `FakeBot` a `tests/fakes.py` e escrever os testes do Telegram (a falhar)**

Em `tests/fakes.py`:
```python
class FakeBot:
    def __init__(self, photo_error=None):
        self.sent = []  # (kind, chat_id, text, reply_markup)
        self.photo_error = photo_error

    async def send_photo(self, chat_id, photo, caption, parse_mode, reply_markup):
        if self.photo_error:
            raise self.photo_error
        self.sent.append(("photo", chat_id, caption, reply_markup))

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        self.sent.append(("message", chat_id, text, reply_markup))
```

`tests/test_telegram_bot.py`:
```python
from telegram.error import BadRequest

from tests.fakes import FakeBot, make_item
from vintedbot.storage import Storage
from vintedbot.telegram_bot import TelegramNotifier, format_caption
from vintedbot.vinted.url_parser import parse_search_url

URL = "https://www.vinted.pt/catalog?search_text=nike"


def _search(name="Nike <42>"):
    return Storage().add_search(1, name, URL, parse_search_url(URL))


def test_caption_escapes_html_and_skips_empty_details():
    item = make_item(1, title="Casaco <novo> & bonito", price="12.5", brand="", size="M")
    caption = format_caption(_search(), item)
    assert caption == "<b>Casaco &lt;novo&gt; &amp; bonito</b>\n💶 12.5 EUR\nM\n🔎 Nike &lt;42&gt;"


def test_caption_truncates_long_titles():
    caption = format_caption(_search("x"), make_item(1, title="a" * 500))
    assert len(caption) < 1024


async def test_item_with_photo_is_sent_as_photo_with_button():
    bot = FakeBot()
    await TelegramNotifier(bot).send_item(1, _search(), make_item(1, photo_url="https://img/1.jpg"))
    kind, chat_id, _, markup = bot.sent[0]
    assert (kind, chat_id) == ("photo", 1)
    assert markup.inline_keyboard[0][0].url == "https://www.vinted.pt/items/1"


async def test_item_without_photo_is_sent_as_message():
    bot = FakeBot()
    await TelegramNotifier(bot).send_item(1, _search(), make_item(1, photo_url=None))
    assert bot.sent[0][0] == "message"


async def test_rejected_photo_falls_back_to_message():
    bot = FakeBot(photo_error=BadRequest("wrong file identifier"))
    await TelegramNotifier(bot).send_item(1, _search(), make_item(1, photo_url="https://img/bad.jpg"))
    assert [s[0] for s in bot.sent] == ["message"]


async def test_item_without_url_has_no_button():
    bot = FakeBot()
    await TelegramNotifier(bot).send_item(1, _search(), make_item(1, url=""))
    assert bot.sent[0][3] is None
```

- [ ] **Step 6: Correr e confirmar que falha**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'vintedbot.telegram_bot'`.

- [ ] **Step 7: Implementar `vintedbot/telegram_bot.py`**

```python
from __future__ import annotations

import asyncio
import logging
import random
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from vintedbot.commands import HELP, Commands
from vintedbot.config import Settings
from vintedbot.monitor import Monitor
from vintedbot.storage import Search, Storage
from vintedbot.vinted.client import VintedClient
from vintedbot.vinted.models import Item

log = logging.getLogger(__name__)

MAX_TITLE = 200
SEEN_RETENTION_S = 30 * 86400


def format_caption(search: Search, item: Item) -> str:
    title = item.title if len(item.title) <= MAX_TITLE else item.title[: MAX_TITLE - 1] + "…"
    lines = [f"<b>{escape(title)}</b>", f"💶 {escape(item.price)} {escape(item.currency)}".rstrip()]
    details = " · ".join(part for part in (item.brand, item.size) if part)
    if details:
        lines.append(escape(details))
    lines.append(f"🔎 {escape(search.name)}")
    return "\n".join(lines)


class TelegramNotifier:
    def __init__(self, bot) -> None:
        self._bot = bot

    async def send_item(self, chat_id: int, search: Search, item: Item) -> None:
        caption = format_caption(search, item)
        markup = (
            InlineKeyboardMarkup([[InlineKeyboardButton("Abrir na Vinted", url=item.url)]]) if item.url else None
        )
        if item.photo_url:
            try:
                await self._bot.send_photo(
                    chat_id=chat_id,
                    photo=item.photo_url,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return
            except BadRequest:
                log.warning("Telegram rejeitou a foto do artigo %s; a enviar só texto", item.id)
        await self._bot.send_message(chat_id, caption, parse_mode=ParseMode.HTML, reply_markup=markup)

    async def send_text(self, chat_id: int, text: str) -> None:
        await self._bot.send_message(chat_id, text)


def build_application(settings: Settings, storage: Storage, client: VintedClient) -> Application:
    async def on_shutdown(_app: Application) -> None:
        await client.close()
        storage.close()

    app = Application.builder().token(settings.telegram_token).post_shutdown(on_shutdown).build()
    monitor = Monitor(storage, client, TelegramNotifier(app.bot))
    commands = Commands(storage, monitor)
    if settings.allowed_chat_id is None:
        log.warning("ALLOWED_CHAT_ID não definido: envia /id ao bot e põe o valor no .env")
    allowed = filters.Chat(chat_id=[] if settings.allowed_chat_id is None else [settings.allowed_chat_id])

    async def reply(update: Update, text: str) -> None:
        await update.effective_message.reply_text(text)

    async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, HELP)

    async def on_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, f"O teu chat id é {update.effective_chat.id}")

    async def on_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, await commands.add(update.effective_chat.id, context.args))

    async def on_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.list(update.effective_chat.id))

    async def on_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.remove(update.effective_chat.id, context.args))

    async def on_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.set_active(update.effective_chat.id, context.args, False))

    async def on_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.set_active(update.effective_chat.id, context.args, True))

    app.add_handler(CommandHandler("id", on_id))
    app.add_handler(CommandHandler(["start", "help"], on_start, filters=allowed))
    app.add_handler(CommandHandler("add", on_add, filters=allowed))
    app.add_handler(CommandHandler("list", on_list, filters=allowed))
    app.add_handler(CommandHandler("remove", on_remove, filters=allowed))
    app.add_handler(CommandHandler("pause", on_pause, filters=allowed))
    app.add_handler(CommandHandler("resume", on_resume, filters=allowed))

    jitter_s = min(30.0, settings.poll_interval * 0.25)

    async def poll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await asyncio.sleep(random.uniform(0, jitter_s))
        await monitor.run_cycle()

    async def purge_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        removed = storage.purge_seen(SEEN_RETENTION_S)
        log.info("Limpeza: %s artigos vistos antigos removidos", removed)

    app.job_queue.run_repeating(
        poll_job,
        interval=settings.poll_interval,
        first=10,
        name="poll",
        job_kwargs={"max_instances": 1, "coalesce": True},
    )
    app.job_queue.run_repeating(purge_job, interval=86400, first=60, name="purge")
    return app
```

- [ ] **Step 8: Correr e confirmar que passa**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: todos passam.

- [ ] **Step 9: Implementar `vintedbot/main.py`**

```python
from __future__ import annotations

import asyncio
import logging
import sys

from vintedbot.config import ConfigError, load_settings
from vintedbot.storage import Storage
from vintedbot.telegram_bot import build_application
from vintedbot.vinted.client import VintedClient


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        settings = load_settings()
    except ConfigError as exc:
        sys.exit(f"Erro de configuração: {exc}")
    app = build_application(settings, Storage(settings.db_path), VintedClient())
    app.run_polling()


if __name__ == "__main__":
    main()
```

Run: `python -c "import vintedbot.main"`
Expected: sem output e sem erro (confirma que os imports do PTB e do curl_cffi estão certos).

- [ ] **Step 10: Atualizar o `README.md`**

```markdown
# VintedBot

Bot pessoal que monitoriza pesquisas da Vinted e envia um alerta no Telegram por cada artigo novo.

> ⚠️ Usa a API interna (não oficial) da Vinted. Os Termos de Serviço proíbem automação: usa com moderação (intervalos ≥ 60 s) e por tua conta e risco.

## Setup (Windows)

1. Instalar o Python 3.12: `winget install -e --id Python.Python.3.12`
2. `python -m venv .venv` e `.venv\Scripts\Activate.ps1`
3. `python -m pip install -r requirements.txt`
4. Criar o bot no Telegram com o [@BotFather](https://t.me/BotFather) e copiar o token.
5. `copy .env.example .env` e preencher `TELEGRAM_TOKEN`.
6. `python -m vintedbot.main`, enviar `/id` ao bot, pôr o número em `ALLOWED_CHAT_ID` no `.env` e reiniciar.

## Utilização

1. Na Vinted, faz a pesquisa com os filtros que quiseres (marca, tamanho, preço…).
2. Copia o URL e envia `/add <url> [nome]` ao bot.
3. A partir daí recebes um alerta por cada artigo novo.

Comandos: `/add`, `/list`, `/pause <id>`, `/resume <id>`, `/remove <id>`, `/id`.

## Testes

`python -m pytest`
```

- [ ] **Step 11: Suite completa**

Run: `python -m pytest -v`
Expected: todos passam, 0 falhas.

- [ ] **Step 12: Commit**

```powershell
git add vintedbot tests README.md
git commit -m "feat: Telegram bot wiring, config and entrypoint"
```

---

### Task 8: Verificação end-to-end (manual, com o utilizador)

**Files:** nenhum (só verificação). Se algo falhar, usar superpowers:systematic-debugging.

- [ ] **Step 1:** O utilizador cria o bot no @BotFather, copia `.env.example` para `.env` e preenche `TELEGRAM_TOKEN`.
- [ ] **Step 2:** `python -m vintedbot.main` → no log aparece o aviso de `ALLOWED_CHAT_ID não definido`. Enviar `/id` ao bot → responde com o chat id. Pôr o valor no `.env` e reiniciar.
- [ ] **Step 3:** Enviar `/start` → recebe a ajuda. A partir de outra conta do Telegram (se houver), `/list` não tem resposta.
- [ ] **Step 4:** Enviar `/add https://www.vinted.pt/catalog?search_text=nike&order=newest_first Nike` → `✅ Pesquisa #1 «Nike» adicionada`, **sem** alertas iniciais.
- [ ] **Step 5:** Esperar 2–5 min → chegam alertas com foto, preço e botão «Abrir na Vinted», e o botão abre o artigo certo.
- [ ] **Step 6:** `/pause 1` → deixam de chegar alertas. `/resume 1` → voltam. `/remove 1` → `/list` fica vazio.
- [ ] **Step 7:** `/add https://www.vinted.pt/items/123` → mensagem de erro, nada gravado.
- [ ] **Step 8:** Parar com Ctrl+C → termina sem traceback. Reiniciar → `/list` mantém as pesquisas (persistência em SQLite).
