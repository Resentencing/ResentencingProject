from flask import Flask, render_template, Response, request, url_for, send_file, abort, jsonify, session, redirect
from flask_cors import CORS
import pandas as pd
import mysql.connector
from io import BytesIO
import os
import sys
import logging
import hashlib
import hmac
import time
import secrets
import zipfile
import datetime
import json
import re
import urllib.parse
import httpx
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# Load environment variables (repo root .env fills keys missing from cwd)
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()
load_dotenv(os.path.join(_repo_root, ".env"), override=False)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
try:
    from assistant import chat as pinecone_chat
except Exception as _e:
    pinecone_chat = None
    logging.warning("Pinecone assistant import failed: %s", _e)


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)

# Enable CORS for frontend -> backend communication (v1 for testing)
CORS(app, resources={
    r"/query_ai": {
        "origins": ["null", "http://localhost:8000", "http://127.0.0.1:8000"]
    },
    r"/api/stats": {
        "origins": ["*"]  # Allow frontend from any origin to fetch stats JSON
    },
    r"/api/public_summary": {
        "origins": ["*"]
    },
})

# Cache directory for faster visualization loading
CACHE_DIR = 'static/cache'
os.makedirs(CACHE_DIR, exist_ok=True)


# Configure Logging
logging.basicConfig(level=logging.DEBUG)

# Database Configuration - use environment variables with fallback to hardcoded values
database_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", "3306")),
}

ACCESS_HANDOFF_SECRET = os.getenv("ACCESS_HANDOFF_SECRET", "")
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
BACKEND_API_KEY = os.getenv("BACKEND_API_KEY") or os.getenv("API_KEY", "")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "ResentenceDecarcerate@gmail.com")
GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "").strip()
ACCESS_REQUEST_URL = (
    os.getenv("ACCESS_REQUEST_URL", "").strip()
    or "https://docs.google.com/forms/d/e/1FAIpQLSeQX5rNoBvAEAo6pO0JNHKygt9rrr_D7yJpXd8GI8PlknXGWA/viewform"
)
# Apps Script Web App URL ending in /exec (no query). Used by /access/magic so approval
# emails can link to your domain first; avoids Gmail/Chrome rewriting script.google.com with /u/N/.
APPS_SCRIPT_WEB_APP_EXEC_URL = os.getenv("APPS_SCRIPT_WEB_APP_EXEC_URL", "").strip().rstrip("/")
DOWNLOAD_LINK_MAX_AGE_SEC = int(os.getenv("DOWNLOAD_LINK_MAX_AGE_SEC", "900"))
DEFAULT_DOWNLOADS_PER_HOUR = int(os.getenv("DOWNLOADS_PER_HOUR", "10"))
DEFAULT_DOWNLOADS_PER_DAY = int(os.getenv("DOWNLOADS_PER_DAY", "50"))
DEFAULT_ZIPS_PER_DAY = int(os.getenv("ZIPS_PER_DAY", "3"))
UNLIMITED_ACCESS_ROLE = (os.getenv("UNLIMITED_ACCESS_ROLE", "priority_access") or "priority_access").strip().lower()
ENFORCE_MAGIC_LINK_EXPIRY = os.getenv("ENFORCE_MAGIC_LINK_EXPIRY", "false").lower() == "true"
REQUIRE_MAGIC_LINK_SIGNATURE = os.getenv("REQUIRE_MAGIC_LINK_SIGNATURE", "true").lower() == "true"
ROLE_LIMITS_JSON = os.getenv("ROLE_LIMITS_JSON", "{}")
STREAMLIT_BASE_URL = os.getenv("STREAMLIT_BASE_URL", "").strip().rstrip("/")
try:
    STREAMLIT_TOKEN_TTL_SECONDS = int(os.getenv("STREAMLIT_TOKEN_TTL_SECONDS", "300"))
except ValueError:
    STREAMLIT_TOKEN_TTL_SECONDS = 300

try:
    ROLE_LIMITS = json.loads(ROLE_LIMITS_JSON)
except json.JSONDecodeError:
    logging.warning("ROLE_LIMITS_JSON is invalid JSON; ignoring role overrides")
    ROLE_LIMITS = {}

AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "audit.log")
RATE_STATE = {}
_METADATA_COLUMNS_CACHE = None


def _normalize_apps_script_exec_url(url: str) -> str:
    if not (url or "").strip():
        return ""
    u = url.strip().rstrip("/")
    return re.sub(
        r"(https?://script\.google\.com/macros/)u/\d+/s/",
        r"\1s/",
        u,
        flags=re.IGNORECASE,
    )

# Keep in sync with mysite/dataset_lineage.py (public site reads; backend writes on upload).
_DATASET_LINEAGE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS dataset_source_refresh (
    source_key VARCHAR(32) NOT NULL PRIMARY KEY,
    refreshed_at DATETIME NOT NULL,
    detail VARCHAR(512) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def _iso_date_from_env(date_str):
    """Parse YYYY-MM-DD from env; return ISO 8601 UTC midnight for JSON."""
    if not date_str or not str(date_str).strip():
        return None
    s = str(date_str).strip()[:10]
    try:
        d = datetime.date.fromisoformat(s)
        dt = datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
        return dt.isoformat()
    except ValueError:
        logging.warning("Invalid PUBLIC_FRESHNESS_*_DATE (expected YYYY-MM-DD): %s", date_str)
        return None


def _merge_public_freshness_fallbacks(data_freshness):
    """
    Fill missing lineage timestamps from PUBLIC_FRESHNESS_* env vars.
    Rows in dataset_source_refresh always win when as_of is present.
    """
    env_pairs = (
        ("main_log", "PUBLIC_FRESHNESS_MAIN_LOG_DATE", "PUBLIC_FRESHNESS_MAIN_LOG_DETAIL"),
        ("race_data", "PUBLIC_FRESHNESS_RACE_DATA_DATE", "PUBLIC_FRESHNESS_RACE_DATA_DETAIL"),
        ("letters_db", "PUBLIC_FRESHNESS_LETTERS_DB_DATE", "PUBLIC_FRESHNESS_LETTERS_DB_DETAIL"),
    )
    for key, date_env, detail_env in env_pairs:
        cur = data_freshness.get(key)
        if cur and cur.get("as_of"):
            continue
        iso = _iso_date_from_env(os.getenv(date_env))
        if not iso:
            continue
        detail = (os.getenv(detail_env) or "").strip() or None
        data_freshness[key] = {"as_of": iso, "source_file": detail}
    return data_freshness


BROWSE_FIELDS = {
    "county": "County",
    "cohort": "Cohort",
    "institution": "Institution",
    "judge": "Judge",
    "action_taken": "Action Taken",
    "ethnicity": "Ethnicity",
}

LOOKUP_FIELDS = {
    "case_number": "Case Number",
    "cdcr_number": "CDCR Number",
    "convict_name": "Name",
    "county": "County",
    "cohort": "Cohort",
    "institution": "Institution",
    "judge": "Judge",
    "action_taken": "Action Taken",
    "ethnicity": "Ethnicity",
    "race": "Race",
    "isl_dsl": "ISL/DSL",
    "sec_decision": "Secretary Decision",
    "sentence_date": "Sentence Date",
}


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(app.secret_key, salt="frontend-download-token")


def _audit(event: str, email: str, detail: str = ""):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{timestamp}\t{event}\t{email or 'anonymous'}\t{detail}\n")


def _session_email() -> str:
    return (session.get("access_email") or "").strip().lower()


def _require_access():
    if not _session_email():
        return redirect(url_for("access_gate"))
    return None


def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_true(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _session_limits() -> dict:
    limits = {
        "downloads_per_hour": DEFAULT_DOWNLOADS_PER_HOUR,
        "downloads_per_day": DEFAULT_DOWNLOADS_PER_DAY,
        "zips_per_day": DEFAULT_ZIPS_PER_DAY,
        "unlimited": False,
    }

    role = (session.get("access_role") or "default").strip().lower()
    role_cfg = ROLE_LIMITS.get(role, {}) if isinstance(ROLE_LIMITS, dict) else {}
    if isinstance(role_cfg, dict):
        limits["downloads_per_hour"] = _to_int(role_cfg.get("downloads_per_hour"), limits["downloads_per_hour"])
        limits["downloads_per_day"] = _to_int(role_cfg.get("downloads_per_day"), limits["downloads_per_day"])
        limits["zips_per_day"] = _to_int(role_cfg.get("zips_per_day"), limits["zips_per_day"])
        limits["unlimited"] = bool(role_cfg.get("unlimited", limits["unlimited"]))

    if "downloads_per_hour" in session:
        limits["downloads_per_hour"] = _to_int(session.get("downloads_per_hour"), limits["downloads_per_hour"])
    if "downloads_per_day" in session:
        limits["downloads_per_day"] = _to_int(session.get("downloads_per_day"), limits["downloads_per_day"])
    if "zips_per_day" in session:
        limits["zips_per_day"] = _to_int(session.get("zips_per_day"), limits["zips_per_day"])
    if "unlimited_access" in session:
        limits["unlimited"] = bool(session.get("unlimited_access"))

    return limits


def _rate_key() -> str:
    key = session.get("access_session_id")
    if not key:
        key = secrets.token_hex(16)
        session["access_session_id"] = key
    return key


def _check_and_increment_limit(kind: str):
    limits = _session_limits()
    if limits["unlimited"]:
        return None

    now = time.time()
    key = _rate_key()
    bucket = RATE_STATE.setdefault(key, {"downloads": [], "zips": []})

    bucket["downloads"] = [t for t in bucket["downloads"] if now - t < 86400]
    bucket["zips"] = [t for t in bucket["zips"] if now - t < 86400]

    if kind == "download":
        recent_hour = [t for t in bucket["downloads"] if now - t < 3600]
        if len(recent_hour) >= limits["downloads_per_hour"]:
            return f"Download limit reached ({limits['downloads_per_hour']}/hour). Contact {CONTACT_EMAIL} for additional access."
        if len(bucket["downloads"]) >= limits["downloads_per_day"]:
            return f"Daily download limit reached ({limits['downloads_per_day']}/day). Contact {CONTACT_EMAIL} for additional access."
        bucket["downloads"].append(now)
        return None

    if kind == "zip":
        if len(bucket["zips"]) >= limits["zips_per_day"]:
            return f"Daily ZIP limit reached ({limits['zips_per_day']}/day). Contact {CONTACT_EMAIL} for additional access."
        bucket["zips"].append(now)
        return None

    return "Unknown rate limit action."


def _make_download_token(file_id: int, email: str) -> str:
    return _serializer().dumps({"file_id": file_id, "email": email})


def _make_zip_token(field: str, value: str, email: str) -> str:
    return _serializer().dumps({"lookup_field": field, "lookup_value": value, "email": email})


def _make_streamlit_handoff_params(email: str, role: str) -> dict:
    """Mint a short-lived HMAC-signed token the Streamlit RAG app can verify.

    Uses the same ACCESS_HANDOFF_SECRET as /access/session so a single shared
    secret governs both gate entry and downstream RAG handoff.
    """
    exp = str(int(time.time()) + STREAMLIT_TOKEN_TTL_SECONDS)
    role_clean = (role or "default").strip().lower()
    payload = f"{email}|{exp}|{role_clean}"
    sig = hmac.new(
        ACCESS_HANDOFF_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "st_email": email,
        "st_exp": exp,
        "st_role": role_clean,
        "st_sig": sig,
    }


def _resolve_file_path(raw_path: str) -> str:
    raw = (raw_path or "").strip()
    if not raw:
        return ""

    candidates = [
        raw,
        os.path.join(os.getcwd(), raw),
        os.path.join(os.path.dirname(__file__), raw),
        os.path.join(os.path.dirname(__file__), "..", raw),
        os.path.join(os.path.dirname(__file__), "static", raw),
    ]

    for c in candidates:
        normalized = os.path.normpath(c)
        if os.path.exists(normalized):
            return normalized
    return ""


def _metadata_columns():
    global _METADATA_COLUMNS_CACHE
    if _METADATA_COLUMNS_CACHE is not None:
        return _METADATA_COLUMNS_CACHE

    conn = mysql.connector.connect(**database_config)
    cursor = conn.cursor()
    cursor.execute("SHOW COLUMNS FROM metadata")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # rows shape: Field, Type, Null, Key, Default, Extra
    columns = [r[0] for r in rows if r and r[0]]
    _METADATA_COLUMNS_CACHE = columns
    return columns


def _labelize_column(column_name: str) -> str:
    return column_name.replace("_", " ").strip().title()


def _prof_bucket_parts(field: str, mode: str):
    resolved_mode = "year" if mode == "year" else "raw"
    if mode == "auto" and "date" in field.lower():
        resolved_mode = "year"

    if resolved_mode == "year":
        # Support real DATE columns and text-formatted dates (common in this dataset).
        # Falls back to the trailing 4-digit year when parsing cannot normalize.
        expr = f"""
        CASE
            WHEN `{field}` IS NULL OR TRIM(CAST(`{field}` AS CHAR(255))) = '' THEN NULL
            WHEN YEAR(`{field}`) IS NOT NULL AND YEAR(`{field}`) <> 0 THEN YEAR(`{field}`)
            WHEN YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%Y-%m-%d')) IS NOT NULL
                 AND YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%Y-%m-%d')) <> 0
                THEN YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%Y-%m-%d'))
            WHEN YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%m/%d/%Y')) IS NOT NULL
                 AND YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%m/%d/%Y')) <> 0
                THEN YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%m/%d/%Y'))
            WHEN YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%M %e, %Y')) IS NOT NULL
                 AND YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%M %e, %Y')) <> 0
                THEN YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%M %e, %Y'))
            WHEN YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%M %e. %Y')) IS NOT NULL
                 AND YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%M %e. %Y')) <> 0
                THEN YEAR(STR_TO_DATE(CAST(`{field}` AS CHAR(255)), '%M %e. %Y'))
            WHEN RIGHT(TRIM(CAST(`{field}` AS CHAR(255))), 4) REGEXP '^[0-9]{4}$'
                THEN CAST(RIGHT(TRIM(CAST(`{field}` AS CHAR(255))), 4) AS UNSIGNED)
            ELSE NULL
        END
        """
        valid_clause = f"({expr}) IS NOT NULL"
    else:
        expr = f"CAST(`{field}` AS CHAR(255))"
        valid_clause = f"`{field}` IS NOT NULL AND TRIM(CAST(`{field}` AS CHAR(255))) <> ''"
    return expr, valid_clause, resolved_mode


def _parse_prof_filters(raw_filters: str, allowed_fields: set):
    if not raw_filters:
        return {}
    try:
        parsed = json.loads(raw_filters)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    filters = {}
    for field, values in parsed.items():
        if field not in allowed_fields:
            continue
        if not isinstance(values, list):
            continue
        cleaned = [str(v).strip() for v in values if str(v).strip()]
        if cleaned:
            filters[field] = cleaned
    return filters

# ----------------------------------------------------------------------------- #
# --------- Temp Test Functions For Frontend -> Backend Communication --------- #

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True}), 200

@app.route("/query_ai", methods=["POST"])
def query_ai():
    access_redirect = _require_access()
    if access_redirect:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    q = (data.get("query") or "").strip()
    if not q:
        return jsonify({"error": "Query is required"}), 400

    _audit("ai_query", _session_email(), f"query={q[:300]}")

    if pinecone_chat is not None:
        try:
            answer = pinecone_chat(q)
            return jsonify({"response": answer}), 200
        except Exception as exc:
            logging.exception("Pinecone assistant call failed")
            logging.warning("Falling back to OCRWebApp /query_ai after Pinecone failure: %s", exc)

    # Secondary path: OCRWebApp backend AI endpoint.
    headers = {"Content-Type": "application/json"}
    if BACKEND_API_KEY:
        headers["X-API-Key"] = BACKEND_API_KEY

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{BACKEND_BASE_URL}/query_ai", headers=headers, json={"query": q})
            if resp.status_code == 200:
                payload = resp.json()
                answer = payload.get("response") or payload.get("answer") or payload.get("result") or str(payload)
                return jsonify({"response": answer}), 200
            logging.warning("OCRWebApp /query_ai failed with status %s: %s", resp.status_code, resp.text[:300])
    except Exception as exc:
        logging.warning("OCRWebApp /query_ai unavailable: %s", exc)

    return jsonify({"response": f"[local fallback] {q}"}), 200

# ----------------------------------------------------------------------------- #
# ----------------------------------------------------------------------------- #


@app.route("/access")
def access_gate():
    debug_enabled = os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "y", "on"}
    return render_template(
        "access.html",
        contact_email=CONTACT_EMAIL,
        debug_enabled=debug_enabled,
        access_request_url=ACCESS_REQUEST_URL,
    )


@app.route("/access/magic")
def access_magic_redirect():
    """Approval emails link here first (your domain), then redirect to Apps Script Web App.

    Gmail and multi-account Chrome often rewrite script.google.com links to
    /macros/u/N/s/... which breaks for recipients. A first hop on rscap avoids that.
    """
    token = (request.args.get("t") or "").strip()
    if not token:
        return "Missing access token.", 400
    base = _normalize_apps_script_exec_url(APPS_SCRIPT_WEB_APP_EXEC_URL)
    if not base:
        return (
            "Email magic links are not configured. Set APPS_SCRIPT_WEB_APP_EXEC_URL to your "
            "Apps Script Web App URL (https://script.google.com/macros/s/.../exec), reload the web app, "
            "and resend the approval email.",
            503,
        )
    target = f"{base}?t={urllib.parse.quote(token, safe='')}"
    return redirect(target, code=302)


@app.route("/access/session")
def access_session():
    email = (request.args.get("e") or "").strip().lower()
    exp = (request.args.get("exp") or "").strip()
    sig = (request.args.get("sig") or "").strip()
    incoming_role = (request.args.get("role") or "default").strip().lower()
    dl_hour = (request.args.get("dl_hour") or "").strip()
    dl_day = (request.args.get("dl_day") or "").strip()
    zip_day = (request.args.get("zip_day") or "").strip()
    unlimited = _is_true(request.args.get("unlimited"))

    # Keep a simple two-tier model:
    # - default role is capped
    # - unlimited role is uncapped
    # .gov users are mapped into the unlimited role automatically.
    is_gov_email = email.endswith(".gov")
    if is_gov_email:
        role = UNLIMITED_ACCESS_ROLE
    else:
        role = "default" if incoming_role in {"", "default"} else UNLIMITED_ACCESS_ROLE
    unlimited = (role == UNLIMITED_ACCESS_ROLE)

    if not email:
        return "Missing email in access link.", 400

    if REQUIRE_MAGIC_LINK_SIGNATURE and not ACCESS_HANDOFF_SECRET:
        return (
            "Magic-link access is disabled because ACCESS_HANDOFF_SECRET is not set on the server.",
            503,
        )

    if ACCESS_HANDOFF_SECRET:
        legacy_payload = f"{email}|{exp}"
        extended_payload = f"{email}|{exp}|{role}|{dl_hour}|{dl_day}|{zip_day}|{int(unlimited)}"
        expected_legacy = hmac.new(ACCESS_HANDOFF_SECRET.encode("utf-8"), legacy_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        expected_extended = hmac.new(ACCESS_HANDOFF_SECRET.encode("utf-8"), extended_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        signature_valid = bool(sig) and (
            hmac.compare_digest(sig, expected_legacy) or hmac.compare_digest(sig, expected_extended)
        )
        if not signature_valid:
            return "Invalid or missing signature.", 403

    if ENFORCE_MAGIC_LINK_EXPIRY:
        if not exp:
            return "Missing expiration timestamp.", 400
        try:
            if int(exp) < int(time.time()):
                return "This access link has expired.", 403
        except ValueError:
            return "Invalid expiration timestamp.", 400

    session["access_email"] = email
    session["access_role"] = role
    session["access_session_id"] = secrets.token_hex(16)
    if dl_hour:
        session["downloads_per_hour"] = _to_int(dl_hour, DEFAULT_DOWNLOADS_PER_HOUR)
    if dl_day:
        session["downloads_per_day"] = _to_int(dl_day, DEFAULT_DOWNLOADS_PER_DAY)
    if zip_day:
        session["zips_per_day"] = _to_int(zip_day, DEFAULT_ZIPS_PER_DAY)
    session["unlimited_access"] = bool(unlimited)

    _audit("access_session", email, f"role={role} unlimited={session['unlimited_access']}")
    return redirect(url_for("tool_hub"))


@app.route("/dev/magiclink")
def dev_magiclink():
    """
    Local-only helper to create a valid magic-link URL.

    Enabled only when FLASK_DEBUG=true. This avoids manually generating
    signatures during local testing. Do not rely on this in production.
    """
    debug_enabled = os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "y", "on"}
    if not debug_enabled:
        return abort(404)
    if not ACCESS_HANDOFF_SECRET:
        return "ACCESS_HANDOFF_SECRET is not set. Add it to .env and restart Flask.", 503

    email = (request.args.get("e") or "local@test").strip().lower()
    exp = str(int(time.time()) + 3600)
    sig = hmac.new(
        ACCESS_HANDOFF_SECRET.encode("utf-8"),
        f"{email}|{exp}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    target = url_for("access_session", e=email, exp=exp, sig=sig, _external=True)
    return redirect(target)


@app.route("/access/logout")
def access_logout():
    email = _session_email()
    session.clear()
    _audit("logout", email, "session cleared")
    return redirect(url_for("access_gate"))


@app.route("/launch_rag")
def launch_rag():
    """Hand the authenticated user off to the Streamlit RAG agent.

    Mints a short-lived HMAC-signed token that the Streamlit app verifies
    using the same ACCESS_HANDOFF_SECRET. Direct hits to the Streamlit URL
    without a valid token are rejected on the Streamlit side.
    """
    access_redirect = _require_access()
    if access_redirect:
        return access_redirect

    if not STREAMLIT_BASE_URL:
        return ("Streamlit RAG agent is not configured. "
                "Set STREAMLIT_BASE_URL in the server environment."), 503
    if not ACCESS_HANDOFF_SECRET:
        return ("Streamlit RAG handoff disabled: ACCESS_HANDOFF_SECRET is not set "
                "on the server. The Streamlit app cannot be reached securely "
                "without a shared signing secret."), 503

    email = _session_email()
    role = (session.get("access_role") or "default").strip().lower()
    params = _make_streamlit_handoff_params(email, role)
    qs = urllib.parse.urlencode(params)
    target = f"{STREAMLIT_BASE_URL}?{qs}"

    _audit("launch_rag", email, f"role={role} ttl={STREAMLIT_TOKEN_TTL_SECONDS}s")
    return redirect(target)


def _browse_search(field: str, term: str):
    if field not in BROWSE_FIELDS:
        raise ValueError("Invalid browse field")

    conn = mysql.connector.connect(**database_config)
    cursor = conn.cursor(dictionary=True)
    like_term = f"%{term}%"

    query = f"""
        SELECT
            m.{field} AS group_value,
            COUNT(*) AS letter_count,
            COUNT(DISTINCT COALESCE(NULLIF(m.cdcr_number, ''), NULLIF(m.case_number, ''), NULLIF(m.convict_name, ''), CAST(m.pdf_id AS CHAR))) AS people_count
        FROM metadata m
        WHERE m.{field} IS NOT NULL AND m.{field} <> '' AND m.{field} LIKE %s
        GROUP BY m.{field}
        ORDER BY letter_count DESC
        LIMIT 250
    """
    cursor.execute(query, (like_term,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def _lookup_search(field: str, term: str):
    if field not in LOOKUP_FIELDS:
        raise ValueError("Invalid lookup field")

    conn = mysql.connector.connect(**database_config)
    cursor = conn.cursor(dictionary=True)
    like_term = f"%{term}%"
    query = f"""
        SELECT
            p.id AS pdf_id,
            p.filename,
            p.file_path,
            m.convict_name,
            m.cdcr_number,
            m.case_number,
            m.judge,
            m.institution,
            m.county,
            m.sentence_date,
            m.action_taken,
            m.ethnicity,
            m.race,
            m.cohort,
            m.notes
        FROM metadata m
        JOIN pdfs p ON p.id = m.pdf_id
        WHERE m.{field} IS NOT NULL
          AND m.{field} LIKE %s
        ORDER BY m.convict_name, p.filename
        LIMIT 500
    """
    cursor.execute(query, (like_term,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def _person_identifier(row: dict):
    for field in ("cdcr_number", "case_number", "convict_name"):
        value = (row.get(field) or "").strip()
        if value:
            return field, value
    return "pdf_id", str(row.get("pdf_id"))


@app.route("/toolhub", methods=["GET", "POST"])
def tool_hub():
    access_redirect = _require_access()
    if access_redirect:
        return access_redirect

    unified_fields = dict(LOOKUP_FIELDS)
    for key, label in BROWSE_FIELDS.items():
        unified_fields[key] = label

    search_field = request.values.get("search_field", "county")
    search_term = (request.values.get("search_term") or "").strip()
    aggregate_results = []
    detail_results = []
    error_message = ""

    if request.method == "POST" and search_term:
        try:
            if search_field not in unified_fields:
                raise ValueError("Invalid search field")

            if search_field in BROWSE_FIELDS:
                aggregate_results = _browse_search(search_field, search_term)
            else:
                # For non-aggregate-first fields, still provide grouped context.
                conn = mysql.connector.connect(**database_config)
                cursor = conn.cursor(dictionary=True)
                like_term = f"%{search_term}%"
                query = f"""
                    SELECT
                        m.{search_field} AS group_value,
                        COUNT(*) AS letter_count,
                        COUNT(DISTINCT COALESCE(NULLIF(m.cdcr_number, ''), NULLIF(m.case_number, ''), NULLIF(m.convict_name, ''), CAST(m.pdf_id AS CHAR))) AS people_count
                    FROM metadata m
                    WHERE m.{search_field} IS NOT NULL AND m.{search_field} <> '' AND m.{search_field} LIKE %s
                    GROUP BY m.{search_field}
                    ORDER BY letter_count DESC
                    LIMIT 100
                """
                cursor.execute(query, (like_term,))
                aggregate_results = cursor.fetchall()
                cursor.close()
                conn.close()

            detail_results = _lookup_search(search_field, search_term)
            for row in detail_results:
                row["download_token"] = _make_download_token(row["pdf_id"], _session_email())
                person_field, person_value = _person_identifier(row)
                row["zip_token"] = _make_zip_token(person_field, person_value, _session_email())

            _audit(
                "toolhub_search",
                _session_email(),
                f"field={search_field} term={search_term} aggregate={len(aggregate_results)} detail={len(detail_results)}",
            )
        except Exception as exc:
            logging.exception("Tool hub search failed")
            error_message = f"Search failed: {exc}"

    limits = _session_limits()
    return render_template(
        "tool_hub.html",
        unified_fields=unified_fields,
        search_field=search_field,
        search_term=search_term,
        aggregate_results=aggregate_results,
        detail_results=detail_results,
        error_message=error_message,
        contact_email=CONTACT_EMAIL,
        access_email=_session_email(),
        access_role=session.get("access_role", "default"),
        limits=limits,
        backend_base_url=BACKEND_BASE_URL,
        streamlit_rag_enabled=bool(STREAMLIT_BASE_URL and ACCESS_HANDOFF_SECRET),
    )


@app.route("/tool-hub", methods=["GET", "POST"])
def tool_hub_alias():
    return tool_hub()


@app.route("/download/signed/<token>")
def download_signed(token):
    access_redirect = _require_access()
    if access_redirect:
        return access_redirect

    try:
        payload = _serializer().loads(token, max_age=DOWNLOAD_LINK_MAX_AGE_SEC)
    except SignatureExpired:
        return "This download link expired. Re-run your lookup search and try again.", 403
    except BadSignature:
        return "Invalid download link.", 403

    email = _session_email()
    if payload.get("email") != email:
        return "This download link is not valid for your session.", 403

    limit_message = _check_and_increment_limit("download")
    if limit_message:
        return limit_message, 429

    file_id = payload.get("file_id")
    conn = mysql.connector.connect(**database_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, filename, file_path FROM pdfs WHERE id = %s", (file_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return "File not found.", 404

    resolved_path = _resolve_file_path(row["file_path"])
    if not resolved_path:
        return f"File path does not exist on this server: {row['file_path']}", 404

    _audit("download", email, f"file_id={file_id} name={row['filename']}")
    return send_file(resolved_path, as_attachment=True, download_name=row["filename"])


@app.route("/download/person_zip/<token>")
def download_person_zip(token):
    access_redirect = _require_access()
    if access_redirect:
        return access_redirect

    try:
        payload = _serializer().loads(token, max_age=DOWNLOAD_LINK_MAX_AGE_SEC)
    except SignatureExpired:
        return "This ZIP link expired. Re-run your lookup search and try again.", 403
    except BadSignature:
        return "Invalid ZIP link.", 403

    email = _session_email()
    if payload.get("email") != email:
        return "This ZIP link is not valid for your session.", 403

    limit_message = _check_and_increment_limit("zip")
    if limit_message:
        return limit_message, 429

    lookup_field = payload.get("lookup_field")
    lookup_value = payload.get("lookup_value")
    if lookup_field not in {"cdcr_number", "case_number", "convict_name", "pdf_id"}:
        return "Invalid ZIP request.", 400

    conn = mysql.connector.connect(**database_config)
    cursor = conn.cursor(dictionary=True)
    if lookup_field == "pdf_id":
        cursor.execute("""
            SELECT p.id, p.filename, p.file_path
            FROM pdfs p
            WHERE p.id = %s
        """, (lookup_value,))
    else:
        cursor.execute(f"""
            SELECT p.id, p.filename, p.file_path
            FROM metadata m
            JOIN pdfs p ON p.id = m.pdf_id
            WHERE m.{lookup_field} = %s
            ORDER BY p.filename
        """, (lookup_value,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return "No files found for this person.", 404

    archive = BytesIO()
    added = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            resolved_path = _resolve_file_path(row["file_path"])
            if resolved_path and os.path.exists(resolved_path):
                zf.write(resolved_path, arcname=row["filename"])
                added += 1

    if added == 0:
        return "No downloadable files were found on this server for this ZIP request.", 404

    archive.seek(0)
    safe_value = str(lookup_value).replace(" ", "_")
    zip_name = f"{lookup_field}_{safe_value}_letters.zip"
    _audit("zip_download", email, f"field={lookup_field} value={lookup_value} files={added}")
    return send_file(archive, mimetype="application/zip", as_attachment=True, download_name=zip_name)

@app.route('/about')
def about():
    """
    Renders the 'About' page.
    """
    return render_template('about.html')

def _render_archive_legacy():
    """
    Legacy archive page renderer retained for reference/testing.
    """
    return render_template('archive.html')


@app.route('/archive')
def archive():
    """
    Archive is disconnected from primary navigation.
    Route now forwards users to Tool Hub.
    """
    return redirect(url_for("tool_hub"))


@app.route('/archive_legacy')
def archive_legacy():
    """
    Explicit legacy route to keep old archive implementation accessible.
    """
    return _render_archive_legacy()

def _archive_search_legacy():
    """
    Legacy archive search handler retained for reference/testing.
    """
    search_term = request.form.get("search_term")
    search_field = request.form.get("search_field")

    conn = mysql.connector.connect(**database_config)
    cursor = conn.cursor(dictionary=True)

    # Base query to join metadata and pdfs table
    query = "SELECT m.*, p.file_path FROM metadata m JOIN pdfs p ON m.pdf_id = p.id WHERE 1=1"
    params = []

    # Add dynamic WHERE clause only if both field and term are provided
    if search_term and search_field:
        query += f" AND m.{search_field} LIKE %s"
        params.append(f"%{search_term}%")

    cursor.execute(query, params)
    results = cursor.fetchall()
    conn.close()

    return render_template('archive.html', results=results)


@app.route('/archive_search', methods=['POST'])
def archive_search():
    """
    Archive search endpoint is disconnected from main UX and forwards to Tool Hub.
    """
    return redirect(url_for("tool_hub"))


@app.route('/archive_search_legacy', methods=['POST'])
def archive_search_legacy():
    """
    Explicit legacy endpoint to keep old archive search behavior available.
    """
    return _archive_search_legacy()

@app.route('/download/<int:file_id>')
def download_file(file_id):
    """
    Serves a requested PDF file for download by file ID.

    Args:
        file_id (int): The ID of the file in the 'pdfs' table.

    Returns:
        Flask Response: Sends the file if it exists or a 404 error if not found.
    """
    conn = mysql.connector.connect(**database_config)
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM pdfs WHERE id = %s", (file_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        # Ensure this matches where the PDFs are located
        pdf_directory = os.path.join(os.getcwd(), 'static')  # or 'processed' or the right folder
        filepath = os.path.join(pdf_directory, result[0])

        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True)
        else:
            return f"File not found at {filepath}", 404
    else:
        return "Invalid file ID", 404

@app.route('/templates/privacy')
def privacy():
    """
    Renders the 'Privacy Policy' page.
    """
    return render_template('privacy.html')

@app.route('/templates/terms')
def terms():
    """
    Renders the 'Terms of Use' page.
    """
    return render_template('terms.html')

@app.route('/templates/contact')
def contact():
    """
    Renders the 'Contact Us' page.
    """
    return render_template('contact.html')

@app.route('/')
def home():
    """
    Renders the homepage.
    """
    return render_template(
        'index.html',
        contact_email=CONTACT_EMAIL,
        github_repo_url=GITHUB_REPO_URL,
        access_request_url=ACCESS_REQUEST_URL,
    )

@app.route('/visualize')
def visualize():
    """
    Legacy server-rendered image chart endpoint (deprecated).
    Use /api/stats + Chart.js on the frontend.
    """
    return (
        jsonify(
            {
                "error": "Deprecated endpoint",
                "message": "Use /api/stats (JSON) and frontend Chart.js rendering instead.",
            }
        ),
        410,
    )


@app.route('/api/stats')
def api_stats():
    """
    Return JSON data for frontend visualizations
    Supported datasets:
      - letters_by_county
      - years_reduced
      - sentence_type
      - parole_eligibility
      - action_taken
      - race_distribution
      - ethnicity_distribution
      - isl_dsl_outcome
    """
    dataset_type = request.args.get('dataset', 'years_reduced')
    try:
        df = fetch_data_from_db(dataset_type)
        if df.empty:
            return jsonify({"dataset": dataset_type, "data": []}), 200
        # pandas to_json handles NaN, datetime, etc. for clean JSON
        import json
        data = json.loads(df.to_json(orient='records', date_format='iso'))
        return jsonify({"dataset": dataset_type, "data": data}), 200
    except Exception as e:
        logging.error(f"Error fetching stats for {dataset_type}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/public_summary')
def api_public_summary():
    """
    Return Priority-1 public summary metrics for the homepage dashboard.
    """
    try:
        conn = mysql.connector.connect(**database_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                COUNT(*) AS total_letters,
                COUNT(
                    DISTINCT COALESCE(
                        NULLIF(TRIM(cdcr_number), ''),
                        NULLIF(TRIM(case_number), ''),
                        NULLIF(TRIM(convict_name), ''),
                        CAST(pdf_id AS CHAR)
                    )
                ) AS total_individuals,
                COUNT(DISTINCT NULLIF(TRIM(county), '')) AS total_counties
            FROM metadata
        """)
        row = cursor.fetchone() or {}

        data_freshness = {
            "main_log": None,
            "race_data": None,
            "letters_db": None,
        }
        try:
            cursor.execute(_DATASET_LINEAGE_TABLE_SQL)
            cursor.execute(
                """
                SELECT source_key, refreshed_at, detail
                FROM dataset_source_refresh
                WHERE source_key IN ('main_log', 'race_data', 'letters_db')
                """
            )
            for r in cursor.fetchall() or []:
                key = r.get("source_key")
                if key not in data_freshness:
                    continue
                ts = r.get("refreshed_at")
                if ts is not None and hasattr(ts, "isoformat"):
                    ts_out = ts.isoformat()
                else:
                    ts_out = str(ts) if ts is not None else None
                data_freshness[key] = {
                    "as_of": ts_out,
                    "source_file": r.get("detail"),
                }
        except mysql.connector.Error as lineage_err:
            logging.debug("dataset lineage read skipped: %s", lineage_err)

        _merge_public_freshness_fallbacks(data_freshness)

        cursor.close()
        conn.close()
        return jsonify({
            "total_letters": int(row.get("total_letters") or 0),
            "total_individuals": int(row.get("total_individuals") or 0),
            "total_counties": int(row.get("total_counties") or 0),
            "data_freshness": data_freshness,
        }), 200
    except Exception as e:
        logging.error(f"Error fetching public summary metrics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/poster_view')
def api_poster_view():
    """
    Return a poster-ready impact summary that highlights pipeline drop-off and
    outcome impact at a glance.
    """
    try:
        conn = mysql.connector.connect(**database_config)
        cursor = conn.cursor(dictionary=True)

        success_case_expr = """
            CASE
                WHEN LOWER(COALESCE(action_taken, '')) LIKE '%resentenced%'
                  OR LOWER(COALESCE(action_taken, '')) LIKE '%released%'
                  OR LOWER(COALESCE(action_taken, '')) LIKE '%grant%'
                  OR LOWER(COALESCE(action_taken, '')) LIKE '%approved%'
                  OR LOWER(COALESCE(action_taken, '')) LIKE '%recalled%'
                THEN 1 ELSE 0
            END
        """

        cursor.execute(f"""
            SELECT
                COUNT(*) AS total_letters,
                SUM(CASE WHEN action_taken IS NOT NULL AND TRIM(action_taken) <> '' THEN 1 ELSE 0 END) AS court_action_cases,
                SUM({success_case_expr}) AS successful_cases,
                AVG(CASE WHEN {success_case_expr} = 1 THEN years_reduced END) AS avg_years_reduced_success,
                SUM(CASE WHEN {success_case_expr} = 1 THEN COALESCE(years_reduced, 0) ELSE 0 END) AS total_years_reduced_success
            FROM metadata
        """)
        row = cursor.fetchone() or {}
        cursor.close()
        conn.close()

        total_letters = int(row.get("total_letters") or 0)
        court_action_cases = int(row.get("court_action_cases") or 0)
        successful_cases = int(row.get("successful_cases") or 0)
        avg_years = float(row.get("avg_years_reduced_success") or 0.0)
        total_years = float(row.get("total_years_reduced_success") or 0.0)

        def pct(part: int, whole: int) -> float:
            return round((part / whole) * 100, 1) if whole > 0 else 0.0

        # MasterGuide-aligned funnel language (considered → letters sent → resentenced).
        # Stage counts are computed from metadata rows; see funnel_definitions for caveats.
        stages = [
            {
                "label": "Considered",
                "value": total_letters,
                "rate_from_start": 100.0 if total_letters > 0 else 0.0,
                "definition": "All resentencing letter records in the dataset (one metadata row per tracked letter event).",
            },
            {
                "label": "Letters sent",
                "value": court_action_cases,
                "rate_from_start": pct(court_action_cases, total_letters),
                "definition": "Records with a populated court/outcome field (action taken). Proxies progression after the letter; not the same as a mail timestamp.",
            },
            {
                "label": "Resentenced",
                "value": successful_cases,
                "rate_from_start": pct(successful_cases, total_letters),
                "definition": "Subset where action indicates resentencing, release, grant, approval, or recall (rule-based on action_taken text).",
            },
        ]

        funnel_definitions = {
            "framing": "Funnel labels follow the project reporting guide (considered → letters sent → resentenced). Counts are descriptive, not a causal trial.",
            "considered": stages[0]["definition"],
            "letters_sent": stages[1]["definition"],
            "resentenced": stages[2]["definition"],
            "missingness": "Blank court fields, lagging logs, or letters not yet ingested shrink downstream stages. Race/ethnicity merge depends on the active race spreadsheet.",
        }

        return jsonify({
            "stages": stages,
            "funnel_definitions": funnel_definitions,
            "impact": {
                "avg_years_reduced_success": round(avg_years, 2),
                "total_years_reduced_success": round(total_years, 2),
                "success_rate_from_all_letters": pct(successful_cases, total_letters),
            }
        }), 200
    except Exception as e:
        logging.error(f"Error building poster view payload: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/prof/variables')
def api_prof_variables():
    """
    Return all metadata table columns for the professor variable explorer.
    """
    try:
        columns = _metadata_columns()
        return jsonify({
            "variables": [{"key": c, "label": _labelize_column(c)} for c in columns]
        }), 200
    except Exception as e:
        logging.error(f"Error fetching metadata columns: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/prof/distribution')
def api_prof_distribution():
    """
    Return grouped counts for any metadata column for professor exploration.
    Query params:
      - field: metadata column name
      - top_n: max buckets (default 20)
      - mode: raw | year | auto
    """
    field = (request.args.get("field") or "").strip()
    mode = (request.args.get("mode") or "auto").strip().lower()

    try:
        top_n = int(request.args.get("top_n", "20"))
    except ValueError:
        top_n = 20
    top_n = max(3, min(top_n, 100))

    try:
        allowed = set(_metadata_columns())
        if field not in allowed:
            return jsonify({"error": "Invalid field"}), 400

        use_year_mode = (mode == "year") or (mode == "auto" and "date" in field.lower())

        conn = mysql.connector.connect(**database_config)
        cursor = conn.cursor(dictionary=True)

        if use_year_mode:
            query = f"""
                SELECT
                    YEAR(`{field}`) AS bucket,
                    COUNT(*) AS count
                FROM metadata
                WHERE `{field}` IS NOT NULL
                  AND `{field}` <> ''
                  AND YEAR(`{field}`) IS NOT NULL
                GROUP BY YEAR(`{field}`)
                ORDER BY bucket ASC
                LIMIT %s
            """
            cursor.execute(query, (top_n,))
        else:
            query = f"""
                SELECT
                    CAST(`{field}` AS CHAR(255)) AS bucket,
                    COUNT(*) AS count
                FROM metadata
                WHERE `{field}` IS NOT NULL
                  AND TRIM(CAST(`{field}` AS CHAR(255))) <> ''
                GROUP BY CAST(`{field}` AS CHAR(255))
                ORDER BY count DESC
                LIMIT %s
            """
            cursor.execute(query, (top_n,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        labels = []
        values = []
        for row in rows:
            bucket = row.get("bucket")
            labels.append(str(bucket) if bucket is not None else "Unknown")
            values.append(int(row.get("count") or 0))

        return jsonify({
            "field": field,
            "field_label": _labelize_column(field),
            "mode": "year" if use_year_mode else "raw",
            "top_n": top_n,
            "labels": labels,
            "values": values
        }), 200
    except Exception as e:
        logging.error(f"Error fetching professor distribution for {field}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/prof/cross_distribution')
def api_prof_cross_distribution():
    """
    Return pairwise grouped counts for two metadata fields so the professor
    can compare variables against each other.
    Query params:
      - x_field, y_field: metadata column names
      - x_mode, y_mode: raw | year | auto
      - top_x, top_y: max buckets kept per axis
    """
    x_field = (request.args.get("x_field") or "").strip()
    y_field = (request.args.get("y_field") or "").strip()
    x_mode = (request.args.get("x_mode") or "auto").strip().lower()
    y_mode = (request.args.get("y_mode") or "auto").strip().lower()

    try:
        top_x = int(request.args.get("top_x", "12"))
    except ValueError:
        top_x = 12
    try:
        top_y = int(request.args.get("top_y", "8"))
    except ValueError:
        top_y = 8

    top_x = max(3, min(top_x, 40))
    top_y = max(2, min(top_y, 20))

    try:
        allowed = set(_metadata_columns())
        if x_field not in allowed or y_field not in allowed:
            return jsonify({"error": "Invalid x_field or y_field"}), 400

        x_is_year = (x_mode == "year") or (x_mode == "auto" and "date" in x_field.lower())
        y_is_year = (y_mode == "year") or (y_mode == "auto" and "date" in y_field.lower())

        if x_is_year:
            x_expr = f"YEAR(`{x_field}`)"
            x_valid = f"`{x_field}` IS NOT NULL AND `{x_field}` <> '' AND YEAR(`{x_field}`) IS NOT NULL"
        else:
            x_expr = f"CAST(`{x_field}` AS CHAR(255))"
            x_valid = f"`{x_field}` IS NOT NULL AND TRIM(CAST(`{x_field}` AS CHAR(255))) <> ''"

        if y_is_year:
            y_expr = f"YEAR(`{y_field}`)"
            y_valid = f"`{y_field}` IS NOT NULL AND `{y_field}` <> '' AND YEAR(`{y_field}`) IS NOT NULL"
        else:
            y_expr = f"CAST(`{y_field}` AS CHAR(255))"
            y_valid = f"`{y_field}` IS NOT NULL AND TRIM(CAST(`{y_field}` AS CHAR(255))) <> ''"

        conn = mysql.connector.connect(**database_config)
        cursor = conn.cursor(dictionary=True)
        query = f"""
            SELECT
                {x_expr} AS x_bucket,
                {y_expr} AS y_bucket,
                COUNT(*) AS count
            FROM metadata
            WHERE {x_valid}
              AND {y_valid}
            GROUP BY {x_expr}, {y_expr}
            ORDER BY count DESC
            LIMIT 12000
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        x_totals = {}
        y_totals = {}
        pair_counts = {}

        for row in rows:
            xb = str(row.get("x_bucket") if row.get("x_bucket") is not None else "Unknown")
            yb = str(row.get("y_bucket") if row.get("y_bucket") is not None else "Unknown")
            c = int(row.get("count") or 0)
            if c <= 0:
                continue
            x_totals[xb] = x_totals.get(xb, 0) + c
            y_totals[yb] = y_totals.get(yb, 0) + c
            pair_counts[(xb, yb)] = pair_counts.get((xb, yb), 0) + c

        x_labels = [k for k, _ in sorted(x_totals.items(), key=lambda t: t[1], reverse=True)[:top_x]]
        y_labels = [k for k, _ in sorted(y_totals.items(), key=lambda t: t[1], reverse=True)[:top_y]]

        matrix = []
        for yb in y_labels:
            series_data = [pair_counts.get((xb, yb), 0) for xb in x_labels]
            matrix.append({"series": yb, "data": series_data})

        return jsonify({
            "x_field": x_field,
            "x_label": _labelize_column(x_field),
            "x_mode": "year" if x_is_year else "raw",
            "y_field": y_field,
            "y_label": _labelize_column(y_field),
            "y_mode": "year" if y_is_year else "raw",
            "x_labels": x_labels,
            "series": matrix
        }), 200
    except Exception as e:
        logging.error(f"Error fetching professor cross distribution: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/prof/value_options')
def api_prof_value_options():
    """
    Return dropdown options for a metadata field (with optional search and filters).
    Query params:
      - field: metadata column name
      - mode: raw | year | auto
      - q: optional text search on bucket label
      - limit: max values (default 250, max 600)
      - filters: JSON object of {field: [values...]}
    """
    field = (request.args.get("field") or "").strip()
    mode = (request.args.get("mode") or "auto").strip().lower()
    search_q = (request.args.get("q") or "").strip()
    raw_filters = (request.args.get("filters") or "").strip()
    try:
        limit = int(request.args.get("limit", "250"))
    except ValueError:
        limit = 250
    limit = max(20, min(limit, 600))

    try:
        allowed = set(_metadata_columns())
        if field not in allowed:
            return jsonify({"error": "Invalid field"}), 400

        expr, valid_clause, resolved_mode = _prof_bucket_parts(field, mode)
        filters = _parse_prof_filters(raw_filters, allowed)

        where_clauses = [valid_clause]
        params = []

        for f_key, f_values in filters.items():
            f_expr, f_valid, _ = _prof_bucket_parts(f_key, "auto")
            placeholders = ", ".join(["%s"] * len(f_values))
            where_clauses.append(f"{f_valid} AND {f_expr} IN ({placeholders})")
            params.extend(f_values)

        if search_q:
            where_clauses.append(f"CAST({expr} AS CHAR(255)) LIKE %s")
            params.append(f"%{search_q}%")

        where_sql = " AND ".join(where_clauses)

        conn = mysql.connector.connect(**database_config)
        cursor = conn.cursor(dictionary=True)
        query = f"""
            SELECT
                {expr} AS bucket,
                COUNT(*) AS count
            FROM metadata
            WHERE {where_sql}
            GROUP BY {expr}
            ORDER BY count DESC
            LIMIT %s
        """
        cursor.execute(query, tuple(params + [limit]))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        options = []
        for row in rows:
            bucket = row.get("bucket")
            if bucket is None:
                continue
            options.append({
                "value": str(bucket),
                "label": str(bucket),
                "count": int(row.get("count") or 0)
            })

        return jsonify({
            "field": field,
            "field_label": _labelize_column(field),
            "mode": resolved_mode,
            "options": options
        }), 200
    except Exception as e:
        logging.error(f"Error fetching value options for {field}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/prof/report')
def api_prof_report():
    """
    Build a report-style grouped chart with optional filter dimensions.
    Query params:
      - x_field, series_field
      - x_mode, series_mode
      - measurement: count | sum:<numeric_field>
      - top_x, top_series
      - filters: JSON object of {field: [values...]}
    """
    x_field = (request.args.get("x_field") or "").strip()
    series_field = (request.args.get("series_field") or "").strip()
    x_mode = (request.args.get("x_mode") or "auto").strip().lower()
    series_mode = (request.args.get("series_mode") or "auto").strip().lower()
    measurement = (request.args.get("measurement") or "count").strip().lower()
    raw_filters = (request.args.get("filters") or "").strip()

    try:
        top_x = int(request.args.get("top_x", "14"))
    except ValueError:
        top_x = 14
    try:
        top_series = int(request.args.get("top_series", "8"))
    except ValueError:
        top_series = 8
    top_x = max(4, min(top_x, 40))
    top_series = max(2, min(top_series, 20))

    try:
        allowed = set(_metadata_columns())
        if x_field not in allowed or series_field not in allowed:
            return jsonify({"error": "Invalid x_field or series_field"}), 400

        x_expr, x_valid, x_resolved_mode = _prof_bucket_parts(x_field, x_mode)
        s_expr, s_valid, s_resolved_mode = _prof_bucket_parts(series_field, series_mode)
        filters = _parse_prof_filters(raw_filters, allowed)

        metric_label = "Record Count"
        metric_expr = "COUNT(*)"
        if measurement.startswith("sum:"):
            sum_field = measurement.split(":", 1)[1].strip()
            if sum_field in allowed:
                metric_expr = f"SUM(COALESCE(CAST(`{sum_field}` AS DECIMAL(18, 4)), 0))"
                metric_label = f"Sum of {_labelize_column(sum_field)}"
            else:
                return jsonify({"error": "Invalid measurement field"}), 400

        where_clauses = [x_valid, s_valid]
        params = []

        for f_key, f_values in filters.items():
            f_expr, f_valid, _ = _prof_bucket_parts(f_key, "auto")
            placeholders = ", ".join(["%s"] * len(f_values))
            where_clauses.append(f"{f_valid} AND {f_expr} IN ({placeholders})")
            params.extend(f_values)

        where_sql = " AND ".join(where_clauses)

        conn = mysql.connector.connect(**database_config)
        cursor = conn.cursor(dictionary=True)
        query = f"""
            SELECT
                {x_expr} AS x_bucket,
                {s_expr} AS series_bucket,
                {metric_expr} AS metric_value
            FROM metadata
            WHERE {where_sql}
            GROUP BY {x_expr}, {s_expr}
            ORDER BY metric_value DESC
            LIMIT 18000
        """
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        x_totals = {}
        series_totals = {}
        pair_values = {}

        for row in rows:
            xb = str(row.get("x_bucket") if row.get("x_bucket") is not None else "Unknown")
            sb = str(row.get("series_bucket") if row.get("series_bucket") is not None else "Unknown")
            metric_value = float(row.get("metric_value") or 0)
            if metric_value <= 0:
                continue
            x_totals[xb] = x_totals.get(xb, 0.0) + metric_value
            series_totals[sb] = series_totals.get(sb, 0.0) + metric_value
            pair_values[(xb, sb)] = pair_values.get((xb, sb), 0.0) + metric_value

        x_labels = [k for k, _ in sorted(x_totals.items(), key=lambda t: t[1], reverse=True)[:top_x]]
        series_labels = [k for k, _ in sorted(series_totals.items(), key=lambda t: t[1], reverse=True)[:top_series]]

        series = []
        for s_label in series_labels:
            values = [pair_values.get((x_label, s_label), 0.0) for x_label in x_labels]
            series.append({
                "series": s_label,
                "data": values
            })

        return jsonify({
            "x_field": x_field,
            "x_label": _labelize_column(x_field),
            "x_mode": x_resolved_mode,
            "series_field": series_field,
            "series_label": _labelize_column(series_field),
            "series_mode": s_resolved_mode,
            "measurement": measurement,
            "measurement_label": metric_label,
            "x_labels": x_labels,
            "series": series
        }), 200
    except Exception as e:
        logging.error(f"Error building professor report: {e}")
        return jsonify({"error": str(e)}), 500


def fetch_data_from_db(dataset_type):
    """
    Fetches relevant data from the database for the specified dataset type.

    Args:
        dataset_type (str): Public dashboard dataset key.

    Returns:
        pandas.DataFrame: DataFrame containing the required dataset.
    """
    conn = mysql.connector.connect(**database_config)

    if dataset_type == 'letters_by_county':
        query = "SELECT county FROM metadata WHERE county IS NOT NULL AND TRIM(county) <> '';"
    elif dataset_type == 'years_reduced':
        query = "SELECT county, years_reduced FROM metadata WHERE years_reduced IS NOT NULL;"
    elif dataset_type == 'sentence_type':
        query = "SELECT isl_dsl FROM metadata WHERE isl_dsl IS NOT NULL;"
    elif dataset_type == 'parole_eligibility':
        query = "SELECT parole_eligibility_date FROM metadata WHERE parole_eligibility_date IS NOT NULL;"
    elif dataset_type == 'action_taken':
        query = "SELECT action_taken FROM metadata WHERE action_taken IS NOT NULL AND TRIM(action_taken) <> '';"
    elif dataset_type == 'race_distribution':
        query = """
            SELECT race, action_taken
            FROM metadata
            WHERE race IS NOT NULL AND TRIM(race) <> ''
        """
    elif dataset_type == 'ethnicity_distribution':
        query = """
            SELECT ethnicity, action_taken
            FROM metadata
            WHERE ethnicity IS NOT NULL AND TRIM(ethnicity) <> ''
        """
    elif dataset_type == 'isl_dsl_outcome':
        query = """
            SELECT isl_dsl, action_taken
            FROM metadata
            WHERE (isl_dsl IS NOT NULL AND TRIM(isl_dsl) <> '')
               OR (action_taken IS NOT NULL AND TRIM(action_taken) <> '')
        """
    else:
        query = "SELECT county, years_reduced FROM metadata WHERE years_reduced IS NOT NULL;"

    df = pd.read_sql(query, conn)
    conn.close()
    return df


def generate_cache_filename(dataset_type):
    """
    Generates a unique filename for caching a dataset visualization.

    Args:
        dataset_type (str): Name of the dataset (e.g., 'years_reduced').

    Returns:
        str: A hashed filename ending in '.png'.
    """
    hash_object = hashlib.md5(dataset_type.encode())
    return f"{hash_object.hexdigest()}.png"

if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')