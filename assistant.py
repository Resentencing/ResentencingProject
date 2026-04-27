import os

from dotenv import load_dotenv
from pinecone import Pinecone
from pinecone_plugins.assistant.models.chat import Message

load_dotenv()

try:
    import streamlit as st
except Exception:
    st = None


def _get_setting(key: str, default: str = "") -> str:
    """
    Prefer real environment variables; fall back to Streamlit secrets.
    This supports local .env, PythonAnywhere, Docker, and Streamlit Community Cloud.
    """
    value = os.environ.get(key)
    if value is not None and str(value).strip() != "":
        return str(value)
    if st is not None:
        try:
            secret_value = st.secrets.get(key, default)
            if secret_value is not None and str(secret_value).strip() != "":
                return str(secret_value)
        except Exception:
            pass
    return default


def get_assistant():
    api_key = _get_setting("PINECONE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing PINECONE_API_KEY (env var or Streamlit secret)")
    pc = Pinecone(api_key=api_key)
    return pc.assistant.Assistant(assistant_name="reg")


def chat(prompt: str) -> str:
    assistant = get_assistant()
    resp = assistant.chat(messages=[Message(content=prompt)])
    return resp["message"]["content"]

