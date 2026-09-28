#Run the code below in terminal to generate URLs for dashboard and interactive chart. 
#python -m streamlit run src/app.py

import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from pathlib import Path

st.set_page_config(page_title="Currency Dashboard", layout="wide")

DB_PATH = Path(__file__).resolve().parent / "project.db"


@st.cache_data
def load_data():
    with sqlite3.connect(DB_PATH) as conn:
        df_rates = pd.read_sql_query(
            "SELECT date, base_code, quote_code, rate FROM exchange_rates",
            conn,
        )

    df_rates["date"] = pd.to_datetime(df_rates["date"])
    return df_rates


st.title("Currency Exchange Rates")
st.caption("Explore historical rates stored in the local currency database.")

if not DB_PATH.exists():
    st.error("The currency database has not been built yet.")
    st.code("python src/build_db.py", language="bash")
    st.stop()

rates = load_data()
if rates.empty:
    st.info("The database does not contain any exchange-rate records yet.")
    st.stop()

base_codes = sorted(rates["base_code"].dropna().unique())
base_code = st.selectbox("Base currency", base_codes)
base_rates = rates[rates["base_code"] == base_code]
quote_codes = sorted(base_rates["quote_code"].dropna().unique())
quote_code = st.selectbox("Quote currency", quote_codes)

selected_rates = base_rates[base_rates["quote_code"] == quote_code].sort_values("date")
latest_rate = selected_rates.iloc[-1]

metric_column, date_column = st.columns(2)
metric_column.metric(
    f"1 {base_code} in {quote_code}",
    f"{latest_rate['rate']:.6g}",
)
date_column.metric("Latest observation", latest_rate["date"].strftime("%Y-%m-%d"))

figure = px.line(
    selected_rates,
    x="date",
    y="rate",
    markers=True,
    title=f"{base_code} to {quote_code}",
    labels={"date": "Date", "rate": f"Rate ({quote_code})"},
)
st.plotly_chart(figure, use_container_width=True)

st.subheader("Rate history")
st.dataframe(
    selected_rates.sort_values("date", ascending=False),
    hide_index=True,
    use_container_width=True,
)