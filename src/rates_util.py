import sqlite3

import pandas as pd

# Codes in the data that are not a country's money (precious metals, IMF unit, trade-block unit)
NON_COUNTRY_CODES = {"XAU", "XAG", "XPD", "XPT", "XDR", "CMD"}

METAL_CODES = {"XAU", "XAG", "XPD", "XPT"}

# Frankfurter labels every symbol it publishes as "currency", "crypto" or
# "metal" in the `type` field of /v2/currencies, and in November 2026 it started
# publishing crypto there. Nothing in this project read that field, so Bitcoin
# arrived in the rankings as though it were a country's money - ranked on a
# fortnight of history against currencies with years of it. `asset_type` is now
# the single place that decides which group a code belongs to, and the groups
# are never ranked against each other.
#
# Snapshots taken before November 2026 carry no `type` field, so this list is
# the fallback for them. Newer snapshots carry the type and this is unused.
KNOWN_CRYPTO = {
    "AAVE", "ADA", "ALGO", "APT", "ARB", "ATOM", "AVAX", "AXS", "BCH", "BTC",
    "CHZ", "CRV", "DOT", "ENA", "ETC", "ETH", "FIL", "HBAR", "ICP", "LINK",
    "LTC", "MANA", "NEAR", "ONDO", "POL", "SNX", "SOL", "SUI", "UNI", "USDC",
    "USDT", "XLM", "XRP", "XTZ", "ZEC",
}


def asset_type(code, declared=None):
    """Which group a code belongs to: 'currency', 'crypto', 'metal' or 'unit'.

    `declared` is Frankfurter's own label where the snapshot has one. 'unit' is
    the IMF special drawing right and the commodity index - not a metal, and not
    anybody's money either. Only 'currency' appears in the main rankings.
    """
    if declared == "crypto" or code in KNOWN_CRYPTO:
        return "crypto"
    if declared == "metal" or code in METAL_CODES:
        return "metal"
    if code in NON_COUNTRY_CODES:
        return "unit"
    return "currency"


# Flag pictures, not flag emoji: an emoji needs a font the reader may not have
# (Chrome on Windows and Linux draws it as two letters), while an image renders
# everywhere. They come from flagcdn.com, addressed by ISO 3166-1 alpha-2
# country code.
#
# Checked against the ISO 4217 currency-to-country table: of the 161 national
# currencies in this data 148 belong to exactly one country, and in every one
# of those cases the first two letters of the currency code are that country's
# code - USD -> US, JPY -> JP, with no exceptions at all. So that rule is the
# mapping, and only the currencies no single country owns need listing here:
# XAF (6 countries), XOF (8), XCD (8), XPF (3), XCG (2), the IMF's XDR, the
# commodity index CMD, and ANG, which Curacao and Sint Maarten are retiring in
# favour of XCG. The euro is the exception among the exceptions - it has a flag
# of its own.
NO_FLAG_CODES = {"XAF", "XOF", "XCD", "XCG", "XPF", "XDR", "CMD", "ANG"}
FLAG_OVERRIDES = {"EUR": "eu"}
FLAG_IMAGE = "https://flagcdn.com/{}/{}.png"


def flag_url(code, declared=None, width="w40"):
    """The flag image for a currency code, or None where no one flag fits.

    None for cryptocurrencies, metals and accounting units, and for currencies
    several countries share. An empty cell is better than a placeholder there:
    the code and the name beside it already say what the row is.

    `width` is one of flagcdn's sizes (w20, w40, w80...): small for a tooltip,
    larger where the flag is drawn big enough to see the detail.
    """
    if asset_type(code, declared) != "currency" or code in NO_FLAG_CODES:
        return None
    country = FLAG_OVERRIDES.get(code)
    if country is None:
        if len(code) < 2 or not code[:2].isalpha():
            return None
        country = code[:2].lower()
    return FLAG_IMAGE.format(width, country)


def load_rates(db_path):
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT exchange_rates.date, exchange_rates.base_code, exchange_rates.quote_code,
                   currencies.name, currencies.symbol, currencies.type,
                   exchange_rates.rate
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
    usd_rows["type"] = "currency"
    return pd.concat([out, usd_rows[out.columns]], ignore_index=True).dropna(subset=["rate"])


def pct_changes(rates, base, scope="traditional"):
    """% change in value of each currency against the base, first day to last day.

    scope="traditional" ranks only countries' money. scope="crypto" ranks only
    cryptocurrencies. The two are never mixed: crypto entered this data in
    November 2026 while the currencies go back years, so a single ranking across
    both would be comparing a fortnight's move with a five-year one.
    """
    rows = []
    for code, grp in rates.sort_values("date").groupby("quote_code"):
        if code == base or len(grp) < 2:
            continue
        kind = asset_type(code, grp.iloc[0].get("type"))
        if kind != ("crypto" if scope == "crypto" else "currency"):
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
