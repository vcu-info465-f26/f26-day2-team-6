import sqlite3
import json
import pathlib


DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)
# makes a data folder if it doesn't already exist

conn = sqlite3.connect(pathlib.Path(__file__).resolve().parent / "project.db")
# opens (or creates) the database file we'll be storing everything in

conn.execute("DROP TABLE IF EXISTS currencies")
conn.execute("DROP TABLE IF EXISTS exchange_rates")
# wipes the tables if they already exist so we don't get duplicate rows on rerun

conn.execute("""CREATE TABLE currencies (
    currency_code TEXT PRIMARY KEY,
    name TEXT,
    symbol TEXT
)""")
# one row per currency, this barely changes so it gets its own small table
# EX: USD, United States Dollar, $

conn.execute("""CREATE TABLE exchange_rates (
    date TEXT,
    base_code TEXT,
    quote_code TEXT,
    rate REAL
)""")
# one row per rate on a given date, this grows every time we fetch
# EX: 2026-09-17, USD, EUR, 0.92

# load the most recent dated currencies snapshot from the data folder
currency_files = sorted(DATA_DIR.glob("currencies_*.json"))
with open(currency_files[-1]) as f:
    currency_names = json.load(f)

for currency in currency_names:
    conn.execute(
        "INSERT OR REPLACE INTO currencies VALUES (?,?,?)",
        (currency["iso_code"], currency["name"], currency["symbol"]),
    )
# loops through every currency and inserts it into the currencies table

# load every dated rates snapshot in the data folder
for path in sorted(DATA_DIR.glob("rates_*.json")):
    with open(path) as f:
        rate_rows = json.load(f)
    for row in rate_rows:
        conn.execute(
            "INSERT INTO exchange_rates VALUES (?,?,?,?)",
            (row["date"], row["base"], row["quote"], row["rate"]),
        )
# loops through every rate in every snapshot and inserts it into the exchange_rates table

print("currencies rows:", conn.execute("SELECT COUNT(*) FROM currencies").fetchone()[0])
print("exchange_rates rows:", conn.execute("SELECT COUNT(*) FROM exchange_rates").fetchone()[0])

conn.commit()
conn.close()
print("rebuilt currency database")
# saves everything and closes the connection, this line just confirms it ran
