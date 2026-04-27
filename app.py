import hashlib
import hmac
import os
import time

import streamlit as st
from dotenv import load_dotenv

from assistant import chat

load_dotenv()

def _get_setting(key: str, default: str = "") -> str:
    value = os.environ.get(key)
    if value is not None and str(value).strip() != "":
        return str(value)
    try:
        secret_value = st.secrets.get(key, default)
        if secret_value is not None and str(secret_value).strip() != "":
            return str(secret_value)
    except Exception:
        pass
    return default


ACCESS_HANDOFF_SECRET = _get_setting("ACCESS_HANDOFF_SECRET", "").strip()
AUTH_REQUIRED = _get_setting("STREAMLIT_AUTH_REQUIRED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}
ACCESS_GATE_URL = _get_setting("ACCESS_GATE_URL", "").strip()
CONTACT_EMAIL = _get_setting("CONTACT_EMAIL", "ResentenceDecarcerate@gmail.com")

st.set_page_config(page_title="RAG Chat", page_icon="💬")


def _expected_signature(email: str, exp: str, role: str) -> str:
    payload = f"{email}|{exp}|{role}"
    return hmac.new(
        ACCESS_HANDOFF_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _verify_token_from_query() -> tuple[bool, str]:
    """Validate ?st_email&st_exp&st_role&st_sig and stash result in session."""
    qp = st.query_params

    email = (qp.get("st_email") or "").strip().lower()
    exp = (qp.get("st_exp") or "").strip()
    role = (qp.get("st_role") or "default").strip().lower()
    sig = (qp.get("st_sig") or "").strip()

    if not (email and exp and sig):
        return False, "Missing access token in URL."

    try:
        if int(exp) < int(time.time()):
            return (
                False,
                "This launch link has expired. Return to the Tool Hub and click "
                "'Open Streamlit RAG Agent' again.",
            )
    except ValueError:
        return False, "Invalid expiration timestamp in launch link."

    expected = _expected_signature(email, exp, role)
    if not hmac.compare_digest(sig, expected):
        return False, "Invalid launch signature."

    st.session_state["authorized_email"] = email
    st.session_state["authorized_role"] = role
    st.session_state["authorized_until"] = int(exp)

    # Scrub the token from the URL so it doesn't get bookmarked or replayed
    # from history. Streamlit will rerun once after this clear.
    st.query_params.clear()
    return True, ""


def _is_session_authorized() -> bool:
    if not AUTH_REQUIRED:
        return True
    until = st.session_state.get("authorized_until")
    if not until:
        return False
    try:
        return int(until) >= int(time.time())
    except (TypeError, ValueError):
        return False


def _render_locked_view(message: str = ""):
    st.title("RAG Chat")
    body = "🔒 **Access required.**\n\n"
    if message:
        body += f"{message}\n\n"
    body += (
        "This RAG agent is only available after signing in via the magic-link "
        "flow on the main site. Please open it from the Tool Hub."
    )
    st.error(body)
    if ACCESS_GATE_URL:
        st.markdown(f"[Go to access page]({ACCESS_GATE_URL})")
    st.markdown(f"Need access? Contact `{CONTACT_EMAIL}`.")
    st.stop()


def _render_misconfigured_view():
    st.title("RAG Chat")
    st.error(
        "**Server misconfiguration.**\n\n"
        "`STREAMLIT_AUTH_REQUIRED=true` but `ACCESS_HANDOFF_SECRET` is not set. "
        "Set `ACCESS_HANDOFF_SECRET` in `.env` to the same value used by the "
        "Flask gate, or set `STREAMLIT_AUTH_REQUIRED=false` for local dev only."
    )
    st.stop()


# === Auth gate ===
if AUTH_REQUIRED:
    if not ACCESS_HANDOFF_SECRET:
        _render_misconfigured_view()

    if not _is_session_authorized():
        ok, msg = _verify_token_from_query()
        if not ok:
            _render_locked_view(msg)


# === Authorized — render the RAG UI ===
st.title("RAG Chat")

signed_in_email = st.session_state.get("authorized_email")
if signed_in_email:
    until_ts = st.session_state.get("authorized_until")
    role = st.session_state.get("authorized_role", "default")
    expiry_str = ""
    if until_ts:
        try:
            remaining = max(0, int(until_ts) - int(time.time()))
            mins = remaining // 60
            expiry_str = f" · session valid ~{mins} min" if mins else " · session expiring soon"
        except (TypeError, ValueError):
            expiry_str = ""
    st.caption(f"Signed in as **{signed_in_email}** · role: `{role}`{expiry_str}")
elif not AUTH_REQUIRED:
    st.caption("⚠️ Auth disabled (local dev mode)")

if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

prompt = st.chat_input("Ask a question…")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                response = chat(prompt)
            except Exception as e:
                response = f"Error: {e}"
        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
