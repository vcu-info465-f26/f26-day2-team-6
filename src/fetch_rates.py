import argparse
import json
import pathlib
import re
from collections import defaultdict
from datetime import date

import requests

URL = "https://api.frankfurter.dev/v2/rates"
DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
HISTORY_FILE = DATA_DIR / "rates_history.json"

# matches the dated daily snapshots, but not rates_history.json
DAILY_NAME = re.compile(r"^rates_(\d{4}-\d{2}-\d{2})\.json$")


def get_latest_rates(base="USD", quotes=None):
    url = URL

    # send the request
    response = requests.get(url, params={"base": base, "quotes": quotes})

    # turn the response into a python list of rows
    data = response.json()

    return data


def get_rates_range(start, end, base="USD", quotes=None, group=None):
    """Same endpoint, but a span of days instead of today.

    Frankfurter keeps history, so these are the real published rates for those
    dates, not estimates. It only returns days it actually has data for, so
    weekends and holidays drop out on their own.
    """
    params = {"base": base, "quotes": quotes, "from": start, "to": end}
    if group:
        # Frankfurter downsamples server-side: one row per week or per month
        # instead of per day, which is what makes years of history practical.
        params["group"] = group
    response = requests.get(URL, params=params, timeout=180)
    response.raise_for_status()
    return response.json()


def get_rates_range_chunked(start, end, base="USD", quotes=None, group=None):
    """Fetch a long span, a calendar year at a time when fetching every day.

    Frankfurter's docs ask you to keep responses small, and a single daily request
    for several years of every currency is slow enough to risk timing out. A
    downsampled request is small enough to take in one go, and chunking it would
    restart the week/month grouping at every year boundary.
    """
    if group:
        print(f"  fetching {start} -> {end} grouped by {group} ...", flush=True)
        rows = get_rates_range(start, end, base, quotes, group)
        print(f"    {len(rows)} rows")
        return rows

    rows = []
    start_year = int(start[:4])
    end_year = int(end[:4])

    for year in range(start_year, end_year + 1):
        chunk_start = start if year == start_year else f"{year}-01-01"
        chunk_end = end if year == end_year else f"{year}-12-31"
        print(f"  fetching {chunk_start} -> {chunk_end} ...", flush=True)
        chunk = get_rates_range(chunk_start, chunk_end, base, quotes, group)
        print(f"    {len(chunk)} rows")
        rows.extend(chunk)

    return rows


def group_by_date(rows):
    """Turn one flat list of rows into {date: [rows for that date]}."""
    by_date = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row)
    return by_date


def existing_daily_dates():
    """Dates that already have their own rates_<date>.json file.

    build_db.py inserts every row of every rates_*.json without de-duplicating,
    so a date must never appear in both the history file and a daily file.
    """
    if not DATA_DIR.exists():
        return set()
    found = set()
    for path in DATA_DIR.iterdir():
        match = DAILY_NAME.match(path.name)
        if match:
            found.add(match.group(1))
    return found


def write_snapshot(rows, day, overwrite=False):
    """Save one day's rows as src/data/rates_<day>.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"rates_{day}.json"

    if path.exists() and not overwrite:
        print(f"skip  {path.name} (already there)")
        return False

    with open(path, "w") as f:
        json.dump(rows, f)
    print(f"write {path.name} ({len(rows)} rows)")
    return True


def write_history(rows):
    """Save many dates into one file, so years of history don't mean years of files."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(rows, f)
    size_mb = HISTORY_FILE.stat().st_size / 1_000_000
    print(f"\nwrote {HISTORY_FILE.name}: {len(rows)} rows, {size_mb:.1f} MB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch today's exchange rates, or backfill days that were missed."
    )
    parser.add_argument(
        "--backfill",
        metavar="START_DATE",
        help="write one snapshot file per day from START_DATE (YYYY-MM-DD) to today",
    )
    parser.add_argument(
        "--history",
        metavar="START_DATE",
        help="fetch from START_DATE to today into a single rates_history.json, "
             "skipping any date that already has its own daily file",
    )
    parser.add_argument(
        "--group",
        choices=["day", "week", "month"],
        default="week",
        help="how often to sample when using --history. Daily over several years "
             "is ~290k rows and ~22MB; weekly is about a fiftieth of that and "
             "still draws a smooth line. Ignored by --backfill, which is always daily.",
    )
    parser.add_argument("--base", default="USD")
    parser.add_argument(
        "--quotes",
        help="comma-separated currency codes to limit the fetch, e.g. EUR,GBP,JPY. "
             "Use this if the full set of currencies makes the files too large.",
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite daily snapshots that already exist"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would be written, write nothing"
    )
    args = parser.parse_args()

    today = date.today().isoformat()

    if args.backfill and args.history:
        parser.error("use --backfill or --history, not both")

    if args.history:
        already = existing_daily_dates()
        print(f"fetching {args.base} history {args.history} -> {today} "
              f"(sampled {args.group})")
        print(f"({len(already)} dates already have their own daily file and will be skipped)")
        group = None if args.group == "day" else args.group
        rows = get_rates_range_chunked(args.history, today, args.base, args.quotes, group)
        kept = [row for row in rows if row["date"] not in already]
        dropped = len(rows) - len(kept)
        dates = {row["date"] for row in kept}
        print(f"\ngot {len(rows)} rows; kept {len(kept)} across {len(dates)} dates "
              f"({dropped} dropped as duplicates of daily files)")
        if args.dry_run:
            print(f"would write {HISTORY_FILE.name}")
        elif kept:
            write_history(kept)
            print("now run: python src/build_db.py")

    elif args.backfill:
        print(f"backfilling {args.base} rates {args.backfill} -> {today}")
        # one file per day, so this one always fetches daily
        rows = get_rates_range_chunked(args.backfill, today, args.base, args.quotes)
        by_date = group_by_date(rows)
        print(f"\ngot {len(rows)} rows across {len(by_date)} dates")

        written = 0
        for day in sorted(by_date):
            if args.dry_run:
                path = DATA_DIR / f"rates_{day}.json"
                state = "skip (already there)" if path.exists() and not args.force else "would write"
                print(f"{state} rates_{day}.json ({len(by_date[day])} rows)")
                continue
            if write_snapshot(by_date[day], day, overwrite=args.force):
                written += 1
        if not args.dry_run:
            print(f"\ndone: {written} new snapshot files")
            if written:
                print("now run: python src/build_db.py")

    else:
        # the daily workflow path: today only, exactly as before
        rows = get_latest_rates(args.base, args.quotes)
        write_snapshot(rows, today, overwrite=True)