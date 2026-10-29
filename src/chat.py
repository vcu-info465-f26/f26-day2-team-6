
import streamlit as st
from openai import OpenAI

MODEL = "openai/gpt-oss-120b"

#creates the function for the chat box
def show_chat(data_context):
    st.subheader("Ask About Exchange Rates")
    #if the previous converstation was not archived then nothing is returned
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    #st.session_state.chat_messages recalls previous conversation
    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
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

    try:
        api_key = st.secrets["GROQ_API_KEY"]

        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
            timeout=30
        )

        system_prompt = (
            "You are a helpful currency exchange assistant. "
            "Explain answers in simple language for beginners. "
            "Use ONLY the exchange rate data provided below. "
            "Do not invent exchange rates, dates, or calculations. "
            "If the data does not contain enough information, "
            "explain what is missing. "
            "For investment questions, explain the calculation "
            "and state any assumptions clearly.\n\n"
            f"Exchange rate data:\n{data_context}"
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
        st.write(answer)
