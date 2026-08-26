from pathlib import Path

import build_db
import chart
import fetch

# YOUR WORK, STEP 1 OF 2
# Uncomment this once you have created src/analyze.py on your branch:
#



def main():
    Path("output").mkdir(exist_ok=True)

    forecast = fetch.api_call()
    build_db.save_to_db(forecast)
    chart.make_chart()


    print("Done. Look in output/ for chart.png and weather.db,")
    print("then run 'git status' and notice that neither one is listed.")


if __name__ == "__main__":
    main()