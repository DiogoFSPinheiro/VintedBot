import json
import subprocess

import pytest

from tests.fakes import FakeClient, make_item
from vintedbot.pricing import (
    PriceCheckError,
    PriceChecker,
    PriceVerdict,
    RecentItems,
    format_verdict,
    price_check_reply,
    run_claude,
)
from vintedbot.storage import Storage
from vintedbot.vinted.client import VintedError
from vintedbot.vinted.url_parser import parse_search_url

URL = "https://www.vinted.pt/catalog?search_text=xenoblade"
ANSWER = {
    "veredicto": "preço justo",
    "preco_justo_min": 29,
    "preco_justo_max": 36.5,
    "comparaveis": 6,
    "razao": "Está no meio dos <comparáveis>.",
}


def _search():
    return Storage().add_search(1, "Xenoblade", URL, parse_search_url(URL))


class FakeRunner:
    def __init__(self, answer=ANSWER, error=None):
        self.prompts = []
        self.answer = answer
        self.error = error

    async def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.answer


ITEM = make_item(1, title="Xenoblade Chronicles 3", price="34.99", total_price="37.44", brand="", size="Muito bom")


async def test_check_searches_title_and_sends_comparables_to_claude():
    others = [ITEM, make_item(2, title="Xenoblade Collector", price="90.0")]
    client = FakeClient([others])
    runner = FakeRunner()
    verdict = await PriceChecker(client, runner).check(_search(), ITEM)

    query = client.queries[0]
    assert query.domain == "www.vinted.pt"
    assert query.params == {"search_text": "Xenoblade Chronicles 3", "order": "relevance"}
    prompt = runner.prompts[0]
    assert "Xenoblade Chronicles 3" in prompt and "37.44" in prompt and "Muito bom" in prompt
    assert "Xenoblade Collector | 90.0 EUR" in prompt
    assert prompt.count("Xenoblade Chronicles 3") == 1  # o próprio anúncio não é comparável
    assert verdict == PriceVerdict("preço justo", 29, 36.5, 6, "Está no meio dos <comparáveis>.")


async def test_check_with_malformed_answer_raises():
    with pytest.raises(PriceCheckError):
        await PriceChecker(FakeClient([[]]), FakeRunner(answer={"veredicto": "x"})).check(_search(), ITEM)


def test_format_verdict_escapes_and_formats_prices():
    text = format_verdict(ITEM, PriceVerdict("preço justo", 29, 36.5, 6, "Está no meio dos <comparáveis>."))
    assert text == (
        "📦 Xenoblade Chronicles 3\n"
        "🟡 <b>Preço justo</b>: 34.99 EUR (37.44 EUR c/ proteção)\n"
        "💰 Valor de mercado: 29–36.5 EUR · 6 anúncios comparáveis\n"
        "Está no meio dos &lt;comparáveis&gt;."
    )


async def test_reply_for_unknown_item_explains_restart():
    checker = PriceChecker(FakeClient([]), FakeRunner())
    assert "reiniciado" in await price_check_reply(checker, RecentItems(), 99)


async def test_reply_reports_errors():
    recent = RecentItems()
    recent.remember(_search(), ITEM)
    checker = PriceChecker(FakeClient([VintedError("HTTP 404")]), FakeRunner())
    assert "❌" in await price_check_reply(checker, recent, ITEM.id)
    checker = PriceChecker(FakeClient([[]]), FakeRunner(error=PriceCheckError("o Claude demorou demasiado")))
    assert "o Claude demorou demasiado" in await price_check_reply(checker, recent, ITEM.id)


async def test_reply_with_verdict():
    recent = RecentItems()
    recent.remember(_search(), ITEM)
    reply = await price_check_reply(PriceChecker(FakeClient([[]]), FakeRunner()), recent, ITEM.id)
    assert "🟡 <b>Preço justo</b>" in reply


def test_recent_items_forgets_oldest():
    recent = RecentItems(max_items=2)
    search = _search()
    for item_id in (1, 2, 3):
        recent.remember(search, make_item(item_id))
    assert recent.get(1) is None
    assert recent.get(3)[1].id == 3


class Completed:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_run_claude_returns_structured_output(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Completed(json.dumps({"is_error": False, "structured_output": ANSWER}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_claude("prompt", binary="claude", model="sonnet") == ANSWER
    cmd, kwargs = calls[0]
    assert cmd[:2] == ["claude", "-p"]
    assert "--json-schema" in cmd and "--strict-mcp-config" in cmd
    assert kwargs["input"] == "prompt"


@pytest.mark.parametrize(
    "outcome",
    [
        FileNotFoundError("claude"),
        subprocess.TimeoutExpired("claude", 180),
        Completed("not json"),
        Completed(json.dumps({"is_error": True, "result": "Not logged in"})),
        Completed("", returncode=1, stderr="boom"),
    ],
)
def test_run_claude_failures_raise_price_check_error(monkeypatch, outcome):
    def fake_run(cmd, **kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(PriceCheckError):
        run_claude("prompt", binary="claude", model="sonnet")
