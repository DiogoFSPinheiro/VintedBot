from tests.fakes import FakeClient, FakeNotifier, make_item
from vintedbot.monitor import (
    BASE_BACKOFF_S,
    ERROR_WARN_AFTER_CYCLES,
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
    monitor = Monitor(storage, client, notifier, clock=clock, wall_clock=clock, sleep=_no_sleep)
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


async def test_failed_cycle_after_block_is_not_a_recovery():
    blocked = [VintedBlockedError(403) for _ in range(WARN_AFTER_FAILURES)]
    storage, client, notifier, clock, monitor = _setup(blocked + [VintedError("timeout"), [make_item(1)]])
    _add(storage)
    wait = BASE_BACKOFF_S
    for _ in range(WARN_AFTER_FAILURES):
        await monitor.run_cycle()
        clock.now += wait
        wait = min(wait * 2, MAX_BACKOFF_S)
    assert len(notifier.texts) == 1  # aviso de bloqueio
    await monitor.run_cycle()  # erro de rede: nada correu bem
    assert len(notifier.texts) == 1
    clock.now += MAX_BACKOFF_S
    await monitor.run_cycle()
    assert "voltou" in notifier.texts[-1][1]
    assert len(notifier.texts) == 2


async def test_old_item_entering_the_first_page_is_not_alerted():
    # O 2 estava fora da 1.ª página ao primar; entra quando o 3 é vendido.
    storage, _, notifier, _, monitor = _setup([[make_item(5), make_item(4), make_item(3)], [make_item(6), make_item(5), make_item(4), make_item(2)]])
    _add(storage)
    await monitor.run_cycle()
    await monitor.run_cycle()
    assert [item.id for _, _, item in notifier.items] == [6]


async def test_all_searches_failing_warns_once_and_recovers():
    errors = [VintedError("HTTP 404") for _ in range(ERROR_WARN_AFTER_CYCLES + 1)]
    storage, _, notifier, _, monitor = _setup(errors + [[make_item(1)]])
    _add(storage)
    for _ in range(ERROR_WARN_AFTER_CYCLES - 1):
        await monitor.run_cycle()
    assert notifier.texts == []
    await monitor.run_cycle()
    assert len(notifier.texts) == 1
    assert "HTTP 404" in notifier.texts[0][1]
    await monitor.run_cycle()  # continua a falhar: não repete o aviso
    assert len(notifier.texts) == 1
    await monitor.run_cycle()
    assert len(notifier.texts) == 2
    assert "voltaram" in notifier.texts[1][1]


async def test_partial_failure_is_not_warned():
    responses = []
    for _ in range(ERROR_WARN_AFTER_CYCLES):
        responses += [VintedError("HTTP 404"), [make_item(1)]]
    storage, _, notifier, _, monitor = _setup(responses)
    _add(storage, text="a")
    _add(storage, text="b")
    for _ in range(ERROR_WARN_AFTER_CYCLES):
        await monitor.run_cycle()
    assert notifier.texts == []


async def test_status_tracks_success_errors_and_backoff():
    storage, _, _, clock, monitor = _setup([[make_item(1)], VintedError("HTTP 404"), VintedBlockedError(429)])
    _add(storage)
    assert monitor.status().last_success_at is None

    await monitor.run_cycle()
    status = monitor.status()
    assert status.last_success_at == clock.now
    assert status.error_cycles == 0

    clock.now += 100
    await monitor.run_cycle()
    status = monitor.status()
    assert status.last_success_at == clock.now - 100
    assert (status.error_cycles, status.last_error) == (1, "HTTP 404")
    assert status.blocked_until is None

    await monitor.run_cycle()
    assert monitor.status().blocked_until == clock.now + BASE_BACKOFF_S
