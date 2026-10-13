"""Made-up Price Flash data for the tests: three parts across five shops."""
import almanac_app as app

DAY = "2026-01-10"


def listing(item_id, category, part, url, raw, currency="SAR", *, shipping=0.0, fees=0.0, status="ok",
            note="", variant="", alert_below=None):
    return {
        "id": item_id, "category": category, "part": part, "variant": variant, "name": f"Example {part}",
        "url": url, "store": app.store_key(url), "currency": currency, "raw_price": raw, "prev_raw": None,
        "baseline_raw": raw, "shipping": shipping, "fees_pct": fees, "status": status, "error": "",
        "last_checked": f"{DAY} 09:00", "skip": False, "note": note, "alert_below": alert_below,
        "last_alert_price": None, "history": {DAY: raw},
    }


def sample_price_flash() -> dict:
    items = [
        listing("am-mon", "Monitor", "Monitor A", "https://www.amazon.sa/-/en/dp/B000000001", 1000.0),
        listing("tr-mon", "Monitor", "Monitor A", "https://www.trendyol.sa/example/monitor-a-p-100000001", 950.0),
        listing("ne-mon", "Monitor", "Monitor A", "https://www.newegg.com/p/N82E00000000001", 240.0, "USD",
                shipping=None, fees=15.0),
        listing("ae-mon", "Monitor", "Monitor A", "https://www.aliexpress.com/item/1000000000000001.html", 900.0,
                shipping=None, status="manual", note="Check the seller before buying"),
        listing("am-kb", "Peripherals", "Keyboard B", "https://www.amazon.sa/-/en/dp/B000000002", 300.0,
                alert_below=280.0),
        listing("cz-kb", "Peripherals", "Keyboard B", "https://www.cazasouq.com/example-keyboard-b", 30.0, "BHD",
                shipping=None),
        listing("am-desk", "Other", "Desk C", "https://www.amazon.sa/-/en/dp/B000000003", 700.0),
    ]
    rates = dict(app.DEFAULT_RATES)
    combo = {"id": "combo-desk", "name": "Desk setup", "parts": ["Monitor A", "Keyboard B", "Desk C"],
             "threshold": 1950.0, "baseline_total": None, "last_alert_total": None}
    combo["baseline_total"] = app.compute_combo(combo, items, rates)["total"]
    return {
        "enabled": True, "check_time": "09:00", "drop_alert_pct": 5.0, "notify_summary": True,
        "last_auto_run": None, "last_run": None, "last_summary": None,
        "items": items, "combos": [combo], "combo_history": {DAY: {"combo-desk": combo["baseline_total"]}},
        "rates": rates, "schema": app.PRICE_SCHEMA, "part_alerts": {},
        "last_best": {name: st["best_price"] for name, st in app.part_stats(items, rates).items()
                      if st["best_price"] is not None},
    }
