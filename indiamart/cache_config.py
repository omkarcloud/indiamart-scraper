"""Cache TTL per /indiamart/* endpoint (cache.py, keyed on the validated
params — marshmallow fills the defaults, so `?page=1` and no `page` share a
row). Tiers follow how fast each surface moves and how scarce upstream
calls are: every host allows ~15 requests a minute per IP, so a cached row
is worth more here than on an unmetered site.
"""
from datetime import timedelta

# Search and category listings re-rank through the day (paid placements
# rotate per request, organic order and prices move daily).
SEARCH_CACHE = timedelta(hours=12)
CATEGORY_PRODUCTS_CACHE = timedelta(hours=12)
# A category's profile (cities, filters, related categories) is taxonomy.
CATEGORY_DETAILS_CACHE = timedelta(days=7)
# The category tree changes a few times a year; the directory home alone
# is a 550 KB page.
CATEGORIES_CACHE = timedelta(days=30)
# Search-box suggestions: stable vocabularies.
AUTOCOMPLETE_CACHE = timedelta(days=30)

# Product page: price, MOQ and seller stats are edited by the seller, daily at most.
PRODUCT_CACHE = timedelta(days=1)
# Recommendations are recomputed by the site's own daily jobs.
SIMILAR_CACHE = timedelta(days=1)

# Company profile (factsheet, statutory numbers, sections) is near-static;
# the rating inside it moves with new reviews.
SUPPLIER_DETAILS_CACHE = timedelta(days=3)
# Catalogue pages are edited by the seller; prices move daily at most.
SUPPLIER_CATALOGUE_CACHE = timedelta(days=3)
SUPPLIER_PRODUCTS_CACHE = timedelta(days=1)
# New ratings land daily on busy suppliers and reorder page 1.
SUPPLIER_REVIEWS_CACHE = timedelta(hours=12)
# MCA record and TrustSEAL certificate change on yearly filings / renewals.
SUPPLIER_REGISTRATION_CACHE = timedelta(days=30)
SUPPLIER_TRUSTSEAL_CACHE = timedelta(days=30)
# Galleries grow when the seller uploads.
SUPPLIER_MEDIA_CACHE = timedelta(days=7)
