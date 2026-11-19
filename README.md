Currency Conversion Rates Dashboard
Frankfuter API

Story Goal:
By November 19, someone using our dashboard will no longer see cryptocurrencies mixed in with traditional currencies. Crypto gets its own tab, where Bitcoin and the others are only compared to each other. Traditional currencies stay in the main charts and rankings, each with a small country flag beside it so a visitor can tell at a glance where that currency comes from.

Story Line:
As an international investor, I want a brief inforamative summary of current international exchange rates data and to be able to query data via a chatbot so that I can stay informed about global currency values that interest me.

Mission Statement:
The purpose of this project is to collect and organize currency information from two related API endpoints so that users can easily query, review and compare currency data.

Foundation:
The first endpoint retrieves currency exchange rate information, including the exchange rate and the date associated with that rate. This allows the system to track how currencies are valued and when the rate was recorded.

The second endpoint retrieves information about currencies, including the country associated with the currency and its currency symbol. This provides additional context that helps identify and understand each currency.

The data from both endpoints is then brought together in the Build.db database. By combining the exchange rate, date, country, and currency symbol, the database creates a centralized dataset that can be used for comparison, analysis, and review.

Achievement: 
Our code runs, it pulls real data from two Frankfuter API endpoints, it writes dated snapshots, and loads them into a database. That data is used to generate a factual summery about currency rates. It provides factual information queried from a chatbot. The data is then automatically refreshresed daily to keep up with real time changes. 

The AI summary is built in Summary.py and updates daily with a 30 day window of exchange rate data. Secrets needed: GROQ_API_KEY

Hassan - Tester

Alana - Project Manager

Shanika - Reviewer

Amare - Review


## Dashboard (Sprint 3)

Live dashboard: https://team6-currency.streamlit.app/

Run locally from the repo root:

    pip install -r requirements.txt
    python -m streamlit run src/app.py
