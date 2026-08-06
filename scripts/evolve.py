#!/usr/bin/env python3
"""Advance the Copilot Book Health snapshot forward in time, one day at a time.

The book baseline (data/book.json) carries month-over-month figures from Kusto.
This step models realistic day-over-day movement on the *current-period* fields
(assigned seats, engaged users, gross/net UBB, AI units, surface mix) while
leaving the month baselines (seats_1mo, seats_3mo, prev_ubb, net_prev) fixed, so
the dashboard's monthly comparisons stay meaningful.

Movement is deterministic: seeded by (date, account id), so re-running a given
day always yields the same numbers. Each account drifts along its own recent
momentum (monthly seat % and UBB %) spread across ~22 working days, plus a small
bounded random component.

Every simulated day is written to history/YYYY-MM-DD.json, data/book.json is
updated to the target day, and the day-over-day book delta is returned for the
dashboard banner and the change summary.

Usage:
    python evolve.py [--to YYYY-MM-DD] [--root <repo-root>]
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import random

WORKING_DAYS = 22.0  # spread a monthly trend across a trading month


def _seed(date_str: str, account_id: str) -> random.Random:
    h = hashlib.sha256(f"{date_str}|{account_id}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def _clamp(v: float, lo: float, hi: float | None = None) -> float:
    v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _scale_surfaces(surfaces: dict, factor: float, rng: random.Random) -> dict:
    out = {}
    for label, val in surfaces.items():
        jitter = 1.0 + rng.gauss(0, 0.01)
        out[label] = max(0, int(round(val * factor * jitter)))
    return out


def evolve_account(acc: dict, date_str: str) -> dict:
    a = copy.deepcopy(acc)
    rng = _seed(date_str, a.get("salesforce_account_id", a.get("account", "")))

    seats = float(a.get("seats_now") or 0)
    seats_1mo = a.get("seats_1mo")
    seat_pct = float(a.get("seat_pct") or 0.0)  # monthly %

    # Daily seat drift along monthly momentum, damped, plus bounded noise.
    drift = seats * (seat_pct / 100.0) / WORKING_DAYS
    drift = _clamp(drift, -0.06 * max(seats, 1), 0.06 * max(seats, 1))
    noise = rng.gauss(0, max(0.6, seats * 0.004))
    new_seats = int(round(_clamp(seats + drift + noise, 0)))

    # Consumption momentum (gross UBB monthly %), damped daily.
    ubb_pct = 0.0
    prev_ubb = float(a.get("prev_ubb") or 0)
    cur_ubb = float(a.get("cur_ubb") or 0)
    if prev_ubb > 0:
        ubb_pct = (cur_ubb - prev_ubb) / prev_ubb * 100.0
    ubb_factor = 1.0 + (ubb_pct / 100.0) / WORKING_DAYS + rng.gauss(0, 0.012)
    ubb_factor = _clamp(ubb_factor, 0.94, 1.08)

    a["seats_now"] = new_seats
    a["hwm"] = max(int(a.get("hwm") or 0), new_seats)
    if isinstance(seats_1mo, (int, float)) and seats_1mo:
        a["seat_delta"] = int(round(new_seats - seats_1mo))
        a["seat_pct"] = round(a["seat_delta"] / seats_1mo * 100.0, 1)

    if cur_ubb > 0:
        a["cur_ubb"] = int(round(cur_ubb * ubb_factor))
        a["ubb_delta"] = int(round(a["cur_ubb"] - prev_ubb))
        a["ubb_pct"] = round((a["cur_ubb"] - prev_ubb) / prev_ubb * 100.0, 1) if prev_ubb > 0 else 0.0
    if a.get("ai_units"):
        a["ai_units"] = int(round(float(a["ai_units"]) * ubb_factor))

    if a.get("net_cur") is not None:
        a["net_cur"] = int(round(float(a["net_cur"]) * ubb_factor))
        net_prev = float(a.get("net_prev") or 0)
        a["net_delta"] = int(round(a["net_cur"] - net_prev))
        a["net_pct"] = round((a["net_cur"] - net_prev) / net_prev * 100.0, 1) if net_prev > 0 else 0.0
    if a.get("projected_eom"):
        a["projected_eom"] = int(round(float(a["projected_eom"]) * ubb_factor))

    if a.get("engaged") is not None and seats > 0:
        eng = float(a["engaged"]) * (new_seats / seats) + rng.gauss(0, max(0.4, float(a["engaged"]) * 0.01))
        a["engaged"] = int(round(_clamp(eng, 0, new_seats)))
        if new_seats > 0:
            a["util"] = round(a["engaged"] / new_seats, 3)

    if a.get("pool_dollars") and a.get("projected_eom") is not None:
        pd = float(a["pool_dollars"])
        a["pool_util"] = round(float(a["projected_eom"]) / pd, 3) if pd > 0 else a.get("pool_util")

    if a.get("budget_current") is not None:
        a["budget_current"] = int(round(float(a["budget_current"]) * ubb_factor))
        bt = float(a.get("budget_target") or 0)
        a["budget_pct"] = round(a["budget_current"] / bt, 3) if bt > 0 else None

    if isinstance(a.get("surfaces"), dict):
        a["surfaces"] = _scale_surfaces(a["surfaces"], ubb_factor, rng)

    return a


def roll_book(book: dict, accounts: list[dict]) -> dict:
    b = dict(book)
    b["seats_now"] = int(sum(int(a.get("seats_now") or 0) for a in accounts))
    b["ubb_cur"] = int(sum(int(a.get("cur_ubb") or 0) for a in accounts))
    net_accts = [a for a in accounts if a.get("net_cur") is not None]
    if net_accts:
        b["net_cur"] = int(sum(int(a.get("net_cur") or 0) for a in net_accts))
        b["net_prev"] = int(sum(int(a.get("net_prev") or 0) for a in net_accts))
    eng_accts = [a for a in accounts if a.get("engaged") is not None]
    if eng_accts:
        b["engaged_now"] = int(sum(int(a.get("engaged") or 0) for a in eng_accts))
    return b


def step_one_day(data: dict, date_str: str) -> dict:
    nxt = copy.deepcopy(data)
    nxt["accounts"] = [evolve_account(a, date_str) for a in data["accounts"]]
    nxt["book"] = roll_book(data["book"], nxt["accounts"])
    nxt["meta"] = dict(data["meta"])
    nxt["meta"]["as_of"] = date_str
    return nxt


def book_delta(prev: dict, cur: dict) -> dict:
    pb, cb = prev["book"], cur["book"]
    prev_by = {a.get("salesforce_account_id"): a for a in prev["accounts"]}
    up = down = 0
    for a in cur["accounts"]:
        p = prev_by.get(a.get("salesforce_account_id"))
        if not p:
            continue
        d = int(a.get("seats_now") or 0) - int(p.get("seats_now") or 0)
        if d > 0:
            up += 1
        elif d < 0:
            down += 1
    net_delta = None
    if cb.get("net_cur") is not None and pb.get("net_cur") is not None:
        net_delta = int(cb["net_cur"] - pb["net_cur"])
    seats_delta = int(cb["seats_now"] - pb["seats_now"])
    ubb_delta = int(cb["ubb_cur"] - pb["ubb_cur"])
    note = (
        f"Assigned seats {'+' if seats_delta >= 0 else ''}{seats_delta}, "
        f"gross UBB {'+' if ubb_delta >= 0 else ''}${ubb_delta:,} across {up + down} moving accounts."
    )
    return {
        "enabled": True,
        "prev_date": pb.get("as_of") or prev["meta"].get("as_of"),
        "date": cb.get("as_of") or cur["meta"].get("as_of"),
        "seats_delta": seats_delta,
        "ubb_delta": ubb_delta,
        "net_delta": net_delta,
        "up": up,
        "down": down,
        "note": note,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default=dt.date.today().isoformat(), help="target date YYYY-MM-DD")
    ap.add_argument("--root", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    args = ap.parse_args()

    root = args.root
    book_path = os.path.join(root, "data", "book.json")
    hist_dir = os.path.join(root, "history")
    os.makedirs(hist_dir, exist_ok=True)

    with open(book_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    start = dt.date.fromisoformat(data["meta"]["as_of"])
    target = dt.date.fromisoformat(args.to)

    # Always persist the current baseline as its own snapshot.
    base_snap = os.path.join(hist_dir, f"{start.isoformat()}.json")
    if not os.path.exists(base_snap):
        with open(base_snap, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    if target <= start:
        # Nothing to advance; report the last transition if we have one.
        days = sorted(f[:-5] for f in os.listdir(hist_dir) if f.endswith(".json") and f != "latest.json")
        delta = {"enabled": False}
        if len(days) >= 2:
            with open(os.path.join(hist_dir, f"{days[-2]}.json")) as fh:
                prev = json.load(fh)
            delta = book_delta(prev, data)
        _finish(hist_dir, data, delta)
        print(f"No advance needed (as_of {start} >= target {target}).")
        return

    prev = data
    day = start
    while day < target:
        day = day + dt.timedelta(days=1)
        cur = step_one_day(prev, day.isoformat())
        with open(os.path.join(hist_dir, f"{day.isoformat()}.json"), "w", encoding="utf-8") as fh:
            json.dump(cur, fh, indent=2)
        prev = cur

    data_final = prev
    with open(book_path, "w", encoding="utf-8") as fh:
        json.dump(data_final, fh, indent=2)

    # Day-over-day delta = final day vs the day before it.
    yday = (target - dt.timedelta(days=1)).isoformat()
    yday_path = os.path.join(hist_dir, f"{yday}.json")
    if os.path.exists(yday_path):
        with open(yday_path) as fh:
            prev_day = json.load(fh)
        delta = book_delta(prev_day, data_final)
    else:
        delta = book_delta(data, data_final)

    _finish(hist_dir, data_final, delta)
    print(f"Advanced book to {target} ({len(data_final['accounts'])} accounts). "
          f"seats {delta['seats_delta']:+d}, ubb ${delta['ubb_delta']:+,}.")


def _finish(hist_dir: str, data: dict, delta: dict) -> None:
    with open(os.path.join(hist_dir, "latest.json"), "w", encoding="utf-8") as fh:
        json.dump({"as_of": data["meta"]["as_of"], "delta": delta}, fh, indent=2)


if __name__ == "__main__":
    main()
