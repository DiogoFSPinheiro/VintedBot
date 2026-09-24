import json
from pathlib import Path

from vintedbot.vinted.models import Item

FIXTURE = Path(__file__).parent / "fixtures" / "catalog_items.json"


def _raw_items():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]


def test_from_api_current_format_with_item_box_and_relative_url():
    item = Item.from_api(_raw_items()[0], base_url="https://www.vinted.pt")
    assert item == Item(
        id=5001,
        title="Sapatilhas Nike Air <novo> & bonito",
        price="25.0",
        currency="EUR",
        size="42 · Muito bom",
        brand="Nike",
        url="https://www.vinted.pt/items/5001-sapatilhas",
        photo_url="https://images1.vinted.net/t/5001.jpeg",
    )


def test_from_api_with_legacy_price_and_no_photo():
    item = Item.from_api(_raw_items()[1])
    assert item.price == "12.5"
    assert item.currency == "EUR"
    assert item.brand == ""
    assert item.size == "M"
    assert item.url == "https://www.vinted.pt/items/5000-casaco"
    assert item.photo_url is None


def test_from_api_tolerates_missing_optional_fields():
    item = Item.from_api({"id": "7"})
    assert item.id == 7
    assert item.title == ""
    assert item.price == ""
    assert item.photo_url is None
