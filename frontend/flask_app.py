from flask import Flask, render_template, Response, request, url_for, send_file, abort, jsonify, session, redirect
from flask_cors import CORS
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd
import mysql.connector
from io import BytesIO
import os
import logging
import hashlib
import hmac
import time
import secrets
import zipfile
import datetime
import json
import httpx
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# Load environment variables
load_dotenv()


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)

# Enable CORS for frontend -> backend communication (v1 for testing)
CORS(app, resources={
    r"/query_ai": {
        "origins": ["null", "http://localhost:8000", "http://127.0.0.1:8000"]
    },
    r"/api/stats": {
        "origins": ["*"]  # Allow frontend from any origin to fetch stats JSON
    }
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
ACCESS_REQUEST_URL = os.getenv("ACCESS_REQUEST_URL", "").strip()
DOWNLOAD_LINK_MAX_AGE_SEC = int(os.getenv("DOWNLOAD_LINK_MAX_AGE_SEC", "900"))
DEFAULT_DOWNLOADS_PER_HOUR = int(os.getenv("DOWNLOADS_PER_HOUR", "10"))
DEFAULT_DOWNLOADS_PER_DAY = int(os.getenv("DOWNLOADS_PER_DAY", "50"))
DEFAULT_ZIPS_PER_DAY = int(os.getenv("ZIPS_PER_DAY", "3"))
ENFORCE_MAGIC_LINK_EXPIRY = os.getenv("ENFORCE_MAGIC_LINK_EXPIRY", "false").lower() == "true"
ROLE_LIMITS_JSON = os.getenv("ROLE_LIMITS_JSON", "{}")

try:
    ROLE_LIMITS = json.loads(ROLE_LIMITS_JSON)
except json.JSONDecodeError:
    logging.warning("ROLE_LIMITS_JSON is invalid JSON; ignoring role overrides")
    ROLE_LIMITS = {}

AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "audit.log")
RATE_STATE = {}

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
    email = _session_email()
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

    if email.endswith(".gov"):
        limits["unlimited"] = True

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

    # Forward to backend AI if configured. Fall back to local echo in dev.
    headers = {"Content-Type": "application/json"}
    if BACKEND_API_KEY:
        headers["X-API-Key"] = BACKEND_API_KEY

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{BACKEND_BASE_URL}/query_ai", headers=headers, json={"query": q})
            if resp.status_code == 200:
                payload = resp.json()
                # Normalized output shape for frontend.
                answer = payload.get("response") or payload.get("answer") or payload.get("result") or str(payload)
                return jsonify({"response": answer}), 200
            logging.warning("Backend AI call failed with status %s: %s", resp.status_code, resp.text[:300])
    except Exception as exc:
        logging.warning("Backend AI unavailable, using local fallback: %s", exc)

    return jsonify({"response": f"[local fallback] {q}"}), 200

# ----------------------------------------------------------------------------- #
# ----------------------------------------------------------------------------- #


@app.route("/access")
def access_gate():
    return render_template("access.html", contact_email=CONTACT_EMAIL)


@app.route("/access/session")
def access_session():
    email = (request.args.get("e") or "").strip().lower()
    exp = (request.args.get("exp") or "").strip()
    sig = (request.args.get("sig") or "").strip()
    role = (request.args.get("role") or "default").strip().lower()
    dl_hour = (request.args.get("dl_hour") or "").strip()
    dl_day = (request.args.get("dl_day") or "").strip()
    zip_day = (request.args.get("zip_day") or "").strip()
    unlimited = _is_true(request.args.get("unlimited"))

    if not email:
        return "Missing email in access link.", 400

    if ACCESS_HANDOFF_SECRET:
        legacy_payload = f"{email}|{exp}"
        extended_payload = f"{email}|{exp}|{role}|{dl_hour}|{dl_day}|{zip_day}|{int(unlimited)}"
        expected_legacy = hmac.new(ACCESS_HANDOFF_SECRET.encode("utf-8"), legacy_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        expected_extended = hmac.new(ACCESS_HANDOFF_SECRET.encode("utf-8"), extended_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not sig or sig not in {expected_legacy, expected_extended}:
            return "Invalid or missing signature.", 403

    if ENFORCE_MAGIC_LINK_EXPIRY and exp:
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


@app.route("/access/logout")
def access_logout():
    email = _session_email()
    session.clear()
    _audit("logout", email, "session cleared")
    return redirect(url_for("access_gate"))


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
    Generates or serves cached data visualizations based on the selected dataset type.

    Dataset types supported:
        - 'years_reduced': Bar chart of years reduced by county.
        - 'sentence_type': Pie chart of ISL/DSL sentence types.
        - 'parole_eligibility': Histogram of parole eligibility years.

    Returns:
        Flask Response: A PNG image of the visualization or a 404/500 error response.
    """
    import logging
    logging.basicConfig(level=logging.DEBUG)

    dataset_type = request.args.get('dataset', 'years_reduced')
    cache_filename = generate_cache_filename(dataset_type)
    cache_path = os.path.join(CACHE_DIR, cache_filename)

    # Check if the cache file already exists
    if os.path.exists(cache_path):
        logging.info(f"Loading cached visualization for {dataset_type}")
        with open(cache_path, 'rb') as f:
            return Response(f.read(), mimetype='image/png')

    # Generate new visualization if not cached
    try:
        df = fetch_data_from_db(dataset_type)

        if df.empty:
            logging.warning(f"No data found for dataset: {dataset_type}")
            return Response("No data available for the requested visualization.", status=404)

        sns.set(rc={'axes.facecolor': '#F9F9F9', 'figure.facecolor': '#F9F9F9'})
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.set_facecolor('#F9F9F9')

        if dataset_type == 'years_reduced':
            sns.barplot(data=df, x='county', y='years_reduced', estimator=sum, ax=ax)
            ax.set_title('Years Reduced by County')
            plt.xticks(rotation=45)

        elif dataset_type == 'sentence_type':
            df = df.groupby('isl_dsl').size().reset_index(name='count')
            ax.pie(df['count'], labels=df['isl_dsl'], autopct='%1.1f%%', startangle=90)
            ax.set_title('Sentence Type Distribution')
            ax.axis('equal')

        elif dataset_type == 'parole_eligibility':
            df['parole_eligibility_date'] = pd.to_datetime(df['parole_eligibility_date'])
            df['parole_eligibility_date'] = df['parole_eligibility_date'].dt.year  # Group by year instead of exact date
            sns.histplot(data=df, x='parole_eligibility_date', kde=True, ax=ax)
            ax.set_title('Parole Eligibility Distribution')
            plt.xticks(rotation=45)

        else:
            logging.error(f"Unknown dataset type requested: {dataset_type}")
            return Response("Invalid dataset type requested.", status=400)

        plt.tight_layout()

        # Save the plot to a cache file
        fig.savefig(cache_path)
        plt.close(fig)

        with open(cache_path, 'rb') as f:
            return Response(f.read(), mimetype='image/png')
    except Exception as e:
        logging.error(f"Error generating visualization: {e}")
        return Response("An error occurred while generating the visualization.", status=500)


@app.route('/api/stats')
def api_stats():
    """
    Return JSON data for frontend visualizations
    Same datasets as /visualize: years_reduced, sentence_type, parole_eligibility.
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


def fetch_data_from_db(dataset_type):
    """
    Fetches relevant data from the database for the specified dataset type.

    Args:
        dataset_type (str): One of 'years_reduced', 'sentence_type', 'parole_eligibility'.

    Returns:
        pandas.DataFrame: DataFrame containing the required dataset.
    """
    conn = mysql.connector.connect(**database_config)

    if dataset_type == 'years_reduced':
        query = "SELECT county, years_reduced FROM metadata WHERE years_reduced IS NOT NULL;"
    elif dataset_type == 'sentence_type':
        query = "SELECT isl_dsl FROM metadata WHERE isl_dsl IS NOT NULL;"
    elif dataset_type == 'parole_eligibility':
        query = "SELECT parole_eligibility_date FROM metadata WHERE parole_eligibility_date IS NOT NULL;"
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