from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass

from vintedbot.vinted.models import Item
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
    primed INTEGER NOT NULL DEFAULT 0,
    last_item_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS seen_items (
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL,
    seen_at REAL NOT NULL,
    PRIMARY KEY (search_id, item_id)
);
-- Alertas enviados, com os detalhes (lidos pela Wintermute em modo só de leitura).
-- Sem ON DELETE CASCADE: o histórico fica mesmo que a pesquisa seja apagada.
CREATE TABLE IF NOT EXISTS alertas (
    item_id INTEGER NOT NULL,
    search_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    preco TEXT NOT NULL,
    moeda TEXT NOT NULL,
    url TEXT NOT NULL,
    enviado_em REAL NOT NULL,
    PRIMARY KEY (search_id, item_id)
);
CREATE INDEX IF NOT EXISTS alertas_enviado ON alertas (enviado_em);
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
    last_item_id: int

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
        last_item_id=row["last_item_id"],
    )


class Storage:
    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(searches)")}
        if "last_item_id" not in columns:
            with self._db:
                self._db.execute("ALTER TABLE searches ADD COLUMN last_item_id INTEGER NOT NULL DEFAULT 0")
                self._db.execute(
                    "UPDATE searches SET last_item_id = "
                    "COALESCE((SELECT MAX(item_id) FROM seen_items WHERE search_id = searches.id), 0)"
                )

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
                # Retomar volta a "primar" a pesquisa: o que apareceu durante a pausa não gera alertas.
                "UPDATE searches SET active = ?, primed = CASE WHEN ? THEN 0 ELSE primed END "
                "WHERE id = ? AND chat_id = ?",
                (int(active), int(active), search_id, chat_id),
            )
        return cur.rowcount > 0

    def mark_primed(self, search_id: int) -> None:
        with self._db:
            self._db.execute("UPDATE searches SET primed = 1 WHERE id = ?", (search_id,))

    def advance_last_item_id(self, search_id: int, item_id: int) -> None:
        with self._db:
            self._db.execute(
                "UPDATE searches SET last_item_id = MAX(last_item_id, ?) WHERE id = ?",
                (item_id, search_id),
            )

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

    def registar_alertas(self, search_id: int, items: list[Item], now: float | None = None) -> None:
        ts = time.time() if now is None else now
        with self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO alertas (item_id, search_id, titulo, preco, moeda, url, enviado_em) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(item.id, search_id, item.title, item.price, item.currency, item.url, ts) for item in items],
            )

    def purge_alertas(self, older_than_s: float, now: float | None = None) -> int:
        ts = time.time() if now is None else now
        with self._db:
            cur = self._db.execute("DELETE FROM alertas WHERE enviado_em < ?", (ts - older_than_s,))
        return cur.rowcount

    def purge_seen(self, older_than_s: float, now: float | None = None) -> int:
        ts = time.time() if now is None else now
        with self._db:
            cur = self._db.execute("DELETE FROM seen_items WHERE seen_at < ?", (ts - older_than_s,))
        return cur.rowcount
