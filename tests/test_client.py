import json
from pathlib import Path

import pytest

from tests.fakes import FakeResponse, FakeSession
from vintedbot.vinted.client import PER_PAGE, VintedBlockedError, VintedClient, VintedError
from vintedbot.vinted.url_parser import parse_search_url

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "catalog_items.json").read_text(encoding="utf-8"))
QUERY = parse_search_url("https://www.vinted.pt/catalog?search_text=nike")
API = "https://www.vinted.pt/web/gateway/svc-catalogue/items"


async def test_first_search_warms_up_then_fetches_items():
    session = FakeSession([FakeResponse(200), FakeResponse(200, PAYLOAD)])
    items = await VintedClient(session).search(QUERY)
    assert [i.id for i in items] == [5001, 5000]
    assert items[0].url == "https://www.vinted.pt/items/5001-sapatilhas"
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


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failure_renews_session_and_retries_once(status):
    session = FakeSession([FakeResponse(200), FakeResponse(status), FakeResponse(200), FakeResponse(200, PAYLOAD)])
    items = await VintedClient(session).search(QUERY)
    assert len(items) == 2
    assert [c[0] for c in session.calls] == ["https://www.vinted.pt/", API, "https://www.vinted.pt/", API]


async def test_401_twice_is_an_error():
    session = FakeSession([FakeResponse(200), FakeResponse(401), FakeResponse(200), FakeResponse(401)])
    with pytest.raises(VintedError):
        await VintedClient(session).search(QUERY)


async def test_429_raises_blocked_error_without_retry():
    session = FakeSession([FakeResponse(200), FakeResponse(429)])
    with pytest.raises(VintedBlockedError) as exc:
        await VintedClient(session).search(QUERY)
    assert exc.value.status == 429
    assert len(session.calls) == 2


async def test_403_after_fresh_session_is_blocked():
    session = FakeSession([FakeResponse(200), FakeResponse(403), FakeResponse(200), FakeResponse(403)])
    with pytest.raises(VintedBlockedError) as exc:
        await VintedClient(session).search(QUERY)
    assert exc.value.status == 403


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
