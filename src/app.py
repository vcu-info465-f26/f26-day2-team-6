#Run the code below in terminal to generate URLs for dashboard and interactive chart. 
#python -m streamlit run src/app.py

import subprocess
import sys
import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from pathlib import Path

st.set_page_config(page_title="Currency Dashboard", layout="wide")

DB_PATH = Path(__file__).resolve().parent / "project.db"
ROOT = Path(__file__).resolve().parent.parent


@st.cache_data
def load_data():
    with sqlite3.connect(DB_PATH) as conn:
        df_rates = pd.read_sql_query(
            """
            SELECT exchange_rates.date,
                   exchange_rates.base_code,
                   exchange_rates.quote_code,
                   currencies.name,
                   currencies.symbol,
                   exchange_rates.rate
            FROM exchange_rates
            JOIN currencies
              ON exchange_rates.quote_code = currencies.currency_code
            """,
            conn,
        )

    df_rates["date"] = pd.to_datetime(df_rates["date"])
    return df_rates


st.title("Currency Exchange Rates")
st.caption("Explore historical rates stored in the local currency database.")

if not DB_PATH.exists():
    with st.spinner("Building the database from data/ ..."):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "build_db.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0 or not DB_PATH.exists():
        st.error("Could not build the database.")
        st.code(result.stderr or result.stdout)
        st.stop()

rates = load_data()
if rates.empty:
    st.info("The database does not contain any exchange-rate records yet.")
    st.stop()

base_codes = sorted(rates["base_code"].dropna().unique())
base_code = st.selectbox("Base currency", base_codes)
base_rates = rates[rates["base_code"] == base_code]
quote_codes = sorted(base_rates["quote_code"].dropna().unique())
quote_labels = (
    base_rates.drop_duplicates("quote_code")
    .set_index("quote_code")
    .apply(lambda row: f"{row.name} – {row['name']} ({row['symbol']})", axis=1)
    .to_dict()
)
quote_code = st.selectbox(
    "Quote currency",
    quote_codes,
    format_func=lambda code: quote_labels.get(code, code),
)

selected_rates = base_rates[base_rates["quote_code"] == quote_code].sort_values("date")
all_dates = base_rates["date"].dt.date
min_date, max_date = all_dates.min(), all_dates.max()
if min_date < max_date:
    start_date, end_date = st.slider(
        "Date range",
        min_value=min_date,
        max_value=max_date,
        value=(min_date, max_date),
        format="YYYY-MM-DD",
    )
else:
    start_date, end_date = min_date, max_date
range_mask = (base_rates["date"].dt.date >= start_date) & (base_rates["date"].dt.date <= end_date)
range_rates = base_rates[range_mask]
selected_rates = selected_rates[
    (selected_rates["date"].dt.date >= start_date) & (selected_rates["date"].dt.date <= end_date)
]
if selected_rates.empty:
    st.warning("No exchange-rate data in the selected date range. Please widen the range.")
    st.stop()

latest_rate = selected_rates.iloc[-1]

metric_column, date_column = st.columns(2)
metric_column.metric(
    f"1 {base_code} in {quote_code}",
    f"{latest_rate['rate']:.6g}",
)
date_column.metric("Latest observation", latest_rate["date"].strftime("%Y-%m-%d"))

st.subheader(f"{base_code} to {quote_code} exchange rate over time")
st.caption(
    f""
)
figure = px.line(
    selected_rates,
    x="date",
    y="rate",
    markers=True,
    title=f"{base_code} to {quote_code}",
    labels={"date": "Date", "rate": f"Rate ({quote_code})"},
)
st.plotly_chart(figure, use_container_width=True)

st.subheader("Currency % change over the selected dates")
st.caption(
    f"Each bar shows how much one currency gained or lost in value against {base_code} between the first and last day "
    "of the date range above. Green bars gained, red bars lost, sorted from biggest gain to biggest loss. "
    "Drag the Date range slider to change the window and the bars update; hover a bar for its exact %."
)
# Codes in the fetched data that are not a country's money (precious metals, IMF unit, trade-bloc unit)
NON_COUNTRY_CODES = {"XAU", "XAG", "XPD", "XPT", "XDR", "CMD"}
changes = []
for code, grp in range_rates.sort_values("date").groupby("quote_code"):
    if code in NON_COUNTRY_CODES or code == base_code:
        continue
    if len(grp) < 2:
        continue
    first_rate, last_rate = grp["rate"].iloc[0], grp["rate"].iloc[-1]
    if first_rate and last_rate:
        changes.append({"quote_code": code, "name": str(grp["name"].iloc[0] or code), "pct_change": (first_rate / last_rate - 1) * 100})
changes_df = pd.DataFrame(changes, columns=["quote_code", "name", "pct_change"])
if changes_df.empty:
    st.info("Not enough data in this date range to calculate % changes. Please widen the range.")
else:
    changes_df = changes_df.sort_values("pct_change", ascending=False)
    changes_df["direction"] = changes_df["pct_change"].apply(lambda v: "Gained" if v >= 0 else "Lost")
    bar_figure = px.bar(
        changes_df,
        x="pct_change",
        y="quote_code",
        orientation="h",
        color="direction",
        custom_data=["name"],
        color_discrete_map={"Gained": "#2e7d32", "Lost": "#c62828"},
        labels={"quote_code": "Currency", "pct_change": f"% change vs {base_code}", "direction": ""},
    )
    # Horizontal bars so every currency code sits right next to its own bar and stays readable
    bar_codes = list(changes_df["quote_code"])
    bar_figure.update_yaxes(
        categoryorder="array",
        categoryarray=bar_codes[::-1],
        tickmode="array",
        tickvals=bar_codes,
        ticktext=bar_codes,
        tickfont={"size": 11},
    )
    bar_figure.update_xaxes(side="top")
    bar_figure.update_layout(height=max(400, 18 * len(bar_codes) + 120), bargap=0.2)
    bar_figure.update_traces(
        hovertemplate="<b>%{y}</b>: %{customdata[0]}<br>%{x:+.2f}% vs " + base_code + "<extra></extra>"
    )
    st.plotly_chart(bar_figure, use_container_width=True)

st.subheader("Rate history")
st.dataframe(
    selected_rates.sort_values("date", ascending=False),
    hide_index=True,
    use_container_width=True,
)
