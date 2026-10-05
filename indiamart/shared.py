"""Helpers shared by the IndiaMART endpoint modules: turning the site's
supplier-grouped result cards into flat product rows or supplier rows."""


def flatten_products(groups):
    """[{supplier, products}] -> one row per product, in rank order, each
    carrying its supplier and whether it is the supplier's lead listing."""
    rows = []
    for group in groups:
        for index, product in enumerate(group["products"]):
            row = dict(product)
            row["is_lead_listing"] = index == 0
            row["supplier"] = group["supplier"]
            rows.append(row)
    return rows


def _supplier_key(supplier):
    return supplier.get("id") or supplier.get("slug") or supplier.get("name")


def group_suppliers(groups):
    """[{supplier, products}] -> one row per supplier (first appearance
    keeps the rank) with every matching product of theirs."""
    rows, index = [], {}
    for group in groups:
        key = _supplier_key(group["supplier"])
        if key is None:
            continue
        row = index.get(key)
        if row is None:
            row = dict(group["supplier"])
            row["products"] = []
            index[key] = row
            rows.append(row)
        seen = {p.get("id") for p in row["products"]}
        for product in group["products"]:
            if product.get("id") is None or product.get("id") not in seen:
                seen.add(product.get("id"))
                row["products"].append(product)
    for row in rows:
        row["matching_product_count"] = len(row["products"])
    return rows
