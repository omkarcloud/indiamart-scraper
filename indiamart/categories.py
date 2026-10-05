"""Category directory: the tree (industries -> sub-categories ->
categories), a category's profile and its product listing.

Listings ride the category page's state API (/mcatAjaxRequest/ajaxData/):
28 supplier cards + their sibling products (~100 products) per call. The
site's load-more needs a login, so depth comes from slicing — one call per
city (the category profile lists the cities) and per business type.

    python indiamart/categories.py                       # industries
    python indiamart/categories.py agro-farm              # its sub-categories
    python indiamart/categories.py --products cnc-machines [city]
    python indiamart/categories.py --details basmati-rice
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indiamart import parsers  # noqa: E402
from indiamart.fetch import (  # noqa: E402
    DIR, IndiamartNotFound, IndiamartUpstreamError, extract_blob, get_json, get_page,
)
from indiamart.refs import BUSINESS_TYPES, category_link, resolve_category_ref, resolve_parent_ref, tree_link  # noqa: E402
from indiamart.shared import flatten_products  # noqa: E402

CATEGORY_API = DIR + "/mcatAjaxRequest/ajaxData/"
STATE_MARKER = "window.__INITIAL_STATE__"


# ---- tree ------------------------------------------------------------------------

def _tree_state(section, slug):
    html, _ = get_page(tree_link(section, slug), referer=DIR + "/", label=f"{section} {slug}")
    state = extract_blob(html, STATE_MARKER)
    if not isinstance(state, dict):
        raise IndiamartNotFound(f"{slug} is not an IndiaMART {section} page")
    return state


def _industry(slug):
    state = _tree_state("industry", slug)
    if not state.get("scats"):
        raise IndiamartNotFound(f"industry {slug} does not exist")
    return parsers.parse_industry(state, slug)


def _sub_category(section, slug):
    state = _tree_state(section, slug)
    if not state.get("mcats"):
        raise IndiamartNotFound(f"sub-category {slug} does not exist")
    return parsers.parse_sub_category(state, slug, section)


def categories(parent=None):
    """One level of the category tree. No `parent`: the industries. An
    industry: its sub-categories (with their top categories). A
    sub-category: its categories, each with child categories — the level
    `/categories/products` lists."""
    if parent is None:
        html, _ = get_page(DIR + "/", label="directory home")
        rows = parsers.parse_industries(html)
        if not rows:
            raise IndiamartUpstreamError("directory home rendered without industries")
        return {"parent": None, "level": "industry", "count": len(rows), "results": rows}
    node = resolve_parent_ref(parent) if isinstance(parent, str) else parent
    section, slug = node.get("section"), node["slug"]
    if section == "industry":
        tree = _industry(slug)
    elif section in ("products", "services"):
        tree = _sub_category(section, slug)
    else:
        tree = None
        for attempt in (lambda: _industry(slug), lambda: _sub_category("products", slug),
                        lambda: _sub_category("services", slug)):
            try:
                tree = attempt()
                break
            except IndiamartNotFound:
                continue
        if tree is None:
            raise IndiamartNotFound(f"{slug} is not an industry or sub-category "
                                    f"(leaf categories go to /categories/details)")
    rows = tree["results"]
    return {"parent": tree["parent"], "level": rows[0]["level"] if rows else None,
            "count": len(rows), "results": rows}


# ---- one category ----------------------------------------------------------------

def _category_state(category, city=None, business_type=None):
    ref = resolve_category_ref(category) if isinstance(category, str) else dict(category)
    slug = ref["slug"]
    city = city or ref.get("city")
    if business_type is not None and business_type not in BUSINESS_TYPES:
        raise ValueError(f"business_type must be one of: {', '.join(BUSINESS_TYPES)}")
    params = {"flname": slug, "isqId": 0, "city": city, "biz": BUSINESS_TYPES.get(business_type, 0)}
    state = get_json(CATEGORY_API, params, referer=category_link(slug, city), label=f"category {slug}")
    if not parsers.category_exists(state):
        raise IndiamartNotFound(f"category {slug} does not exist")
    if city and not parsers.to_int(state.get("cityid")):
        # an unknown city silently answers the all-India listing
        raise ValueError(f"city '{city}' is not listed for this category — use a `slug` from "
                         f"/indiamart/categories/details `cities` or /indiamart/cities/autocomplete")
    return state


def category_details(category, city=None):
    """A category's profile: identity + place in the tree, product count,
    the cities it is listed in, business-type and price filters, related
    categories and brands, branded standard products, FAQs."""
    return parsers.parse_category_details(_category_state(category, city))


def category_products(category, city=None, business_type=None):
    """Products listed in a category (optionally in one city / from one
    business type), in the site's order, each with its supplier."""
    parsed = parsers.parse_category_products(_category_state(category, city, business_type))
    rows = flatten_products(parsed["groups"])
    return {
        "category": parsed["category"],
        "city": parsed["city"],
        "business_type": parsed["business_type"],
        "total_count": parsed["total_count"],
        "count": len(rows),
        "results": rows,
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--products":
        out = category_products(args[1], city=args[2] if len(args) > 2 else None)
    elif args and args[0] == "--details":
        out = category_details(args[1])
    else:
        out = categories(args[0] if args else None)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:5000])
