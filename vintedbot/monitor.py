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
