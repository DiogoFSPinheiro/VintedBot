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


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Devolve respostas por ordem. Um item Exception na lista é lançado em vez de devolvido."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append((url, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        pass
