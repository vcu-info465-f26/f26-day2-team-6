Currency Conversion Rates Dashboard
Frankfuter API

Story Goal:
By November 12th, we can answer one real question about currency exchange rates by running a SQL query across data our code has been collecting since September 10.

Story Line:
As an international investor, I want to access current currency exchange rates, along with the corresponding currency symbols and countries, so that I can stay informed about global currency values and make better-informed decisions when monitoring international financial markets.

Mission Statement:
The purpose of this project is to collect and organize currency information from two related API endpoints so that users can easily query, review and compare currency data.

Foundation:
The first endpoint retrieves currency exchange rate information, including the exchange rate and the date associated with that rate. This allows the system to track how currencies are valued and when the rate was recorded.

The second endpoint retrieves information about currencies, including the country associated with the currency and its currency symbol. This provides additional context that helps identify and understand each currency.

The data from both endpoints is then brought together in the Build.db database. By combining the exchange rate, date, country, and currency symbol, the database creates a centralized dataset that can be used for comparison, analysis, and review.

Achievement: 
Our code runs, it pulls real data from two Frankfuter API endpoints, it writes dated snapshots, it
loads them into a database. That data is used to generate a factial summery about currency rates. I provides factial information queried from a chatbot. The data is then automatically refreshresed daily to keep up with real time changes. 

Hassan - Tester
Alana - Project Manager
Shanika - Reviewer
Amare - Review


## Dashboard (Sprint 3)

Live dashboard: https://team6-currency.streamlit.app/

Run locally from the repo root:

    pip install -r requirements.txt
    python -m streamlit run src/app.py