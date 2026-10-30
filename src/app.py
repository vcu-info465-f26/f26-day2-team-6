# Run the code below in terminal to generate URLs for dashboard and interactive chart.
# python -m streamlit run src/app.py

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
from rates_util import (
    NON_COUNTRY_CODES,
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


def db_is_stale():
    """True if the db is missing or older than the json files it was built from."""
    if not DB_PATH.exists():
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
    # a currency that was redenominated inside this window has endpoints in
    # different units, so its percent change is not a real move
    broken = redenominated(window)
    comparable = window[~window["quote_code"].isin(broken)]
    return pct_changes(comparable, base), window, broken


def selector_label(code):
    """'USD' -> 'USD - United States Dollar $', used in every currency dropdown."""
    name, symbol = currency_info.get(code, (code, ""))
    return f"{code} - {name} {symbol}".strip()


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

    base_codes = sorted((set(rates["quote_code"]) | {"USD"}) - NON_COUNTRY_CODES)
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
    help=str(top_row["name"]),
)
hero_2.metric(
    f"Lost most vs {base_code}",
    f"{bottom_row['quote_code']}  {bottom_row['pct_change']:+.2f}%",
    help=str(bottom_row["name"]),
)
hero_3.metric("Data through", str(FULL_END), help=f"{len(rates):,} stored observations")

st.divider()

tab_summary, tab_rankings, tab_trend, tab_ask = st.tabs(
    ["Summary", "Rankings", "Trend", "Ask"]
)


# --- Summary ------------------------------------------------------------------
with tab_summary:
    summary_text, summary_meta = load_summary()

    meta_start = meta_end = None
    try:
        if summary_meta.get("start") and summary_meta.get("end"):
            meta_start = date.fromisoformat(summary_meta["start"])
            meta_end = date.fromisoformat(summary_meta["end"])
    except (ValueError, TypeError):
        meta_start = meta_end = None

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
            st.markdown(esc(f"#### {row['name']} ({code})"))

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

    # The written summary comes last, because unlike everything above it does not
    # follow the sidebar: it is one fixed paragraph over its own rolling window.
    if not summary_text:
        st.info("No written summary yet. Run `python src/summary.py` to generate one.")
    else:
        label = (
            f"Daily written summary — {summary_meta.get('start')} to {summary_meta.get('end')}"
            if meta_start and meta_end
            else "Daily written summary"
        )
        with st.expander(label, expanded=True):
            if meta_end and meta_end < FULL_END:
                st.warning(
                    f"Written from data up to {meta_end}, but the database now runs to "
                    f"{FULL_END}. Re-run `python src/summary.py` to refresh it."
                )
            meta_top = summary_meta.get("top") or {}
            meta_bottom = summary_meta.get("bottom") or {}
            if meta_top.get("code") and meta_bottom.get("code"):
                g1, g2 = st.columns(2)
                g1.metric(
                    "Biggest gainer vs USD",
                    f"{meta_top['code']} {meta_top.get('pct_change', 0):+.2f}%",
                    help=meta_top.get("name"),
                )
                g2.metric(
                    "Biggest loser vs USD",
                    f"{meta_bottom['code']} {meta_bottom.get('pct_change', 0):+.2f}%",
                    help=meta_bottom.get("name"),
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
        st.dataframe(
            changes.rename(
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
        )


# --- Trend --------------------------------------------------------------------
with tab_trend:
    all_quotes = sorted(base_rates["quote_code"].dropna().unique())
    # XAU, XAG, XDR and friends are metals and accounting units, not a country's
    # money. They are already excluded from the rankings; keep them out of the
    # picker too unless they are asked for.
    special = [c for c in all_quotes if c in NON_COUNTRY_CODES]
    quote_codes = [c for c in all_quotes if c not in NON_COUNTRY_CODES]

    pick_col, toggle_col = st.columns([3, 1])
    with toggle_col:
        if special and st.checkbox("Metals & IMF units", value=False):
            quote_codes = quote_codes + special
    with pick_col:
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