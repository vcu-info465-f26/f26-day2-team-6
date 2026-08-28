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