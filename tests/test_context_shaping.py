import json
import pathlib

from core import context

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_resolve_id_handles_table_shape():
    # multiple matches -> {headers, rows} columnar table (live-verified 2026-06-16)
    search = load_fixture("cmc_mcp_search_sample.json")
    assert context.resolve_id(search, "usdc") == "3408"
    assert context.resolve_id(search, "USDC.E") == "9999"
    assert context.resolve_id(search, "DAI") is None


def test_resolve_id_handles_list_shape():
    # single/few matches -> plain list of objects (live-verified 2026-06-16)
    search = [{"id": 3408, "name": "USDC", "symbol": "USDC",
               "slug": "usd-coin", "rank": 6}]
    assert context.resolve_id(search, "usdc") == "3408"
    assert context.resolve_id(search, "DAI") is None


def test_resolve_id_empty_inputs_return_none():
    assert context.resolve_id([], "USDC") is None
    assert context.resolve_id({}, "USDC") is None
    assert context.resolve_id(None, "USDC") is None


def test_shape_news_maps_rows_and_drops_missing_urls():
    news = context.shape_news(load_fixture("cmc_mcp_news_sample.json"))
    assert [n["title"] for n in news] == [
        "USDC reserves attested", "Stablecoin bill advances"]
    assert news[0] == {
        "title": "USDC reserves attested",
        "date": "11 June 2026 12:43 AM UTC+0",
        "url": "https://example.com/usdc-attestation",
    }


def test_shape_news_tolerates_junk():
    assert context.shape_news({}) == []
    assert context.shape_news({"headers": ["title"], "rows": None}) == []


def test_extract_fear_greed():
    metrics = load_fixture("cmc_mcp_global_metrics_sample.json")
    assert context.extract_fear_greed(metrics) == {
        "value": 15, "classification": "Extreme fear"}
    assert context.extract_fear_greed({}) is None


def test_shape_narratives():
    narratives = context.shape_narratives(
        load_fixture("cmc_mcp_narratives_sample.json"))
    assert narratives == [
        {"rank": 1, "name": "Real World Assets",
         "url": "https://coinmarketcap.com/view/rwa"},
        {"rank": 2, "name": "Stablecoins",
         "url": "https://coinmarketcap.com/view/stablecoins"},
    ]
    assert context.shape_narratives({}) == []
