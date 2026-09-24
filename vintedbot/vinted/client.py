from __future__ import annotations

import asyncio
import sys

from vintedbot.vinted.models import Item
from vintedbot.vinted.url_parser import SearchQuery, parse_search_url

PER_PAGE = 30
_BLOCKED = {403, 429}
# 401/403 também acontecem quando o cookie access_token_web expira ou falta.
_AUTH_FAILURES = {401, 403}


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
        if response.status_code in _AUTH_FAILURES:
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
        base_url = f"https://{query.domain}"
        return [Item.from_api(raw, base_url) for raw in data.get("items", [])]

    async def close(self) -> None:
        await self._session.close()

    async def _warm_up(self, domain: str) -> None:
        response = await self._get(f"https://{domain}/")
        if response.status_code in _BLOCKED:
            raise VintedBlockedError(response.status_code)
        self._warm.add(domain)

    async def _get_items(self, query: SearchQuery):
        params = {**query.params, "page": "1", "per_page": str(PER_PAGE)}
        return await self._get(f"https://{query.domain}/web/gateway/svc-catalogue/items", params)

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
