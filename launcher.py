#!/usr/bin/env python3
"""
Almanac launcher: this is what Almanac.exe runs.

The app itself is almanac_app.py. The .exe carries a copy of it, but once the updater has put a
newer almanac_app.py in the "core" folder next to the .exe, that one runs instead, so most updates
are a single small file rather than a whole new .exe.

Safety net: a freshly installed version is "pending" until it has been up for a few seconds. If it
crashes while starting (or never gets that far twice in a row), the launcher puts the previous
version back and starts that instead.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import traceback

LAUNCHER_VERSION = 1
CORE_FILE = "almanac_app.py"
PREVIOUS_FILE = "almanac_app.previous.py"
STATE_FILE = "state.json"
MAX_ATTEMPTS = 2  # starts allowed for a pending update before it is rolled back
VERSION_RE = re.compile(r'^APP_VERSION\s*=\s*"([^"]+)"', re.M)

try:  # written by the build (build_exe.bat / the release workflow)
    import build_info  # type: ignore

    BUNDLED_VERSION = build_info.CORE_VERSION
except Exception:  # running from source
    BUNDLED_VERSION = None


def version_tuple(text) -> tuple:
    try:
        return tuple(int(part) for part in str(text).strip().lstrip("vV").split("."))
    except (TypeError, ValueError):
        return (0,)


def read_version(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            match = VERSION_RE.search(fh.read(400_000))
        return match.group(1) if match else None
    except OSError:
        return None


def install_dir() -> str:
    if os.environ.get("ALMANAC_HOME"):
        return os.environ["ALMANAC_HOME"]
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _writable(folder: str) -> bool:
    try:
        probe = os.path.join(folder, ".almanac_write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def data_dir() -> str:
    """Same rule as the app: next to the .exe, or %APPDATA%\\Almanac if that folder is read-only."""
    base = install_dir()
    if _writable(base):
        return base
    fallback = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Almanac")
    os.makedirs(fallback, exist_ok=True)
    return fallback


class Launcher:
    """Handed to the app as main(launcher=...). The app's updater calls install(), mark_healthy(),
    roll_back() and restart(); everything about which file runs stays in here."""

    version = LAUNCHER_VERSION

    def __init__(self):
        self.frozen = bool(getattr(sys, "frozen", False))
        self.core_dir = os.path.join(data_dir(), "core")
        os.makedirs(self.core_dir, exist_ok=True)
        self.core_path = os.path.join(self.core_dir, CORE_FILE)
        self.previous_path = os.path.join(self.core_dir, PREVIOUS_FILE)
        self.state_path = os.path.join(self.core_dir, STATE_FILE)
        self.state = self._load_state()
        self.source = None  # "bundled" or "core" once chosen
        self.running_version = None

    # ---- state
    def _load_state(self) -> dict:
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_state(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.state, fh, indent=2)
        os.replace(tmp, self.state_path)

    def log(self, text: str):
        try:
            with open(os.path.join(self.core_dir, "launcher.log"), "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
        except OSError:
            pass

    # ---- which almanac_app.py runs
    def bundled_version(self) -> str | None:
        if BUNDLED_VERSION:
            return BUNDLED_VERSION
        return read_version(os.path.join(os.path.dirname(os.path.abspath(__file__)), CORE_FILE))

    def choose(self) -> str:
        core_version = read_version(self.core_path) if os.path.exists(self.core_path) else None
        bundled = self.bundled_version()
        if core_version and version_tuple(core_version) >= version_tuple(bundled or "0"):
            self.source, self.running_version = "core", core_version
            return self.source
        if os.path.exists(self.core_path):
            # A newer full download replaced the .exe: the old core file is stale.
            self.log(f"Removing stale core {core_version} (exe carries {bundled})")
            for path in (self.core_path, self.previous_path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self.state = {}
            self.save_state()
        self.source, self.running_version = "bundled", bundled
        return self.source

    def load(self):
        if self.source == "core":
            spec = importlib.util.spec_from_file_location("almanac_app", self.core_path)
            module = importlib.util.module_from_spec(spec)
            prior = sys.modules.get("almanac_app")
            sys.modules["almanac_app"] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:  # don't leave a half-loaded module behind
                if prior is None:
                    sys.modules.pop("almanac_app", None)
                else:
                    sys.modules["almanac_app"] = prior
                raise
            return module
        import almanac_app  # the copy inside the .exe (or the file next to this one)

        return almanac_app

    # ---- used by the app's updater
    def install(self, data: bytes, new_version: str, current_version: str):
        """Put a verified almanac_app.py in place. Takes effect on the next start."""
        tmp = self.core_path + ".download"
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if self.source == "core" and os.path.exists(self.core_path):
            os.replace(self.core_path, self.previous_path)
            previous_source = "core"
        else:
            if os.path.exists(self.previous_path):
                os.remove(self.previous_path)
            previous_source = "bundled"
        os.replace(tmp, self.core_path)
        self.state = {"pending": new_version, "attempts": 0, "previous_version": current_version,
                      "previous_source": previous_source, "installed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.save_state()
        self.log(f"Installed {new_version} (previous {current_version} from {previous_source})")

    def mark_healthy(self):
        """Called by the app once its window has been up for a few seconds."""
        if self.state.get("pending"):
            self.log(f"{self.state['pending']} started fine")
            self.state["current"] = self.state.pop("pending")
            self.state["attempts"] = 0
            self.save_state()

    def previous_version(self) -> str | None:
        """The version roll_back() would return to, if there is one."""
        src = self.state.get("previous_source")
        if src == "core" and os.path.exists(self.previous_path):
            return self.state.get("previous_version")
        if src == "bundled" and os.path.exists(self.core_path):
            return self.state.get("previous_version") or self.bundled_version()
        return None

    def roll_back(self, failed: bool = False) -> bool:
        target = self.previous_version()
        if target is None:
            return False
        from_version = self.state.get("pending") or self.state.get("current") or self.running_version
        if self.state.get("previous_source") == "core":
            os.replace(self.previous_path, self.core_path)
        else:
            os.remove(self.core_path)
        self.state = {"rolled_back_from": from_version, "rolled_back_to": target, "rollback_failed_start": failed}
        self.save_state()
        self.log(f"Rolled back from {from_version} to {target} ({'failed start' if failed else 'by hand'})")
        return True

    def take_message(self) -> dict | None:
        """One-time note for the app after a rollback, then forgotten."""
        if "rolled_back_from" not in self.state:
            return None
        note = {k: self.state.pop(k) for k in ("rolled_back_from", "rolled_back_to", "rollback_failed_start")
                if k in self.state}
        self.save_state()
        return note

    def restart_command(self, *flags) -> list:
        if self.frozen:
            return [sys.executable, *flags]
        return [sys.executable, os.path.abspath(__file__), *flags]

    def restart(self, *flags):
        """Start a new Almanac; the caller then quits. The new one waits for this one to close."""
        env = dict(os.environ)
        # A one-file .exe started by another one would otherwise reuse (and lose) the parent's unpacked files.
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(self.restart_command(*flags), env=env, close_fds=True, cwd=install_dir(), **kwargs)


def show_error(text: str):
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text, "Almanac", 0x10)
            return
        except Exception:
            pass
    sys.stderr.write(text + "\n")


def run() -> int:
    if not getattr(sys, "frozen", False):
        os.environ.setdefault("ALMANAC_HOME", install_dir())
    launcher = Launcher()
    pending = launcher.state.get("pending")
    if pending:
        launcher.state["attempts"] = int(launcher.state.get("attempts", 0)) + 1
        launcher.save_state()
        if launcher.state["attempts"] > MAX_ATTEMPTS and launcher.roll_back(failed=True):
            pending = None  # it never got going; the previous version is back
    source = launcher.choose()
    try:
        module = launcher.load()
        module.main(launcher=launcher)
        return 0
    except SystemExit:
        raise
    except BaseException:
        details = traceback.format_exc()
        launcher.log(f"Start-up failed ({source} {launcher.running_version}):\n{details}")
        if launcher.state.get("pending") and source == "core" and launcher.roll_back(failed=True):
            launcher.restart("--rolled-back")
            return 1
        show_error("Almanac couldn't start.\n\n"
                   f"Details were saved to {os.path.join(launcher.core_dir, 'launcher.log')}.\n\n"
                   + details[-1500:])
        return 1


def _bundle_hints():  # pragma: no cover - never called
    """Only here so PyInstaller packs these into Almanac.exe, which lets later versions of
    almanac_app.py use them without a new .exe."""
    import almanac_app  # noqa: F401
    import csv, sqlite3, zipfile, hashlib, shutil, tempfile, statistics, decimal, fractions  # noqa: F401,E401
    import difflib, textwrap, string, bisect, heapq, itertools, functools, operator  # noqa: F401,E401
    import email.utils, http.client, http.server, urllib.request, urllib.parse, html.parser  # noqa: F401,E401
    import xml.etree.ElementTree, zoneinfo, uuid, base64, hmac, ssl, platform, ctypes, locale  # noqa: F401,E401
    import concurrent.futures, asyncio, dataclasses, enum, typing, pathlib, glob, fnmatch, gzip  # noqa: F401,E401
    import tkinter.filedialog, tkinter.simpledialog, tkinter.colorchooser, tkinter.font  # noqa: F401,E401
    import PIL.ImageFont, PIL.ImageOps, PIL.ImageFilter  # noqa: F401,E401
    import matplotlib.pyplot, matplotlib.patches  # noqa: F401,E401


if __name__ == "__main__":
    sys.exit(run())
