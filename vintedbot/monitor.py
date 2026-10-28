from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from typing import Protocol

from vintedbot.storage import Search, Storage
from vintedbot.vinted.client import VintedBlockedError
from vintedbot.vinted.models import Item

log = logging.getLogger(__name__)

MAX_ALERTS_PER_CYCLE = 10
BASE_BACKOFF_S = 60
MAX_BACKOFF_S = 900
WARN_AFTER_FAILURES = 3
ERROR_WARN_AFTER_CYCLES = 3


class Notifier(Protocol):
    async def send_item(self, chat_id: int, search: Search, item: Item) -> None: ...

    async def send_text(self, chat_id: int, text: str) -> None: ...


@dataclass(frozen=True)
class MonitorStatus:
    now: float
    last_success_at: float | None
    error_cycles: int
    last_error: str | None
    blocked_until: float | None


class Monitor:
    def __init__(
        self,
        storage: Storage,
        client,
        notifier: Notifier,
        *,
        clock=time.monotonic,
        wall_clock=time.time,
        sleep=asyncio.sleep,
        pause_between_s: float = 3.0,
    ) -> None:
        self._storage = storage
        self._client = client
        self._notifier = notifier
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._pause_between_s = pause_between_s
        self._blocked_until = 0.0
        self._backoff = 0
        self._failures = 0
        self._error_cycles = 0
        self._last_error: str | None = None
        self._last_success_at: float | None = None

    def status(self) -> MonitorStatus:
        now = self._wall_clock()
        remaining = self._blocked_until - self._clock()
        return MonitorStatus(
            now=now,
            last_success_at=self._last_success_at,
            error_cycles=self._error_cycles,
            last_error=self._last_error,
            blocked_until=now + remaining if remaining > 0 else None,
        )

    async def check_search(self, search: Search) -> int:
        items = await self._client.search(search.query)
        ids = [item.id for item in items]
        if not search.primed:
            self._storage.mark_seen(search.id, ids)
            self._storage.advance_last_item_id(search.id, max(ids, default=0))
            self._storage.mark_primed(search.id)
            return 0

        # Os IDs da Vinted são sequenciais: um ID abaixo do máximo já visto é um artigo antigo
        # que entrou na 1.ª página (outro foi vendido/apagado), não um artigo novo.
        unseen = set(self._storage.filter_unseen(search.id, ids))
        new_items = [item for item in items if item.id in unseen and item.id > search.last_item_id]
        to_send = new_items[:MAX_ALERTS_PER_CYCLE]
        overflow = new_items[MAX_ALERTS_PER_CYCLE:]
        for item in reversed(to_send):
            if item.seller_id is not None:
                country = await self._client.seller_country(search.domain, item.seller_id)
                if country:
                    item = replace(item, country=country)
            await self._notifier.send_item(search.chat_id, search, item)
            self._storage.mark_seen(search.id, [item.id])
            self._storage.registar_alertas(search.id, [item])
        if overflow:
            await self._notifier.send_text(
                search.chat_id,
                f"… e mais {len(overflow)} artigos novos em «{search.name}»: {search.url}",
            )
            # Também contam: apareceram, só não foram alertados um a um.
            self._storage.registar_alertas(search.id, overflow)
        self._storage.mark_seen(search.id, ids)
        self._storage.advance_last_item_id(search.id, max(ids, default=0))
        return len(to_send)

    async def run_cycle(self) -> None:
        if self._clock() < self._blocked_until:
            log.info("Em backoff; ciclo ignorado")
            return
        searches = self._storage.list_searches(active_only=True)
        succeeded = 0
        for index, search in enumerate(searches):
            if index:
                await self._sleep(self._pause_between_s)
            try:
                await self.check_search(search)
                succeeded += 1
            except VintedBlockedError as exc:
                await self._on_blocked(exc, searches)
                return
            except Exception as exc:
                self._last_error = str(exc) or type(exc).__name__
                log.exception("Falha ao verificar a pesquisa #%s", search.id)
        # Só é recuperação se a Vinted respondeu de facto a pelo menos uma pesquisa.
        if succeeded or not searches:
            await self._on_healthy(searches)
        else:
            await self._on_all_failed(searches)

    async def _on_all_failed(self, searches: list[Search]) -> None:
        # Erros que não são bloqueio (ex.: 404 quando a Vinted muda a API) ficavam só no log.
        self._error_cycles += 1
        if self._error_cycles == ERROR_WARN_AFTER_CYCLES:
            await self._broadcast(
                searches,
                f"⚠️ Nenhuma pesquisa está a funcionar há {ERROR_WARN_AFTER_CYCLES} ciclos "
                f"(último erro: {self._last_error}). A Vinted pode ter mudado a API — vê o log.",
            )

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
        if self._error_cycles >= ERROR_WARN_AFTER_CYCLES:
            await self._broadcast(searches, "✅ As pesquisas voltaram a funcionar.")
        self._failures = 0
        self._backoff = 0
        self._error_cycles = 0
        self._last_success_at = self._wall_clock()

    async def _broadcast(self, searches: list[Search], text: str) -> None:
        for chat_id in sorted({search.chat_id for search in searches}):
            try:
                await self._notifier.send_text(chat_id, text)
            except Exception:
                log.exception("Falha ao enviar aviso para %s", chat_id)
