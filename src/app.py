# Run the code below in terminal to generate URLs for dashboard and interactive chart.
# python -m streamlit run src/app.py

import html
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import sqlite3
import streamlit as st

from chat import build_chat_context, show_chat
from countries import COUNTRY_CURRENCY, COUNTRY_NAMES
from rates_util import (
    NON_COUNTRY_CODES,
    asset_type,
    flag_url,
    invest_one,
    load_currency_info,
    long_date,
    pct_changes,
    plural,
    rebase,
)

st.set_page_config(page_title="Currency Dashboard", layout="wide")

DB_PATH = Path(__file__).resolve().parent / "project.db"
ROOT = Path(__file__).resolve().parent.parent
SUMMARY_FILE = ROOT / "data" / "summary.md"
SUMMARY_META = ROOT / "data" / "summary.json"


# --- colour roles -------------------------------------------------------------
# Diverging pair for "gained vs lost": blue <-> red. Validated for colour-vision
# deficiency in both themes. The old green/red pair is the one combination that
# red-green colourblind readers cannot separate, so the sign is also carried by
# the legend, the bar direction and the % label - never by colour alone.
# "up"/"down" encode gained/lost on the ranking bars and the single-series
# sparklines. "series_1"/"series_2" identify the two lines on the comparison
# chart: there, colour carries WHICH currency, not which way it moved - two
# currencies that both fell would otherwise draw two identical red lines.
LIGHT = {
    "up": "#2a78d6", "down": "#e34948", "line": "#2a78d6",
    "series_1": "#2a78d6", "series_2": "#eb6834",
    "grid": "#e1e0d9", "axis": "#898781",
}
DARK = {
    "up": "#3987e5", "down": "#e66767", "line": "#3987e5",
    "series_1": "#3987e5", "series_2": "#d95926",
    "grid": "#2c2c2a", "axis": "#898781",
}


def palette():
    """Pick the theme-appropriate steps. Falls back to light if Streamlit's
    version does not expose the active theme."""
    try:
        if st.context.theme.type == "dark":
            return DARK
    except Exception:
        try:
            if st.get_option("theme.base") == "dark":
                return DARK
        except Exception:
            pass
    return LIGHT


COLORS = palette()


# --- data ---------------------------------------------------------------------
SRC_DATA_DIR = Path(__file__).resolve().parent / "data"


def data_token():
    """Changes whenever the db or any source json file changes, so the
    cached frame is rebuilt instead of serving a stale snapshot."""
    stamps = [p.stat().st_mtime for p in SRC_DATA_DIR.glob("*.json")]
    if DB_PATH.exists():
        stamps.append(DB_PATH.stat().st_mtime)
    return max(stamps, default=0.0)


def missing_type_column():
    """True if the db was built before currencies were split into asset types.

    Such a database has no `type` column on `currencies`, so it has to be
    rebuilt even when its timestamp is newer than every json file.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(currencies)")}
    except sqlite3.Error:
        return True
    return "type" not in columns


def db_is_stale():
    """True if the db is missing, out of date, or built to the old schema."""
    if not DB_PATH.exists():
        return True
    if missing_type_column():
        return True
    built = DB_PATH.stat().st_mtime
    return any(p.stat().st_mtime > built for p in SRC_DATA_DIR.glob("*.json"))


@st.cache_data
def load_data(token):
    with sqlite3.connect(DB_PATH) as conn:
        df_rates = pd.read_sql_query(
            """
            SELECT exchange_rates.date,
                   exchange_rates.base_code,
                   exchange_rates.quote_code,
                   currencies.name,
                   currencies.symbol,
                   currencies.type,
                   exchange_rates.rate
            FROM exchange_rates
            JOIN currencies
              ON exchange_rates.quote_code = currencies.currency_code
            """,
            conn,
        )

    df_rates["date"] = pd.to_datetime(df_rates["date"])
    return df_rates


if db_is_stale():
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

rates = load_data(data_token())
if rates.empty:
    st.info("The database does not contain any exchange-rate records yet.")
    st.stop()

ALL_DAYS = rates["date"].dt.date
FULL_START, FULL_END = ALL_DAYS.min(), ALL_DAYS.max()
currency_info = load_currency_info(DB_PATH)

# Which group every code belongs to, read once from the frame. Frankfurter
# started publishing cryptocurrencies through the same endpoint as national
# currencies in November 2026, and until this split they were ranked side by
# side - Bitcoin's run since 2020 sat at the top of "biggest gainer" as if it
# were a country's money. CRYPTO_CODES is what the Crypto tab shows and what
# every other tab leaves out.
ASSET_TYPES = {
    code: asset_type(code, kind)
    for code, kind in rates.drop_duplicates("quote_code")[
        ["quote_code", "type"]
    ].values
}
CRYPTO_CODES = {code for code, kind in ASSET_TYPES.items() if kind == "crypto"}


# These close over `rates`, which is itself cached and does not change during a
# session. max_entries keeps a long history from pinning one frame per base
# currency in memory on a small host.
@st.cache_data(max_entries=4)
def redenominated(rates, threshold=10):
    """Currencies whose series contains a single-step jump of `threshold`x or more.

    A real exchange rate does not move tenfold between two consecutive
    observations. A redenomination does: Venezuela removed six zeros from the
    bolivar in 2021, so a 2020-to-2026 comparison reads as a +5,000% "gain" when
    the currency actually collapsed. The two endpoints are in different units, so
    any percent change across the break is meaningless and must not be ranked,
    summarised or described as an investment return.

    Returns {code: date of the break}.
    """
    broken = {}
    for code, group in rates.sort_values("date").groupby("quote_code"):
        series = group["rate"]
        series = series[series > 0]
        if len(series) < 2:
            continue
        ratio = (series / series.shift()).dropna()
        if ratio.empty:
            continue
        # symmetric, so a 1000x drop counts the same as a 1000x rise
        ratio = ratio.where(ratio >= 1, 1 / ratio)
        if (ratio >= threshold).any():
            broken[code] = group.loc[ratio.idxmax(), "date"].date()
    return broken


@st.cache_data(max_entries=4)
def rebased(base):
    return rebase(rates, base)


@st.cache_data(max_entries=16)
def changes_for(base, start, end):
    frame = rebased(base)
    days = frame["date"].dt.date
    window = frame[(days >= start) & (days <= end)]
    # cryptocurrencies are compared with each other on their own tab, never
    # against a country's money
    window = window[~window["quote_code"].isin(CRYPTO_CODES)]
    # a currency that was redenominated inside this window has endpoints in
    # different units, so its percent change is not a real move
    broken = redenominated(window)
    comparable = window[~window["quote_code"].isin(broken)]
    return pct_changes(comparable, base), window, broken


@st.cache_data(max_entries=16)
def crypto_changes_for(base, start, end):
    """The same calculation over cryptocurrencies only, for the Crypto tab."""
    frame = rebased(base)
    days = frame["date"].dt.date
    window = frame[(days >= start) & (days <= end)]
    window = window[window["quote_code"].isin(CRYPTO_CODES)]
    return pct_changes(window, base, scope="crypto"), window


def selector_label(code):
    """'USD' -> 'USD - United States Dollar $', used in every currency dropdown.

    No flag here: a dropdown label is plain text, so a flag could only be an
    emoji, and the platforms that lack the font would show two stray letters in
    front of every currency. The flags live in the rankings table, where a real
    image can be drawn.
    """
    name, symbol = currency_info.get(code, (code, ""))
    return f"{code} - {name} {symbol}".strip()


def flag_image(code, size=16):
    """The <img> for a currency's flag, or "" where no one flag fits it.

    An image rather than a flag emoji: emoji need a font the reader may not
    have, and Chrome on Windows and Linux draws them as two letters.
    """
    url = flag_url(code, ASSET_TYPES.get(code))
    if not url:
        return ""
    name = html.escape(currency_info.get(code, (code, ""))[0])
    return (
        f'<img src="{url}" alt="" title="{name}" style="height:{size}px;'
        f"border-radius:2px;vertical-align:-3px;margin-right:6px;"
        f'box-shadow:0 0 0 1px rgba(128,128,128,.25)">'
    )


def help_text(code):
    """What the question mark beside a figure reveals: flag, then full name.

    Streamlit renders help as markdown, and markdown can carry an image, so
    this is the one tooltip in the app that can show a real flag. A small
    flagcdn size, because the tooltip draws it at its natural width.
    """
    name = currency_info.get(code, (code, ""))[0]
    url = flag_url(code, ASSET_TYPES.get(code), "w20")
    return f"![]({url}) {name}" if url else name


def currency_chip(code, size=16):
    """A flag and the currency's full name, to sit under a bare code.

    Anywhere the dashboard shows only a code - a headline figure, a chart
    label - this says what the code stands for, so USD reads as the United
    States Dollar and BTC as Bitcoin. Hovering the name shows it too, which is
    what the title attribute is for. Cryptocurrencies get the name without a
    flag: they belong to no country.
    """
    name = html.escape(currency_info.get(code, (code, ""))[0])
    return (
        f'<div style="font-size:0.85rem;color:#898781;margin-top:-0.4rem;'
        f'margin-bottom:0.6rem">{flag_image(code, size)}'
        f'<span title="{name}">{name}</span></div>'
    )


def chart_label(code):
    """'USD' -> '(USD$)', used in chart headings."""
    symbol = currency_info.get(code, (code, ""))[1]
    return f"({code}{symbol})"


def load_summary():
    """The daily written summary plus the metadata saying what it covers.

    Deliberately not cached: re-running summary.py should show up on the next
    rerun without restarting the app.
    """
    text = SUMMARY_FILE.read_text() if SUMMARY_FILE.exists() else ""
    meta = {}
    if SUMMARY_META.exists():
        try:
            meta = json.loads(SUMMARY_META.read_text())
        except (ValueError, OSError):
            meta = {}
    return text, meta


def indexed(track):
    """Value of the currency against the base, rebased to 100 on the first day.

    Stored rates are units of currency per 1 base, so the raw series FALLS when a
    currency gains - the opposite of what a reader expects from "biggest gainer".
    Inverting and indexing fixes that and makes two currencies of wildly different
    scale (1,725,139 IRR vs 5,747 PYG) share one axis honestly, which a second
    y-axis would not. The last point lands on 100 + pct_change by construction, so
    the chart and the percentages always agree.
    """
    out = track.sort_values("date").copy()
    first = out["rate"].iloc[0]
    out["value"] = first / out["rate"] * 100
    return out


def comparison_chart(frames, labels, colors, dashes):
    """Two indexed series on one axis.

    Colour says which way the currency moved (blue gained, red lost). That alone
    cannot separate two currencies that both fell, so the dash pattern carries
    identity: first series solid, second dashed. Both channels are in the legend.
    """
    data = pd.concat(
        [f.assign(series=label) for f, label in zip(frames, labels)], ignore_index=True
    )
    figure = px.line(
        data,
        x="date",
        y="value",
        color="series",
        line_dash="series",
        color_discrete_map=dict(zip(labels, colors)),
        line_dash_map=dict(zip(labels, dashes)),
        labels={"date": "Date", "value": "Indexed to 100", "series": ""},
    )
    figure.update_traces(line={"width": 2}, hovertemplate="%{x|%Y-%m-%d}: %{y:.1f}<extra></extra>")
    # A series with only a handful of points draws a stub at one edge - a coin
    # that arrived last week against one with six years of history is a line a
    # few pixels long, easy to mistake for a missing series. Markers make those
    # points visible without changing anything about the long series.
    for trace in figure.data:
        if trace.x is not None and len(trace.x) <= 30:
            trace.update(mode="lines+markers", marker={"size": 6})
    figure.update_xaxes(gridcolor=COLORS["grid"], title=None)
    figure.update_yaxes(gridcolor=COLORS["grid"])
    figure.update_layout(
        height=300,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return figure


def sparkline(series, rising):
    """A small, axis-free line of one currency across the selected window.

    Rates are units of the currency per 1 base, so a currency that GAINED value
    shows a falling line. The colour carries gained/lost; the caption says which
    way to read the line.
    """
    figure = px.line(series, x="date", y="value")
    figure.update_traces(
        line={"color": COLORS["up"] if rising else COLORS["down"], "width": 2},
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1f} vs 100<extra></extra>",
    )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    figure.update_layout(
        height=90,
        margin={"l": 0, "r": 0, "t": 8, "b": 0},
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return figure


# --- period presets -----------------------------------------------------------
PRESET_DAYS = {"1M": 30, "6M": 182, "1Y": 365, "5Y": 1826}
PERIODS = ["1M", "6M", "YTD", "1Y", "5Y", "All", "Custom"]


def preset_range(label, min_date, max_date):
    if label == "All":
        return min_date, max_date
    if label == "YTD":
        start = date(max_date.year, 1, 1)
    else:
        start = max_date - timedelta(days=PRESET_DAYS[label])
    return max(start, min_date), max_date


def period_picker():
    """Segmented buttons where available, radio otherwise."""
    default = PERIODS.index("All")
    if hasattr(st, "segmented_control"):
        picked = st.segmented_control("Period", PERIODS, default=PERIODS[default])
        return picked or PERIODS[default]
    return st.radio("Period", PERIODS, index=default, horizontal=True)


# --- sidebar: the only place controls live ------------------------------------
with st.sidebar:
    st.header("Controls")
    st.caption("These settings drive every tab.")

    # a base is something you hold and spend, so this stays on national
    # currencies: no crypto, no metals, no IMF units
    base_codes = sorted(
        {code for code, kind in ASSET_TYPES.items() if kind == "currency"} | {"USD"}
    )
    base_code = st.selectbox(
        "Base currency",
        base_codes,
        index=base_codes.index("USD") if "USD" in base_codes else 0,
        format_func=selector_label,
        help="Rates are stored against the USD, so any other base is a cross rate.",
    )

    st.divider()
    period = period_picker()
    if period == "Custom":
        picked = st.date_input(
            "Custom range",
            value=(FULL_START, FULL_END),
            min_value=FULL_START,
            max_value=FULL_END,
            format="YYYY-MM-DD",
        )
        if isinstance(picked, tuple) and len(picked) == 2:
            start_date, end_date = picked
        else:
            start_date, end_date = FULL_START, FULL_END
    else:
        start_date, end_date = preset_range(period, FULL_START, FULL_END)
    st.caption(f"{long_date(start_date)} to {long_date(end_date)}")

    st.divider()
    amount = st.number_input(
        f"Amount in {base_code}",
        min_value=1.0,
        value=100.0,
        step=10.0,
        format="%.2f",
        help="Used for the 'what would this have been worth' figures.",
    )

base_name, base_symbol = currency_info.get(base_code, (base_code, ""))


def money(value):
    """100.0 -> '$100', 103.13 -> '$103.13', falling back to the code."""
    text = f"{value:,.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    return f"{base_symbol}{text}" if base_symbol else f"{text} {base_code}"


def fmt_rate(value):
    """Rates span 1,725,139 (IRR) to 0.00024 (gold). Fixed decimal places make one
    of those unreadable, so scale the precision to the magnitude."""
    if value is None or value != value:  # NaN
        return "n/a"
    size = abs(value)
    if size >= 10000:
        return f"{value:,.0f}"
    if size >= 100:
        return f"{value:,.2f}"
    if size >= 1:
        return f"{value:,.4f}"
    if size >= 0.01:
        return f"{value:.4f}"
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def esc(text):
    """Streamlit markdown reads a bare $ as the start of LaTeX."""
    return text.replace("$", "\\$")


changes, window, broken = changes_for(base_code, start_date, end_date)
base_rates = rebased(base_code)

st.title("Currency Exchange Rates")
st.caption(f"{long_date(start_date)} to {long_date(end_date)}, measured against the {base_name}.")

if changes.empty:
    st.warning(
        "Not enough data in this date range to compare currencies. "
        "Widen the period in the sidebar."
    )
    st.stop()

first_date = window["date"].min().date()
last_date = window["date"].max().date()
first_day = long_date(first_date)
last_day = long_date(last_date)
top_code = changes.iloc[0]["quote_code"]
bottom_code = changes.iloc[-1]["quote_code"]
compare_codes = sorted(changes["quote_code"])

# The headline answer, before any tab has to be clicked.
top_row = changes.iloc[0]
bottom_row = changes.iloc[-1]
hero_1, hero_2, hero_3 = st.columns(3)
hero_1.metric(
    f"Gained most vs {base_code}",
    f"{top_row['quote_code']}  {top_row['pct_change']:+.2f}%",
    help=help_text(top_row["quote_code"]),
)
hero_2.metric(
    f"Lost most vs {base_code}",
    f"{bottom_row['quote_code']}  {bottom_row['pct_change']:+.2f}%",
    help=help_text(bottom_row["quote_code"]),
)
hero_3.metric("Data through", str(FULL_END), help=f"{len(rates):,} stored observations")
hero_1.markdown(currency_chip(top_row["quote_code"]), unsafe_allow_html=True)
hero_2.markdown(currency_chip(bottom_row["quote_code"]), unsafe_allow_html=True)

st.divider()

(
    tab_insights,
    tab_daily,
    tab_rankings,
    tab_map,
    tab_trend,
    tab_crypto,
    tab_ask,
) = st.tabs(
    [
        "Conversion Insights",
        "Daily Summary",
        "Rankings",
        "Map",
        "Trend",
        "Crypto",
        "Ask",
    ]
)


# --- Conversion Insights ------------------------------------------------------------------
with tab_insights:
    st.subheader("What moved, and what it means")
    st.caption(
        f"Every figure here is calculated in Python from the stored rates between "
        f"{first_day} and {last_day} in {base_code}. The model is never asked to do "
        f"arithmetic. Change the base currency or period in the sidebar and all of "
        f"this recalculates."
    )

    # Opening selection: the biggest gainer and biggest loser against the base
    # over the selected period, which on first load is the whole stored history.
    col_a, col_b = st.columns(2)
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

    if code_a == code_b:
        st.info("Pick two different currencies to compare them.")

    picked = list(dict.fromkeys([code_a, code_b]))

    for code in picked:
        row = changes[changes["quote_code"] == code].iloc[0]
        ending = invest_one(row, amount)
        change = row["pct_change"]
        gained = change > 0

        with st.container(border=True):
            st.markdown(
                f'<h4 style="margin:0 0 .5rem 0">{flag_image(code, 22)}'
                f'{html.escape(str(row["name"]))} ({code})</h4>',
                unsafe_allow_html=True,
            )

            facts_col, spark_col = st.columns([3, 2])

            with facts_col:
                f1, f2 = st.columns(2)
                f1.metric(
                    f"Change vs {base_code}",
                    f"{change:+.2f}%",
                    help="Positive means the currency gained value against your base.",
                )
                f2.metric(
                    esc(f"{money(amount)} would now be"),
                    esc(money(ending)),
                    delta=f"{(ending / amount - 1) * 100:+.2f}%",
                    # Streamlit's delta arrows are red/green, which would undo the
                    # colourblind-safe palette used everywhere else. The sign carries it.
                    delta_color="off",
                )
                st.caption(
                    esc(
                        f"1 {base_code} bought {fmt_rate(row['first_rate'])} {code} on "
                        f"{first_day}, and {fmt_rate(row['last_rate'])} {code} on "
                        f"{last_day}."
                    )
                )

            with spark_col:
                track = window[window["quote_code"] == code]
                if len(track) >= 2:
                    st.plotly_chart(
                        sparkline(indexed(track), gained), use_container_width=True
                    )
                    st.caption(esc(f"{code} vs {base_code} · indexed to 100"))
                else:
                    st.caption("Not enough points to chart.")

            # The two sentences, kept as they were - without the tinted banners.
            verb = "Gained" if ending >= amount else "Lost"
            st.markdown(
                esc(
                    f"**{money(amount)} Investment {verb}:** A {money(amount)} investment in "
                    f"the {row['name']} on {first_day} would be worth {money(ending)} on "
                    f"{last_day}."
                )
            )

            if gained:
                st.markdown(
                    esc(
                        f"\U0001F30D Your {base_name} buys fewer {plural(row['name'])} than it "
                        f"did on {first_day}, so expect things to feel slightly more "
                        f"expensive there as a traveller."
                    )
                )
            elif change < 0:
                st.markdown(
                    esc(
                        f"\U0001F30D Your {base_name} buys more {plural(row['name'])} than it "
                        f"did on {first_day}, so expect things to feel slightly cheaper "
                        f"there as a traveller."
                    )
                )
            else:
                st.markdown(
                    esc(
                        f"\U0001F30D Purchases as a traveller using the {base_name} should "
                        f"cost about the same where the {row['name']} is used."
                    )
                )

    frames, labels, colors, dashes = [], [], [], []
    for code in picked:
        track = window[window["quote_code"] == code]
        if len(track) >= 2:
            row = changes[changes["quote_code"] == code].iloc[0]
            frames.append(indexed(track))
            labels.append(code)
            colors.append(COLORS["up"] if row["pct_change"] > 0 else COLORS["down"])
            # solid, then dashed: two currencies that both fell are both red, so
            # the dash is what tells them apart
            dashes.append("solid" if len(frames) == 1 else "dash")

    if frames:
        st.plotly_chart(
            comparison_chart(frames, labels, colors, dashes), use_container_width=True
        )
        st.caption(
            f"Value against the {base_code}, both set to 100 on {first_day}. A rising "
            f"line means the currency gained value, so each line ends at 100 plus its "
            f"percent change. Blue gained, red lost; the dashed line is the second "
            f"currency."
        )



# --- Daily Summary -----------------------------------------------------------
with tab_daily:
    summary_text, summary_meta = load_summary()

    meta_start = meta_end = None
    try:
        if summary_meta.get("start") and summary_meta.get("end"):
            meta_start = date.fromisoformat(summary_meta["start"])
            meta_end = date.fromisoformat(summary_meta["end"])
    except (ValueError, TypeError):
        meta_start = meta_end = None

    # Unlike every other tab this one does not follow the sidebar: it is one
    # fixed paragraph written over its own rolling window by summary.py, and it
    # changes when that script next runs, not when the controls move.
    if not summary_text:
        st.info("No written summary yet. Run `python src/summary.py` to generate one.")
    else:
        label = (
            f"Daily written summary — {summary_meta.get('start')} to {summary_meta.get('end')}"
            if meta_start and meta_end
            else "Daily written summary"
        )
        st.subheader(label)
        with st.container():
            if meta_end and meta_end < FULL_END:
                st.warning(
                    f"Written from data up to {meta_end}, but the database now runs to "
                    f"{FULL_END}. Re-run `python src/summary.py` to refresh it."
                )
            meta_top = summary_meta.get("top") or {}
            meta_bottom = summary_meta.get("bottom") or {}
            # the written summary is produced by summary.py on a schedule, so
            # one written before cryptocurrencies were separated out can still
            # be sitting here ranking Ethereum against the Seychellois rupee
            mixed = [
                code
                for code in (meta_top.get("code"), meta_bottom.get("code"))
                if code in CRYPTO_CODES
            ]
            if mixed:
                st.warning(
                    f"This summary ranks {', '.join(mixed)} against national "
                    f"currencies, so it was written before the two were "
                    f"separated. Re-run `python src/summary.py` to rewrite it."
                )
            if meta_top.get("code") and meta_bottom.get("code"):
                g1, g2 = st.columns(2)
                g1.metric(
                    "Biggest gainer vs USD",
                    f"{meta_top['code']} {meta_top.get('pct_change', 0):+.2f}%",
                    help=help_text(meta_top["code"]),
                )
                g2.metric(
                    "Biggest loser vs USD",
                    f"{meta_bottom['code']} {meta_bottom.get('pct_change', 0):+.2f}%",
                    help=help_text(meta_bottom["code"]),
                )
                # the same flag and name the charts above carry, so the written
                # summary is not the one place a bare code stands on its own
                g1.markdown(
                    currency_chip(meta_top["code"]), unsafe_allow_html=True
                )
                g2.markdown(
                    currency_chip(meta_bottom["code"]), unsafe_allow_html=True
                )
            # the same two currencies over the same window the paragraph describes,
            # independent of the sidebar - otherwise the chart beside the summary
            # shows a different period than the summary is talking about
            if meta_start and meta_end and meta_top.get("code") and meta_bottom.get("code"):
                sum_changes, sum_window, _ = changes_for("USD", meta_start, meta_end)
                s_frames, s_labels, s_colors, s_dashes = [], [], [], []
                for code in (meta_top["code"], meta_bottom["code"]):
                    track = sum_window[sum_window["quote_code"] == code]
                    row = sum_changes[sum_changes["quote_code"] == code]
                    if len(track) >= 2 and not row.empty:
                        s_frames.append(indexed(track))
                        s_labels.append(code)
                        s_colors.append(
                            COLORS["up"] if row.iloc[0]["pct_change"] > 0 else COLORS["down"]
                        )
                        s_dashes.append("solid" if len(s_frames) == 1 else "dash")
                if s_frames:
                    st.plotly_chart(
                        comparison_chart(s_frames, s_labels, s_colors, s_dashes),
                        use_container_width=True,
                    )
                    st.caption(
                        f"{' and '.join(s_labels)} against the USD over the summary's own "
                        f"window, both set to 100 on {meta_start}."
                    )

            st.markdown(esc(summary_text))
            st.caption(
                "Rewritten once a day over its own rolling window, so it does not "
                "follow the sidebar. The figures above do."
            )

# --- Rankings -----------------------------------------------------------------
with tab_rankings:
    st.subheader(f"Biggest movers against the {base_code}")
    st.caption(
        f"Change in value between {first_day} and {last_day}, out of "
        f"{len(changes)} currencies. Blue gained, red lost. Hover a bar for the exact figure."
    )
    if CRYPTO_CODES:
        st.caption(
            f"National currencies only. The {len(CRYPTO_CODES)} cryptocurrencies in "
            f"this data are on the Crypto tab, compared with each other."
        )

    # changes is sorted descending, so head(n) alone is "top n gainers" - with ~170
    # currencies a small n means the chart never shows a single loser, however the
    # legend is labelled. Take from both ends by default.
    pick_col, count_col = st.columns([2, 1])
    with pick_col:
        view = st.radio(
            "Show", ["Both ends", "Top gainers", "Biggest losers"], horizontal=True
        )
    with count_col:
        show_count = st.selectbox("How many", [6, 10, 20, 50, 100], index=1)

    if view == "Top gainers":
        ranked = changes.head(show_count).copy()
    elif view == "Biggest losers":
        ranked = changes.tail(show_count).copy()
    else:
        half = max(1, show_count // 2)
        ranked = (
            pd.concat([changes.head(half), changes.tail(half)])
            .drop_duplicates("quote_code")
            .sort_values("pct_change", ascending=False)
            .copy()
        )
    ranked["direction"] = ranked["pct_change"].apply(
        lambda v: "Gained" if v >= 0 else "Lost"
    )

    bar_figure = px.bar(
        ranked,
        x="pct_change",
        y="quote_code",
        orientation="h",
        color="direction",
        custom_data=["name"],
        color_discrete_map={"Gained": COLORS["up"], "Lost": COLORS["down"]},
        labels={
            "quote_code": "Currency",
            "pct_change": f"% change vs {base_code}",
            "direction": "",
        },
        text="pct_change" if show_count <= 20 else None,
    )
    order = list(ranked["quote_code"])
    bar_figure.update_yaxes(
        categoryorder="array",
        categoryarray=order[::-1],
        tickmode="array",
        tickvals=order,
        ticktext=order,
        tickfont={"size": 11},
        title=None,
    )
    bar_figure.update_xaxes(
        side="top", gridcolor=COLORS["grid"], zerolinecolor=COLORS["axis"]
    )
    # height follows the number of bars instead of a fixed 450px, so 100 rows are
    # not crushed into the same space as 5
    bar_figure.update_layout(
        height=max(280, 26 * len(ranked) + 120),
        bargap=0.3,
        margin={"l": 0, "r": 0, "t": 50, "b": 0},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.08, "x": 0},
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    if show_count <= 20:
        bar_figure.update_traces(
            texttemplate="%{x:+.2f}%", textposition="outside", cliponaxis=False
        )

    # A flag at the foot of each bar, on the far side of the zero line so it
    # never covers the bar itself. Positions are in data units rather than
    # pixels, so they hold wherever the chart is resized, and the gap and the
    # flag scale with the axis instead of drifting across it.
    span = float(ranked["pct_change"].abs().max()) or 1.0
    bar_figure.update_layout(
        images=[
            {
                "source": flag_url(row.quote_code, ASSET_TYPES.get(row.quote_code)),
                "xref": "x",
                "yref": "y",
                "x": -0.012 * span if row.pct_change >= 0 else 0.012 * span,
                "y": row.quote_code,
                "sizex": 0.05 * span,
                "sizey": 0.66,
                "xanchor": "right" if row.pct_change >= 0 else "left",
                "yanchor": "middle",
                "layer": "above",
            }
            for row in ranked.itertuples()
            if flag_url(row.quote_code, ASSET_TYPES.get(row.quote_code))
        ]
    )
    bar_figure.update_traces(
        hovertemplate="<b>%{y}</b>: %{customdata[0]}<br>%{x:+.2f}% vs "
        + base_code
        + "<extra></extra>"
    )
    st.plotly_chart(bar_figure, use_container_width=True)

    if last_date - first_date > timedelta(days=400):
        st.caption(
            "Note: over a span this long, currencies whose data starts later are "
            "compared across a shorter window than the rest."
        )

    if broken:
        names = ", ".join(
            f"{code} ({currency_info.get(code, (code, ''))[0]}, {day})"
            for code, day in sorted(broken.items())
        )
        st.caption(
            f"Left out as not comparable: {names}. These were redenominated inside "
            f"this period — the currency was reissued at a new scale, so the rates "
            f"before and after are in different units and any percent change across "
            f"the break would be meaningless."
        )

    with st.expander("View as a table"):
        ranked_table = changes.copy()
        # the flag goes in its own image column, so it renders the same on every
        # platform; the cell is simply empty for a currency no one country owns
        ranked_table.insert(
            0,
            "Flag",
            ranked_table["quote_code"].map(
                lambda code: flag_url(code, ASSET_TYPES.get(code))
            ),
        )
        st.dataframe(
            ranked_table.rename(
                columns={
                    "quote_code": "Code",
                    "name": "Currency",
                    "first_rate": f"Rate on {first_date}",
                    "last_rate": f"Rate on {last_date}",
                    "pct_change": "% change",
                }
            ),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Flag": st.column_config.ImageColumn(
                    "", width="small", help="The country this currency belongs to"
                )
            },
        )


# --- Map ----------------------------------------------------------------------
with tab_map:
    st.subheader(
        f"Where money gained and lost against the {base_code}, "
        f"{first_day} to {last_day}",
        help=help_text(base_code),
    )

    # One currency can cover many countries - the euro covers 36 of them, the
    # CFA francs cover 14 between them - so the map is drawn per country from
    # the ISO country-to-currency table, not per currency.
    move_of = dict(zip(changes["quote_code"], changes["pct_change"]))
    currency_name_of = dict(zip(changes["quote_code"], changes["name"]))

    map_rows = []
    for alpha3, code in COUNTRY_CURRENCY.items():
        if code == base_code:
            # the base cannot move against itself: it is the zero of the scale
            change = 0.0
        elif code in move_of:
            change = float(move_of[code])
        else:
            continue
        map_rows.append(
            {
                "country": alpha3,
                "country_name": COUNTRY_NAMES.get(alpha3, alpha3),
                "code": code,
                "currency": currency_name_of.get(code, code),
                "pct_change": change,
            }
        )
    map_data = pd.DataFrame(map_rows)

    if map_data.empty:
        st.info(
            "No currency in this date range can be placed on the map. Widen the "
            "period in the sidebar."
        )
    else:
        # A single currency can flatten every other colour: over the full
        # history the bolivar moved thousands of percent while most currencies
        # moved single digits, and on one shared scale the whole world would
        # read as "no change". So the colour saturates at the 90th percentile of
        # the absolute moves, symmetric about zero so that a gain and a loss of
        # the same size get the same strength of colour. Countries past that
        # point keep the end colour; hovering always shows the true figure.
        limit = max(float(map_data["pct_change"].abs().quantile(0.9)), 1.0)

        map_figure = px.choropleth(
            map_data,
            locations="country",
            locationmode="ISO-3",
            color="pct_change",
            hover_name="country_name",
            custom_data=["currency", "code", "pct_change"],
            color_continuous_scale=[COLORS["down"], "#f4f3ef", COLORS["up"]],
            color_continuous_midpoint=0,
            range_color=(-limit, limit),
            labels={"pct_change": f"% vs {base_code}"},
        )
        map_figure.update_traces(
            marker_line_color=COLORS["grid"],
            marker_line_width=0.4,
            # clicking a country selects it, and Plotly's default is to fade
            # everything else to near-invisible. Keep the rest of the map at
            # full strength: the point of the map is the whole picture.
            unselected={"marker": {"opacity": 1}},
            hovertemplate=(
                "<b>%{hovertext}</b><br>%{customdata[0]} (%{customdata[1]})"
                "<br>%{customdata[2]:+.2f}% vs " + base_code + "<extra></extra>"
            ),
        )
        map_figure.update_geos(
            projection_type="natural earth",
            showframe=False,
            showcoastlines=False,
            showland=True,
            landcolor=COLORS["grid"],
            showocean=False,
            bgcolor="rgba(0,0,0,0)",
            # Antarctica has no currency and takes up a third of the frame
            lataxis_range=[-58, 85],
        )
        map_figure.update_layout(
            height=520,
            margin={"l": 0, "r": 0, "t": 0, "b": 0},
            paper_bgcolor="rgba(0,0,0,0)",
            coloraxis_colorbar={
                "title": f"% vs {base_code}",
                "ticksuffix": "%",
                "thickness": 14,
                "len": 0.7,
            },
        )
        # scroll wheel zoom is off: the map fills the width, so a reader
        # scrolling the page would otherwise zoom the map instead. Dragging
        # still pans it, and the toolbar still zooms.
        # Plotly draws its hover label as plain text, so a flag cannot go
        # inside it - an image in a hovertemplate is ignored. Clicking can do
        # what hovering cannot: the country stays selected and its flag, name,
        # currency and figure are drawn underneath in ordinary HTML.
        map_event = st.plotly_chart(
            map_figure,
            use_container_width=True,
            config={"scrollZoom": False},
            on_select="rerun",
            selection_mode="points",
            key="map_selection",
        )

        chosen = []
        try:
            chosen = (map_event.get("selection") or {}).get("points") or []
        except AttributeError:
            chosen = []

        if chosen:
            point = chosen[0]
            alpha3 = point.get("location")
            picked_row = map_data[map_data["country"] == alpha3]
            if not picked_row.empty:
                row = picked_row.iloc[0]
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:10px;'
                    f"padding:10px 14px;border:1px solid {COLORS['grid']};"
                    f'border-radius:8px;margin-top:4px">'
                    f"{flag_image(row['code'], 28)}"
                    f'<div><b>{html.escape(str(row["country_name"]))}</b><br>'
                    f'<span style="font-size:0.85rem;color:#898781">'
                    f'{html.escape(str(row["currency"]))} ({row["code"]}) · '
                    f'{row["pct_change"]:+.2f}% vs {base_code}</span></div></div>',
                    unsafe_allow_html=True,
                )

                picked_code = row["code"]
                detail = changes[changes["quote_code"] == picked_code]
                if picked_code == base_code:
                    st.markdown(
                        f"- This country spends the {base_name}, which is the base "
                        f"every other currency is measured against here, so it "
                        f"cannot move against itself."
                    )
                elif not detail.empty:
                    detail_row = detail.iloc[0]
                    ending = invest_one(detail_row, amount)
                    change = detail_row["pct_change"]
                    if change > 0:
                        travel = (
                            f"buys fewer {plural(detail_row['name'])} than it did on "
                            f"{first_day}, so expect things to feel slightly more "
                            f"expensive there as a traveller"
                        )
                    elif change < 0:
                        travel = (
                            f"buys more {plural(detail_row['name'])} than it did on "
                            f"{first_day}, so expect things to feel slightly cheaper "
                            f"there as a traveller"
                        )
                    else:
                        travel = (
                            f"buys about as many {plural(detail_row['name'])} as it "
                            f"did on {first_day}"
                        )
                    st.markdown(
                        esc(
                            f"- **{money(amount)}** put into the {detail_row['name']} "
                            f"on {first_day} would be worth **{money(ending)}** on "
                            f"{last_day} ({(ending / amount - 1) * 100:+.2f}%).\n"
                            f"- 1 {base_code} bought "
                            f"{fmt_rate(detail_row['first_rate'])} {picked_code} on "
                            f"{first_day}, and {fmt_rate(detail_row['last_rate'])} "
                            f"{picked_code} on {last_day}.\n"
                            f"- \U0001F30D Your {base_name} {travel}."
                        )
                    )
        else:
            st.caption(
                "Click a country to pin its flag here, with what it would have "
                "done to a holding and what it means for a traveller. Hovering "
                "gives the headline figure without the flag: a Plotly hover label "
                "is plain text and cannot hold an image."
            )

        st.caption(
            f"Change in each country's currency against the {base_code} between "
            f"{first_day} and {last_day}. Blue gained, red lost, pale means it "
            f"barely moved; countries on the {base_name} itself sit at zero, "
            f"because the base is what everything else is measured against. "
            f"Hover a country for its currency and exact figure, click it to pin "
            f"its flag below, and drag to pan."
        )


# --- Trend --------------------------------------------------------------------
with tab_trend:
    # National currencies only. Cryptocurrencies have a tab of their own, and
    # gold, silver, the IMF's drawing right and the commodity index are not any
    # country's money, so none of them belong in a currency picker.
    quote_codes = [
        code
        for code in sorted(base_rates["quote_code"].dropna().unique())
        if code not in CRYPTO_CODES and code not in NON_COUNTRY_CODES
    ]

    quote_code = st.selectbox(
        "Currency to chart",
        quote_codes,
        index=quote_codes.index(top_code) if top_code in quote_codes else 0,
        format_func=selector_label,
    )

    pair_rates = base_rates[base_rates["quote_code"] == quote_code].sort_values("date")
    pair_rates = pair_rates[
        (pair_rates["date"].dt.date >= start_date)
        & (pair_rates["date"].dt.date <= end_date)
    ]

    if pair_rates.empty:
        st.warning(
            f"No {quote_code} data in this date range. Widen the period in the sidebar."
        )
    else:
        latest_rate = pair_rates.iloc[-1]
        first_pair, last_pair = pair_rates.iloc[0]["rate"], latest_rate["rate"]

        k1, k2, k3 = st.columns(3)
        k1.metric(f"1 {base_code} in {quote_code}", fmt_rate(last_pair))
        k2.metric(
            "Change over the period",
            f"{(last_pair / first_pair - 1) * 100:+.2f}%" if first_pair else "n/a",
        )
        k3.metric("Latest observation", latest_rate["date"].strftime("%Y-%m-%d"))

        st.subheader(
            esc(f"{chart_label(base_code)} to {chart_label(quote_code)} over time")
        )
        st.markdown(currency_chip(quote_code, 20), unsafe_allow_html=True)
        figure = px.line(
            pair_rates,
            x="date",
            y="rate",
            labels={"date": "Date", "rate": f"Rate ({quote_code})"},
        )
        # markers only when there are few enough points to see them
        figure.update_traces(
            line={"color": COLORS["line"], "width": 2},
            mode="lines+markers" if len(pair_rates) <= 120 else "lines",
            marker={"size": 8},
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.6g} " + quote_code + "<extra></extra>",
        )
        figure.update_xaxes(gridcolor=COLORS["grid"], title=None)
        figure.update_yaxes(gridcolor=COLORS["grid"])
        figure.update_layout(
            height=380,
            margin={"l": 0, "r": 0, "t": 10, "b": 0},
            hovermode="x unified",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
        )
        st.plotly_chart(figure, use_container_width=True)

        with st.expander(f"Rate history ({len(pair_rates):,} rows)"):
            st.dataframe(
                pair_rates[["date", "base_code", "quote_code", "rate"]].sort_values(
                    "date", ascending=False
                ),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
                    "base_code": "Base",
                    "quote_code": "Quote",
                    "rate": st.column_config.NumberColumn("Rate", format="%.6g"),
                },
            )


# --- Crypto -------------------------------------------------------------------
with tab_crypto:
    st.subheader(f"Cryptocurrencies against the {base_code}")

    crypto_changes, crypto_window = crypto_changes_for(base_code, start_date, end_date)

    if crypto_changes.empty:
        st.info(
            "No cryptocurrency has two or more observations in this date range, so "
            "there is no change to measure yet. Widen the period in the sidebar."
        )
    else:
        crypto_first = crypto_window["date"].min().date()
        crypto_last = crypto_window["date"].max().date()
        st.caption(
            f"Change in value between {long_date(crypto_first)} and "
            f"{long_date(crypto_last)}, across {len(crypto_changes)} of them. "
            f"Blue gained, red lost. Crypto is measured the same way as the "
            f"currencies but kept apart from them: most of these codes arrived in a "
            f"single recent snapshot, so a joint ranking would compare one day's "
            f"move with years of them. A coin with only one observation in this "
            f"range is left out until it has two."
        )

        crypto_top = crypto_changes.iloc[0]
        crypto_bottom = crypto_changes.iloc[-1]
        crypto_1, crypto_2 = st.columns(2)
        crypto_1.metric(
            f"Gained most vs {base_code}",
            f"{crypto_top['quote_code']}  {crypto_top['pct_change']:+.2f}%",
            help=help_text(crypto_top["quote_code"]),
        )
        crypto_2.metric(
            f"Lost most vs {base_code}",
            f"{crypto_bottom['quote_code']}  {crypto_bottom['pct_change']:+.2f}%",
            help=help_text(crypto_bottom["quote_code"]),
        )
        crypto_1.markdown(
            currency_chip(crypto_top["quote_code"]), unsafe_allow_html=True
        )
        crypto_2.markdown(
            currency_chip(crypto_bottom["quote_code"]), unsafe_allow_html=True
        )

        ranked_crypto = crypto_changes.copy()
        ranked_crypto["direction"] = ranked_crypto["pct_change"].apply(
            lambda v: "Gained" if v >= 0 else "Lost"
        )
        crypto_bars = px.bar(
            ranked_crypto,
            x="pct_change",
            y="quote_code",
            orientation="h",
            color="direction",
            custom_data=["name"],
            color_discrete_map={"Gained": COLORS["up"], "Lost": COLORS["down"]},
            labels={
                "quote_code": "Crypto",
                "pct_change": f"% change vs {base_code}",
                "direction": "",
            },
            text="pct_change",
        )
        crypto_order = list(ranked_crypto["quote_code"])
        crypto_bars.update_yaxes(
            categoryorder="array",
            categoryarray=crypto_order[::-1],
            tickmode="array",
            tickvals=crypto_order,
            ticktext=crypto_order,
            tickfont={"size": 11},
            title=None,
        )
        crypto_bars.update_xaxes(
            side="top", gridcolor=COLORS["grid"], zerolinecolor=COLORS["axis"]
        )
        crypto_bars.update_layout(
            height=max(280, 26 * len(ranked_crypto) + 120),
            bargap=0.3,
            # room on the right for the outside label: a four-figure percent
            # change is wide, and crypto produces those
            margin={"l": 0, "r": 80, "t": 50, "b": 0},
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.08, "x": 0},
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        crypto_bars.update_traces(
            texttemplate="%{x:+.2f}%", textposition="outside", cliponaxis=False
        )
        crypto_bars.update_traces(
            hovertemplate="<b>%{y}</b>: %{customdata[0]}<br>%{x:+.2f}% vs "
            + base_code
            + "<extra></extra>"
        )
        st.plotly_chart(crypto_bars, use_container_width=True)

        st.divider()
        st.subheader("Compare two cryptocurrencies")

        crypto_codes = sorted(crypto_changes["quote_code"])
        crypto_col_a, crypto_col_b = st.columns(2)
        with crypto_col_a:
            crypto_a = st.selectbox(
                "First cryptocurrency",
                crypto_codes,
                index=crypto_codes.index(crypto_top["quote_code"]),
                format_func=selector_label,
                key="crypto_a",
            )
        with crypto_col_b:
            crypto_b = st.selectbox(
                "Second cryptocurrency",
                crypto_codes,
                index=crypto_codes.index(crypto_bottom["quote_code"]),
                format_func=selector_label,
                key="crypto_b",
            )

        if crypto_a == crypto_b:
            st.info("Pick two different cryptocurrencies to compare them.")

        crypto_picked = list(dict.fromkeys([crypto_a, crypto_b]))
        crypto_frames, crypto_labels, crypto_colors, crypto_dashes = [], [], [], []
        for code in crypto_picked:
            track = crypto_window[crypto_window["quote_code"] == code]
            row = crypto_changes[crypto_changes["quote_code"] == code]
            if len(track) >= 2 and not row.empty:
                crypto_frames.append(indexed(track))
                crypto_labels.append(code)
                crypto_colors.append(
                    COLORS["up"] if row.iloc[0]["pct_change"] > 0 else COLORS["down"]
                )
                crypto_dashes.append("solid" if len(crypto_frames) == 1 else "dash")

        # Each coin is indexed to its own first day in this range, and most of
        # these arrived in the data only days ago - Filecoin has a week where
        # Ethereum has six years. The window's own first day is therefore the
        # wrong date to quote for the newcomer, both on the chart and in the
        # sentence underneath, so every date here is the coin's own.
        coin_span = {}
        for code in crypto_picked:
            track = crypto_window[crypto_window["quote_code"] == code]
            if not track.empty:
                coin_span[code] = (
                    track["date"].min().date(),
                    track["date"].max().date(),
                )

        if crypto_frames:
            st.plotly_chart(
                comparison_chart(
                    crypto_frames, crypto_labels, crypto_colors, crypto_dashes
                ),
                use_container_width=True,
            )
            starts = {code: coin_span[code][0] for code in crypto_labels}
            if len(set(starts.values())) == 1:
                indexed_on = (
                    f"both set to 100 on {long_date(next(iter(starts.values())))}"
                )
            else:
                each = ", ".join(
                    f"{code} on {long_date(day)}" for code, day in starts.items()
                )
                indexed_on = f"each set to 100 on its own first day here ({each})"
            st.caption(
                f"Value against the {base_code}, {indexed_on}. A rising line means "
                f"the coin gained value, so each line ends at 100 plus its percent "
                f"change. Blue gained, red lost; the dashed line is the second one. "
                f"A coin with only days of history draws a short line at the right "
                f"of the chart, with a marker on every point so it stays visible."
            )

        for code in crypto_picked:
            row = crypto_changes[crypto_changes["quote_code"] == code].iloc[0]
            ending = invest_one(row, amount)
            began, ended = coin_span[code]
            st.markdown(
                esc(
                    f"**{row['name']} ({code}):** {money(amount)} put in on "
                    f"{long_date(began)} would be worth {money(ending)} on "
                    f"{long_date(ended)} "
                    f"({(ending / amount - 1) * 100:+.2f}%)."
                )
            )
        st.caption(
            "Past movement, not a forecast, and these are far more volatile than "
            "the currencies on the other tabs."
        )

        with st.expander("View as a table"):
            st.dataframe(
                crypto_changes.rename(
                    columns={
                        "quote_code": "Code",
                        "name": "Crypto",
                        "first_rate": f"Rate on {crypto_first}",
                        "last_rate": f"Rate on {crypto_last}",
                        "pct_change": "% change",
                    }
                ),
                hide_index=True,
                use_container_width=True,
            )


# --- Ask ----------------------------------------------------------------------
with tab_ask:
    st.subheader("Ask about this data")
    st.caption(
        f"The chatbot sees one row per currency for {long_date(start_date)} to "
        f"{long_date(end_date)} in {base_code}: percent change, the rate on the first "
        f"and last day, and what {money(amount)} would have become. Change the base, "
        f"period or amount in the sidebar to change what it can see."
    )
    # build_chat_context summarises every currency into one line each, so the whole
    # window fits in the prompt regardless of how many days it spans
    data_context = build_chat_context(window, base_code, amount)
    show_chat(data_context)