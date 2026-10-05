"""Offline tests for reference resolution, marshmallow schemas, the egress
policy of the transport and the endpoint functions (fetch layer
monkeypatched — no network).

    python -m pytest indiamart/test_endpoints.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from schema_fields import load_query  # noqa: E402
from indiamart import categories, discovery, fetch, products, refs, schemas, search, suppliers  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


def load(name):
    return json.loads(raw(name))


# ---- refs ------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("11558361073", 11558361073),
    ("https://www.indiamart.com/proddetail/cnc-milling-deburring-spm-11558361073.html", 11558361073),
    ("https://m.indiamart.com/proddetail/11558361073.html?pos=1&kwd=cnc", 11558361073),
    ("//www.indiamart.com/proddetail/hygienic-pumps-24360300030.html", 24360300030),
    ("www.indiamart.com/proddetail/x-y-2853567329233.html#top", 2853567329233),
])
def test_product_ref(value, expected):
    assert refs.resolve_product_ref(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "123", "https://example.com/proddetail/x-11558361073.html",
                                   "https://www.indiamart.com/risansi/"])
def test_product_ref_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_product_ref(value)


@pytest.mark.parametrize("value,expected", [
    ("risansi", "risansi"),
    ("RISANSI", "risansi"),
    ("https://www.indiamart.com/risansi/", "risansi"),
    ("https://www.indiamart.com/vm-technology-bengaluru/testimonial.html#reviewsratings", "vm-technology-bengaluru"),
    ("https://m.indiamart.com/risansi/about-us.html", "risansi"),
    ("www.indiamart.com/risansi", "risansi"),
    ("20902177", "20902177"),
    ("https://www.indiamart.com/company/20902177/", "20902177"),
])
def test_supplier_ref(value, expected):
    assert refs.resolve_supplier_ref(value) == expected


@pytest.mark.parametrize("value", ["", "proddetail", "bad name", "https://www.patsonmachines.com/",
                                   "https://dir.indiamart.com/impcat/cnc-machines.html",
                                   "https://www.indiamart.com/", "about-us.html"])
def test_supplier_ref_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_supplier_ref(value)


@pytest.mark.parametrize("value,expected", [
    ("cnc-machines", {"slug": "cnc-machines", "city": None}),
    ("CNC Machines", {"slug": "cnc-machines", "city": None}),
    ("cnc-machines.html", {"slug": "cnc-machines", "city": None}),
    ("https://dir.indiamart.com/impcat/cnc-machines.html", {"slug": "cnc-machines", "city": None}),
    ("https://dir.indiamart.com/pune/cnc-machines.html?biz=10", {"slug": "cnc-machines", "city": "pune"}),
    ("https://m.indiamart.com/impcat/basmati-rice.html", {"slug": "basmati-rice", "city": None}),
    ("https://dir.indiamart.com/impcat/cnc-machines-q1234.html", {"slug": "cnc-machines", "city": None}),
])
def test_category_ref(value, expected):
    assert refs.resolve_category_ref(value) == expected


@pytest.mark.parametrize("value", ["", "https://example.com/impcat/x.html", "https://dir.indiamart.com/",
                                   "https://dir.indiamart.com/industry/agro-farm.html", "!!!"])
def test_category_ref_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_category_ref(value)


def test_parent_city_and_catalogue_refs():
    assert refs.resolve_parent_ref("agro-farm") == {"section": None, "slug": "agro-farm"}
    assert refs.resolve_parent_ref("https://dir.indiamart.com/industry/agro-farm.html") == {
        "section": "industry", "slug": "agro-farm"}
    assert refs.resolve_parent_ref("https://dir.indiamart.com/indianexporters/m_rcmach.html") == {
        "section": "products", "slug": "m_rcmach"}
    assert refs.resolve_parent_ref("dir.indiamart.com/indianservices/adventure-tours.html")["section"] == "services"
    with pytest.raises(ValueError):
        refs.resolve_parent_ref("https://dir.indiamart.com/impcat/cnc-machines.html")
    assert refs.resolve_city("New Delhi") == "new-delhi" and refs.resolve_city("navi-mumbai") == "navi-mumbai"
    with pytest.raises(ValueError):
        refs.resolve_city("  ")
    assert refs.resolve_supplier_category_ref("screw-pump.html") == "screw-pump"
    assert refs.resolve_supplier_category_ref(
        "https://www.indiamart.com/risansi/screw-pump.html#24360300030") == "screw-pump"
    assert refs.supplier_alias_of("https://www.indiamart.com/risansi/about-us.html") == "risansi"
    assert refs.supplier_alias_of("https://www.indiamart.com/company/1/") is None
    assert refs.tree_link("services", "x") == "https://dir.indiamart.com/indianservices/x.html"


# ---- schemas ---------------------------------------------------------------------

def test_search_schema():
    data, error = load_query(schemas.SearchSchema, {
        "query": "  cnc   machine ", "city": "New Delhi", "business_type": "Manufacturer",
        "min_price": "100", "max_price": "500", "annual_turnover": "above_5_crore",
        "gst_registration_age": "above_3_years"})
    assert error is None
    assert data == {"query": "cnc machine", "city": "new-delhi", "business_type": "manufacturer",
                    "min_price": 100.0, "max_price": 500.0, "annual_turnover": "above_5_crore",
                    "gst_registration_age": "above_3_years"}
    defaults, _ = load_query(schemas.SearchSchema, {"query": "x"})
    assert defaults == {"query": "x", "city": None, "business_type": None, "min_price": None,
                        "max_price": None, "annual_turnover": None, "gst_registration_age": None}
    for bad in ({}, {"query": " "}, {"query": "x", "business_type": "trader"}, {"query": "x", "page": "2"},
                {"query": "x", "min_price": "9", "max_price": "1"}, {"query": "x", "min_price": "-1"}):
        assert load_query(schemas.SearchSchema, bad)[0] is None


def test_category_and_supplier_schemas():
    data, _ = load_query(schemas.CategoryProductsSchema,
                         {"category": "https://dir.indiamart.com/pune/cnc-machines.html", "business_type": "exporter"})
    assert data == {"category": "cnc-machines", "city": "pune", "business_type": "exporter"}
    data, _ = load_query(schemas.CategoryProductsSchema,
                         {"category": "https://dir.indiamart.com/pune/cnc-machines.html", "city": "Mumbai"})
    assert data["city"] == "mumbai"                      # an explicit city wins over the link's
    assert load_query(schemas.CategoryDetailsSchema, {"category": "CNC Machines"})[0] == {
        "category": "cnc-machines", "city": None}
    assert load_query(schemas.CategoriesSchema, {})[0] == {"parent": None}
    data, _ = load_query(schemas.SupplierReviewsSchema, {"supplier": "https://www.indiamart.com/company/20902177/"})
    assert data == {"supplier": "20902177", "page": 1, "sort_by": "top"}
    assert load_query(schemas.SupplierReviewsSchema, {"supplier": "risansi", "sort_by": "oldest"})[0] is None
    assert load_query(schemas.SupplierReviewsSchema, {"supplier": "risansi", "page": "0"})[0] is None
    _, error = load_query(schemas.SupplierSchema, {"supplier": "https://www.patsonmachines.com/"})
    assert "own domain" in error["error"]
    assert load_query(schemas.SupplierProductsSchema, {"supplier": "risansi"})[0] is None
    assert load_query(schemas.SupplierProductsSchema, {"supplier": "risansi", "category": "Screw-Pump.html"})[0] == {
        "supplier": "risansi", "category": "screw-pump"}
    assert load_query(schemas.ProductSchema, {"product": "11558361073", "id": "1"})[0] is None   # unknown param
    assert load_query(schemas.AutocompleteSchema, {"query": "cnc", "limit": "21"})[0] is None


# ---- transport: egress policy ----------------------------------------------------

class _Resp:
    def __init__(self, status=200, text='{"ok": true}', url="https://x/"):
        self.status_code, self.text, self.url = status, text, url

    def json(self):
        return json.loads(self.text)


class _Session:
    def __init__(self, log, proxy, script):
        self.log, self.proxy, self.script = log, proxy, script

    def request(self, method, url, **kwargs):
        self.log.append(("exit" if self.proxy else "direct", self.proxy, url))
        return self.script(self.proxy, url, kwargs)

    def close(self):
        pass


@pytest.fixture
def egress(monkeypatch):
    """Fresh transport state with fake sessions; yields (log, set_script)."""
    log, state = [], {"script": lambda proxy, url, kw: _Resp(), "n": 0}

    def new_session(proxy=None):
        return _Session(log, proxy, lambda *a: state["script"](*a))

    def proxy():
        state["n"] += 1
        return f"http://exit-{state['n']}"

    monkeypatch.setattr(fetch, "_new_session", new_session)
    monkeypatch.setattr(fetch, "_local", type("L", (), {})())
    monkeypatch.setattr(fetch, "_direct_hits", fetch.collections.defaultdict(fetch.collections.deque))
    monkeypatch.setattr(fetch, "_direct_blocked_until", {})
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "INDIAMART_PROXY_COUNTRY", "in")
    monkeypatch.setattr(config, "indiamart_proxy", proxy)
    monkeypatch.setattr(config, "INDIAMART_DIRECT_PER_MINUTE", 2)
    monkeypatch.setattr(config, "INDIAMART_REQUESTS_PER_EXIT", 3)
    monkeypatch.setattr(config, "INDIAMART_MAX_ATTEMPTS", 4)
    return log, lambda script: state.__setitem__("script", script)


def test_direct_budget_then_exits_and_rotation(egress):
    log, _ = egress
    for _ in range(7):
        assert fetch.get_json(fetch.DIR + "/api/x") == {"ok": True}
    routes = [(kind, proxy) for kind, proxy, _ in log]
    assert routes[:2] == [("direct", None), ("direct", None)]             # the own-IP budget
    assert routes[2:5] == [("exit", "http://exit-1")] * 3                 # one sticky exit…
    assert routes[5:] == [("exit", "http://exit-2")] * 2                  # …retired after 3 requests
    log.clear()
    fetch.get_json(fetch.WWW + "/api/y")                                  # budgets are per host
    assert log[0][0] == "direct"


def test_429_on_own_ip_moves_the_host_to_exits(egress):
    log, set_script = egress
    set_script(lambda proxy, url, kw: _Resp(429, "429 Too Many Requests") if proxy is None else _Resp())
    assert fetch.get_json(fetch.DIR + "/api/x") == {"ok": True}
    assert [kind for kind, _, _ in log] == ["direct", "exit"]
    log.clear()
    fetch.get_json(fetch.DIR + "/api/x")
    assert [kind for kind, _, _ in log] == ["exit"]                       # still cooling down
    log.clear()
    fetch.get_json(fetch.WWW + "/other")
    assert log[0][0] == "direct"                                          # another host is unaffected


def test_blocked_exit_is_replaced_and_gives_up_as_blocked(egress, monkeypatch):
    log, set_script = egress
    monkeypatch.setattr(config, "INDIAMART_DIRECT_PER_MINUTE", 0)
    set_script(lambda proxy, url, kw: _Resp(429, "429"))
    with pytest.raises(fetch.IndiamartBlocked):
        fetch.get_json(fetch.DIR + "/api/x")
    assert [proxy for _, proxy, _ in log] == [f"http://exit-{i}" for i in range(1, 5)]


def test_no_proxy_configured_stays_direct_and_suggest_is_unmetered(egress, monkeypatch):
    log, _ = egress
    for _ in range(5):
        fetch.get_json(fetch.SUGGEST + "/suggest/suggest.php")
    assert {kind for kind, _, _ in log} == {"direct"}                     # unmetered host, budget of 2 ignored
    monkeypatch.setattr(config, "INDIAMART_PROXY_COUNTRY", None)
    log.clear()
    for _ in range(5):
        fetch.get_json(fetch.DIR + "/api/x")
    assert {kind for kind, _, _ in log} == {"direct"}


def test_status_mapping(egress):
    _, set_script = egress
    set_script(lambda proxy, url, kw: _Resp(404, "<html>nope</html>"))
    with pytest.raises(fetch.IndiamartNotFound):
        fetch.get_page(fetch.WWW + "/x/")
    set_script(lambda proxy, url, kw: _Resp(200, "<html>challenge</html>"))
    with pytest.raises(fetch.IndiamartBlocked):
        fetch.get_json(fetch.DIR + "/api/x")
    set_script(lambda proxy, url, kw: _Resp(400, '{"error_msg": "Authentication Token is missing in the URL"}'))
    with pytest.raises(fetch.IndiamartBadRequest, match="Authentication Token"):
        fetch.get_json(fetch.DIR + "/api/x")
    set_script(lambda proxy, url, kw: _Resp(503, "busy"))
    with pytest.raises(fetch.IndiamartUpstreamError):
        fetch.get_json(fetch.DIR + "/api/x")
    seen = {}
    set_script(lambda proxy, url, kw: seen.update(kw) or _Resp())
    fetch.get_json(fetch.DIR + "/api/x", {"a": 1, "b": None, "c": ""})
    assert seen["params"] == {"a": 1} and seen["headers"]["sec-fetch-site"] == "same-origin"


# ---- endpoints -------------------------------------------------------------------

def test_search_params_and_views(monkeypatch):
    calls = []

    def fake(url, params=None, **kwargs):
        calls.append((url, params, kwargs))
        return 200, load("search_basmati_rice_mumbai.json")

    monkeypatch.setattr(search, "get_json", fake)
    out = search.search_products("basmati  rice", city="navi-mumbai", business_type="exporter",
                                 min_price=50, max_price=120.5, annual_turnover="above_5_crore",
                                 gst_registration_age="1_to_3_years")
    url, params, kwargs = calls[0]
    assert url == "https://dir.indiamart.com/api/search.rp" and kwargs["raw_status"] is True
    assert params == {
        "q": "basmati rice", "page": 1, "source": "dir.search",
        "options.filters.city.data": "navi mumbai", "options.filters.biztype.data": 20,
        "options.filters.biztype.type": "value", "min-price": 50, "max-price": 120.5,
        "annualTurnover": "bucket3", "gstMinYear": 1, "gstMaxYear": 3}
    assert out["count"] == len(out["results"]) > 3 and out["total_count"] > out["count"]
    assert list(out)[:6] == ["query", "interpreted_query", "detected_city", "total_count", "count", "results"]
    assert out["results"][0]["supplier"]["gst_number"]
    grouped = search.search_suppliers("basmati rice")
    assert grouped["count"] == 3 and grouped["results"][0]["products"]
    assert calls[1][1]["options.filters.city.data"] is None and "gstMinYear" not in calls[1][1]


def test_search_errors(monkeypatch):
    monkeypatch.setattr(search, "get_json", lambda *a, **k: (400, load("search_page2_denied.json")))
    with pytest.raises(fetch.IndiamartBadRequest):
        search.search_products("x")
    monkeypatch.setattr(search, "get_json", lambda *a, **k: (200, {"unexpected": 1}))
    with pytest.raises(fetch.IndiamartUpstreamError):
        search.search_products("x")
    monkeypatch.setattr(search, "get_json", lambda *a, **k: (200, {"results": [], "total_results": 0}))
    assert search.search_products("x")["results"] == []
    for kwargs in ({"business_type": "trader"}, {"min_price": 5, "max_price": 1}, {"annual_turnover": "big"}):
        with pytest.raises(ValueError):
            search.search_products("x", **kwargs)
    with pytest.raises(ValueError):
        search.search_products("  ")


def test_discovery(monkeypatch):
    seen = []

    def fake(url, params=None, **kwargs):
        seen.append(params)
        return load({"product": "suggest_products_cnc.json", "city": "suggest_cities_pun.json",
                     "mcat": "suggest_mcat_cnc.json"}[params["type"]])

    monkeypatch.setattr(discovery, "get_json", fake)
    assert discovery.autocomplete("cnc", limit=3)["results"][0]["text"] == "cnc machine"
    assert seen[0] == {"q": "cnc", "tag": "suggestions", "limit": 3, "type": "product"}
    assert discovery.autocomplete_cities("pun")["results"][0] == {"name": "Pune", "slug": "pune"}
    assert discovery.autocomplete_categories("cnc")["results"][0] == {
        "name": "CNC Adapter", "slug": "cnc-adapter", "link": "https://dir.indiamart.com/impcat/cnc-adapter.html"}
    with pytest.raises(ValueError):
        discovery.autocomplete("cnc", limit=99)


def test_category_listing(monkeypatch):
    calls = []

    def fake(url, params=None, **kwargs):
        calls.append((url, params, kwargs.get("referer")))
        if params["flname"] == "zz":
            return load("category_missing.json")
        if params.get("city") == "atlantis":
            return load("category_cnc_machines.json")          # unknown city -> the all-India listing
        return load("category_cnc_machines_pune_manufacturer.json")

    monkeypatch.setattr(categories, "get_json", fake)
    out = categories.category_products("cnc-machines", city="pune", business_type="manufacturer")
    assert calls[0] == ("https://dir.indiamart.com/mcatAjaxRequest/ajaxData/",
                        {"flname": "cnc-machines", "isqId": 0, "city": "pune", "biz": 10},
                        "https://dir.indiamart.com/pune/cnc-machines.html")
    assert out["city"]["slug"] == "pune" and out["count"] == len(out["results"]) > 5
    assert out["results"][0]["supplier"]["id"] and out["results"][0]["is_lead_listing"] is True
    assert categories.category_products({"slug": "cnc-machines", "city": "pune"})["city"]["id"] == 70630
    with pytest.raises(fetch.IndiamartNotFound):
        categories.category_products("zz")
    with pytest.raises(ValueError, match="atlantis"):
        categories.category_products("cnc-machines", city="atlantis")
    with pytest.raises(ValueError):
        categories.category_products("cnc-machines", business_type="trader")
    assert categories.category_details("cnc-machines")["id"] == 3878


def test_category_tree(monkeypatch):
    pages = {
        "https://dir.indiamart.com/": raw("dir_home.html"),
        "https://dir.indiamart.com/industry/agro-farm.html": raw("industry_agro_farm.html"),
        "https://dir.indiamart.com/indianexporters/ac-refrigeration-equipment.html":
            raw("subcategory_ac_refrigeration_equipment.html"),
    }
    visited = []

    def fake(url, **kwargs):
        visited.append(url)
        if url not in pages:
            return "<html><script>window.__INITIAL_STATE__ = {\"scats\": [], \"mcats\": []};</script></html>", url
        return pages[url], url

    monkeypatch.setattr(categories, "get_page", fake)
    root = categories.categories()
    assert root["parent"] is None and root["level"] == "industry" and root["count"] > 40
    industry = categories.categories("agro-farm")
    assert industry["parent"]["level"] == "industry" and industry["level"] == "sub_category"
    visited.clear()
    sub = categories.categories("ac-refrigeration-equipment")           # bare slug: industry first, then sub-category
    assert visited == ["https://dir.indiamart.com/industry/ac-refrigeration-equipment.html",
                       "https://dir.indiamart.com/indianexporters/ac-refrigeration-equipment.html"]
    assert sub["level"] == "category" and sub["count"] == 12
    visited.clear()
    categories.categories({"section": "products", "slug": "ac-refrigeration-equipment"})
    assert len(visited) == 1
    with pytest.raises(fetch.IndiamartNotFound):
        categories.categories("nope")


def test_products(monkeypatch):
    html = raw("product_11558361073.html")
    monkeypatch.setattr(products, "get_page", lambda url, **k: (html, url))
    seen = {}

    def fake_json(url, params=None, **kwargs):
        seen.update(url=url, params=params)
        return load("similar_11558361073.json")

    monkeypatch.setattr(products, "get_json", fake_json)
    details = products.product_details("https://www.indiamart.com/proddetail/x-11558361073.html")
    assert details["id"] == 11558361073
    similar = products.similar_products(11558361073)
    assert seen["url"].endswith("/api/ajax-services/caps_service/")
    assert seen["params"] == {"displayid": 11558361073, "count": 20, "cityid": 70630, "mcatid": 191249,
                              "webAddLoc": "www.indiamart.com"}
    assert similar["product"]["id"] == 11558361073 and similar["count"] == 5
    monkeypatch.setattr(products, "get_page", lambda url, **k: ("<html>IndiaMART: Page not found</html>", url))
    with pytest.raises(fetch.IndiamartNotFound):
        products.product_details("11558361073")
    monkeypatch.setattr(products, "get_page", lambda url, **k: ("<html>something else</html>", url))
    with pytest.raises(fetch.IndiamartUpstreamError):
        products.product_details("11558361073")


@pytest.fixture
def storefront(monkeypatch):
    """Serve the risansi / patsonmachines fixtures as storefront pages."""
    pages = {
        "https://www.indiamart.com/risansi/": "supplier_risansi_home.html",
        "https://www.indiamart.com/company/20902177/": "supplier_risansi_home.html",
        "https://www.indiamart.com/risansi/about-us.html": "supplier_risansi_about_us.html",
        "https://www.indiamart.com/risansi/screw-pump.html": "supplier_risansi_screw_pump.html",
        "https://www.indiamart.com/risansi/registration-directors-info.html":
            "supplier_risansi_registration_directors_info.html",
        "https://www.indiamart.com/risansi/trustseal/": "supplier_risansi_trustseal.html",
        "https://www.indiamart.com/risansi/photos.html": "supplier_risansi_photos.html",
        "https://www.indiamart.com/risansi/videos.html": "supplier_risansi_videos.html",
        "https://www.indiamart.com/patsonmachines/": "supplier_patsonmachines_home.html",
        "https://www.indiamart.com/patsonmachines/cnc-spm-machines.html": "supplier_patsonmachines_cnc_spm_machines.html",
    }
    visited, encrypted = [], []

    def fake_page(url, **kwargs):
        visited.append(url)
        if url not in pages:
            raise fetch.IndiamartNotFound(f"{url} not found")
        final = "https://www.indiamart.com/risansi/" if "/company/" in url else url
        return raw(pages[url]), final

    def fake_encrypted(path, params, **kwargs):
        encrypted.append((path, params))
        return load("reviews_42011038_recent_limit40.json")

    monkeypatch.setattr(suppliers, "get_page", fake_page)
    monkeypatch.setattr(suppliers, "get_encrypted", fake_encrypted)
    monkeypatch.setattr(suppliers, "gather", lambda mapping, optional=(): {k: _quiet(fn) for k, fn in mapping.items()})
    for memo in (suppliers._ids, suppliers._aliases, suppliers._names):
        memo.clear()
    return visited, encrypted


def _quiet(fn):
    try:
        return fn()
    except (fetch.IndiamartNotFound, fetch.IndiamartUpstreamError):
        return None


def test_supplier_details_by_alias_and_id(storefront):
    visited, encrypted = storefront
    details = suppliers.supplier_details("risansi")
    assert visited == ["https://www.indiamart.com/risansi/", "https://www.indiamart.com/risansi/about-us.html"]
    assert details["id"] == 20902177 and details["registration"]["cin"]
    assert details["rating_breakdown"]["5"] == 90 and details["review_count"] == 155     # from the reviews XHR
    assert details["website"] == "https://www.vmtechnology.in/"
    assert encrypted[0][1]["glid"] == 20902177 and encrypted[0][1]["limit"] == 20
    visited.clear()
    suppliers._aliases.clear()
    by_id = suppliers.supplier_details("https://www.indiamart.com/company/20902177/")
    assert visited[0] == "https://www.indiamart.com/company/20902177/" and by_id["slug"] == "risansi"
    with pytest.raises(fetch.IndiamartNotFound):
        suppliers.supplier_details("no-such-supplier")


def test_supplier_catalogue_and_products(storefront):
    visited, _ = storefront
    catalogue = suppliers.supplier_catalogue("patsonmachines")
    assert visited == ["https://www.indiamart.com/patsonmachines/",
                       "https://www.indiamart.com/patsonmachines/cnc-spm-machines.html"]
    assert catalogue["supplier"] == {"id": 949553, "slug": "patsonmachines",
                                     "name": "Patson Machines Private Limited",
                                     "link": "https://www.indiamart.com/patsonmachines/"}
    assert catalogue["count"] == 16
    fallback = suppliers.supplier_catalogue("risansi")              # index page missing -> the home page's range
    assert fallback["count"] == 8 and fallback["results"][0]["slug"] == "screw-pump"
    page = suppliers.supplier_products("risansi", "https://www.indiamart.com/risansi/screw-pump.html")
    assert page["count"] == 8 and page["supplier"]["id"] == 20902177 and page["category"]["slug"] == "screw-pump"
    with pytest.raises(fetch.IndiamartNotFound, match="not a catalogue page"):
        suppliers.supplier_products("risansi", "about-us")
    with pytest.raises(fetch.IndiamartNotFound):
        suppliers.supplier_products("risansi", "missing-page")


def test_supplier_reviews_paging(storefront):
    visited, encrypted = storefront
    out = suppliers.supplier_reviews("risansi", page=2, sort_by="recent")
    assert visited == ["https://www.indiamart.com/risansi/"]            # one fetch to learn the supplier id
    path, params = encrypted[0]
    assert path == "/ajaxRequestCompanyDesktop/SellerRatingDesktop/"
    assert params["glid"] == 20902177 and params["sort_type"] == "2" and params["limit"] == 40
    assert out["pagination"] == {"page": 2, "items_per_page": 20, "total_pages": 8, "total_count": 155}
    assert len(out["results"]) == 20 and out["supplier"]["name"] == "Risansi Industries Limited"
    visited.clear()
    again = suppliers.supplier_reviews("20902177")                       # memoised: no page fetch at all
    assert visited == [] and again["supplier"]["slug"] == "risansi" and encrypted[-1][1]["limit"] == 20
    with pytest.raises(fetch.IndiamartNotFound):
        suppliers.supplier_reviews("risansi", page=9)
    with pytest.raises(ValueError):
        suppliers.supplier_reviews("risansi", sort_by="oldest")


def test_supplier_reviews_empty(storefront, monkeypatch):
    monkeypatch.setattr(suppliers, "get_encrypted", lambda *a, **k: {"Response": {"Code": "200", "Data": []}})
    out = suppliers.supplier_reviews("risansi")
    assert out["results"] == [] and out["pagination"]["total_count"] == 0 and out["summary"]["rating"] is None
    monkeypatch.setattr(suppliers, "get_encrypted", lambda *a, **k: "garbage")
    with pytest.raises(fetch.IndiamartUpstreamError):
        suppliers.supplier_reviews("risansi")


def test_supplier_registration_trustseal_media(storefront):
    record = suppliers.supplier_registration("risansi")
    assert record["supplier"]["slug"] == "risansi" and record["director_count"] == 3
    cert = suppliers.supplier_trustseal("risansi")
    assert cert["certificate_id"] == 36450 and cert["supplier"]["id"] == 20902177
    assert suppliers.supplier_photos("risansi")["count"] == 72
    assert suppliers.supplier_videos("risansi")["count"] == 4
    with pytest.raises(fetch.IndiamartNotFound, match="no registration"):
        suppliers.supplier_registration("patsonmachines")              # page absent for this fixture set
    with pytest.raises(fetch.IndiamartNotFound, match="TrustSEAL"):
        suppliers.supplier_trustseal("patsonmachines")
    assert suppliers.supplier_photos("patsonmachines") == {
        "supplier": {"id": 949553, "slug": "patsonmachines", "name": "Patson Machines Private Limited",
                     "link": "https://www.indiamart.com/patsonmachines/"}, "count": 0, "results": []}
