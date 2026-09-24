from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

_HOST_RE = re.compile(r"(?:www\.)?vinted\.[a-z]{2,3}(?:\.[a-z]{2})?")
_PATH_RE = re.compile(r"/catalog(?:/(\d+)(?:-[^/]*)?)?/?")
_IGNORED = {"page", "per_page", "order", "time", "search_id", "disabled_personalization"}


class InvalidSearchUrl(ValueError):
    pass


@dataclass(frozen=True)
class SearchQuery:
    domain: str
    params: dict[str, str]


def parse_search_url(url: str) -> SearchQuery:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not _HOST_RE.fullmatch(host):
        raise InvalidSearchUrl("Isto não é um URL da Vinted.")
    path_match = _PATH_RE.fullmatch(parts.path)
    if not path_match:
        raise InvalidSearchUrl("Cola o URL de uma pesquisa (página /catalog), não de um artigo ou perfil.")
    if not host.startswith("www."):
        host = "www." + host

    lists: dict[str, list[str]] = {}
    params: dict[str, str] = {}
    for key, value in parse_qsl(parts.query):
        if key.endswith("[]"):
            attribute = key[:-2].removesuffix("_ids")
            lists.setdefault(attribute, []).append(value)
        elif key not in _IGNORED:
            params[key] = value
    if path_match.group(1) and "catalog" not in lists:
        lists["catalog"] = [path_match.group(1)]
    for attribute, values in lists.items():
        params[f"attribute_ids[{attribute}]"] = ",".join(values)
    params["order"] = "newest_first"
    return SearchQuery(domain=host, params=params)
