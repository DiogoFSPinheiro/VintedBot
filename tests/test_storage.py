from vintedbot.storage import Storage
from vintedbot.vinted.url_parser import parse_search_url

URL = "https://www.vinted.pt/catalog?search_text=nike&brand_ids[]=53"
DAY = 86400


def _add(storage, chat_id=1, name="nike"):
    return storage.add_search(chat_id, name, URL, parse_search_url(URL))


def test_add_and_get_search_roundtrip():
    storage = Storage()
    search = _add(storage)
    assert search.id == 1
    assert search.active and not search.primed
    assert search.query == parse_search_url(URL)
    assert storage.get_search(1) == search
    assert storage.get_search(99) is None


def test_list_filters_by_chat_and_active():
    storage = Storage()
    a = _add(storage, chat_id=1)
    b = _add(storage, chat_id=2)
    storage.set_active(1, a.id, False)
    assert [s.id for s in storage.list_searches()] == [a.id, b.id]
    assert [s.id for s in storage.list_searches(chat_id=1)] == [a.id]
    assert [s.id for s in storage.list_searches(active_only=True)] == [b.id]


def test_remove_and_set_active_only_touch_own_chat():
    storage = Storage()
    search = _add(storage, chat_id=1)
    assert storage.set_active(2, search.id, False) is False
    assert storage.remove_search(2, search.id) is False
    assert storage.set_active(1, search.id, False) is True
    assert storage.get_search(search.id).active is False
    assert storage.remove_search(1, search.id) is True
    assert storage.get_search(search.id) is None


def test_mark_primed():
    storage = Storage()
    search = _add(storage)
    storage.mark_primed(search.id)
    assert storage.get_search(search.id).primed is True


def test_filter_unseen_keeps_order_and_is_per_search():
    storage = Storage()
    a = _add(storage)
    b = _add(storage)
    storage.mark_seen(a.id, [2, 4])
    assert storage.filter_unseen(a.id, [5, 4, 3, 2, 1]) == [5, 3, 1]
    assert storage.filter_unseen(b.id, [4, 2]) == [4, 2]
    assert storage.filter_unseen(a.id, []) == []


def test_removing_search_deletes_its_seen_items():
    storage = Storage()
    a = _add(storage)
    storage.mark_seen(a.id, [1])
    storage.remove_search(1, a.id)
    b = _add(storage)
    assert storage.filter_unseen(b.id, [1]) == [1]


def test_purge_removes_old_items():
    storage = Storage()
    s = _add(storage)
    storage.mark_seen(s.id, [1], now=0)
    storage.mark_seen(s.id, [2], now=35 * DAY)
    assert storage.purge_seen(30 * DAY, now=36 * DAY) == 1
    assert storage.filter_unseen(s.id, [1, 2]) == [1]


def test_mark_seen_again_refreshes_timestamp_so_item_survives_purge():
    storage = Storage()
    s = _add(storage)
    storage.mark_seen(s.id, [1], now=0)
    storage.mark_seen(s.id, [1], now=40 * DAY)
    assert storage.purge_seen(30 * DAY, now=41 * DAY) == 0
    assert storage.filter_unseen(s.id, [1]) == []


def test_data_persists_in_file(tmp_path):
    path = str(tmp_path / "bot.db")
    storage = Storage(path)
    s = _add(storage)
    storage.mark_seen(s.id, [9])
    storage.close()
    reopened = Storage(path)
    assert reopened.get_search(s.id).name == "nike"
    assert reopened.filter_unseen(s.id, [9]) == []
    reopened.close()


def test_resume_resets_priming_so_backlog_is_not_alerted():
    storage = Storage()
    s = _add(storage)
    storage.mark_primed(s.id)
    storage.set_active(1, s.id, False)
    assert storage.get_search(s.id).primed is True
    storage.set_active(1, s.id, True)
    assert storage.get_search(s.id).primed is False


def test_last_item_id_only_moves_forward():
    storage = Storage()
    s = _add(storage)
    assert s.last_item_id == 0
    storage.advance_last_item_id(s.id, 50)
    storage.advance_last_item_id(s.id, 20)
    assert storage.get_search(s.id).last_item_id == 50


def test_existing_database_is_migrated_with_last_item_id_from_seen_items(tmp_path):
    import sqlite3

    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE searches (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, name TEXT NOT NULL,
            url TEXT NOT NULL, domain TEXT NOT NULL, params_json TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, primed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE seen_items (search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL, seen_at REAL NOT NULL, PRIMARY KEY (search_id, item_id));
        INSERT INTO searches (chat_id, name, url, domain, params_json, primed) VALUES (1, 'a', 'u', 'www.vinted.pt', '{}', 1);
        INSERT INTO searches (chat_id, name, url, domain, params_json) VALUES (1, 'b', 'u', 'www.vinted.pt', '{}');
        INSERT INTO seen_items VALUES (1, 70, 0), (1, 90, 0);
        """
    )
    db.commit()
    db.close()
    storage = Storage(path)
    assert storage.get_search(1).last_item_id == 90
    assert storage.get_search(2).last_item_id == 0
    storage.close()
    Storage(path).close()  # reabrir não volta a migrar nem falha


def _alertas(storage):
    return [tuple(r) for r in storage._db.execute(
        "SELECT item_id, search_id, titulo, preco, moeda, url, enviado_em FROM alertas ORDER BY item_id")]


def test_registar_alertas_guarda_detalhes_sem_duplicados():
    from tests.fakes import make_item

    storage = Storage()
    search = _add(storage)
    item = make_item(7, title="Air Max 90", price="45.0", currency="EUR")
    storage.registar_alertas(search.id, [item], now=100.0)
    storage.registar_alertas(search.id, [item], now=200.0)
    assert _alertas(storage) == [(7, search.id, "Air Max 90", "45.0", "EUR", "https://www.vinted.pt/items/7", 100.0)]


def test_purge_alertas():
    from tests.fakes import make_item

    storage = Storage()
    search = _add(storage)
    storage.registar_alertas(search.id, [make_item(1)], now=0.0)
    storage.registar_alertas(search.id, [make_item(2)], now=40 * DAY)
    assert storage.purge_alertas(30 * DAY, now=41 * DAY) == 1
    assert [r[0] for r in _alertas(storage)] == [2]
