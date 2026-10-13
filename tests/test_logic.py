"""Logic tests for Almanac (no GUI, no network). All products and prices here are made up."""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("ALMANAC_HOME", tempfile.mkdtemp())  # keep logs out of the repo
import almanac_app as app  # noqa: E402
from sample_data import sample_price_flash  # noqa: E402

# ---- page fragments shaped like each shop's real product page -------------------------------
AMAZON_OK = """<html><span id="productTitle" class="a-size-large product-title-word-break">        Example Monitor A 27-inch       </span>
<div class="sponsored"><span class="a-offscreen">SAR3,025.37</span></div>
<div id="corePrice_feature_div" class="celwidget" data-feature-name="corePrice">
<div class="a-section apex-core-price-identifier"><span class="a-price"><span class="a-offscreen">SAR1,249.00</span><span aria-hidden="true"><span class="a-price-symbol">SAR</span><span class="a-price-whole">1,249<span class="a-price-decimal">.</span></span><span class="a-price-fraction">00</span></span></span></div></div>
<div id="availability" class="a-section"><span class="primary-availability-message"> In Stock </span></div>
</html>"""
AMAZON_NO_OFFER = """<html><span id="productTitle">Example Keyboard B</span>
<div id="availability"><div id="all-offers-display" class="a-section"></div></div>
<span class="a-offscreen">SAR3,025.37</span><span class="a-offscreen">SAR2,776.36</span></html>"""
AMAZON_AR = """<html><span id="productTitle">x</span>
<div id="corePrice_feature_div"><span class="a-offscreen">١٬٢٤٩٫٠٠ ريال</span></div></html>"""
CAPTCHA = """<html><form action="/errors/validateCaptcha">Type the characters you see in this image</form></html>"""

TRENDYOL = """<html><head><title>Example Monitor A | Trendyol</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Trendyol"}</script>
<script type="application/ld+json">{
 "@context": "https://schema.org/", "@type": "Product", "name": "Example Monitor A 27-inch",
 "offers": { "@type": "Offer", "url": "https://www.trendyol.sa/example/monitor-a-p-100000001",
   "priceCurrency": "SAR", "price": "1611.88", "itemCondition": "https://schema.org/NewCondition",
   "availability": "https://schema.org/InStock",
   "shippingDetails": {"@type": "OfferShippingDetails", "shippingRate": {"@type": "MonetaryAmount", "value": "5", "currency": "SAR"}}}
}</script></head><body>"discountedPrice":{"value":1611.88,"text":"1,611.88 SAR"},"sellingPrice":{"value":2686.47}</body></html>"""

INFINIARC = """<html><head><title>Example Desk C | Infiniarc</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"InfiniArc",
 "location":[{"@type":"Store","priceRange":"20 SAR - 50000 SAR"}]}</script>
<script type="application/ld+json">{"@context":"https://schema.org/","@graph":[{"@type":"Product",
 "@id":"https://www.infiniarc.com/shop/example-desk-c-10001#product","name":"Example Desk C",
 "offers":{"@type":"Offer","priceCurrency":"SAR","price":"629.0","availability":"https://schema.org/InStock"}},
 {"@type":"BreadcrumbList","itemListElement":[]}]}</script></head></html>"""

CAZASOUQ = """<html><head><title>Example Keyboard B</title>
<script type="application/ld+json">{
    "@context": "http://schema.org", "@type": "Product", "name": "Example Keyboard B",
    "offers": { "@type": "Offer", "url": "https://www.cazasouq.com/example-keyboard-b",
        "priceCurrency": "BHD", "price": "225.00", "priceValidUntil": "2028-10-08", "availability": "http://schema.org/InStock" } }
</script></head><body><div class="product-price">BHD 225.00</div></body></html>"""

NEWEGG = """<html><head><title>Example Monitor A - Newegg.com</title></head><body>
<script>window.__initialState__ = {"SponsoredItems":{"SponsoredData":[{"ItemCell":{"Item":"00-000-001","UnitCost":279.99,"FinalPrice":279.99}}]},
"ItemDetail":{"Item":"00-000-002","UnitCost":506.99,"FinalPrice":469,"Instock":true,"Description":{"Title":"Example Monitor A 27-inch"}},
"BestSeller":{"LowestPriceFromSeller":{"FinalPrice":353.49}}};</script>
<div class="price-current">$279.99</div></body></html>"""

CLOUDFLARE = """<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1?ray=1"></script><div id="cf-chl-widget"></div></body></html>"""

ALIEXPRESS_RAW = """<html><head><title>Example Monitor A</title></head><body><script>window.runParams = {};
window._d_c_.isCSR = true;</script></body></html>"""

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL:", msg)


def test_parsers():
    r = app.parse_amazon(AMAZON_OK)
    check(r["price"] == 1249.0 and r["currency"] == "SAR", f"amazon core price {r}")
    check(r["title"].startswith("Example Monitor A"), "amazon title")
    check(set(r) == {"blocked", "price", "title", "currency"}, f"amazon: price only, no stock fields {set(r)}")
    check(app.parse_amazon(AMAZON_NO_OFFER)["price"] is None, "no-offer page must not pick a sponsored price")
    check(app.parse_amazon(AMAZON_AR)["price"] == 1249.0, "arabic digits")
    check(app.parse_amazon(CAPTCHA)["blocked"], "captcha detected")
    r = app.parse_generic(TRENDYOL)
    check((r["price"], r["currency"]) == (1611.88, "SAR"), f"trendyol {r}")
    r = app.parse_generic(INFINIARC)
    check((r["price"], r["currency"]) == (629.0, "SAR"), f"infiniarc @graph {r}")
    r = app.parse_generic(CAZASOUQ)
    check((r["price"], r["currency"]) == (225.0, "BHD"), f"cazasouq {r}")
    r = app.parse_newegg(NEWEGG)
    check((r["price"], r["currency"]) == (469.0, "USD"), f"newegg main item, not sponsored {r}")
    check(r["title"].startswith("Example Monitor A"), "newegg title")
    check(app.parse_newegg(CLOUDFLARE)["blocked"], "newegg cloudflare page = blocked")
    check(app.parse_generic(CLOUDFLARE)["blocked"], "generic cloudflare page = blocked")
    r = app.parse_generic(ALIEXPRESS_RAW)
    check(r["price"] is None and not r["blocked"], "aliexpress raw html has no price")


def test_stores_and_urls():
    cases = {
        "https://www.amazon.sa/-/en/dp/B000000001": "amazon",
        "https://www.trendyol.sa/example/x-p-100000001?boutiqueId=61&merchantId=100": "trendyol",
        "https://www.newegg.com/p/N82E00000000001": "newegg",
        "https://www.cazasouq.com/example-keyboard-b?search=keyboard": "cazasouq",
        "https://www.infiniarc.com/shop/example-desk-c-10001": "infiniarc",
        "https://ar.aliexpress.com/item/1000000000000001.html?gatewayAdapt=glo2ara": "aliexpress",
        "https://www.example-shop.com/p/123": "other",
    }
    for url, key in cases.items():
        check(app.store_key(url) == key, f"store_key {url} -> {app.store_key(url)}")
    check(app.store_label("other", "https://www.example-shop.com/x") == "example-shop.com", "other shop label = domain")
    check(app.normalize_product_url("B000000001") == "https://www.amazon.sa/-/en/dp/B000000001", "asin -> url")
    u = app.normalize_product_url("https://www.amazon.sa/Example-Monitor/dp/B000000001/ref=sr_1_3?crid=X")
    check(u == "https://www.amazon.sa/-/en/dp/B000000001", f"amazon canonical {u}")
    u = app.normalize_product_url("www.trendyol.sa/example/x-p-100000001?boutiqueId=61&merchantId=100")
    check(u == "https://www.trendyol.sa/example/x-p-100000001", f"trendyol tracking params dropped {u}")
    u = app.normalize_product_url("https://shop.example.com/item?id=5")
    check(u == "https://shop.example.com/item?id=5", "unknown shop keeps its query")


def test_landed_prices():
    rates = dict(app.DEFAULT_RATES)
    newegg = {"currency": "USD", "shipping": 25.0, "fees_pct": 15.0}
    check(app.landed(newegg, 389.0, rates) == round((389 + 25) * 3.75 * 1.15, 2), "usd + shipping + import vat")
    caz = {"currency": "BHD", "shipping": None, "fees_pct": 0.0}
    check(app.landed(caz, 225.0, rates) in (2244.01, 2244.02), f"bhd peg {app.landed(caz, 225.0, rates)}")
    check(app.landed({"currency": "EUR"}, 100, rates) is None, "unknown currency -> no price")
    check(app.landed({"currency": "SAR"}, None, rates) is None, "no raw price")


def test_recurrence():
    d = datetime(2026, 1, 31, 9, 0)
    m1 = app.add_recurrence(d, "Monthly", 31)
    check(m1 == datetime(2026, 2, 28, 9, 0) and app.add_recurrence(m1, "Monthly", 31) == datetime(2026, 3, 31, 9, 0), "monthly")
    check(app.add_recurrence(datetime(2026, 10, 12, 18, 0), "Bi-weekly") == datetime(2026, 10, 26, 18, 0), "bi-weekly +14 days")
    ref = datetime(2026, 11, 3, 12, 0)
    n = app.next_occurrence_after(datetime(2026, 10, 12, 8, 0), "Bi-weekly", ref)
    check(n == datetime(2026, 11, 9, 8, 0), f"bi-weekly next after a gap {n}")
    check("Bi-weekly" in app.RECURRENCES, "bi-weekly offered in the form")
    t = {"name": "Pay rent", "due": "2026-10-12 18:00", "urgency": "Medium", "recurring": "Bi-weekly"}
    check("Repeats bi-weekly" in app.task_push_text(t, datetime(2026, 10, 12, 17, 0))[1], "push mentions bi-weekly")


def fresh_db(sample=True):
    path = os.path.join(tempfile.mkdtemp(), "almanac_data.json")
    db = app.Database(path)
    if sample:
        db.update(lambda d: d.__setitem__("price_flash", sample_price_flash()))
    return db, path


def test_new_user():
    db, path = fresh_db(sample=False)
    raw = json.load(open(path, encoding="utf-8"))
    s = raw["settings"]
    check(raw["scheduled"] == [] and raw["past"] == [], "starts empty (no mock tasks)")
    check(s["user_name"] == "" and s["ntfy_topic"].startswith("almanac-") and len(s["ntfy_topic"]) == 18,
          f"no name, private topic {s['ntfy_topic']}")
    check(s["seen_version"] == app.APP_VERSION, "no 'updated' message for a brand-new user")
    pf = raw["price_flash"]
    check(pf["items"] == [] and pf["combos"] == [] and pf["schema"] == 2 and pf["rates"]["USD"] == 3.75,
          "empty Price Flash with currency rates")
    other = app.Database(os.path.join(tempfile.mkdtemp(), "almanac_data.json")).data["settings"]["ntfy_topic"]
    check(other != s["ntfy_topic"], "every install gets its own topic")
    check(app.Database(path).data["settings"]["ntfy_topic"] == s["ntfy_topic"], "topic kept on the next start")


def test_best_prices():
    db, _ = fresh_db()
    pf = db.get("price_flash")
    stats = app.part_stats(pf["items"], pf["rates"])
    check(list(stats) == ["Monitor A", "Keyboard B", "Desk C"], f"parts in category order {list(stats)}")
    mon = stats["Monitor A"]
    check(len(mon["listings"]) == 4 and app.store_label(mon["best"]) == "AliExpress" and mon["best_price"] == 900.0,
          f"monitor best {mon['best_price']}")
    check(mon["high"]["price"] == 1035.0, f"newegg 240 USD x3.75 +15% = 1035 is the highest {mon['high']}")
    kb = stats["Keyboard B"]
    check(app.store_label(kb["best"]) == "Cazasouq" and kb["best_price"] == 299.2, f"30 BHD beats 300 SAR {kb['best_price']}")
    combo = pf["combos"][0]
    check(abs(app.compute_combo(combo, pf["items"], pf["rates"])["total"] - 1899.2) < 0.01, "build total")


def test_rename_adopts_old_data():
    """A v1.11 data file next to the exe becomes almanac_data.json; the old file stays as a backup."""
    folder = tempfile.mkdtemp()
    legacy = os.path.join(folder, "scheduler_db.json")
    shutil.copy(os.path.join(ROOT, "tests", "fixtures", "v111_db.json"), legacy)
    target = os.path.join(folder, "almanac_data.json")
    check(app.adopt_legacy_data(target, [os.path.join(folder, "nope.json"), legacy]) == legacy, "old file found")
    db = app.Database(target)
    s = db.data["settings"]
    check(s["user_name"] == "Sam" and s["ntfy_topic"] == "example-topic-111", "name and phone topic kept")
    check(s["seen_version"] == "1.11" and s["check_updates"] is True and s["skip_version"] is None,
          "new settings added, so the 'welcome' message shows once")
    check(len(db.data["scheduled"]) == 2 and len(db.data["past"]) == 1 and db.data["past"][0].get("task"),
          "tasks and undo history kept")
    check(len(db.data["price_flash"]["items"]) == 7, "price data kept")
    check(os.path.exists(legacy), "scheduler_db.json left in place")
    check(app.adopt_legacy_data(target, [legacy]) is None, "never copies over existing almanac data")
    check(app.adopt_legacy_data(os.path.join(tempfile.mkdtemp(), "almanac_data.json"), []) is None,
          "new user: nothing to adopt")


def test_migration_from_v100():
    """A v1.00-layout database (made-up content) moves to the v1.10 layout without losing anything."""
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "scheduler_db.json")
    shutil.copy(os.path.join(ROOT, "tests", "fixtures", "v100_db.json"), path)
    db = app.Database(path)
    data = db.data
    pf = data["price_flash"]
    check(data["scheduled"][0]["name"] == "Gym" and data["settings"]["ntfy_topic"] == "example-topic-100",
          "tasks/settings untouched")
    check(pf["schema"] == 2 and len(pf["items"]) == 3, "schema bumped, nothing added")
    mon = next(i for i in pf["items"] if i["id"] == "mon-a")
    check(mon["raw_price"] == 950.0 and mon["prev_raw"] == 1000.0 and mon["baseline_raw"] == 1000.0, f"prices kept {mon}")
    check(mon["history"] == {"2026-01-10": 1000.0, "2026-01-11": 950.0}, "history kept")
    check(mon["part"] == "Monitor A" and mon["store"] == "amazon" and mon["currency"] == "SAR", "grouped by part")
    check(not ({"in_stock", "availability", "delivery", "short", "price"} & set(mon)), "old fields dropped")
    fan = next(i for i in pf["items"] if i["id"] == "fan-c")
    check(fan["store"] == "other" and fan["raw_price"] == 79.0, f"other shop migrated {fan}")
    combo = pf["combos"][0]
    check(combo["parts"] == ["Monitor A", "Keyboard B"] and "item_ids" not in combo and combo["threshold"] == 1200.0,
          "build now made of parts")
    check(pf["last_summary"] is None and pf["last_best"]["Monitor A"] == 950.0, "old summary dropped, best primed")
    before = json.dumps(pf, sort_keys=True)
    check(json.dumps(app.Database(path).data["price_flash"], sort_keys=True) == before, "migration is idempotent")


def test_price_flow():
    db, _ = fresh_db()
    calls = []
    fake = {
        "tr-mon": {"status": "ok", "price": 880.0, "currency": "SAR", "title": ""},  # new low
        "am-kb": {"status": "ok", "price": 270.0, "currency": "SAR", "title": ""},  # new low, under target
        "am-desk": {"status": "ok", "price": 750.0, "currency": "SAR", "title": ""},  # up
        "ne-mon": {"status": "blocked", "error": "blocked"},
        "cz-kb": {"status": "no_price", "error": "No seller price on the page right now"},
    }

    def fake_check(item, fetcher, retries=1):
        calls.append(item["id"])
        return fake.get(item["id"], {"status": "ok", "price": item["raw_price"], "currency": item["currency"], "title": ""})

    orig_check, orig_sleep = app.check_item, app.time.sleep
    app.check_item = fake_check
    app.time.sleep = lambda s: None
    try:
        report = app.run_price_check(db)
    finally:
        app.check_item, app.time.sleep = orig_check, orig_sleep
    check("ae-mon" not in calls and len(calls) == 6, f"6 automatic listings fetched, manual one skipped {calls}")
    parts = {p["part"]: p for p in report["parts"]}
    check(parts["Monitor A"]["price"] == 880.0 and parts["Monitor A"]["store"] == "Trendyol", "best moved to Trendyol")
    check(parts["Keyboard B"]["price"] == 270.0 and parts["Desk C"]["price"] == 750.0, "keyboard down, desk up")
    total = report["combos"][0]["total"]
    check(abs(total - 1900.0) < 0.01, f"build total {total}")
    title, body = app.build_summary(report)
    print("\n--- daily summary push ---\n" + title + "\n" + body + "\n--------------------------")
    check("▼ Monitor A: 880 · Trendyol" in body, "summary: part, price, shop")
    check("▼ Keyboard B: 270 · Amazon.sa" in body and "▲ Desk C: 750 · Amazon.sa" in body, "summary down/up lines")
    check("1 listing(s) couldn't be read" in body, "blocked listing flagged (no_price isn't a failure)")
    pf = db.get("price_flash")
    kb = next(i for i in pf["items"] if i["id"] == "cz-kb")
    check(kb["status"] == "no_price" and kb["raw_price"] == 30.0, "no-price listing keeps its last price")
    alerts = app.evaluate_alerts(db, report)
    lines = [a["line"] for a in alerts]
    print("--- alerts ---\n" + "\n".join(lines))
    check(any(l.startswith("Monitor A: SAR 880 at Trendyol, lowest seen") for l in lines), "new-low alert")
    check(any(l.startswith("Keyboard B: SAR 270 at Amazon.sa, lowest seen") and l.endswith("under your SAR 280 target")
              for l in lines), "new low + under target in one line")
    check(any(l.startswith("Desk setup") for l in lines), "build alert (1,900 <= 1,950)")
    check(app.evaluate_alerts(db, report) == [], "no repeat alerts on the same prices")
    check(app.alert_message(alerts)[2].startswith("https://www.trendyol.sa"), "alert opens the cheapest listing")


def test_manual_and_skip():
    db, _ = fresh_db()

    def edit(d):
        pf = d["price_flash"]
        next(i for i in pf["items"] if i["id"] == "ae-mon")["skip"] = True
        app.apply_check_result(next(i for i in pf["items"] if i["id"] == "ne-mon"),
                               {"status": "ok", "price": 230.0, "currency": "USD"}, app.now())
    db.update(edit)
    pf = db.get("price_flash")
    best = app.part_stats(pf["items"], pf["rates"])["Monitor A"]
    check(app.store_label(best["best"]) == "Trendyol" and best["best_price"] == 950.0,
          f"skipped AliExpress ignored; Newegg 230 USD = 991.88 loses to 950 ({best['best_price']})")
    check(best["low"]["price"] == 900.0, "lowest seen still remembers the skipped listing's price")


for fn in (test_parsers, test_stores_and_urls, test_landed_prices, test_recurrence, test_new_user, test_best_prices,
           test_rename_adopts_old_data, test_migration_from_v100, test_price_flow, test_manual_and_skip):
    fn()
print("\nRESULT:", "ALL PASSED" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
