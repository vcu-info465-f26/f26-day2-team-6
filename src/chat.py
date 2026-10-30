import os

import streamlit as st
from openai import OpenAI

from rates_util import invest_one, long_date, pct_changes

MODEL = "openai/gpt-oss-120b"


def groq_key():
    """GROQ_API_KEY from wherever this is running.

    st.secrets covers Streamlit Cloud and a local .streamlit/secrets.toml, but it
    does NOT fall back to environment variables - and reading it at all raises
    when no secrets file exists. The environment is where a Codespaces secret
    lands, which is also where summary.py looks for the same key.
    """
    try:
        key = st.secrets.get("GROQ_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY")


def build_chat_context(range_rates, base_code, amount=100):
    changes = pct_changes(range_rates, base_code)
    if changes.empty:
        return "No exchange rate data is available for the selected dates."
    start = long_date(range_rates["date"].min().date())
    end = long_date(range_rates["date"].max().date())
    lines = [
        f"{r['quote_code']}|{r['name']}|{r['pct_change']:+.2f}|"
        f"{r['first_rate']:.4f}|{r['last_rate']:.4f}|{invest_one(r, amount):.2f}"
        for _, r in changes.iterrows()
    ]
    return (
        f"Base currency: {base_code}. Dates covered: {start} to {end}.\n"
        f"Columns: code|name|pct_change|units per 1 {base_code} on first day|"
        f"units per 1 {base_code} on last day|value on last day of {amount} {base_code} "
        f"converted on first day\n" + "\n".join(lines)
    )


#creates the function for the chat box
def show_chat(data_context):
    st.subheader("Ask About Exchange Rates")
    #if the previous converstation was not archived then nothing is returned
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    #st.session_state.chat_messages recalls previous conversation
    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.write(message["content"].replace("$", "\\$"))
    #holds a message prompt in the chatbox asking you to ask it a question 
    question = st.chat_input("Ask a question about exchange rates...")

    if not question:
        return

    st.session_state.chat_messages.append({
        "role": "user",
        "content": question
    })

    with st.chat_message("user"):
        st.write(question)

    api_key = groq_key()
    if not api_key:
        # name the actual problem instead of blaming the service: a missing key
        # used to fall into the same branch as a network failure
        answer = (
            "The chat needs a Groq API key. Set GROQ_API_KEY as an environment "
            "variable, or add it to .streamlit/secrets.toml."
        )
        st.session_state.chat_messages.append({"role": "assistant", "content": answer})
        with st.chat_message("assistant"):
            st.warning(answer)
        return

    try:
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
            timeout=30
        )

        system_prompt = (
            "You are a helpful currency exchange assistant. "
            "Explain answers in simple language for beginners, in under 120 words. "
            "Use ONLY the table below. Quote its numbers exactly and never invent rates, dates or calculations. "
            "The table covers the current base currency and date range only. "
            "pct_change is how much a currency gained or lost in value against the base currency. "
            "A positive value means the base buys fewer units of it, so travelling there costs more. "
            "A negative value means the base goes further there. "
            "To compare two countries, compare their pct_change values and say which lets the base go further. "
            "Exchange rates show conversion only, not local prices, so say that when comparing travel. "
            "For investment questions use the last column. It assumes the money was converted on the first day "
            "and back on the last day, with no interest or fees, and it is only given for the amount in the "
            "column heading. Do not work out other amounts. "
            "If a currency or date is not in the table, say it is not in this dashboard's data. "
            "If asked whether to buy a currency or what rates will do next, say you cannot give advice or "
            "predict rates, then describe only what the table shows.\n\n"
            f"{data_context}"
        )
        #Allows the chatbox to archive the last 8 inquiries incase it needs to be recalled
        recent_messages = st.session_state.chat_messages[-8:]

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                *recent_messages
            ]
        )

        answer = response.choices[0].message.content

        if not answer:
            raise ValueError("Empty response")

    except Exception as e:
        print("GROQ ERROR:", type(e).__name__, str(e))

        answer = (
            "Sorry, the chat is temporarily unavailable. "
            "Please try again later."
        )

    st.session_state.chat_messages.append({
        "role": "assistant",
        "content": answer
    })

    with st.chat_message("assistant"):
        st.write(answer.replace("$", "\\$"))