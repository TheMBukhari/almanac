#!/usr/bin/env python3
"""Release helpers, used by .github/workflows/release.yml (and handy locally).

    python tools/release.py version                       print APP_VERSION
    python tools/release.py check --tag v1.13             the tag must match APP_VERSION
    python tools/release.py stamp --repo owner/almanac     write the update source into almanac_app.py
    python tools/release.py manifest --repo owner/almanac --tag v1.13 --out dist/latest.json
    python tools/release.py notes --out dist/notes.md      this version's patch notes as Markdown
    python tools/release.py changelog                      rewrite CHANGELOG.md from PATCH_NOTES

Reads almanac_app.py with ast, so it needs no third-party packages.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "almanac_app.py")


def constants(path: str = CORE) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("APP_NAME", "APP_VERSION", "APP_CODENAME", "MIN_LAUNCHER", "UPDATE_REPO", "PATCH_NOTES"):
                found[name] = ast.literal_eval(node.value)
    return found


def release_dict(release: dict) -> dict:
    return {
        "version": release["version"], "name": release.get("name", ""), "date": release.get("date", ""),
        "summary": release.get("summary", ""),
        "sections": [[heading, list(bullets)] for heading, bullets in release.get("sections", [])],
    }


def markdown(release: dict, heading_level: str = "##") -> str:
    lines = [f"{heading_level} v{release['version']} · {release.get('name', '')}".rstrip(" ·"), ""]
    if release.get("date"):
        lines += [f"*{release['date']}*", ""]
    if release.get("summary"):
        lines += [release["summary"], ""]
    for heading, bullets in release.get("sections", []):
        lines.append(f"**{heading}**")
        lines += [f"- {b}" for b in bullets]
        lines.append("")
    return "\n".join(lines)


def cmd_check(args):
    c = constants()
    want = f"v{c['APP_VERSION']}"
    if args.tag != want:
        sys.exit(f"Tag {args.tag} doesn't match APP_VERSION ({want}). Bump APP_VERSION or retag.")
    if c["PATCH_NOTES"][0]["version"] != c["APP_VERSION"]:
        sys.exit("The newest PATCH_NOTES entry isn't for APP_VERSION. Log the update first.")
    print(f"OK: {want} · {c['APP_CODENAME']}")


def cmd_version(args):
    print(constants()["APP_VERSION"])


def cmd_stamp(args):
    with open(CORE, "r", encoding="utf-8") as fh:
        text = fh.read()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        sys.exit(f"Bad repo name {args.repo!r}")
    new, count = re.subn(r'^UPDATE_REPO = "[^"]*"$', f'UPDATE_REPO = "{args.repo}"', text, flags=re.M)
    if count != 1:
        sys.exit("UPDATE_REPO line not found")
    with open(CORE, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new)
    print(f"UPDATE_REPO = {args.repo}")


def cmd_manifest(args):
    c = constants()
    with open(CORE, "rb") as fh:
        data = fh.read()
    base = f"https://github.com/{args.repo}/releases/download/{args.tag}"
    manifest = release_dict(c["PATCH_NOTES"][0])
    manifest.update({
        "core_url": f"{base}/almanac_app.py",
        "core_sha256": hashlib.sha256(data).hexdigest(),
        "core_size": len(data),
        "min_launcher": int(c.get("MIN_LAUNCHER", 1)),
        "full_url": f"{base}/Almanac.exe",
        "page_url": f"https://github.com/{args.repo}/releases/tag/{args.tag}",
    })
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(json.dumps({k: manifest[k] for k in ("version", "core_sha256", "core_size", "min_launcher")}))


def cmd_notes(args):
    c = constants()
    text = markdown(release_dict(c["PATCH_NOTES"][0]), "##")
    text += ("\n---\n**New install:** download `Almanac.exe` below and run it.  \n"
             "**Already on v1.12 or later:** Almanac offers this update by itself "
             "(or press *Check for updates* on the Patch Notes page).\n")
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


def cmd_changelog(args):
    c = constants()
    parts = [f"# {c['APP_NAME']} changelog", "",
             "Generated from PATCH_NOTES in almanac_app.py; the app shows the same notes on its Patch Notes page.",
             "Versions before 1.12 were released under an earlier name.", ""]
    for release in c["PATCH_NOTES"]:
        parts.append(markdown(release_dict(release), "##"))
    with open(args.out or os.path.join(ROOT, "CHANGELOG.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(parts).rstrip() + "\n")
    print("CHANGELOG.md written")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version")
    p = sub.add_parser("check")
    p.add_argument("--tag", required=True)
    p = sub.add_parser("stamp")
    p.add_argument("--repo", required=True)
    p = sub.add_parser("manifest")
    p.add_argument("--repo", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("notes")
    p.add_argument("--out", required=True)
    p = sub.add_parser("changelog")
    p.add_argument("--out")
    args = parser.parse_args()
    {"version": cmd_version, "check": cmd_check, "stamp": cmd_stamp, "manifest": cmd_manifest, "notes": cmd_notes,
     "changelog": cmd_changelog}[args.cmd](args)


if __name__ == "__main__":
    main()
