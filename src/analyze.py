# This file reads weather data from the database and finds the hottest day.
# get_max() takes no input and returns a table with the day and its highest temperature.
# This works only because SQLite lets the day match the highest temperature
# without a GROUP BY, which most other databases would reject.

import sqlite3
from pathlib import Path

import pandas as pd
DB_PATH = Path("output") / "weather.db"
def get_max():
    conn = sqlite3.connect(DB_PATH)
    hottest = pd.read_sql_query(
            "SELECT day, max(high) FROM forecast ", conn
        )
    conn.close()
    return hottest
if __name__=="__main__":
    print(get_max())