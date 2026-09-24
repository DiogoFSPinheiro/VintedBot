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


class FakeClient:
    """Cada chamada a search() consome a próxima resposta: list[Item] ou Exception."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    async def search(self, query):
        self.queries.append(query)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeNotifier:
    def __init__(self, fail_item_ids=()):
        self.items = []  # (chat_id, search, item)
        self.texts = []  # (chat_id, text)
        self.fail_item_ids = set(fail_item_ids)

    async def send_item(self, chat_id, search, item):
        if item.id in self.fail_item_ids:
            raise RuntimeError("telegram down")
        self.items.append((chat_id, search, item))

    async def send_text(self, chat_id, text):
        self.texts.append((chat_id, text))


class FakeMonitor:
    def __init__(self, error=None):
        self.checked = []
        self.error = error

    async def check_search(self, search):
        self.checked.append(search.id)
        if self.error:
            raise self.error
        return 0
