from tests.fakes import FakeMonitor
from vintedbot.commands import Commands
from vintedbot.storage import Storage
from vintedbot.vinted.client import VintedBlockedError

URL = "https://www.vinted.pt/catalog?search_text=nike+air&price_to=30"


def _commands(monitor=None):
    storage = Storage()
    return storage, Commands(storage, monitor or FakeMonitor())


async def test_add_stores_search_and_primes_it():
    monitor = FakeMonitor()
    storage, commands = _commands(monitor)
    reply = await commands.add(1, [URL])
    assert "#1" in reply and "nike air" in reply
    assert storage.get_search(1).name == "nike air"
    assert monitor.checked == [1]


async def test_add_uses_custom_name():
    storage, commands = _commands()
    await commands.add(1, [URL, "Sapatilhas", "baratas"])
    assert storage.get_search(1).name == "Sapatilhas baratas"


async def test_add_without_args_shows_usage():
    _, commands = _commands()
    assert "Uso" in await commands.add(1, [])


async def test_add_invalid_url_stores_nothing():
    storage, commands = _commands()
    reply = await commands.add(1, ["https://www.vinted.pt/items/1-casaco"])
    assert reply.startswith("❌")
    assert storage.list_searches() == []


async def test_add_when_vinted_fails_still_stores():
    storage, commands = _commands(FakeMonitor(error=VintedBlockedError(429)))
    reply = await commands.add(1, [URL])
    assert "próximo ciclo" in reply
    assert len(storage.list_searches()) == 1


async def test_list_shows_status():
    storage, commands = _commands()
    assert "Ainda não tens" in commands.list(1)
    await commands.add(1, [URL])
    await commands.add(1, [URL, "outra"])
    commands.set_active(1, ["2"], False)
    assert commands.list(1) == "#1 ▶️ nike air\n#2 ⏸ outra"


async def test_remove():
    storage, commands = _commands()
    await commands.add(1, [URL])
    assert "Uso" in commands.remove(1, [])
    assert "Uso" in commands.remove(1, ["abc"])
    assert "não existe" in commands.remove(2, ["1"])  # pesquisa de outro chat
    assert "removida" in commands.remove(1, ["1"])
    assert storage.list_searches() == []


async def test_pause_and_resume():
    storage, commands = _commands()
    await commands.add(1, [URL])
    assert "pausa" in commands.set_active(1, ["1"], False)
    assert storage.get_search(1).active is False
    assert "retomada" in commands.set_active(1, ["#1"], True)
    assert storage.get_search(1).active is True
    assert "não existe" in commands.set_active(1, ["9"], True)
