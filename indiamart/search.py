"""Keyword search: products (flat rows) and suppliers (grouped rows), both
from the search page's own JSON API (dir.indiamart.com/api/search.rp).

One call answers the first result page — 10 supplier groups, ~30 products.
Page 2+ needs a logged-in token upstream, so there is no page param; narrow
with the filters (city, business type, price, turnover, GST age) instead.

    python indiamart/search.py "cnc machine" [city]
    python indiamart/search.py --suppliers "basmati rice" mumbai
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indiamart import parsers  # noqa: E402
from indiamart.fetch import DIR, IndiamartBadRequest, IndiamartUpstreamError, get_json  # noqa: E402
from indiamart.refs import ANNUAL_TURNOVER, BUSINESS_TYPES, GST_REGISTRATION_AGE  # noqa: E402
from indiamart.shared import flatten_products, group_suppliers  # noqa: E402

SEARCH_API = DIR + "/api/search.rp"
SEARCH_REFERER = DIR + "/search.mp"


def _search(query, city, business_type, min_price, max_price, annual_turnover, gst_registration_age):
    if not query or not str(query).strip():
        raise ValueError("query is required")
    if business_type is not None and business_type not in BUSINESS_TYPES:
        raise ValueError(f"business_type must be one of: {', '.join(BUSINESS_TYPES)}")
    if annual_turnover is not None and annual_turnover not in ANNUAL_TURNOVER:
        raise ValueError(f"annual_turnover must be one of: {', '.join(ANNUAL_TURNOVER)}")
    if gst_registration_age is not None and gst_registration_age not in GST_REGISTRATION_AGE:
        raise ValueError(f"gst_registration_age must be one of: {', '.join(GST_REGISTRATION_AGE)}")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("min_price must be <= max_price")
    params = {
        "q": " ".join(str(query).split()),
        "page": 1,
        "source": "dir.search",
        # the API matches the lowercase city name ("navi mumbai", "new delhi")
        "options.filters.city.data": str(city).replace("-", " ").lower() if city else None,
        "options.filters.biztype.data": BUSINESS_TYPES[business_type] if business_type else None,
        "options.filters.biztype.type": "value" if business_type else None,
        "min-price": parsers.number(min_price),
        "max-price": parsers.number(max_price),
        "annualTurnover": ANNUAL_TURNOVER[annual_turnover] if annual_turnover else None,
    }
    if gst_registration_age:
        low, high = GST_REGISTRATION_AGE[gst_registration_age]
        params["gstMinYear"] = low
        params["gstMaxYear"] = high
    status, body = get_json(SEARCH_API, params, referer=SEARCH_REFERER, label="search", raw_status=True)
    if status == 400 or (isinstance(body, dict) and str(body.get("res_code")) == "400"):
        raise IndiamartBadRequest((body or {}).get("error_msg") or "search rejected")
    if not isinstance(body, dict) or "results" not in body:
        raise IndiamartUpstreamError("search answered without a result list")
    return parsers.parse_search(body, params["q"])


def _envelope(parsed, rows):
    return {
        "query": parsed["query"],
        "interpreted_query": parsed["interpreted_query"],
        "detected_city": parsed["detected_city"],
        "total_count": parsed["total_count"],
        "count": len(rows),
        "results": rows,
        "filters": parsed["filters"],
    }


def search_products(query, city=None, business_type=None, min_price=None, max_price=None,
                    annual_turnover=None, gst_registration_age=None):
    """Products matching a keyword, best match first, each with its
    supplier (phone, GST number, rating, verification). `total_count` is
    the size of the full result set on the site; `count` what this call
    returned (the first result page)."""
    parsed = _search(query, city, business_type, min_price, max_price, annual_turnover, gst_registration_age)
    return _envelope(parsed, flatten_products(parsed["groups"]))


def search_suppliers(query, city=None, business_type=None, min_price=None, max_price=None,
                     annual_turnover=None, gst_registration_age=None):
    """Suppliers selling a keyword, best match first, one row per supplier
    with the products of theirs that matched."""
    parsed = _search(query, city, business_type, min_price, max_price, annual_turnover, gst_registration_age)
    return _envelope(parsed, group_suppliers(parsed["groups"]))


if __name__ == "__main__":
    args = sys.argv[1:] or ["cnc machine"]
    fn = search_products
    if args[0] == "--suppliers":
        fn, args = search_suppliers, args[1:]
    out = fn(args[0], city=args[1] if len(args) > 1 else None)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:5000])
