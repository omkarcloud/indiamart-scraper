# 🏭 Indiamart Scraper

Indiamart Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Indiamart data for free.

## ✨ What Can I Get?

- 🔍 **Search 130M+ products** — price, specs & minimum order, with the seller's phone & GST number on every row
- 🏭 **Profiles of 8.8M suppliers** — contact person, rating, factsheet, GST, IEC & CIN numbers
- ⭐ **Every buyer review** — star breakdown, satisfaction by aspect, 20 per page
- 🗂️ **The full category tree** — 56 industries down to city-level product listings

## 🎥 Example: A Full Indiamart Product Search

```json
{
  "query": "solar panel",
  "total_count": 4567,
  "count": 37,
  "results": [
    {
      "id": 2850582943433,
      "name": "Polycrystalline PV Solar Panel, 330 W, 24V",
      "link": "https://www.indiamart.com/proddetail/pv-solar-panel-2850582943433.html",
      "image": "https://5.imimg.com/data5/SELLER/Default/2023/6/317457405/BC/BT/OR/8686952/adani-solar-panels-500x500.jpg",
      "price": { "amount": 4000, "currency": "INR", "unit": "Piece" },
      "min_order": { "quantity": 10, "unit": "Piece" },
      "specifications": [
        { "name": "Panel Type", "value": "Polycrystalline" },
        { "name": "Maximum Power Output", "value": "330 W" }
      ],
      "categories": [{ "id": 141927, "name": "Polycrystalline Solar Panels" }],
      "supplier": {
        "slug": "sunlightservices",
        "name": "Sunlight Infra Energy Private Limited",
        "link": "https://www.indiamart.com/sunlightservices/",
        "website": "https://www.sunlightinfra.com/",
        "phone": "+917949357759",
        "rating": 4,
        "review_count": 224,
        "call_response_rate": 80,
        "business_types": ["Manufacturer"],
        "gst_number": "24AALCS6764K1ZR",
        "is_gst_verified": true,
        "is_verified_exporter": true,
        "member_since": "2013-11-02",
        "location": { "city": "Ahmedabad", "state": "Gujarat", "country": "India" }
      }
    }
  ]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Indiamart Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/indiamart-scraper
cd indiamart-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/search?query=solar%20panel"
```

```json
{
  "query": "solar panel",
  "total_count": 4567,
  "count": 37,
  "results": [
    {
      "id": 2850582943433,
      "name": "Polycrystalline PV Solar Panel, 330 W, 24V",
      "link": "https://www.indiamart.com/proddetail/pv-solar-panel-2850582943433.html",
      "price": { "amount": 4000, "currency": "INR", "unit": "Piece" },
      "min_order": { "quantity": 10, "unit": "Piece" },
      "supplier": {
        "name": "Sunlight Infra Energy Private Limited",
        "phone": "+917949357759",
        "gst_number": "24AALCS6764K1ZR",
        "rating": 4,
        "review_count": 224,
        "location": { "city": "Ahmedabad", "state": "Gujarat", "country": "India" }
      }
    }
  ]
}
```

All 18 endpoints are now live at `http://localhost:8000`.

Indiamart allows about 15 requests a minute per IP. Past that the scraper waits and retries by itself; for more volume, set a rotating proxy with `INDIAMART_PROXY=http://user:pass@host:port`.

## 📚 Endpoints

18 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Search Products | `/products/search` | Best-matching products with seller phone, GST number and rating |
| Search Suppliers | `/suppliers/search` | One row per supplier with contact, GST and matching products |
| Product Details | `/products/details` | Specs, images, price, trade terms and the seller's full profile |
| Similar Products | `/products/similar` | Recommended alternatives with suppliers, plus related categories |
| Supplier Details | `/suppliers/details` | Company profile, contact person, factsheet, GST, IEC and CIN |
| Supplier Catalogue | `/suppliers/catalogue` | Every catalogue page with featured products |
| Supplier Products | `/suppliers/products` | Full product cards: price, minimum order, specs, images, brochure |
| Supplier Reviews | `/suppliers/reviews` | Buyer reviews, 20 per page, with star breakdown |
| Supplier Registration & Directors | `/suppliers/registration` | CIN, status, capital, charges and every director |
| Supplier TrustSEAL Certificate | `/suppliers/trustseal` | Certificate ID, validity and what was verified |
| Supplier Photos / Videos | `/suppliers/photos`, `/suppliers/videos` | Product photo gallery and YouTube videos |
| Category Products | `/categories/products` | About 100 products per call, by city and business type |
| Category Details | `/categories/details` | Product count, cities, price ranges, related categories |
| Categories | `/categories` | The category tree, one level per call |
| Autocomplete | `/autocomplete` | Search keyword suggestions with search volume |
| Autocomplete Categories / Cities | `/categories/autocomplete`, `/cities/autocomplete` | Category and city names with ready-to-use slugs |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-indiamart-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-indiamart-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-indiamart-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/search",
    params={"query": "solar panel"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Indiamart Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Indiamart%20Scraper%20API.)

[![Ask Us by Email about Indiamart Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Indiamart%20Scraper%20API&body=I%20need%20help%20using%20the%20Indiamart%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**Alibaba Scraper**](https://github.com/omkarcloud/alibaba-scraper) — Alibaba products, suppliers, price ladders & reviews
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/indiamart-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/indiamart-scraper)
