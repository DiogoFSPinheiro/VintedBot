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
        self._locales: dict[str, str] = {}
        self._countries: dict[int, str] = {}

    async def search(self, query: SearchQuery) -> list[Item]:
        if query.domain not in self._warm:
            await self._warm_up(query.domain)
        response = await self._get_items(query)
        if response.status_code in _AUTH_FAILURES:
            # Cookies antigos podem impedir a renovação do token: recomeça do zero, como no arranque.
            self._session.cookies.clear()
            self._warm.clear()
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

    async def seller_country(self, domain: str, seller_id: int) -> str | None:
        """País do vendedor (ex.: «🇫🇷 França»), ou None se não for possível saber. Nunca lança."""
        if seller_id in self._countries:
            return self._countries[seller_id]
        try:
            response = await self._get(f"https://{domain}/api/v2/users/{seller_id}")
            if response.status_code != 200:
                return None
            user = response.json().get("user") or {}
        except (VintedError, ValueError, AttributeError):
            return None
        title = user.get("country_title_local") or user.get("country_title")
        if not title:
            return None
        code = (user.get("country_iso_code") or "").upper()
        flag = "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code) if len(code) == 2 and code.isalpha() else ""
        country = f"{flag} {title}".strip()
        self._countries[seller_id] = country
        return country

    async def close(self) -> None:
        await self._session.close()

    async def _warm_up(self, domain: str) -> None:
        response = await self._get(f"https://{domain}/")
        if response.status_code in _BLOCKED:
            raise VintedBlockedError(response.status_code)
        self._warm.add(domain)
        # A homepage define a língua do site neste cookie (ex.: pt-PT em vinted.pt).
        for cookie in self._session.cookies.jar:
            if cookie.name == "anonymous-iso-locale" and cookie.domain.lstrip(".") == domain:
                self._locales[domain] = cookie.value

    async def _get_items(self, query: SearchQuery):
        params = {**query.params, "page": "1", "per_page": str(PER_PAGE)}
        # A gateway saiu de /web/gateway para o subdomínio api.<domínio> (out/2026).
        api_host = "api." + query.domain.removeprefix("www.")
        # Sem o header Locale a gateway devolve os textos (ex.: estado do artigo) em francês.
        locale = self._locales.get(query.domain)
        headers = {"Locale": locale} if locale else None
        return await self._get(f"https://{api_host}/svc-catalogue/items", params, headers)

    async def _get(self, url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None):
        try:
            return await self._session.get(url, params=params, headers=headers)
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
