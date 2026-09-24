# Joins exchange rates with currency details and prints the latest ten rates.
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "project.db"


def show_latest_rates():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run build_db.py first, then run analyze.py again.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        query = """
            SELECT exchange_rates.date,
                   exchange_rates.base_code,
                   exchange_rates.quote_code,
                   currencies.name,
                   currencies.symbol,
                   exchange_rates.rate
            FROM exchange_rates
            JOIN currencies
              ON exchange_rates.quote_code = currencies.currency_code
            ORDER BY exchange_rates.date DESC, exchange_rates.quote_code
            LIMIT 10
        """
        rows = conn.execute(query).fetchall()

        print("Date | Base | Quote | Currency Name | Symbol | Rate")
        print("-----|------|-------|----------------|--------|-----")
        for row in rows:
            print(" | ".join(str(value) for value in row))
    finally:
        conn.close()


if __name__ == "__main__":
    show_latest_rates()