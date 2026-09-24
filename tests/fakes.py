from vintedbot.vinted.models import Item


def make_item(item_id: int, **overrides) -> Item:
    fields = dict(
        id=item_id,
        title=f"Item {item_id}",
        price="10.0",
        currency="EUR",
        size="M",
        brand="Nike",
        url=f"https://www.vinted.pt/items/{item_id}",
        photo_url=None,
    )
    fields.update(overrides)
    return Item(**fields)
