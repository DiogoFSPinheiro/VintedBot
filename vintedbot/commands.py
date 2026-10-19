from __future__ import annotations

from datetime import datetime

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
    "/status – ver se o bot está a funcionar\n"
    "/id – mostrar o chat id"
)


def _hhmm(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M")


def _parse_id(args: list[str]) -> int | None:
    if len(args) != 1:
        return None
    raw = args[0].lstrip("#")
    return int(raw) if raw.isdigit() else None


class Commands:
    def __init__(self, storage: Storage, monitor, *, poll_interval: int) -> None:
        self._storage = storage
        self._monitor = monitor
        self._poll_interval = poll_interval

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

    def status(self, chat_id: int) -> str:
        status = self._monitor.status()
        if status.last_success_at is None:
            lines = ["⏳ Ainda nenhum ciclo com sucesso desde o arranque."]
        else:
            minutes = int((status.now - status.last_success_at) // 60)
            ago = f"há {minutes} min" if minutes else "há menos de 1 min"
            lines = [f"✅ Último ciclo com sucesso: {_hhmm(status.last_success_at)} ({ago})"]
        if status.error_cycles:
            lines.append(f"⚠️ {status.error_cycles} ciclos seguidos com erro ({status.last_error})")
        if status.blocked_until is not None:
            lines.append(f"⏳ Em pausa por bloqueio até {_hhmm(status.blocked_until)}")
        searches = self._storage.list_searches(chat_id=chat_id)
        active = sum(1 for search in searches if search.active)
        lines.append(f"Pesquisas ativas: {active} de {len(searches)}")
        lines.append(f"Intervalo: {self._poll_interval} s")
        return "\n".join(lines)
