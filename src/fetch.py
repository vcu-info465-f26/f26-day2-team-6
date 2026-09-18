# Fetch the latest exchange rates from Frankfurter and return it as a table.
import pandas as pd
import requests

BASE_CURRENCY = "USD"
QUOTE_CURRENCIES = "EUR,GBP,JPY"


def api_call():
    url = "https://api.frankfurter.dev/v2/rates"
    params = {
        "base": BASE_CURRENCY,
        "quotes": QUOTE_CURRENCIES,
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()  # stop here with a clear error if the request failed

    rows = response.json() 
    return pd.DataFrame(rows)  # list of dicts converts straight into a table, one dict per row


if __name__ == "__main__":
    rates = api_call()
    print(rates)


# If I am not in class today, here is how to run it to get real data from our Frankfurter API:
# 1. Open a terminal in the Codespace.
# 2. Run: python src/fetch.py
# 3. Expected output: a small table with columns date, base, quote, rate,
#    one row per currency (EUR, GBP, JPY), with today's date and real exchange rates.