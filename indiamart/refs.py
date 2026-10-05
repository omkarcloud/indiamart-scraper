"""IndiaMART reference parsing: ONE param per input that auto-detects its
forms (tripadvisor QueryOrLinkField convention — never a sibling `url`/`id`
pair), plus the option vocabularies the routes share. Parsing is offline;
every resolver raises ValueError with a user-facing message.

  product     11558361073
              | https://www.indiamart.com/proddetail/cnc-milling-deburring-spm-11558361073.html
              | https://m.indiamart.com/proddetail/11558361073.html
  supplier    risansi                                  (storefront alias)
              | https://www.indiamart.com/risansi/[about-us.html|testimonial.html|…]
              | 20902177 | https://www.indiamart.com/company/20902177/   (numeric supplier id)
              A supplier's own domain (www.patsonmachines.com) cannot be
              mapped to its alias offline and is rejected.
  category    cnc-machines | CNC Machines
              | https://dir.indiamart.com/impcat/cnc-machines.html
              | https://dir.indiamart.com/pune/cnc-machines.html   (carries the city)
  parent      (category tree) agro-farm | https://dir.indiamart.com/industry/agro-farm.html
              | https://dir.indiamart.com/indianexporters/ac-refrigeration-equipment.html
              | https://dir.indiamart.com/indianservices/adventure-tours.html
  city        Pune | navi-mumbai | New Delhi   (-> the site's lowercase hyphen slug)

Query strings and fragments are ignored; www / m / dir / hindi hosts are
accepted wherever the path identifies the entity.
"""
import re
from urllib.parse import unquote, urlparse

WWW = "https://www.indiamart.com"
DIR = "https://dir.indiamart.com"

_SITE_HOSTS = {"indiamart.com", "www.indiamart.com", "m.indiamart.com", "dir.indiamart.com",
               "hindi.indiamart.com", "export.indiamart.com"}

_PRODUCT_ID_RE = re.compile(r"^\d{6,16}$")
_PRODUCT_PATH_RE = re.compile(r"/proddetail/(?:[^/?#]*?-)?(\d{6,16})\.html?$", re.I)
_SUPPLIER_ID_RE = re.compile(r"^\d{3,12}$")
_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,99}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,119}$")
_SPEC_SUFFIX_RE = re.compile(r"-q\d+$")

# First path segments of www.indiamart.com that are site sections, never a
# supplier alias.
RESERVED_ALIASES = {
    "proddetail", "company", "impcat", "search", "search.mp", "city", "industry", "indianexporters",
    "indianservices", "items", "isearch", "products", "suppliers", "buyer", "seller", "enquiry",
    "api", "ajaxrequest", "ajaxrequestcompanydesktop", "cgi", "static", "help", "about", "terms-of-use",
    "privacy-policy", "sitemap", "login", "register", "my", "messages", "bl", "buyleads", "tenders",
    "export", "dir", "hindi", "m", "www", "corporate", "blog", "careers",
}

# Sections of dir.indiamart.com that hold category-tree levels.
TREE_SECTIONS = {"industry": "industry", "indianexporters": "products", "indianservices": "services"}

# public value -> the site's primary-business-type id (FK_PBIZ_ID)
BUSINESS_TYPES = {
    "manufacturer": 10,
    "exporter": 20,
    "wholesaler": 30,
    "retailer": 40,
    "service_provider": 50,
}
BUSINESS_TYPE_NAMES = {
    10: "Manufacturer", 20: "Exporter", 30: "Wholesaler/Distributor", 40: "Retailer",
    50: "Service Provider",
}
BUSINESS_TYPE_BY_ID = {v: k for k, v in BUSINESS_TYPES.items()}

# public value -> search.rp annualTurnover bucket
ANNUAL_TURNOVER = {"under_1_5_crore": "bucket1", "1_5_to_5_crore": "bucket2", "above_5_crore": "bucket3"}
# public value -> (gstMinYear, gstMaxYear)
GST_REGISTRATION_AGE = {"under_1_year": (0, 1), "1_to_3_years": (1, 3), "above_3_years": (3, None)}

# public value -> SellerRatingDesktop sort_type
REVIEW_SORTS = {"top": "1", "recent": "2", "with_comments": "6"}


def _parse_link(value):
    """(host, path) of a link, or None when `value` is not link-like."""
    text = value.strip()
    if text.startswith("//"):
        text = "https:" + text
    if not re.match(r"^https?://", text, re.I):
        # scheme-less: only "host/path" or a bare site host counts as a link —
        # "screw-pump.html" and "cnc-machines.html" are slugs, not hosts
        host = text.split("/", 1)[0].lower()
        if not re.match(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$", host) or host.endswith((".html", ".htm")):
            return None
        if "/" not in text and host not in _SITE_HOSTS and not host.startswith("www."):
            return None
        text = "https://" + text
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    return host, unquote(parsed.path or "/")


def _segments(path):
    return [s for s in path.split("/") if s]


def slugify(value):
    """'CNC Machines' / 'New Delhi' -> 'cnc-machines' / 'new-delhi'."""
    text = re.sub(r"[^a-z0-9_]+", "-", str(value).strip().lower())
    return text.strip("-")


# ---- product ---------------------------------------------------------------------

def resolve_product_ref(value):
    """Product id (the number at the end of a /proddetail/ link) -> int."""
    text = str(value or "").strip()
    if _PRODUCT_ID_RE.match(text):
        return int(text)
    link = _parse_link(text)
    if link:
        host, path = link
        if host not in _SITE_HOSTS:
            raise ValueError("Must be an IndiaMART product id or an indiamart.com/proddetail/ link.")
        match = _PRODUCT_PATH_RE.search(path)
        if match:
            return int(match.group(1))
    raise ValueError("Must be an IndiaMART product id (e.g. 11558361073) or a "
                     "https://www.indiamart.com/proddetail/…-<id>.html link.")


def product_link(product_id):
    return f"{WWW}/proddetail/{int(product_id)}.html"


# ---- supplier --------------------------------------------------------------------

def resolve_supplier_ref(value):
    """Storefront alias (lowercase) or the numeric supplier id as a digit
    string — fetch.py follows /company/<id>/ to the alias."""
    text = str(value or "").strip()
    if not text:
        raise ValueError("Must not be empty.")
    link = _parse_link(text)
    if link:
        host, path = link
        if host not in _SITE_HOSTS:
            raise ValueError("Must be an indiamart.com storefront link, alias or supplier id — a supplier's "
                             "own domain cannot be resolved; use its https://www.indiamart.com/<alias>/ link.")
        if host == "dir.indiamart.com":
            raise ValueError("That is a category link, not a supplier storefront link.")
        segs = _segments(path)
        if len(segs) >= 2 and segs[0].lower() == "company" and _SUPPLIER_ID_RE.match(segs[1]):
            return segs[1]
        if not segs:
            raise ValueError("The link has no supplier alias (expected https://www.indiamart.com/<alias>/).")
        text = segs[0]
    text = text.strip("/").lower()
    if _SUPPLIER_ID_RE.match(text):
        return text
    if text.endswith(".html") or text in RESERVED_ALIASES or not _ALIAS_RE.match(text):
        raise ValueError("Must be a supplier alias (e.g. risansi), a https://www.indiamart.com/<alias>/ link "
                         "or a numeric supplier id.")
    return text


def supplier_link(alias, page=""):
    return f"{WWW}/{alias}/{page}"


def supplier_alias_of(link):
    """Alias from any www/m.indiamart.com storefront link, else None."""
    parsed = _parse_link(str(link or ""))
    if not parsed:
        return None
    host, path = parsed
    if host not in ("www.indiamart.com", "indiamart.com", "m.indiamart.com"):
        return None
    segs = _segments(path)
    if not segs:
        return None
    alias = segs[0].lower()
    if alias in RESERVED_ALIASES or alias.endswith(".html") or not _ALIAS_RE.match(alias):
        return None
    return alias


def resolve_supplier_category_ref(value):
    """A supplier's own catalogue page: slug or its storefront link
    (screw-pump | screw-pump.html | https://www.indiamart.com/risansi/screw-pump.html)."""
    text = str(value or "").strip()
    link = _parse_link(text)
    if link:
        segs = _segments(link[1])
        if not segs:
            raise ValueError("The link has no catalogue page.")
        text = segs[-1]
    text = text.split("#")[0].split("?")[0].strip("/").lower()
    if text.endswith(".html"):
        text = text[:-5]
    if not _SLUG_RE.match(text):
        raise ValueError("Must be a catalogue page slug (e.g. screw-pump) or its storefront link.")
    return text


# ---- category --------------------------------------------------------------------

def resolve_category_ref(value):
    """{"slug", "city"}: the category's file name and, when a city listing
    link was pasted, that city's slug (else None)."""
    text = str(value or "").strip()
    if not text:
        raise ValueError("Must not be empty.")
    city = None
    link = _parse_link(text)
    if link:
        host, path = link
        if host not in _SITE_HOSTS:
            raise ValueError("Must be an IndiaMART category slug, name or dir.indiamart.com link.")
        segs = _segments(path)
        if len(segs) < 2 or not segs[-1].lower().endswith(".html"):
            raise ValueError("Must be a category link like https://dir.indiamart.com/impcat/cnc-machines.html.")
        section = segs[-2].lower()
        if section in TREE_SECTIONS:
            raise ValueError("That link is an industry / sub-category page; pass it to /categories as `parent`.")
        if section not in ("impcat", "impcat1", "city"):
            city = section
        slug = segs[-1][:-5].lower()
    else:
        slug = slugify(text[:-5] if text.lower().endswith(".html") else text)
    slug = _SPEC_SUFFIX_RE.sub("", slug)
    if not _SLUG_RE.match(slug):
        raise ValueError("Must be a category slug (e.g. cnc-machines), name or dir.indiamart.com link.")
    return {"slug": slug, "city": city}


def category_link(slug, city=None):
    return f"{DIR}/{city or 'impcat'}/{slug}.html"


def resolve_parent_ref(value):
    """A category-tree node: {"section": "industry" | "products" |
    "services" | None, "slug"}. A bare slug has no section — the caller
    tries the industry level first, then the sub-category level."""
    text = str(value or "").strip()
    if not text:
        raise ValueError("Must not be empty.")
    link = _parse_link(text)
    if link:
        host, path = link
        if host not in _SITE_HOSTS:
            raise ValueError("Must be an IndiaMART industry / sub-category slug or dir.indiamart.com link.")
        segs = _segments(path)
        if len(segs) >= 2 and segs[-2].lower() in TREE_SECTIONS and segs[-1].lower().endswith(".html"):
            return {"section": TREE_SECTIONS[segs[-2].lower()], "slug": segs[-1][:-5].lower()}
        raise ValueError("Must be a https://dir.indiamart.com/industry/<slug>.html or "
                         "/indianexporters/<slug>.html link (a /impcat/ link is a leaf category).")
    slug = text[:-5] if text.lower().endswith(".html") else text
    slug = slug.strip().lower()
    if not _SLUG_RE.match(slug):
        raise ValueError("Must be an industry / sub-category slug (e.g. agro-farm) or its dir.indiamart.com link.")
    return {"section": None, "slug": slug}


def tree_link(section, slug):
    folder = {"industry": "industry", "products": "indianexporters", "services": "indianservices"}[section]
    return f"{DIR}/{folder}/{slug}.html"


# ---- city ------------------------------------------------------------------------

def resolve_city(value):
    """City name or slug -> the site's lowercase hyphen slug ('New Delhi' -> 'new-delhi')."""
    slug = slugify(value or "")
    if not slug or len(slug) > 60:
        raise ValueError("Must be an Indian city name or slug (e.g. Pune, navi-mumbai).")
    return slug
