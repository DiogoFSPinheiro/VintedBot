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

    @classmethod
    def from_api(cls, data: dict) -> Item:
        price = data.get("price")
        if isinstance(price, dict):
            amount = str(price.get("amount") or "")
            currency = price.get("currency_code") or ""
        else:
            amount = str(price or "")
            currency = data.get("currency") or ""
        photo = data.get("photo") or {}
        return cls(
            id=int(data["id"]),
            title=data.get("title") or "",
            price=amount,
            currency=currency,
            size=data.get("size_title") or "",
            brand=data.get("brand_title") or "",
            url=data.get("url") or "",
            photo_url=photo.get("url"),
        )
