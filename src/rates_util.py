import sqlite3

import pandas as pd

# Codes in the data that are not a country's money (precious metals, IMF unit, trade-block unit)
NON_COUNTRY_CODES = {"XAU", "XAG", "XPD", "XPT", "XDR", "CMD"}


def load_rates(db_path):
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT exchange_rates.date, exchange_rates.base_code, exchange_rates.quote_code,
                   currencies.name, currencies.symbol, exchange_rates.rate
            FROM exchange_rates
            JOIN currencies ON exchange_rates.quote_code = currencies.currency_code
            """,
            conn,
        )
    df["date"] = pd.to_datetime(df["date"])
    return df


def rebase(rates, base):
    """Re-express the USD-based rates in any other base currency (cross rates)."""
    usd = rates[rates["base_code"] == "USD"]
    if base == "USD":
        return usd.copy()
    # units of the new base per 1 USD, one value per date
    per_usd = usd[usd["quote_code"] == base].drop_duplicates("date").set_index("date")["rate"]
    out = usd[usd["quote_code"] != base].copy()
    out["rate"] = out["rate"] / out["date"].map(per_usd)
    out["base_code"] = base
    usd_rows = (1 / per_usd).rename("rate").reset_index()
    usd_rows["base_code"] = base
    usd_rows["quote_code"] = "USD"
    usd_rows["name"] = "US Dollar"
    usd_rows["symbol"] = "$"
    return pd.concat([out, usd_rows[out.columns]], ignore_index=True).dropna(subset=["rate"])


def pct_changes(rates, base):
    """% change in value of each currency against the base, first day to last day."""
    rows = []
    for code, grp in rates.sort_values("date").groupby("quote_code"):
        if code in NON_COUNTRY_CODES or code == base or len(grp) < 2:
            continue
        first, last = grp.iloc[0], grp.iloc[-1]
        rows.append({
            "quote_code": code,
            "name": first["name"],
            "first_rate": first["rate"],
            "last_rate": last["rate"],
            "pct_change": (first["rate"] / last["rate"] - 1) * 100,
        })
    cols = ["quote_code", "name", "first_rate", "last_rate", "pct_change"]
    return pd.DataFrame(rows, columns=cols).sort_values("pct_change", ascending=False)


def invest_one(row, amount=100):
    """What `amount` of the base currency put into one currency on the first day is worth on the last day."""
    units = amount * row["first_rate"]   # local money bought on the first day
    return units / row["last_rate"]      # converted back to the base on the last day


def invest(changes, amount=100):
    """The same calculation, for the biggest gainer and the biggest loser."""
    results = {}
    for label, row in ("best", changes.iloc[0]), ("worst", changes.iloc[-1]):
        results[label] = {
            "name": row["name"],
            "quote_code": row["quote_code"],
            "end": invest_one(row, amount),
        }
    return results


def load_currency_info(db_path):
    """currency code -> (name, symbol) for every currency in the database."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT currency_code, name, symbol FROM currencies").fetchall()
    return {code: (name, symbol or "") for code, name, symbol in rows}


def long_date(d):
    """A date object -> 'September 17th 2026', so the page never shows 2026-09-17."""
    day = d.day
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{d.strftime('%B')} {day}{suffix} {d.year}"



# Currency names that do not take an "s" in the plural, so a sentence reads
# "fewer Japanese Yen" rather than "fewer Japanese Yens".
INVARIANT_PLURALS = {
    "Yen", "Won", "Guarani", "Guaraní", "Baht", "Dong", "Rand", "Renminbi", "Yuan", "Riel", "Kip",
    "Ngultrum", "Loti", "Maloti", "Dalasi", "Lilangeni", "Emalangeni",
    "Taka", "Kyat", "Birr", "Nakfa", "Quetzal", "Rupiah", "Ringgit",
}


def plural(name):
    """'Colombian Peso' -> 'Colombian Pesos', 'Japanese Yen' -> 'Japanese Yen'."""
    last = name.split()[-1]
    if last in INVARIANT_PLURALS:
        return name
    if last.endswith(("s", "x", "z", "ch", "sh")):
        return name + "es"
    return name + "s"
