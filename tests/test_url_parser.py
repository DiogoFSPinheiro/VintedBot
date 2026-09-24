import pytest

from vintedbot.vinted.url_parser import InvalidSearchUrl, SearchQuery, parse_search_url


def test_full_search_url_maps_to_api_params():
    q = parse_search_url(
        "https://www.vinted.pt/catalog?search_text=nike%20air&catalog[]=1206"
        "&brand_ids[]=53&brand_ids[]=14&size_ids[]=207&price_from=5&price_to=30"
        "&currency=EUR&status_ids[]=6&order=relevance&time=1727180000&page=2"
    )
    assert q == SearchQuery(
        domain="www.vinted.pt",
        params={
            "search_text": "nike air",
            "attribute_ids[catalog]": "1206",
            "attribute_ids[brand]": "53,14",
            "attribute_ids[size]": "207",
            "price_from": "5",
            "price_to": "30",
            "currency": "EUR",
            "attribute_ids[status]": "6",
            "order": "newest_first",
        },
    )


def test_url_encoded_brackets_are_understood():
    q = parse_search_url("https://www.vinted.fr/catalog?brand_ids%5B%5D=53&catalog%5B%5D=5")
    assert q.domain == "www.vinted.fr"
    assert q.params["attribute_ids[brand]"] == "53"
    assert q.params["attribute_ids[catalog]"] == "5"


def test_category_path_sets_catalog_ids():
    q = parse_search_url("https://www.vinted.pt/catalog/1206-men?search_text=casaco")
    assert q.params["attribute_ids[catalog]"] == "1206"
    assert q.params["search_text"] == "casaco"


def test_other_list_filters_map_to_attribute_ids():
    q = parse_search_url("https://www.vinted.pt/catalog?color_ids[]=1&color_ids[]=12&material_ids[]=44")
    assert q.params["attribute_ids[color]"] == "1,12"
    assert q.params["attribute_ids[material]"] == "44"


def test_host_without_www_is_normalised_and_multi_part_tld_accepted():
    assert parse_search_url("https://vinted.pt/catalog?search_text=x").domain == "www.vinted.pt"
    assert parse_search_url("https://www.vinted.co.uk/catalog?search_text=x").domain == "www.vinted.co.uk"


def test_whitespace_around_url_is_ignored():
    assert parse_search_url("  https://www.vinted.pt/catalog?search_text=x \n").params["search_text"] == "x"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.olx.pt/catalog?search_text=x",
        "https://www.vinted.pt.evil.com/catalog?search_text=x",
        "ftp://www.vinted.pt/catalog",
        "nike air",
    ],
)
def test_non_vinted_urls_are_rejected(url):
    with pytest.raises(InvalidSearchUrl, match="Vinted"):
        parse_search_url(url)


@pytest.mark.parametrize(
    "url",
    ["https://www.vinted.pt/items/123-casaco", "https://www.vinted.pt/member/99-joana"],
)
def test_non_search_pages_are_rejected(url):
    with pytest.raises(InvalidSearchUrl, match="pesquisa"):
        parse_search_url(url)
