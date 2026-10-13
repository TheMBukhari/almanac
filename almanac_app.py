#!/usr/bin/env python3
"""
Almanac
=======
A desktop scheduler that pushes reminders to your phone (through ntfy) and
compares PC-part prices across shops ("Price Flash").

    python almanac_app.py               start normally
    python almanac_app.py --minimized   start hidden in the system tray (used by "Start with Windows")

Everything is stored in almanac_data.json next to this file (or next to Almanac.exe).
In the .exe build this file is loaded by launcher.py, which is what lets it update itself.
"""
from __future__ import annotations

import calendar
import copy
import hashlib
import html as htmllib
import json
import logging
import os
import queue
import random
import re
import secrets
import shutil
import socket
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime, timedelta
from urllib.parse import urlparse

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
import requests

import matplotlib

matplotlib.use("TkAgg")
import matplotlib.dates  # noqa: E402
import matplotlib.ticker  # noqa: E402
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

try:  # Pillow ships with matplotlib, but stay defensive
    from PIL import Image, ImageDraw, ImageTk
except Exception:  # pragma: no cover
    Image = ImageDraw = ImageTk = None

try:  # system tray (optional)
    import pystray
except Exception:  # pragma: no cover
    pystray = None

try:  # browser-grade TLS fingerprint: far fewer Amazon blocks than plain requests
    from curl_cffi import requests as cffi_requests
except Exception:  # pragma: no cover
    cffi_requests = None


APP_NAME = "Almanac"
APP_VERSION = "1.12"
APP_CODENAME = "Open Doors"
# Oldest launcher (Almanac.exe) that can run this file. Raise it when the code needs a library
# the old .exe doesn't contain; the updater then asks for the full download instead.
MIN_LAUNCHER = 1
# Where updates come from (GitHub "owner/repo"). The release build stamps this automatically.
UPDATE_REPO = "TheMBukhari/almanac"

# Newest first. Every update adds an entry here; the Patch Notes page and CHANGELOG.md show it.
PATCH_NOTES = [
    {
        "version": "1.12",
        "name": "Open Doors",
        "date": "2026-10-13",
        "summary": "The app is now called Almanac. It can update itself, and new users start with a clean slate.",
        "sections": [
            ("New", [
                "Updates install themselves. Almanac checks once a day (or when you press Check for updates on "
                "this page), shows what's new, and installs only when you say so. Most updates are one small "
                "file instead of a whole new download.",
                "Your data is backed up before every update. If a new version doesn't start, Almanac goes back to "
                "the previous one by itself, and Settings has a button to go back by hand.",
                "A clock under the app name.",
                "New versions are built on GitHub and published as a ready-made Almanac.exe, so there's no build "
                "script to run.",
            ]),
            ("Changed", [
                "New name: Almanac. The data file is now almanac_data.json. On first start it's copied from "
                "scheduler_db.json, which stays where it is as a backup. Turn Start with Windows on again in "
                "Settings.",
                "New users start empty: no name, a private phone topic made just for them, and an empty Price "
                "Flash page. Your own data is unchanged.",
                "Price Flash categories can be typed freely, with more ready-made ones (PSU, Case, Cooling, "
                "Monitor, Peripherals).",
            ]),
            ("Known limits", [
                "This version is installed by hand. Automatic updates start with the next one.",
                "Prices are still converted to SAR.",
            ]),
        ],
    },
    {
        "version": "1.11",
        "name": "Rewind",
        "date": "2026-10-13",
        "summary": "Mistakes on the Scheduled page can now be taken back.",
        "sections": [
            ("New", [
                "Undo: after Done, Missed or Remove, the message in the corner has an Undo button for a few seconds.",
                "Undo in Past Activities: the latest entry of each task can be undone at any time. Undoing a "
                "repeating task steps it back one occurrence per click, so several accidental Done clicks can "
                "all be reversed. This also works on entries made before this update.",
                "Repeating tasks show their next two dates on the card.",
            ]),
            ("Changed", [
                "The Scheduled page is grouped into Overdue, Today, Tomorrow, This week, Next week and Later.",
                "Marking a repeating task done or missed before its day now asks first, since that skips ahead "
                "to the following occurrence.",
            ]),
        ],
    },
    {
        "version": "1.10",
        "name": "Wide Net",
        "date": "2026-10-12",
        "summary": "Price Flash now compares shops instead of watching one, and tracks price only.",
        "sections": [
            ("New", [
                "Five more shops alongside Amazon.sa: Trendyol, Newegg, Cazasouq, Infiniarc and AliExpress.",
                "Best prices table: every part shows its cheapest price right now and the shop selling it, "
                "plus the lowest and highest price seen.",
                "Prices in USD, BHD and other Gulf currencies are converted to SAR, with the shipping and import "
                "fees you set on each listing added in.",
                "New-low alert: your phone gets a separate alert when a part hits its lowest price so far.",
                "Bi-weekly repeat for scheduled tasks.",
                "This Patch Notes page.",
            ]),
            ("Changed", [
                "Price Flash tracks price only. Stock, arrival and other details go in a note on each listing, "
                "and a listing can be skipped by hand, for example when it's out of stock.",
                "Builds are made of parts, and each part is priced at its cheapest shop.",
                "The daily phone message lists the best price and shop for each part.",
                "Your parts, prices, history and builds carried over from v1.00.",
            ]),
            ("Known limits", [
                "AliExpress only shows prices after its page loads in a browser, so its prices are typed in by hand.",
                "Newegg and Cazasouq only show shipping to Saudi Arabia at checkout. Add it to the listing once "
                "you've seen it.",
            ]),
        ],
    },
    {
        "version": "1.00",
        "name": "First Light",
        "date": "2026-10-11",
        "summary": "The first release.",
        "sections": [
            ("Highlights", [
                "Scheduler with one-time, daily, weekly and monthly tasks, urgency levels and phone reminders "
                "through ntfy.",
                "Past Activities history and a Dashboard with completion stats.",
                "Price Flash: a daily Amazon.sa price check for PC parts, with build totals, "
                "a daily phone summary and separate price-drop alerts.",
                "Runs in the system tray, can start with Windows, and has light and dark themes.",
            ]),
        ],
    },
]
IS_WINDOWS = sys.platform.startswith("win")
INSTANCE_PORT = 48217
DT_FMT = "%Y-%m-%d %H:%M"
TS_FMT = "%Y-%m-%d %H:%M:%S"

URGENCIES = ["Low", "Medium", "High"]
RECURRENCES = ["One-Time", "Daily", "Weekly", "Bi-weekly", "Monthly"]
REMINDERS = {"At time": 0, "10 min before": 10, "30 min before": 30, "1 hour before": 60}
CATEGORIES = ["CPU", "Motherboard", "RAM", "GPU", "Storage", "PSU", "Case", "Cooling", "Monitor",
              "Peripherals", "Other"]


# ════════════════════════════════════════════════════════════════════════════
#  Paths
# ════════════════════════════════════════════════════════════════════════════
def _is_writable(folder: str) -> bool:
    try:
        probe = os.path.join(folder, ".almanac_write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _appdata(name: str) -> str:
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), name)


def install_dir() -> str:
    """Folder of Almanac.exe (or of this file when run from source). ALMANAC_HOME overrides it (tests)."""
    if os.environ.get("ALMANAC_HOME"):
        return os.environ["ALMANAC_HOME"]
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def app_dir() -> str:
    base = install_dir()
    if _is_writable(base):
        return base
    fallback = _appdata("Almanac")
    os.makedirs(fallback, exist_ok=True)
    return fallback


DATA_DIR = app_dir()
DB_NAME = "almanac_data.json"
DB_PATH = os.path.join(DATA_DIR, DB_NAME)
LOG_PATH = os.path.join(DATA_DIR, "almanac.log")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
# Where v1.00 to v1.11 kept their data.
LEGACY_DB_PATHS = (os.path.join(DATA_DIR, "scheduler_db.json"),
                   os.path.join(install_dir(), "scheduler_db.json"))

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("almanac")


def adopt_legacy_data(db_path: str = None, legacy_paths=None) -> str | None:
    """First start after the rename: copy scheduler_db.json to almanac_data.json.
    The old file is left where it is, as a backup. Returns the file that was copied, if any."""
    db_path = db_path or DB_PATH
    if os.path.exists(db_path):
        return None
    for old in legacy_paths if legacy_paths is not None else LEGACY_DB_PATHS:
        if os.path.isfile(old):
            try:
                shutil.copy2(old, db_path)
                log.info("Copied %s to %s", old, db_path)
                return old
            except OSError:
                log.error("Couldn't copy the old data file:\n%s", traceback.format_exc())
    return None


# ════════════════════════════════════════════════════════════════════════════
#  Palette — "desert night"
# ════════════════════════════════════════════════════════════════════════════
NAVY, SAND, TERRACOTTA = "#050517", "#EFC88B", "#CF5C36"


class P:
    """Colour tokens as (light, dark) pairs; CustomTkinter switches them automatically."""

    BG = ("#FBF3E3", NAVY)
    SIDEBAR = (SAND, "#0A0A22")
    SIDEBAR_HOVER = ("#E6B66F", "#17173A")
    CARD = ("#FFFAF1", "#0F0F2B")
    CARD_ALT = ("#F5E8CF", "#16163A")
    BORDER = ("#E9D5B0", "#1F1F47")
    INPUT = ("#FFFFFF", "#0B0B24")
    TEXT = (NAVY, SAND)
    MUTED = ("#76664D", "#948A78")
    ACCENT = TERRACOTTA
    ACCENT_HOVER = "#B44B28"
    ON_ACCENT = "#FFF5E8"
    ACCENT_SOFT = ("#F8DCD0", "#3A1A10")
    SUCCESS = ("#2F8A57", "#6CC18F")
    SUCCESS_HOVER = ("#257048", "#57A877")
    SUCCESS_SOFT = ("#DDF0E3", "#11301F")
    WARN = ("#A86A12", "#E8B04B")
    WARN_SOFT = ("#F7E6C4", "#33280F")
    INFO = ("#4C5F8A", "#93A8D6")
    INFO_SOFT = ("#E2E7F2", "#171D38")
    ROSE = ("#B03A55", "#E58AA0")
    ROSE_SOFT = ("#F6DDE3", "#351620")


URGENCY_STYLE = {
    "High": (P.ACCENT, P.ON_ACCENT),
    "Medium": (P.WARN_SOFT, P.WARN),
    "Low": (P.INFO_SOFT, P.INFO),
}
URGENCY_STRIP = {"High": P.ACCENT, "Medium": P.WARN, "Low": P.INFO}


def is_dark() -> bool:
    return ctk.get_appearance_mode().lower() == "dark"


def pick(color):
    if isinstance(color, (tuple, list)):
        return color[1] if is_dark() else color[0]
    return color


def font_family() -> str:
    if IS_WINDOWS:
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "DejaVu Sans"


class Fonts:
    def __init__(self):
        fam = font_family()
        self.h1 = ctk.CTkFont(fam, 28, "bold")
        self.h2 = ctk.CTkFont(fam, 20, "bold")
        self.h3 = ctk.CTkFont(fam, 16, "bold")
        self.body = ctk.CTkFont(fam, 14)
        self.body_bold = ctk.CTkFont(fam, 14, "bold")
        self.field = ctk.CTkFont(fam, 13, "bold")
        self.small = ctk.CTkFont(fam, 12)
        self.small_bold = ctk.CTkFont(fam, 12, "bold")
        self.tiny = ctk.CTkFont(fam, 11)
        self.number = ctk.CTkFont(fam, 30, "bold")
        self.number_md = ctk.CTkFont(fam, 22, "bold")
        self.icon = ctk.CTkFont(fam, 40)
        self.clock = ctk.CTkFont(fam, 13, "bold")


FONTS: Fonts | None = None


# ════════════════════════════════════════════════════════════════════════════
#  Small helpers
# ════════════════════════════════════════════════════════════════════════════
def now() -> datetime:
    return datetime.now()


def parse_dt(text: str) -> datetime:
    return datetime.strptime(text, DT_FMT)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def fmt_money(value) -> str:
    if value is None:
        return "—"
    if abs(value - round(value)) < 0.005:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def fmt_delta(delta) -> str:
    if delta is None:
        return "—"
    if abs(delta) < 0.005:
        return "="
    return f"{'+' if delta > 0 else '−'}{fmt_money(abs(delta))}"


def delta_color(delta):
    if delta is None or abs(delta) < 0.005:
        return P.MUTED
    return P.ACCENT if delta > 0 else P.SUCCESS  # price up is bad, down is good


def humanize_until(due: datetime, ref: datetime) -> str:
    secs = (due - ref).total_seconds()
    past = secs < 0
    secs = abs(secs)
    if secs < 60:
        txt = "now" if not past else "just now"
        return txt
    mins = int(secs // 60)
    if mins < 60:
        span = f"{mins} min"
    elif mins < 60 * 24:
        hours = mins // 60
        span = f"{hours} h" + (f" {mins % 60} min" if hours < 4 and mins % 60 else "")
    else:
        days = mins // (60 * 24)
        span = f"{days} day" + ("s" if days != 1 else "")
    return f"overdue by {span}" if past else f"in {span}"


def add_recurrence(dt: datetime, rule: str, anchor_day: int | None = None) -> datetime:
    if rule == "Daily":
        return dt + timedelta(days=1)
    if rule == "Weekly":
        return dt + timedelta(weeks=1)
    if rule == "Bi-weekly":  # every two weeks, same weekday
        return dt + timedelta(weeks=2)
    if rule == "Monthly":
        year = dt.year + (1 if dt.month == 12 else 0)
        month = 1 if dt.month == 12 else dt.month + 1
        day = min(anchor_day or dt.day, calendar.monthrange(year, month)[1])
        return dt.replace(year=year, month=month, day=day)
    raise ValueError(f"Not a recurring rule: {rule}")


def next_occurrence_after(dt: datetime, rule: str, ref: datetime, anchor_day=None) -> datetime:
    nxt = add_recurrence(dt, rule, anchor_day)
    guard = 0
    while nxt <= ref and guard < 5000:
        nxt = add_recurrence(nxt, rule, anchor_day)
        guard += 1
    return nxt


# ════════════════════════════════════════════════════════════════════════════
#  Price Flash: stores, currencies and seed data
# ════════════════════════════════════════════════════════════════════════════
# "mode": auto = the app reads the price itself; manual = the shop only shows prices after its
# scripts run (AliExpress), so the price is typed in by hand.
# "shipping": None means "not known yet" (the user fills it in); 0 means delivery is free.
STORES = {
    "amazon": {"label": "Amazon.sa", "hosts": ("amazon.",), "currency": "SAR", "fees": 0.0, "shipping": 0.0, "mode": "auto"},
    "trendyol": {"label": "Trendyol", "hosts": ("trendyol.",), "currency": "SAR", "fees": 0.0, "shipping": 0.0, "mode": "auto"},
    "infiniarc": {"label": "Infiniarc", "hosts": ("infiniarc.",), "currency": "SAR", "fees": 0.0, "shipping": 0.0, "mode": "auto"},
    "cazasouq": {"label": "Cazasouq", "hosts": ("cazasouq.",), "currency": "BHD", "fees": 0.0, "shipping": None, "mode": "auto"},
    "newegg": {"label": "Newegg", "hosts": ("newegg.",), "currency": "USD", "fees": 15.0, "shipping": None, "mode": "auto"},
    "aliexpress": {"label": "AliExpress", "hosts": ("aliexpress.",), "currency": "SAR", "fees": 0.0, "shipping": None, "mode": "manual"},
}
OTHER_STORE = {"label": "", "hosts": (), "currency": "SAR", "fees": 0.0, "shipping": None, "mode": "auto"}

# SAR for one unit of each currency. USD, BHD, AED, QAR and OMR are pegged, so these stay right;
# KWD floats a little. All of them can be edited on the Price Flash page.
DEFAULT_RATES = {"SAR": 1.0, "USD": 3.75, "BHD": 9.9734, "AED": 1.0211, "QAR": 1.0302, "OMR": 9.7403, "KWD": 12.2}

PRICE_SCHEMA = 2


def store_key(url: str) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    for key, info in STORES.items():
        if any(h in host for h in info["hosts"]):
            return key
    return "other"


def store_info(key: str) -> dict:
    return STORES.get(key, OTHER_STORE)


def store_label(item_or_key, url: str = "") -> str:
    if isinstance(item_or_key, dict):
        key, url = item_or_key.get("store") or store_key(item_or_key.get("url", "")), item_or_key.get("url", "")
    else:
        key = item_or_key
    if key in STORES:
        return STORES[key]["label"]
    host = (urlparse(url or "").netloc or "").lower()
    return host[4:] if host.startswith("www.") else (host or "Other shop")


def migrate_price_flash(pf: dict) -> bool:
    """v1.00 -> v1.10 layout: listings grouped into parts, prices kept in the shop's own currency,
    stock/delivery tracking dropped, builds made of parts."""
    if pf.get("schema", 1) >= PRICE_SCHEMA:
        return False
    for item in pf.get("items", []):
        part, variant = item.get("short") or item.get("name") or "Part", ""
        key = store_key(item.get("url", ""))
        info = store_info(key)
        item.setdefault("part", part)
        item.setdefault("variant", variant)
        item["store"] = key
        item.setdefault("currency", info["currency"] if key in STORES else "SAR")
        item["raw_price"] = item.pop("price", None)
        item["prev_raw"] = item.pop("prev_price", None)
        item["baseline_raw"] = item.pop("baseline", None)
        item.setdefault("shipping", info["shipping"])
        item.setdefault("fees_pct", info["fees"])
        item.setdefault("skip", False)
        item.setdefault("note", "")
        item.setdefault("history", {})
        for old in ("in_stock", "availability", "delivery", "short"):
            item.pop(old, None)
        if item.get("status") not in ("ok", "blocked", "error", "no_price", "manual"):
            item["status"] = "ok"
    by_id = {i["id"]: i for i in pf.get("items", [])}
    for combo in pf.get("combos", []):
        if "parts" not in combo:
            parts = []
            for item_id in combo.pop("item_ids", []):
                part = by_id.get(item_id, {}).get("part")
                if part and part not in parts:
                    parts.append(part)
            combo["parts"] = parts
    rates = dict(DEFAULT_RATES)
    rates.update(pf.get("rates") or {})
    pf["rates"] = rates
    pf["last_summary"] = None  # the v1.00 report layout can't be re-sent
    pf["last_best"] = {name: st["best_price"] for name, st in part_stats(pf["items"], rates).items()
                       if st["best_price"] is not None}
    pf.setdefault("part_alerts", {})
    pf["schema"] = PRICE_SCHEMA
    return True


def default_price_flash() -> dict:
    """What a new user starts with: nothing tracked yet."""
    return {
        "enabled": True, "check_time": "09:00", "drop_alert_pct": 5.0, "notify_summary": True,
        "last_auto_run": None, "last_run": None, "last_summary": None,
        "items": [], "combos": [], "combo_history": {},
        "rates": dict(DEFAULT_RATES), "last_best": {}, "part_alerts": {}, "schema": PRICE_SCHEMA,
    }


def new_topic() -> str:
    return f"almanac-{secrets.token_hex(5)}"


DEFAULT_SETTINGS = {
    "user_name": "",
    "theme": "dark",
    "ntfy_server": "https://ntfy.sh",
    "ntfy_topic": "",
    "notifications_enabled": True,
    "close_to_tray": True,
    "tray_hint_shown": False,
    "seen_version": None,
    "check_updates": True,
    "skip_version": None,
    "last_update_check": None,
}


# ════════════════════════════════════════════════════════════════════════════
#  Local JSON database
# ════════════════════════════════════════════════════════════════════════════
class Database:
    """Thread-safe JSON store. Writes are atomic (temp file + replace)."""

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        self.data = self._load()

    def _load(self) -> dict:
        data = None
        fresh = not os.path.exists(self.path)
        if not fresh:
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                backup = f"{self.path}.corrupt-{int(time.time())}"
                try:
                    os.replace(self.path, backup)
                except OSError:
                    pass
                log.error("Database was unreadable; moved to %s", backup)
                data = None
        if not isinstance(data, dict):
            data = {"scheduled": [], "past": []}
        data.setdefault("scheduled", [])
        data.setdefault("past", [])
        if not isinstance(data.get("settings"), dict):
            data["settings"] = {"ntfy_topic": new_topic(), "seen_version": APP_VERSION}  # brand-new user
        settings = dict(DEFAULT_SETTINGS)
        settings.update(data["settings"])
        data["settings"] = settings
        if not isinstance(data.get("price_flash"), dict):
            data["price_flash"] = default_price_flash()
        else:
            pf = data["price_flash"]
            for key, value in default_price_flash().items():
                if key not in ("items", "combos", "combo_history", "schema", "rates", "last_best", "part_alerts"):
                    pf.setdefault(key, value)
            pf.setdefault("items", [])
            pf.setdefault("combos", [])
            pf.setdefault("combo_history", {})
            if migrate_price_flash(pf):
                log.info("Price Flash data upgraded to schema %s", PRICE_SCHEMA)
        self.data = data
        self.save()
        return data

    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)

    def get(self, key):
        with self.lock:
            return copy.deepcopy(self.data[key])

    def update(self, fn):
        with self.lock:
            result = fn(self.data)
            self.save()
            return result


# ════════════════════════════════════════════════════════════════════════════
#  Task logic
# ════════════════════════════════════════════════════════════════════════════
def make_task(name, due: datetime, urgency, recurring, remind_minutes) -> dict:
    return {
        "id": new_id("task"),
        "name": name.strip(),
        "due": due.strftime(DT_FMT),
        "urgency": urgency,
        "recurring": recurring,
        "remind": int(remind_minutes),
        "anchor_day": due.day,
        "notified": False,
        "created": now().strftime(TS_FMT),
    }


def _past_record(task: dict, status: str, auto=False, when: datetime | None = None) -> dict:
    return {
        "id": new_id("past"),
        "task_id": task["id"],
        "name": task["name"],
        "due": task["due"],
        "urgency": task.get("urgency", "Medium"),
        "recurring": task.get("recurring", "One-Time"),
        "status": status,
        "auto": auto,
        "resolved_at": (when or now()).strftime(TS_FMT),
        "task": copy.deepcopy(task),  # exactly how the task looked before; lets Undo put it back
    }


def resolve_task(db: Database, task_id: str, status: str):
    """Done / Missed: log to history; recurring tasks roll forward instead of disappearing.
    Returns the history entry's id (for Undo), or None if the task wasn't found."""
    ref = now()

    def apply(data):
        for index, task in enumerate(data["scheduled"]):
            if task["id"] != task_id:
                continue
            record = _past_record(task, status, when=ref)
            data["past"].append(record)
            if task.get("recurring", "One-Time") == "One-Time":
                data["scheduled"].pop(index)
            else:
                nxt = next_occurrence_after(parse_dt(task["due"]), task["recurring"], ref, task.get("anchor_day"))
                task["due"] = nxt.strftime(DT_FMT)
                task["notified"] = False
                task.pop("retry_at", None)
            return record["id"]
        return None

    return db.update(apply)


def undoable_past_ids(past: list) -> set:
    """Only the newest history entry of each task can be undone, so undoing always steps a
    repeating task back one occurrence at a time and history never contradicts the schedule."""
    newest = {}
    for rec in past:
        key = rec.get("task_id") or rec["id"]
        if key not in newest or rec["resolved_at"] >= newest[key]["resolved_at"]:
            newest[key] = rec
    return {rec["id"] for rec in newest.values()}


def undo_resolution(db: Database, past_id: str):
    """Reverse a Done / Missed: drop the history entry and put the task back as it was.
    Returns the restored task, or None if that entry can't be undone."""
    ref = now()

    def apply(data):
        rec = next((r for r in data["past"] if r["id"] == past_id), None)
        if rec is None or past_id not in undoable_past_ids(data["past"]):
            return None
        data["past"] = [r for r in data["past"] if r["id"] != past_id]
        snapshot = rec.get("task")
        current = next((t for t in data["scheduled"] if t["id"] == rec.get("task_id")), None)
        if snapshot:  # v1.11+ entries: exact restore
            restored = copy.deepcopy(snapshot)
        else:  # entries from v1.00/v1.10 carry less detail: rebuild from what's there
            restored = copy.deepcopy(current) if current else {
                "id": rec.get("task_id") or new_id("task"), "name": rec["name"], "urgency": rec.get("urgency", "Medium"),
                "recurring": rec.get("recurring", "One-Time"), "remind": 0,
                "anchor_day": parse_dt(rec["due"]).day, "created": rec["resolved_at"],
            }
            restored["due"] = rec["due"]
            restored["notified"] = parse_dt(rec["due"]) <= ref  # don't fire a late reminder for an old date
            restored.pop("retry_at", None)
        if current is not None:
            if parse_dt(restored["due"]) > parse_dt(current["due"]):
                restored["due"], restored["notified"] = current["due"], current.get("notified", False)
            data["scheduled"] = [restored if t["id"] == current["id"] else t for t in data["scheduled"]]
        else:
            data["scheduled"].append(restored)
        return copy.deepcopy(restored)

    return db.update(apply)


def remove_task(db: Database, task_id: str):
    """Returns the removed task (for Undo)."""

    def apply(data):
        gone = next((t for t in data["scheduled"] if t["id"] == task_id), None)
        data["scheduled"] = [t for t in data["scheduled"] if t["id"] != task_id]
        return gone

    return db.update(apply)


def restore_task(db: Database, task: dict):
    db.update(lambda data: None if any(t["id"] == task["id"] for t in data["scheduled"])
              else data["scheduled"].append(copy.deepcopy(task)))


def upcoming_dates(task: dict, count: int = 2) -> list:
    """The next few dates after the current one, for repeating tasks."""
    rule = task.get("recurring", "One-Time")
    if rule == "One-Time":
        return []
    dates, dt = [], parse_dt(task["due"])
    for _ in range(count):
        dt = add_recurrence(dt, rule, task.get("anchor_day"))
        dates.append(dt)
    return dates


def roll_recurring(data: dict, ref: datetime) -> bool:
    """Recurring tasks whose *next* occurrence has also passed are auto-marked missed and rolled forward."""
    changed = False
    for task in data["scheduled"]:
        rule = task.get("recurring", "One-Time")
        if rule == "One-Time":
            continue
        due = parse_dt(task["due"])
        nxt = add_recurrence(due, rule, task.get("anchor_day"))
        logged = 0
        while nxt <= ref:
            if logged < 10:
                data["past"].append(_past_record(task, "missed", auto=True, when=ref))
                logged += 1
            task["due"] = nxt.strftime(DT_FMT)
            task["notified"] = False
            due, nxt = nxt, add_recurrence(nxt, rule, task.get("anchor_day"))
            changed = True
    return changed


# ════════════════════════════════════════════════════════════════════════════
#  Phone push (ntfy)
# ════════════════════════════════════════════════════════════════════════════
def send_ntfy(settings: dict, title: str, message: str, priority: int = 3, tags=None, click=None):
    """Publish through ntfy's JSON API (UTF-8 safe for titles and emoji). Returns (ok, error)."""
    topic = (settings.get("ntfy_topic") or "").strip()
    server = (settings.get("ntfy_server") or "https://ntfy.sh").strip().rstrip("/")
    if not topic:
        return False, "No ntfy topic set"
    payload = {"topic": topic, "title": title, "message": message, "priority": int(priority)}
    if tags:
        payload["tags"] = list(tags)
    if click:
        payload["click"] = click
    try:
        resp = requests.post(server + "/", json=payload, timeout=12)
        if resp.status_code >= 400:
            return False, f"ntfy answered {resp.status_code}: {resp.text[:120]}"
        return True, ""
    except requests.RequestException as exc:
        return False, str(exc)[:160]


def task_push_text(task: dict, ref: datetime):
    due = parse_dt(task["due"])
    clock = due.strftime("%H:%M")
    if ref < due:
        body = f"Starts at {clock} ({humanize_until(due, ref)})"
    elif (ref - due) > timedelta(minutes=15):
        body = f"Was due at {clock} on {due.strftime('%a %d %b')} (sent late, the app was closed)"
    else:
        body = f"Due now · {clock}"
    if task.get("recurring", "One-Time") != "One-Time":
        body += f"\nRepeats {task['recurring'].lower()}"
    body += f"\nUrgency: {task.get('urgency', 'Medium')}"
    priority = {"High": 5, "Medium": 3, "Low": 2}.get(task.get("urgency"), 3)
    tags = {"High": ["rotating_light"], "Medium": ["bell"], "Low": ["memo"]}.get(task.get("urgency"), ["bell"])
    return task["name"], body, priority, tags


# ════════════════════════════════════════════════════════════════════════════
#  Price engine (price only: stock and delivery are noted by hand)
# ════════════════════════════════════════════════════════════════════════════
ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d|product)/([A-Z0-9]{10})(?:[/?#]|$)", re.I)
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٬٫", "0123456789,.")
BLOCK_MARKERS = (
    "validateCaptcha",
    "Type the characters you see in this image",
    "Enter the characters you see below",
    "api-services-support@amazon.com",
)
CHALLENGE_MARKERS = ("<title>Just a moment...</title>", "cf-chl-", "Attention Required! | Cloudflare",
                     "<title>CAPTCHA page</title>")
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def is_amazon(url: str) -> bool:
    return "amazon." in (urlparse(url).netloc or "").lower()


def normalize_product_url(text: str) -> str:
    """Accepts an Amazon ASIN or a product link from any shop; returns a clean product URL."""
    raw = (text or "").strip()
    if re.fullmatch(r"[A-Za-z0-9]{10}", raw):
        return f"https://www.amazon.sa/-/en/dp/{raw.upper()}"
    if not raw:
        return ""
    if not re.match(r"https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if "amazon." in host:
        match = ASIN_RE.search(parsed.path + "/")
        if match:
            asin = match.group(1).upper()
            if host.endswith((".sa", ".ae", ".eg")):
                return f"https://{host}/-/en/dp/{asin}"
            return f"https://{host}/dp/{asin}"
    if store_key(raw) in STORES:  # tracking/search parameters aren't part of the product
        return f"https://{host}{parsed.path}"
    return raw


def parse_price_text(text: str):
    if not text:
        return None
    cleaned = htmllib.unescape(text).translate(ARABIC_DIGITS)
    match = re.search(r"\d[\d,]*(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        value = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", htmllib.unescape(fragment)).strip()


def _region(page: str, pattern: str, size: int) -> str:
    match = re.search(pattern, page)
    return page[match.start(): match.start() + size] if match else ""


def _looks_challenged(page: str) -> bool:
    head = page[:30000]
    return any(marker in head for marker in CHALLENGE_MARKERS)


PRICE_REGIONS = (
    r'\sid="corePrice_feature_div"',
    r'\sid="corePriceDisplay_desktop_feature_div"',
    r'\sid="apex_desktop"',
    r'\sid="apex_offerDisplay_desktop"',
    r'\sid="price_inside_buybox"',
    r'\sid="priceblock_ourprice"',
    r'\sid="tp_price_block_total_price_ww"',
)


def parse_amazon(page: str) -> dict:
    out = {"blocked": False, "price": None, "title": "", "currency": "SAR"}
    if any(marker in page for marker in BLOCK_MARKERS) and "productTitle" not in page:
        out["blocked"] = True
        return out
    title = re.search(r'id="productTitle"[^>]*>(.*?)</span>', page, re.S)
    if title:
        out["title"] = _strip_tags(title.group(1))
    # Only the buy-box price block counts. Other a-offscreen prices on the page belong to
    # sponsored/related products and must never be used.
    for pattern in PRICE_REGIONS:
        region = _region(page, pattern, 7000)
        if not region:
            continue
        offscreen = re.search(r'class="a-offscreen">\s*([^<]*\d[^<]*)<', region)
        price = parse_price_text(offscreen.group(1)) if offscreen else None
        if price is None:
            whole = re.search(r'class="a-price-whole">\s*([\d,٠-٩٬]+)', region)
            fraction = re.search(r'class="a-price-fraction">\s*(\d+)', region)
            if whole:
                price = parse_price_text(whole.group(1) + ("." + fraction.group(1) if fraction else ""))
        if price is not None:
            out["price"] = price
            break
    if out["price"] is None:
        amount = re.search(r'"priceAmount"\s*:\s*([\d.]+)', page)
        if amount:
            out["price"] = parse_price_text(amount.group(1))
    return out


def _walk_json_offers(node):
    """Yields (price, currency) from schema.org offers, wherever they sit (incl. @graph)."""
    if isinstance(node, dict):
        offers = node.get("offers")
        if offers is not None:
            for offer in offers if isinstance(offers, list) else [offers]:
                if isinstance(offer, dict):
                    for key in ("price", "lowPrice"):
                        if offer.get(key) not in (None, ""):
                            yield offer[key], offer.get("priceCurrency")
                            break
        for value in node.values():
            yield from _walk_json_offers(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_json_offers(value)


def parse_generic(page: str) -> dict:
    """Trendyol, Infiniarc, Cazasouq and most other shops: schema.org JSON-LD, then meta tags."""
    out = {"blocked": _looks_challenged(page), "price": None, "title": "", "currency": None}
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    if title:
        out["title"] = _strip_tags(title.group(1))[:160]
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        for raw, currency in _walk_json_offers(data):
            price = parse_price_text(str(raw))
            if price:
                out["price"] = price
                out["currency"] = (currency or "").strip().upper() or None
                break
        if out["price"]:
            break
    if out["price"] is None:
        for pattern in (
            r'property="product:price:amount"\s+content="([^"]+)"',
            r'itemprop="price"[^>]*content="([^"]+)"',
            r'content="([^"]+)"[^>]*itemprop="price"',
        ):
            match = re.search(pattern, page, re.I)
            if match and parse_price_text(match.group(1)):
                out["price"] = parse_price_text(match.group(1))
                cur = re.search(r'property="product:price:currency"\s+content="([A-Za-z]{3})"', page)
                out["currency"] = cur.group(1).upper() if cur else None
                break
    if out["price"] is not None:
        out["blocked"] = False
    return out


def parse_newegg(page: str) -> dict:
    """Newegg keeps the product (and its final USD price) in window.__initialState__."""
    out = {"blocked": False, "price": None, "title": "", "currency": "USD"}
    match = re.search(r"window\.__initialState__\s*=\s*", page)
    if match:
        end = page.find("</script>", match.end())
        blob = page[match.end(): end if end > 0 else None].strip().rstrip(";").strip()
        try:
            detail = (json.loads(blob) or {}).get("ItemDetail") or {}
            price = detail.get("FinalPrice") or detail.get("UnitCost")
            if price:
                out["price"] = float(price)
            out["title"] = ((detail.get("Description") or {}).get("Title") or "")[:160]
        except (ValueError, TypeError, AttributeError):
            pass
    if out["price"] is None:
        generic = parse_generic(page)
        out.update({k: generic[k] for k in ("price", "title", "blocked") if generic[k]})
        out["currency"] = generic["currency"] or "USD"
    return out


class Fetcher:
    """One browser-like session per check run (cookies persist between products)."""

    def __init__(self):
        if cffi_requests is not None:
            self.session = cffi_requests.Session(impersonate="chrome")
            self.session.headers.update({"Accept-Language": BROWSER_HEADERS["Accept-Language"]})
            self.engine = "curl_cffi"
        else:
            self.session = requests.Session()
            self.session.headers.update(BROWSER_HEADERS)
            self.engine = "requests"
        for name, value in (("i18n-prefs", "SAR"), ("lc-acbsa", "en_AE")):
            try:
                self.session.cookies.set(name, value, domain=".amazon.sa")
            except Exception:
                pass
        self._warmed = False

    def get(self, url: str):
        if is_amazon(url) and not self._warmed:
            self._warmed = True
            try:
                host = urlparse(url).netloc
                self.session.get(f"https://{host}/-/en/", timeout=20)
            except Exception:
                pass
        resp = self.session.get(url, timeout=25)
        return resp.status_code, resp.text


def parser_for(key: str):
    return {"amazon": parse_amazon, "newegg": parse_newegg}.get(key, parse_generic)


def check_item(item: dict, fetcher: Fetcher, retries: int = 1) -> dict:
    url = item["url"]
    key = item.get("store") or store_key(url)
    if store_info(key)["mode"] == "manual":
        return {"status": "manual"}
    for attempt in range(retries + 1):
        try:
            status, page = fetcher.get(url)
        except Exception as exc:
            if attempt < retries:
                time.sleep(4)
                continue
            return {"status": "error", "error": f"Network error: {str(exc)[:100]}"}
        if status == 404:
            return {"status": "error", "error": "Product page not found (404)"}
        parsed = parser_for(key)(page)
        if status in (429, 503) or parsed["blocked"] or (status == 403 and parsed["price"] is None):
            if attempt < retries:
                time.sleep(random.uniform(8, 14))
                continue
            return {"status": "blocked", "error": "The shop blocked the automatic check this time"}
        if status >= 400:
            return {"status": "error", "error": f"Shop answered HTTP {status}"}
        if parsed["price"] is None:
            if key == "amazon":
                return {"status": "no_price", "error": "No seller price on the page right now", "title": parsed["title"]}
            return {"status": "error", "error": "Couldn't find a price on that page"}
        return {"status": "ok", **parsed}
    return {"status": "error", "error": "Unknown error"}


# ---- prices in SAR -----------------------------------------------------------
def landed(item: dict, raw, rates: dict):
    """What the listing costs delivered, in SAR: (price + shipping) × rate, plus import VAT/fees."""
    if raw is None:
        return None
    rate = (rates or DEFAULT_RATES).get((item.get("currency") or "SAR").upper())
    if not rate:
        return None
    ship = item.get("shipping") or 0.0
    fees = item.get("fees_pct") or 0.0
    return round((float(raw) + float(ship)) * float(rate) * (1 + float(fees) / 100), 2)


def item_price(item: dict, rates: dict):
    return landed(item, item.get("raw_price"), rates)


def listing_usable(item: dict, rates: dict) -> bool:
    return not item.get("skip") and item.get("status") != "no_price" and item_price(item, rates) is not None


def display_name(item: dict) -> str:
    variant = (item.get("variant") or "").strip()
    return f"{item['part']} ({variant})" if variant else item["part"]


def shipping_unknown(item: dict) -> bool:
    return item.get("shipping") is None and store_info(item.get("store", "other"))["shipping"] != 0.0


def items_in_category_order(items: list) -> list:
    order = {cat: i for i, cat in enumerate(CATEGORIES)}
    position = {id(it): n for n, it in enumerate(items)}
    return sorted(items, key=lambda it: (order.get(it.get("category"), 99), position[id(it)]))


def part_stats(items: list, rates: dict) -> dict:
    """Per part: every listing, the cheapest usable one right now, and the lowest/highest
    price ever recorded across all its listings (in SAR, with current shipping/fees/rates)."""
    stats = {}
    for item in items_in_category_order(items):
        st = stats.setdefault(item["part"], {"part": item["part"], "category": item["category"], "listings": [],
                                              "best": None, "best_price": None, "low": None, "high": None})
        st["listings"].append(item)
        price = item_price(item, rates)
        if listing_usable(item, rates) and (st["best_price"] is None or price < st["best_price"]):
            st["best"], st["best_price"] = item, price
        for day, raw in (item.get("history") or {}).items():
            value = landed(item, raw, rates)
            if value is None:
                continue
            point = {"price": value, "store": store_label(item), "date": day, "id": item["id"]}
            if st["low"] is None or value < st["low"]["price"]:
                st["low"] = point
            if st["high"] is None or value > st["high"]["price"]:
                st["high"] = point
    return stats


def listing_low_high(item: dict, rates: dict):
    values = [v for v in (landed(item, raw, rates) for raw in (item.get("history") or {}).values()) if v is not None]
    return (min(values), max(values)) if values else (None, None)


def compute_combo(combo: dict, items: list, rates: dict, use_baseline: bool = False) -> dict:
    """For every category in the build, take the cheapest part (each part at its best shop)."""
    stats = part_stats(items, rates)
    chosen = [stats[p] for p in combo.get("parts", []) if p in stats]
    cats = [c for c in CATEGORIES if any(st["category"] == c for st in chosen)]
    cats += sorted({st["category"] for st in chosen} - set(cats))
    picks, missing, total = [], [], 0.0
    for cat in cats:
        pool = []
        for st in chosen:
            if st["category"] != cat:
                continue
            if use_baseline:
                for it in st["listings"]:
                    value = landed(it, it.get("baseline_raw"), rates)
                    if value is not None and not it.get("skip"):
                        pool.append((value, st["part"], store_label(it)))
            elif st["best_price"] is not None:
                pool.append((st["best_price"], st["part"], store_label(st["best"])))
        if not pool:
            missing.append(cat)
            continue
        price, part, store = min(pool, key=lambda row: row[0])
        picks.append({"category": cat, "part": part, "store": store, "price": price})
        total += price
    return {"total": None if missing or not picks else round(total, 2), "picks": picks, "missing": missing}


def apply_check_result(item: dict, res: dict, stamp: datetime):
    today = stamp.strftime("%Y-%m-%d")
    item["last_checked"] = stamp.strftime(DT_FMT)
    if res["status"] == "ok":
        currency = (res.get("currency") or "").upper()
        if currency and currency != (item.get("currency") or "").upper():
            # the shop changed currency: old numbers are in a different unit, start fresh
            item["currency"] = currency
            item["history"], item["baseline_raw"], item["raw_price"] = {}, None, None
        if res.get("title") and item.get("name", "").startswith("New listing"):
            item["name"] = res["title"][:120]
        item["prev_raw"] = item.get("raw_price")
        item["raw_price"] = res["price"]
        if item.get("baseline_raw") is None:
            item["baseline_raw"] = res["price"]
        history = item.setdefault("history", {})
        history[today] = res["price"]
        if len(history) > 400:
            for key in sorted(history)[:-400]:
                history.pop(key, None)
        item["status"], item["error"] = "ok", ""
    else:
        item["status"] = res["status"]
        item["error"] = res.get("error", "")


def run_price_check(db: Database, progress=lambda text: None) -> dict:
    pf = db.get("price_flash")
    targets = [i for i in items_in_category_order(pf["items"])
               if not i.get("skip") and store_info(i.get("store") or store_key(i["url"]))["mode"] == "auto"]
    fetcher = Fetcher()
    results = {}
    for index, item in enumerate(targets):
        progress(f"Checking {index + 1}/{len(targets)} · {store_label(item)} · {display_name(item)}")
        results[item["id"]] = check_item(item, fetcher)
        if index < len(targets) - 1:
            time.sleep(random.uniform(2.5, 5.5))

    stamp = now()
    today = stamp.strftime("%Y-%m-%d")

    def apply(data):
        pfd = data["price_flash"]
        rates = pfd.get("rates") or DEFAULT_RATES
        before = part_stats(pfd["items"], rates)
        listings = []
        for item in pfd["items"]:
            res = results.get(item["id"])
            if res is None:  # skipped, manual, or added while the check was running
                continue
            apply_check_result(item, res, stamp)
            listings.append({"id": item["id"], "part": item["part"], "store": store_label(item),
                             "status": item["status"], "fresh": res["status"] == "ok"})
        after = part_stats(pfd["items"], rates)
        last_best = pfd.get("last_best") or {}
        parts = []
        for name, st in after.items():
            low_before = (before.get(name) or {}).get("low")
            parts.append({
                "part": name,
                "category": st["category"],
                "price": st["best_price"],
                "store": store_label(st["best"]) if st["best"] else None,
                "url": st["best"]["url"] if st["best"] else None,
                "prev": last_best.get(name),
                "low_before": low_before["price"] if low_before else None,
            })
        pfd["last_best"] = {name: st["best_price"] for name, st in after.items() if st["best_price"] is not None}
        combos = []
        day_totals = pfd.setdefault("combo_history", {}).setdefault(today, {})
        for combo in pfd.get("combos", []):
            calc = compute_combo(combo, pfd["items"], rates)
            if calc["total"] is not None:
                day_totals[combo["id"]] = calc["total"]
            combos.append({"id": combo["id"], "name": combo["name"], "total": calc["total"],
                           "baseline_total": combo.get("baseline_total"), "threshold": combo.get("threshold"),
                           "picks": calc["picks"], "missing": calc["missing"]})
        pfd["last_run"] = stamp.strftime(DT_FMT)
        report = {"time": stamp.strftime(DT_FMT), "parts": parts, "listings": listings, "combos": combos,
                  "engine": fetcher.engine}
        pfd["last_summary"] = report
        return report

    return db.update(apply)


def build_summary(report: dict) -> tuple[str, str]:
    """The daily phone message: best price per part (and where), then what went up and down."""
    stamp = datetime.strptime(report["time"], DT_FMT)
    title = f"Price Flash · {stamp.strftime('%a %d %b')}"
    lines, ups, downs = [], [], []
    current_cat = None
    for part in report["parts"]:
        if part["category"] != current_cat:
            current_cat = part["category"]
            if lines:
                lines.append("")
            lines.append(current_cat.upper())
        if part["price"] is None:
            lines.append(f"• {part['part']}: no price")
            continue
        delta = None if part["prev"] is None else part["price"] - part["prev"]
        arrow = "•"
        if delta is not None and abs(delta) >= 0.005:
            arrow = "▲" if delta > 0 else "▼"
            (ups if delta > 0 else downs).append(f"{part['part']} {fmt_delta(delta)}")
        line = f"{arrow} {part['part']}: {fmt_money(part['price'])} · {part['store']}"
        if delta is not None and abs(delta) >= 0.005:
            line += f" ({fmt_delta(delta)})"
        lines.append(line)
    lines.append("")
    lines.append("Up: " + (", ".join(ups) if ups else "nothing"))
    lines.append("Down: " + (", ".join(downs) if downs else "nothing"))
    for combo in report["combos"]:
        if combo["total"] is None:
            lines.append(f"{combo['name']}: incomplete (no price for {', '.join(combo['missing'])})")
            continue
        base = combo.get("baseline_total")
        extra = f" ({fmt_delta(combo['total'] - base)} vs start)" if base else ""
        lines.append(f"{combo['name']}: SAR {fmt_money(combo['total'])}{extra}")
    failed = [l for l in report["listings"] if l["status"] in ("blocked", "error")]
    if failed:
        lines.append(f"⚠ {len(failed)} listing(s) couldn't be read; their last price is used.")
    return title, "\n".join(lines)


def evaluate_alerts(db: Database, report: dict) -> list[dict]:
    """Fire only when a deal is new or got better since the last alert ('occasional' alerts)."""
    alerts = []

    def apply(data):
        pfd = data["price_flash"]
        rates = pfd.get("rates") or DEFAULT_RATES
        pct = float(pfd.get("drop_alert_pct") or 5.0)
        # 1) a part's best price is the lowest ever recorded
        part_alerts = pfd.setdefault("part_alerts", {})
        for part in report["parts"]:
            price, low = part["price"], part.get("low_before")
            if price is None or low is None:
                continue
            if price < low - 0.5:
                last = part_alerts.get(part["part"])
                if last is None or price < last - 0.5:
                    part_alerts[part["part"]] = price
                    alerts.append({"line": f"{part['part']}: SAR {fmt_money(price)} at {part['store']}, lowest seen "
                                           f"(was {fmt_money(low)})", "url": part["url"]})
            else:
                part_alerts.pop(part["part"], None)
        covered = {a["url"]: a for a in alerts}
        # 2) listing-level: % under its start price, or under the user's own target
        fresh_ids = {l["id"] for l in report["listings"] if l["fresh"]}
        for item in pfd["items"]:
            if item["id"] not in fresh_ids or item.get("skip"):
                continue
            price = item_price(item, rates)
            base = landed(item, item.get("baseline_raw"), rates)
            if price is None:
                continue
            reasons = []
            if base and price <= base * (1 - pct / 100):
                reasons.append(f"{(base - price) / base * 100:.1f}% below start ({fmt_money(base)})")
            if item.get("alert_below") and price < float(item["alert_below"]):
                reasons.append(f"under your SAR {fmt_money(float(item['alert_below']))} target")
            last = item.get("last_alert_price")
            if reasons and (last is None or price < last - 0.5):
                item["last_alert_price"] = price
                if item["url"] in covered:  # same deal as a new-low alert: one line, all reasons
                    extra = [r for r in reasons if "target" in r]
                    if extra:
                        covered[item["url"]]["line"] += f", {extra[0]}"
                else:
                    alerts.append({"line": f"{display_name(item)} at {store_label(item)}: SAR {fmt_money(price)}, "
                                           f"{' & '.join(reasons)}", "url": item["url"]})
            elif not reasons:
                item["last_alert_price"] = None
        # 3) a build total under its target
        for combo in pfd.get("combos", []):
            calc = compute_combo(combo, pfd["items"], rates)
            total, target = calc["total"], combo.get("threshold")
            if total is None or not target:
                continue
            if total <= float(target):
                last = combo.get("last_alert_total")
                if last is None or total < last - 0.5:
                    combo["last_alert_total"] = total
                    picks = " + ".join(f"{p['part']} ({p['store']})" for p in calc["picks"])
                    alerts.append({"line": f"{combo['name']}: SAR {fmt_money(total)} (target ≤ "
                                           f"{fmt_money(float(target))}) · {picks}", "url": None})
            else:
                combo["last_alert_total"] = None

    db.update(apply)
    return alerts


def alert_message(alerts: list[dict]) -> tuple[str, str, str | None]:
    title = "🔔 Price drop alert"
    body = "\n".join(a["line"] for a in alerts)
    click = next((a["url"] for a in alerts if a.get("url")), None)
    return title, body, click


# ════════════════════════════════════════════════════════════════════════════
#  Background service (daemon thread)
# ════════════════════════════════════════════════════════════════════════════
class BackgroundService(threading.Thread):
    TICK_SECONDS = 15

    def __init__(self, db: Database, events: queue.Queue):
        super().__init__(daemon=True, name="almanac-service")
        self.db = db
        self.events = events
        self.stop_event = threading.Event()
        self._price_lock = threading.Lock()
        self.price_running = False
        self.started = time.monotonic()
        self._update_lock = threading.Lock()
        self.update_running = False
        self._update_retry_at = 0.0

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                log.error("Service tick failed:\n%s", traceback.format_exc())
            self.stop_event.wait(self.TICK_SECONDS)

    def stop(self):
        self.stop_event.set()

    def tick(self):
        self._roll_recurring()
        self._send_due_reminders()
        self._maybe_auto_price_check()
        self._maybe_check_updates()

    def _roll_recurring(self):
        if self.db.update(lambda data: roll_recurring(data, now())):
            self.events.put(("tasks_changed",))

    def _send_due_reminders(self):
        ref = now()
        settings = self.db.get("settings")
        due_tasks = []
        with self.db.lock:
            for task in self.db.data["scheduled"]:
                if task.get("notified"):
                    continue
                remind_at = parse_dt(task["due"]) - timedelta(minutes=int(task.get("remind", 0)))
                retry_at = task.get("retry_at")
                if ref >= remind_at and (not retry_at or ref >= parse_dt(retry_at)):
                    due_tasks.append(copy.deepcopy(task))
        for task in due_tasks:
            ok, err = True, ""
            if settings.get("notifications_enabled", True):
                title, body, priority, tags = task_push_text(task, ref)
                ok, err = send_ntfy(settings, title, body, priority=priority, tags=tags)

            def mark(data, task_id=task["id"], ok=ok):
                for t in data["scheduled"]:
                    if t["id"] == task_id:
                        if ok:
                            t["notified"] = True
                            t.pop("retry_at", None)
                        else:
                            t["retry_at"] = (ref + timedelta(minutes=2)).strftime(DT_FMT)

            self.db.update(mark)
            self.events.put(("tasks_changed",))
            if ok:
                self.events.put(("toast", f"Reminder: {task['name']}", "info"))
            else:
                log.warning("Push failed for %s: %s", task["name"], err)
                self.events.put(("toast", f"Couldn't reach your phone: {err[:60]}", "error"))

    def _maybe_auto_price_check(self):
        pf = self.db.get("price_flash")
        if not pf.get("enabled") or not pf.get("items"):
            return
        ref = now()
        today = ref.strftime("%Y-%m-%d")
        if pf.get("last_auto_run") == today or ref.strftime("%H:%M") < pf.get("check_time", "09:00"):
            return
        if self.start_price_check(auto=True):
            self.db.update(lambda data: data["price_flash"].__setitem__("last_auto_run", today))

    def _maybe_check_updates(self):
        settings = self.db.get("settings")
        if not settings.get("check_updates", True) or not updates_supported()[0]:
            return
        if time.monotonic() - self.started < 60 or time.monotonic() < self._update_retry_at:
            return
        last = settings.get("last_update_check")
        if last and now() - datetime.strptime(last, TS_FMT) < timedelta(hours=UPDATE_CHECK_HOURS):
            return
        self.start_update_check(manual=False)

    def start_update_check(self, manual: bool) -> bool:
        with self._update_lock:
            if self.update_running:
                return False
            self.update_running = True
        threading.Thread(target=self._update_job, args=(manual,), daemon=True, name="almanac-update").start()
        return True

    def _update_job(self, manual: bool):
        try:
            manifest = fetch_manifest()
            self.db.update(lambda d: d["settings"].__setitem__("last_update_check", now().strftime(TS_FMT)))
            status = update_status(manifest, self.db.get("settings"), getattr(LAUNCHER, "version", 0), manual)
            self.events.put(("update_checked", status, manifest, manual))
        except UpdateError as exc:
            self._update_retry_at = time.monotonic() + 3600
            log.info("Update check failed: %s", exc)
            if manual:
                self.events.put(("update_check_failed", str(exc)))
        except Exception as exc:
            self._update_retry_at = time.monotonic() + 3600
            log.error("Update check crashed:\n%s", traceback.format_exc())
            if manual:
                self.events.put(("update_check_failed", str(exc)))
        finally:
            with self._update_lock:
                self.update_running = False

    def start_price_check(self, auto=False) -> bool:
        with self._price_lock:
            if self.price_running:
                return False
            self.price_running = True
        threading.Thread(target=self._price_job, args=(auto,), daemon=True, name="almanac-prices").start()
        self.events.put(("price_started",))
        return True

    def _price_job(self, auto: bool):
        try:
            report = run_price_check(self.db, progress=lambda text: self.events.put(("price_progress", text)))
            alerts = evaluate_alerts(self.db, report)
            settings = self.db.get("settings")
            pf = self.db.get("price_flash")
            pushed = []
            if settings.get("notifications_enabled", True):
                if auto and pf.get("notify_summary", True):
                    title, body = build_summary(report)
                    ok, _ = send_ntfy(settings, title, body, priority=3, tags=["chart_with_upwards_trend"])
                    pushed.append(("summary", ok))
                if alerts:
                    title, body, click = alert_message(alerts)
                    ok, _ = send_ntfy(settings, title, body, priority=4, tags=["rotating_light", "moneybag"], click=click)
                    pushed.append(("alert", ok))
            self.events.put(("price_done", report, alerts, pushed))
        except Exception as exc:
            log.error("Price check failed:\n%s", traceback.format_exc())
            self.events.put(("price_error", str(exc)))
        finally:
            with self._price_lock:
                self.price_running = False


# ════════════════════════════════════════════════════════════════════════════
#  Updates
# ════════════════════════════════════════════════════════════════════════════
# The release on GitHub carries latest.json:
#   {"version": "1.13", "name": "...", "date": "2026-11-01", "summary": "...", "sections": [[heading, [bullets]]],
#    "core_url": ".../almanac_app.py", "core_sha256": "...", "core_size": 123456, "min_launcher": 1,
#    "full_url": ".../Almanac-v1.13-windows.zip", "page_url": ".../releases/tag/v1.13"}
LAUNCHER = None  # set by main() when started through launcher.py / Almanac.exe
UPDATE_CHECK_HOURS = 24
UPDATE_MAX_BYTES = 8_000_000
BACKUPS_KEPT = 10
VERSION_LINE_RE = re.compile(r'^APP_VERSION\s*=\s*"([^"]+)"', re.M)


class UpdateError(Exception):
    pass


def version_tuple(text) -> tuple:
    try:
        return tuple(int(part) for part in str(text).strip().lstrip("vV").split("."))
    except (TypeError, ValueError):
        return (0,)


def manifest_url() -> str | None:
    if os.environ.get("ALMANAC_MANIFEST_URL"):
        return os.environ["ALMANAC_MANIFEST_URL"]
    if not UPDATE_REPO or UPDATE_REPO.startswith("__"):
        return None
    return f"https://github.com/{UPDATE_REPO}/releases/latest/download/latest.json"


def updates_supported() -> tuple[bool, str]:
    if LAUNCHER is None:
        return False, "Running from source, so updates come from the source files, not the updater."
    if manifest_url() is None:
        return False, "This copy wasn't built with an update source."
    return True, ""


def _http_get(url: str, stream=False):
    headers = {"User-Agent": f"Almanac/{APP_VERSION}", "Cache-Control": "no-cache"}
    return requests.get(url, headers=headers, timeout=25, stream=stream)


def fetch_manifest() -> dict:
    url = manifest_url()
    if not url:
        raise UpdateError("No update source")
    try:
        resp = _http_get(url)
    except requests.RequestException as exc:
        raise UpdateError("Couldn't reach GitHub. Check the internet connection.") from exc
    if resp.status_code == 404:
        raise UpdateError("No release has been published yet.")
    if resp.status_code != 200:
        raise UpdateError(f"GitHub answered {resp.status_code}")
    try:
        manifest = resp.json()
    except ValueError as exc:
        raise UpdateError("The update information was unreadable") from exc
    for key in ("version", "core_url", "core_sha256"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise UpdateError(f"The update information is missing '{key}'")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["core_sha256"].lower()):
        raise UpdateError("The update information has a bad checksum")
    if not manifest["core_url"].startswith("https://") and not os.environ.get("ALMANAC_MANIFEST_URL"):
        raise UpdateError("Updates must come over HTTPS")
    return manifest


def update_status(manifest: dict, settings: dict, launcher_version: int, manual: bool) -> str:
    """'none' (nothing newer), 'skipped', 'needs_full' (needs a newer Almanac.exe) or 'available'."""
    if version_tuple(manifest["version"]) <= version_tuple(APP_VERSION):
        return "none"
    if not manual and settings.get("skip_version") == manifest["version"]:
        return "skipped"
    if int(manifest.get("min_launcher") or 1) > int(launcher_version or 0):
        return "needs_full"
    return "available"


def download_core(manifest: dict, progress=lambda text: None) -> bytes:
    """Download almanac_app.py and prove it is the file the release describes before anything changes."""
    progress("Downloading…")
    try:
        resp = _http_get(manifest["core_url"], stream=True)
        resp.raise_for_status()
        chunks, size = [], 0
        for chunk in resp.iter_content(64 * 1024):
            size += len(chunk)
            if size > UPDATE_MAX_BYTES:
                raise UpdateError("The download was far larger than expected")
            chunks.append(chunk)
    except requests.RequestException as exc:
        raise UpdateError("The download failed. Nothing was changed.") from exc
    data = b"".join(chunks)
    progress("Checking the download…")
    if hashlib.sha256(data).hexdigest() != manifest["core_sha256"].lower():
        raise UpdateError("The download didn't match the release checksum. Nothing was changed.")
    try:
        text = data.decode("utf-8")
        compile(text, "almanac_app.py", "exec")
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise UpdateError("The downloaded file isn't valid. Nothing was changed.") from exc
    found = VERSION_LINE_RE.search(text)
    if not found or found.group(1) != manifest["version"]:
        raise UpdateError("The downloaded file is a different version than announced. Nothing was changed.")
    return data


def backup_database(db: Database, reason: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(BACKUP_DIR, f"almanac_data-{reason}-{stamp}.json")
    with db.lock:
        db.save()
        shutil.copy2(db.path, target)
    backups = sorted((os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith(".json")),
                     key=os.path.getmtime)
    for old in backups[:-BACKUPS_KEPT]:
        try:
            os.remove(old)
        except OSError:
            pass
    return target


def install_update(db: Database, manifest: dict, launcher, progress=lambda text: None) -> str:
    """Download, verify, back up the data, then hand the file to the launcher. Restart to finish."""
    data = download_core(manifest, progress)
    progress("Backing up your data…")
    backup = backup_database(db, f"before-v{manifest['version']}")
    progress("Installing…")
    launcher.install(data, manifest["version"], APP_VERSION)
    log.info("Update %s installed; data backed up to %s", manifest["version"], backup)
    return backup


# ════════════════════════════════════════════════════════════════════════════
#  Icon, tray, single instance, start-up
# ════════════════════════════════════════════════════════════════════════════
def make_icon_image(size: int = 256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.24), fill=NAVY)
    pad = int(size * 0.17)
    ring = max(2, int(size * 0.075))
    draw.ellipse([pad, pad, size - pad, size - pad], outline=TERRACOTTA, width=ring)
    c = size / 2
    hand = max(2, int(size * 0.07))
    draw.line([c, c, c, size * 0.31], fill=SAND, width=hand)
    draw.line([c, c, size * 0.67, size * 0.58], fill=SAND, width=hand)
    dot = size * 0.06
    draw.ellipse([c - dot, c - dot, c + dot, c + dot], fill=TERRACOTTA)
    return img


def write_icon_file(path: str):
    make_icon_image(256).save(path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def acquire_single_instance(wait_seconds: float = 0):
    """Bind the instance port. After an update the old window is still closing, so wait for it."""
    deadline = time.monotonic() + wait_seconds
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", INSTANCE_PORT))
            sock.listen(2)
            return sock
        except OSError:
            sock.close()
            if time.monotonic() < deadline:
                time.sleep(0.4)
                continue
        try:
            with socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=2) as conn:
                conn.sendall(b"show")
        except OSError:
            pass
        return None


def listen_for_second_instance(sock, events: queue.Queue):
    def loop():
        while True:
            try:
                conn, _ = sock.accept()
                with conn:
                    conn.recv(16)
                events.put(("show",))
            except OSError:
                return

    threading.Thread(target=loop, daemon=True, name="almanac-instance").start()


def startup_script_path() -> str | None:
    if not IS_WINDOWS:
        return None
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "Almanac.vbs")


def set_start_with_windows(enabled: bool):
    path = startup_script_path()
    if not path:
        return
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
        return
    if getattr(sys, "frozen", False):
        command = f'""{sys.executable}"" --minimized'
    else:
        pythonw = sys.executable
        candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(candidate):
            pythonw = candidate
        command = f'""{pythonw}"" ""{os.path.abspath(__file__)}"" --minimized'
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f'CreateObject("WScript.Shell").Run "{command}", 0, False\n')


class Tray:
    def __init__(self, app: "App"):
        self.app = app
        self.icon = None
        self.available = False
        if pystray is None or Image is None:
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem(f"Open {APP_NAME}", lambda *_: app.events.put(("show",)), default=True),
                pystray.MenuItem("Check prices now", lambda *_: app.events.put(("tray_check_prices",))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda *_: app.events.put(("quit",))),
            )
            self.icon = pystray.Icon("almanac", make_icon_image(64), APP_NAME, menu)
            self.icon.run_detached()
            self.available = True
        except Exception:
            log.warning("Tray unavailable:\n%s", traceback.format_exc())
            self.icon = None

    def notify(self, text: str):
        if self.icon is not None:
            try:
                self.icon.notify(text, APP_NAME)
            except Exception:
                pass

    def stop(self):
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════════════════
#  UI building blocks
# ════════════════════════════════════════════════════════════════════════════
def card(master, **kw):
    opts = dict(fg_color=P.CARD, corner_radius=12, border_width=1, border_color=P.BORDER)
    opts.update(kw)
    return ctk.CTkFrame(master, **opts)


def label(master, text="", font=None, color=P.TEXT, **kw):
    return ctk.CTkLabel(master, text=text, font=font or FONTS.body, text_color=color, **kw)


def pill(master, text, fg, fg_text):
    return ctk.CTkLabel(
        master, text=f"  {text}  ", fg_color=fg, text_color=fg_text, corner_radius=8,
        font=FONTS.small_bold, height=24,
    )


def accent_button(master, text, command, **kw):
    opts = dict(fg_color=P.ACCENT, hover_color=P.ACCENT_HOVER, text_color=P.ON_ACCENT,
                corner_radius=10, height=38, font=FONTS.body_bold)
    opts.update(kw)
    return ctk.CTkButton(master, text=text, command=command, **opts)


def ghost_button(master, text, command, **kw):
    opts = dict(fg_color="transparent", hover_color=P.CARD_ALT, text_color=P.TEXT, border_width=1,
                border_color=P.BORDER, corner_radius=10, height=36, font=FONTS.body)
    opts.update(kw)
    return ctk.CTkButton(master, text=text, command=command, **opts)


def option_menu(master, values, width=90, command=None):
    return ctk.CTkOptionMenu(
        master, values=values, width=width, height=36, corner_radius=10, command=command,
        fg_color=P.INPUT, button_color=P.CARD_ALT, button_hover_color=P.BORDER,
        text_color=P.TEXT, dropdown_fg_color=P.CARD, dropdown_text_color=P.TEXT,
        dropdown_hover_color=P.CARD_ALT, font=FONTS.body, dropdown_font=FONTS.body,
    )


def segmented(master, values, command=None):
    return ctk.CTkSegmentedButton(
        master, values=values, command=command, height=36, corner_radius=10, font=FONTS.body,
        fg_color=P.CARD_ALT, selected_color=P.ACCENT, selected_hover_color=P.ACCENT_HOVER,
        unselected_color=P.CARD_ALT, unselected_hover_color=P.BORDER, text_color=P.TEXT,
    )


def entry(master, placeholder="", width=200):
    return ctk.CTkEntry(
        master, placeholder_text=placeholder, width=width, height=38, corner_radius=10,
        fg_color=P.INPUT, border_color=P.BORDER, text_color=P.TEXT, font=FONTS.body,
        placeholder_text_color=P.MUTED,
    )


def switch(master, text, command=None):
    return ctk.CTkSwitch(
        master, text=text, command=command, font=FONTS.body, text_color=P.TEXT,
        progress_color=P.ACCENT, button_color=("#FFFFFF", SAND), button_hover_color=("#F2F2F2", "#F6D9A8"),
        fg_color=P.BORDER,
    )


def field_title(master, text):
    return ctk.CTkLabel(master, text=text, font=FONTS.field, text_color=P.TEXT, anchor="w")


def scroll_area(master):
    return ctk.CTkScrollableFrame(
        master, fg_color="transparent", scrollbar_button_color=P.BORDER,
        scrollbar_button_hover_color=P.MUTED,
    )


def chart_colors() -> dict:
    return {
        "bg": pick(P.CARD),
        "text": pick(P.TEXT),
        "muted": pick(P.MUTED),
        "grid": pick(P.BORDER),
        "accent": TERRACOTTA,
        "success": pick(P.SUCCESS),
        "info": pick(P.INFO),
        "warn": pick(P.WARN),
        "empty": pick(P.BORDER),
    }


class ChartPanel(ctk.CTkFrame):
    """A card that hosts a matplotlib figure painted in the current theme colours."""

    def __init__(self, master, title: str, height: int = 260):
        super().__init__(master, fg_color=P.CARD, corner_radius=12, border_width=1, border_color=P.BORDER)
        label(self, title, FONTS.h3).pack(anchor="w", padx=20, pady=(16, 0))
        self.holder = ctk.CTkFrame(self, fg_color="transparent", height=height)
        self.holder.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.holder.pack_propagate(False)
        self.canvas = None
        self.height = height

    def draw(self, painter):
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
            self.canvas = None
        colors = chart_colors()
        fig = Figure(figsize=(4.6, self.height / 100), dpi=100, facecolor=colors["bg"])
        painter(fig, colors)
        self.canvas = FigureCanvasTkAgg(fig, master=self.holder)
        widget = self.canvas.get_tk_widget()
        widget.configure(bg=colors["bg"], highlightthickness=0, borderwidth=0)
        widget.pack(fill="both", expand=True)
        self.canvas.draw_idle()


class EmptyState(ctk.CTkFrame):
    def __init__(self, master, icon, title, subtitle, action_text=None, action=None, second_text=None, second=None):
        super().__init__(master, fg_color="transparent")
        label(self, icon, FONTS.icon, P.ACCENT).pack(pady=(50, 6))
        label(self, title, FONTS.h2).pack()
        label(self, subtitle, FONTS.body, P.MUTED, wraplength=560, justify="center").pack(pady=(4, 16))
        if action_text:
            accent_button(self, action_text, action, width=200).pack()
        if second_text:
            ghost_button(self, second_text, second, width=200, border_width=0).pack(pady=(8, 0))


# ════════════════════════════════════════════════════════════════════════════
#  Pages
# ════════════════════════════════════════════════════════════════════════════
class Page(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.db = app.db

    def on_show(self):
        self.refresh()

    def refresh(self):
        pass

    def on_theme_change(self):
        pass

    def make_header(self, title: str):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=28, pady=(24, 8))
        actions = ctk.CTkFrame(bar, fg_color="transparent", height=1, width=1)
        actions.pack(side="right", anchor="n", pady=(6, 0))
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        label(left, title, FONTS.h1).pack(anchor="w")
        subtitle = label(left, "", FONTS.body, P.MUTED, anchor="w", justify="left")
        subtitle.pack(anchor="w")
        return subtitle, actions

    @staticmethod
    def clear(frame):
        for child in frame.winfo_children():
            child.destroy()


# ─────────────────────────────────────────────────────────────── Scheduled
class ScheduledPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.subtitle, actions = self.make_header("Scheduled")
        accent_button(actions, "+  New task", lambda: app.show("new"), width=140).pack()
        self.list = scroll_area(self)
        self.list.pack(fill="both", expand=True, padx=16, pady=(4, 16))

    def refresh(self):
        self.clear(self.list)
        tasks = sorted(self.db.get("scheduled"), key=lambda t: t["due"])
        ref = now()
        if not tasks:
            self.subtitle.configure(text="Nothing on the calendar.")
            EmptyState(self.list, "◷", "No tasks yet", "Schedule something and it will ping your phone on time.",
                       "Schedule a task", lambda: self.app.show("new")).pack(fill="x")
            return
        overdue = sum(1 for t in tasks if parse_dt(t["due"]) < ref)
        nxt = next((t for t in tasks if parse_dt(t["due"]) >= ref), None)
        parts = [f"{len(tasks)} scheduled"]
        if overdue:
            parts.append(f"{overdue} overdue")
        if nxt:
            parts.append(f"next: {nxt['name']} {humanize_until(parse_dt(nxt['due']), ref)}")
        self.subtitle.configure(text="  ·  ".join(parts))
        current = None
        for task in tasks:
            group = schedule_group(parse_dt(task["due"]), ref)
            if group != current:
                current = group
                count = sum(1 for t in tasks if schedule_group(parse_dt(t["due"]), ref) == group)
                head = ctk.CTkFrame(self.list, fg_color="transparent")
                head.pack(fill="x", padx=16, pady=(14, 2))
                label(head, group, FONTS.small_bold, P.ACCENT if group == "Overdue" else P.MUTED).pack(side="left")
                label(head, f"  {count}", FONTS.small, P.MUTED).pack(side="left")
            self._task_card(task, ref).pack(fill="x", padx=12, pady=5)

    def _task_card(self, task, ref):
        due = parse_dt(task["due"])
        urgency = task.get("urgency", "Medium")
        box = card(self.list)
        strip = ctk.CTkFrame(box, width=6, height=20, corner_radius=3, fg_color=URGENCY_STRIP.get(urgency, P.WARN))
        strip.pack(side="left", fill="y", padx=(10, 0), pady=14)

        body = ctk.CTkFrame(box, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, padx=16, pady=14)
        label(body, task["name"], FONTS.h3, anchor="w", justify="left", wraplength=520).pack(anchor="w")
        meta = ctk.CTkFrame(body, fg_color="transparent")
        meta.pack(anchor="w", pady=(6, 0))
        label(meta, f"{due.strftime('%Y-%m-%d')}   {due.strftime('%H:%M')}", FONTS.body_bold).pack(side="left")
        when = humanize_until(due, ref)
        label(meta, f"   {when}", FONTS.small, P.ACCENT if due < ref else P.MUTED).pack(side="left")

        badges = ctk.CTkFrame(body, fg_color="transparent")
        badges.pack(anchor="w", pady=(8, 0))
        fg, fg_text = URGENCY_STYLE.get(urgency, URGENCY_STYLE["Medium"])
        pill(badges, f"{urgency} urgency", fg, fg_text).pack(side="left", padx=(0, 6))
        rec = task.get("recurring", "One-Time")
        pill(badges, "One-time" if rec == "One-Time" else f"↻ {rec}", P.CARD_ALT, P.TEXT).pack(side="left", padx=(0, 6))
        later = upcoming_dates(task)
        if later:
            label(badges, "then " + ", ".join(d.strftime("%a %d %b") for d in later), FONTS.small, P.MUTED
                  ).pack(side="left", padx=(4, 8))
        remind = int(task.get("remind", 0))
        pill(badges, "⏰ at time" if remind == 0 else f"⏰ {remind} min before", P.CARD_ALT, P.MUTED).pack(side="left", padx=(0, 6))
        if due < ref:
            pill(badges, "Overdue", P.ACCENT_SOFT, P.ACCENT).pack(side="left", padx=(0, 6))
        elif task.get("notified"):
            pill(badges, "Reminder sent", P.SUCCESS_SOFT, P.SUCCESS).pack(side="left", padx=(0, 6))

        actions = ctk.CTkFrame(box, fg_color="transparent")
        actions.pack(side="right", padx=16, pady=14)
        ctk.CTkButton(
            actions, text="✓  Done", width=112, height=36, corner_radius=10, font=FONTS.body_bold,
            fg_color=P.SUCCESS, hover_color=P.SUCCESS_HOVER, text_color=("#FFFFFF", NAVY),
            command=lambda tid=task["id"]: self._resolve(tid, "completed"),
        ).pack(pady=(0, 6))
        ghost_button(actions, "✕  Missed", lambda tid=task["id"]: self._resolve(tid, "missed"), width=112,
                     text_color=P.ACCENT, border_color=P.ACCENT, hover_color=P.ACCENT_SOFT).pack(pady=(0, 6))
        ctk.CTkButton(
            actions, text="Remove", width=112, height=24, fg_color="transparent", hover_color=P.CARD_ALT,
            text_color=P.MUTED, font=FONTS.small, command=lambda tid=task["id"], n=task["name"]: self._remove(tid, n),
        ).pack()
        return box

    def _resolve(self, task_id, status):
        task = next((t for t in self.db.get("scheduled") if t["id"] == task_id), None)
        if task is None:
            return
        due = parse_dt(task["due"])
        end_of_today = now().replace(hour=23, minute=59, second=59)
        if task.get("recurring", "One-Time") != "One-Time" and due > end_of_today:
            word = "done" if status == "completed" else "missed"
            if not messagebox.askyesno(
                    "Not due yet", f"“{task['name']}” isn't due until {due.strftime('%A %d %b')}.\n\n"
                                   f"Mark that occurrence as {word} already? It will move on to "
                                   f"{upcoming_dates(task, 1)[0].strftime('%a %d %b')}.", parent=self.app):
                return
        past_id = resolve_task(self.db, task_id, status)
        if past_id is None:
            return
        after = next((t for t in self.db.get("scheduled") if t["id"] == task_id), None)
        text = "Marked as done" if status == "completed" else "Marked as missed"
        if after:
            text += f" · next {parse_dt(after['due']).strftime('%a %d %b')}"
        self.app.toast(text, "success" if status == "completed" else "info",
                       undo=lambda: self.app.undo_past(past_id))
        self.app.refresh_badges()
        self.refresh()

    def _remove(self, task_id, name):
        if messagebox.askyesno("Remove task", f"Remove “{name}” without logging it to history?", parent=self.app):
            gone = remove_task(self.db, task_id)
            self.app.refresh_badges()
            self.refresh()
            if gone:
                self.app.toast(f"Removed “{name}”", "info", undo=lambda: self._restore(gone))

    def _restore(self, task):
        restore_task(self.db, task)
        self.app.toast(f"Restored “{task['name']}”", "success")
        self.app.refresh_badges()
        self.refresh()


def schedule_group(due: datetime, ref: datetime) -> str:
    if due < ref:
        return "Overdue"
    days = (due.date() - ref.date()).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    if days < 7:
        return "This week"
    if days < 14:
        return "Next week"
    return "Later"


# ─────────────────────────────────────────────────────────────── New task
class NewTaskPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.subtitle, _ = self.make_header("Schedule New")
        self.subtitle.configure(text="Your phone gets a push notification when it's time.")
        outer = scroll_area(self)
        outer.pack(fill="both", expand=True, padx=16, pady=(4, 16))
        form = card(outer)
        form.pack(fill="x", padx=12, pady=8)
        inner = ctk.CTkFrame(form, fg_color="transparent")
        inner.pack(fill="x", padx=28, pady=24)

        field_title(inner, "Task Name").pack(anchor="w")
        self.name = entry(inner, "e.g. Check the PC parts prices", width=520)
        self.name.pack(anchor="w", fill="x", pady=(6, 18))

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=(0, 18))
        date_col = ctk.CTkFrame(row, fg_color="transparent")
        date_col.pack(side="left", padx=(0, 40))
        field_title(date_col, "Date").pack(anchor="w")
        dates = ctk.CTkFrame(date_col, fg_color="transparent")
        dates.pack(anchor="w", pady=(6, 0))
        year_now = now().year
        self.day = self._cell(dates, "Day", [f"{d:02d}" for d in range(1, 32)], 76)
        self.month = self._cell(dates, "Month", [f"{m:02d}" for m in range(1, 13)], 76, lambda _: self._sync_days())
        self.year = self._cell(dates, "Year", [str(y) for y in range(year_now, year_now + 6)], 96, lambda _: self._sync_days())

        time_col = ctk.CTkFrame(row, fg_color="transparent")
        time_col.pack(side="left")
        field_title(time_col, "Time").pack(anchor="w")
        times = ctk.CTkFrame(time_col, fg_color="transparent")
        times.pack(anchor="w", pady=(6, 0))
        self.hour = self._cell(times, "Hour", [f"{h:02d}" for h in range(24)], 76)
        self.minute = self._cell(times, "Minute", [f"{m:02d}" for m in range(60)], 76)

        field_title(inner, "Repeat").pack(anchor="w")
        self.recurring = segmented(inner, RECURRENCES)
        self.recurring.pack(anchor="w", pady=(6, 18))

        field_title(inner, "Urgency").pack(anchor="w")
        self.urgency = segmented(inner, URGENCIES)
        self.urgency.pack(anchor="w", pady=(6, 18))

        field_title(inner, "Phone Reminder").pack(anchor="w")
        self.remind = segmented(inner, list(REMINDERS))
        self.remind.pack(anchor="w", pady=(6, 18))

        self.error = label(inner, "", FONTS.body_bold, P.ACCENT)
        self.error.pack(anchor="w")
        buttons = ctk.CTkFrame(inner, fg_color="transparent")
        buttons.pack(anchor="w", pady=(8, 0))
        accent_button(buttons, "Save Task", self.save, width=180, height=44,
                      font=ctk.CTkFont(font_family(), 15, "bold")).pack(side="left")
        ghost_button(buttons, "Reset", self.reset, width=100, height=44).pack(side="left", padx=10)
        self.reset()

    @staticmethod
    def _cell(parent, caption, values, width, command=None):
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.pack(side="left", padx=(0, 8))
        menu = option_menu(cell, values, width=width, command=command)
        menu.pack()
        label(cell, caption, FONTS.tiny, P.MUTED).pack(anchor="w", padx=4)
        return menu

    def _sync_days(self):
        days = calendar.monthrange(int(self.year.get()), int(self.month.get()))[1]
        values = [f"{d:02d}" for d in range(1, days + 1)]
        self.day.configure(values=values)
        if int(self.day.get()) > days:
            self.day.set(values[-1])

    def reset(self):
        start = (now() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        self.name.delete(0, "end")
        self.year.set(str(start.year))
        self.month.set(f"{start.month:02d}")
        self._sync_days()
        self.day.set(f"{start.day:02d}")
        self.hour.set(f"{start.hour:02d}")
        self.minute.set(f"{start.minute:02d}")
        self.recurring.set("One-Time")
        self.urgency.set("Medium")
        self.remind.set("At time")
        self.error.configure(text="")

    def save(self):
        name = self.name.get().strip()
        if not name:
            self.error.configure(text="Give the task a name first.")
            return
        try:
            due = datetime(int(self.year.get()), int(self.month.get()), int(self.day.get()),
                           int(self.hour.get()), int(self.minute.get()))
        except ValueError:
            self.error.configure(text="That date doesn't exist.")
            return
        rule = self.recurring.get() or "One-Time"
        ref = now()
        if due <= ref:
            if rule == "One-Time":
                self.error.configure(text="That time has already passed. Pick a future time.")
                return
            due = next_occurrence_after(due, rule, ref, due.day)
        task = make_task(name, due, self.urgency.get() or "Medium", rule, REMINDERS.get(self.remind.get(), 0))
        self.db.update(lambda data: data["scheduled"].append(task))
        self.app.toast(f"Saved · {due.strftime('%a %d %b, %H:%M')}", "success")
        self.reset()
        self.app.refresh_badges()
        self.app.show("scheduled")


# ─────────────────────────────────────────────────────────────── Past
class PastPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.subtitle, actions = self.make_header("Past Activities")
        ghost_button(actions, "Clear history", self._clear, width=130).pack(side="right")
        self.filter = segmented(actions, ["All", "Completed", "Missed"], command=lambda _: self.refresh())
        self.filter.set("All")
        self.filter.pack(side="right", padx=10)
        self.list = scroll_area(self)
        self.list.pack(fill="both", expand=True, padx=16, pady=(4, 16))

    def refresh(self):
        self.clear(self.list)
        past = self.db.get("past")
        done = sum(1 for p in past if p["status"] == "completed")
        missed = len(past) - done
        self.subtitle.configure(text=f"{done} completed  ·  {missed} missed" if past else "Your finished and missed tasks show up here.")
        mode = self.filter.get()
        rows = [p for p in past if mode == "All" or p["status"] == mode.lower()]
        rows.sort(key=lambda p: p["resolved_at"], reverse=True)
        if not rows:
            EmptyState(self.list, "↺", "No history yet" if not past else f"No {mode.lower()} tasks",
                       "Mark scheduled tasks as done or missed to build your history.").pack(fill="x")
            return
        today = now().date()
        current = None
        group = None
        undoable = undoable_past_ids(past)
        for rec in rows:
            day = datetime.strptime(rec["resolved_at"], TS_FMT).date()
            if day != current:
                current = day
                if day == today:
                    title = "Today"
                elif day == today - timedelta(days=1):
                    title = "Yesterday"
                else:
                    title = day.strftime("%A, %d %B %Y")
                label(self.list, title, FONTS.small_bold, P.MUTED).pack(anchor="w", padx=16, pady=(14, 4))
                group = card(self.list)
                group.pack(fill="x", padx=12, pady=(0, 4))
            self._row(group, rec, rec["id"] in undoable and not rec.get("auto"))

    def _row(self, parent, rec, can_undo=False):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=8)
        if can_undo:
            ghost_button(row, "↶  Undo", lambda pid=rec["id"]: self.app.undo_past(pid), width=86, height=30,
                         font=FONTS.small).pack(side="right", padx=(8, 0))
        completed = rec["status"] == "completed"
        badge = ctk.CTkLabel(
            row, text="✓" if completed else "✕", width=36, height=36, corner_radius=18,
            fg_color=P.SUCCESS_SOFT if completed else P.ACCENT_SOFT,
            text_color=P.SUCCESS if completed else P.ACCENT, font=FONTS.h3,
        )
        badge.pack(side="left", padx=(0, 14))
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True)
        label(text, rec["name"], FONTS.body_bold, anchor="w").pack(anchor="w")
        resolved = datetime.strptime(rec["resolved_at"], TS_FMT)
        how = "Completed" if completed else ("Missed (auto, never confirmed)" if rec.get("auto") else "Missed")
        label(text, f"{how} at {resolved.strftime('%H:%M')}  ·  was due {rec['due']}", FONTS.small, P.MUTED,
              anchor="w").pack(anchor="w")
        fg, fg_text = URGENCY_STYLE.get(rec.get("urgency", "Medium"), URGENCY_STYLE["Medium"])
        pill(row, rec.get("urgency", "Medium"), fg, fg_text).pack(side="right")
        if rec.get("recurring", "One-Time") != "One-Time":
            pill(row, f"↻ {rec['recurring']}", P.CARD_ALT, P.TEXT).pack(side="right", padx=6)

    def _clear(self):
        if not self.db.get("past"):
            return
        if messagebox.askyesno("Clear history", "Delete all past activities? This can't be undone.", parent=self.app):
            self.db.update(lambda data: data.__setitem__("past", []))
            self.refresh()


# ─────────────────────────────────────────────────────────────── Dashboard
class DashboardPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.subtitle, _ = self.make_header("Dashboard")
        body = scroll_area(self)
        body.pack(fill="both", expand=True, padx=16, pady=(4, 16))
        self.tiles = ctk.CTkFrame(body, fg_color="transparent")
        self.tiles.pack(fill="x", padx=4, pady=(4, 8))
        self.tile_values = {}
        for col, (key, caption) in enumerate((("upcoming", "Upcoming"), ("completed", "Completed"),
                                              ("missed", "Missed"), ("rate", "Completion rate"))):
            self.tiles.grid_columnconfigure(col, weight=1, uniform="tiles")
            tile = card(self.tiles)
            tile.grid(row=0, column=col, sticky="nsew", padx=8, pady=4)
            label(tile, caption, FONTS.small_bold, P.MUTED).pack(anchor="w", padx=20, pady=(16, 0))
            value = label(tile, "0", FONTS.number)
            value.pack(anchor="w", padx=20, pady=(0, 16))
            self.tile_values[key] = value
        charts = ctk.CTkFrame(body, fg_color="transparent")
        charts.pack(fill="x", padx=4, pady=4)
        charts.grid_columnconfigure(0, weight=2, uniform="charts")
        charts.grid_columnconfigure(1, weight=3, uniform="charts")
        self.donut = ChartPanel(charts, "Completed vs missed", height=300)
        self.donut.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.bars = ChartPanel(charts, "Last 7 days", height=300)
        self.bars.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        self.next_card = card(body)
        self.next_card.pack(fill="x", padx=12, pady=8)

    def refresh(self):
        past = self.db.get("past")
        scheduled = self.db.get("scheduled")
        done = sum(1 for p in past if p["status"] == "completed")
        missed = len(past) - done
        rate = f"{done / len(past) * 100:.0f}%" if past else "—"
        self.tile_values["upcoming"].configure(text=str(len(scheduled)))
        self.tile_values["completed"].configure(text=str(done), text_color=P.SUCCESS)
        self.tile_values["missed"].configure(text=str(missed), text_color=P.ACCENT)
        self.tile_values["rate"].configure(text=rate)
        self.subtitle.configure(text="How you're keeping up." if past else "Stats appear once tasks are done or missed.")
        self.donut.draw(lambda fig, c: self._paint_donut(fig, c, done, missed))
        self.bars.draw(lambda fig, c: self._paint_bars(fig, c, past))
        self._paint_next(scheduled)

    def on_theme_change(self):
        if self.app.current == "dashboard":
            self.refresh()

    @staticmethod
    def _paint_donut(fig, c, done, missed):
        ax = fig.add_subplot(111)
        ax.set_facecolor(c["bg"])
        total = done + missed
        if total == 0:
            ax.pie([1], colors=[c["empty"]], startangle=90, wedgeprops=dict(width=0.28, edgecolor=c["bg"]))
            ax.text(0, 0.05, "No Data Yet", ha="center", va="center", color=c["muted"], fontsize=13, fontweight="bold")
            ax.text(0, -0.18, "finish a task to start", ha="center", va="center", color=c["muted"], fontsize=9)
        else:
            ax.pie([done, missed], colors=[c["success"], c["accent"]], startangle=90, counterclock=False,
                   wedgeprops=dict(width=0.28, edgecolor=c["bg"], linewidth=3))
            ax.text(0, 0.06, f"{done / total * 100:.0f}%", ha="center", va="center", color=c["text"], fontsize=24, fontweight="bold")
            ax.text(0, -0.2, "completed", ha="center", va="center", color=c["muted"], fontsize=10)
            ax.legend([f"Completed  {done}", f"Missed  {missed}"], loc="lower center", bbox_to_anchor=(0.5, -0.12),
                      ncol=2, frameon=False, labelcolor=c["text"], fontsize=9, handlelength=1, handletextpad=0.5)
        ax.set_aspect("equal")
        fig.subplots_adjust(left=0.02, right=0.98, top=0.98, bottom=0.08)

    @staticmethod
    def _paint_bars(fig, c, past):
        ax = fig.add_subplot(111)
        ax.set_facecolor(c["bg"])
        today = now().date()
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        done = {d: 0 for d in days}
        missed = {d: 0 for d in days}
        for rec in past:
            d = datetime.strptime(rec["resolved_at"], TS_FMT).date()
            if d in done:
                (done if rec["status"] == "completed" else missed)[d] += 1
        xs = range(len(days))
        dv = [done[d] for d in days]
        mv = [missed[d] for d in days]
        ax.bar(xs, dv, width=0.55, color=c["success"], label="Completed")
        ax.bar(xs, mv, width=0.55, bottom=dv, color=c["accent"], label="Missed")
        ax.set_xticks(list(xs), [("Today" if d == today else d.strftime("%a")) for d in days])
        top = max([a + b for a, b in zip(dv, mv)] + [0])
        if top == 0:
            ax.set_ylim(0, 4)
            ax.text(3, 2, "No activity this week", ha="center", va="center", color=c["muted"], fontsize=12)
        else:
            ax.set_ylim(0, top + 1)
            ax.legend(frameon=False, labelcolor=c["text"], fontsize=9, loc="upper left")
        ax.yaxis.get_major_locator().set_params(integer=True)
        for spine in ("top", "right", "left"):
            ax.spines[spine].set_visible(False)
        ax.spines["bottom"].set_color(c["grid"])
        ax.tick_params(colors=c["muted"], labelsize=9, length=0)
        ax.grid(axis="y", color=c["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        fig.subplots_adjust(left=0.07, right=0.98, top=0.95, bottom=0.12)

    def _paint_next(self, scheduled):
        self.clear(self.next_card)
        inner = ctk.CTkFrame(self.next_card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=16)
        label(inner, "Next up", FONTS.small_bold, P.MUTED).pack(anchor="w")
        upcoming = sorted(scheduled, key=lambda t: t["due"])
        if not upcoming:
            label(inner, "Nothing scheduled.", FONTS.h3).pack(anchor="w", pady=(2, 0))
            return
        task = upcoming[0]
        due = parse_dt(task["due"])
        label(inner, task["name"], FONTS.h3, anchor="w").pack(anchor="w", pady=(2, 0))
        label(inner, f"{due.strftime('%A %d %B, %H:%M')}  ·  {humanize_until(due, now())}", FONTS.body, P.MUTED).pack(anchor="w")


# ─────────────────────────────────────────────────────────────── Price Flash
STORE_STYLE = {
    "amazon": (P.WARN_SOFT, P.WARN),
    "trendyol": (P.ACCENT_SOFT, P.ACCENT),
    "newegg": (P.INFO_SOFT, P.INFO),
    "cazasouq": (P.SUCCESS_SOFT, P.SUCCESS),
    "infiniarc": (P.CARD_ALT, P.TEXT),
    "aliexpress": (P.ROSE_SOFT, P.ROSE),
}


def store_pill(master, item_or_key):
    key = item_or_key.get("store", "other") if isinstance(item_or_key, dict) else item_or_key
    fg, text = STORE_STYLE.get(key, (P.CARD_ALT, P.MUTED))
    return pill(master, store_label(item_or_key), fg, text)


def short_date(day: str) -> str:
    try:
        return datetime.strptime(day[:10], "%Y-%m-%d").strftime("%d %b")
    except (ValueError, TypeError):
        return ""


class PriceFlashPage(Page):
    BEST_COLS = (("Part", 0), ("Best now (SAR)", 130), ("Shop", 130), ("Lowest seen", 170), ("Highest seen", 140))
    LIST_COLS = (("Shop", 110), ("Listing", 0), ("Price (SAR)", 140), ("vs last", 80), ("Low · High", 150),
                 ("Status", 140), ("", 60))

    def __init__(self, master, app):
        super().__init__(master, app)
        self.subtitle, actions = self.make_header("Price Flash")
        self.check_btn = accent_button(actions, "⟳  Check now", self.check_now, width=140)
        self.check_btn.pack(side="right")
        ghost_button(actions, "☎  Send summary", self.send_summary, width=150).pack(side="right", padx=10)
        ghost_button(actions, "+  Add listing", lambda: ItemDialog(self.app, None, self._after_edit), width=130).pack(side="right")

        self.progress_row = ctk.CTkFrame(self, fg_color="transparent", height=24)
        self.progress_row.pack(fill="x", padx=30, pady=(0, 4))
        self.progress_label = label(self.progress_row, "", FONTS.small, P.MUTED, height=22)
        self.progress_label.pack(side="left", padx=(0, 12))
        self.progress = ctk.CTkProgressBar(self.progress_row, mode="indeterminate", width=220, height=6,
                                           progress_color=P.ACCENT, fg_color=P.BORDER)

        self.body = scroll_area(self)
        self.body.pack(fill="both", expand=True, padx=16, pady=(4, 16))
        label(self.body, "Best prices", FONTS.h2).pack(anchor="w", padx=16, pady=(4, 0))
        label(self.body, "The cheapest shop for each part right now, in SAR, including the shipping and fees you set.",
              FONTS.small, P.MUTED).pack(anchor="w", padx=16, pady=(0, 6))
        self.best_box = ctk.CTkFrame(self.body, fg_color="transparent")
        self.best_box.pack(fill="x", padx=4)
        label(self.body, "Builds", FONTS.h2).pack(anchor="w", padx=16, pady=(18, 6))
        self.combo_row = ctk.CTkFrame(self.body, fg_color="transparent")
        self.combo_row.pack(fill="x", padx=4)

        head = ctk.CTkFrame(self.body, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(18, 6))
        label(head, "All listings", FONTS.h2).pack(side="left")
        self.shop_filter = option_menu(head, ["All shops"] + [s["label"] for s in STORES.values()], width=150,
                                       command=lambda _: self._render_listings(self.db.get("price_flash")))
        self.shop_filter.set("All shops")
        self.shop_filter.pack(side="right")
        self.list_box = ctk.CTkFrame(self.body, fg_color="transparent")
        self.list_box.pack(fill="x", padx=4)

        self.chart = ChartPanel(self.body, "Build totals over time (SAR)", height=280)
        self.chart.pack(fill="x", padx=12, pady=(18, 8))
        self.settings_card = card(self.body)
        self.settings_card.pack(fill="x", padx=12, pady=(8, 8))
        self._build_settings(self.settings_card)

    # ---- data refresh
    def refresh(self):
        pf = self.db.get("price_flash")
        self.refresh_subtitle_only()
        self._render_best(pf)
        self._render_combos(pf)
        self._render_listings(pf)
        self.chart.draw(lambda fig, c: self._paint_history(fig, c, pf))
        self.set_running(self.app.service.price_running)

    def on_theme_change(self):
        if self.app.current == "prices":
            self.chart.draw(lambda fig, c: self._paint_history(fig, c, self.db.get("price_flash")))

    def set_running(self, running: bool, text: str = ""):
        if running:
            if not self.progress.winfo_ismapped():
                self.progress.pack(side="left")
                self.progress.start()
            self.progress_label.configure(text=text or "Checking prices…", text_color=P.ACCENT)
            self.check_btn.configure(state="disabled", text="Checking…")
        else:
            self.progress.stop()
            self.progress.pack_forget()
            self.progress_label.configure(text=self._idle_status(), text_color=P.MUTED)
            self.check_btn.configure(state="normal", text="⟳  Check now")

    def _idle_status(self) -> str:
        report = self.db.get("price_flash").get("last_summary")
        if not report:
            if not self.db.get("price_flash").get("items"):
                return "Add product links and Almanac checks their prices every day."
            return "Not checked yet. Press Check now for live prices."
        listings = report.get("listings", [])
        read = sum(1 for it in listings if it["fresh"])
        when = datetime.strptime(report["time"], DT_FMT).strftime("%a %d %b, %H:%M")
        text = f"Last checked {when}  ·  read {read} of {len(listings)} listings"
        if read < len(listings):
            text += "  ·  the rest keep their last price (shop blocked or page changed)"
        return text

    def _grid(self, parent, cols):
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        for col, (_, width) in enumerate(cols):
            grid.grid_columnconfigure(col, weight=1 if width == 0 else 0, minsize=width)
        return grid

    # ---- best prices
    def _render_best(self, pf):
        self.clear(self.best_box)
        rates = pf.get("rates") or DEFAULT_RATES
        stats = part_stats(pf.get("items", []), rates)
        if not stats:
            EmptyState(self.best_box, "⚡", "No parts tracked yet",
                       "Paste a product link from Amazon.sa, Trendyol, Newegg, Cazasouq, Infiniarc or AliExpress. "
                       "Add the same part from several shops and Almanac shows you the cheapest one every day.",
                       "Add listing", lambda: ItemDialog(self.app, None, self._after_edit)).pack(fill="x")
            return
        box = card(self.best_box)
        box.pack(fill="x", padx=8, pady=6)
        grid = self._grid(box, self.BEST_COLS)
        grid.pack(fill="x", padx=18, pady=(12, 14))
        for col, (title, _) in enumerate(self.BEST_COLS):
            label(grid, title, FONTS.tiny, P.MUTED, anchor="w").grid(row=0, column=col, sticky="w", pady=(0, 2))
        row, current = 1, None
        for st in stats.values():
            if st["category"] != current:
                current = st["category"]
                label(grid, current.upper(), FONTS.small_bold, P.ACCENT, anchor="w").grid(
                    row=row, column=0, columnspan=5, sticky="w", pady=(10, 0))
                row += 1
            self._best_row(grid, row, st)
            row += 1

    def _best_row(self, grid, row, st):
        pad = dict(pady=5, sticky="w")
        name = ctk.CTkFrame(grid, fg_color="transparent")
        name.grid(row=row, column=0, **pad)
        label(name, st["part"], FONTS.body_bold, anchor="w", justify="left", wraplength=250).pack(anchor="w")
        n = len(st["listings"])
        label(name, f"{n} listing{'s' if n != 1 else ''}", FONTS.tiny, P.MUTED, anchor="w").pack(anchor="w")
        best, price = st["best"], st["best_price"]
        cell = ctk.CTkFrame(grid, fg_color="transparent")
        cell.grid(row=row, column=1, **pad)
        if price is None:
            label(cell, "No price", FONTS.body_bold, P.MUTED, anchor="w").pack(anchor="w")
        else:
            label(cell, fmt_money(price), FONTS.h3, anchor="w").pack(anchor="w")
            moved = st["low"] and st["high"] and st["high"]["price"] - st["low"]["price"] >= 0.5
            if moved and price <= st["low"]["price"] + 0.5:
                label(cell, "▼ lowest so far", FONTS.tiny, P.SUCCESS, anchor="w").pack(anchor="w")
            elif shipping_unknown(best):
                label(cell, "+ shipping not set", FONTS.tiny, P.WARN, anchor="w").pack(anchor="w")
        shop = ctk.CTkFrame(grid, fg_color="transparent")
        shop.grid(row=row, column=2, **pad)
        if best is not None:
            pl = store_pill(shop, best)
            pl.configure(cursor="hand2")
            pl.pack(anchor="w")
            pl.bind("<Button-1>", lambda _e, url=best["url"]: webbrowser.open(url))
            if best.get("variant"):
                label(shop, best["variant"], FONTS.tiny, P.MUTED, anchor="w").pack(anchor="w")
        for col, key in ((3, "low"), (4, "high")):
            point = st[key]
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=row, column=col, **pad)
            if not point:
                label(cell, "—", FONTS.body, P.MUTED).pack(anchor="w")
                continue
            label(cell, f"{fmt_money(point['price'])}", FONTS.body_bold,
                  P.SUCCESS if key == "low" else P.TEXT, anchor="w").pack(anchor="w")
            label(cell, f"{point['store']} · {short_date(point['date'])}", FONTS.tiny, P.MUTED, anchor="w").pack(anchor="w")

    # ---- builds
    def _render_combos(self, pf):
        self.clear(self.combo_row)
        rates = pf.get("rates") or DEFAULT_RATES
        combos = pf.get("combos", [])
        cols = max(1, min(3, len(combos) + 1))
        for col in range(3):
            self.combo_row.grid_columnconfigure(col, weight=1 if col < cols else 0, uniform="combo" if col < cols else "")
        for index, combo in enumerate(combos):
            calc = compute_combo(combo, pf["items"], rates)
            box = card(self.combo_row)
            box.grid(row=index // 3, column=index % 3, sticky="nsew", padx=8, pady=6)
            top = ctk.CTkFrame(box, fg_color="transparent")
            top.pack(fill="x", padx=18, pady=(14, 0))
            label(top, combo["name"], FONTS.h3).pack(side="left")
            ctk.CTkButton(top, text="Edit", width=46, height=24, fg_color="transparent", hover_color=P.CARD_ALT,
                          text_color=P.MUTED, font=FONTS.small,
                          command=lambda cb=combo: ComboDialog(self.app, cb, self._after_edit)).pack(side="right")
            total = calc["total"]
            label(box, f"SAR {fmt_money(total)}" if total is not None else "Incomplete", FONTS.number_md
                  ).pack(anchor="w", padx=18, pady=(4, 0))
            meta = ctk.CTkFrame(box, fg_color="transparent")
            meta.pack(anchor="w", padx=18, pady=(4, 0))
            base = combo.get("baseline_total")
            if total is not None and base:
                delta = total - base
                fg = P.SUCCESS_SOFT if delta < 0 else (P.ACCENT_SOFT if delta > 0 else P.CARD_ALT)
                pill(meta, f"{fmt_delta(delta)} vs start", fg, delta_color(delta)).pack(side="left", padx=(0, 6))
            if combo.get("threshold"):
                hit = total is not None and total <= combo["threshold"]
                pill(meta, f"alert ≤ {fmt_money(combo['threshold'])}", P.SUCCESS_SOFT if hit else P.CARD_ALT,
                     P.SUCCESS if hit else P.MUTED).pack(side="left")
            parts = "\n".join(f"{p['part']} · {p['store']}" for p in calc["picks"])
            if calc["missing"]:
                parts += ("\n" if parts else "") + "no price for " + ", ".join(calc["missing"])
            label(box, parts, FONTS.small, P.MUTED, wraplength=250, justify="left", anchor="w").pack(anchor="w", padx=18, pady=(8, 14))
        add = card(self.combo_row, fg_color="transparent", border_color=P.BORDER)
        idx = len(combos)
        add.grid(row=idx // 3, column=idx % 3, sticky="nsew", padx=8, pady=6)
        ghost_button(add, "+  New build", lambda: ComboDialog(self.app, None, self._after_edit), width=150,
                     border_width=0).pack(expand=True, padx=18, pady=40)

    # ---- all listings
    def _render_listings(self, pf):
        self.clear(self.list_box)
        rates = pf.get("rates") or DEFAULT_RATES
        wanted = self.shop_filter.get()
        shown = 0
        for st in part_stats(pf.get("items", []), rates).values():
            listings = [it for it in st["listings"] if wanted == "All shops" or store_label(it) == wanted]
            if not listings:
                continue
            shown += 1
            box = card(self.list_box)
            box.pack(fill="x", padx=8, pady=6)
            top = ctk.CTkFrame(box, fg_color="transparent")
            top.pack(fill="x", padx=18, pady=(12, 0))
            label(top, st["part"], FONTS.h3).pack(side="left")
            pill(top, st["category"], P.CARD_ALT, P.MUTED).pack(side="left", padx=10)
            grid = self._grid(box, self.LIST_COLS)
            grid.pack(fill="x", padx=18, pady=(6, 12))
            for col, (title, _) in enumerate(self.LIST_COLS):
                label(grid, title, FONTS.tiny, P.MUTED, anchor="w").grid(row=0, column=col, sticky="w")
            for row, item in enumerate(listings, start=1):
                self._listing_row(grid, row, item, rates, item is st["best"])
        if not shown and pf.get("items"):
            label(self.list_box, f"No listings from {wanted} yet.", FONTS.body, P.MUTED).pack(anchor="w", padx=16, pady=8)

    def _listing_row(self, grid, row, item, rates, is_best):
        pad = dict(pady=5, sticky="w")
        store_pill(grid, item).grid(row=row, column=0, **pad)
        name_box = ctk.CTkFrame(grid, fg_color="transparent")
        name_box.grid(row=row, column=1, **pad)
        title = (item.get("variant") or "listing").capitalize() + "  ↗"
        link = label(name_box, title, FONTS.body_bold, anchor="w", cursor="hand2")
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda _e, url=item["url"]: webbrowser.open(url))
        sub = item.get("note") or item.get("name", "")
        label(name_box, sub if len(sub) <= 36 else sub[:35] + "…", FONTS.tiny,
              P.WARN if item.get("note") else P.MUTED, anchor="w").pack(anchor="w")

        price = item_price(item, rates)
        cell = ctk.CTkFrame(grid, fg_color="transparent")
        cell.grid(row=row, column=2, **pad)
        label(cell, fmt_money(price) + ("  ★" if is_best else ""), FONTS.body_bold,
              P.SUCCESS if is_best else P.TEXT, anchor="w").pack(anchor="w")
        currency = (item.get("currency") or "SAR").upper()
        extras = []
        if currency != "SAR" and item.get("raw_price") is not None:
            extras.append(f"{currency} {fmt_money(item['raw_price'])}")
        if item.get("shipping"):
            extras.append(f"+{fmt_money(item['shipping'])} ship")
        elif shipping_unknown(item):
            extras.append("ship ?")
        if item.get("fees_pct"):
            extras.append(f"+{item['fees_pct']:g}%")
        if extras:
            label(cell, "  ".join(extras), FONTS.tiny, P.WARN if shipping_unknown(item) else P.MUTED, anchor="w").pack(anchor="w")

        prev = landed(item, item.get("prev_raw"), rates)
        d_prev = None if price is None or prev is None else price - prev
        label(grid, fmt_delta(d_prev), FONTS.body_bold, delta_color(d_prev), anchor="w").grid(row=row, column=3, **pad)
        low, high = listing_low_high(item, rates)
        label(grid, f"{fmt_money(low)} · {fmt_money(high)}" if low is not None else "—", FONTS.small, P.MUTED,
              anchor="w").grid(row=row, column=4, **pad)

        status_box = ctk.CTkFrame(grid, fg_color="transparent")
        status_box.grid(row=row, column=5, **pad)
        status = item.get("status", "ok")
        checked = item.get("last_checked") or ""
        if item.get("skip"):
            pill(status_box, "Skipped", P.CARD_ALT, P.MUTED).pack(anchor="w")
        elif status == "manual":
            pill(status_box, "Manual", P.INFO_SOFT, P.INFO).pack(anchor="w")
            label(status_box, f"price set {short_date(checked)}" if checked else "type the price in Edit",
                  FONTS.tiny, P.MUTED, anchor="w").pack(anchor="w")
        elif status == "blocked":
            pill(status_box, "Check blocked", P.WARN_SOFT, P.WARN).pack(anchor="w")
            label(status_box, "keeping the last price", FONTS.tiny, P.MUTED, anchor="w").pack(anchor="w")
        elif status == "error":
            pill(status_box, "Couldn't read", P.ACCENT_SOFT, P.ACCENT).pack(anchor="w")
            err = item.get("error", "")
            label(status_box, err if len(err) <= 28 else err[:27] + "…", FONTS.tiny, P.MUTED, anchor="w").pack(anchor="w")
        elif status == "no_price":
            pill(status_box, "No price now", P.ACCENT_SOFT, P.ACCENT).pack(anchor="w")
        else:
            label(status_box, f"checked {short_date(checked)} {checked[11:16]}" if checked else "not checked yet",
                  FONTS.tiny, P.MUTED, anchor="w").pack(anchor="w")
        ctk.CTkButton(grid, text="Edit", width=56, height=28, corner_radius=8, fg_color=P.CARD_ALT,
                      hover_color=P.BORDER, text_color=P.TEXT, font=FONTS.small,
                      command=lambda it=item: ItemDialog(self.app, it, self._after_edit)).grid(row=row, column=6, sticky="e", pady=5)

    @staticmethod
    def _paint_history(fig, c, pf):
        ax = fig.add_subplot(111)
        ax.set_facecolor(c["bg"])
        history = pf.get("combo_history", {})
        days = sorted(history)
        palette = [c["accent"], c["info"], c["success"], c["warn"], c["text"]]
        drawn = 0
        for index, combo in enumerate(pf.get("combos", [])):
            points = [(datetime.strptime(d, "%Y-%m-%d"), history[d][combo["id"]]) for d in days if combo["id"] in history[d]]
            if not points:
                continue
            color = palette[index % len(palette)]
            xs, ys = zip(*points)
            ax.plot(xs, ys, marker="o", markersize=4, linewidth=2.2, color=color, label=combo["name"])
            if combo.get("threshold"):
                ax.axhline(combo["threshold"], color=color, linewidth=1, linestyle=(0, (4, 4)), alpha=0.6)
            drawn += 1
        if drawn == 0:
            ax.text(0.5, 0.5, "No history yet", transform=ax.transAxes, ha="center", va="center", color=c["muted"], fontsize=12)
            ax.set_xticks([])
            ax.set_yticks([])
        else:
            if len(days) <= 2:
                ax.text(0.5, 0.06, "The line fills in with each daily check  ·  dashed = alert target",
                        transform=ax.transAxes, ha="center", color=c["muted"], fontsize=9)
            ax.legend(frameon=False, labelcolor=c["text"], fontsize=9, loc="lower left",
                      bbox_to_anchor=(0, 1.0), ncol=min(4, drawn), borderaxespad=0.2)
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _p: f"{v:,.0f}"))
            day_points = sorted({datetime.strptime(d, "%Y-%m-%d") for d in days})
            if len(day_points) <= 12:
                ax.set_xticks(day_points)
            else:
                ax.xaxis.set_major_locator(matplotlib.dates.AutoDateLocator(maxticks=10))
            ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d %b"))
            ax.margins(x=0.08, y=0.25)
        for spine in ("top", "right", "left"):
            ax.spines[spine].set_visible(False)
        ax.spines["bottom"].set_color(c["grid"])
        ax.tick_params(colors=c["muted"], labelsize=9, length=0)
        ax.grid(axis="y", color=c["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        fig.subplots_adjust(left=0.08, right=0.98, top=0.88, bottom=0.12)

    # ---- schedule, alerts and currency rates
    RATE_CODES = ("USD", "BHD", "AED", "QAR", "OMR", "KWD")

    def _build_settings(self, box):
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=16)
        label(inner, "Schedule & alerts", FONTS.h3).pack(anchor="w")
        label(inner, "The daily check runs while the app is open or in the tray. If the PC was off at check time, "
                     "it runs as soon as the app starts.", FONTS.small, P.MUTED, wraplength=760, justify="left").pack(anchor="w", pady=(2, 12))
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        self.enabled_sw = switch(row, "Daily auto-check", command=self._save_settings)
        self.enabled_sw.pack(side="left", padx=(0, 24))
        label(row, "at", FONTS.body).pack(side="left", padx=(0, 6))
        self.hour = option_menu(row, [f"{h:02d}" for h in range(24)], width=72, command=lambda _: self._save_settings())
        self.hour.pack(side="left")
        label(row, ":", FONTS.body_bold).pack(side="left", padx=4)
        self.minute = option_menu(row, [f"{m:02d}" for m in range(0, 60, 5)], width=72, command=lambda _: self._save_settings())
        self.minute.pack(side="left", padx=(0, 24))
        label(row, "Alert when a listing drops", FONTS.body).pack(side="left", padx=(0, 6))
        self.pct = option_menu(row, ["3%", "5%", "7%", "10%", "15%", "20%"], width=80, command=lambda _: self._save_settings())
        self.pct.pack(side="left")
        label(row, "below its start price", FONTS.body).pack(side="left", padx=6)
        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.pack(fill="x", pady=(12, 0))
        self.summary_sw = switch(row2, "Send the daily price table to my phone", command=self._save_settings)
        self.summary_sw.pack(side="left")
        label(inner, "Alerts are separate notifications. They fire when a part hits its lowest price so far, a build drops "
                     "under its target, a listing drops by the percentage above, or a listing goes under its own target. "
                     "You won't get the same alert twice unless the price drops further.",
              FONTS.small, P.MUTED, wraplength=760, justify="left").pack(anchor="w", pady=(12, 0))

        label(inner, "Currency rates", FONTS.h3).pack(anchor="w", pady=(20, 0))
        label(inner, "SAR for 1 unit. USD, BHD, AED, QAR and OMR are pegged, so they rarely change; KWD moves a little.",
              FONTS.small, P.MUTED).pack(anchor="w", pady=(2, 8))
        rates_row = ctk.CTkFrame(inner, fg_color="transparent")
        rates_row.pack(fill="x")
        self.rate_entries = {}
        for code in self.RATE_CODES:
            label(rates_row, code, FONTS.small_bold).pack(side="left", padx=(0, 4))
            box_entry = entry(rates_row, "", width=74)
            box_entry.pack(side="left", padx=(0, 14))
            self.rate_entries[code] = box_entry
        ghost_button(rates_row, "Save rates", self._save_rates, width=100).pack(side="left")
        self.rates_status = label(inner, "", FONTS.small_bold, P.MUTED)
        self.rates_status.pack(anchor="w", pady=(6, 0))
        self._load_settings()

    def _load_settings(self):
        pf = self.db.get("price_flash")
        (self.enabled_sw.select if pf.get("enabled") else self.enabled_sw.deselect)()
        (self.summary_sw.select if pf.get("notify_summary", True) else self.summary_sw.deselect)()
        hh, mm = (pf.get("check_time") or "09:00").split(":")
        self.hour.set(hh)
        self.minute.set(f"{(int(mm) // 5) * 5:02d}")
        self.pct.set(f"{pf.get('drop_alert_pct', 5):g}%")
        rates = pf.get("rates") or DEFAULT_RATES
        for code, box_entry in self.rate_entries.items():
            box_entry.delete(0, "end")
            box_entry.insert(0, f"{rates.get(code, DEFAULT_RATES.get(code, 0)):g}")

    def _save_settings(self):
        check_time = f"{self.hour.get()}:{self.minute.get()}"
        enabled = bool(self.enabled_sw.get())
        notify = bool(self.summary_sw.get())
        pct = float(self.pct.get().rstrip("%"))

        def apply(data):
            pfd = data["price_flash"]
            if pfd.get("check_time") != check_time:
                # a new time today should still run today if it's later than now
                if now().strftime("%H:%M") < check_time and pfd.get("last_auto_run") == now().strftime("%Y-%m-%d"):
                    pfd["last_auto_run"] = None
            pfd["check_time"] = check_time
            pfd["enabled"] = enabled
            pfd["notify_summary"] = notify
            pfd["drop_alert_pct"] = pct

        self.db.update(apply)
        self.refresh_subtitle_only()

    def _save_rates(self):
        new_rates = {}
        for code, box_entry in self.rate_entries.items():
            try:
                value = float(box_entry.get().replace(",", "").strip())
                if value <= 0:
                    raise ValueError
            except ValueError:
                self.rates_status.configure(text=f"{code} needs a positive number.", text_color=P.ACCENT)
                return
            new_rates[code] = value
        self.db.update(lambda data: data["price_flash"].setdefault("rates", dict(DEFAULT_RATES)).update(new_rates))
        self.rates_status.configure(text="Rates saved. Prices below are recalculated.", text_color=P.SUCCESS)
        self.refresh()

    def refresh_subtitle_only(self):
        pf = self.db.get("price_flash")
        sched = f"auto-check daily at {pf.get('check_time')}" if pf.get("enabled") else "auto-check off"
        shops = len({it.get("store") for it in pf.get("items", [])})
        self.subtitle.configure(text=f"{len(pf.get('items', []))} listings across {shops} shops  ·  {sched}")
        if not self.app.service.price_running:
            self.progress_label.configure(text=self._idle_status())

    # ---- actions
    def check_now(self):
        if not self.app.service.start_price_check(auto=False):
            self.app.toast("A price check is already running", "info")

    def send_summary(self):
        report = self.db.get("price_flash").get("last_summary")
        if not report:
            self.app.toast("Run a check first; there's no summary yet", "info")
            return
        settings = self.db.get("settings")
        title, body = build_summary(report)

        def work():
            ok, err = send_ntfy(settings, title, body, priority=3, tags=["chart_with_upwards_trend"])
            self.app.events.put(("toast", "Summary sent to your phone" if ok else f"Push failed: {err[:60]}",
                                 "success" if ok else "error"))

        threading.Thread(target=work, daemon=True).start()

    def _after_edit(self):
        self.refresh()


class Dialog(ctk.CTkToplevel):
    def __init__(self, app: "App", title: str, width=560, height=640):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.configure(fg_color=P.BG)
        self.transient(app)
        app.update_idletasks()
        x = app.winfo_rootx() + max(0, (app.winfo_width() - width) // 2)
        y = app.winfo_rooty() + max(0, (app.winfo_height() - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(width, 420)
        if IS_WINDOWS and app.ico_path:
            self.after(260, lambda: self._safe(self.iconbitmap, app.ico_path))
        self.after(120, self._grab)

    @staticmethod
    def _safe(fn, *args):
        try:
            fn(*args)
        except tk.TclError:
            pass

    def _grab(self):
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            self.after(120, self._grab)


def _parse_optional_number(text: str, allow_zero: bool = False):
    text = (text or "").replace(",", "").strip()
    if not text:
        return None
    value = float(text)
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError
    return value


class ItemDialog(Dialog):
    def __init__(self, app, item: dict | None, on_done):
        super().__init__(app, "Edit listing" if item else "Track a new listing", width=600, height=800)
        self.item = item
        self.on_done = on_done
        pf = app.db.get("price_flash")
        self.rates = pf.get("rates") or DEFAULT_RATES
        self.known_parts = {}
        for it in pf.get("items", []):
            self.known_parts.setdefault(it["part"], it["category"])
        body = scroll_area(self)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        form = ctk.CTkFrame(body, fg_color="transparent")
        form.pack(fill="x", padx=18, pady=10)
        self.form = form

        def add_field(title, widget_factory, hint=None):
            field_title(form, title).pack(anchor="w", pady=(10, 0))
            widget = widget_factory()
            widget.pack(anchor="w", fill="x", pady=(6, 0))
            hint_label = None
            if hint:
                hint_label = label(form, hint, FONTS.tiny, P.MUTED, anchor="w", justify="left", wraplength=500)
                hint_label.pack(anchor="w")
            return widget, hint_label

        self.link, self.store_hint = add_field(
            "Product link (or an Amazon ASIN)", lambda: entry(form, "https://www.trendyol.sa/…  ·  https://www.newegg.com/p/…"),
            "Amazon.sa, Trendyol, Newegg, Cazasouq and Infiniarc are read automatically. "
            "AliExpress prices are typed in by hand.")
        self.link.bind("<FocusOut>", lambda _e: self._detect_store())
        self.link.bind("<Return>", lambda _e: self._detect_store())

        field_title(form, "Part").pack(anchor="w", pady=(10, 0))
        self.part = ctk.CTkComboBox(
            form, values=list(self.known_parts) or [""], height=38, corner_radius=10, fg_color=P.INPUT,
            border_color=P.BORDER, button_color=P.CARD_ALT, button_hover_color=P.BORDER, text_color=P.TEXT,
            dropdown_fg_color=P.CARD, dropdown_text_color=P.TEXT, dropdown_hover_color=P.CARD_ALT,
            font=FONTS.body, dropdown_font=FONTS.body, command=self._part_picked)
        self.part.pack(anchor="w", fill="x", pady=(6, 0))
        label(form, "Pick an existing part to compare shops, or type a new name.", FONTS.tiny, P.MUTED,
              anchor="w").pack(anchor="w")
        self.variant, _ = add_field("Variant (optional)", lambda: entry(form, "e.g. tray, boxed, white"))
        field_title(form, "Category").pack(anchor="w", pady=(10, 0))
        used = sorted({c for c in self.known_parts.values() if c and c not in CATEGORIES})
        self.category = ctk.CTkComboBox(
            form, values=CATEGORIES + used, width=220, height=38, corner_radius=10, fg_color=P.INPUT,
            border_color=P.BORDER, button_color=P.CARD_ALT, button_hover_color=P.BORDER, text_color=P.TEXT,
            dropdown_fg_color=P.CARD, dropdown_text_color=P.TEXT, dropdown_hover_color=P.CARD_ALT,
            font=FONTS.body, dropdown_font=FONTS.body)
        self.category.pack(anchor="w", pady=(6, 0))
        label(form, "Pick one or type your own.", FONTS.tiny, P.MUTED, anchor="w").pack(anchor="w")

        field_title(form, "Currency, shipping and fees").pack(anchor="w", pady=(14, 0))
        money = ctk.CTkFrame(form, fg_color="transparent")
        money.pack(anchor="w", fill="x", pady=(6, 0))
        codes = list(dict.fromkeys(["SAR", *self.rates]))

        def cell(caption_text, widget_factory, padx):
            box = ctk.CTkFrame(money, fg_color="transparent")
            box.pack(side="left", padx=padx, anchor="n")
            widget = widget_factory(box)
            widget.pack(anchor="w")
            caption = label(box, caption_text, FONTS.tiny, P.MUTED, anchor="w")
            caption.pack(anchor="w", padx=4)
            return widget, caption

        self.currency, _ = cell("Currency", lambda m: option_menu(m, codes, width=90, command=lambda _: self._update_units()), 0)
        self.shipping, self.ship_caption = cell("Shipping", lambda m: entry(m, "unknown", width=150), (12, 0))
        self.fees, _ = cell("Import VAT / fees %", lambda m: entry(m, "0", width=170), (12, 0))
        self.money_hint = label(form, "", FONTS.tiny, P.MUTED, anchor="w", justify="left", wraplength=500)
        self.money_hint.pack(anchor="w")

        self.manual, self.manual_hint = add_field("Price (type it in to set it by hand)", lambda: entry(form, ""),
                                                  "Only needed for AliExpress, or when a shop blocks the check.")
        self.alert_below, _ = add_field("Alert me under (SAR, optional)", lambda: entry(form, "e.g. 500"))
        self.note, _ = add_field("Note (optional)", lambda: entry(form, "Stock, arrival date, seller, coupon…"),
                                 "Price Flash only tracks price. Keep stock and delivery notes here.")
        self.skip = switch(form, "Leave out of best prices and builds (e.g. out of stock)")
        self.skip.pack(anchor="w", pady=(14, 0))
        self.error = label(form, "", FONTS.body_bold, P.ACCENT, wraplength=500, justify="left")
        self.error.pack(anchor="w", pady=(10, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=26, pady=(0, 18))
        accent_button(buttons, "Save", self.save, width=120).pack(side="right")
        ghost_button(buttons, "Cancel", self.destroy, width=100).pack(side="right", padx=10)
        if item:
            ghost_button(buttons, "Delete", self.delete, width=100, text_color=P.ACCENT, border_color=P.ACCENT,
                         hover_color=P.ACCENT_SOFT).pack(side="left")
            self.link.insert(0, item["url"])
            self.part.set(item["part"])
            self.variant.insert(0, item.get("variant", ""))
            self.category.set(item.get("category", "Other"))
            self.currency.set((item.get("currency") or "SAR").upper())
            if item.get("shipping") is not None:
                self.shipping.insert(0, f"{item['shipping']:g}")
            if item.get("fees_pct"):
                self.fees.insert(0, f"{item['fees_pct']:g}")
            if item.get("alert_below"):
                self.alert_below.insert(0, f"{float(item['alert_below']):.0f}")
            self.note.insert(0, item.get("note", ""))
            (self.skip.select if item.get("skip") else self.skip.deselect)()
            self._detected = item.get("store")
        else:
            self.part.set("")
            self.category.set("Other")
            self.currency.set("SAR")
            self._detected = None
        self._update_units()

    def _part_picked(self, value):
        if value in self.known_parts:
            self.category.set(self.known_parts[value])

    def _detect_store(self):
        url = normalize_product_url(self.link.get())
        key = store_key(url) if url else None
        if not key or key == self._detected:
            return
        self._detected = key
        info = store_info(key)
        self.currency.set(info["currency"])
        for widget, value in ((self.shipping, "0" if info["shipping"] == 0 else ""),
                              (self.fees, f"{info['fees']:g}" if info["fees"] else "")):
            if widget.get():  # deleting an empty entry would wipe its placeholder
                widget.delete(0, "end")
            if value:
                widget.insert(0, value)
        self._update_units()

    def _update_units(self):
        code = self.currency.get()
        key = self._detected or "other"
        tips = {
            "newegg": "Newegg ships from the US in USD. 15% covers Saudi import VAT; add customs duty if you're charged it. "
                      "Shipping to Saudi shows at checkout, so type it in once you see it.",
            "cazasouq": "Cazasouq is in Bahrain and prices in BHD. GCC shipping shows at checkout; type it in once you see it.",
            "aliexpress": "AliExpress shows prices only after its page loads in a browser, so type the price you see.",
        }
        self.ship_caption.configure(text=f"Shipping ({code})")
        self.money_hint.configure(text=tips.get(key, f"Shipping is in {code}. Leave it empty if you don't know it yet; "
                                                     f"0 means free delivery."))
        self.manual_hint.configure(text=f"In {code}. " + ("Required for AliExpress." if key == "aliexpress"
                                                          else "Only needed when a shop blocks the check."))

    def save(self):
        url = normalize_product_url(self.link.get())
        if not url or not urlparse(url).netloc or "." not in urlparse(url).netloc:
            self.error.configure(text="Paste a product link or an Amazon ASIN.")
            return
        part = self.part.get().strip()
        if not part:
            self.error.configure(text="Name the part so the same part at different shops can be compared.")
            return
        try:
            shipping = _parse_optional_number(self.shipping.get(), allow_zero=True)
            fees = _parse_optional_number(self.fees.get(), allow_zero=True) or 0.0
            manual = _parse_optional_number(self.manual.get())
            alert_below = _parse_optional_number(self.alert_below.get())
        except ValueError:
            self.error.configure(text="Prices, shipping and fees must be numbers (0 or more), like 1249.00")
            return
        key = store_key(url)
        currency = self.currency.get()
        if currency not in self.rates:
            self.error.configure(text=f"There's no rate for {currency}. Add it under Currency rates first.")
            return
        variant, note, skip = self.variant.get().strip(), self.note.get().strip(), bool(self.skip.get())
        category = self.category.get().strip()[:30] or "Other"
        stamp = now()
        item_id = self.item["id"] if self.item else new_id("item")
        is_new_part = part not in self.known_parts
        manual_store = store_info(key)["mode"] == "manual"

        def apply(data):
            pfd = data["price_flash"]
            items = pfd["items"]
            target = next((i for i in items if i["id"] == item_id), None)
            if target is None:
                target = {"id": item_id, "raw_price": None, "prev_raw": None, "baseline_raw": None, "status": "ok",
                          "error": "", "last_checked": None, "last_alert_price": None, "history": {},
                          "name": f"New listing ({store_label(key, url)})"}
                items.append(target)
            if target.get("url") != url or (target.get("currency") or currency) != currency:
                if target.get("currency") and target["currency"] != currency:
                    # numbers in the old currency mean nothing in the new one
                    target.update({"raw_price": None, "prev_raw": None, "baseline_raw": None, "history": {}})
                target["status"], target["error"] = "ok", ""
            target.update({
                "url": url, "store": key, "part": part, "variant": variant, "category": category,
                "currency": currency, "shipping": shipping, "fees_pct": fees, "alert_below": alert_below,
                "note": note, "skip": skip,
            })
            for other in items:  # a part lives in one category
                if other["part"] == part:
                    other["category"] = category
            if manual is not None:
                apply_check_result(target, {"status": "ok", "price": manual, "currency": currency}, stamp)
            if manual_store:
                target["status"], target["error"] = "manual", ""
            if is_new_part:
                # a brand-new part joins every build that already has that category
                for combo in pfd.get("combos", []):
                    if any(i["category"] == category and i["part"] in combo.get("parts", []) for i in items):
                        combo.setdefault("parts", []).append(part)

        self.app.db.update(apply)
        if manual is None and not self.item:
            msg = "Listing saved; type its price in Edit" if manual_store else "Listing saved; it gets a price on the next check"
        else:
            msg = "Listing saved"
        self.app.toast(msg, "success")
        self.destroy()
        self.on_done()

    def delete(self):
        if not messagebox.askyesno("Delete listing", f"Stop tracking {display_name(self.item)} at {store_label(self.item)}?",
                                   parent=self):
            return
        item_id = self.item["id"]

        def apply(data):
            pfd = data["price_flash"]
            pfd["items"] = [i for i in pfd["items"] if i["id"] != item_id]
            alive = {i["part"] for i in pfd["items"]}
            for combo in pfd.get("combos", []):
                combo["parts"] = [p for p in combo.get("parts", []) if p in alive]

        self.app.db.update(apply)
        self.destroy()
        self.on_done()


class ComboDialog(Dialog):
    def __init__(self, app, combo: dict | None, on_done):
        super().__init__(app, "Edit build" if combo else "New build", width=640, height=720)
        self.combo = combo
        self.on_done = on_done
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=26, pady=(18, 0))
        field_title(top, "Build name").pack(anchor="w")
        self.name = entry(top, "e.g. Gaming PC")
        self.name.pack(fill="x", pady=(6, 10))
        field_title(top, "Alert me when the total is at or under (SAR)").pack(anchor="w")
        self.threshold = entry(top, "e.g. 4000")
        self.threshold.pack(fill="x", pady=(6, 10))
        label(top, "Tick the parts to consider. For each category the build uses the cheapest ticked part, "
                   "priced at its cheapest shop.", FONTS.small, P.MUTED, wraplength=560, justify="left",
              anchor="w").pack(anchor="w")
        picks = scroll_area(self)
        picks.pack(fill="both", expand=True, padx=16, pady=8)
        self.vars = {}
        pf = app.db.get("price_flash")
        stats = part_stats(pf["items"], pf.get("rates") or DEFAULT_RATES)
        selected = set(combo.get("parts", [])) if combo else set()
        current = None
        for st in stats.values():
            if st["category"] != current:
                current = st["category"]
                label(picks, current, FONTS.small_bold, P.MUTED).pack(anchor="w", padx=10, pady=(10, 2))
            var = tk.BooleanVar(value=st["part"] in selected)
            where = f"SAR {fmt_money(st['best_price'])} at {store_label(st['best'])}" if st["best"] else "no price yet"
            ctk.CTkCheckBox(picks, text=f"{st['part']}   ·   {where}", variable=var, font=FONTS.body, text_color=P.TEXT,
                            fg_color=P.ACCENT, hover_color=P.ACCENT_HOVER, border_color=P.MUTED,
                            corner_radius=6).pack(anchor="w", padx=14, pady=3)
            self.vars[st["part"]] = var
        self.error = label(self, "", FONTS.body_bold, P.ACCENT)
        self.error.pack(anchor="w", padx=26)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=26, pady=(4, 18))
        accent_button(buttons, "Save", self.save, width=120).pack(side="right")
        ghost_button(buttons, "Cancel", self.destroy, width=100).pack(side="right", padx=10)
        if combo:
            ghost_button(buttons, "Delete", self.delete, width=100, text_color=P.ACCENT, border_color=P.ACCENT,
                         hover_color=P.ACCENT_SOFT).pack(side="left")
            self.name.insert(0, combo["name"])
            if combo.get("threshold"):
                self.threshold.insert(0, f"{float(combo['threshold']):.0f}")

    def save(self):
        name = self.name.get().strip()
        if not name:
            self.error.configure(text="Give the build a name.")
            return
        try:
            threshold = _parse_optional_number(self.threshold.get())
        except ValueError:
            self.error.configure(text="The alert total must be a positive number.")
            return
        parts = [part for part, var in self.vars.items() if var.get()]
        if not parts:
            self.error.configure(text="Tick at least one part.")
            return
        combo_id = self.combo["id"] if self.combo else new_id("combo")

        def apply(data):
            pfd = data["price_flash"]
            rates = pfd.get("rates") or DEFAULT_RATES
            combos = pfd.setdefault("combos", [])
            target = next((c for c in combos if c["id"] == combo_id), None)
            if target is None:
                target = {"id": combo_id, "last_alert_total": None}
                combos.append(target)
            parts_changed = set(target.get("parts", [])) != set(parts)
            target.update({"name": name, "parts": parts, "threshold": threshold})
            if parts_changed or target.get("baseline_total") is None:
                target["baseline_total"] = compute_combo(target, pfd["items"], rates, use_baseline=True)["total"]
                target["last_alert_total"] = None

        self.app.db.update(apply)
        self.destroy()
        self.on_done()

    def delete(self):
        if not messagebox.askyesno("Delete build", f"Delete “{self.combo['name']}”? Tracked parts stay.", parent=self):
            return
        cid = self.combo["id"]
        self.app.db.update(lambda data: data["price_flash"].__setitem__(
            "combos", [c for c in data["price_flash"]["combos"] if c["id"] != cid]))
        self.destroy()
        self.on_done()


# ─────────────────────────────────────────────────────────────── Patch notes
def render_release(parent, release: dict, badge: str | None = None, wrap: int = 740):
    """One release's notes (used by the Patch Notes page and the update window)."""
    top = ctk.CTkFrame(parent, fg_color="transparent")
    top.pack(fill="x")
    label(top, f"v{release['version']}", FONTS.h2).pack(side="left")
    if release.get("name"):
        label(top, f"   {release['name']}", FONTS.h3, P.ACCENT).pack(side="left")
    if badge:
        pill(top, badge, P.SUCCESS_SOFT, P.SUCCESS).pack(side="right")
    try:
        when = datetime.strptime(release.get("date", ""), "%Y-%m-%d").strftime("%d %b %Y")
        pill(top, when, P.CARD_ALT, P.MUTED).pack(side="right", padx=8)
    except ValueError:
        pass
    if release.get("summary"):
        label(parent, release["summary"], FONTS.body, P.MUTED, wraplength=wrap + 20, justify="left",
              anchor="w").pack(anchor="w", pady=(6, 0))
    for heading, bullets in release.get("sections") or []:
        label(parent, heading, FONTS.small_bold, P.TEXT).pack(anchor="w", pady=(12, 2))
        for text in bullets:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=1)
            label(row, "•", FONTS.body, P.ACCENT, width=16, anchor="n").pack(side="left", anchor="n")
            label(row, text, FONTS.body, P.TEXT, wraplength=wrap, justify="left", anchor="w").pack(
                side="left", anchor="w", padx=(6, 0))


class PatchNotesPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.subtitle, actions = self.make_header("Patch Notes")
        self.subtitle.configure(text=f"You're on v{APP_VERSION} · {APP_CODENAME}. Every update is logged here.")
        self.check_btn = ghost_button(actions, "⟳  Check for updates", app.check_for_updates, width=180)
        self.check_btn.pack(side="right")
        body = scroll_area(self)
        body.pack(fill="both", expand=True, padx=16, pady=(4, 16))
        for index, release in enumerate(PATCH_NOTES):
            box = card(body)
            box.pack(fill="x", padx=12, pady=8)
            inner = ctk.CTkFrame(box, fg_color="transparent")
            inner.pack(fill="x", padx=24, pady=(18, 18))
            render_release(inner, release, "Current" if index == 0 else None)


class UpdateDialog(Dialog):
    """What's new in the waiting update, and the buttons to install it, wait, or skip it."""

    def __init__(self, app, manifest: dict, status: str):
        super().__init__(app, "Update available", width=640, height=620)
        self.manifest, self.status = manifest, status
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=26, pady=(6, 18))
        body = scroll_area(self)
        body.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        inner = ctk.CTkFrame(body, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=10)
        label(inner, f"A new version of {APP_NAME} is ready. You're on v{APP_VERSION}.", FONTS.body_bold,
              anchor="w").pack(anchor="w", pady=(0, 12))
        render_release(inner, manifest, wrap=520)

        if status == "needs_full":
            note = ("This update needs a new Almanac.exe, so it can't install itself. Download it, close Almanac, "
                    "and put the new Almanac.exe in place of the old one. Your data stays where it is.")
        else:
            note = ("Your data is backed up first. If the new version doesn't start, Almanac goes back to "
                    "this one by itself.")
        self.status_label = label(footer, note, FONTS.small, P.MUTED, wraplength=580, justify="left", anchor="w")
        self.status_label.pack(anchor="w", pady=(0, 10))
        buttons = ctk.CTkFrame(footer, fg_color="transparent")
        buttons.pack(fill="x")
        if status == "needs_full":
            self.go_btn = accent_button(buttons, "Open download page", self._open_page, width=180)
        else:
            self.go_btn = accent_button(buttons, "Update now", self._install, width=150)
        self.go_btn.pack(side="right")
        self.later_btn = ghost_button(buttons, "Later", self.destroy, width=100)
        self.later_btn.pack(side="right", padx=10)
        self.skip_btn = ghost_button(buttons, "Skip this version", self._skip, width=150, border_width=0)
        self.skip_btn.pack(side="left")
        app.update_dialog = self

    def _open_page(self):
        webbrowser.open(self.manifest.get("full_url") or self.manifest.get("page_url") or
                        f"https://github.com/{UPDATE_REPO}/releases/latest")

    def _skip(self):
        version = self.manifest["version"]
        self.app.db.update(lambda d: d["settings"].__setitem__("skip_version", version))
        self.app.clear_update_offer()
        self.app.toast(f"Skipped v{version}. Check for updates on Patch Notes to get it later.", "info")
        self.destroy()

    def _install(self):
        for btn in (self.go_btn, self.later_btn, self.skip_btn):
            btn.configure(state="disabled")
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # don't close half-way
        self.show_progress("Starting…")
        app, manifest = self.app, self.manifest

        def work():
            try:
                backup = install_update(app.db, manifest, LAUNCHER,
                                        progress=lambda text: app.events.put(("update_progress", text)))
                app.events.put(("update_installed", backup))
            except UpdateError as exc:
                app.events.put(("update_failed", str(exc)))
            except Exception as exc:
                log.error("Update failed:\n%s", traceback.format_exc())
                app.events.put(("update_failed", f"Something went wrong ({exc}). Nothing was changed."))

        threading.Thread(target=work, daemon=True, name="almanac-install").start()

    def show_progress(self, text: str):
        self.status_label.configure(text=text, text_color=P.ACCENT)

    def show_failed(self, text: str):
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.status_label.configure(text=text, text_color=P.ACCENT)
        for btn in (self.go_btn, self.later_btn, self.skip_btn):
            btn.configure(state="normal")
        self.go_btn.configure(text="Try again")

    def show_installed(self):
        self.status_label.configure(text=f"Installed. Restarting {APP_NAME}…", text_color=P.SUCCESS)


# ─────────────────────────────────────────────────────────────── Settings
class SettingsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.subtitle, _ = self.make_header("Settings")
        self.subtitle.configure(text="Phone link, name, updates and background behaviour.")
        body = self.body = scroll_area(self)
        body.pack(fill="both", expand=True, padx=16, pady=(4, 16))

        phone = card(body)
        phone.pack(fill="x", padx=12, pady=8)
        p = ctk.CTkFrame(phone, fg_color="transparent")
        p.pack(fill="x", padx=24, pady=20)
        label(p, "☎  Link your phone", FONTS.h3).pack(anchor="w")
        steps = ("1.  Install the free ntfy app (Google Play / App Store).\n"
                 "2.  In the app tap  +  and subscribe to the topic below (server: ntfy.sh).\n"
                 "3.  Press  Send test  and your phone should buzz within a few seconds.")
        label(p, steps, FONTS.body, P.TEXT, justify="left", anchor="w").pack(anchor="w", pady=(8, 12))
        field_title(p, "Topic").pack(anchor="w")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", pady=(6, 4))
        self.topic = entry(row, "your-private-topic", width=340)
        self.topic.pack(side="left")
        ghost_button(row, "Generate private topic", self._generate_topic, width=190).pack(side="left", padx=10)
        label(p, "Topics are public on ntfy.sh. Anyone who knows the name can read the notifications, so use something hard to guess.",
              FONTS.small, P.MUTED, wraplength=720, justify="left", anchor="w").pack(anchor="w", pady=(0, 10))
        field_title(p, "Server").pack(anchor="w")
        self.server = entry(p, "https://ntfy.sh", width=340)
        self.server.pack(anchor="w", pady=(6, 12))
        row2 = ctk.CTkFrame(p, fg_color="transparent")
        row2.pack(fill="x")
        self.notify_sw = switch(row2, "Phone notifications on", command=self._save_switches)
        self.notify_sw.pack(side="left")
        accent_button(row2, "Send test", self._send_test, width=120).pack(side="right")
        ghost_button(row2, "Save", self._save_text, width=90).pack(side="right", padx=10)
        self.phone_status = label(p, "", FONTS.small_bold, P.MUTED)
        self.phone_status.pack(anchor="w", pady=(8, 0))

        general = card(body)
        general.pack(fill="x", padx=12, pady=8)
        g = ctk.CTkFrame(general, fg_color="transparent")
        g.pack(fill="x", padx=24, pady=20)
        label(g, "General", FONTS.h3).pack(anchor="w")
        field_title(g, "Your name").pack(anchor="w", pady=(10, 0))
        name_row = ctk.CTkFrame(g, fg_color="transparent")
        name_row.pack(fill="x", pady=(6, 12))
        self.user_name = entry(name_row, "Your name", width=240)
        self.user_name.pack(side="left")
        ghost_button(name_row, "Save", self._save_text, width=90).pack(side="left", padx=10)
        self.tray_sw = switch(g, "Keep running in the system tray when the window is closed", command=self._save_switches)
        self.tray_sw.pack(anchor="w", pady=4)
        self.startup_sw = switch(g, "Start with Windows (hidden in the tray)", command=self._toggle_startup)
        self.startup_sw.pack(anchor="w", pady=4)
        if not app.tray.available:
            self.tray_sw.configure(state="disabled")
            label(g, "System tray isn't available here (install the pystray package).", FONTS.small, P.MUTED).pack(anchor="w")
        if not IS_WINDOWS:
            self.startup_sw.configure(state="disabled")
        label(g, f"Data file:  {DB_PATH}", FONTS.small, P.MUTED, anchor="w", wraplength=760, justify="left").pack(anchor="w", pady=(12, 0))
        ghost_button(g, "Open data folder", self._open_folder, width=160).pack(anchor="w", pady=(8, 0))
        label(g, f"{APP_NAME} v{APP_VERSION} ({APP_CODENAME})  ·  price engine: {'curl_cffi' if cffi_requests else 'requests'}",
              FONTS.tiny, P.MUTED).pack(anchor="w", pady=(12, 0))

        updates = card(body)
        updates.pack(fill="x", padx=12, pady=8)
        u = ctk.CTkFrame(updates, fg_color="transparent")
        u.pack(fill="x", padx=24, pady=20)
        label(u, "⬆  Updates", FONTS.h3).pack(anchor="w")
        self.update_info = label(u, "", FONTS.body, P.TEXT, anchor="w", justify="left", wraplength=720)
        self.update_info.pack(anchor="w", pady=(8, 8))
        self.auto_update_sw = switch(u, "Check for updates once a day", command=self._save_switches)
        self.auto_update_sw.pack(anchor="w", pady=4)
        urow = ctk.CTkFrame(u, fg_color="transparent")
        urow.pack(fill="x", pady=(10, 0))
        self.update_btn = accent_button(urow, "Check now", app.check_for_updates, width=130)
        self.update_btn.pack(side="left")
        self.rollback_btn = ghost_button(urow, "Go back", app.roll_back_update, width=170)
        self.update_status = label(u, "", FONTS.small_bold, P.MUTED, anchor="w", justify="left", wraplength=720)
        self.update_status.pack(anchor="w", pady=(8, 0))
        label(u, f"Before every update your data is copied to the backups folder ({BACKUPS_KEPT} copies are kept).",
              FONTS.small, P.MUTED, anchor="w").pack(anchor="w", pady=(4, 0))

    def refresh(self):
        settings = self.db.get("settings")
        for widget, key in ((self.topic, "ntfy_topic"), (self.server, "ntfy_server"), (self.user_name, "user_name")):
            widget.delete(0, "end")
            widget.insert(0, settings.get(key, ""))
        (self.notify_sw.select if settings.get("notifications_enabled", True) else self.notify_sw.deselect)()
        (self.tray_sw.select if settings.get("close_to_tray", True) else self.tray_sw.deselect)()
        path = startup_script_path()
        (self.startup_sw.select if path and os.path.exists(path) else self.startup_sw.deselect)()
        self.refresh_updates()

    def refresh_updates(self, status_text: str | None = None, color=P.MUTED):
        settings = self.db.get("settings")
        supported, reason = updates_supported()
        info = f"You're on v{APP_VERSION} · {APP_CODENAME}."
        if not supported:
            info += f"  {reason}"
        elif settings.get("last_update_check"):
            when = datetime.strptime(settings["last_update_check"], TS_FMT).strftime("%a %d %b, %H:%M")
            info += f"  Last checked {when}."
        offer = self.app.update_manifest
        if offer:
            info += f"  v{offer['version']} is ready to install."
        self.update_info.configure(text=info)
        (self.auto_update_sw.select if settings.get("check_updates", True) else self.auto_update_sw.deselect)()
        for widget in (self.auto_update_sw, self.update_btn):
            widget.configure(state="normal" if supported else "disabled")
        previous = LAUNCHER.previous_version() if LAUNCHER is not None else None
        if previous:
            self.rollback_btn.configure(text=f"Go back to v{previous}")
            self.rollback_btn.pack(side="left", padx=10)
        else:
            self.rollback_btn.pack_forget()
        if status_text is not None:
            self.update_status.configure(text=status_text, text_color=color)

    def _generate_topic(self):
        self.topic.delete(0, "end")
        self.topic.insert(0, new_topic())
        self.phone_status.configure(text="New topic generated. Press Save, then subscribe to it in the ntfy app.", text_color=P.WARN)

    def _save_text(self):
        topic = self.topic.get().strip()
        if topic and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
            self.phone_status.configure(text="Topics can only use letters, numbers, - and _.", text_color=P.ACCENT)
            return
        server = self.server.get().strip() or "https://ntfy.sh"
        name = self.user_name.get().strip()

        def apply(data):
            data["settings"].update({"ntfy_topic": topic, "ntfy_server": server, "user_name": name})

        self.db.update(apply)
        self.app.sidebar.update_greeting()
        self.phone_status.configure(text="Saved.", text_color=P.SUCCESS)

    def _save_switches(self):
        notify, tray = bool(self.notify_sw.get()), bool(self.tray_sw.get())
        auto = bool(self.auto_update_sw.get())
        self.db.update(lambda data: data["settings"].update({"notifications_enabled": notify, "close_to_tray": tray,
                                                             "check_updates": auto}))

    def _toggle_startup(self):
        try:
            set_start_with_windows(bool(self.startup_sw.get()))
            self.app.toast("Will start with Windows" if self.startup_sw.get() else "Won't start with Windows", "success")
        except OSError as exc:
            self.app.toast(f"Couldn't change start-up: {exc}", "error")
            self.refresh()

    def _send_test(self):
        self._save_text()
        settings = self.db.get("settings")
        self.phone_status.configure(text="Sending…", text_color=P.MUTED)

        def work():
            ok, err = send_ntfy(settings, f"{APP_NAME} is linked ✅",
                                "Your PC can reach this phone. Reminders and Price Flash alerts will arrive here.",
                                priority=3, tags=["white_check_mark"])
            self.app.events.put(("phone_test", ok, err))

        threading.Thread(target=work, daemon=True).start()

    def show_test_result(self, ok, err):
        if ok:
            self.phone_status.configure(text="Sent. Check your phone.", text_color=P.SUCCESS)
        else:
            self.phone_status.configure(text=f"Couldn't send: {err}", text_color=P.ACCENT)

    @staticmethod
    def _open_folder():
        if IS_WINDOWS:
            os.startfile(DATA_DIR)  # noqa: S606
        else:
            webbrowser.open("file://" + DATA_DIR)


# ════════════════════════════════════════════════════════════════════════════
#  Sidebar + App shell
# ════════════════════════════════════════════════════════════════════════════
NAV = (
    ("scheduled", "◷   Scheduled"),
    ("new", "+   Schedule New"),
    ("past", "↺   Past Activities"),
    ("dashboard", "◔   Dashboard"),
    ("prices", "⚡   Price Flash"),
    ("notes", "✎   Patch Notes"),
    ("settings", "⚙   Settings"),
)


class Sidebar(ctk.CTkFrame):
    def __init__(self, app: "App"):
        super().__init__(app, width=250, corner_radius=0, fg_color=P.SIDEBAR)
        self.app = app
        self.pack_propagate(False)
        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.pack(fill="x", padx=22, pady=(26, 0))
        if app.icon_image is not None:
            try:
                self._logo = ctk.CTkImage(light_image=app.icon_image, dark_image=app.icon_image, size=(28, 28))
                ctk.CTkLabel(brand, image=self._logo, text="").pack(side="left")
            except Exception:
                log.warning("Logo image unavailable:\n%s", traceback.format_exc())
        title_box = ctk.CTkFrame(brand, fg_color="transparent")
        title_box.pack(side="left", padx=(10, 0))
        label(title_box, APP_NAME, FONTS.small_bold, P.MUTED, anchor="w", height=16).pack(anchor="w")
        self.clock = label(title_box, "", FONTS.clock, P.TEXT, anchor="w", height=18)
        self.clock.pack(anchor="w")
        self._tick_clock()
        self.greeting = label(self, "", FONTS.h2, anchor="w", justify="left")
        self.greeting.pack(anchor="w", padx=22, pady=(22, 0))
        self.today = label(self, "", FONTS.small, P.MUTED, anchor="w")
        self.today.pack(anchor="w", padx=22, pady=(2, 22))
        self.buttons = {}
        for key, text in NAV:
            btn = ctk.CTkButton(
                self, text=text, anchor="w", height=42, corner_radius=10, font=FONTS.body,
                fg_color="transparent", hover_color=P.SIDEBAR_HOVER, text_color=P.TEXT,
                command=lambda k=key: app.show(k),
            )
            btn.pack(fill="x", padx=14, pady=3)
            self.buttons[key] = btn
        spacer = ctk.CTkFrame(self, fg_color="transparent")
        spacer.pack(fill="both", expand=True)
        self.phone = label(self, "", FONTS.tiny, P.MUTED, anchor="w", justify="left", wraplength=210)
        self.phone.pack(anchor="w", padx=22, pady=(0, 6))
        self.update_link = label(self, "", FONTS.small_bold, P.ACCENT, anchor="w", cursor="hand2")
        self.update_link.bind("<Button-1>", lambda _e: app.open_update_dialog())
        self.version = label(self, f"v{APP_VERSION} · {APP_CODENAME}", FONTS.tiny, P.MUTED, anchor="w", cursor="hand2")
        self.version.pack(anchor="w", padx=22, pady=(0, 10))
        self.version.bind("<Button-1>", lambda _e: app.show("notes"))
        self.theme_sw = switch(self, "Dark mode", command=self._toggle_theme)
        self.theme_sw.pack(anchor="w", padx=22, pady=(0, 24))
        if ctk.get_appearance_mode().lower() == "dark":
            self.theme_sw.select()
        self.update_greeting()

    def _tick_clock(self):
        stamp = now()
        self.clock.configure(text=stamp.strftime("%H:%M:%S"))
        self.after(1000 - stamp.microsecond // 1000 + 5, self._tick_clock)

    def update_greeting(self):
        settings = self.app.db.get("settings")
        name = (settings.get("user_name") or "").strip()
        self.greeting.configure(text=f"Welcome, {name}" if name else "Welcome")
        self.today.configure(text=now().strftime("%A, %d %B"))
        topic = settings.get("ntfy_topic")
        on = settings.get("notifications_enabled", True) and topic
        self.phone.configure(text=f"☎  Phone topic: {topic}" if on else "☎  Phone notifications off")

    def show_update(self, version: str | None):
        if version:
            self.update_link.configure(text=f"⬆  Update ready: v{version}")
            self.update_link.pack(anchor="w", padx=22, pady=(0, 4), before=self.version)
        else:
            self.update_link.pack_forget()

    def set_active(self, key):
        for name, btn in self.buttons.items():
            if name == key:
                btn.configure(fg_color=P.ACCENT, text_color=P.ON_ACCENT, hover_color=P.ACCENT_HOVER, font=FONTS.body_bold)
            else:
                btn.configure(fg_color="transparent", text_color=P.TEXT, hover_color=P.SIDEBAR_HOVER, font=FONTS.body)

    def set_badge(self, count: int):
        base = dict(NAV)["scheduled"]
        self.buttons["scheduled"].configure(text=f"{base}   ({count})" if count else base)

    def _toggle_theme(self):
        mode = "dark" if self.theme_sw.get() else "light"
        ctk.set_appearance_mode(mode)
        self.app.db.update(lambda data: data["settings"].__setitem__("theme", mode))
        self.app.after(60, self.app.on_theme_change)


class App(ctk.CTk):
    def __init__(self, db: Database, instance_socket=None, start_hidden=False, adopted_from=None):
        ctk.set_appearance_mode(db.get("settings").get("theme", "dark"))
        super().__init__()
        global FONTS
        FONTS = Fonts()
        self.db = db
        self.events: queue.Queue = queue.Queue()
        self.instance_socket = instance_socket
        self.adopted_from = adopted_from
        self.update_manifest = None  # a newer release waiting to be installed
        self.update_offer = None  # "available" or "needs_full"
        self.update_dialog = None
        self.title(APP_NAME)
        self.geometry("1260x820")
        self.minsize(1080, 700)
        self.configure(fg_color=P.BG)
        self.icon_image = make_icon_image(256) if Image is not None else None
        self.ico_path = None
        self._set_window_icon()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.tray = Tray(self)
        self.service = BackgroundService(db, self.events)
        self.sidebar = Sidebar(self)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.grid(row=0, column=1, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)
        page_classes = {
            "scheduled": ScheduledPage, "new": NewTaskPage, "past": PastPage,
            "dashboard": DashboardPage, "prices": PriceFlashPage, "notes": PatchNotesPage,
            "settings": SettingsPage,
        }
        self.pages = {}
        for key, cls in page_classes.items():
            page = cls(self.container, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        self.current = None
        self._toast = None
        self._toast_job = None

        if instance_socket is not None:
            listen_for_second_instance(instance_socket, self.events)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show("scheduled")
        self.refresh_badges()
        self.service.start()
        self.after(200, self._poll_events)
        self.after(60_000, self._minute_tick)
        self.after(1500, self._announce_update)
        self.after(8000, self._mark_healthy)
        if start_hidden:
            if self.tray.available:
                self.withdraw()
            else:
                self.iconify()

    def _announce_update(self):
        """First start on a new version: point at the patch notes once. Also reports a rollback."""
        note = LAUNCHER.take_message() if LAUNCHER is not None else None
        if note:
            failed_version = note.get("rolled_back_from")
            if note.get("rollback_failed_start"):
                self.db.update(lambda data: data["settings"].__setitem__("skip_version", failed_version))
                self.toast(f"v{failed_version} couldn't start, so Almanac went back to v{APP_VERSION}. "
                           "Your data is safe.", "error", action=("Settings", lambda: self.show("settings")))
                if self.state() == "withdrawn":
                    self.tray.notify(f"v{failed_version} couldn't start, so Almanac went back to v{APP_VERSION}.")
            else:
                self.toast(f"Back on v{APP_VERSION}. v{failed_version} won't be offered again.", "success")
            self.db.update(lambda data: data["settings"].__setitem__("seen_version", APP_VERSION))
            return
        if self.db.get("settings").get("seen_version") == APP_VERSION:
            return
        self.db.update(lambda data: data["settings"].__setitem__("seen_version", APP_VERSION))
        if self.adopted_from:
            text = "Welcome to Almanac. Everything came along; see Patch Notes for what's new."
        else:
            text = f"Updated to v{APP_VERSION} · {APP_CODENAME}. See Patch Notes for what's new."
        self.toast(text, "success", action=("Patch Notes", lambda: self.show("notes")))
        if self.state() == "withdrawn":
            self.tray.notify(f"Updated to v{APP_VERSION} · {APP_CODENAME}")

    def _mark_healthy(self):
        if LAUNCHER is not None:
            try:
                LAUNCHER.mark_healthy()
            except OSError:
                log.warning("Couldn't record a healthy start:\n%s", traceback.format_exc())

    # ---- updates
    def check_for_updates(self):
        supported, reason = updates_supported()
        if not supported:
            self.toast(reason, "error")
            return
        if self.service.start_update_check(manual=True):
            self.pages["settings"].refresh_updates("Checking…", P.MUTED)
            self.toast("Checking for updates…", "info")

    def open_update_dialog(self):
        if self.update_manifest is None:
            return
        if self.update_dialog is not None and self.update_dialog.winfo_exists():
            self.update_dialog.lift()
            return
        UpdateDialog(self, self.update_manifest, self.update_offer)

    def clear_update_offer(self):
        self.update_manifest = self.update_offer = None
        self.sidebar.show_update(None)
        self.pages["settings"].refresh_updates()

    def restart_after_update(self):
        try:
            LAUNCHER.restart("--after-update")
        except OSError as exc:
            log.error("Couldn't restart:\n%s", traceback.format_exc())
            self.toast(f"Installed. Please close and reopen Almanac to finish ({exc}).", "info")
            return
        self.quit_app()

    def roll_back_update(self):
        previous = LAUNCHER.previous_version() if LAUNCHER is not None else None
        if not previous:
            return
        if not messagebox.askyesno("Go back", f"Go back to v{previous}? Almanac will restart. Your data stays "
                                              f"as it is now, and v{APP_VERSION} won't be offered again.", parent=self):
            return
        backup_database(self.db, f"before-going-back-to-v{previous}")
        if not LAUNCHER.roll_back():
            self.toast("The previous version isn't there any more", "error")
            return
        self.db.update(lambda data: data["settings"].__setitem__("skip_version", APP_VERSION))
        LAUNCHER.restart("--rolled-back")
        self.quit_app()

    def _on_update_checked(self, status, manifest, manual):
        settings_page = self.pages["settings"]
        if status in ("available", "needs_full"):
            self.update_manifest, self.update_offer = manifest, status
            self.sidebar.show_update(manifest["version"])
            settings_page.refresh_updates(f"v{manifest['version']} is available.", P.SUCCESS)
            if manual:
                self._hide_toast()
                self.open_update_dialog()
            else:
                self.toast(f"{APP_NAME} v{manifest['version']} is ready to install", "info",
                           action=("See what's new", self.open_update_dialog))
                if self.state() == "withdrawn":
                    self.tray.notify(f"{APP_NAME} v{manifest['version']} is ready. Open Almanac to install it.")
        else:
            if status == "none":
                self.clear_update_offer()
            settings_page.refresh_updates("You're on the latest version." if manual else None, P.SUCCESS)
            if manual:
                self.toast(f"You're on the latest version (v{APP_VERSION})", "success")

    # ---- window plumbing
    def _set_window_icon(self):
        if self.icon_image is None:
            return
        try:
            if IS_WINDOWS:
                self.ico_path = os.path.join(DATA_DIR, "almanac.ico")
                if not os.path.exists(self.ico_path):
                    write_icon_file(self.ico_path)
                self.iconbitmap(self.ico_path)
            else:
                self._icon_photo = ImageTk.PhotoImage(make_icon_image(64))
                self.iconphoto(True, self._icon_photo)
        except Exception:
            log.warning("Couldn't set window icon:\n%s", traceback.format_exc())

    def show(self, key: str):
        self.current = key
        self.sidebar.set_active(key)
        page = self.pages[key]
        page.tkraise()
        page.on_show()

    def refresh_badges(self):
        self.sidebar.set_badge(len(self.db.get("scheduled")))

    def on_theme_change(self):
        for page in self.pages.values():
            page.on_theme_change()

    def toast(self, text: str, kind: str = "info", undo=None, action=None):
        """Bottom-right message. With undo=callable (or action=(text, callable)) it gets a button
        and stays up longer."""
        if undo is not None:
            action = ("↶  Undo", undo)
        colors = {"success": (P.SUCCESS, ("#FFFFFF", NAVY)), "error": (P.ACCENT, P.ON_ACCENT),
                  "info": (P.TEXT, P.BG)}
        bg, fg = colors.get(kind, colors["info"])
        if self._toast is not None:
            self._toast.destroy()
        self._toast = ctk.CTkFrame(self, fg_color=bg, corner_radius=10, height=40)
        ctk.CTkLabel(self._toast, text=f"   {text}", text_color=fg, font=FONTS.body_bold, height=40,
                     fg_color="transparent").pack(side="left", padx=(0, 10 if action else 12))
        if action is not None:
            action_text, action_fn = action

            def _do_action():
                self._hide_toast()
                action_fn()
            ctk.CTkButton(self._toast, text=action_text, width=84, height=28, corner_radius=8, font=FONTS.body_bold,
                          fg_color=fg, hover_color=P.CARD_ALT, text_color=bg, command=_do_action
                          ).pack(side="left", padx=(0, 8))
        self._toast.place(relx=0.985, rely=0.975, anchor="se")
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(9000 if action else 3800, self._hide_toast)

    def _hide_toast(self):
        if self._toast is not None:
            self._toast.destroy()
            self._toast = None

    def undo_past(self, past_id: str):
        task = undo_resolution(self.db, past_id)
        if task is None:
            self.toast("That one can't be undone any more", "error")
        else:
            self.toast(f"Undone · {task['name']} is due {parse_dt(task['due']).strftime('%a %d %b, %H:%M')}", "success")
        self.refresh_badges()
        if self.current in ("scheduled", "past", "dashboard"):
            self.pages[self.current].refresh()

    def _minute_tick(self):
        self.sidebar.update_greeting()
        if self.current in ("scheduled", "dashboard") and self.state() != "withdrawn":
            self.pages[self.current].refresh()
        self.after(60_000, self._minute_tick)

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                try:
                    self._handle(event)
                except Exception:
                    log.error("UI event %s failed:\n%s", event[0], traceback.format_exc())
        except queue.Empty:
            pass
        finally:
            self.after(200, self._poll_events)

    def _handle(self, event):
        kind = event[0]
        if kind == "tasks_changed":
            self.refresh_badges()
            if self.current in ("scheduled", "past", "dashboard"):
                self.pages[self.current].refresh()
        elif kind == "toast":
            self.toast(event[1], event[2] if len(event) > 2 else "info")
        elif kind == "price_started":
            self.pages["prices"].set_running(True)
        elif kind == "price_progress":
            self.pages["prices"].set_running(True, event[1])
        elif kind == "price_done":
            _, report, alerts, pushed = event
            failed = sum(1 for it in report["listings"] if it["status"] in ("blocked", "error"))
            msg = "Prices updated"
            if alerts:
                msg += f" · {len(alerts)} alert{'s' if len(alerts) != 1 else ''}"
            if failed:
                msg += f" · {failed} couldn't be read"
            self.toast(msg, "error" if report["listings"] and failed == len(report["listings"]) else "success")
            self.pages["prices"].set_running(False)
            if self.current == "prices":
                self.pages["prices"].refresh()
            if alerts and self.state() == "withdrawn":
                self.tray.notify(f"Price drop: {alerts[0]['line'][:80]}")
        elif kind == "price_error":
            self.pages["prices"].set_running(False)
            self.toast(f"Price check failed: {event[1][:70]}", "error")
        elif kind == "phone_test":
            self.pages["settings"].show_test_result(event[1], event[2])
        elif kind == "update_checked":
            self._on_update_checked(*event[1:])
        elif kind == "update_check_failed":
            self.pages["settings"].refresh_updates(f"Couldn't check: {event[1]}", P.ACCENT)
            self.toast(f"Couldn't check for updates: {event[1][:70]}", "error")
        elif kind == "update_progress":
            if self.update_dialog is not None and self.update_dialog.winfo_exists():
                self.update_dialog.show_progress(event[1])
        elif kind == "update_installed":
            if self.update_dialog is not None and self.update_dialog.winfo_exists():
                self.update_dialog.show_installed()
            self.after(1200, self.restart_after_update)
        elif kind == "update_failed":
            log.warning("Update failed: %s", event[1])
            if self.update_dialog is not None and self.update_dialog.winfo_exists():
                self.update_dialog.show_failed(event[1])
            else:
                self.toast(event[1][:90], "error")
        elif kind == "tray_check_prices":
            self.service.start_price_check(auto=False)
        elif kind == "show":
            self.deiconify()
            self.lift()
            self.focus_force()
            if self.current:
                self.pages[self.current].refresh()
        elif kind == "quit":
            self.quit_app()

    def on_close(self):
        settings = self.db.get("settings")
        if self.tray.available and settings.get("close_to_tray", True):
            self.withdraw()
            if not settings.get("tray_hint_shown"):
                self.tray.notify("Still running in the tray, so reminders and price checks keep working.")
                self.db.update(lambda data: data["settings"].__setitem__("tray_hint_shown", True))
        else:
            self.quit_app()

    def quit_app(self):
        self.service.stop()
        self.tray.stop()
        if self.instance_socket is not None:  # free the port now: a restarted Almanac is waiting for it
            for step in (lambda: self.instance_socket.shutdown(socket.SHUT_RDWR), self.instance_socket.close):
                try:
                    step()
                except OSError:
                    pass
        self.destroy()


# ════════════════════════════════════════════════════════════════════════════
def main(launcher=None):
    global LAUNCHER
    LAUNCHER = launcher
    if "--write-icon" in sys.argv:
        target = sys.argv[sys.argv.index("--write-icon") + 1]
        write_icon_file(target)
        print(f"Icon written to {target}")
        return
    if "--write-build-info" in sys.argv:
        target = sys.argv[sys.argv.index("--write-build-info") + 1]
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(f'"""Written by the build."""\nCORE_VERSION = "{APP_VERSION}"\nUPDATE_REPO = "{UPDATE_REPO}"\n')
        print(f"Build info written to {target}")
        return
    restarting = "--after-update" in sys.argv or "--rolled-back" in sys.argv
    instance = acquire_single_instance(wait_seconds=30 if restarting else 0)
    if instance is None:
        print(f"{APP_NAME} is already running. Brought the open window to the front.")
        return
    adopted = adopt_legacy_data()
    db = Database(DB_PATH)
    app = App(db, instance_socket=instance, start_hidden="--minimized" in sys.argv, adopted_from=adopted)
    app.mainloop()


if __name__ == "__main__":
    main()
