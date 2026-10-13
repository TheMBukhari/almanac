# Almanac

A Windows desktop scheduler that sends reminders to your phone, plus **Price Flash**, which tracks
PC-part prices across shops and tells you where each part is cheapest.

- **Scheduled**: one-time, daily, weekly, bi-weekly and monthly tasks, grouped by when they're due,
  with Undo for Done, Missed and Remove.
- **Phone reminders** through the free [ntfy](https://ntfy.sh) app.
- **Past Activities** and a **Dashboard** with completion stats.
- **Price Flash** reads prices from Amazon.sa, Trendyol, Newegg, Cazasouq and Infiniarc (AliExpress
  prices are typed in by hand). It converts everything to SAR with your shipping and import fees, keeps
  each part's lowest and highest price, totals your builds, and messages your phone when something drops.
- **Updates itself**: it checks once a day, shows what's new, and installs only when you say so.

## Install

1. Download **Almanac.exe** from the [latest release](../../releases/latest).
2. Put it in a folder of its own (for example `Documents\Almanac`) and run it. It keeps its data
   (`almanac_data.json`) next to itself.
3. Windows may warn that the app is from an unknown publisher, because it isn't code-signed.
   Choose **More info → Run anyway**.

### Coming from v1.11 or older

1. If the old version starts with Windows, turn that off in its Settings. Then right-click the tray
   icon and choose **Quit**.
2. Put `Almanac.exe` in the **same folder** as the old .exe and `scheduler_db.json`.
3. Run Almanac. It copies `scheduler_db.json` to `almanac_data.json` and leaves the old file as a backup.
   Turn **Start with Windows** on in Almanac's Settings if you want it.
4. Once everything looks right, delete the old .exe.

## Link your phone

1. Install **ntfy** from Google Play or the App Store.
2. In Almanac, open **Settings** and copy your topic. New installs get a private one like `almanac-3f9c1a7b2e`.
3. In ntfy, tap **+** and subscribe to that topic on `ntfy.sh`.
4. Press **Send test** in Almanac.

Anyone who knows a topic name can read its messages, so keep it hard to guess. **Generate private
topic** makes a new one.

## Updates

Almanac checks GitHub once a day. You can also press **Check for updates** on the Patch Notes page or in
Settings. When there's a new version you see its notes first, then choose **Update now**, **Later** or
**Skip this version**.

- Most updates download only `almanac_app.py`, about 200 KB, instead of the whole 70 MB+ `Almanac.exe`.
  `Almanac.exe` loads it from the `core` folder next to itself.
- Your data is copied to `backups\` first. The newest 10 copies are kept.
- If a new version fails to start, Almanac goes back to the previous one by itself and won't offer the
  broken version again. **Settings → Updates → Go back** does the same thing by hand.
- An update that needs a newer `Almanac.exe` (for example one that adds a new library) says so and links
  to the download.

## Files next to Almanac.exe

| File | What it is |
|---|---|
| `almanac_data.json` | All your tasks, history, settings and prices |
| `backups\` | Copies of the data made before each update |
| `core\` | The installed update (`almanac_app.py`), the previous one, and the update state and log |
| `almanac.log` | Errors, if any |

## For developers

```
pip install -r requirements.txt
python almanac_app.py           # run from source (the self-updater is off)
python launcher.py              # run the way Almanac.exe does (updater on)
python tools/run_tests.py
```

**Releasing a version:**
1. Bump `APP_VERSION` and `APP_CODENAME` in `almanac_app.py`.
2. Add a new entry at the top of `PATCH_NOTES`.
3. Run `python tools/release.py changelog`.
4. Commit and push to `main`.

When a push to `main` carries a version that has no release yet, the GitHub workflow in
`.github/workflows/release.yml`:
- runs the tests;
- builds `Almanac.exe` on Windows and checks that it starts;
- publishes release `vX.YY` with `Almanac.exe`, `almanac_app.py` and `latest.json`. `latest.json` holds the
  version, its notes and the checksum.

If an update needs a library the current `Almanac.exe` doesn't contain, raise `MIN_LAUNCHER` in
`almanac_app.py` and `LAUNCHER_VERSION` in `launcher.py` together.

`build_exe.bat` builds `Almanac.exe` locally, but you normally don't need it.
