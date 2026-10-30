"""Writes data/summary.md from the database using Groq.

The key is GROQ_API_KEY - the same name chat.py uses - read from the environment,
or from .streamlit/secrets.toml when running locally.

The summary covers a rolling recent window, not the whole stored history. With
years of backfilled data a whole-history summary names the same "biggest gainer"
for months on end; a rolling window gives a genuinely new answer each day.
Set SUMMARY_WINDOW_DAYS to change the span.

Fail safe: summary.md is only replaced after a good answer is in hand.
"""
import json
import os
import subprocess
import sys
import tomllib
from datetime import date, timedelta
from pathlib import Path

from openai import OpenAI

from rates_util import invest, load_rates, long_date, pct_changes

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
DB_PATH = SRC / "project.db"
OUT = ROOT / "data" / "summary.md"
META_OUT = ROOT / "data" / "summary.json"
MODEL = "openai/gpt-oss-120b"

# how many days back from the latest observation the summary looks
WINDOW_DAYS = int(os.environ.get("SUMMARY_WINDOW_DAYS", "30"))

SYSTEM_PROMPT = (
    "You write a short summary for a currency dashboard. The reader knows nothing about currencies. "
    "Use ONLY the numbers in the data you are given; never invent or recalculate numbers. "
    "A currency that gained value means one US dollar buys less of it, so travelling and spending there costs more. "
    "A currency that lost value means one US dollar goes further there. "
    "Write exactly two paragraphs of plain prose with no headings, no bullet points and no preamble. "
    "Paragraph 1 (3 to 4 sentences): name the currencies that gained and lost the most against the USD with their "
    "percent changes, and explain what that means for an American travelling to those countries and for someone "
    "investing with US dollars. "
    "Paragraph 2 (exactly 2 sentences): say what $100 invested in the biggest gainer and in the biggest loser would "
    "be worth in USD at the end of the period, using the exact dollar amounts given. "
    "Write every date exactly as it is written in the data, for example September 17th 2026, "
    "and never as 2026-09-17."
)


def redenominated(rates, threshold=10):
    """Currencies whose series contains a single-step jump of `threshold`x or more.

    A real exchange rate does not move tenfold between two consecutive
    observations. A redenomination does: Venezuela removed six zeros from the
    bolivar in 2021, so a 2020-to-2026 comparison reads as a +5,000% "gain" when
    the currency actually collapsed. The two endpoints are in different units, so
    any percent change across the break is meaningless and must not be ranked,
    summarised or described as an investment return.

    Returns {code: date of the break}.
    """
    broken = {}
    for code, group in rates.sort_values("date").groupby("quote_code"):
        series = group["rate"]
        series = series[series > 0]
        if len(series) < 2:
            continue
        ratio = (series / series.shift()).dropna()
        if ratio.empty:
            continue
        # symmetric, so a 1000x drop counts the same as a 1000x rise
        ratio = ratio.where(ratio >= 1, 1 / ratio)
        if (ratio >= threshold).any():
            broken[code] = group.loc[ratio.idxmax(), "date"].date()
    return broken


def find_api_key():
    """The Groq key: GROQ_API_KEY, the same name chat.py uses.

    chat.py reads st.secrets["GROQ_API_KEY"]; this script runs headless in CI
    where there is no Streamlit context, so it checks the environment first and
    then falls back to the same secrets.toml, which makes a local run work
    without exporting anything.
    """
    value = os.environ.get("GROQ_API_KEY")
    if value:
        return value, "$GROQ_API_KEY"

    for path in (ROOT / ".streamlit" / "secrets.toml",
                 Path.home() / ".streamlit" / "secrets.toml"):
        try:
            with open(path, "rb") as f:
                secrets = tomllib.load(f)
        except (OSError, ValueError):
            continue
        if secrets.get("GROQ_API_KEY"):
            return secrets["GROQ_API_KEY"], f"{path}:GROQ_API_KEY"

    return None, None


def build_facts():
    # rebuild the database fresh from the snapshot files so the numbers are current
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run([sys.executable, str(SRC / "build_db.py")], cwd=ROOT, check=True, capture_output=True)
    rates = load_rates(DB_PATH)
    if rates.empty:
        raise RuntimeError("No rates in the database")

    # the most recent WINDOW_DAYS of data, so the answer changes as days roll by
    days = rates["date"].dt.date
    latest = days.max()
    window = rates[days >= latest - timedelta(days=WINDOW_DAYS)]
    broken = redenominated(window)
    if broken:
        print(f"Excluding redenominated currencies: {sorted(broken)}")
        window = window[~window["quote_code"].isin(broken)]
    changes = pct_changes(window, "USD")

    # a short window right after a gap may not have two observations per currency;
    # fall back to everything rather than writing nothing at all
    if len(changes) < 10:
        print(f"Only {len(changes)} currencies in the last {WINDOW_DAYS} days, using full history")
        window = rates[~rates["quote_code"].isin(redenominated(rates))]
        changes = pct_changes(window, "USD")
        if len(changes) < 10:
            raise RuntimeError("Not enough data to summarize")

    window_days = window["date"].dt.date
    return window_days.min(), window_days.max(), changes, invest(changes, 100)


def fact_line(r):
    return (f"- {r['name']} ({r['quote_code']}): {r['pct_change']:+.2f}% "
            f"(from {r['first_rate']:.4f} to {r['last_rate']:.4f} per 1 USD)")


def build_prompt(start, end, changes, money):
    gainers = "\n".join(fact_line(r) for _, r in changes.head(5).iterrows())
    losers = "\n".join(fact_line(r) for _, r in changes.tail(5).iloc[::-1].iterrows())
    best, worst = money["best"], money["worst"]
    return (
        f"Data covers {start} to {end}. Rates are units of local currency per 1 US dollar.\n"
        f"Biggest gainers against the USD:\n{gainers}\n"
        f"Biggest losers against the USD:\n{losers}\n"
        f"$100 invested in the biggest gainer, {best['name']}, on {start} would be worth ${best['end']:.2f} on {end}.\n"
        f"$100 invested in the biggest loser, {worst['name']}, on {start} would be worth ${worst['end']:.2f} on {end}."
    )


def is_good(text, money):
    plain = text.replace(",", "")
    best, worst = money["best"], money["worst"]
    return (
        len(text) > 200
        and f"{best['end']:.2f}" in plain
        and f"{worst['end']:.2f}" in plain
        and (best["name"] in text or best["quote_code"] in text)
        and (worst["name"] in text or worst["quote_code"] in text)
    )


def write_meta(start_date, end_date, changes, money):
    """A machine-readable copy of what the summary covers.

    The dashboard reads this to label the summary with its own date range, so a
    summary written for a 30-day window is never shown as if it described
    whatever the viewer currently has selected.
    """
    top, bottom = changes.iloc[0], changes.iloc[-1]
    meta = {
        "base": "USD",
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "window_days": WINDOW_DAYS,
        "generated": date.today().isoformat(),
        "top": {
            "code": top["quote_code"],
            "name": top["name"],
            "pct_change": round(float(top["pct_change"]), 4),
            "hundred_becomes": round(float(money["best"]["end"]), 2),
        },
        "bottom": {
            "code": bottom["quote_code"],
            "name": bottom["name"],
            "pct_change": round(float(bottom["pct_change"]), 4),
            "hundred_becomes": round(float(money["worst"]["end"]), 2),
        },
    }
    tmp = META_OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2) + "\n")
    tmp.replace(META_OUT)
    return meta


def main():
    key, source = find_api_key()
    if not key:
        sys.exit(
            "GROQ_API_KEY is not set - summary.md left unchanged. Set it in the "
            "environment, or add it to .streamlit/secrets.toml."
        )
    print(f"Using Groq key from {source}")
    start_date, end_date, changes, money = build_facts()
    start, end = long_date(start_date), long_date(end_date)
    print(f"Summarizing {start} to {end} "
          f"(top: {changes.iloc[0]['quote_code']} {changes.iloc[0]['pct_change']:+.2f}%)")
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=key, timeout=60)
    text = ""
    for _ in range(2):  # one retry if the answer fails the check
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(start, end, changes, money)},
            ],
            reasoning_effort="low",
        )
        text = (response.choices[0].message.content or "").strip()
        if is_good(text, money):
            break
        print("Answer failed the check, retrying")
    else:
        sys.exit("No good answer from the model - summary.md left unchanged")
    # only now do we touch the file; write to a temp file first so it is never half written
    OUT.parent.mkdir(exist_ok=True)
    header = (f"*The last {WINDOW_DAYS} days of exchange-rate data, {start} to {end} "
              f"(generated {long_date(date.today())}).*")
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(header + "\n\n" + text + "\n")
    tmp.replace(OUT)
    write_meta(start_date, end_date, changes, money)
    print(f"Wrote {OUT} and {META_OUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"WARNING: summary not updated ({type(e).__name__}: {e})")
        sys.exit(1)