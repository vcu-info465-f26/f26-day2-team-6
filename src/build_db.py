"""Storing the data. One job: put the table somewhere it will stay.

A SQLite database is a single file. There is no server to start, no
connection string, and no password -- connect() simply creates the file
if it is not already there.

sqlite3 ships with Python, which is why it is not in requirements.txt.
"""

import sqlite3
from pathlib import Path

# NOTE: this same line appears in chart.py. Two copies of one fact will
# eventually disagree with each other. We will fix that properly later.
DB_PATH = Path("output") / "weather.db"


def save_to_db(forecast):
    """Write the forecast table into the database.

    Four moves, every time: connect, execute, commit, close.

    Forgetting commit() is the one that hurts, because nothing errors --
    the program finishes cleanly and the rows are simply not there.
    """
    conn = sqlite3.connect(DB_PATH)

    # IF NOT EXISTS is what makes this safe to run twice. Without it, the
    # second run crashes on a table that already exists.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast (
            day  TEXT PRIMARY KEY,
            high REAL,
            low  REAL,
            rain REAL
        )
        """
    )

    rows = list(forecast.itertuples(index=False, name=None))

    # The ? placeholders are not a style preference. Building this string
    # with an f-string breaks on any value containing an apostrophe, and
    # is the hole SQL injection goes through.
    #
    # INSERT OR REPLACE means re-running today overwrites today's row
    # instead of adding a second copy. Run the program five times and you
    # still have seven rows.
    conn.executemany(
        "INSERT OR REPLACE INTO forecast (day, high, low, rain) VALUES (?, ?, ?, ?)",
        rows,
    )

    conn.commit()
    conn.close()

if __name__ == "__main__":
    # Testing this file on its own. From the repo root:
    #
    #     python src/build_db.py
    #
    # Notice that this never calls the API. Storing data and fetching
    # data are separate jobs, so they can be tested separately -- and
    # that is most of the reason they live in separate files. This test
    # works on a plane with no wifi.
    import pandas as pd

    Path("output").mkdir(exist_ok=True)

    fake = pd.DataFrame(
        {
            "day": ["2026-08-27", "2026-08-28"],
            "high": [88.1, 91.4],
            "low": [70.2, 72.8],
            "rain": [0.0, 0.12],
        }
    )

    save_to_db(fake)
    save_to_db(fake)  # deliberately twice -- should still be 2 rows

    conn = sqlite3.connect(DB_PATH)
    for row in conn.execute("SELECT * FROM forecast ORDER BY day"):
        print(row)
    count = conn.execute("SELECT COUNT(*) FROM forecast").fetchone()[0]
    conn.close()

    print("row count:", count, "(should be 2, not 4)")