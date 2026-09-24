from telegram.error import BadRequest

from tests.fakes import FakeBot, make_item
from vintedbot.storage import Storage
from vintedbot.telegram_bot import TelegramNotifier, format_caption
from vintedbot.vinted.url_parser import parse_search_url

URL = "https://www.vinted.pt/catalog?search_text=nike"


def _search(name="Nike <42>"):
    return Storage().add_search(1, name, URL, parse_search_url(URL))


def test_caption_escapes_html_and_skips_empty_details():
    item = make_item(1, title="Casaco <novo> & bonito", price="12.5", brand="", size="M")
    caption = format_caption(_search(), item)
    assert caption == "<b>Casaco &lt;novo&gt; &amp; bonito</b>\n💶 12.5 EUR\nM\n🔎 Nike &lt;42&gt;"


def test_caption_truncates_long_titles():
    caption = format_caption(_search("x"), make_item(1, title="a" * 500))
    assert len(caption) < 1024


async def test_item_with_photo_is_sent_as_photo_with_button():
    bot = FakeBot()
    await TelegramNotifier(bot).send_item(1, _search(), make_item(1, photo_url="https://img/1.jpg"))
    kind, chat_id, _, markup = bot.sent[0]
    assert (kind, chat_id) == ("photo", 1)
    assert markup.inline_keyboard[0][0].url == "https://www.vinted.pt/items/1"


async def test_item_without_photo_is_sent_as_message():
    bot = FakeBot()
    await TelegramNotifier(bot).send_item(1, _search(), make_item(1, photo_url=None))
    assert bot.sent[0][0] == "message"


async def test_rejected_photo_falls_back_to_message():
    bot = FakeBot(photo_error=BadRequest("wrong file identifier"))
    await TelegramNotifier(bot).send_item(1, _search(), make_item(1, photo_url="https://img/bad.jpg"))
    assert [s[0] for s in bot.sent] == ["message"]


async def test_item_without_url_has_no_button():
    bot = FakeBot()
    await TelegramNotifier(bot).send_item(1, _search(), make_item(1, url=""))
    assert bot.sent[0][3] is None


async def test_retry_after_waits_and_retries_once(monkeypatch):
    from telegram.error import RetryAfter

    import vintedbot.telegram_bot as tb

    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(tb.asyncio, "sleep", fake_sleep)
    bot = FakeBot()
    original = bot.send_photo
    calls = []

    async def flaky_send_photo(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RetryAfter(3)
        await original(**kwargs)

    bot.send_photo = flaky_send_photo
    await TelegramNotifier(bot).send_item(1, _search(), make_item(1, photo_url="https://img/1.jpg"))
    assert [s[0] for s in bot.sent] == ["photo"]
    assert slept and slept[0] >= 3
