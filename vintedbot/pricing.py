from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html import escape

from vintedbot.storage import Search
from vintedbot.vinted.client import VintedError
from vintedbot.vinted.models import Item
from vintedbot.vinted.url_parser import SearchQuery

log = logging.getLogger(__name__)

MAX_COMPARABLES = 30
CLAUDE_TIMEOUT_S = 180
MAX_REASON = 1500

VERDICT_EMOJI = {"bom negócio": "🟢", "preço justo": "🟡", "caro": "🔴", "incerto": "⚪"}

SYSTEM_PROMPT = (
    "És um avaliador de preços de artigos em segunda mão vendidos na Vinted. "
    "Respondes sempre em português de Portugal, de forma concisa."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "veredicto": {"type": "string", "enum": list(VERDICT_EMOJI)},
        "preco_justo_min": {"type": "number"},
        "preco_justo_max": {"type": "number"},
        "comparaveis": {"type": "integer", "description": "Quantos anúncios da lista são de facto comparáveis"},
        "razao": {"type": "string", "description": "No máximo 3 frases"},
    },
    "required": ["veredicto", "preco_justo_min", "preco_justo_max", "comparaveis", "razao"],
}


class PriceCheckError(Exception):
    pass


@dataclass(frozen=True)
class PriceVerdict:
    verdict: str
    fair_min: float
    fair_max: float
    comparables: int
    reason: str


class RecentItems:
    """Artigos alertados recentemente, para o botão «Avaliar preço» (perdem-se ao reiniciar)."""

    def __init__(self, max_items: int = 500) -> None:
        self._items: OrderedDict[int, tuple[Search, Item]] = OrderedDict()
        self._max_items = max_items

    def remember(self, search: Search, item: Item) -> None:
        self._items[item.id] = (search, item)
        self._items.move_to_end(item.id)
        while len(self._items) > self._max_items:
            self._items.popitem(last=False)

    def get(self, item_id: int) -> tuple[Search, Item] | None:
        return self._items.get(item_id)


def _describe(item: Item) -> str:
    price = f"{item.price} {item.currency}"
    if item.total_price and item.total_price != item.price:
        price += f" ({item.total_price} {item.currency} com proteção do comprador)"
    details = " · ".join(part for part in (item.brand, item.size) if part)
    return " | ".join(part for part in (item.title, price, details, item.country) if part)


def build_prompt(search: Search, item: Item, others: list[Item]) -> str:
    lines = [
        "Avalia se o preço deste anúncio da Vinted é bom face ao mercado.",
        "",
        f"Anúncio: {_describe(item)}",
        f"Encontrado pela pesquisa «{search.name}» em {search.domain}.",
        "",
        "Outros anúncios ativos na Vinted com um título parecido "
        "(alguns podem não ser comparáveis — edições diferentes, outros artigos, lotes; ignora esses):",
    ]
    lines += [f"- {_describe(other)}" for other in others] or ["(nenhum)"]
    lines += [
        "",
        "Os preços da Vinted são pedidos, não vendas. Se ajudar, pesquisa na web o preço novo atual "
        "em Portugal. Dá o intervalo de preço justo em segunda mão na mesma moeda do anúncio.",
    ]
    return "\n".join(lines)


def run_claude(prompt: str, *, binary: str, model: str) -> dict:
    """Corre o Claude CLI em modo não interativo e devolve a resposta estruturada (bloqueante)."""
    cmd = [
        binary, "-p",
        "--output-format", "json",
        "--model", model,
        "--tools", "WebSearch",
        "--allowedTools", "WebSearch",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--setting-sources", "",
        "--system-prompt", SYSTEM_PROMPT,
        "--json-schema", json.dumps(SCHEMA, ensure_ascii=False),
    ]  # fmt: skip
    try:
        done = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=CLAUDE_TIMEOUT_S
        )
    except FileNotFoundError as exc:
        raise PriceCheckError("não encontrei o comando claude") from exc
    except subprocess.TimeoutExpired as exc:
        raise PriceCheckError("o Claude demorou demasiado") from exc
    try:
        data = json.loads(done.stdout)
    except ValueError as exc:
        log.warning("Saída inesperada do claude (código %s): %s", done.returncode, (done.stderr or done.stdout)[:500])
        raise PriceCheckError("resposta inválida do Claude") from exc
    if data.get("is_error") or not isinstance(data.get("structured_output"), dict):
        raise PriceCheckError(f"o Claude falhou: {str(data.get('result') or data.get('subtype'))[:200]}")
    return data["structured_output"]


def claude_runner(binary: str, model: str) -> Callable[[str], Awaitable[dict]]:
    async def run(prompt: str) -> dict:
        # Numa thread: o event loop Selector do Windows não suporta subprocessos asyncio.
        return await asyncio.to_thread(run_claude, prompt, binary=binary, model=model)

    return run


class PriceChecker:
    def __init__(self, client, runner: Callable[[str], Awaitable[dict]]) -> None:
        self._client = client
        self._runner = runner
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    async def check(self, search: Search, item: Item) -> PriceVerdict:
        async with self._lock:
            query = SearchQuery(domain=search.domain, params={"search_text": item.title, "order": "relevance"})
            others = [other for other in await self._client.search(query) if other.id != item.id]
            answer = await self._runner(build_prompt(search, item, others[:MAX_COMPARABLES]))
        try:
            return PriceVerdict(
                verdict=str(answer["veredicto"]),
                fair_min=float(answer["preco_justo_min"]),
                fair_max=float(answer["preco_justo_max"]),
                comparables=int(answer["comparaveis"]),
                reason=str(answer["razao"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PriceCheckError("resposta incompleta do Claude") from exc


def _money(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def format_verdict(item: Item, verdict: PriceVerdict) -> str:
    emoji = VERDICT_EMOJI.get(verdict.verdict, "⚪")
    currency = escape(item.currency)
    price = f"{escape(item.price)} {currency}"
    if item.total_price and item.total_price != item.price:
        price += f" ({escape(item.total_price)} {currency} c/ proteção)"
    reason = verdict.reason if len(verdict.reason) <= MAX_REASON else verdict.reason[: MAX_REASON - 1] + "…"
    return "\n".join(
        [
            f"{emoji} <b>{escape(verdict.verdict.capitalize())}</b>: {price}",
            f"💰 Valor de mercado: {_money(verdict.fair_min)}–{_money(verdict.fair_max)} {currency}"
            f" · {verdict.comparables} anúncios comparáveis",
            escape(reason),
        ]
    )


async def price_check_reply(checker: PriceChecker, recent: RecentItems, item_id: int) -> str:
    """Texto (HTML) a enviar ao carregar em «Avaliar preço». Nunca lança."""
    remembered = recent.get(item_id)
    if remembered is None:
        return "Já não tenho os dados deste anúncio (o bot foi reiniciado entretanto). Abre-o na Vinted."
    search, item = remembered
    try:
        verdict = await checker.check(search, item)
    except (PriceCheckError, VintedError) as exc:
        return f"❌ Não consegui avaliar o preço: {escape(str(exc))}"
    except Exception:
        log.exception("Falha ao avaliar o preço do artigo %s", item_id)
        return "❌ Não consegui avaliar o preço (erro inesperado, vê o log)."
    return format_verdict(item, verdict)
