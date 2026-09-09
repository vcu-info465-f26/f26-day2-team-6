import requests
import pandas as pd

def get_currency_names():

    currency_names_url = "https://api.frankfurter.dev/v2/currencies"
    # fetch the list of currencies (the names of the currencies & their symbols)
    currency_names_response = requests.get(currency_names_url)

    # turn the response into a list of currency dictionaries, one dictionary per currency
    currency_names_data = currency_names_response.json()
    return currency_names_data


# The Block Below Puts the Response in a Table To Print

currency_names_rows = get_currency_names()
# stores the list of currency data dictionaries (Messy Looking Data)

currency_names_df = pd.DataFrame(currency_names_rows)
# Turns the list of currency data dictionaries from the API response into a dataframe/table

currency_names_df = currency_names_df.drop(columns=["iso_numeric", "start_date", "end_date"])
# Drops the numeric codes & useless dates (keeps code, name, and symbol EX: USD, United States Dollar, $)

print(currency_names_df)