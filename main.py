"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. The functions live in indiamart/search.py, products.py,
categories.py, suppliers.py and discovery.py.
"""
import json
import os

from indiamart.products import product_details
from indiamart.search import search_products
from indiamart.suppliers import supplier_details

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # products with the supplier's phone, GST number and rating on every row
    save("search_solar_panel.json", search_products("solar panel", city="mumbai"))

    # a product id or any indiamart.com/proddetail/ link
    save("product_2850582943433.json", product_details("2850582943433"))

    # a storefront alias, storefront link or numeric supplier id
    save("supplier_sunlightservices.json", supplier_details("sunlightservices"))
