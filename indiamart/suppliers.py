"""Supplier storefronts: profile, catalogue, product cards, reviews, MCA
registration + directors, TrustSEAL certificate, photos and videos.

Every storefront page is server-rendered HTML on
www.indiamart.com/<alias>/…; a numeric supplier id is followed through
/company/<id>/ to its alias. Reviews page through the storefront's
encrypted XHR, 20 per page (fetch.get_encrypted).

    python indiamart/suppliers.py risansi
    python indiamart/suppliers.py --catalogue patsonmachines
    python indiamart/suppliers.py --products risansi screw-pump
    python indiamart/suppliers.py --reviews vm-technology-bengaluru 2 recent
    python indiamart/suppliers.py --registration risansi
"""
import json
import math
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indiamart import parsers, store_parsers  # noqa: E402
from indiamart.fetch import (  # noqa: E402
    WWW, IndiamartNotFound, IndiamartUpstreamError, extract_blob, gather, get_encrypted, get_page,
)
from indiamart.refs import (  # noqa: E402
    REVIEW_SORTS, resolve_supplier_category_ref, resolve_supplier_ref, supplier_alias_of, supplier_link,
)

COMPANY_MARKER = "window.__COMPANY_DATA__"
REVIEWS_API = "/ajaxRequestCompanyDesktop/SellerRatingDesktop/"
REVIEWS_PAGE_SIZE = 20
REVIEWS_MAX_PAGE = 500

# alias <-> supplier id (+ name) seen on storefront pages (ids never change);
# saves the home-page fetch a reviews call would otherwise need.
_ids = {}
_aliases = {}
_names = {}
_memo_lock = threading.Lock()
_MEMO_MAX = 20000


def _remember(alias, supplier_id, name=None):
    if alias and supplier_id:
        with _memo_lock:
            if len(_ids) >= _MEMO_MAX:
                _ids.clear()
                _aliases.clear()
                _names.clear()
            _ids[alias] = supplier_id
            _aliases[supplier_id] = alias
            if name:
                _names[supplier_id] = name


class _Page:
    """One fetched storefront page: parsed doc + its __COMPANY_DATA__."""

    def __init__(self, html, final_url, alias):
        self.html = html
        self.doc = store_parsers.soup(html)
        self.data = extract_blob(html, COMPANY_MARKER) or {}
        company = store_parsers.company_blob(self.data)
        self.alias = parsers.text(company.get("alias")) or supplier_alias_of(final_url) or alias
        self.supplier_id = parsers.to_int(company.get("glid"))
        _remember(self.alias, self.supplier_id, parsers.text(company.get("companyName")))

    @property
    def is_storefront(self):
        return bool(store_parsers.company_blob(self.data))

    def identity(self):
        return store_parsers.parse_identity(self.doc, self.data, self.alias)


def _fetch(supplier, page="", *, optional=False):
    """GET one storefront page of `supplier` (alias or numeric id)."""
    ref = resolve_supplier_ref(str(supplier))
    if ref.isdigit():
        alias = _aliases.get(int(ref))
        if alias is None:
            if page:
                alias = _fetch(ref).alias                  # /company/<id>/ -> the alias
            else:
                url = f"{WWW}/company/{ref}/"
                html, final = get_page(url, referer=WWW + "/", label=f"supplier {ref}")
                result = _Page(html, final, None)
                if not result.is_storefront or not result.alias:
                    raise IndiamartNotFound(f"supplier {ref} does not exist")
                return result
        ref = alias
    url = supplier_link(ref, page)
    try:
        html, final = get_page(url, referer=supplier_link(ref), label=f"supplier {ref}/{page}")
    except IndiamartNotFound:
        if optional:
            return None
        raise IndiamartNotFound(f"supplier {ref} has no page {page}" if page else f"supplier {ref} does not exist")
    result = _Page(html, final, ref)
    if not result.is_storefront:
        if optional:
            return None
        raise IndiamartNotFound(f"{ref} is not a supplier storefront")
    return result


def _relative(link, alias):
    """A storefront page link -> its path under the alias ('about-us.html')."""
    prefix = supplier_link(alias)
    return link[len(prefix):] if link and link.startswith(prefix) else None


def _reviews_payload(supplier_id, alias, sort_type, limit):
    body = get_encrypted(REVIEWS_API, {
        "glid": supplier_id, "input_supplier_id": supplier_id, "sort_type": sort_type, "limit": limit,
        "pagelinktype": "testimonial", "is_presnt_tstmonial": 1,
        "testimonialPageLink": f"/{alias}/testimonial.html" if alias else None,
    }, referer=supplier_link(alias, "testimonial.html") if alias else WWW + "/", label="supplier reviews")
    data = store_parsers.reviews_data(body)
    if data is None:
        raise IndiamartUpstreamError("reviews answered in an unknown shape")
    return data


# ---- endpoints -------------------------------------------------------------------

def supplier_details(supplier):
    """The supplier's company profile: identity, contact person, rating +
    star breakdown, verification badges, factsheet (business nature,
    employees, turnover, legal status…), statutory numbers (GST, IEC, CIN,
    bankers), profile sections, HSN codes and catalogue pages."""
    home = _fetch(supplier)
    pages, _, _ = store_parsers._pages(home.doc, home.alias)
    about_path = _relative(pages.get("about"), home.alias)
    extra = gather({
        "about": (lambda: _fetch(home.alias, about_path, optional=True)) if about_path else (lambda: None),
        "reviews": (lambda: _reviews_payload(home.supplier_id, home.alias, "1", REVIEWS_PAGE_SIZE))
        if home.supplier_id else (lambda: None),
    }, optional=("about", "reviews"))
    about = extra.get("about")
    result = store_parsers.parse_details(home.doc, home.data, home.alias, about.doc if about else None)
    reviews = extra.get("reviews")
    if reviews:
        summary = store_parsers.rating_summary(reviews)
        result["rating"] = summary["rating"] or result["rating"]
        if summary["review_count"] is not None:
            result["review_count"] = summary["review_count"]
        result["rating_breakdown"] = summary["breakdown"]
        result["satisfaction"] = summary["satisfaction"]
        website = parsers.own_website(reviews.get("paid_catalog_url"))
        if website:
            result["website"] = website.split("/testimonial")[0].rstrip("/") + "/"
    return result


def supplier_catalogue(supplier):
    """The supplier's catalogue index: every catalogue page (category) with
    its description, product count where shown and featured products."""
    home = _fetch(supplier)
    pages, _, _ = store_parsers._pages(home.doc, home.alias)
    index_path = _relative(pages.get("products"), home.alias)
    index = _fetch(home.alias, index_path, optional=True) if index_path else None
    if index is not None:
        parsed = store_parsers.parse_catalogue(index.doc, home.alias)
    else:
        parsed = {"title": None, "description": None, "results": []}
    if not parsed["results"]:
        parsed["results"] = [
            {**row, "description": None, "product_count": None, "featured_products": []}
            for row in store_parsers.parse_home_categories(home.doc, home.data, home.alias) if row.get("slug")]
    return {
        "supplier": store_parsers.supplier_ref(home.identity()),
        "title": parsed["title"],
        "description": parsed["description"],
        "count": len(parsed["results"]),
        "results": parsed["results"],
    }


def supplier_products(supplier, category):
    """The products on one catalogue page of the supplier, with full cards:
    price, minimum order, specification table, description, images, videos
    and brochure. `category` = a slug from /suppliers/catalogue."""
    slug = resolve_supplier_category_ref(str(category))
    page = _fetch(supplier, f"{slug}.html")
    if not store_parsers.is_catalogue_page(page.doc):
        raise IndiamartNotFound(f"{slug} is not a catalogue page of this supplier "
                                f"(see /indiamart/suppliers/catalogue)")
    parsed = store_parsers.parse_catalogue_page(page.doc, page.alias, slug)
    return {
        "supplier": store_parsers.supplier_ref(page.identity()),
        "category": parsed["category"],
        "count": len(parsed["results"]),
        "results": parsed["results"],
    }


def supplier_reviews(supplier, page=1, sort_by="top"):
    """Buyer ratings and reviews of a supplier, 20 per page, with the
    rating summary (average, star breakdown, satisfaction by aspect)."""
    page = int(page or 1)
    if not 1 <= page <= REVIEWS_MAX_PAGE:
        raise ValueError(f"page must be 1-{REVIEWS_MAX_PAGE}")
    if sort_by not in REVIEW_SORTS:
        raise ValueError(f"sort_by must be one of: {', '.join(REVIEW_SORTS)}")
    ref = resolve_supplier_ref(str(supplier))
    if ref.isdigit():
        supplier_id, alias = int(ref), _aliases.get(int(ref))
    else:
        alias, supplier_id = ref, _ids.get(ref)
    stub = None
    if supplier_id is None or alias is None:
        home = _fetch(ref)
        supplier_id, alias = home.supplier_id, home.alias
        stub = store_parsers.supplier_ref(home.identity())
        if not supplier_id:
            raise IndiamartUpstreamError("storefront rendered without a supplier id")
    # `limit` is the END index upstream: limit=40 answers reviews 21-40
    data = _reviews_payload(supplier_id, alias, REVIEW_SORTS[sort_by], page * REVIEWS_PAGE_SIZE)
    summary, reviews = store_parsers.parse_reviews(data)
    total = summary["review_count"] or 0
    total_pages = math.ceil(total / REVIEWS_PAGE_SIZE) if total else 0
    if page > 1 and (not reviews or page > max(total_pages, 1)):
        raise IndiamartNotFound(f"page {page} is past the last page ({total_pages})")
    return {
        "supplier": stub or {"id": supplier_id, "slug": alias, "name": _names.get(supplier_id),
                             "link": supplier_link(alias)},
        "sort_by": sort_by,
        "summary": summary,
        "results": reviews,
        "pagination": {"page": page, "items_per_page": REVIEWS_PAGE_SIZE,
                       "total_pages": total_pages, "total_count": total},
    }


def supplier_registration(supplier):
    """The supplier's Ministry of Corporate Affairs record as the storefront
    shows it: CIN, company type and status, incorporation date, capital,
    open charges, AGM / balance-sheet dates and the directors (name,
    designation, DIN, appointment date). Only registered companies have it."""
    page = _fetch(supplier, "registration-directors-info.html", optional=True)
    if page is None or not store_parsers.has_registration(page.doc):
        _fetch(supplier)                                   # 404 for a supplier that does not exist
        raise IndiamartNotFound("this supplier has no registration & directors record")
    result = {"supplier": store_parsers.supplier_ref(page.identity())}
    result.update(store_parsers.parse_registration(page.doc))
    return result


def supplier_trustseal(supplier):
    """The supplier's TrustSEAL certificate: id, issue / validity months and
    what IndiaMART verified. 404 for suppliers without TrustSEAL."""
    page = _fetch(supplier)                                # resolves ids + the supplier stub
    ref = page.alias
    try:
        html, _ = get_page(supplier_link(ref, "trustseal/"), referer=supplier_link(ref), label=f"trustseal {ref}")
    except IndiamartNotFound:
        raise IndiamartNotFound("this supplier has no TrustSEAL certificate")
    certificate = store_parsers.parse_trustseal(store_parsers.soup(html))
    if certificate is None:
        raise IndiamartNotFound("this supplier has no TrustSEAL certificate")
    return {"supplier": store_parsers.supplier_ref(page.identity()), **certificate}


def supplier_photos(supplier):
    """The supplier's photo gallery: product photos (large + thumbnail)
    with the product each belongs to."""
    page = _fetch(supplier, "photos.html", optional=True)
    if page is None:                                       # no gallery page: still a valid supplier?
        home = _fetch(supplier)
        return {"supplier": store_parsers.supplier_ref(home.identity()), "count": 0, "results": []}
    rows = store_parsers.parse_photos(page.doc)
    return {"supplier": store_parsers.supplier_ref(page.identity()), "count": len(rows), "results": rows}


def supplier_videos(supplier):
    """The supplier's videos (YouTube): corporate video and product videos."""
    home = _fetch(supplier)
    rows = store_parsers.parse_videos(home.doc)
    try:      # the videos page carries no __COMPANY_DATA__, so it is read as a bare page
        html, _ = get_page(supplier_link(home.alias, "videos.html"), referer=supplier_link(home.alias),
                           label=f"videos {home.alias}")
    except (IndiamartNotFound, IndiamartUpstreamError):
        html = None
    if html:
        seen = {row["id"] for row in rows}
        rows.extend(row for row in store_parsers.parse_videos(store_parsers.soup(html)) if row["id"] not in seen)
    return {"supplier": store_parsers.supplier_ref(home.identity()), "count": len(rows), "results": rows}


if __name__ == "__main__":
    args = sys.argv[1:] or ["risansi"]
    modes = {
        "--catalogue": lambda a: supplier_catalogue(a[0]),
        "--products": lambda a: supplier_products(a[0], a[1]),
        "--reviews": lambda a: supplier_reviews(a[0], page=int(a[1]) if len(a) > 1 else 1,
                                                sort_by=a[2] if len(a) > 2 else "top"),
        "--registration": lambda a: supplier_registration(a[0]),
        "--trustseal": lambda a: supplier_trustseal(a[0]),
        "--photos": lambda a: supplier_photos(a[0]),
        "--videos": lambda a: supplier_videos(a[0]),
    }
    out = modes[args[0]](args[1:]) if args[0] in modes else supplier_details(args[0])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])
