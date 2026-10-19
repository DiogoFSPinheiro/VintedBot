from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    id: int
    title: str
    price: str
    currency: str
    size: str
    brand: str
    url: str
    photo_url: str | None
    # Preço com a proteção do comprador (o que se paga de facto); "" quando a API não o devolve.
    total_price: str = ""

    @classmethod
    def from_api(cls, data: dict, base_url: str = "") -> Item:
        price = data.get("price")
        if isinstance(price, dict):
            amount = str(price.get("amount") or "")
            currency = price.get("currency_code") or ""
        else:
            amount = str(price or "")
            currency = data.get("currency") or ""
        total = data.get("total_item_price")
        total_amount = str(total.get("amount") or "") if isinstance(total, dict) else ""
        photo = data.get("photo") or {}
        box = data.get("item_box") or {}
        title = data.get("title") or ""
        # Sem marca, a Vinted põe o título no first_line: não é uma marca.
        first_line = box.get("first_line") or ""
        if first_line == title:
            first_line = ""
        url = data.get("url") or ""
        if url.startswith("/"):
            url = base_url + url
        return cls(
            id=int(data["id"]),
            title=title,
            price=amount,
            currency=currency,
            size=box.get("second_line") or data.get("size_title") or "",
            brand=first_line or data.get("brand_title") or "",
            url=url,
            photo_url=photo.get("url"),
            total_price=total_amount,
        )
