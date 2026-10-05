"""The 18 IndiaMART endpoints. Every path is served with and without the
`/indiamart` prefix, so code generated against the hosted API on RapidAPI
(paths like /products/search) runs unchanged against this server.

Query params are validated by the marshmallow schemas in
indiamart/schemas.py: unknown params and bad values answer 400 with the
reason, a missing product / supplier / category answers 404."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from indiamart import categories, discovery, products, schemas, search, suppliers
from schema_fields import load_query
from scraper_errors import BadRequest, NotFound

PREFIX = "/indiamart"


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    scheme = request.urlparts.scheme or "http"
    return f"{scheme}://{request.get_header('Host', 'localhost')}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, raw):
    """Lift the scraper's `pagination` block into the hosted API's flat
    shape: count / per_page / current_page / total_pages / next / previous."""
    pagination = result.pop("pagination", None) or {}
    page = int(pagination.get("page") or 1)
    total_pages = max(int(pagination.get("total_pages") or 0), 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, raw, page + 1 if page < total_pages else None),
        "previous": _page_link(path, raw, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(path, schema, impl, paginated=False):
    """Validate, run, map errors: bad params -> 400, missing entity -> 404,
    blocks / transport failures -> 500."""
    raw = query_dict()
    data, error = load_query(schema, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"indiamart rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / rate limited
        return json_response({"error": f"indiamart {path.strip('/')} failed: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


# (path, schema, function, paginated) — the order of the API reference
ENDPOINTS = [
    ("/products/search", schemas.SearchSchema, search.search_products, False),
    ("/suppliers/search", schemas.SearchSchema, search.search_suppliers, False),
    ("/products/details", schemas.ProductSchema, products.product_details, False),
    ("/products/similar", schemas.ProductSchema, products.similar_products, False),
    ("/suppliers/details", schemas.SupplierSchema, suppliers.supplier_details, False),
    ("/suppliers/catalogue", schemas.SupplierSchema, suppliers.supplier_catalogue, False),
    ("/suppliers/products", schemas.SupplierProductsSchema, suppliers.supplier_products, False),
    ("/suppliers/reviews", schemas.SupplierReviewsSchema, suppliers.supplier_reviews, True),
    ("/suppliers/registration", schemas.SupplierSchema, suppliers.supplier_registration, False),
    ("/suppliers/trustseal", schemas.SupplierSchema, suppliers.supplier_trustseal, False),
    ("/suppliers/photos", schemas.SupplierSchema, suppliers.supplier_photos, False),
    ("/suppliers/videos", schemas.SupplierSchema, suppliers.supplier_videos, False),
    ("/categories/products", schemas.CategoryProductsSchema, categories.category_products, False),
    ("/categories/details", schemas.CategoryDetailsSchema, categories.category_details, False),
    ("/categories", schemas.CategoriesSchema, categories.categories, False),
    ("/autocomplete", schemas.AutocompleteSchema, discovery.autocomplete, False),
    ("/categories/autocomplete", schemas.AutocompleteSchema, discovery.autocomplete_categories, False),
    ("/cities/autocomplete", schemas.AutocompleteSchema, discovery.autocomplete_cities, False),
]


def mount(path, schema, impl, paginated):
    """Serve one endpoint at /path and /indiamart/path."""
    def handler():
        return call(path, schema, impl, paginated)
    handler.__name__ = "indiamart_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route(PREFIX + path, method="GET")(handler)


for _endpoint in ENDPOINTS:
    mount(*_endpoint)


@route("/", method="GET")
@route("/health", method="GET")
@route(PREFIX + "/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [e[0] for e in ENDPOINTS]})
