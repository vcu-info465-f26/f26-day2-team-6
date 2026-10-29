#Run the code below in terminal to generate URLs for dashboard and interactive chart. 
#python -m streamlit run src/app.py

import subprocess
import sys
import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from chat import build_chat_context, show_chat
from rates_util import (
    NON_COUNTRY_CODES,
    invest_one,
    load_currency_info,
    long_date,
    pct_changes,
    plural,
    rebase,
)
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

# any currency can be the base: the data is USD-based, so other bases are cross rates
# --- AI summary, with selectors that recalculate it -----------------------
# Every number here is worked out in Python from the database. The model is
# never asked to do arithmetic, so these figures cannot be invented.
summary_file = ROOT / "data" / "summary.md"
currency_info = load_currency_info(DB_PATH)


def selector_label(code):
    """'USD' -> 'USD - United States Dollar $', used in every currency dropdown."""
    name, symbol = currency_info.get(code, (code, ""))
    return f"{code} - {name} {symbol}".strip()


def chart_label(code):
    """'USD' -> '(USD$)', used in chart headings."""
    symbol = currency_info.get(code, (code, ""))[1]
    return f"({code}{symbol})"

with st.container(border=True):
    st.subheader("AI summary")
    compare_base_codes = sorted((set(rates["quote_code"]) | {"USD"}) - NON_COUNTRY_CODES)
    compare_base = st.selectbox(
        "Base currency for this comparison",
        compare_base_codes,
        index=compare_base_codes.index("USD"),
        format_func=selector_label,
    )
    # The summary follows this date range, so changing it changes every figure below.
    all_days = rates["date"].dt.date
    full_start, full_end = all_days.min(), all_days.max()
    if full_start < full_end:
        summary_start, summary_end = st.slider(
            "Date range for this summary",
            min_value=full_start,
            max_value=full_end,
            value=(full_start, full_end),
            format="YYYY-MM-DD",
        )
    else:
        summary_start, summary_end = full_start, full_end
    window = rates[(all_days >= summary_start) & (all_days <= summary_end)]
    compare_changes = pct_changes(rebase(window, compare_base), compare_base)
    if compare_changes.empty:
        st.info("Not enough data in this date range to compare currencies.")
    else:
        compare_codes = sorted(compare_changes["quote_code"])
        compare_names = dict(zip(compare_changes["quote_code"], compare_changes["name"]))
        top_code = compare_changes.iloc[0]["quote_code"]
        bottom_code = compare_changes.iloc[-1]["quote_code"]
        first_date = window["date"].min().date()
        last_date = window["date"].max().date()
        first_day = long_date(first_date)
        last_day = long_date(last_date)
        col_a, col_b, col_amount = st.columns(3)
        with col_a:
            code_a = st.selectbox(
                "First currency",
                compare_codes,
                index=compare_codes.index(top_code),
                format_func=selector_label,
            )
        with col_b:
            code_b = st.selectbox(
                "Second currency",
                compare_codes,
                index=compare_codes.index(bottom_code),
                format_func=selector_label,
            )
        with col_amount:
            amount = st.number_input(
                f"Amount in {compare_base}",
                min_value=1.0,
                value=100.0,
                step=10.0,
                format="%.2f",
            )
        base_name, base_symbol = currency_info.get(compare_base, (compare_base, ""))

        def money(value):
            """100.0 -> '$100', 103.13 -> '$103.13', falling back to the code."""
            text = f"{value:,.2f}"
            if text.endswith(".00"):
                text = text[:-3]
            return f"{base_symbol}{text}" if base_symbol else f"{text} {compare_base}"

        # The bordered boxes come first, grouped by currency: the investment, then the trip.
        # Each currency is judged on its own figure, so both can be green or both red.
        for code in (code_a, code_b):
            row = compare_changes[compare_changes["quote_code"] == code].iloc[0]
            ending = invest_one(row, amount)
            grew = ending >= amount
            invested = (
                f"**{money(amount)} Investment {'Gained' if grew else 'Lost'}:** "
                f"A {money(amount)} investment in the {row['name']} on {first_day} "
                f"would be worth {money(ending)} on {last_day}."
            ).replace("$", "\\$")
            if grew:
                st.success(invested)
            else:
                st.error(invested)
            # A currency that gained costs your base currency more, so the trip is dearer.
            change = row["pct_change"]
            if change > 0:
                trip = (
                    f"\U0001F30D Your {base_name} buys fewer {plural(row['name'])} "
                    f"than it did on {first_day}, so expect things to feel slightly "
                    f"more expensive there as a traveller."
                )
            elif change < 0:
                trip = (
                    f"\U0001F30D Your {base_name} buys more {plural(row['name'])} "
                    f"than it did on {first_day}, so expect things to feel slightly "
                    f"cheaper there as a traveller."
                )
            else:
                trip = (
                    f"\U0001F30D Purchases as a traveller using the {base_name} "
                    f"should cost about the same where the {row['name']} is used."
                )
            trip = trip.replace("$", "\\$")
            if change > 0:
                st.error(trip)
            elif change < 0:
                st.success(trip)
            else:
                st.info(trip)
        if code_a == code_b:
            st.info("Pick two different currencies to compare them.")
        # The workflow writes one summary a day: USD, the top and bottom currency,
        # 100 units, the whole period. Any other selection has to be rebuilt here.
        showing_daily = (
            compare_base == "USD"
            and code_a == top_code
            and code_b == bottom_code
            and abs(amount - 100.0) < 0.005
            and first_date == full_start
            and last_date == full_end
        )
        if showing_daily and summary_file.exists():
            st.markdown(summary_file.read_text().replace("$", "\\$"))
        else:
            st.markdown(
                f"*Rebuilt for the currencies and dates you picked, so this is not today's "
                f"written summary. Worked out from the stored rates between {first_day} "
                f"and {last_day}.*"
            )
        for code in (code_a, code_b):
            row = compare_changes[compare_changes["quote_code"] == code].iloc[0]
            gained = row["pct_change"] >= 0
            spending = (
                f"so your {compare_base} buys less there than it used to"
                if gained
                else f"so your {compare_base} stretches further there than it used to"
            )
            st.markdown(
                (
                    f"**{row['name']} ({code})** {'gained' if gained else 'lost'} "
                    f"{abs(row['pct_change']):.2f}% in value against the {compare_base} "
                    f"between {first_day} and {last_day}. "
                    f"1 {compare_base} bought {row['first_rate']:,.4f} {code} on {first_day} "
                    f"and {row['last_rate']:,.4f} {code} on {last_day}, **{spending}.**"
                ).replace("$", "\\$")
            )

base_codes = sorted((set(rates["quote_code"]) | {"USD"}) - NON_COUNTRY_CODES)
base_code = st.selectbox(
    "Base currency",
    base_codes,
    index=base_codes.index("USD"),
    format_func=selector_label,
)
rates = rebase(rates, base_code)
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

st.subheader(
    (f"{chart_label(base_code)} to {chart_label(quote_code)} "
     "exchange rate over time").replace("$", "\\$")
)
st.caption(
    f""
)
figure = px.line(
    selected_rates,
    x="date",
    y="rate",
    markers=True,
    title=f"{chart_label(base_code)} to {chart_label(quote_code)}",
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
    show_count = st.selectbox("Currencies to display", [5, 10, 20, 50, 100], index=1)
    changes_df = changes_df.head(show_count)
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
    bar_figure.update_layout(height=450, bargap=0.3)    
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

# Prepare exchange-rate data for the chatbot
data_context = build_chat_context(range_rates, base_code)

# Display the chatbot
show_chat(data_context)