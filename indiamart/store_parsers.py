"""Supplier storefront (www.indiamart.com/<alias>/…) -> stable dicts.

The storefront is server-rendered: window.__COMPANY_DATA__ carries the
identity, semantic HTML carries the profile (factsheet tables, catalogue
cards, MCA registration page, TrustSEAL certificate) and the hydration
islands carry JSON props (data-island / data-props) — reviews, gallery
media, product brochures. Shared value helpers come from parsers.py.

Intentionally skipped (and why):
  __COMPANY_DATA__  mcat0 / rcvCityId / rcvCustType / serviceName / glb_cntCd /
                    userCountry / showEnquiry / showAds / proserve (targeting +
                    render switches); top8Products (repeats the catalogue)
  page chrome       nav, sticky header, enquiry / login / call-now islands,
                    share links, "Explore our categories" footer strip
                    (repeats the catalogue), JSON-LD Product snippets (repeat
                    catalogue cards with a display price string)
  product cards     thumbnail radio inputs, "Get Best Quote" / "Get More
                    Photos" CTAs, EnquiryButton tracking props (section,
                    position, formType, ctaName, htmlLabel)
  reviews           FK_GLUSR_BUYER_ID (buyer account id), SORT_TIMESTAMP,
                    GLUSR_RATING_DISPLAY_STATUS / DISABLED_RATING_CNT /
                    FK_GLUSR_RATING_SOURCE / FK_GLUSR_RATING_TYPE /
                    GLUSR_RATING_MODREF_ID (an enquiry reference, not a product id) /
                    GLUSR_RATING_MODID (moderation + source codes),
                    RATING_REVIEW_ABUSE_CNT, SUPPLIER_NAME /
                    SUPPLIER_COMPANY_NAME (empty), display_flag / is_display /
                    in_percentage (render switches)
  gallery           imgW / imgH / gridSpan (layout), pdpUrl (empty)
  TrustSEAL page    QR code image, masked GST number (the full one is on the
                    profile), decorative certificate images
"""
import json
import re

from bs4 import BeautifulSoup

from indiamart import parsers as P

WWW = P.WWW

_COUNT_RE = re.compile(r"(\d[\d,]*)\s+products?", re.I)
_CONTACT_RE = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")
_YOUTUBE_RE = re.compile(r"(?:youtube\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/|img\.youtube\.com/vi/)([A-Za-z0-9_-]{6,})")


def soup(html):
    return BeautifulSoup(html or "", "lxml")


def _txt(node):
    return P.text(node.get_text(" ", strip=True)) if node is not None else None


def _rich(node):
    """A rich-text node -> plain text with its line / list breaks kept."""
    if node is None:
        return None
    return P.multiline(node.decode_contents())


def island_props(doc, name):
    """Every data-props JSON of the islands called `name`, in page order."""
    out = []
    for node in doc.select(f'[data-island="{name}"]'):
        raw = node.get("data-props")
        if not raw:
            continue
        try:
            props = json.loads(raw)
        except ValueError:
            continue
        if isinstance(props, dict):
            out.append(props)
    return out


def _abs(href, alias=None):
    """Storefront-relative href -> absolute link (fragment kept)."""
    href = P.text(href)
    if not href:
        return None
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return WWW + href
    if href.startswith("http://"):
        return "https://" + href[7:]
    if href.startswith("https://"):
        return href
    if alias and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return f"{WWW}/{alias}/{href}"
    return None


def _page_slug(href):
    """'/risansi/screw-pump.html#123' -> 'screw-pump'."""
    href = (P.text(href) or "").split("#")[0].split("?")[0].rstrip("/")
    name = href.rsplit("/", 1)[-1]
    return name[:-5] if name.endswith(".html") else (name or None)


def _fragment_id(href):
    match = re.search(r"#(\d{6,16})$", P.text(href) or "")
    return int(match.group(1)) if match else None


def _image(node):
    if node is None:
        return None
    return P.media_link(node.get("data-dataimg") or node.get("data-src") or node.get("src"))


# ---- identity (every storefront page) --------------------------------------------

def company_blob(company_data):
    company = company_data.get("company") if isinstance(company_data, dict) else None
    return company if isinstance(company, dict) else {}


def _json_ld_org(doc):
    for node in doc.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(node.string or "")
        except (TypeError, ValueError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Organization":
                return item
    return {}


def _contact(doc):
    """Footer "Reach Us" block -> (address, {name, designation})."""
    address = _txt(doc.select_one(".footer__address"))
    person = _txt(doc.select_one(".footer__contact-name"))
    contact = None
    if person:
        match = _CONTACT_RE.match(person)
        contact = {"name": match.group(1).strip(), "designation": match.group(2).strip()} if match \
            else {"name": person, "designation": None}
    return address, contact


def _header_flags(doc):
    header = doc.select_one("#company-header")
    labels = [(_txt(n) or "").lower() for n in header.select(".detail-item")] if header else []
    response = None
    if header is not None:
        match = re.search(r"(\d{1,3})\s*%\s*Response rate", header.get_text(" ", strip=True), re.I)
        response = int(match.group(1)) if match else None
    return {
        "is_trustseal_verified": any("trustseal" in label for label in labels),
        "is_payment_protected": any("payment protected" in label for label in labels),
        "call_response_rate": response,
    }


def _pages(doc, alias):
    """The storefront's own pages, from the nav + the About dropdown."""
    pages = {}

    def put(key, href):
        target = _abs(href, alias)
        if target and key not in pages:
            pages[key] = target

    for node_id, key in (("nav-trigger-catindex", "products"), ("nav-trigger-aboutus", "about"),
                         ("nav-trigger-videos", "videos"), ("nav-trigger-gallery", "photos"),
                         ("nav-trigger-enquiry", "contact")):
        node = doc.select_one(f"#{node_id}")
        if node is not None:
            put(key, node.get("href"))
    sub_links = []
    for props in island_props(doc, "NavProductsDropdown"):
        sub_links.extend(item for item in props.get("subLinks") or [] if isinstance(item, dict))
    brochure = None
    extra = []
    for item in sub_links:
        kind, href, label = P.text(item.get("pageType")), item.get("link"), P.text(item.get("label"))
        if kind == "cinpage":
            put("registration", href)
        elif kind == "testimonial":
            put("reviews", href)
        elif kind == "corporate-brochure" and str(href or "").lower().endswith(".pdf"):
            brochure = P.media_link(href)
        elif label and href:
            target = _abs(href, alias)
            if target and all(target != e["link"] for e in extra):
                extra.append({"title": label, "link": target})
    if "reviews" not in pages:
        node = doc.select_one("a.rating-container--link, a[href$='testimonial.html']")
        if node is not None:
            put("reviews", node.get("href"))
    if doc.select_one("a[href$='/trustseal/']") is not None:
        put("trustseal", f"/{alias}/trustseal/")
    return pages, extra, brochure


def rating_summary(ssr):
    """RatingReviews ssrData / SellerRatingDesktop Data -> rating block."""
    ssr = ssr if isinstance(ssr, dict) else {}
    counts = ssr.get("rating_counts") if isinstance(ssr.get("rating_counts"), dict) else {}
    total = P.to_int(counts.get("total_count"))
    breakdown = {str(star): P.to_int(counts.get(f"{word}_star_count")) or 0
                 for star, word in ((5, "five"), (4, "four"), (3, "three"), (2, "two"), (1, "one"))}
    return {
        "rating": P.number(counts.get("avg_rating")) or None,
        "review_count": total,
        "breakdown": breakdown if counts else None,
        "satisfaction": P.satisfaction(ssr.get("rating_influ_params_name")),
    }


def page_reviews_state(doc):
    """(supplier id, ssrData) from the page's RatingReviews island."""
    for props in island_props(doc, "RatingReviews"):
        ssr = props.get("ssrData") if isinstance(props.get("ssrData"), dict) else None
        return P.to_int(props.get("glid")), ssr
    return None, None


def parse_identity(doc, company_data, alias):
    """The block shared by every supplier endpoint: who the supplier is."""
    c = company_blob(company_data)
    alias = P.text(c.get("alias")) or alias
    org = _json_ld_org(doc)
    address, contact = _contact(doc)
    _, ssr = page_reviews_state(doc)
    website = P.own_website((ssr or {}).get("paid_catalog_url"))
    if website:
        website = re.sub(r"^(https://[^/]+/).*$", r"\1", website)
    summary = rating_summary(ssr) if ssr else None
    return {
        "id": P.to_int(c.get("glid")),
        "slug": alias,
        "name": P.text(c.get("companyName")) or _txt(doc.select_one("#company-header h1")),
        "link": f"{WWW}/{alias}/" if alias else None,
        "website": website,
        "logo": P.media_link(c.get("companyLogo")) or P.media_link(org.get("logo")),
        "phone": P.phone(c.get("pnsNumber")),
        "contact_person": contact,
        "rating": (summary or {}).get("rating") or P.number(c.get("seller_rating")) or None,
        "review_count": (summary or {}).get("review_count") if summary and summary.get("review_count") is not None
        else P.to_int(c.get("rating_count")),
        "business_type": P.text(c.get("businessType")),
        "years_on_platform": P.years(c.get("membersince")),
        "year_established": P.profile_value("year_established", org.get("foundingDate")),
        "is_gst_verified": P.flag(c.get("gst_verified_flag")),
        "is_verified_exporter": bool(P.flag(c.get("verified_exporter_flag"))),
        "is_paid_member": P.flag(c.get("isPaid")),
        **_header_flags(doc),
        "location": P.location(
            address=address,
            city=c.get("city") or P.dig(org, "address", "addressLocality"),
            state=c.get("state") or P.dig(org, "address", "addressRegion"),
            postal_code=P.dig(org, "address", "postalCode"),
            country=c.get("rcvCountry") or P.dig(org, "address", "addressCountry")),
    }


def supplier_ref(identity):
    """The compact supplier stub list endpoints attach to their results."""
    return {key: identity.get(key) for key in ("id", "slug", "name", "link")}


# ---- profile (home + about pages) ------------------------------------------------

_FACT_KEYS = dict(P._PROFILE_KEYS)
_FACT_KEYS.update(P._STATUTORY_KEYS)
_FACT_KEYS.update({"gst number": "gst_number", "import export code (iec)": "import_export_code"})
_REGISTRATION_FIELDS = set(P._STATUTORY_KEYS.values())


def _dd_value(dd):
    items = [P.text(li.get_text(" ", strip=True)) for li in dd.select("li")]
    items = [item for item in items if item]
    return items if items else _txt(dd)


def _facts(rows):
    """[(label, value)] -> ({profile}, {registration}) by known label."""
    profile, registration = {}, {}
    for label, value in rows:
        key = _FACT_KEYS.get((label or "").strip().lower())
        if not key:
            continue
        shaped = P.profile_value(key, value)
        if shaped in (None, [], ""):
            continue
        target = registration if key in _REGISTRATION_FIELDS else profile
        target.setdefault(key, shaped)
    return profile, registration


def parse_home_facts(doc):
    """The home page's factsheet strip (dl.factsheet)."""
    rows = []
    for item in doc.select("dl.factsheet .factsheet-item"):
        value = item.select_one(".factsheet-value")
        if value is not None:
            rows.append((_txt(item.select_one(".factsheet-label")), _dd_value(value)))
    return _facts(rows)


def parse_about_facts(doc):
    """The About page's full factsheet (section.factsheet-table)."""
    rows = []
    for row in doc.select(".factsheet-table .factsheet-table__row"):
        dd = row.select_one("dd")
        if dd is not None:
            rows.append((_txt(row.select_one("dt")), _dd_value(dd)))
    return _facts(rows)


def _data_images(node, attr):
    try:
        items = json.loads(node.get(attr) or "[]")
    except ValueError:
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            image = P.media_link(item.get("full") or item.get("bimg") or item.get("display") or item.get("thumb"))
            if image and image not in out:
                out.append(image)
    return out


def parse_about_sections(doc):
    """About page -> (description, [{title, text, images}], album images)."""
    description = _rich(doc.select_one(".aboutus-desc"))
    sections = []
    for article in doc.select(".extended-sections .profile-section"):
        title = _txt(article.find(["h2", "h3"]))
        body = _rich(article.select_one(".profile-section__desc"))
        media = article.select_one("[data-profile-images]")
        images = _data_images(media, "data-profile-images") if media is not None else []
        if title and (body or images):
            sections.append({"title": title, "text": body, "images": images})
    album_node = doc.select_one("[data-album-images]")
    album = _data_images(album_node, "data-album-images") if album_node is not None else []
    return description, sections, album


def parse_hsn_codes(doc):
    out = []
    for row in doc.select(".hsn-table tbody tr"):
        cells = row.find_all("td")
        if len(cells) >= 2 and P.text(cells[0].get_text()):
            out.append({"code": P.text(cells[0].get_text()), "description": P.text(P.multiline(cells[1].get_text()))})
    return out


def parse_home_categories(doc, company_data, alias):
    """The home page's "Our Products" range: one entry per catalogue page."""
    listed = {}
    for item in (company_data.get("categories") if isinstance(company_data, dict) else None) or []:
        if isinstance(item, dict) and P.text(item.get("name")):
            listed[P.text(item["name"]).lower()] = item
    out = []
    for card in doc.select(".category-range-card"):
        anchor = card.select_one("a.category-range-media") or card.select_one("a[href]")
        if anchor is None:
            continue
        slug = _page_slug(anchor.get("href"))
        name = P.text(card.select_one("img").get("alt")) if card.select_one("img") is not None else None
        if not slug:
            continue
        out.append({"slug": slug, "name": name, "link": _abs(anchor.get("href"), alias),
                    "image": _image(card.select_one("img"))})
    if not out:
        for key, item in listed.items():
            out.append({"slug": None, "name": P.text(item.get("name")), "link": None, "image": None})
    return out


def parse_details(home_doc, company_data, alias, about_doc=None):
    """Home (+ About) page -> the full supplier profile."""
    identity = parse_identity(home_doc, company_data, alias)
    alias = identity["slug"]
    pages, extra_pages, brochure = _pages(home_doc, alias)
    profile, registration = parse_home_facts(home_doc)
    description = _rich(home_doc.select_one(".about-text"))
    sections, album = [], []
    if about_doc is not None:
        about_profile, about_registration = parse_about_facts(about_doc)
        profile = {**profile, **about_profile}
        registration = {**registration, **about_registration}
        about_description, sections, album = parse_about_sections(about_doc)
        description = about_description or description
        if not identity["contact_person"] or not identity["location"]["address"]:
            address, contact = _contact(about_doc)
            identity["contact_person"] = identity["contact_person"] or contact
            identity["location"]["address"] = identity["location"]["address"] or address
    _, ssr = page_reviews_state(home_doc)
    summary = rating_summary(ssr) if ssr else {}
    result = dict(identity)
    result.update({
        "description": description,
        "rating_breakdown": summary.get("breakdown"),
        "satisfaction": summary.get("satisfaction") or [],
        "profile": profile,
        "registration": registration,
        "sections": sections,
        "album": album,
        "hsn_codes": parse_hsn_codes(home_doc),
        "catalogue": parse_home_categories(home_doc, company_data, alias),
        "brochure": brochure,
        "pages": pages,
        "more_pages": extra_pages,
    })
    return result


# ---- catalogue index ("Our Products") --------------------------------------------

def parse_catalogue(doc, alias):
    """Catalogue index page -> {title, description, results: [category]}."""
    categories = []
    for card in doc.select(".catindex-category-card"):
        name_node = card.select_one(".catindex-cat-name")
        anchor = card.select_one(".catindex-cat-name a") or card.select_one("a.catindex-simple-card-link") \
            or card.select_one("a[href]")
        if name_node is None or anchor is None:
            continue
        count = None
        count_node = card.select_one(".catindex-simple-count")
        if count_node is not None:
            match = _COUNT_RE.search(count_node.get_text(" ", strip=True))
            count = int(match.group(1).replace(",", "")) if match else None
            count_node.extract()
        for arrow in name_node.select(".catindex-simple-arrows"):
            arrow.extract()
        products = []
        for item in card.select(".catindex-product-item"):
            link_node = item.select_one(".catindex-product-name a") or item.select_one("a[href]")
            if link_node is None:
                continue
            product_id = _fragment_id(link_node.get("href"))
            products.append({
                "id": product_id,
                "name": _txt(link_node) or P.text((item.select_one("img") or {}).get("alt")),
                "link": f"{WWW}/proddetail/{product_id}.html" if product_id else None,
                "image": _image(item.select_one("img")),
            })
        if count is None and 0 < len(products) < 5:
            count = len(products)                 # the grid shows up to 5; fewer = all of them
        categories.append({
            "slug": _page_slug(anchor.get("href")),
            "name": _txt(name_node),
            "link": _abs(anchor.get("href"), alias),
            "description": _txt(card.select_one(".catindex-cat-desc")),
            "product_count": count,
            "featured_products": products,
        })
    return {
        "title": _txt(doc.select_one(".catindex-heading")),
        "description": _txt(doc.select_one(".catindex-page-desc")),
        "results": categories,
    }


# ---- one catalogue page (product cards) ------------------------------------------

def _card_media(card):
    images, videos = [], []
    for node in card.select('[data-island="CategoryImageGallery"]'):
        try:
            props = json.loads(node.get("data-props") or "{}")
        except ValueError:
            continue
        for item in props.get("galleryMedia") or []:
            if not isinstance(item, dict):
                continue
            source = P.text(item.get("src")) or ""
            video = _YOUTUBE_RE.search(source) or _YOUTUBE_RE.search(P.text(item.get("videoUrl") or item.get("thumb")) or "")
            if P.text(item.get("type")) == "video" or (video and "youtube" in source):
                target = P.media_link(item.get("videoUrl") or item.get("vidUrl")) \
                    or (f"https://www.youtube.com/watch?v={video.group(1)}" if video else None)
                if target and target not in videos:
                    videos.append(target)
                continue
            image = P.media_link(source)
            if image and image not in images:
                images.append(image)
    if not images:
        for img in card.select(".udg-category-item__stage img"):
            image = _image(img)
            if image and "youtube.com" not in image and image not in images:
                images.append(image)
    if not videos:
        for img in card.select(".udg-category-item__stage--video img"):
            match = _YOUTUBE_RE.search(img.get("src") or "")
            if match:
                videos.append(f"https://www.youtube.com/watch?v={match.group(1)}")
    return images, videos


def _card_enquiry(card):
    """The card's EnquiryButton props that carry data (brochure, ids, price)."""
    brochure, category_id, product_category_id = None, None, None
    for node in card.select('[data-island="EnquiryButton"], [data-island="PhoneReveal"]'):
        try:
            props = json.loads(node.get("data-props") or "{}")
        except ValueError:
            continue
        brochure = brochure or P.media_link(props.get("pdfurl"))
        category_id = category_id or max(P.to_int(props.get("productMcatId")) or 0, 0) or None   # "-1" = none
        product_category_id = product_category_id or max(P.to_int(props.get("productCatId")) or 0, 0) or None
    return brochure, category_id, product_category_id


def _card_product(card):
    product_id = P.to_int(card.get("id"))
    title = card.select_one(".udg-category-item__title a") or card.select_one(".udg-category-item__title")
    amount_text = _txt(card.select_one(".udg-category-item__priceAmount"))
    unit = (_txt(card.select_one(".udg-category-item__priceUnit")) or "").lstrip("/ ").strip() or None
    moq_node = card.select_one(".udg-category-item__moq strong") or card.select_one(".udg-category-item__moq")
    moq_text = _txt(moq_node) or ""
    moq_text = re.sub(r"^Minimum Order Quantity\s*:?\s*", "", moq_text, flags=re.I)
    moq_match = re.match(r"^([\d,.]+)\s*(.*)$", moq_text)
    specs = P.specs_from_pairs(
        (_txt(row.select_one(".udg-category-item__specKey")), _txt(row.select_one(".udg-category-item__specVal")))
        for row in card.select(".udg-category-item__specRow"))
    extras = {}
    for section in card.select(".udg-category-item__additional"):
        heading = _txt(section.select_one(".udg-category-item__sectionTitle"))
        bullets = [P.text(li.get_text(" ", strip=True)) for li in section.select("li")]
        bullets = [b for b in bullets if b]
        if heading and bullets:
            extras[heading] = bullets
    images, videos = _card_media(card)
    brochure, category_id, product_category_id = _card_enquiry(card)
    href = title.get("href") if title is not None and title.name == "a" else None
    return {
        "id": product_id,
        "name": _txt(title),
        "link": P.link(href) or (f"{WWW}/proddetail/{product_id}.html" if product_id else None),
        "description": _rich(card.select_one(".udg-category-item__sdescRich")),
        "images": images,
        "videos": videos,
        "brochure": brochure,
        "price": P.price(P._amount_of(amount_text), "INR", unit),
        "min_order": P.quantity(moq_match.group(1), moq_match.group(2) or None) if moq_match else None,
        "specifications": specs,
        "additional_information": _additional(extras),
        "category_id": category_id,
    }


def _additional(extras):
    """{'Additional Information': ['Item Code: X', 'Delivery Time: 2 weeks']}
    -> [{name, value}] (bullets without a colon keep name null)."""
    out = []
    for bullets in extras.values():
        for bullet in bullets:
            name, sep, value = bullet.partition(":")
            if sep and value.strip() and len(name) <= 60:
                out.append({"name": name.strip(), "value": value.strip()})
            else:
                out.append({"name": None, "value": bullet})
    return out


def parse_catalogue_page(doc, alias, slug):
    """One catalogue page -> {category, results: [product]}."""
    products = [_card_product(card) for card in doc.select("article.udg-category-item")]
    products = [p for p in products if p["id"] or p["name"]]
    return {
        "category": {
            "slug": slug,
            "name": _txt(doc.select_one(".category-heading")),
            "link": f"{WWW}/{alias}/{slug}.html",
            "description": _txt(doc.select_one(".category-description")),
        },
        "results": products,
    }


def is_catalogue_page(doc):
    return doc.select_one(".category-page, article.udg-category-item") is not None


# ---- reviews ---------------------------------------------------------------------

def _review_images(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    out = []
    for item in raw if isinstance(raw, list) else []:
        source = item if isinstance(item, str) else (item.get("full") or item.get("IMG_URL") or item.get("img_url")
                                                      or item.get("thumb") if isinstance(item, dict) else None)
        image = P.media_link(source)
        if image and image not in out:
            out.append(image)
    return out


def _review_aspects(raw):
    """'{"0":"Delivery","1":"Response,Quality"}' -> [{aspect, is_satisfied}]
    (key 1 lists what the buyer was satisfied with, key 0 what not)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    out = []
    for key in ("1", "0"):
        for aspect in P.split_list(raw.get(key) if isinstance(raw, dict) else None):
            if not aspect.isdigit():
                out.append({"aspect": aspect, "is_satisfied": key == "1"})
    return out


def _review(r):
    return {
        "id": P.to_int(r.get("GLUSR_RATING_ID")),
        "rating": P.to_int(r.get("GLUSR_RATING_VALUE")),
        "comment": P.multiline(r.get("GLUSR_RATING_COMMENTS")),
        "date": P.iso_date(r.get("GLUSR_RATING_DATE")),
        "images": _review_images(r.get("RATING_IMGS")),
        "aspects": _review_aspects(r.get("RATING_INFLU_PARAMS_NAME")),
        "helpful_count": P.to_int(r.get("RATING_REVIEW_USEFULNESS")),
        "product": {
            "name": P.text(r.get("RATING_MODREF_NAME")),
            "category_id": P.to_int(r.get("RATING_MCAT_ID")),
            "category": P.text(r.get("RATING_MCAT_NAME")),
        } if P.text(r.get("RATING_MODREF_NAME")) or P.text(r.get("RATING_MCAT_NAME")) else None,
        "reviewer": {
            "name": P.text(r.get("BUYER_NAME")),
            "company": P.text(r.get("BUYER_COMPANY_NAME")),
            "city": P.text(r.get("BUYER_CITY_NAME")),
            "state": P.text(r.get("BUYER_STATE_NAME")),
            "country": P.text(r.get("BUYER_COUNTRY_NAME")),
        },
        "supplier_reply": {
            "comment": P.multiline(r.get("SUPPLIER_COMMENTS")),
            "date": P.iso_date(r.get("GLUSR_RATING_REPLY_DATE")),
        } if P.text(r.get("SUPPLIER_COMMENTS")) else None,
    }


def reviews_data(payload):
    """The Data dict of a SellerRatingDesktop / supplierrating body, {} for
    "data not found", None for an unrecognised body."""
    if not isinstance(payload, dict):
        return None
    data = P.dig(payload, "Response", "Data")
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"rating_list": data} if data else {}
    if "rating_list" in payload or "rating_counts" in payload:
        return payload
    return None


def parse_reviews(data):
    """Reviews Data (or a page's ssrData) -> (summary, [review]) in order."""
    data = data if isinstance(data, dict) else {}
    listed = data.get("rating_list")
    if isinstance(listed, dict):
        def order(key):
            return P.to_int(key) if P.to_int(key) is not None else 10 ** 9
        rows = [listed[key] for key in sorted(listed, key=order)]
    else:
        rows = listed if isinstance(listed, list) else []
    reviews = [_review(r) for r in rows if isinstance(r, dict)]
    return rating_summary(data), [r for r in reviews if r["id"] or r["rating"]]


# ---- registration & directors ----------------------------------------------------

_HIGHLIGHT_KEYS = {
    "company registered office address": "registered_office_address",
    "category": "company_category",
    "company age": "company_age_years",
    "company cin": "cin",
    "company type": "company_type",
    "directors": "director_count",
    "incorporation date & year": "incorporation_date",
    "last agm date": "last_agm_date",
    "balance sheet date": "balance_sheet_date",
    "paid up capital": "paid_up_capital",
    "authorised capital": "authorised_capital",
    "company status": "company_status",
    "open charges": "open_charges",
    "roc": "registrar_of_companies",
    "registration number": "registration_number",
    "company sub category": "company_sub_category",
    "listing status": "listing_status",
}


def _money(value):
    """'₹ 2,24,43,280.00' -> {amount, currency}."""
    amount = P.number(re.sub(r"[^\d.,-]", "", P.text(value) or "").strip(".") or None)
    return {"amount": amount, "currency": "INR"} if amount is not None else None


def parse_registration(doc):
    """Registration & Directors page -> MCA company record + directors."""
    record = {}
    for cell in doc.select(".cin-highlight-cell"):
        label = (_txt(cell.select_one(".cin-highlight-label")) or "").lower()
        value = _txt(cell.select_one(".cin-highlight-value"))
        key = _HIGHLIGHT_KEYS.get(label)
        if not key or not value:
            continue
        if key.endswith("_date"):
            record[key] = P.iso_date(value)
        elif key == "company_age_years":
            record[key] = P.to_float(value)
        elif key == "director_count":
            record[key] = P.to_int(value)
        elif key in ("paid_up_capital", "authorised_capital"):
            record[key] = _money(value)
        elif key == "open_charges":
            match = re.search(r"\(\s*(\d+)\s*Charges?\s*\)", value, re.I)
            money = _money(value.split("(")[0])
            record[key] = {"amount": money["amount"] if money else None, "currency": "INR",
                           "charge_count": int(match.group(1)) if match else None}
        else:
            record[key] = value
    directors = []
    for table in doc.select(".cin-directors-table"):
        headers = [(_txt(th) or "").lower() for th in table.select("thead th")]
        for row in table.select("tbody tr"):
            cells = [_txt(td) for td in row.find_all("td")]
            item = dict(zip(headers, cells))
            if not any(cells):
                continue
            directors.append({
                "name": (item.get("name") or "").title() or None,
                "designation": item.get("designation"),
                "din": item.get("din"),
                "appointment_date": P.iso_date(item.get("appointment date")),
            })
    ordered = {key: record.get(key) for key in (
        "cin", "company_status", "company_type", "company_category", "company_sub_category",
        "incorporation_date", "company_age_years", "registered_office_address", "registrar_of_companies",
        "registration_number", "listing_status", "authorised_capital", "paid_up_capital", "open_charges",
        "last_agm_date", "balance_sheet_date", "director_count")}
    ordered["directors"] = directors
    return ordered


def has_registration(doc):
    return doc.select_one(".cin-highlight-cell, .cin-directors-table") is not None


# ---- TrustSEAL certificate -------------------------------------------------------

def parse_trustseal(doc):
    cert = doc.select_one(".trustseal-cert")
    if cert is None:
        return None
    details = {}
    for col in cert.select(".trustseal-cert__details-col"):
        label = (_txt(col.select_one(".trustseal-cert__details-label")) or "").lower()
        details[label] = _txt(col.select_one(".trustseal-cert__details-value"))
    cert_id = re.search(r"(\d+)", _txt(cert.select_one(".trustseal-cert__id")) or "")
    return {
        "certificate_id": int(cert_id.group(1)) if cert_id else None,
        "awarded_to": _txt(cert.select_one(".trustseal-cert__name")),
        "location": _txt(cert.select_one(".trustseal-cert__location")),
        "issued": P.month_year(details.get("issue date")),
        "valid_until": P.month_year(details.get("valid till")),
        "rating": P.number(_txt(cert.select_one(".trustseal-cert__rating-number"))),
        "verified_items": [item for item in (_txt(li) for li in cert.select(".trustseal-cert__check-item")) if item],
    }


# ---- photos / videos -------------------------------------------------------------

def parse_photos(doc):
    """Photos page -> [{product id / name, price, image, large image}]."""
    out = []
    for props in island_props(doc, "GalleryViewMore"):
        raw = props.get("initialGallery")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            image = P.media_link(item.get("popupImage")) or P.media_link(item.get("cardImage"))
            if not image:
                continue
            product_id = P.to_int(item.get("displayId")) or P.to_int(item.get("itemId"))
            shown = P.text(item.get("price"))
            out.append({
                "image": image,
                "thumbnail": P.media_link(item.get("cardImage")),
                "product": {
                    "id": product_id,
                    "name": P.text(item.get("name")),
                    "link": f"{WWW}/proddetail/{product_id}.html" if product_id else None,
                    "price": P.price(P._amount_of(shown), "INR", None, shown),
                    "is_service": P.text(item.get("itemServ")) == "S",
                },
            })
    return out


def _components(doc, name):
    """data-props JSON of the page's data-component="<name>" widgets."""
    out = []
    for node in doc.select(f'[data-component="{name}"]'):
        try:
            props = json.loads(node.get("data-props") or "{}")
        except ValueError:
            continue
        if isinstance(props, dict):
            out.append(props)
    return out


def _video(video_id, title, kind=None, thumbnail=None, uploaded=None, product_link=None):
    product_id = _fragment_id(product_link)
    return {
        "id": video_id,
        "title": P.text(title),
        "link": f"https://www.youtube.com/watch?v={video_id}",
        "thumbnail": P.media_link(thumbnail) or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "is_short": (P.text(kind) or "").upper() == "SHORTS",
        "uploaded_at": P.iso_date(uploaded),
        "product_id": product_id,
    }


def parse_videos(doc):
    """Videos page / home video sections -> [{id, title, link, thumbnail,
    is_short, uploaded_at, product_id}] (YouTube ids, deduped, page order)."""
    out, seen = [], set()

    def add(video):
        if video["id"] and video["id"] not in seen:
            seen.add(video["id"])
            out.append(video)

    for node in doc.select(".video-placeholder[data-video-id]"):          # corporate video
        add(_video(P.text(node.get("data-video-id")), node.get("data-video-title")))
    for props in _components(doc, "desktop/flips-video-player"):          # videos page
        raw = props.get("videosJson")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            match = _YOUTUBE_RE.search(P.text(item.get("CONTENT_URL")) or "")
            video_id = P.text(item.get("CONTENT_VIDEO_ID")) or (match.group(1) if match else None)
            if video_id:
                add(_video(video_id, item.get("CONTENT_TITLE"), item.get("CONTENT_MEDIA_PRODUCT_TYPE"),
                           item.get("CONTENT_THUMBNAIL_URL"), item.get("CONTENT_UPLOAD_DATE")))
    for props in _components(doc, "desktop/desktop-player"):              # home product videos
        for item in props.get("videos") or []:
            if isinstance(item, dict) and P.text(item.get("videoid")):
                add(_video(P.text(item.get("videoid")), item.get("videotitle"), item.get("type"),
                           item.get("thumbnail"), None, item.get("link")))
    return out
