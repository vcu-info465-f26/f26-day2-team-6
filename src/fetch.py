"""Getting the data. One job: go to the API and come back with a table.

This file knows about Open-Meteo. Nothing else in the project does, which
means changing to a different API is a change to this file alone.
"""

import pandas as pd
import requests

# Richmond, VA. Change these two numbers and the whole program is about
# somewhere else, which is worth trying once.
LATITUDE = 37.54
LONGITUDE = -77.44


def api_call():
    """Fetch a 7-day forecast from Open-Meteo and return it as a table.

    Open-Meteo needs no API key and no signup, which is why we start here
    rather than with something that wants a credential on night one.

    The response is JSON shaped like this -- parallel lists, one entry
    per day, lined up by position:

        {"daily": {"time":               ["2026-08-27", "2026-08-28", ...],
                   "temperature_2m_max": [88.1, 91.4, ...],
                   "temperature_2m_min": [70.2, 72.8, ...],
                   "precipitation_sum":  [0.0, 0.12, ...]}}

    Parallel lists like that become table columns directly, which is why
    the dataframe below is four lines rather than a loop.

    Returns the table. It does not print it and it does not save it --
    a function that prints can only ever be used for printing, while a
    function that returns can be printed, stored, or handed onward.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "temperature_unit": "fahrenheit",
        "timezone": "America/New_York",
        "forecast_days": 7,
    }

    response = requests.get(url, params=params, timeout=10)

    # If the server said no, stop here with a clear error rather than
    # carrying on and failing later with a confusing one.
    response.raise_for_status()

    daily = response.json()["daily"]

    # Renaming the columns is not cosmetic. You are about to write SQL
    # against this table, and "high" is a nicer thing to type in a
    # WHERE clause than "temperature_2m_max" is.
    return pd.DataFrame(
        {
            "day": daily["time"],
            "high": daily["temperature_2m_max"],
            "low": daily["temperature_2m_min"],
            "rain": daily["precipitation_sum"],
        }
    )

if __name__ == "__main__":
    poop=api_call()
    print(poop)