#!/usr/bin/env python3
"""Run every tests/test_*.py; on GitHub Actions a failure also becomes an annotation with its output."""
import glob
import os
import subprocess
import sys

try:  # a Windows console may not be UTF-8; never crash on printing test output
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
failed = []
for path in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py"))):
    name = os.path.basename(path)
    run = subprocess.run([sys.executable, path], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env, cwd=ROOT)
    output = run.stdout + run.stderr
    print(f"===== {name}: {'passed' if run.returncode == 0 else 'FAILED'}")
    print(output)
    if run.returncode != 0:
        failed.append(name)
        if os.environ.get("GITHUB_ACTIONS"):
            lines = [l for l in output.splitlines() if l.startswith("FAIL")] or output.splitlines()
            text = "\n".join(lines[-25:]).replace("%", "%25").replace("\r", "").replace("\n", "%0A")
            print(f"::error title={name} failed::{text}")
print("FAILED: " + ", ".join(failed) if failed else "ALL TEST FILES PASSED")
sys.exit(1 if failed else 0)
