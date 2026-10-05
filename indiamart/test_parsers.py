"""Offline tests for the IndiaMART parsers (no network).

    python -m pytest indiamart/test_parsers.py -q

Fixtures are real captures (2026-10-05) taken through indiamart/fetch.py and
trimmed for size: search.rp bodies (first groups kept, engine diagnostics
dropped), category ajaxData states (first cards kept), the industry /
sub-category page states re-wrapped in their window.__INITIAL_STATE__
script, the directory home's industry anchors, two product pages, the
similar-products service, a decrypted reviews page, suggest bodies and
storefront pages of two suppliers.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indiamart import fetch, parsers as P, shared, store_parsers as S  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


def load(name):
    return json.loads(raw(name))


def no_blank_strings(obj, path="$"):
    """House rule: missing values are null, never '' / 'null' / 'N/A'."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            no_blank_strings(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            no_blank_strings(value, f"{path}[{index}]")
    elif isinstance(obj, str):
        assert obj.strip() and obj.strip().lower() not in ("null", "n/a", "undefined"), path


def no_link_keys_named_url(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert "url" not in key.lower(), key
            no_link_keys_named_url(value)
    elif isinstance(obj, list):
        for value in obj:
            no_link_keys_named_url(value)


# ---- helpers ---------------------------------------------------------------------

def test_value_helpers():
    assert P.phone("8047551306") == "+918047551306"
    assert P.phone("+91-8047551306") == "+918047551306"
    assert P.phone("08047547416") == "+918047547416"
    assert P.phone("") is None
    assert P.iso_date("2007-09-19T20:19:46Z") == "2007-09-19"
    assert P.iso_date("10-02-26") == "2026-02-10"
    assert P.iso_date("23-7-1996") == "1996-07-23"
    assert P.iso_date("06/10/2019") == "2019-10-06"
    assert P.iso_date("garbage") is None
    assert P.month_year("April 2018") == "2018-04"
    assert P.years("16 yrs") == 16 and P.years("10 Months") == 0 and P.years("") is None
    assert P.price("8500000", "INR", "Piece") == {"amount": 8500000, "currency": "INR", "unit": "Piece"}
    assert P.price("65", None, None, "₹ 65/Kg") == {"amount": 65, "currency": "INR", "unit": "Kg"}
    assert P.price("", "INR") is None and P.price("0") is None
    assert P._amount_of("₹ 32 Lakh/Piece") == 3200000 and P._amount_of("₹ 4.50 Lakh") == 450000
    assert P._amount_of("₹ 50,350") == 50350
    assert P.quantity("26000", "Kg") == {"quantity": 26000, "unit": "Kg"} and P.quantity("") is None
    assert P.text("null") is None and P.text(" a  <b>b</b> ") == "a b"
    assert P.multiline("one<br /><br />two") == "one\n\ntwo"
    assert P.link("http://x.com/a?pos=1&kwd=q&tags=z") == "https://x.com/a"
    assert P.media_link("http://5.imimg.com/a.pdf#ITEM_DOC#") == "https://5.imimg.com/a.pdf"
    assert P.own_website("https://www.indiamart.com/risansi/") is None
    assert P.own_website("http://www.patsonmachines.com/") == "https://www.patsonmachines.com/"
    assert P.alias_of("https://www.indiamart.com/risansi/x.html") == "risansi"
    assert P.alias_of("https://www.indiamart.com/proddetail/x-1.html") is None
    assert P.flag("1") is True and P.flag("0") is False and P.flag("") is None and P.flag(22) is True
    assert P.specs_from_strings(["A==1", "A==1", "B==", "junk"]) == [{"name": "A", "value": "1"}]
    assert P.business_types(["10", "20", "99"]) == ["Manufacturer", "Exporter"]


def test_extract_blob_ignores_trailing_code():
    html = '<script>window.__X__ = {"a": {"b": [1, 2]}};window.y = 1</script>'
    assert fetch.extract_blob(html, "window.__X__") == {"a": {"b": [1, 2]}}
    assert fetch.extract_blob(html, "window.__MISSING__") is None
    assert fetch.extract_blob("window.__X__ = not json", "window.__X__") is None


def test_decrypt_envelope_round_trip():
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    aes_key, iv = os.urandom(32), os.urandom(12)
    sealed = AESGCM(aes_key).encrypt(iv, json.dumps({"Response": {"Code": "200"}}).encode(), None)
    wrapped = private.public_key().encrypt(
        aes_key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    b64 = lambda data: base64.b64encode(data).decode()  # noqa: E731
    envelope = {"key": b64(wrapped), "iv": b64(iv), "data": b64(sealed[:-16]), "tag": b64(sealed[-16:])}
    assert fetch.decrypt_envelope(envelope, private) == {"Response": {"Code": "200"}}
    assert fetch.decrypt_envelope({"plain": 1}, private) == {"plain": 1}


# ---- search ----------------------------------------------------------------------

def test_search_groups_and_supplier():
    parsed = P.parse_search(load("search_cnc_machine.json"), "cnc machine")
    assert parsed["total_count"] > 1000 and parsed["interpreted_query"] == "cnc machines"
    assert len(parsed["groups"]) == 4
    lead = parsed["groups"][0]
    supplier, product = lead["supplier"], lead["products"][0]
    assert supplier["slug"] == "patsonmachines"
    assert supplier["link"] == "https://www.indiamart.com/patsonmachines/"
    assert supplier["website"] == "https://www.patsonmachines.com/"
    assert supplier["phone"].startswith("+91") and len(supplier["gst_number"]) == 15
    assert supplier["member_since"] == "2007-09-19" and supplier["business_types"] == ["Manufacturer"]
    assert supplier["location"]["city"] == "Pune" and supplier["location"]["state"] == "Maharashtra"
    assert product["id"] == 11558361073 and product["link"].endswith("-11558361073.html")
    assert product["price"] == {"amount": 8500000, "currency": "INR", "unit": "Piece"}
    assert {"name": "Voltage", "value": "415V"} in product["specifications"]
    assert product["categories"][0] == {"id": 191249, "name": "Automatic CNC Machine"}
    assert product["brochure"].endswith(".pdf") and product["is_sponsored"] is True
    assert parsed["filters"]["cities"][0]["name"] == "Bengaluru"
    assert parsed["filters"]["price_ranges"][-1]["max_price"] is None
    no_blank_strings(parsed)
    no_link_keys_named_url(parsed)


def test_search_flat_and_grouped_views():
    parsed = P.parse_search(load("search_basmati_rice_mumbai.json"), "basmati rice")
    assert parsed["detected_city"] == "Mumbai"
    flat = shared.flatten_products(parsed["groups"])
    assert len(flat) == sum(len(g["products"]) for g in parsed["groups"])
    assert flat[0]["is_lead_listing"] is True and flat[0]["supplier"]["name"]
    assert [row["is_lead_listing"] for row in flat].count(True) == len(parsed["groups"])
    grouped = shared.group_suppliers(parsed["groups"])
    assert len(grouped) == len({g["supplier"]["slug"] for g in parsed["groups"]})
    assert grouped[0]["matching_product_count"] == len(grouped[0]["products"]) >= 1
    assert all(p["min_order"] is None or p["min_order"]["quantity"] > 0 for p in flat)


def test_search_survives_partial_payloads():
    for payload in (None, {}, {"results": None}, {"results": [{}, {"fields": {}}, "x"]},
                    {"results": [{"fields": {"title": "Only a title"}}], "facet_fields": {"city": ["x"]}}):
        parsed = P.parse_search(payload, "q")
        assert isinstance(parsed["groups"], list) and parsed["total_count"] == 0
    assert P.parse_search({"results": [{"fields": {"title": "Only a title"}}]}, "q")["groups"][0]["products"][0]["price"] is None


# ---- categories ------------------------------------------------------------------

def test_category_products():
    parsed = P.parse_category_products(load("category_cnc_machines_pune_manufacturer.json"))
    assert parsed["category"]["id"] == 3878 and parsed["category"]["slug"] == "cnc-machines"
    assert parsed["category"]["link"] == "https://dir.indiamart.com/pune/cnc-machines.html"
    assert parsed["city"] == {"id": 70630, "slug": "pune", "name": "Pune"}
    assert parsed["business_type"] == "Manufacturer" and parsed["total_count"] > 100
    group = parsed["groups"][0]
    assert group["supplier"]["id"] and group["supplier"]["link"].startswith("https://www.indiamart.com/")
    assert group["supplier"]["location"]["city"] == "Pune"
    assert len(group["products"]) > 1 and group["products"][0]["price"]["currency"] == "INR"
    assert all(spec["value"] == spec["value"].strip() for spec in group["products"][0]["specifications"])
    no_blank_strings(parsed)
    no_link_keys_named_url(parsed)


def test_category_details_and_missing():
    details = P.parse_category_details(load("category_basmati_rice.json"))
    assert details["id"] == 2093 and details["parent_category"]["slug"] == "rice"
    assert details["industry"] == {"id": 16, "slug": "agro-farm"}
    assert len(details["cities"]) == 50 and details["cities"][0]["link"].endswith("/basmati-rice.html")
    assert "Exporter" in details["business_types"] and details["price_ranges"][0]["unit"] == "Kg"
    assert details["related_categories"] and details["standard_products"][0]["id"]
    assert details["product_count"] > 1000
    no_blank_strings(details)
    assert "COOKIES" not in json.dumps(details)
    assert P.category_exists(load("category_cnc_machines.json")) is True
    assert P.category_exists(load("category_missing.json")) is False
    assert P.parse_category_products({})["groups"] == []


def test_category_tree():
    industries = P.parse_industries(raw("dir_home.html"))
    assert len(industries) > 40 and all(row["slug"] and row["name"] for row in industries)
    assert len({row["slug"] for row in industries}) == len(industries)
    state = fetch.extract_blob(raw("industry_agro_farm.html"), "window.__INITIAL_STATE__")
    tree = P.parse_industry(state, "agro-farm")
    assert tree["parent"]["slug"] == "agro-farm" and tree["parent"]["level"] == "industry"
    child = tree["results"][0]
    assert child["level"] == "sub_category" and "/indianexporters/" in child["link"]
    assert child["top_categories"][0]["link"].startswith("https://dir.indiamart.com/impcat/")
    state = fetch.extract_blob(raw("subcategory_ac_refrigeration_equipment.html"), "window.__INITIAL_STATE__")
    sub = P.parse_sub_category(state, "ac-refrigeration-equipment", "products")
    assert sub["parent"]["id"] == 66 and sub["parent"]["industry"]["slug"] == "electrical-equipment-supplies"
    node = sub["results"][0]
    assert node["level"] == "category" and node["product_count"] > 0 and node["child_categories"]
    no_blank_strings(sub)


# ---- products --------------------------------------------------------------------

def _record(name):
    return P.product_data(fetch.next_data(raw(name)))


def test_product_details():
    product = P.parse_product(_record("product_11558361073.html"))
    assert product["id"] == 11558361073 and product["short_name"] == "CNC Milling & Deburring SPM"
    assert product["price"]["amount"] == 8500000 and product["price"]["currency"] == "INR"
    assert product["images"] and product["images"][0]["link"].endswith("1000x1000.jpg")
    assert product["trade"]["delivery_time"] == "16-20 weeks"
    assert product["category"]["id"] == 191249 and product["parent_category"]["slug"] == "cnc-machines"
    supplier = product["supplier"]
    assert supplier["id"] == 949553 and supplier["link"] == "https://www.indiamart.com/company/949553/"
    assert supplier["website"] == "https://www.patsonmachines.com/" and supplier["member_since"] == "2007-09-20"
    assert supplier["profile"]["year_established"] == 2005 and supplier["profile"]["annual_turnover"]
    assert supplier["registration"]["gst_number"] == "27AAECP0052E1ZV"
    assert supplier["registration"]["bankers"] == ["HDFC BANK"]
    assert "employee_count" not in supplier                    # lives in profile only
    no_blank_strings(product)
    no_link_keys_named_url(product)


def test_product_details_second_shape():
    product = P.parse_product(_record("product_2858239336388.html"))
    assert product["price"] == {"amount": 65, "currency": "INR", "unit": "Kg"}
    assert product["supplier"]["is_verified_exporter"] is True
    assert {"code": "AE", "name": "United Arab Emirates"} in product["supplier"]["export_countries"]
    aspects = {row["aspect"]: row for row in product["supplier"]["satisfaction"]}
    assert aspects["Quality"]["satisfied_percent"] == 95 and aspects["Quality"]["rating_count"] == 22
    assert P.product_lookup_keys(_record("product_2858239336388.html"))[0] > 0
    assert P.product_data({"props": {}}) is None and P.parse_product(None)["id"] is None


def test_similar_products():
    parsed = P.parse_similar(load("similar_11558361073.json"))
    assert len(parsed["results"]) == 5 and len({row["id"] for row in parsed["results"]}) == 5
    row = parsed["results"][0]
    assert row["link"].endswith(".html") and "?" not in row["link"]
    assert row["price"]["amount"] == 1600000 and row["supplier"]["slug"] == "proarcwelding"
    assert row["specifications"][0]["name"] == "X-Y Axis Working Area"
    assert parsed["related_categories"][0]["slug"] == "cnc-turning-machine"
    assert P.parse_similar({}) == {"results": [], "related_categories": []}
    no_blank_strings(parsed)


def test_suggestions():
    rows = P.parse_suggestions(load("suggest_products_cnc.json"), "product", 10)
    assert rows[0] == {"text": "cnc machine", "sub_category_id": 587, "search_count": rows[0]["search_count"]}
    assert rows[0]["search_count"] > 1000
    assert P.parse_suggestions(load("suggest_cities_pun.json"), "city", 3) == [
        {"text": "Pune"}, {"text": "Punganuru"}, {"text": "Punahana"}]
    assert P.parse_suggestions(load("suggest_mcat_cnc.json"), "mcat", 50)[0] == {"text": "CNC Adapter"}
    assert P.parse_suggestions(None, "product", 5) == []


# ---- supplier storefront ---------------------------------------------------------

def _page(name):
    html = raw(name)
    return S.soup(html), fetch.extract_blob(html, "window.__COMPANY_DATA__")


def test_supplier_details():
    home, data = _page("supplier_risansi_home.html")
    about, _ = _page("supplier_risansi_about_us.html")
    details = S.parse_details(home, data, "risansi", about)
    assert details["id"] == 20902177 and details["slug"] == "risansi"
    assert details["contact_person"] == {"name": "Vipul Agarwal", "designation": "Managing Director"}
    assert details["phone"] == "+918047547416" and details["year_established"] == 1996
    assert details["is_trustseal_verified"] is True and details["is_gst_verified"] is True
    assert details["location"]["postal_code"] == "208012" and details["location"]["city"] == "Kanpur"
    assert details["profile"]["employee_count"] == "51 to 100 People"
    assert details["profile"]["additional_business"] == ["Wholesale Business", "Factory / Manufacturing"]
    assert details["registration"] == {"gst_number": "09AAACR6923J1Z4", "import_export_code": "0696002931",
                                       "bankers": ["BANK OF INDIA"], "cin": "U29150UP1996PLC020359"}
    assert [s["title"] for s in details["sections"]][:2] == ["ISO Certification", "Quality Assurance"]
    assert details["hsn_codes"][0] == {"code": "73151100", "description": "Roller chain"}
    assert details["catalogue"][0]["slug"] == "screw-pump"
    assert details["pages"]["about"].endswith("/risansi/about-us.html")
    assert details["pages"]["registration"].endswith("/registration-directors-info.html")
    no_blank_strings(details)
    no_link_keys_named_url(details)


def test_supplier_details_without_about_page():
    home, data = _page("supplier_patsonmachines_home.html")
    details = S.parse_details(home, data, "patsonmachines")
    assert details["call_response_rate"] == 91 and details["brochure"].endswith(".pdf")
    assert details["registration"]["gst_number"] == "27AAECP0052E1ZV"
    assert details["pages"]["about"].endswith("/patsonmachines/know-us.html")
    about, _ = _page("supplier_patsonmachines_know_us.html")
    full = S.parse_details(home, data, "patsonmachines", about)
    assert full["profile"]["payment_modes"] == ["Cash", "Cheque", "DD", "Bank Transfer", "Online"]
    assert S.parse_details(S.soup(""), {}, "x")["name"] is None       # never crashes on an empty page


def test_supplier_catalogue():
    doc, _ = _page("supplier_patsonmachines_cnc_spm_machines.html")
    catalogue = S.parse_catalogue(doc, "patsonmachines")
    assert catalogue["title"] == "CNC & SPM Machines" and len(catalogue["results"]) == 16
    first, last = catalogue["results"][0], catalogue["results"][-1]
    assert first["slug"] == "defence-product-machines" and len(first["featured_products"]) == 5
    assert first["featured_products"][0]["link"] == "https://www.indiamart.com/proddetail/21001250291.html"
    assert last == {"slug": "servo-press-machine", "name": "Servo Press Machine",
                    "link": "https://www.indiamart.com/patsonmachines/servo-press-machine.html",
                    "description": None, "product_count": 1, "featured_products": []}


def test_supplier_catalogue_page():
    doc, _ = _page("supplier_risansi_screw_pump.html")
    assert S.is_catalogue_page(doc) is True
    page = S.parse_catalogue_page(doc, "risansi", "screw-pump")
    assert page["category"]["name"] == "Screw Pump" and len(page["results"]) == 8
    product = page["results"][0]
    assert product["id"] == 24360300030 and product["link"].endswith("hygienic-pumps-24360300030.html")
    assert product["price"] == {"amount": 50350, "currency": "INR", "unit": "Piece"}
    assert product["min_order"] == {"quantity": 1, "unit": "Piece"}
    assert len(product["images"]) == 10 and product["videos"] and product["brochure"].endswith(".pdf")
    assert {"name": "Max pressure", "value": "25 bar"} in product["specifications"]
    assert product["additional_information"][0]["name"] == "Packaging Details"
    home, _ = _page("supplier_risansi_home.html")
    assert S.is_catalogue_page(home) is False
    no_blank_strings(page)


def test_supplier_reviews_from_page_and_api():
    doc, _ = _page("supplier_patsonmachines_testimonial.html")
    supplier_id, ssr = S.page_reviews_state(doc)
    summary, reviews = S.parse_reviews(ssr)
    assert supplier_id == 949553 and summary["review_count"] == 15 == len(reviews)
    assert summary["breakdown"] == {"5": 10, "4": 0, "3": 1, "2": 1, "1": 3}
    assert reviews[0]["date"] == "2026-02-10" and reviews[0]["reviewer"]["city"] == "Udaipur"
    data = S.reviews_data(load("reviews_42011038_recent_limit40.json"))
    summary, reviews = S.parse_reviews(data)
    assert summary["review_count"] == 155 and len(reviews) == 20
    assert [r["date"] for r in reviews] == sorted((r["date"] for r in reviews), reverse=True)
    assert any(r["aspects"] and r["aspects"][0]["is_satisfied"] is True for r in reviews)
    assert {a["aspect"] for a in summary["satisfaction"]} == {"Delivery", "Quality", "Response"}
    assert S.reviews_data({"Response": {"Code": "200", "Data": [], "Message": "data not found"}}) == {}
    assert S.reviews_data("nope") is None
    assert S.parse_reviews({})[1] == []
    no_blank_strings(reviews)


def test_supplier_registration_and_trustseal():
    doc, _ = _page("supplier_risansi_registration_directors_info.html")
    assert S.has_registration(doc) is True
    record = S.parse_registration(doc)
    assert record["cin"] == "U29150UP1996PLC020359" and record["incorporation_date"] == "1996-07-23"
    assert record["paid_up_capital"] == {"amount": 22443280, "currency": "INR"}
    assert record["open_charges"] == {"amount": 48744000, "currency": "INR", "charge_count": 7}
    assert record["directors"][1] == {"name": "Vipul Kumar Agarwal", "designation": "Managing Director",
                                      "din": "00059805", "appointment_date": "1998-04-01"}
    cert = S.parse_trustseal(S.soup(raw("supplier_risansi_trustseal.html")))
    assert cert["certificate_id"] == 36450 and cert["issued"] == "2018-04" and cert["valid_until"] == "2027-04"
    assert cert["verified_items"] == ["GST Registration", "Bank Account", "Business Address"]
    assert S.parse_trustseal(S.soup("<html></html>")) is None
    assert S.has_registration(S.soup(raw("supplier_risansi_home.html"))) is False


def test_supplier_media():
    photos = S.parse_photos(S.soup(raw("supplier_risansi_photos.html")))
    assert len(photos) == 72 and photos[0]["product"]["id"] == 24360300030
    assert photos[0]["product"]["price"] == {"amount": 50350, "currency": "INR", "unit": "Piece"}
    videos = S.parse_videos(S.soup(raw("supplier_risansi_videos.html")))
    assert len(videos) == 4 and videos[0]["uploaded_at"] == "2025-12-31" and videos[0]["is_short"] is True
    home_videos = S.parse_videos(S.soup(raw("supplier_patsonmachines_home.html")))
    assert home_videos[0]["title"].endswith("Corporate Video") and home_videos[1]["product_id"] == 2417647533
    assert len({v["id"] for v in home_videos}) == len(home_videos)
