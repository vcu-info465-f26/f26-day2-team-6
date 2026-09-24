import json
from datetime import date
import requests

def get_currency_names():
    currency_names_url = "https://api.frankfurter.dev/v2/currencies"
    # fetch the list of currencies (the names of the currencies & their symbols)
    currency_names_response = requests.get(currency_names_url)

    # turn the response into a list of currency dictionaries, one dictionary per currency
    currency_names_data = currency_names_response.json()
    return currency_names_data

if __name__ == "__main__":
    rows = get_currency_names()
    print(rows[0])

    # save a dated snapshot so every run adds a new file instead of overwriting one
    today = date.today().isoformat()
    with open(f"src/data/currencies_{today}.json", "w") as f:
        json.dump(rows, f)
