"""Drawing the picture. One job: read the database, write a PNG.

Note that matplotlib is never imported here. pandas plots by calling it
underneath, so it has to be installed -- which is why it is in
requirements.txt -- but you reach the figure through the object that
.plot() hands back.

A Codespace has no screen, so plt.show() would do nothing at all.
Saving a file works fine. Click output/chart.png in the sidebar to see it.
"""

import sqlite3
from pathlib import Path

import pandas as pd

# NOTE: this same line appears in build_db.py. Two copies of one fact
# will eventually disagree with each other. We will fix that later.
DB_PATH = Path("output") / "weather.db"

CHART_PATH = Path("output") / "chart.png"


def make_chart():
    """Read the forecast back out of the database and save a bar chart.

    Reading from the database rather than from the table we already had
    in memory is slightly redundant, on purpose. If the chart appears,
    the write worked. It is also the shape the rest of this course uses:
    fetch once, store, and everything downstream reads from the store.

    pd.read_sql_query runs SQL and hands back a dataframe, which is the
    bridge between the database and pandas.
    """
    conn = sqlite3.connect(DB_PATH)
    daily = pd.read_sql_query(
        "SELECT day, high, low FROM forecast ORDER BY day", conn
    )
    conn.close()

    axes = daily.set_index("day").plot(
        kind="bar",
        title="Richmond 7-day forecast (F)",
    )
    axes.set_xlabel("")
    axes.get_figure().savefig(CHART_PATH, bbox_inches="tight", dpi=120)


if __name__ == "__main__":
    # Testing this file on its own. From the repo root:
    #
    #     python src/chart.py
    #
    # Unlike the other two, this one needs something to read, so run
    # build_db.py or main.py first. Checking for the file and saying so
    # plainly beats letting sqlite3 raise "no such table: forecast",
    # which reads like a bug in the code rather than a missing step.
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}.")
        print("Run 'python src/build_db.py' or 'python src/main.py' first.")
    else:
        make_chart()
        print(f"Wrote {CHART_PATH} ({CHART_PATH.stat().st_size} bytes).")
        print("Click it in the file sidebar to see it.")