import requests
import json
from datetime import date

def get_latest_rates(base="USD", quotes=None):
    url = "https://api.frankfurter.dev/v2/rates"

    # send the request
    response = requests.get(url, params={"base": base, "quotes": quotes})

    # turn the response into a python list of rows
    data = response.json()

    return data

# run it and print what came back
if __name__ == "__main__":
    rows = get_latest_rates()
    print(type(rows))
    print(rows)

    today = date.today().isoformat()
    with open(f"src/data/rates_{today}.json", "w") as f:
        json.dump(rows, f)