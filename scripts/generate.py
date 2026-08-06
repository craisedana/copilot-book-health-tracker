#!/usr/bin/env python3
"""Regenerate the Copilot Book Health Tracker for a target day and publish it.

Steps:
  1. Advance data/book.json to the target date (default: today), writing daily
     history snapshots (scripts/evolve.py).
  2. Rebuild the dashboard from the advanced book plus the day-over-day delta.
  3. Write docs/index.html (served by GitHub Pages), docs/data.json (the raw
     book), and change-summary.md (a short day-over-day note).

Usage:
    python generate.py [--to YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import build_dashboard  # noqa: E402


def _fmt_usd(n: int) -> str:
    return ("+" if n >= 0 else "-") + "$" + f"{abs(int(n)):,}"


def write_change_summary(delta: dict, as_of: str) -> str:
    lines = [f"# Copilot Book Health — {as_of}", ""]
    if not delta.get("enabled"):
        lines.append("No prior day to compare against yet; this is the baseline snapshot.")
    else:
        s, u = delta.get("seats_delta", 0), delta.get("ubb_delta", 0)
        lines.append(f"Day-over-day change since {delta.get('prev_date')}:")
        lines.append("")
        lines.append(f"- Assigned Copilot seats: {'+' if s >= 0 else ''}{s}")
        lines.append(f"- Gross UBB: {_fmt_usd(u)}")
        if delta.get("net_delta") is not None:
            lines.append(f"- Net / billable UBB: {_fmt_usd(delta['net_delta'])}")
        lines.append(f"- Accounts moving: {delta.get('up', 0)} up / {delta.get('down', 0)} down")
    lines.append("")
    lines.append("Published: https://craisedana.github.io/copilot-book-health-tracker/")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default=dt.date.today().isoformat())
    args = ap.parse_args()

    # 1. Advance the book and history.
    subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "evolve.py"), "--to", args.to, "--root", ROOT],
        check=True,
    )

    # 2. Load advanced book + latest delta.
    with open(os.path.join(ROOT, "data", "book.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    latest_path = os.path.join(ROOT, "history", "latest.json")
    delta = {"enabled": False}
    if os.path.exists(latest_path):
        with open(latest_path, encoding="utf-8") as fh:
            delta = json.load(fh).get("delta", {"enabled": False})
    data["daily"] = delta

    # 3. Build dashboard and publish outputs.
    html = build_dashboard.build(data)
    docs = os.path.join(ROOT, "docs")
    os.makedirs(docs, exist_ok=True)
    with open(os.path.join(docs, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    with open(os.path.join(docs, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    with open(os.path.join(ROOT, "change-summary.md"), "w", encoding="utf-8") as fh:
        fh.write(write_change_summary(delta, data["meta"]["as_of"]))

    print(f"Published dashboard for {data['meta']['as_of']} ({len(data['accounts'])} accounts).")


if __name__ == "__main__":
    main()
