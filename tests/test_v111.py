"""v1.11 'Rewind': undo, grouping, early-done guard logic."""
import os
import sys
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ALMANAC_HOME", tempfile.mkdtemp())  # keep logs out of the repo
import almanac_app as app  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def fresh_db():
    return app.Database(os.path.join(tempfile.mkdtemp(), "almanac_data.json"))


def test_undo_entries_without_snapshots():
    """A weekly task marked Done 3 times under v1.10, whose history entries have no snapshots."""
    db = fresh_db()
    first_due = (app.now() + timedelta(days=2)).replace(hour=18, minute=0, second=0, microsecond=0)
    task = app.make_task("Gym", first_due, "High", "Weekly", 30)
    db.update(lambda d: d["scheduled"].append(task))
    for _ in range(3):
        app.resolve_task(db, task["id"], "completed")
    db.update(lambda d: [r.pop("task", None) for r in d["past"]])  # what v1.10 wrote
    now_task = db.get("scheduled")[0]
    check(app.parse_dt(now_task["due"]) == first_due + timedelta(weeks=3), "3 clicks pushed it 3 weeks ahead")
    past = db.get("past")
    check(app.undoable_past_ids(past) == {past[-1]["id"]}, "only the newest entry is undoable")
    for step in range(3, 0, -1):
        newest = next(iter(app.undoable_past_ids(db.get("past"))))
        restored = app.undo_resolution(db, newest)
        check(restored is not None and app.parse_dt(restored["due"]) == first_due + timedelta(weeks=step - 1),
              f"undo #{4 - step} -> due {restored['due'] if restored else None}")
    check(db.get("past") == [], "history clean again")
    t = db.get("scheduled")[0]
    check(len(db.get("scheduled")) == 1 and t["due"] == first_due.strftime(app.DT_FMT) and not t["notified"],
          "task back on its original date, reminder still pending")
    check(t["remind"] == 30 and t["urgency"] == "High", "task settings kept")


def test_exact_restore_and_one_time():
    db = fresh_db()
    t = app.make_task("Pay bill", app.now() + timedelta(hours=3), "Low", "One-Time", 10)
    db.update(lambda d: d["scheduled"].append(t))
    pid = app.resolve_task(db, t["id"], "completed")
    check(db.get("scheduled") == [] and pid, "one-time task left the schedule")
    restored = app.undo_resolution(db, pid)
    check(restored == t and db.get("scheduled") == [t], "one-time task restored exactly (snapshot)")
    check(app.undo_resolution(db, pid) is None, "same entry can't be undone twice")
    # v1.10-era one-time entry (no snapshot) is rebuilt from the record
    pid = app.resolve_task(db, t["id"], "missed")
    db.update(lambda d: d["past"][-1].pop("task"))
    restored = app.undo_resolution(db, pid)
    check(restored["id"] == t["id"] and restored["due"] == t["due"] and restored["name"] == "Pay bill",
          "old-style one-time entry rebuilt")


def test_remove_restore():
    db = fresh_db()
    t = app.make_task("Call mum", app.now() + timedelta(days=1), "Medium", "Daily", 0)
    db.update(lambda d: d["scheduled"].append(t))
    gone = app.remove_task(db, t["id"])
    check(gone == t and db.get("scheduled") == [], "remove returns the task")
    app.restore_task(db, gone)
    app.restore_task(db, gone)
    check(db.get("scheduled") == [t], "restore puts it back once")


def test_groups_and_dates():
    ref = datetime(2026, 10, 13, 11, 30)
    cases = [(datetime(2026, 10, 13, 9, 0), "Overdue"), (datetime(2026, 10, 13, 20, 0), "Today"),
             (datetime(2026, 10, 14, 8, 0), "Tomorrow"), (datetime(2026, 10, 19, 8, 0), "This week"),
             (datetime(2026, 10, 22, 8, 0), "Next week"), (datetime(2026, 11, 2, 8, 0), "Later")]
    for due, want in cases:
        check(app.schedule_group(due, ref) == want, f"{due:%a %d %b %H:%M} -> {want}")
    t = {"due": "2026-10-15 18:00", "recurring": "Bi-weekly", "anchor_day": 15}
    check([d.strftime("%d %b") for d in app.upcoming_dates(t)] == ["29 Oct", "12 Nov"], "next dates for bi-weekly")
    check(app.upcoming_dates({"due": "2026-10-15 18:00", "recurring": "One-Time"}) == [], "none for one-time")


for fn in (test_undo_entries_without_snapshots, test_exact_restore_and_one_time, test_remove_restore,
           test_groups_and_dates):
    fn()
print("RESULT:", "ALL PASSED" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
