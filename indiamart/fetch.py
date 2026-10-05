"""IndiaMART transport: plain curl_cffi with browser-impersonated TLS. No
browser, no cookies, no login (validated 2026-10-05 from direct Indian
egress and through Indian / US residential proxy exits — same payloads).

Surfaces (all public, logged-out):

  * SEARCH   https://dir.indiamart.com/api/search.rp?q=…&page=1&source=dir.search
    The search page's own JSON API: 10 supplier groups per call, each a lead
    product + up to 4 more products of the same supplier, with the supplier's
    phone, full GST number, rating, membership and verification flags, plus
    city / business-type facets and price buckets. Filters that work
    logged-out: city, business type, price range, annual-turnover bucket,
    GST-registration age. PAGE 2+ IS LOGIN-GATED ("Authentication Token is
    missing": the AK param is the `t=` JWT of the im_iss login cookie), so
    search has no page param.

  * CATEGORY https://dir.indiamart.com/mcatAjaxRequest/ajaxData/?flname=<slug>&isqId=0&city=<city>&biz=<id>
    The category ("impcat") page state as bare JSON: 28 cards + their
    more_prod siblings (~100 products), the 50 biggest cities, business-type
    filter, related categories / brands, price buckets. The load-more XHR
    (/mcatAjaxRequest/listing/) answers APP_AUTH_FAILURE logged-out and the
    page ignores ?page=N, so volume comes from city x business-type slices.
    Industry (/industry/<slug>.html) and sub-category
    (/indianexporters|indianservices/<slug>.html) pages carry
    window.__INITIAL_STATE__; the directory home lists the industries.

  * PRODUCT  https://www.indiamart.com/proddetail/<displayid>.html
    Next.js page, data in __NEXT_DATA__ (props.pageProps.serviceRes.Data[0]).
    /api/ajax-services/caps_service/ = similar products + related categories
    (needs the product's category + city ids, both on the page).

  * SUPPLIER https://www.indiamart.com/<alias>/[about-us.html|testimonial.html|<category>.html|…]
    Server-rendered storefront: window.__COMPANY_DATA__ + semantic HTML
    (factsheet tables, product cards, MCA registration page) + island props
    (data-island / data-props JSON). /company/<glid>/ redirects to the alias.
    Reviews page through /ajaxRequestCompanyDesktop/SellerRatingDesktop/ —
    the response is RSA-OAEP + AES-GCM encrypted to a public key the client
    sends in X-Client-Public-Key (ajax-helper chunk); it needs the
    sec-fetch-site: same-origin header, nothing else. `limit` is the END
    index: limit=40 answers reviews 21-40.

  * SUGGEST  https://suggest.imimg.com/suggest/suggest.php?q=&type=product|city|mcat

Rate limit: each host answers HTTP 429 after 15 requests a minute from one
IP (plain "429 Too Many Requests" page; counted per host, clears ~60 s after
the window's first request; suggest.imimg.com is not limited). So egress is
budgeted: up to
config.INDIAMART_DIRECT_PER_MINUTE requests a minute per host leave from
the machine's own IP (fast, free), everything above that — and everything
while the own IP is cooling down on that host after a 429 — goes through
sticky residential proxy exits (config.indiamart_proxy()), one per worker thread,
each retired after config.INDIAMART_REQUESTS_PER_EXIT requests or on its
first 429. With no proxy country configured all traffic is direct.

FALLBACK HOOK: no fingerprint / JS gate exists today. If one appears
(403 or a challenge page on every exit), escalate the way trustpilot/fetch.py
does — a headful patchright load mints the cookies, curl replays them on the
same exit. Not built: dead code while cookie-free HTTP works.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  IndiamartUpstreamError  transport failure / 5xx                 — retryable
  IndiamartBlocked        429 / 403 / HTML where JSON was expected — retryable on a new exit
  IndiamartBadRequest     upstream rejected the params             — never retried
  IndiamartNotFound       404 / missing entity                     — never retried
"""
import base64
import collections
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

DIR = "https://dir.indiamart.com"
WWW = "https://www.indiamart.com"
SUGGEST = "https://suggest.imimg.com"
IMPERSONATE = "chrome"

JSON_TIMEOUT = 30
PAGE_TIMEOUT = 40
FANOUT_WORKERS = 8
DIRECT_WINDOW = 60          # seconds the per-IP budget is counted over
UNLIMITED_HOSTS = {"suggest.imimg.com"}   # no limiter there (40-call burst all 200)

PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "accept-language": "en-IN,en;q=0.9",
    "upgrade-insecure-requests": "1",
}
XHR_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-IN,en;q=0.9",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
}


class IndiamartUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class IndiamartBlocked(IndiamartUpstreamError, Blocked):
    """429 / 403 or an HTML body where JSON was expected — retryable."""


class IndiamartBadRequest(BadRequest):
    """Upstream rejected the params. Never retried."""


class IndiamartNotFound(NotFound):
    """Entity / page does not exist — never retried."""


# ---- egress: own-IP budget + sticky exits ----------------------------------------
_local = threading.local()
_direct_lock = threading.Lock()
_direct_hits = collections.defaultdict(collections.deque)   # host -> request times
_direct_blocked_until = {}                                  # host -> epoch


def _proxy_configured():
    return bool(config.INDIAMART_PROXY_COUNTRY)


def _take_direct(host):
    """True when this request may leave from the machine's own IP: always
    when no proxy is configured, else while that host's per-minute budget
    lasts and the IP is not cooling down there after a 429 (the limiter
    counts per host: a 429 on dir.indiamart.com leaves www untouched)."""
    if not _proxy_configured() or host in UNLIMITED_HOSTS:
        return True
    limit = config.INDIAMART_DIRECT_PER_MINUTE
    if limit <= 0:
        return False
    now = time.time()
    with _direct_lock:
        if now < _direct_blocked_until.get(host, 0):
            return False
        hits = _direct_hits[host]
        while hits and now - hits[0] > DIRECT_WINDOW:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


def _note_direct_block(host):
    with _direct_lock:
        _direct_blocked_until[host] = time.time() + config.INDIAMART_DIRECT_COOLDOWN


def _new_session(proxy=None):
    from curl_cffi import requests as curl_requests
    sess = curl_requests.Session(impersonate=IMPERSONATE)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return sess


def _close(sess):
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _session(direct):
    """The worker thread's curl session for one route (a curl handle must
    not be shared across threads). Exit sessions hold one sticky residential
    IP and are replaced after INDIAMART_REQUESTS_PER_EXIT requests."""
    if direct:
        sess = getattr(_local, "direct", None)
        if sess is None:
            sess = _local.direct = _new_session()
        return sess
    sess = getattr(_local, "exit", None)
    if sess is not None and getattr(_local, "exit_uses", 0) >= config.INDIAMART_REQUESTS_PER_EXIT:
        _drop_session(False)
        sess = None
    if sess is None:
        sess = _local.exit = _new_session(config.indiamart_proxy())
        _local.exit_uses = 0
    _local.exit_uses += 1
    return sess


def _drop_session(direct):
    name = "direct" if direct else "exit"
    sess = getattr(_local, name, None)
    setattr(_local, name, None)
    if not direct:
        _local.exit_uses = 0
    _close(sess)


def dump_debug(name, text):
    """Write a raw body to $INDIAMART_DEBUG_DIR/<name>.txt (utf-8)."""
    dbg = os.environ.get("INDIAMART_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


# ---- requests ------------------------------------------------------------------------

def _clean_params(params):
    return {k: v for k, v in (params or {}).items() if v is not None and v != ""}


def _request(method, url, *, params=None, headers=None, json_body=None, timeout=JSON_TIMEOUT,
             label=None):
    """One upstream call under the egress policy. Returns the response for
    any status the caller should interpret (200 / 400 / 404); 429 / 403 /
    5xx / transport errors are retried on another route or exit."""
    label = label or url
    query = _clean_params(params)
    attempts = max(1, config.INDIAMART_MAX_ATTEMPTS)
    host = urlsplit(url).netloc
    last = None
    for attempt in range(1, attempts + 1):
        direct = _take_direct(host)
        sess = _session(direct)
        try:
            resp = sess.request(method, url, params=query or None, headers=headers,
                                json=json_body, timeout=timeout, allow_redirects=True)
        except Exception as e:
            _drop_session(direct)
            last = IndiamartUpstreamError(f"request failed on {label}: {type(e).__name__}: {e}")
            continue
        status = resp.status_code
        if status == 429 or (status == 403 and "<html" in (resp.text or "")[:400].lower()):
            dump_debug("blocked", resp.text)
            last = IndiamartBlocked(f"HTTP {status} on {label}")
            if direct and _proxy_configured():
                _note_direct_block(host)
            else:
                _drop_session(direct)
                if direct and attempt < attempts:   # no exits to move to: wait the limiter out
                    time.sleep(config.RETRY_BACKOFF * attempt * 3)
            continue
        if status >= 500:
            last = IndiamartUpstreamError(f"HTTP {status} on {label}")
            _drop_session(direct)
            if attempt < attempts:
                time.sleep(config.RETRY_BACKOFF * attempt)
            continue
        return resp
    raise last


def _json_of(resp, label):
    body = resp.text or ""
    if not body.lstrip().startswith(("{", "[")):
        dump_debug("nonjson", body)
        raise IndiamartBlocked(f"{label} returned a non-JSON body")
    try:
        return resp.json()
    except Exception:
        dump_debug("badjson", body)
        raise IndiamartUpstreamError(f"could not parse JSON from {label}")


def get_json(url, params=None, *, referer=None, headers=None, label=None, raw_status=False):
    """GET one JSON endpoint. 404 -> IndiamartNotFound. With raw_status the
    (status, body) pair comes back for 200/400 so the caller can read the
    API's own error message."""
    label = label or url.replace(DIR, "dir:").replace(WWW, "www:").replace(SUGGEST, "suggest:")
    hdrs = dict(XHR_HEADERS)
    if referer:
        hdrs["referer"] = referer
    hdrs.update(headers or {})
    resp = _request("GET", url, params=params, headers=hdrs, label=label)
    if resp.status_code == 404:
        raise IndiamartNotFound(f"{label} not found")
    if resp.status_code == 403:
        raise IndiamartBlocked(f"HTTP 403 on {label}")
    if resp.status_code not in (200, 400):
        raise IndiamartUpstreamError(f"HTTP {resp.status_code} on {label}")
    body = _json_of(resp, label)
    if raw_status:
        return resp.status_code, body
    if resp.status_code == 400:
        raise IndiamartBadRequest(_error_message(body) or f"upstream rejected {label}")
    return body


def post_json(url, body, *, referer=None, label=None):
    """POST a JSON body, parse a JSON answer."""
    label = label or url.replace(WWW, "www:")
    hdrs = dict(XHR_HEADERS)
    hdrs["content-type"] = "application/json"
    if referer:
        hdrs["referer"] = referer
    resp = _request("POST", url, headers=hdrs, json_body=body, label=label)
    if resp.status_code == 404:
        raise IndiamartNotFound(f"{label} not found")
    if resp.status_code != 200:
        raise IndiamartUpstreamError(f"HTTP {resp.status_code} on {label}")
    return _json_of(resp, label)


def get_page(url, params=None, *, referer=None, label=None):
    """GET one HTML page -> (html, final_url). 404 -> IndiamartNotFound."""
    label = label or url.replace(DIR, "dir:").replace(WWW, "www:")
    hdrs = dict(PAGE_HEADERS)
    if referer:
        hdrs["referer"] = referer
    resp = _request("GET", url, params=params, headers=hdrs, timeout=PAGE_TIMEOUT, label=label)
    if resp.status_code in (404, 410):
        raise IndiamartNotFound(f"{label} not found")
    if resp.status_code == 400:
        raise IndiamartNotFound(f"{label} not found")       # "Please type correct URL..."
    if resp.status_code != 200:
        raise IndiamartUpstreamError(f"HTTP {resp.status_code} on {label}")
    html = resp.text or ""
    if not html.strip():
        raise IndiamartUpstreamError(f"empty body for {label}")
    return html, str(resp.url)


def _error_message(body):
    if not isinstance(body, dict):
        return None
    for key in ("error_msg", "msg", "MESSAGE", "message", "error"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ---- encrypted storefront XHRs ---------------------------------------------------------
# /ajaxRequestCompanyDesktop/{SellerRatingDesktop,RecommendedDataDesktop}/ encrypt
# their JSON to the RSA public key sent in X-Client-Public-Key: {key: RSA-OAEP
# (SHA-256) wrapped AES key, iv, data, tag} (AES-GCM), all base64. One key pair
# per process, exactly what the site's ajax-helper chunk does per page load.
_key_lock = threading.Lock()
_keypair = None


def _client_key():
    global _keypair
    if _keypair is None:
        with _key_lock:
            if _keypair is None:
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.asymmetric import rsa
                private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                public = private.public_key().public_bytes(
                    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
                _keypair = (private, base64.b64encode(public).decode())
    return _keypair


def decrypt_envelope(body, private_key):
    """{key, iv, data, tag} -> the JSON it wraps; any other body is returned as is."""
    if not (isinstance(body, dict) and all(isinstance(body.get(k), str) for k in ("key", "iv", "data", "tag"))):
        return body
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        aes_key = private_key.decrypt(
            base64.b64decode(body["key"]),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        plain = AESGCM(aes_key).decrypt(
            base64.b64decode(body["iv"]), base64.b64decode(body["data"]) + base64.b64decode(body["tag"]), None)
        return json.loads(plain)
    except Exception as e:
        raise IndiamartUpstreamError(f"could not decrypt the storefront response: {type(e).__name__}: {e}")


def get_encrypted(path, params, *, referer, label=None):
    """GET one encrypted storefront XHR on www.indiamart.com -> decrypted JSON."""
    private, public_b64 = _client_key()
    body = get_json(WWW + path, params, referer=referer,
                    headers={"X-Client-Public-Key": public_b64}, label=label or f"www:{path}")
    return decrypt_envelope(body, private)


# ---- embedded page data ---------------------------------------------------------------
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def extract_blob(html, marker):
    """The JSON value that follows `marker` in a page (window.__X__ = {...};
    trailing script code is ignored). None when absent / unparsable."""
    start = (html or "").find(marker)
    if start < 0:
        return None
    start += len(marker)
    while start < len(html) and html[start] in " \t\r\n=":
        start += 1
    try:
        return json.JSONDecoder().raw_decode(html, start)[0]
    except ValueError:
        return None


def next_data(html):
    """The page's __NEXT_DATA__ JSON, or None."""
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


# ---- fan-out -----------------------------------------------------------------------------
# A persistent pool: its threads keep their curl sessions (and sticky exits)
# between calls instead of paying a proxy handshake per fan-out.
_pool = None
_pool_lock = threading.Lock()


def _executor():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadPoolExecutor(max_workers=FANOUT_WORKERS, thread_name_prefix="indiamart")
    return _pool


def run_parallel(fns):
    """Run callables concurrently; results in order, the first error raised."""
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    futures = [_executor().submit(fn) for fn in fns]
    return [f.result() for f in futures]


def gather(mapping, optional=()):
    """{key: callable} in parallel -> {key: result}. Keys listed in
    `optional` yield None on NotFound / upstream failure instead of failing
    the whole set."""
    keys = list(mapping)

    def guarded(key):
        fn = mapping[key]
        if key not in optional:
            return fn

        def run():
            try:
                return fn()
            except (IndiamartNotFound, IndiamartBadRequest, IndiamartUpstreamError):
                return None
        return run

    return dict(zip(keys, run_parallel([guarded(k) for k in keys])))


if __name__ == "__main__":
    # Smoke test: python indiamart/fetch.py [query]
    query = sys.argv[1] if len(sys.argv) > 1 else "cnc machine"
    data = get_json(DIR + "/api/search.rp", {"q": query, "page": 1, "source": "dir.search"},
                    referer=f"{DIR}/search.mp")
    print(f"search {query!r}: total={data.get('total_results')} groups={len(data.get('results') or [])}")
    html, final = get_page(WWW + "/proddetail/11558361073.html")
    print(f"product page: bytes={len(html)} final={final} next_data={bool(next_data(html))}")
