# Copilot Book Health Tracker

A daily dashboard that tracks the health of a Copilot seller's book of business:
assigned seats, usage-based billing (UBB) consumption, engagement, overage and
budget risk, and per-account recommendations.

**Stable URL:** https://craisedana.github.io/copilot-book-health-tracker/

The Pages URL is fixed; only the content behind it changes each day.

## What it shows

- Book-level KPIs: assigned Copilot seats, gross and net UBB, book utilization,
  overage-risk and near-budget-cap account counts, and month-over-month change.
- A "since yesterday" delta banner driven by the daily history snapshots.
- Deterministic, rules-based recommendations (where to spend your time).
- Seat and consumption growth charts, a churn and risk watchlist, product-surface
  mix, a budget and cap watch, and a full sortable account table.

## How the daily run works

`scripts/generate.py` runs once per day and:

1. Advances `data/book.json` one day at a time to the target date
   (`scripts/evolve.py`), writing a snapshot to `history/YYYY-MM-DD.json`.
   Day-over-day movement follows each account's own recent momentum (monthly seat
   and UBB percentages spread across a working month) plus a small bounded random
   component. Movement is seeded by date and account id, so re-running a day is
   idempotent. Month baselines (`seats_1mo`, `seats_3mo`, `prev_ubb`, `net_prev`)
   stay fixed so the dashboard's monthly comparisons remain valid.
2. Rebuilds the dashboard (`scripts/build_dashboard.py` +
   `templates/dashboard-template.html`) with the advanced book and the
   day-over-day delta.
3. Writes `docs/index.html` (served by Pages), `docs/data.json` (the raw book),
   and `change-summary.md` (a short day-over-day note).

The scheduled workflow `.github/workflows/daily.yml` runs this every morning,
commits the refreshed dashboard and the new history snapshot, and opens a GitHub
issue summarizing what changed.

## Running it manually

```
python3 scripts/generate.py            # advance to today and publish
python3 scripts/generate.py --to 2026-08-10   # advance to a specific date
```

## Layout

```
data/book.json                     current book snapshot (source of truth)
history/YYYY-MM-DD.json            one snapshot per day
history/latest.json                latest date + day-over-day delta
scripts/evolve.py                  advances the book one day at a time
scripts/generate.py                orchestrates evolve + build + publish
scripts/build_dashboard.py         renders the dashboard from a book snapshot
scripts/recommend.py               deterministic recommendation rules
templates/dashboard-template.html  dashboard template
docs/index.html                    published dashboard (GitHub Pages, /docs)
```
