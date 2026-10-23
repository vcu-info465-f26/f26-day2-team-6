"""Writes data/summary.md from the database using Groq. The key is the TEAM_6_API_KEY environment variable.

Fail safe: summary.md is only replaced after a good answer is in hand.
"""
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from openai import OpenAI

from rates_util import invest, load_rates, long_date, pct_changes

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
DB_PATH = SRC / "project.db"
OUT = ROOT / "data" / "summary.md"
MODEL = "openai/gpt-oss-120b"

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


def build_facts():
    # rebuild the database fresh from the snapshot files so the numbers are current
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run([sys.executable, str(SRC / "build_db.py")], cwd=ROOT, check=True, capture_output=True)
    rates = load_rates(DB_PATH)
    changes = pct_changes(rates, "USD")
    if len(changes) < 10:
        raise RuntimeError("Not enough data to summarize")
    start = long_date(rates["date"].min().date())
    end = long_date(rates["date"].max().date())
    return start, end, changes, invest(changes, 100)


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


def main():
    key = os.environ.get("TEAM_6_API_KEY")
    if not key:
        sys.exit("TEAM_6_API_KEY is not set - summary.md left unchanged")
    start, end, changes, money = build_facts()
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
    header = f"*Written from exchange-rate data dated {start} to {end} (generated {long_date(date.today())}).*"
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(header + "\n\n" + text + "\n")
    tmp.replace(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"WARNING: summary not updated ({type(e).__name__}: {e})")
        sys.exit(1)
