import sqlite3
from fetch_currency_names import get_currency_names
from fetch_rates import get_latest_rates


conn = sqlite3.connect("project.db")
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

currency_names = get_currency_names()
# stores the list of currency dictionaries from the API (same messy data as before)

for currency in currency_names:
    conn.execute(
        "INSERT INTO currencies VALUES (?,?,?)",
        (currency["iso_code"], currency["name"], currency["symbol"]),
    )
# loops through every currency and inserts it into the currencies table
# iso_code is what the API calls it, we're just calling it currency_code in our table

rate_rows = get_latest_rates()
# stores the list of rate dictionaries from the API

for row in rate_rows:
    conn.execute(
        "INSERT INTO exchange_rates VALUES (?,?,?,?)",
        (row["date"], row["base"], row["quote"], row["rate"]),
    )
# loops through every rate and inserts it into the exchange_rates table
# base_code and quote_code are what link back to the currency_code in the other table

conn.commit()
conn.close()
print("rebuilt currency database")
# saves everything and closes the connection, this line just confirms it ran