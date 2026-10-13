# Almanac changelog

Generated from PATCH_NOTES in almanac_app.py; the app shows the same notes on its Patch Notes page.
Versions before 1.12 were released under an earlier name.

## v1.12 · Open Doors

*2026-10-13*

The app is now called Almanac. It can update itself, and new users start with a clean slate.

**New**
- Updates install themselves. Almanac checks once a day (or when you press Check for updates on this page), shows what's new, and installs only when you say so. Most updates are one small file instead of a whole new download.
- Your data is backed up before every update. If a new version doesn't start, Almanac goes back to the previous one by itself, and Settings has a button to go back by hand.
- A clock under the app name.
- New versions are built on GitHub and published as a ready-made Almanac.exe, so there's no build script to run.

**Changed**
- New name: Almanac. The data file is now almanac_data.json. On first start it's copied from scheduler_db.json, which stays where it is as a backup. Turn Start with Windows on again in Settings.
- New users start empty: no name, a private phone topic made just for them, and an empty Price Flash page. Your own data is unchanged.
- Price Flash categories can be typed freely, with more ready-made ones (PSU, Case, Cooling, Monitor, Peripherals).

**Known limits**
- This version is installed by hand. Automatic updates start with the next one.
- Prices are still converted to SAR.

## v1.11 · Rewind

*2026-10-13*

Mistakes on the Scheduled page can now be taken back.

**New**
- Undo: after Done, Missed or Remove, the message in the corner has an Undo button for a few seconds.
- Undo in Past Activities: the latest entry of each task can be undone at any time. Undoing a repeating task steps it back one occurrence per click, so several accidental Done clicks can all be reversed. This also works on entries made before this update.
- Repeating tasks show their next two dates on the card.

**Changed**
- The Scheduled page is grouped into Overdue, Today, Tomorrow, This week, Next week and Later.
- Marking a repeating task done or missed before its day now asks first, since that skips ahead to the following occurrence.

## v1.10 · Wide Net

*2026-10-12*

Price Flash now compares shops instead of watching one, and tracks price only.

**New**
- Five more shops alongside Amazon.sa: Trendyol, Newegg, Cazasouq, Infiniarc and AliExpress.
- Best prices table: every part shows its cheapest price right now and the shop selling it, plus the lowest and highest price seen.
- Prices in USD, BHD and other Gulf currencies are converted to SAR, with the shipping and import fees you set on each listing added in.
- New-low alert: your phone gets a separate alert when a part hits its lowest price so far.
- Bi-weekly repeat for scheduled tasks.
- This Patch Notes page.

**Changed**
- Price Flash tracks price only. Stock, arrival and other details go in a note on each listing, and a listing can be skipped by hand, for example when it's out of stock.
- Builds are made of parts, and each part is priced at its cheapest shop.
- The daily phone message lists the best price and shop for each part.
- Your parts, prices, history and builds carried over from v1.00.

**Known limits**
- AliExpress only shows prices after its page loads in a browser, so its prices are typed in by hand.
- Newegg and Cazasouq only show shipping to Saudi Arabia at checkout. Add it to the listing once you've seen it.

## v1.00 · First Light

*2026-10-11*

The first release.

**Highlights**
- Scheduler with one-time, daily, weekly and monthly tasks, urgency levels and phone reminders through ntfy.
- Past Activities history and a Dashboard with completion stats.
- Price Flash: a daily Amazon.sa price check for PC parts, with build totals, a daily phone summary and separate price-drop alerts.
- Runs in the system tray, can start with Windows, and has light and dark themes.
