"""Marshmallow request schemas for every /indiamart/* route.

Generic fields (strings, flags, pages, choices, prices, the id-or-link
`RefField`) live in the shared top-level schema_fields.py; this module only
adds the IndiaMART resolvers and the per-route schemas. Every schema's
load() output is the kwargs dict its endpoint function takes.

ONE param per input: `product` (id or /proddetail/ link), `supplier`
(storefront alias, storefront link or numeric supplier id), `category`
(slug, name or dir.indiamart.com link — a city listing link also sets the
city), `parent` (industry / sub-category slug or link), `city` (name or slug).
"""
from marshmallow import ValidationError, post_load, validates_schema

from schema_fields import (
    BaseSchema, ChoiceField, PageField, PageSizeField, Price, QueryField, RefField, load_query,
)
from indiamart import refs
from indiamart.discovery import MAX_SUGGESTIONS
from indiamart.suppliers import REVIEWS_MAX_PAGE


# ---- indiamart id-or-link fields ---------------------------------------------------

class ProductRefField(RefField):
    resolver = staticmethod(refs.resolve_product_ref)


class SupplierRefField(RefField):
    resolver = staticmethod(refs.resolve_supplier_ref)


class SupplierCategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_supplier_category_ref)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category_ref)


class ParentRefField(RefField):
    resolver = staticmethod(refs.resolve_parent_ref)


class CityField(RefField):
    """City name or slug -> the site's slug. Optional."""
    resolver = staticmethod(refs.resolve_city)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


def _business_type():
    return ChoiceField(list(refs.BUSINESS_TYPES))


# ---- search ------------------------------------------------------------------------

class SearchSchema(BaseSchema):
    query = QueryField()
    city = CityField()
    business_type = _business_type()
    min_price = Price()
    max_price = Price()
    annual_turnover = ChoiceField(list(refs.ANNUAL_TURNOVER))
    gst_registration_age = ChoiceField(list(refs.GST_REGISTRATION_AGE))

    @validates_schema
    def _range(self, data, **kwargs):
        if data.get("min_price") is not None and data.get("max_price") is not None \
                and data["min_price"] > data["max_price"]:
            raise ValidationError("min_price must be <= max_price.", "min_price")


class AutocompleteSchema(BaseSchema):
    query = QueryField(max_length=100)
    limit = PageSizeField(default=10, max_size=MAX_SUGGESTIONS)


# ---- categories --------------------------------------------------------------------

class CategoriesSchema(BaseSchema):
    parent = ParentRefField(required=False, load_default=None)


class _CategorySchema(BaseSchema):
    category = CategoryRefField()
    city = CityField()

    @post_load
    def _city_from_link(self, data, **kwargs):
        ref = data["category"]
        # a pasted city listing link sets the city unless `city` says otherwise
        data["city"] = data.get("city") or ref.get("city")
        data["category"] = ref["slug"]
        return data


class CategoryDetailsSchema(_CategorySchema):
    pass


class CategoryProductsSchema(_CategorySchema):
    business_type = _business_type()


# ---- products ----------------------------------------------------------------------

class ProductSchema(BaseSchema):
    product = ProductRefField()


# ---- suppliers ---------------------------------------------------------------------

class SupplierSchema(BaseSchema):
    supplier = SupplierRefField()


class SupplierProductsSchema(BaseSchema):
    supplier = SupplierRefField()
    category = SupplierCategoryRefField()


class SupplierReviewsSchema(BaseSchema):
    supplier = SupplierRefField()
    page = PageField(max_page=REVIEWS_MAX_PAGE)
    sort_by = ChoiceField(list(refs.REVIEW_SORTS), load_default="top")


__all__ = [name for name in globals() if name.endswith("Schema")] + ["load_query"]
