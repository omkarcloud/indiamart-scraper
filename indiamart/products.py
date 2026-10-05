"""Product pages: full details (with the seller's company profile and
statutory numbers) and similar products.

    python indiamart/products.py 11558361073
    python indiamart/products.py --similar 11558361073
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indiamart import parsers  # noqa: E402
from indiamart.fetch import WWW, IndiamartNotFound, IndiamartUpstreamError, get_json, get_page, next_data  # noqa: E402
from indiamart.refs import product_link, resolve_product_ref  # noqa: E402

SIMILAR_API = WWW + "/api/ajax-services/caps_service/"
SIMILAR_COUNT = 20


def _product_record(product):
    product_id = resolve_product_ref(str(product))
    html, _ = get_page(product_link(product_id), referer=WWW + "/", label=f"product {product_id}")
    record = parsers.product_data(next_data(html))
    if record is None:
        if "Page not found" in html[:3000]:
            raise IndiamartNotFound(f"product {product_id} does not exist")
        raise IndiamartUpstreamError("product page rendered without its data")
    if not parsers.to_int(record.get("PC_ITEM_DISPLAY_ID")):
        raise IndiamartNotFound(f"product {product_id} does not exist")
    return product_id, record


def product_details(product):
    """Everything a product page shows: specifications, images, price,
    minimum order, trade terms, category path and the seller (contact,
    ratings, verification, company profile, statutory registrations)."""
    _, record = _product_record(product)
    return parsers.parse_product(record)


def similar_products(product):
    """Products the site recommends next to this one (same category, near
    the seller's city) and the related categories."""
    product_id, record = _product_record(product)
    category_id, city_id = parsers.product_lookup_keys(record)
    stub = {
        "id": product_id,
        "name": parsers.text(record.get("PC_ITEM_DISPLAY_NAME")) or parsers.text(record.get("PC_ITEM_NAME")),
        "link": parsers.link(record.get("PDP_CANONICAL_URL")) or product_link(product_id),
    }
    if not category_id:
        return {"product": stub, "count": 0, "results": [], "related_categories": []}
    body = get_json(SIMILAR_API, {"displayid": product_id, "count": SIMILAR_COUNT, "cityid": city_id,
                                  "mcatid": category_id, "webAddLoc": "www.indiamart.com"},
                    referer=product_link(product_id), label=f"similar {product_id}")
    parsed = parsers.parse_similar(body)
    return {"product": stub, "count": len(parsed["results"]), "results": parsed["results"],
            "related_categories": parsed["related_categories"]}


if __name__ == "__main__":
    args = sys.argv[1:] or ["11558361073"]
    out = similar_products(args[1]) if args[0] == "--similar" else product_details(args[0])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])
