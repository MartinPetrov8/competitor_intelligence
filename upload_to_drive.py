#!/usr/bin/env python3
"""
upload_to_drive.py — Push the latest static dashboard to GitHub Pages.

Usage:
    python upload_to_drive.py
    python upload_to_drive.py --file dashboard_2026-02-25.html

Live URL: https://martinpetrov8.github.io/competitor_intelligence/
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
TODAY      = datetime.now(timezone.utc).strftime("%Y-%m-%d")
PAGES_URL  = "https://martinpetrov8.github.io/competitor_intelligence/"


def run(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None)
    args = parser.parse_args()

    html_path = Path(args.file) if args.file else SCRIPT_DIR / f"dashboard_{TODAY}.html"
    if not html_path.is_absolute():
        html_path = SCRIPT_DIR / html_path
    if not html_path.exists():
        print(f"❌ File not found: {html_path}", file=sys.stderr)
        return 1

    repo = SCRIPT_DIR
    size_kb = html_path.stat().st_size // 1024
    print(f"📤 Deploying {html_path.name} ({size_kb} KB) to GitHub Pages…")

    # Switch to gh-pages, update index.html, push, switch back
    current = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)

    try:
        run(["git", "checkout", "gh-pages"], cwd=repo)
        import shutil
        shutil.copy(html_path, repo / "index.html")
        run(["git", "add", "index.html"], cwd=repo)
        run(["git", "commit", "--allow-empty", "-m", f"Dashboard snapshot {TODAY}"], cwd=repo)
        run(["git", "push", "origin", "gh-pages", "--force"], cwd=repo)
        print(f"\n✅ Live at: {PAGES_URL}")
    finally:
        run(["git", "checkout", current], cwd=repo)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
