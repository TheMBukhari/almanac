"""Updater + launcher tests against a local fake release server (no GUI, no internet)."""
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
HOME = tempfile.mkdtemp()
os.environ["ALMANAC_HOME"] = HOME
import almanac_app as app  # noqa: E402
import launcher as launcher_mod  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


SOURCE = open(os.path.join(ROOT, "almanac_app.py"), encoding="utf-8").read()


def fake_core(version: str, name: str = "Test", extra: str = "") -> bytes:
    text = re.sub(r'^APP_VERSION = "[^"]+"', f'APP_VERSION = "{version}"', SOURCE, count=1, flags=re.M)
    text = re.sub(r'^APP_CODENAME = "[^"]+"', f'APP_CODENAME = "{name}"', text, count=1, flags=re.M)
    entry = ('PATCH_NOTES = [\n    {"version": "%s", "name": "%s", "date": "2026-11-01", "summary": "Test release.",\n'
             '     "sections": [("New", ["Something new."])]},\n' % (version, name))
    text = text.replace("PATCH_NOTES = [\n", entry, 1)
    return (text + extra).encode("utf-8")


class Server:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=self.dir, **k)  # noqa: E731
        http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        os.environ["ALMANAC_MANIFEST_URL"] = f"{self.base}/latest.json"

    def publish(self, data: bytes, version: str, sha: str | None = None, min_launcher: int = 1):
        """Each release goes in its own folder: Windows won't let a file be replaced while it's being served."""
        self.count = getattr(self, "count", 0) + 1
        folder = os.path.join(self.dir, f"r{self.count}")
        os.makedirs(folder)
        url = f"{self.base}/r{self.count}"
        with open(os.path.join(folder, "almanac_app.py"), "wb") as fh:
            fh.write(data)
        manifest = {"version": version, "name": "Test", "date": "2026-11-01", "summary": "Test release.",
                    "sections": [["New", ["Something new."]]], "core_url": f"{url}/almanac_app.py",
                    "core_sha256": sha or hashlib.sha256(data).hexdigest(), "core_size": len(data),
                    "min_launcher": min_launcher, "page_url": f"{url}/page"}
        with open(os.path.join(folder, "latest.json"), "w") as fh:
            json.dump(manifest, fh)
        os.environ["ALMANAC_MANIFEST_URL"] = f"{url}/latest.json"
        return manifest


def fresh_launcher():
    shutil.rmtree(os.path.join(HOME, "core"), ignore_errors=True)
    lch = launcher_mod.Launcher()
    lch.choose()
    return lch


def test_manifest_and_status(srv):
    srv.publish(fake_core("1.13"), "1.13")
    m = app.fetch_manifest()
    settings = dict(app.DEFAULT_SETTINGS)
    check(m["version"] == "1.13", "manifest read from the release")
    check(app.update_status(m, settings, 1, manual=False) == "available", "1.13 offered to 1.12")
    check(app.update_status(m, {**settings, "skip_version": "1.13"}, 1, manual=False) == "skipped", "skipped version stays quiet")
    check(app.update_status(m, {**settings, "skip_version": "1.13"}, 1, manual=True) == "available", "manual check still offers it")
    check(app.update_status({**m, "min_launcher": 2}, settings, 1, manual=False) == "needs_full", "needs a new exe")
    check(app.update_status({**m, "version": "1.12"}, settings, 1, manual=True) == "none", "same version: nothing")
    check(app.update_status({**m, "version": "1.9"}, settings, 1, manual=True) == "none", "1.9 < 1.12 (numeric compare)")
    os.environ["ALMANAC_MANIFEST_URL"] = f"{srv.base}/nothing-published/latest.json"
    try:
        app.fetch_manifest()
        check(False, "missing release raises")
    except app.UpdateError as exc:
        check("No release" in str(exc), f"no release yet: {exc}")


def test_rejects_bad_downloads(srv):
    db = app.Database(os.path.join(HOME, app.DB_NAME))
    lch = fresh_launcher()
    good = fake_core("1.13")
    cases = [("checksum", srv.publish(good, "1.13", sha="0" * 64)),
             ("different version", srv.publish(fake_core("1.14"), "1.13")),
             ("not valid", srv.publish(b"def broken(:\n    APP_VERSION = '1.13'\n", "1.13"))]
    for what, manifest in cases:
        try:
            app.install_update(db, manifest, lch)
            check(False, f"{what}: should be rejected")
        except app.UpdateError as exc:
            check("Nothing was changed" in str(exc), f"{what} rejected: {exc}")
    check(not os.path.exists(lch.core_path) and not lch.state, "nothing installed, no state written")
    check(not os.path.exists(app.BACKUP_DIR) or not os.listdir(app.BACKUP_DIR), "no backup made for a rejected download")


def test_install_restart_rollback(srv):
    db = app.Database(os.path.join(HOME, app.DB_NAME))
    db.update(lambda d: d["scheduled"].append(app.make_task("Gym", app.now(), "High", "Weekly", 0)))
    lch = fresh_launcher()
    check(lch.source == "bundled" and lch.running_version == app.APP_VERSION, f"starts on bundled {lch.running_version}")

    manifest = srv.publish(fake_core("1.13", "Thirteen"), "1.13")
    steps = []
    backup = app.install_update(db, manifest, lch, progress=steps.append)
    check(steps == ["Downloading…", "Checking the download…", "Backing up your data…", "Installing…"], f"progress {steps}")
    check(json.load(open(backup))["scheduled"][0]["name"] == "Gym", "data backed up before installing")
    check(lch.state["pending"] == "1.13" and lch.state["previous_source"] == "bundled", "pending 1.13, previous = bundled")

    # "restart": a new launcher picks the downloaded file
    lch2 = launcher_mod.Launcher()
    check(lch2.choose() == "core" and lch2.running_version == "1.13", "next start runs the downloaded 1.13")
    real = sys.modules["almanac_app"]
    try:
        module = lch2.load()
        check(module.APP_VERSION == "1.13" and module.PATCH_NOTES[0]["name"] == "Thirteen", "downloaded file imports")
    finally:
        sys.modules["almanac_app"] = real
    lch2.mark_healthy()
    check(lch2.state.get("current") == "1.13" and "pending" not in lch2.state, "healthy start clears pending")
    check(lch2.previous_version() == app.APP_VERSION, f"can go back to {app.APP_VERSION}")

    # 1.13 -> 1.14 keeps 1.13 as the previous file
    m14 = srv.publish(fake_core("1.14"), "1.14")
    data14 = app.download_core(m14)
    lch2.install(data14, "1.14", "1.13")
    check(launcher_mod.read_version(lch2.previous_path) == "1.13" and lch2.state["previous_source"] == "core",
          "1.13 kept as previous")
    check(lch2.roll_back() and launcher_mod.read_version(lch2.core_path) == "1.13", "going back restores 1.13")
    note = lch2.take_message()
    check(note == {"rolled_back_from": "1.14", "rolled_back_to": "1.13", "rollback_failed_start": False}, f"note {note}")
    check(lch2.take_message() is None, "note shown once")
    check(lch2.previous_version() is None and not lch2.roll_back(), "nothing further to go back to")


def test_failed_start_rolls_back(srv):
    lch = fresh_launcher()
    bad = fake_core("1.13", extra="\nraise RuntimeError('broken release')\n")
    lch.install(bad, "1.13", app.APP_VERSION)
    restarts = []
    orig_restart, orig_main = launcher_mod.Launcher.restart, app.main
    launcher_mod.Launcher.restart = lambda self, *flags: restarts.append(flags)
    try:
        code = launcher_mod.run()
    finally:
        launcher_mod.Launcher.restart = orig_restart
    after = launcher_mod.Launcher()
    check(code == 1 and restarts == [("--rolled-back",)], f"crash on start -> rolled back and restarted {restarts}")
    check(not os.path.exists(after.core_path) and after.choose() == "bundled", "back on the bundled version")
    check(after.state.get("rolled_back_from") == "1.13" and after.state.get("rollback_failed_start"), "app will be told")
    check(sys.modules.get("almanac_app") is app, "broken module not left loaded")

    # a release that hangs or dies hard: after two starts without a healthy mark it's rolled back too
    lch = fresh_launcher()
    lch.install(fake_core("1.13"), "1.13", app.APP_VERSION)
    lch.state["attempts"] = 2
    lch.save_state()
    started = []
    app.main = lambda launcher=None: started.append((launcher.source, launcher.running_version))
    try:
        code = launcher_mod.run()
    finally:
        app.main = orig_main
    check(code == 0 and started == [("bundled", app.APP_VERSION)], f"third start runs the previous version {started}")
    check(launcher_mod.Launcher().state.get("rolled_back_from") == "1.13", "and says why")


def test_stale_core_and_exe_upgrade():
    lch = fresh_launcher()
    lch.install(fake_core("1.11"), "1.11", "1.10")  # an older core than the .exe carries
    lch2 = launcher_mod.Launcher()
    check(lch2.choose() == "bundled" and not os.path.exists(lch2.core_path) and lch2.state == {},
          "a newer full download wins over an older core file")


def test_release_tool():
    out = os.path.join(tempfile.mkdtemp(), "latest.json")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "release.py"), "manifest", "--repo", "someone/almanac",
                    "--tag", f"v{app.APP_VERSION}", "--out", out], check=True, capture_output=True)
    m = json.load(open(out))
    data = open(os.path.join(ROOT, "almanac_app.py"), "rb").read()
    check(m["version"] == app.APP_VERSION and m["core_sha256"] == hashlib.sha256(data).hexdigest(), "manifest checksum")
    check(m["core_url"] == f"https://github.com/someone/almanac/releases/download/v{app.APP_VERSION}/almanac_app.py",
          "manifest points at the release asset")
    check(m["sections"][0][0] == "New" and m["min_launcher"] == 1, "notes and launcher level included")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "release.py"), "check", "--tag", "v0.1"],
                       capture_output=True, text=True)
    check(r.returncode != 0 and "doesn't match" in r.stderr, "wrong tag refused")
    check(launcher_mod.version_tuple("1.12") > launcher_mod.version_tuple("1.9") and
          app.version_tuple("v1.12.1") > app.version_tuple("1.12"), "version compare")


def test_backups_pruned():
    db = app.Database(os.path.join(HOME, app.DB_NAME))
    for i in range(app.BACKUPS_KEPT + 3):
        path = app.backup_database(db, f"test{i}")
        os.utime(path, (1_000_000 + i, 1_000_000 + i))
    names = sorted(os.listdir(app.BACKUP_DIR))
    check(len(names) == app.BACKUPS_KEPT, f"only the newest {app.BACKUPS_KEPT} backups kept ({len(names)})")


def test_supported():
    app.LAUNCHER = None
    check(app.updates_supported()[0] is False, "running from source: updater off")
    app.LAUNCHER = launcher_mod.Launcher()
    check(app.updates_supported()[0] is True, "through the launcher: updater on")
    saved, repo = os.environ.pop("ALMANAC_MANIFEST_URL"), app.UPDATE_REPO
    app.UPDATE_REPO = "__ALMANAC_REPO__"
    check(app.manifest_url() is None and not app.updates_supported()[0], "unstamped build has no update source")
    app.UPDATE_REPO = repo
    check(app.manifest_url() == f"https://github.com/{repo}/releases/latest/download/latest.json",
          f"stamped build checks {repo}")
    os.environ["ALMANAC_MANIFEST_URL"] = saved
    app.LAUNCHER = None


server = Server()
for fn in (test_manifest_and_status, test_rejects_bad_downloads, test_install_restart_rollback,
           test_failed_start_rolls_back, test_stale_core_and_exe_upgrade, test_release_tool, test_backups_pruned,
           test_supported):
    fn(server) if fn.__code__.co_argcount else fn()
print("RESULT:", "ALL PASSED" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
