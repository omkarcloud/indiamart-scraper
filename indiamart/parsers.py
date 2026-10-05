"""Payload -> stable dict normalization for IndiaMART's JSON surfaces: the
search API, category page state, category tree states, product page data,
the similar-products service and search suggestions. Supplier storefront
HTML lives in store_parsers.py and reuses the helpers below.

Rules (house style): snake_case, `link` not `url`, booleans as questions,
identity first then content then ratings then nested objects then metadata,
numbers as numbers, prices as amount + currency (+ unit), ISO dates, null
for missing, never crash on a partial payload.

Intentionally skipped raw fields (and why):
  search results  score / pla_weight / productqualityscore / *MatchCount /
                  NumberOfMatched* / matched_attributes / tpMatch / dupMatch /
                  primeMatching / product_accuracy_level / mcatRank / subrank
                  (ranking internals); desktop_* / mobile_* links (the same
                  links with tracking tags); titleHtml / smalldesc / sdesclen
                  (duplicates of title / description); image / large_image /
                  photo[] (smaller renditions of the kept image); glusrid (an
                  obfuscated id that is NOT the storefront supplier id);
                  datarefid / itemcode (internal item ids); ecom_* / BL_DATA /
                  bl_* / hotnew / prefprod / deals_in_loc / categoryinfo
                  (empty for every listing seen); *displayflag* /
                  *VisibilityFlag / allow_ecom_* / pns_display_flag /
                  serviceFlag / serviceMcatPrefLoc / d_in_range / distance
                  (render switches + a distance from the caller's IP);
                  CustTypeWt (membership weight number); phone / mobile /
                  address / zipcode (always empty logged-out; `pns` is the
                  public call number); gstVerificationSrcId (source id)
  search page     trackingParams / urlTrackingInfo / internalLog /
                  add_in_varnish_logs / Cd-Miscellaneous / kwplServiceResults /
                  search_time / search_from / query_breakup / guess.* (engine
                  diagnostics, internal solr URLs), googleResults (empty),
                  facet itemprice2, nextPage / nextPageAuth (page 2 is
                  login-gated; there is no page param to act on them)
  category state  COOKIES (request cookies echoed by the server), ea /
                  CD_* / cityImgIsqFlag / Abexperiment / abtest / randomizer /
                  srcParam / template_id / viewtype / *Popup* / loader /
                  compare* / enqFormParam (analytics + UI state), image_flag /
                  seller_isq_flag / company_display_flag / sold_flag (render
                  switches), plaWidgetData (ads duplicating listed products),
                  urls.alternate_* (mobile / app mirrors), McatMetaData
                  keyword stuffing (title + description kept)
  category cards  srch_id (internal item id), cw_o (membership weight),
                  c_vl / iil_display / d_in / hnpd / g_s / f_ad (flags, empty)
  product page    GLCAT_MCAT_* render flags, DISCLAIMER_*, META* (SEO text),
                  PC_ITEM_CODE / PC_ITEM_ID (internal ids), INDIC_HINDI_*,
                  PDP_ALTERNATE_* (mobile / app mirrors), PC_IMG_SMALL_* /
                  PC_ITEM_IMG_* (renditions already in `images`), key "0" (a
                  copy of ITEM_IMG), *_DISPLAY_FLAG / PDP_VISIBILITY_FLAG /
                  GLUSR_USR_LISTING_STATUS / GLUSR_USR_LOC_PREF / MCAT_RANK /
                  SUBRANK / GLUSR_USR_CUSTTYPE_WEIGHT, empty-titled rows of
                  the profile tables, pathData / *ApiRes (request echo)
  similar         ECOM_* / FCP_FLAG / LOCATION_FLAG / MAPPING_LOGIC_FLAG /
                  RECOM_SOURCE* / PLA_TRACKING_URL / CUSTTYPE_* / STATUS_* /
                  MSG_* / UNIQUE_ID (service diagnostics + tracking)
  suggestions     data.type_data / sort_order (render hints)
"""
import html as _html
import re
from datetime import date, datetime

WWW = "https://www.indiamart.com"
DIR = "https://dir.indiamart.com"

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<\s*(?:br\s*/?|/p|/li|/div|/h[1-6]|/tr)\s*>", re.I)
_WS_RE = re.compile(r"[ \t\r\f\v\xa0]+")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_DOC_MARK_RE = re.compile(r"#[A-Z_]+#.*$")
_PRICE_UNIT_RE = re.compile(r"/\s*([^/]+?)\s*$")

# primary business type id -> label (FK_PBIZ_ID of the category filter)
BUSINESS_TYPE_NAMES = {
    10: "Manufacturer", 20: "Exporter", 30: "Wholesaler/Distributor", 40: "Retailer",
    50: "Service Provider",
}


# ---- tiny helpers ----------------------------------------------------------------

def dig(obj, *path, default=None):
    cur = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int) and -len(cur) <= key < len(cur):
            cur = cur[key]
        else:
            return default
        if cur is None:
            return default
    return cur


def text(value):
    """Tags / entities / whitespace stripped onto one line; None when empty
    (also for the site's literal "null" / "NA" placeholders)."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, str):
        value = str(value)
    value = _html.unescape(_TAG_RE.sub(" ", value))
    value = " ".join(value.split())
    if not value or value.lower() in ("null", "none", "na", "n/a", "undefined"):
        return None
    return value


def multiline(value):
    """Rich text -> plain text that keeps paragraph / line breaks."""
    if value is None or not isinstance(value, str):
        return None
    value = _BR_RE.sub("\n", value)
    value = _html.unescape(_TAG_RE.sub(" ", value))
    lines = [_WS_RE.sub(" ", line).strip() for line in value.split("\n")]
    out = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    result = "\n".join(out).strip()
    if not result or result.lower() in ("null", "none"):
        return None
    return result


def to_int(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    cleaned = str(value).replace(",", "").strip()
    match = _NUM_RE.search(cleaned)
    if not match:
        return None
    try:
        return int(float(match.group(0)))
    except ValueError:
        return None


def to_float(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUM_RE.search(str(value).replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def number(value):
    """Float, shown as int when whole (85.0 -> 85) so amounts read naturally."""
    result = to_float(value)
    if result is None:
        return None
    return int(result) if result == int(result) else result


def flag(value):
    """The site's 1 / "1" / true / "Y" style flags -> bool; None when absent."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    low = str(value).strip().lower()
    if low in ("1", "true", "y", "yes"):
        return True
    if low in ("0", "false", "n", "no", "null", "none"):
        return False
    number_value = to_float(low)
    return bool(number_value) if number_value is not None else None


def link(value, base=WWW):
    """Absolute https link (protocol-relative / relative / http accepted),
    tracking query (?pos=…&kwd=…&tags=…) removed; None when empty."""
    value = text(value)
    if not value:
        return None
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = base + value
    elif value.startswith("http://"):
        value = "https://" + value[len("http://"):]
    elif not value.startswith("https://"):
        return None
    head, sep, query = value.partition("?")
    if sep and re.search(r"(?:^|&)(?:pos|kwd|tags)=", query):
        value = head
    return value


def media_link(value):
    """Image / document / video link without the site's '#ITEM_DOC#' /
    '#VIDEO#VIDEO' markers."""
    value = text(value)
    if not value:
        return None
    return link(_DOC_MARK_RE.sub("", value))


def phone(value):
    """'8047551306' / '08047547416' / '+91-8047551306' -> '+918047551306'."""
    value = text(value)
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    if value.strip().startswith("+"):
        return "+" + digits
    digits = digits.lstrip("0")
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    return digits or None


def iso_date(value):
    """ISO date from the formats the site uses: 2007-09-19T20:19:46Z,
    2007-09-20 01:49:46, 10-02-26 (dd-mm-yy), 23-7-1996 (d-m-yyyy),
    06/10/2019 (dd/mm/yyyy)."""
    value = text(value)
    if not value:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        parts = tuple(int(x) for x in match.groups())
    else:
        match = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2}|\d{4})$", value)
        if not match:
            return None
        day, month, year = (int(x) for x in match.groups())
        if year < 100:
            year += 2000
        parts = (year, month, day)
    try:
        return date(*parts).isoformat()
    except ValueError:
        return None


def month_year(value):
    """'April 2018' -> '2018-04' (TrustSEAL certificate dates)."""
    value = text(value)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%B %Y").strftime("%Y-%m")
    except ValueError:
        return None


def years(value):
    """'16 yrs' -> 16, '10 Months' -> 0 (whole years on the platform)."""
    value = text(value)
    if not value:
        return None
    count = to_int(value)
    if count is None:
        return None
    return 0 if "month" in value.lower() else count


def percent(value):
    result = to_float(value)
    if result is None:
        return None
    return int(result) if result == int(result) else result


def price(amount, currency=None, unit=None, display=None):
    """{amount, currency, unit} or None when the listing shows no price.
    `display` ("₹ 85 Lakh/Piece", "₹ 65 / Kg") only supplies the unit when
    no explicit one is given."""
    value = number(amount)
    if value is None or value <= 0:
        return None
    unit = text(unit)
    if not unit and display:
        shown = text(display) or ""
        match = _PRICE_UNIT_RE.search(shown)
        if match and not any(ch.isdigit() for ch in match.group(1)):
            unit = match.group(1).strip() or None
    return {"amount": value, "currency": text(currency) or "INR", "unit": unit}


def quantity(amount, unit=None):
    """{quantity, unit} for a minimum order, or None."""
    value = number(amount)
    if value is None or value <= 0:
        return None
    return {"quantity": value, "unit": text(unit)}


def specs_from_pairs(pairs):
    """[(name, value)] -> [{name, value}] with empties and duplicates dropped."""
    out, seen = [], set()
    for name, value in pairs:
        name, value = text(name), text(value)
        if not name or not value or (name, value) in seen:
            continue
        seen.add((name, value))
        out.append({"name": name, "value": value})
    return out


def specs_from_strings(items, sep="=="):
    """['Voltage==415V', …] -> [{name, value}]."""
    pairs = []
    for item in items or []:
        if isinstance(item, str) and sep in item:
            name, _, value = item.partition(sep)
            pairs.append((name, value))
    return specs_from_pairs(pairs)


def business_types(codes):
    """['10', '20'] -> ['Manufacturer', 'Exporter'] (unknown codes dropped)."""
    out = []
    for code in codes or []:
        name = BUSINESS_TYPE_NAMES.get(to_int(code))
        if name and name not in out:
            out.append(name)
    return out


def split_list(value, sep=","):
    """'a, b,,a' -> ['a', 'b'] (trimmed, deduped, order kept)."""
    if isinstance(value, list):
        parts = value
    elif isinstance(value, str):
        parts = value.split(sep)
    else:
        return []
    out = []
    for part in parts:
        part = text(part)
        if part and part not in out:
            out.append(part)
    return out


def storefront(alias=None, supplier_id=None):
    """The supplier's indiamart.com storefront link from its alias, else the
    /company/<id>/ redirect link, else None."""
    if alias:
        return f"{WWW}/{alias}/"
    if supplier_id:
        return f"{WWW}/company/{supplier_id}/"
    return None


def alias_of(value):
    """Storefront alias from a www.indiamart.com/<alias>/… link, else None."""
    value = text(value)
    if not value:
        return None
    match = re.match(r"^https?://(?:www\.|m\.)?indiamart\.com/([a-z0-9][a-z0-9-]{1,99})(?:/|$)", value, re.I)
    if not match or match.group(1).lower() in ("proddetail", "company", "impcat", "search", "items"):
        return None
    return match.group(1).lower()


def own_website(value):
    """A supplier's own domain link (None for indiamart.com links)."""
    value = link(value)
    if not value or re.match(r"^https://(?:[a-z0-9-]+\.)?indiamart\.com(?:/|$)", value, re.I):
        return None
    return value


def location(city=None, district=None, state=None, country=None, postal_code=None,
             locality=None, address=None):
    return {
        "address": text(address),
        "locality": text(locality),
        "city": text(city),
        "district": text(district),
        "state": text(state),
        "postal_code": text(postal_code),
        "country": text(country),
    }


def product_id_of(value):
    """Display id from a /proddetail/…-<id>.html link."""
    match = re.search(r"-?(\d{6,16})\.html", str(value or ""))
    return int(match.group(1)) if match else None


# ---- search ----------------------------------------------------------------------

def _search_supplier(f):
    alias = text(f.get("companyalias"))
    member_since = iso_date(f.get("memberSince"))
    return {
        "slug": alias,
        "name": text(f.get("companyname")),
        "link": storefront(alias),
        "website": own_website(f.get("paidurl") or f.get("catalog_url")),
        "phone": phone(f.get("pns")),
        "rating": number(f.get("supplier_rating")) or None,
        "review_count": to_int(f.get("rating_count")),
        "call_response_rate": percent(f.get("pns_success_ratio")),
        "business_types": business_types(f.get("biztype")),
        "gst_number": text(f.get("gstNumber")),
        "is_gst_verified": flag(f.get("gstVerifiedFlag")) if "gstVerifiedFlag" in f else None,
        "is_email_verified": flag(f.get("emailVerifiedFlag")),
        "is_mobile_verified": flag(f.get("primaryMobileVerifiedFlag")),
        "is_verified_exporter": bool(flag(f.get("isverifiedexporter")) or flag(f.get("vef_flag"))),
        "has_import_export_code": bool(flag(f.get("iecflag"))),
        "member_since": member_since,
        "years_on_platform": years(f.get("memberSinceDisplay")),
        "video": media_link(dig(f, "company_video", 0)),
        "location": location(city=f.get("city"), district=f.get("district"), state=f.get("state"),
                             country=f.get("countryname") or ("India" if f.get("countryiso") == "IN" else None),
                             postal_code=f.get("zipcode"), locality=f.get("locality"),
                             address=f.get("address")),
    }


def _search_product(f):
    categories = []
    names = f.get("mcatname") if isinstance(f.get("mcatname"), list) else []
    for index, cat_id in enumerate(f.get("mcatid") if isinstance(f.get("mcatid"), list) else []):
        categories.append({"id": to_int(cat_id), "name": text(names[index]) if index < len(names) else None})
    image = media_link(f.get("photo_1000")) or media_link(f.get("zoomed_image")) \
        or media_link(f.get("large_image")) or media_link(f.get("image"))
    catalogue_page = text(f.get("usrpcatflname"))
    return {
        "id": to_int(f.get("displayid")),
        "name": text(f.get("title")) or text(f.get("original_title")),
        "short_name": text(f.get("original_title")),
        "link": link(f.get("title_url")),
        "description": multiline(f.get("smalldescorg")),
        "image": image,
        "image_count": to_int(f.get("photo_count")),
        "video": media_link(f.get("prod_video")),
        "brochure": media_link(f.get("prod_doc")),
        "price": price(f.get("itemprice"), f.get("itemcurrency"), f.get("moq_type"),
                       f.get("indiaPriceFormat")),
        "min_order": quantity(f.get("moq"), f.get("moq_type")),
        "specifications": specs_from_strings(f.get("isq")),
        "categories": categories,
        "supplier_catalogue_page": catalogue_page[:-5] if catalogue_page and catalogue_page.endswith(".html") else catalogue_page,
        "is_sponsored": bool(flag(f.get("is_pla_product")) or text(f.get("premium_listing"))),
        "is_service": text(f.get("datatype")) == "service",
    }


def _fields(entry):
    """A result's field dict (lead results wrap it in `fields`; the
    more_results siblings are bare)."""
    if not isinstance(entry, dict):
        return {}
    inner = entry.get("fields")
    return inner if isinstance(inner, dict) else entry


def _pairs(flat):
    """Solr facet list ['Pune', '2708', …] -> [('Pune', 2708), …]."""
    out = []
    if isinstance(flat, list):
        for index in range(0, len(flat) - 1, 2):
            out.append((text(flat[index]), to_int(flat[index + 1])))
    return out


def search_filters(payload):
    """The filter options the result page offers for this query."""
    facets = payload.get("facet_fields") if isinstance(payload.get("facet_fields"), dict) else {}
    cities = [{"name": name, "product_count": count} for name, count in _pairs(facets.get("city"))
              if name and name.lower() != "all india"]
    types = []
    for code, _ in _pairs(facets.get("biztype")):
        name = BUSINESS_TYPE_NAMES.get(to_int(code))
        if name:
            types.append(name)
    ranges = []
    for item in dig(payload, "priceData", "filters", default=[]) or []:
        if isinstance(item, dict):
            ranges.append({"label": text(item.get("displayName")), "min_price": number(item.get("minPrice")),
                           "max_price": number(item.get("maxPrice")), "unit": text(item.get("unit"))})
    return {"cities": cities, "business_types": types, "price_ranges": ranges}


def parse_search(payload, query):
    """search.rp body -> {query, total_count, groups, filters}. Each group is
    {supplier, products} in rank order (the lead product first, then the
    supplier's other matching products)."""
    payload = payload if isinstance(payload, dict) else {}
    groups = []
    for entry in payload.get("results") or []:
        lead = _fields(entry)
        if not lead:
            continue
        products = [_search_product(lead)]
        for more in entry.get("more_results") or []:
            fields = _fields(more)
            if fields:
                products.append(_search_product(fields))
        products = [p for p in products if p["id"] or p["name"]]
        if products:
            groups.append({"supplier": _search_supplier(lead), "products": products})
    corrected = text(dig(payload, "guess", "modified"))
    detected_city = None
    cities = dig(payload, "location_info", "cities")
    if isinstance(cities, dict) and cities:
        detected_city = text(next(iter(cities)))
    return {
        "query": query,
        "interpreted_query": corrected if corrected and corrected.lower() != str(query).lower() else None,
        "detected_city": detected_city.title() if detected_city else None,
        "total_count": to_int(payload.get("total_results")) or 0,
        "groups": groups,
        "filters": search_filters(payload),
    }


# ---- category listing ------------------------------------------------------------

def _category_supplier(card):
    supplier_id = to_int(card.get("gl_id"))
    alias = alias_of(card.get("s_url"))
    locality = card.get("ad")
    if locality == card.get("city") or str(locality or "").strip().lower().startswith("deals in "):
        locality = None                          # the city again, or a "Deals in <city>" label
    return {
        "id": supplier_id,
        "slug": alias,
        "name": text(card.get("CMP")),
        "link": storefront(alias, supplier_id),
        "website": own_website(card.get("s_url")),
        "phone": phone(card.get("c_ct")),
        "rating": number(card.get("wt_avg")) or None,
        "review_count": to_int(card.get("tr_c")),
        "call_response_rate": percent(card.get("PF")),
        "membership_tier": text(card.get("g_cn")),
        "is_gst_verified": flag(card.get("gst_v")) if "gst_v" in card else None,
        "is_email_verified": flag(card.get("ev")) if "ev" in card else None,
        "is_mobile_verified": flag(card.get("mv")) if "mv" in card else None,
        "is_verified_exporter": bool(flag(card.get("vefexp"))) if "vefexp" in card else None,
        "is_verified_supplier": flag(card.get("vf_sp")) if "vf_sp" in card else None,
        "years_on_platform": years(card.get("m_sn")),
        "location": location(city=card.get("city"), locality=locality,
                             address=card.get("f_ad"), country=card.get("g_c")),
    }


def _category_product(card):
    specs = specs_from_pairs((item.get("MASTER_DESC"), item.get("OPTIONS_DESC"))
                             for item in card.get("isq") or [] if isinstance(item, dict))
    return {
        "id": to_int(card.get("disp_id")),
        "name": text(card.get("p_nm")) or text(card.get("f_nm")),
        "short_name": text(card.get("f_nm")),
        "link": link(card.get("p_url")),
        "description": multiline(card.get("ds")),
        "image": media_link(card.get("photo")),
        "image_count": to_int(card.get("imgc")),
        "brochure": media_link(card.get("pdf")),
        "price": price(card.get("prd_price") or _amount_of(card.get("pr")), "INR", None, card.get("pr")),
        "specifications": specs,
    }


def _amount_of(display):
    """'₹ 30,00,000/Piece' -> 3000000 (cards without a numeric price field)."""
    shown = text(display)
    if not shown:
        return None
    match = re.search(r"\d[\d,]*(?:\.\d+)?", shown)
    if not match:
        return None
    value = to_float(match.group(0))
    low = shown.lower()
    if value is not None and "lakh" in low:
        value *= 100000
    elif value is not None and ("crore" in low or re.search(r"\bcr\b", low)):
        value *= 10000000
    return round(value, 2) if value is not None else None


def category_exists(state):
    return bool(isinstance(state, dict) and text(state.get("mcatname")) and text(state.get("mcatflname")))


def _category_identity(state):
    slug = text(state.get("mcatflname"))
    city_slug = text(state.get("cityflname"))
    if city_slug in (None, "impcat", "impcat1", "city"):
        city_slug = None
    crumbs = {}
    for item in state.get("breadcrumb") or []:
        if isinstance(item, dict):
            crumbs.update(item)
    parent_slug = text(dig(crumbs, "PARENT_MCAT", "pmcatflName"))
    sub_slug = text(dig(crumbs, "CAT", "catflName")) or text(state.get("cat_link"))
    return {
        "id": to_int(state.get("mcatid")),
        "slug": slug,
        "name": text(state.get("mcatname")),
        "singular_name": text(state.get("mcatsingular_name")),
        "link": f"{DIR}/{city_slug or 'impcat'}/{slug}.html" if slug else None,
        "image": media_link(state.get("mcat_img")),
        "is_brand": bool(flag(state.get("is_brand"))),
        "is_service": text(state.get("mcatprod")) == "S",
        "parent_category": {
            "slug": parent_slug,
            "name": text(dig(crumbs, "PARENT_MCAT", "pmcatName")),
            "link": f"{DIR}/impcat/{parent_slug}.html",
        } if parent_slug else None,
        "sub_category": {
            "id": to_int(state.get("catid")),
            "slug": sub_slug,
            "name": text(dig(crumbs, "CAT", "catName")),
        } if sub_slug or state.get("catid") else None,
        "industry": {"id": to_int(state.get("groupid")), "slug": text(state.get("grp_link"))}
        if state.get("groupid") or state.get("grp_link") else None,
    }


def parse_category_products(state):
    """ajaxData state -> {category, city, total_count, groups}: one group per
    card = the supplier + the lead product and its more_prod siblings."""
    state = state if isinstance(state, dict) else {}
    groups = []
    for card in state.get("data") or []:
        if not isinstance(card, dict):
            continue
        products = [_category_product(card)]
        for more in card.get("more_prod") or []:
            if isinstance(more, dict):
                products.append(_category_product(more))
        products = [p for p in products if p["id"] or p["name"]]
        if products:
            groups.append({"supplier": _category_supplier(card), "products": products})
    selected = to_int(state.get("bizSelected"))
    return {
        "category": _category_identity(state),
        "city": _selected_city(state),
        "business_type": BUSINESS_TYPE_NAMES.get(selected) if selected else None,
        "total_count": to_int(state.get("totalResults")) or to_int(state.get("prodsAvailable")) or 0,
        "groups": groups,
    }


def _selected_city(state):
    city_id = to_int(state.get("cityid"))
    slug = text(state.get("cityflname"))
    if not city_id or slug in (None, "impcat", "impcat1"):
        return None
    name = None
    for item in state.get("citybar") or []:
        if isinstance(item, dict) and item.get("cityFlName") == slug:
            name = text(item.get("cityName"))
            break
    return {"id": city_id, "slug": slug, "name": name or slug.replace("-", " ").title()}


def _related(items, name_key="GLCAT_MCAT_NAME", slug_key="GLCAT_MCAT_FLNAME", image_key="IMG"):
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        slug = text(item.get(slug_key))
        if not slug:
            continue
        out.append({"slug": slug, "name": text(item.get(name_key)),
                    "link": f"{DIR}/impcat/{slug}.html", "image": media_link(item.get(image_key))})
    return out


def parse_category_details(state):
    """ajaxData state -> the category's profile: identity, counts, the cities
    it is listed in, filters, related categories / brands, standard products."""
    state = state if isinstance(state, dict) else {}
    identity = _category_identity(state)
    slug = identity["slug"]
    cities = []
    for item in state.get("citybar") or []:
        if not isinstance(item, dict) or not item.get("cityFlName"):
            continue
        cities.append({
            "slug": text(item.get("cityFlName")),
            "name": text(item.get("cityName")),
            "state": text(item.get("stateName")),
            "link": f"{DIR}/{item.get('cityFlName')}/{slug}.html" if slug else None,
        })
    types = []
    for item in state.get("biz_filter") or []:
        if isinstance(item, dict):
            name = BUSINESS_TYPE_NAMES.get(to_int(item.get("FK_PBIZ_ID"))) or text(item.get("GL_PRIMARY_BIZ_TYPE"))
            if name and name not in types:
                types.append(name)
    ranges = []
    for item in state.get("priceData") or []:
        if isinstance(item, dict):
            ranges.append({"label": text(item.get("displayName")), "min_price": number(item.get("minPrice")),
                           "max_price": number(item.get("maxPrice")), "unit": text(item.get("unit"))})
    standard = []
    for item in state.get("relatedStdProducts") or []:
        if isinstance(item, dict) and text(item.get("name")):
            standard.append({
                "id": to_int(item.get("id")),
                "name": text(item.get("name")),
                "link": link(item.get("url"), base=DIR),
                "image": media_link(item.get("img")),
                "min_price": number(item.get("minPrice")),
                "max_price": number(item.get("maxPrice")),
                "currency": "INR",
            })
    faqs = []
    for item in state.get("questions") or []:
        if isinstance(item, dict) and text(item.get("questionText")):
            faqs.append({"question": text(item.get("questionText")),
                         "answer": multiline(dig(item, "answers", 0, "answerText"))})
    videos = [media_link(v.get("VIDEO_URL") or v.get("url")) for v in dig(state, "VIDEO_DATA", "DATA", default=[]) or []
              if isinstance(v, dict)]
    result = dict(identity)
    result.update({
        "local_name": text(state.get("hindiName")),
        "title": text(dig(state, "McatMetaData", "title")),
        "description": text(dig(state, "McatMetaData", "desc")),
        "product_count": to_int(state.get("map_ctotal")) or to_int(state.get("prodsAvailable")),
        "cities": cities,
        "business_types": types,
        "price_ranges": ranges,
        "related_categories": _related(state.get("relCat")),
        "related_brands": _related(state.get("relBrand")),
        "categories_to_explore": _related(state.get("catstoexplore"), "ch", "FL"),
        "standard_products": standard,
        "faqs": faqs,
        "videos": [v for v in videos if v],
    })
    return result


# ---- category tree ---------------------------------------------------------------

def parse_industry(state, slug):
    """/industry/<slug>.html state -> the industry + its sub-categories."""
    state = state if isinstance(state, dict) else {}
    is_service = text(state.get("prod_or_serv")) == "S"
    children = []
    for item in state.get("scats") or []:
        if not isinstance(item, dict) or not text(item.get("dir-fname")):
            continue
        section = "services" if text(item.get("type")) == "S" else "products"
        child_slug = text(item.get("dir-fname"))
        top = []
        for mcat in item.get("TopMcatData") or []:
            if isinstance(mcat, dict) and text(mcat.get("GLCAT_MCAT_FLNAME")):
                top.append({
                    "id": to_int(mcat.get("GLCAT_MCAT_ID")),
                    "slug": text(mcat.get("GLCAT_MCAT_FLNAME")),
                    "name": text(mcat.get("GLCAT_MCAT_NAME")),
                    "link": f"{DIR}/impcat/{mcat.get('GLCAT_MCAT_FLNAME')}.html",
                    "supplier_count": to_int(mcat.get("GLUSR_CNT")),
                })
        children.append({
            "id": to_int(item.get("id")),
            "slug": child_slug,
            "name": text(item.get("name")),
            "level": "sub_category",
            "link": f"{DIR}/{'indianservices' if section == 'services' else 'indianexporters'}/{child_slug}.html",
            "image": media_link(item.get("auto-image")),
            "category_count": to_int(dig(item, "TopMcatData", 0, "MCAT_CNT")),
            "product_count": to_int(item.get("mm")),
            "is_service": section == "services",
            "has_children": True,
            "top_categories": top,
        })
    return {
        "parent": {
            "id": to_int(state.get("gid")),
            "slug": text(state.get("grp_fname")) or slug,
            "name": text(state.get("grp_name")),
            "short_name": text(state.get("grp_sname")),
            "level": "industry",
            "link": f"{DIR}/industry/{text(state.get('grp_fname')) or slug}.html",
            "description": text(state.get("grp_desc")),
            "is_service": is_service,
        },
        "results": children,
    }


def _leaf(item, id_key, slug_key, name_key, image_key, count_key):
    slug = text(item.get(slug_key))
    if not slug:
        return None
    return {
        "id": to_int(item.get(id_key)),
        "slug": slug,
        "name": text(item.get(name_key)),
        "level": "category",
        "link": f"{DIR}/impcat/{slug}.html",
        "image": media_link(item.get(image_key)),
        "product_count": to_int(item.get(count_key)),
    }


def parse_sub_category(state, slug, section):
    """/indianexporters|indianservices/<slug>.html state -> the sub-category
    + its categories (each with its child categories)."""
    state = state if isinstance(state, dict) else {}
    children = []
    for item in state.get("mcats") or []:
        if not isinstance(item, dict):
            continue
        node = _leaf(item, "id", "fname", "name", "img-mcat-url", "prod-map-total")
        if not node:
            continue
        kids = [k for k in (_leaf(c, "childid", "glcat_mcat_flname", "childname",
                                  "glcat_mcat_img1_125x125", "prd_mappingcount_ctotal")
                            for c in item.get("child_mcat") or [] if isinstance(c, dict)) if k]
        node["is_brand"] = bool(flag(item.get("isbrand")))
        node["brand"] = text(item.get("brand_name"))
        node["has_children"] = False            # products are listed at this level
        node["child_categories"] = kids
        children.append(node)
    folder = "indianservices" if section == "services" else "indianexporters"
    real_slug = text(state.get("glcat_cat_flname")) or slug
    return {
        "parent": {
            "id": to_int(state.get("catid")),
            "slug": real_slug,
            "name": text(state.get("cat_name")) or text(state.get("subcat_name")),
            "short_name": None,
            "level": "sub_category",
            "link": f"{DIR}/{folder}/{real_slug}.html",
            "description": text(state.get("META_DESC")),
            "is_service": text(state.get("prod_or_serv")) == "S",
            "industry": {"slug": text(state.get("grp_flname")), "name": text(state.get("grp_name"))}
            if state.get("grp_flname") else None,
        },
        "results": children,
    }


_INDUSTRY_LINK_RE = re.compile(
    r'<a[^>]+href="(?:https://dir\.indiamart\.com)?/industry/([a-z0-9_-]+)\.html"[^>]*>(.*?)</a>', re.S | re.I)


def parse_industries(html):
    """Directory home -> the industry list (slug, name, link), in page order."""
    out, seen = [], {}
    for slug, inner in _INDUSTRY_LINK_RE.findall(html or ""):
        name = text(inner)
        slug = slug.lower()
        if slug in seen:
            if name and not seen[slug]["name"]:
                seen[slug]["name"] = name
            continue
        node = {
            "id": None,
            "slug": slug,
            "name": name,
            "level": "industry",
            "link": f"{DIR}/industry/{slug}.html",
            "has_children": True,
        }
        seen[slug] = node
        out.append(node)
    for node in out:
        if not node["name"]:
            node["name"] = node["slug"].replace("-", " ").replace("_", " ").title()
    return out


# ---- product page ----------------------------------------------------------------

_PROFILE_KEYS = {
    "nature of business": "nature_of_business",
    "additional business": "additional_business",
    "company ceo": "ceo",
    "key customers": "key_customers",
    "registered address": "registered_address",
    "industry": "industry",
    "total number of employees": "employee_count",
    "year of establishment": "year_established",
    "standards & quality certifications": "certifications",
    "legal status of firm": "legal_status",
    "promoter": "promoter",
    "annual turnover": "annual_turnover",
    "gst partner name": "gst_partner_name",
    "gst registration year": "gst_registration_year",
    "gst registration date": "gst_registration_year",
    "gst legal status of firm": "gst_legal_status",
    "gst nature of business": "gst_nature_of_business",
    "gst annual turnover": "gst_annual_turnover",
    "gst additional nob": "gst_business_activities",
    "export percentage": "export_percentage",
    "location type": "location_type",
    "building infrastructure": "building_type",
    "size of premises": "premises_size",
    "space around": "space_around",
    "payment mode": "payment_modes",
    "shipment mode": "shipment_modes",
    "customized packaging": "has_customized_packaging",
    "quality measures/testing facilities": "has_quality_testing",
    "provides after sales support": "has_after_sales_support",
}
_STATUTORY_KEYS = {
    "year of incorporation": "year_of_incorporation",
    "legal history": "legal_history",
    "banker": "bankers",
    "import export code (iec)": "import_export_code",
    "epf no.": "epf_number",
    "esi no.": "esi_number",
    "registration authority": "registration_authority",
    "registration no.": "registration_number",
    "fssai-license no": "fssai_license_number",
    "central sales tax no.": "central_sales_tax_number",
    "value added tax registration no.": "vat_number",
    "service tax registration no.": "service_tax_number",
    "excise registration no.": "excise_number",
    "ssi no.": "ssi_number",
    "cin no.": "cin",
    "sct no.": "sct_number",
    "rbi no.": "rbi_number",
    "dun & bradstreet number": "duns_number",
    "coface number": "coface_number",
    "nsic no.": "nsic_number",
    "sst no.": "sst_number",
    "gst no.": "gst_number",
    "pan no.": "pan",
    "tan no.": "tan",
    "msme udyam no.": "udyam_number",
}
_LIST_FIELDS = {"additional_business", "key_customers", "certifications", "gst_business_activities",
                "bankers", "payment_modes", "shipment_modes"}
_YEAR_FIELDS = {"year_established", "gst_registration_year", "year_of_incorporation"}
_YES_NO_FIELDS = {"has_customized_packaging", "has_quality_testing", "has_after_sales_support"}


def profile_value(key, value):
    """Shape one factsheet value by its field: lists, years, yes/no, text."""
    if key in _LIST_FIELDS:
        items = split_list(value)
        # the site repeats the same bank once per account
        seen, out = set(), []
        for item in items:
            if item.lower() not in seen:
                seen.add(item.lower())
                out.append(item)
        return out
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value if v)
    if key in _YEAR_FIELDS:
        year = to_int(value)
        return year if year and 1700 < year < 2200 else None
    if key in _YES_NO_FIELDS:
        return flag(value)
    return text(value)


def profile_table(rows, mapping):
    """[{TITLE, DATA}] -> {snake_key: value} for the known titles; rows with
    no title, an unknown title or an empty value are left out."""
    out = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = mapping.get((text(row.get("TITLE")) or "").lower())
        if not key:
            continue
        value = profile_value(key, row.get("DATA"))
        if value in (None, [], "") or (key in out and out[key] not in (None, [], "")):
            continue
        out[key] = value
    return out


def satisfaction(params):
    """{'Delivery': '88,16,18'} -> [{aspect, satisfied_percent,
    satisfied_count, rating_count}]."""
    out = []
    if isinstance(params, dict):
        for aspect, raw in params.items():
            parts = str(raw or "").split(",")
            if not text(aspect) or not parts or to_float(parts[0]) is None:
                continue
            out.append({
                "aspect": text(aspect),
                "satisfied_percent": percent(parts[0]),
                "satisfied_count": to_int(parts[1]) if len(parts) > 1 else None,
                "rating_count": to_int(parts[2]) if len(parts) > 2 else None,
            })
    return out


def _images(items):
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        large = media_link(item.get("IMAGE_1000x1000")) or media_link(item.get("IMAGE_ORIGINAL")) \
            or media_link(item.get("IMAGE_500X500"))
        if not large:
            continue
        out.append({
            "link": large,
            "medium": media_link(item.get("IMAGE_500X500")),
            "thumbnail": media_link(item.get("IMAGE_250x250")) or media_link(item.get("IMAGE_125x125")),
            "original": media_link(item.get("IMAGE_ORIGINAL")),
        })
    return out


def product_data(next_payload):
    """The product record inside __NEXT_DATA__, or None."""
    data = dig(next_payload, "props", "pageProps", "serviceRes", "Data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def parse_product(d):
    """Product page record -> product details with the seller block."""
    d = d if isinstance(d, dict) else {}
    product_id = to_int(d.get("PC_ITEM_DISPLAY_ID"))
    supplier_id = to_int(d.get("GLUSR_USR_ID"))
    website = own_website(d.get("URL"))
    alias = alias_of(d.get("URL"))
    basic = profile_table(d.get("Basic_Information"), _PROFILE_KEYS)
    statutory = profile_table(d.get("Statutory_Profile"), _STATUTORY_KEYS)
    infrastructure = profile_table(d.get("Infrastructure"), _PROFILE_KEYS)
    specs = specs_from_pairs(
        (item.get("FK_IM_SPEC_MASTER_DESC"), item.get("SUPPLIER_RESPONSE_DETAIL") or item.get("IM_SPEC_OPTIONS_DESC"))
        for item in d.get("ISQ") or [] if isinstance(item, dict))
    documents = []
    for item in d.get("ITEM_DOCS") or []:
        doc = media_link(item.get("DOC_PATH") if isinstance(item, dict) else item)
        if doc and doc not in documents:
            documents.append(doc)
    brochure = media_link(d.get("DOC_PATH")) or media_link(d.get("CTA_DOC_PATH"))
    parent_slug = text(dig(d, "PARENT_MCAT", "GLCAT_MCAT_FLNAME"))
    category_slug = text(d.get("BRD_MCAT_FLNAME"))
    rating_total = to_int(dig(d, "SUPPLIER_RATING", "TOTAL_RATINGS_COUNT")) \
        or to_int(dig(d, "SELLER_RATING_COUNTS", "total_count"))
    shown = d.get("PRICE_SEO") if "/" in str(d.get("PRICE_SEO") or "") else d.get("PRODUCT_PRICE")
    product_price = price(d.get("FOB_PRICE"), d.get("FOB_PRICE_CURRENCY"), None, shown)
    if product_price and not product_price["unit"]:
        product_price["unit"] = text(d.get("PC_ITEM_MOQ_UNIT_TYPE"))
    # the seller block repeats four factsheet rows as scalars: keep them once, in `profile`
    profile = {**basic, **infrastructure}
    for key, raw in (("employee_count", d.get("GLUSR_NOOF_EMP_VAL")), ("annual_turnover", d.get("GL_TURNOVER_VAL")),
                     ("legal_status", d.get("GL_LEGAL_STATUS_VAL")), ("year_established", d.get("GLUSR_USR_YEAR_OF_ESTB"))):
        if profile.get(key) in (None, "", []):
            value = profile_value(key, raw)
            if value not in (None, "", []):
                profile[key] = value
    export_countries = [{"code": text(c.get("iso")), "name": text(c.get("name"))}
                        for c in d.get("TOP_EXPORT_COUNTRIES") or [] if isinstance(c, dict) and c.get("name")]
    return {
        "id": product_id,
        "name": text(d.get("PC_ITEM_DISPLAY_NAME")) or text(d.get("PC_ITEM_NAME")),
        "short_name": text(d.get("PC_ITEM_NAME")),
        "link": link(d.get("PDP_CANONICAL_URL")) or (f"{WWW}/proddetail/{product_id}.html" if product_id else None),
        "description": multiline(d.get("PC_ITEM_DESC_SMALL")),
        "images": _images(d.get("ITEM_IMG")),
        "video": media_link(d.get("COMPANY_VIDEO_LINK")),
        "brochure": brochure,
        "documents": documents,
        "price": product_price,
        "min_order": quantity(d.get("PC_ITEM_MIN_ORDER_QUANTITY"), d.get("PC_ITEM_MOQ_UNIT_TYPE")),
        "specifications": specs,
        "trade": {
            "delivery_time": text(d.get("DELIVERY_TIME")),
            "production_capacity": text(d.get("PRODUCTION_CAPACITY")),
            "packaging_details": multiline(d.get("PACKAGING_DETAILS")),
            "port_of_dispatch": text(d.get("PORT_OF_DISPATCH")),
            "payment_terms": text(d.get("ETO_OFR_PAY_TERM")),
        },
        "is_service": text(d.get("IS_PROD_SERV")) == "S",
        "category": {
            "id": to_int(d.get("BRD_MCAT_ID")),
            "slug": category_slug,
            "name": text(d.get("BRD_MCAT_NAME")),
            "link": f"{DIR}/impcat/{category_slug}.html" if category_slug else None,
            "image": media_link(d.get("BRD_MCAT_NAME_IMG1_250x250")),
        },
        "parent_category": {
            "id": to_int(dig(d, "PARENT_MCAT", "GLCAT_MCAT_ID")),
            "slug": parent_slug,
            "name": text(dig(d, "PARENT_MCAT", "GLCAT_MCAT_NAME")),
            "link": f"{DIR}/impcat/{parent_slug}.html",
        } if parent_slug else None,
        "sub_category": {
            "id": to_int(d.get("BRD_CAT_ID")) or to_int(d.get("CAT_ID")),
            "slug": text(d.get("BRD_CAT_FLNAME")),
            "name": text(d.get("BRD_CAT_NAME")),
        },
        "industry_id": to_int(d.get("BRD_GRP_ID")),
        "supplier": {
            "id": supplier_id,
            "slug": alias,
            "name": text(d.get("COMPANYNAME")),
            "link": storefront(alias, supplier_id),
            "website": website,
            "logo": media_link(d.get("GLUSR_USR_LOGO_IMG")),
            "description": multiline(d.get("GLUSR_USR_DESC")),
            "contact_person": text(d.get("GLUSR_USR_FIRSTNAME")),
            "phone": phone(d.get("MOBILE_PNS")),
            "rating": number(dig(d, "SUPPLIER_RATING", "OVERALL_RATING")) or number(d.get("SELLER_RATING")) or None,
            "review_count": rating_total,
            "satisfaction": satisfaction(d.get("RATING_INFLU_PARAM")),
            "call_response_rate": percent(d.get("PNS_RATIO")),
            "membership_tier": text(d.get("GLUSR_CUST_NAME")),
            "business_type": text(d.get("BIZ")) or text(d.get("GLUSR_USR_BIZ_TYPE")),
            "member_since": iso_date(d.get("GLUSR_USR_MEMBERSINCE")),
            "years_on_platform": years(d.get("GLUSR_USR_MEMBERSINCE_NEW")),
            "is_gst_verified": flag(d.get("GST_VERIFIED")) if "GST_VERIFIED" in d else flag(d.get("GST_VERIFIED_FLAG")),
            "is_email_verified": flag(d.get("EMAIL_VERIFIED")),
            "is_mobile_verified": flag(d.get("MOBILE_VERIFIED")),
            "is_verified_exporter": bool(flag(d.get("IVE_FLAG"))),
            "export_countries": export_countries,
            "video": media_link(d.get("GLUSR_PROFILE_MEDIA_URL")),
            "location": {
                **location(city=d.get("CITY"), district=d.get("GLUSR_USR_DISTRICT"), state=d.get("GLUSR_USR_STATE"),
                           country=d.get("GLUSR_USR_COUNTRYNAME"), postal_code=d.get("GLUSR_USR_ZIP"),
                           locality=d.get("LOCALITY"), address=d.get("ADDRESS") or d.get("LONG_ADDRESS")),
                "country_code": text(d.get("FK_GL_COUNTRY_ISO")),
                "latitude": to_float(d.get("GLUSR_USR_LATITUDE")),
                "longitude": to_float(d.get("GLUSR_USR_LONGITUDE")),
            },
            "profile": profile,
            "registration": statutory,
        },
    }


def product_lookup_keys(d):
    """(category id, city id) the similar-products service needs."""
    return to_int(d.get("BRD_MCAT_ID")), to_int(d.get("CITY_ID"))


# ---- similar products ------------------------------------------------------------

def _similar_product(item):
    supplier_id = to_int(item.get("GLUSR_ID"))
    alias = text(item.get("FREESHOWROOM_ALIAS_IM")) or alias_of(item.get("COMPANY_URL"))
    category_slug = text(item.get("GLCAT_MCAT_FLNAME"))
    display = text(item.get("PRICE_SEO")) or text(item.get("PRICE_F"))
    address_parts = split_list(item.get("LONG_ADDRESS"))
    return {
        "id": to_int(item.get("DISPLAY_ID")),
        "name": text(item.get("PC_ITEM_DISPLAY_NAME")) or text(item.get("ITEM_NAME")),
        "short_name": text(item.get("ITEM_NAME")),
        "link": link(item.get("PDP_URL") or item.get("PC_ITEM_URL")),
        "description": multiline(item.get("SMALL_DESC")),
        "image": media_link(item.get("IMAGE_500X500")) or media_link(item.get("IMAGE_ORIGINAL"))
        or media_link(item.get("IMAGE_250X250")),
        "image_count": (to_int(item.get("SEC_IMG_CNT")) or 0) + 1,
        "price": price(_amount_of(display), item.get("CURRENCY") or "INR", item.get("STANDARD_UNIT"), display),
        "min_order": quantity(item.get("PRD_SEARCH_MIN_ORDER_QUANTITY")),
        "specifications": specs_from_strings(str(item.get("ISQ_RESPONSE") or "").split("::")),
        "category": {"id": to_int(item.get("MCAT_ID")), "slug": category_slug, "name": text(item.get("GLCAT_MCAT_NAME")),
                     "link": f"{DIR}/impcat/{category_slug}.html" if category_slug else None},
        "supplier": {
            "id": supplier_id,
            "slug": alias,
            "name": text(item.get("COMPANYNAME")),
            "link": storefront(alias, supplier_id),
            "website": own_website(item.get("PAIDSHOWROOM_URL")),
            "phone": phone(item.get("CONTACT_NUMBER")),
            "rating": number(dig(item, "SELLER_RATING_COUNTS", "avg_rating")) or None,
            "review_count": to_int(dig(item, "SELLER_RATING_COUNTS", "total_count")),
            "call_response_rate": percent(item.get("PNS_RATIO")),
            "membership_tier": text(item.get("GLUSR_CUST_NAME")),
            "is_gst_verified": flag(item.get("GST_VERIFIED_FLAG")),
            "is_email_verified": flag(item.get("EMAIL_VERIFIED")),
            "is_mobile_verified": flag(item.get("MOBILE_VERIFIED")),
            "is_verified_exporter": bool(flag(item.get("IVE_FLAG"))),
            "years_on_platform": years(item.get("GLUSR_USR_MEMBERSINCE")),
            "location": location(city=item.get("CITY_NAME") or item.get("SHORT_ADDRESS"),
                                 state=item.get("STATE_NAME") or (address_parts[-1] if len(address_parts) > 1 else None),
                                 locality=item.get("SDA_GLUSR_USR_LOCALITY"),
                                 postal_code=item.get("GLUSR_USR_ZIP"),
                                 country=item.get("GLUSR_USR_COUNTRYNAME")
                                 or ("India" if item.get("FK_GL_COUNTRY_ISO") == "IN" else None)),
        },
    }


def parse_similar(payload):
    """caps_service body -> {results (products), related_categories}."""
    payload = payload if isinstance(payload, dict) else {}
    products, seen = [], set()
    for key in ("RECOMMMENDATON_PRODUCT_BASED", "RECOMMMENDATON_CATEGORY_BASED",
                "RECOMMENDATION_NEWLY_HOSTED_PRODUCT_BASED", "RECOMMENDATION_NEWLY_HOSTED_CATEGORY_BASED",
                "RECOMMENDATION_SMP"):
        for item in payload.get(key) or []:
            if not isinstance(item, dict):
                continue
            product = _similar_product(item)
            if product["id"] and product["id"] not in seen:
                seen.add(product["id"])
                products.append(product)
    related = []
    for item in payload.get("RECOMMENDATION_MCAT") or []:
        if not isinstance(item, dict) or not text(item.get("IIL_DIR_REL_MCAT_FLNAME")):
            continue
        slug = text(item.get("IIL_DIR_REL_MCAT_FLNAME"))
        related.append({
            "id": to_int(item.get("IIL_DIR_REL_MCAT_ID")),
            "slug": slug,
            "name": text(item.get("IIL_DIR_REL_MCAT_NAME")),
            "link": f"{DIR}/impcat/{slug}.html",
            "city_link": link(item.get("URL"), base=DIR),
            "image": media_link(item.get("GLCAT_MCAT_IMG1_250X250")) or media_link(item.get("GLCAT_MCAT_IMG1_125X125")),
            "is_brand": bool(flag(item.get("GLCAT_MCAT_ISBRAND"))),
        })
    return {"results": products, "related_categories": related}


# ---- suggestions -----------------------------------------------------------------

def parse_suggestions(payload, key, limit):
    """suggest.php body -> [{text, …}] for `key` = product | city | mcat."""
    out = []
    for item in (payload.get(key) if isinstance(payload, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        value = text(item.get("value")) or text(item.get("label"))
        if not value:
            continue
        row = {"text": value}
        if key == "product":
            row["sub_category_id"] = to_int(dig(item, "cat_id", 0))
            row["search_count"] = to_int(item.get("freq"))
        out.append(row)
        if len(out) >= limit:
            break
    return out
