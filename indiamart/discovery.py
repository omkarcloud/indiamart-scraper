"""Search-box suggestions (suggest.imimg.com — open JSON, no rate limit):
product keywords, city names and category names.

    python indiamart/discovery.py cnc
    python indiamart/discovery.py --cities pun
    python indiamart/discovery.py --categories cnc
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indiamart import parsers  # noqa: E402
from indiamart.fetch import SUGGEST, WWW, get_json  # noqa: E402
from indiamart.refs import category_link, resolve_city, slugify  # noqa: E402

SUGGEST_API = SUGGEST + "/suggest/suggest.php"
MAX_SUGGESTIONS = 20


def _suggest(query, kind, limit):
    if not query or not str(query).strip():
        raise ValueError("query is required")
    limit = int(limit or 10)
    if not 1 <= limit <= MAX_SUGGESTIONS:
        raise ValueError(f"limit must be 1-{MAX_SUGGESTIONS}")
    body = get_json(SUGGEST_API, {"q": str(query).strip(), "tag": "suggestions", "limit": limit, "type": kind},
                    referer=WWW + "/", label=f"suggest {kind}")
    return parsers.parse_suggestions(body, kind, limit)


def autocomplete(query, limit=10):
    """Search-keyword suggestions with how often each is searched."""
    rows = _suggest(query, "product", limit)
    return {"query": query, "count": len(rows), "results": rows}


def autocomplete_cities(query, limit=10):
    """City names matching a prefix; `slug` is what the `city` params take."""
    rows = []
    for row in _suggest(query, "city", limit):
        rows.append({"name": row["text"], "slug": resolve_city(row["text"])})
    return {"query": query, "count": len(rows), "results": rows}


def autocomplete_categories(query, limit=10):
    """Category names matching a prefix; `slug` is what `category` takes."""
    rows = []
    for row in _suggest(query, "mcat", limit):
        slug = slugify(row["text"])
        rows.append({"name": row["text"], "slug": slug, "link": category_link(slug)})
    return {"query": query, "count": len(rows), "results": rows}


if __name__ == "__main__":
    args = sys.argv[1:] or ["cnc"]
    fn = autocomplete
    if args[0] == "--cities":
        fn, args = autocomplete_cities, args[1:]
    elif args[0] == "--categories":
        fn, args = autocomplete_categories, args[1:]
    print(json.dumps(fn(args[0]), ensure_ascii=False, indent=1))
