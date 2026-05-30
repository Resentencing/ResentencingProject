from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, jsonify, abort, send_file
import os
import io
import mysql
import openai
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import ocrmypdf
import shutil
import logging
import zipfile
import dbconnector
import extracttext
import tagextraction
from dbconnector import database_config, connect_to_database
import secrets
from openai import OpenAI
from dotenv import load_dotenv
from drive_duplicate_names import upload_basename_variants
import re
import json
import decimal
import datetime
import pymysql
import subprocess
import sys as _sys
from pathlib import Path
try:
    from enhanced_upload_route import enhanced_upload_to_database_route
except Exception:
    enhanced_upload_to_database_route = None

from site_help_knowledge import format_site_help_context, select_site_help_pages


Image.MAX_IMAGE_PIXELS = None


# from mysite.dbconnector_ssh import connect_to_database as connect_to_database_ssh

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI()

# TEMPORARY: Disable database connections for UI testing
DATABASE_DISABLED = False

# Maintain a queue of files to process
processing_queue = []

# Set up logging for easier debugging
logging.basicConfig(level=logging.DEBUG)

# Debug the actual key value
api_key = os.getenv("OPENAI_API_KEY")

# Ensure environment variables and API key setup
os.environ['PATH'] = '/home/RSCAP/.virtualenvs/myvirtualenv/bin:' + os.environ['PATH']

# Load OpenAI API key from environment variables
openai_api_key = os.getenv("OPENAI_API_KEY")
# Set To Required Variable
openai.api_key = openai_api_key
if not openai.api_key:
    logging.error("OpenAI API key not set. Please set OPENAI_API_KEY in environment variables.")
    raise RuntimeError("OpenAI API key not configured!")

# Flask app configuration
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # Securely generate a random secret key
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'processed'
app.config['EXTRACTIONS']='OCRextractions'

# Purpose-specific key for Apps Script/backend ingestion auth.
# Backward-compatible fallback to API_KEY during migration.
INGEST_API_KEY = os.getenv("INGEST_API_KEY", "") or os.getenv("API_KEY", "")

if not INGEST_API_KEY:
    # Fail if not configured.
    logging.error("INGEST_API_KEY (or fallback API_KEY) is NOT set. "
                  "All X-API-Key checks will fail until it's configured.")

def _api_key_ok() -> bool:
    """
    Validates the incoming request by checking the 'X-API-Key' header against the
    environment-provided ingestion API key using constant-time comparison.
    """
    incoming = (request.headers.get("X-API-Key") or "").strip()
    expected = INGEST_API_KEY
    # If either is missing, reject.
    if not expected or not incoming:
        return False
    return secrets.compare_digest(incoming, expected)

def authorized() -> bool:
    """
    Authorization passes if EITHER:
      - the user has a logged-in session (admin UI on PythonAnywhere), OR
      - the request presents a valid 'X-API-Key' shared secret from the Netlify Function.
    """
    return bool(session.get("logged_in")) or _api_key_ok()

def require_auth_json():
    """
    Short-circuits unauthorized requests for JSON APIs with 401.
    Routes can call this and return early if it returns a response.
    """
    if not authorized():
        return jsonify({"error": "Unauthorized"}), 401


def _mysite_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _dashboard_logs_dir():
    d = os.getenv("LOG_DIR")
    if d:
        return d
    return os.path.join(_mysite_dir(), "logs")


def _archive_dir_resolved():
    archive_dir = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
    if archive_dir.startswith("/home/RSCAP") and not os.path.exists("/home/RSCAP"):
        archive_dir = os.path.join(_mysite_dir(), "shared", "archive_directory")
    return archive_dir


def _virtualenv_python_candidates():
    """Known PythonAnywhere venv paths (PA sets sys.executable to uwsgi, not Python)."""
    home = os.path.expanduser("~")
    return (
        os.path.join(home, ".virtualenvs", "myvirtualenv", "bin", "python3"),
        os.path.join(home, ".virtualenvs", "myvirtualenv", "bin", "python"),
        "/home/RSCAP/.virtualenvs/myvirtualenv/bin/python3",
        "/home/RSCAP/.virtualenvs/myvirtualenv/bin/python",
    )


def _pipeline_python():
    """
    Interpreter for pipeline scripts (metadata_refresh, fileconsistencycheck).

    Under uWSGI on PythonAnywhere, sys.executable is the uwsgi binary. Spawning
    [sys.executable, "metadata_refresh.py"] makes uwsgi treat the script as a
    config file ("unable to load configuration from metadata_refresh.py").
    """
    explicit = (os.environ.get("PYTHON_EXECUTABLE") or "").strip()
    if explicit:
        return explicit

    exe = _sys.executable or ""
    base = os.path.basename(exe).lower()
    if base.startswith("python"):
        return exe
    if "uwsgi" not in base:
        if os.path.isfile(exe) and os.access(exe, os.X_OK):
            return exe

    for candidate in _virtualenv_python_candidates():
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    return exe or "python3"


def _pipeline_subprocess_env():
    """Subprocess env with venv bin on PATH (dotenv vars from the web app)."""
    env = os.environ.copy()
    bin_dir = os.path.dirname(_pipeline_python())
    if bin_dir:
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env


def _log_reconcile_summary():
    """Counts for Missing Letters page (no full missing[] list — loaded via API)."""
    from log_reconcile import load_log_reconcile

    data = load_log_reconcile()
    if not isinstance(data, dict):
        return {}
    keys = (
        "error",
        "log_filename",
        "log_file_modified",
        "total_log",
        "total_log_raw",
        "letter_created_filter",
        "matched",
        "missing_count",
        "extra_in_db_count",
        "match_by_cdcr",
        "match_by_case",
        "match_by_name_county",
    )
    return {k: data[k] for k in keys if k in data}


def _load_dashboard_recent_activity(max_items=10):
    """Parse tail of ``upload_safety.log`` into activity rows (most recent first)."""
    path = os.path.join(_dashboard_logs_dir(), "upload_safety.log")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines() if ln.strip()]
    except OSError:
        return []
    activities = []
    for line in reversed(lines[-120:]):
        if len(activities) >= max_items:
            break
        parts = line.split(" - ", 3)
        if len(parts) >= 4:
            ts_raw = parts[0].strip()
            ts = ts_raw.split(",")[0] if "," in ts_raw else ts_raw
            level = parts[2].strip().upper() if len(parts) > 2 else ""
            msg = parts[3].strip()
            if "ERROR" in level or "ERROR" in msg.upper():
                typ = "ERROR"
            elif "WARNING" in level:
                typ = "WARN"
            elif "SUCCESS" in msg.upper():
                typ = "SUCCESS"
            else:
                typ = "INFO"
            activities.append({"timestamp": ts, "type": typ, "description": msg[:500]})
        else:
            activities.append({"timestamp": "", "type": "LOG", "description": line[:500]})
    return activities


def _latest_consistency_check_stamp():
    log_dir = _dashboard_logs_dir()
    try:
        if not os.path.isdir(log_dir):
            return "Never"
        consistency_logs = [
            f
            for f in os.listdir(log_dir)
            if f.startswith("FileConsistencyCheck_") and f.endswith(".log")
        ]
    except OSError:
        return "Never"
    if not consistency_logs:
        return "Never"
    return max(consistency_logs).replace("FileConsistencyCheck_", "").replace(".log", "")


# Ensure upload and processed folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Upload safety monitoring (/safety/status, /safety/dashboard, etc.)
try:
    from safety_routes import register_safety_routes

    register_safety_routes(app)
    logging.info("Registered upload safety routes (/safety/*).")
except Exception as _safety_err:
    logging.warning("Could not register upload safety routes: %s", _safety_err)

# Temp Password
PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")

@app.route('/', methods=['GET', 'POST'])
def login():
    """
    Handles user login via a simple password form.
    If the submitted password matches the preset one, the user is logged in and redirected to the home page.
    Otherwise, it re-renders the login page with an error message.
    """
    if request.method == 'POST':
        if request.form['password'] == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error='Invalid password.')
    return render_template('login.html')

@app.route('/home')
def home():
    """
    Renders the main homepage only if the user is logged in.
    Otherwise, redirects the user to the login screen.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('home.html')

@app.route('/queue_pdfs', methods=['POST'])
def queue_pdfs():
    """
    Save PDFs to uploads/ only — returns quickly.

    For Google Apps Script and other automated callers that must not wait for
    OCR (6-minute Apps Script cap). Pair with ``process_uploads.py`` (cron or
    ``POST /run_process_uploads``) for OCR + DB.
    """
    auth_fail = require_auth_json()
    if auth_fail:
        return auth_fail

    uploaded_files = request.files.getlist('files[]')
    saved = []
    skipped = []
    for file in uploaded_files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            saved.append(filename)
        else:
            skipped.append(getattr(file, "filename", "<unknown>"))

    return jsonify(
        status='success',
        message=(
            f'Saved {len(saved)} file(s) to the server queue. '
            'OCR + database ingest runs via process_uploads.py (scheduled or manual).'
        ),
        saved=saved,
        skipped=skipped,
    )


@app.route('/upload_and_process', methods=['POST'])
def upload_and_process_files():
    """
    Admin / manual tool: upload PDFs and run OCR immediately (legacy).

    Saves each file to uploads/, then calls ``preprocess_pdf`` so corrected PDFs
    land in processed/. Use **Upload to Database** (or ``POST /upload_to_database``)
    as a second step for text extraction + MySQL insert.

    Automated Drive sync should use ``POST /queue_pdfs`` instead so callers are
    not held open during OCR.
    """
    auth_fail = require_auth_json()
    if auth_fail:
        return auth_fail

    uploaded_files = request.files.getlist('files[]')
    saved = []
    skipped = []
    for file in uploaded_files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            preprocess_pdf(file_path, app.config['OUTPUT_FOLDER'])
            saved.append(filename)
        else:
            skipped.append(getattr(file, "filename", "<unknown>"))

    return jsonify(
        status='success',
        message='Files uploaded and processed successfully',
        saved=saved,
        skipped=skipped,
    )


_SCRIPT_DIR = Path(__file__).resolve().parent
_PROCESS_UPLOADS_SCRIPT = _SCRIPT_DIR / "process_uploads.py"
_PROCESS_UPLOADS_LOG_DIR = _SCRIPT_DIR / "logs"
_PROCESS_UPLOADS_STATUS = _SCRIPT_DIR / "process_uploads.status.json"


@app.route('/run_process_uploads', methods=['POST'])
def run_process_uploads():
    """Start `process_uploads.py` in the background (same as daily cron).

    Auth: logged-in admin session or X-API-Key (Apps Script could call this
    if you add a second trigger later — not required for the Drive file-upload flow).
    """
    auth_fail = require_auth_json()
    if auth_fail:
        return auth_fail
    if not _PROCESS_UPLOADS_SCRIPT.exists():
        return jsonify({"error": "process_uploads.py not found"}), 500
    try:
        _PROCESS_UPLOADS_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _PROCESS_UPLOADS_LOG_DIR / "process_uploads.last.log"
        log_fh = open(log_path, "ab")
        log_fh.write(
            b"\n===== manual run_process_uploads "
            + datetime.datetime.now(datetime.timezone.utc).isoformat().encode()
            + b" =====\n"
        )
        log_fh.flush()
        subprocess.Popen(
            [_sys.executable, str(_PROCESS_UPLOADS_SCRIPT)],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            cwd=str(_SCRIPT_DIR),
            close_fds=True,
            start_new_session=True,
        )
        logging.info("Started process_uploads.py in background (log %s)", log_path)
        return jsonify({
            "status": "started",
            "message": "Processing started in the background. Poll GET /process_uploads_status.",
            "log_file": str(log_path),
        }), 202
    except Exception as exc:
        logging.error("run_process_uploads failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route('/process_uploads_status', methods=['GET'])
def process_uploads_status():
    """Latest JSON status from process_uploads.py (for home page polling)."""
    auth_fail = require_auth_json()
    if auth_fail:
        return auth_fail
    if not _PROCESS_UPLOADS_STATUS.exists():
        return jsonify({"state": "never_run"}), 200
    try:
        with open(_PROCESS_UPLOADS_STATUS, "r", encoding="utf-8") as f:
            return jsonify(json.load(f)), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "state": "unknown"}), 500


@app.route('/database_ai')
def database_ai():
    """
    Displays the AI-assisted database interface page if the user is logged in.
    Redirects to login otherwise.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('database_ai.html')

@app.route('/upload_to_database', methods=['POST'])
def upload_to_database_route():
    """
    Coordinates the full ETL (Extract, Transform, Load) pipeline:
    - Extracts text from processed PDFs
    - Generates metadata from text
    - Uploads both to the MySQL database
    Errors are caught and logged at each stage.
    """
    auth_fail = require_auth_json()
    if auth_fail:
        return auth_fail

    use_enhanced = os.getenv("USE_ENHANCED_UPLOAD_ROUTE", "true").strip().lower() in {"1", "true", "yes", "on"}
    # Keep existing API tests and legacy mock-based flows stable.
    if app.config.get("TESTING"):
        use_enhanced = False
    if use_enhanced and enhanced_upload_to_database_route is not None:
        try:
            archive_dir = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
            if archive_dir.startswith("/home/RSCAP") and not os.path.exists("/home/RSCAP"):
                archive_dir = os.path.join(os.getcwd(), "shared", "archive_directory")

            results = enhanced_upload_to_database_route(
                database_config=database_config,
                output_folder=app.config["OUTPUT_FOLDER"],
                extractions_folder=app.config["EXTRACTIONS"],
                metadata_file="./Jsontags/metadata.json",
                archive_dir=archive_dir,
            )
            if results.get("success"):
                return jsonify({"message": results.get("message", "Data successfully uploaded to the database.")})

            return jsonify({
                "error": results.get("message", "Upload failed."),
                "details": results.get("errors", []),
            }), 500
        except Exception as enhanced_error:
            logging.error(f"Enhanced upload route failed, falling back to legacy path: {enhanced_error}")

    try:
        logging.info("Starting database upload process...")

        # Extract text from PDFs
        extracttext.extract_text_from_pdfs(app.config['OUTPUT_FOLDER'], app.config['EXTRACTIONS'])
        logging.info("Text extraction completed.")

        # Extract metadata from text files
        logging.info(f"Text files found for tagging: {os.listdir('OCRextractions')}")
        tagextraction.extract_metadata_from_text_files("OCRextractions", "./Jsontags/metadata.json")
        logging.info("Metadata extraction completed.")

        # Connect to the MySQL database
        conn = mysql.connector.connect(**database_config)
        logging.info("Connected to database successfully.")

        # Upload to database
        dbconnector.upload_to_database(conn, "/home/RSCAP/shared/archive_directory", "OCRextractions", "./Jsontags/metadata.json")
        try:
            cur_lineage = conn.cursor()
            from dataset_lineage import touch_dataset_source
            touch_dataset_source(cur_lineage, conn, "letters_db", detail="legacy upload_to_database")
            cur_lineage.close()
        except Exception as lineage_err:
            logging.warning("dataset lineage (letters) skipped: %s", lineage_err)
        conn.close()

        logging.info("Database upload completed successfully.")
        clear_files()
        ME_json_size=os.path.getsize('./logs/Missedentries.json')
        if(ME_json_size>0):
            return jsonify({"message": "file(s) couldn't find a matching entry in the logs.  Please check Missedentries.json"})
        else:
            return jsonify({"message": "Data successfully uploaded to the database."})

    except mysql.connector.Error as db_error:
        logging.error(f"Database error: {db_error}")
        return jsonify({"error": f"Database error: {str(db_error)}"}), 500

    except FileNotFoundError as file_error:
        logging.error(f"File error: {file_error}")
        return jsonify({"error": f"File not found: {str(file_error)}"}), 500

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

def query_database(ai_generated_sql):
    """
    Executes a given SQL query and returns structured results.
    Handles errors and ensures proper cleanup of connections and cursors.
    """
    try:
        conn = mysql.connector.connect(**database_config)
        cursor = conn.cursor(dictionary=True)

        logging.info(f"Executing SQL Query: {ai_generated_sql}")
        cursor.execute(ai_generated_sql)
        results = cursor.fetchall()
        cursor.close()
        conn.close()

        if not results:
            return {"status": "error", "message": "No relevant data found in the database."}

        return {"status": "success", "data": results}

    except mysql.connector.Error as e:
        logging.error(f"Database query error: {e}")
        return {"status": "error", "message": "Database unavailable at this time. Please try again later."}

def make_serializable(obj):
    """
    Ensures all Python objects returned from SQL queries are JSON-serializable.
    Converts Decimal to float and datetime to ISO format strings.
    """
    if isinstance(obj, decimal.Decimal):
        return float(obj)  # Convert Decimal → float
    elif isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()  # Convert datetime → string
    return obj  # Return unchanged for other types


def _ai_completion_text(completion, step: str) -> str:
    """Extract non-empty text from an OpenAI chat completion."""
    if not completion or not getattr(completion, "choices", None):
        raise ValueError(f"{step}: empty response from OpenAI")
    content = completion.choices[0].message.content
    if content is None:
        raise ValueError(f"{step}: OpenAI returned no message content")
    text = content.strip()
    if not text:
        raise ValueError(f"{step}: OpenAI returned blank content")
    return text


def _parse_query_classification(raw: str) -> str:
    """
    Normalize classifier output. Models often wrap the label in quotes or add prose.
    """
    cleaned = (raw or "").strip().strip('"').strip("'")
    match = re.search(r"\b(SQL_QUERY|SITE_HELP|OFF_TOPIC|NATURAL_RESPONSE)\b", cleaned, re.IGNORECASE)
    if match:
        label = match.group(1).upper()
        if label == "NATURAL_RESPONSE":
            return "OFF_TOPIC"
        return label
    upper = cleaned.upper()
    if upper in {"SQL_QUERY", "SITE_HELP", "OFF_TOPIC"}:
        return upper
    if upper == "NATURAL_RESPONSE":
        return "OFF_TOPIC"
    raise ValueError(f"Unexpected classification response: {raw!r}")


_PUBLIC_SITE_BASE_URL = os.getenv("PUBLIC_SITE_BASE_URL", "https://rscap.pythonanywhere.com").rstrip("/")

_OUT_OF_SCOPE_MESSAGE = (
    "I can answer (1) questions about cases and letters in the database — try "
    "\"How many cases are in the database?\" — or (2) questions about this website, "
    "methods, and how metrics are calculated — try \"What does this website do?\" or "
    f"\"How are cost savings calculated?\" See [{_PUBLIC_SITE_BASE_URL}/how-to-use-tools]"
    f"({_PUBLIC_SITE_BASE_URL}/how-to-use-tools) and "
    f"[{_PUBLIC_SITE_BASE_URL}/methods]({_PUBLIC_SITE_BASE_URL}/methods)."
)


def _prefers_site_help_query(user_query: str) -> bool:
    """Questions about the public site, methods, definitions — not live DB counts."""
    q = (user_query or "").strip().lower()
    if not q:
        return False
    if _prefers_database_query(user_query):
        return False
    site_patterns = (
        r"\b(what does (this|the) (website|site)|what is (this|the) (website|site|project)|"
        r"how does (this|the) (website|site))\b",
        r"\b(tool hub|how to use|four tools|request access|magic link)\b",
        r"\b(methods|variables|what we measure|data sources?|github)\b",
        r"\b(cost saving|cost savings|calculated|calculation method|unallocated|marginal|per capita)\b",
        r"\b(success rate|case progression)\b.*\b(calculated|defined|mean|measured)\b",
        r"\b(how (are|is)|what (is|does)|explain|define)\b.*\b(success|cost|progression|measured|calculated)\b",
        r"\b(1172\.?1|penal code|cdcr-initiated)\b",
        r"\btell me about\b.*\b(law|laws|project|website|methods|resentenc)\b",
        r"\b(about (the )?project|who (built|made)|privacy|terms)\b",
    )
    return any(re.search(p, q) for p in site_patterns)


def _prefers_database_query(user_query: str) -> bool:
    """Heuristic: Tool Hub questions about letters/cases/counts should use SQL, not open chat."""
    q = (user_query or "").strip().lower()
    if not q:
        return False
    if re.search(
        r"\b(how (are|is)|what (is|does)|explain|define)\b.*\b(success|cost saving|calculated|measured)\b",
        q,
    ):
        return False
    count_terms = r"(how many|how much|count|number of|total|list|show|breakdown|compare|rate|percentage|average|sum)"
    db_terms = (
        r"(database|cases?|letters?|records?|pdfs?|metadata|county|counties|judge|cohort|"
        r"cdcr|outcomes?|outcome|action taken|years reduced|cost savings|sec decision)"
    )
    if re.search(count_terms, q) and re.search(db_terms, q):
        return True
    if re.search(r"\b(in (the|our) database|from (the|our) database|in metadata)\b", q):
        return True
    if re.search(r"\bcase (number|#)|cdcr|rif\d", q):
        return True
    return False


def _answer_site_help_query(user_query: str) -> str:
    """Answer from curated public website copy; cite source page links."""
    pages = select_site_help_pages(user_query)
    context = format_site_help_context(pages, _PUBLIC_SITE_BASE_URL)
    system_message = f"""
You help users understand the Resentencing Accountability Dashboard (RAD) public website.

Rules:
- Answer ONLY using the website excerpts below. Do not invent policies, numbers, or legal facts.
- If the excerpts do not fully answer the question, say what is missing and point to the closest page.
- Do NOT answer live database counts here (those require a database question).
- Keep answers concise (2–4 short paragraphs max).
- End with a **Sources:** section listing markdown links [Page Title](URL) for every excerpt you used.
  Use the exact URL lines from the excerpts.

Website excerpts:
{context}
"""
    chat_completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_query},
        ],
    )
    return _ai_completion_text(chat_completion, "site help")


def _sanitize_ai_sql(raw_sql: str) -> str:
    """Strip markdown fences and validate read-only SQL."""
    sql = re.sub(r"```(?:sql)?", "", raw_sql or "", flags=re.IGNORECASE).strip().strip("`")
    if not sql or sql.upper() == "INVALID":
        return "INVALID"
    first = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
    if first not in {"SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "WITH"}:
        logging.warning("Rejected non-read-only SQL from AI: %s", sql[:200])
        return "INVALID"
    return sql


def _openai_error_payload(exc: Exception):
    """Map OpenAI / network failures to a safe JSON error for the UI."""
    name = exc.__class__.__name__
    text = str(exc)
    lowered = text.lower()
    if name in {"AuthenticationError", "PermissionDeniedError"} or "invalid api key" in lowered:
        return {"error": "OpenAI API key is missing or invalid on the server. Ask the maintainer to check OPENAI_API_KEY and reload the web app."}, 502
    if name == "RateLimitError" or "rate limit" in lowered or "quota" in lowered or "insufficient" in lowered:
        return {"error": "OpenAI rate limit or billing quota was hit. If billing was just updated, reload the PythonAnywhere web app and try again in a minute."}, 503
    if name == "NotFoundError" or "model" in lowered and "not found" in lowered:
        return {"error": "The configured OpenAI model is unavailable. Ask the maintainer to update the model name."}, 502
    if "timeout" in lowered or name in {"APITimeoutError", "TimeoutError"}:
        return {"error": "OpenAI request timed out. Please try again."}, 504
    return {"error": "AI service error. Please try again in a moment."}, 502


@app.route('/query_ai', methods=['POST'])
def query_ai():
    """
    Main AI interface for user queries:
    - Classifies input as SQL-based or general
    - Generates SQL (if applicable) using OpenAI
    - Executes SQL query and interprets the result in natural language
    """

    # Auth Guard
    auth_fail = require_auth_json()
    if auth_fail:
        return auth_fail
    # /Auth Guard

    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    user_query = request.json.get('query')
    if not user_query:
        return jsonify({"error": "No query provided"}), 400

    try:
        # **Step 1: Classify Query Type**
        if _prefers_database_query(user_query):
            query_type = "SQL_QUERY"
            logging.info("Query routed to SQL via database heuristic")
        elif _prefers_site_help_query(user_query):
            query_type = "SITE_HELP"
            logging.info("Query routed to site help via heuristic")
        else:
            system_message_classification = """
            You classify Tool Hub questions for the RAD resentencing website.

            Reply with exactly one label: SQL_QUERY, SITE_HELP, or OFF_TOPIC.

            **SQL_QUERY** — answer requires live data from MySQL (`pdfs`, `metadata`):
            counts, lookups, aggregates, county/outcome breakdowns from the letter database.
            "Letters" means resentencing letter PDFs / case records, not spelling.

            **SITE_HELP** — answer is on the public website (no live DB count needed):
            what the site/tools do, methods, Penal Code 1172.1 scope, variables, how cost savings
            or success rates are defined/calculated, data sources, access/login, about the project.

            **OFF_TOPIC** — unrelated (homework, jokes, generic legal advice outside this project).

            **Examples:**
            - "How many cases are in the database?" → SQL_QUERY
            - "How many letters in our database?" → SQL_QUERY
            - "What does this website do?" → SITE_HELP
            - "How are cost savings calculated?" → SITE_HELP
            - "Tell me about resentencing laws" → SITE_HELP (project scope on /methods)
            - "Write my homework essay" → OFF_TOPIC

            **Now classify this user query:**
            """

            classification_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_message_classification},
                    {"role": "user", "content": user_query}
                ],
            )

            try:
                query_type = _parse_query_classification(_ai_completion_text(classification_response, "classification"))
            except ValueError as exc:
                logging.error("Classification parse failed: %s", exc)
                return jsonify({"error": "Failed to classify query. Try again later."}), 500

            logging.info(f"Query Classification: {query_type}")

        if query_type == "SITE_HELP":
            logging.info("Processing as website help (grounded in public pages).")
            return jsonify({"response": _answer_site_help_query(user_query)})

        if query_type == "OFF_TOPIC":
            logging.info("Out-of-scope query; returning guidance.")
            return jsonify({"response": _OUT_OF_SCOPE_MESSAGE})

        # **If AI Cannot Determine a Query Type, Alert the User**
        if query_type == "INVALID":
            logging.warning("AI could not classify the query.")
            return jsonify({"error": "I couldn't process your query. Please rephrase and try again."}), 400  # **EARLY RETURN**

        # **Only Proceed if Classified as "SQL_QUERY"**
        if query_type == "SQL_QUERY":
            logging.info("Recognized as a database-related query.")

            system_message_generate_sql = """
            You are an SQL assistant. Your task is to generate **ONLY valid, safe SQL queries**.

            **Vocabulary:** In this project, "letters", "letter PDFs", "cases", and "records" usually mean rows in
            `pdfs` (one PDF per letter) and/or joined `metadata`. Count letters with `COUNT(*)` or `COUNT(DISTINCT ...)`
            on `pdfs` unless the question needs metadata fields.

            **RULES:**
            - **You must ONLY use these tables and columns:**
              - `pdfs` (columns: `id`, `filename`, `file_path`)
              - `metadata` (columns: `id`, `pdf_id`, `date_stamped`, `judge`, `county`, `address`, `convict_name`, `cdcr_number`, `case_number`, `sentence_date`, `cohort`, `pid_no`, `institution`, `old_release_date`, `documents_printed_date`, `letter_creation_date`, `secretary_send_date`, `sec_decision`, `court_mail_date`, `court_response_date`, `resentencing_hearing_date`, `action_taken`, `days_reduced`, `years_reduced`, `cost_savings`, `notes`, `completion_date`, `post_release`, `isl_dsl`, `parole_eligibility_date`, "race", "ethnicity")
            - **You may only generate `SELECT`, `SHOW`, `DESCRIBE`, or `EXPLAIN` queries.**
            - **Do NOT generate `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, or `CREATE` statements.**
            - **If the query is not possible using the given schema, return "INVALID"**.
            - **Use `LIMIT 20` for listing results.**
            - **Do not use the word "Convict" in your response, use the word "Incarcerated person(s)" to describe such people.**
            - **Use `COUNT(DISTINCT column_name)` for unique counts.**

            **Now generate an SQL query based on this user request:**
            """

            sql_generation_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_message_generate_sql},
                    {"role": "user", "content": user_query}
                ],
            )

            if not sql_generation_response.choices:
                logging.error(" AI failed to generate an SQL query.")
                return jsonify({"error": "Failed to generate SQL query. Try again later."}), 500

            ai_generated_sql = _sanitize_ai_sql(_ai_completion_text(sql_generation_response, "sql generation"))
            logging.debug(f" AI-Generated SQL Query (Raw): {ai_generated_sql}")

            if ai_generated_sql == "INVALID":
                logging.warning("AI could not generate a valid SQL query.")

                # **New Response: AI Doesn't Know How to Define Query**
                system_message_unknown_query = f"""
                You are an AI assistant responding to a user who asked a question that you couldn't translate into a database query.

                The question was: "{user_query}"

                You should explain to the user that you do not have a definition for the requested term. Do **NOT** apologize unnecessarily. If the term is ambiguous (like "success rate"), guide the user to rephrase.

                **Example Responses:**
                - User: "What is the success rate of Orange County?"
                  AI: "I don't have a clear definition for success rate in this context. Could you clarify what aspect of success you're referring to?"
                - User: "How effective is resentencing?"
                  AI: "I'm not sure how to measure effectiveness in this case. Could you specify a metric, like reduced prison time or cost savings?"

                **Now generate a response based on the user's original query:**
                """

                unknown_query_response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_message_unknown_query}
                    ],
                )

                if not unknown_query_response.choices:
                    logging.error("AI failed to generate a response for an unknown query.")
                    return jsonify({"error": "I'm not sure how to define that query. Could you clarify?"}), 200  # **SAFE RESPONSE**

                final_unknown_response = _ai_completion_text(unknown_query_response, "unknown query")
                logging.debug(f"AI Unknown Query Response: {final_unknown_response}")

                return jsonify({"response": final_unknown_response})  # **EARLY RETURN**


            # **Step 3: Execute AI-Generated SQL**
            database_response = query_database(ai_generated_sql)

            if database_response["status"] == "error":
                return jsonify({"error": database_response["message"]}), 503

            # **Ensure database response has data**
            if "data" not in database_response or not database_response["data"]:
                return jsonify({"response": "No relevant data found in the database."})  # **EARLY RETURN**

            # Convert the list of dictionaries into a string to prevent frontend errors
            formatted_response = json.dumps(database_response["data"], default=str)

            # **Step 4: AI-Interpret Database Results into Natural Language**
            system_message_interpret_results = """
            You are an AI assistant that translates structured database results into natural language.
            Your goal is to take raw SQL output and respond with a **clear, concise, and human-readable answer**.

            **Examples:**
            - Input: `[{"total_cases": 147}]`
              Output: `"The database contains 147 cases."`
            - Input: `[{"judge": "Alan M. Simpson"}]`
              Output: `"The judge presiding over the case was Alan M. Simpson."`
            - Input: `[{"unique_counties": 22}]`
              Output: `"There are 22 unique counties represented in the database."`
            - Input: `[{"cost_savings": 500000}]`
              Output: `"The total cost savings recorded is $500,000."`

            **Do not use the word "Convict" in your response, use the word "Incarcerated person(s)" to describe such people.**

            **Now, convert this SQL result into a user-friendly response:**
            """

            ai_interpretation_prompt = f"{system_message_interpret_results}\nResults: {json.dumps(database_response['data'], default=str)}"

            interpretation_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": ai_interpretation_prompt}
                ],
            )

            if not interpretation_response.choices:
                logging.error("AI interpretation failed.")
                return jsonify({"error": "Failed to interpret database results. Try again later."}), 500

            final_response = _ai_completion_text(interpretation_response, "interpretation")
            logging.debug(f"AI Final Interpretation: {final_response}")

            return jsonify({"response": final_response})  # **EARLY RETURN**

    except Exception as e:
        logging.exception("query_ai failed")
        module = getattr(e.__class__, "__module__", "") or ""
        name = e.__class__.__name__
        if module.startswith("openai") or name in {
            "AuthenticationError",
            "RateLimitError",
            "APIConnectionError",
            "APITimeoutError",
            "PermissionDeniedError",
            "NotFoundError",
        }:
            payload, status = _openai_error_payload(e)
            return jsonify(payload), status
        return jsonify({"error": "An unexpected error occurred. Please try again later."}), 500


@app.route('/upload_excel', methods=['POST'])
def upload_excel_files():
    """
    Accepts uploaded Excel files and saves them to a server-side directory.
    Ensures the folder exists and returns a success/failure response.
    """
    auth_fail = require_auth_json()
    if auth_fail:
        return auth_fail

    # Create the folder if it doesn't exist
    excel_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Excel')
    os.makedirs(excel_folder, exist_ok=True)

    # 'excel_files[]' is the field name from the JS
    if 'excel_files[]' not in request.files:
        return jsonify(status='error', message='No Excel files uploaded'), 400

    uploaded_excel_files = request.files.getlist('excel_files[]')
    if not uploaded_excel_files:
        return jsonify(status='error', message='No Excel files selected'), 400

    saved_files = []
    for file in uploaded_excel_files:
        filename = secure_filename(file.filename)
        # Save each file to the Excel folder
        if filename:  # Make sure it's not empty
            save_path = os.path.join(excel_folder, filename)
            file.save(save_path)
            saved_files.append(filename)

            lower_name = filename.lower()
            # Keep one active race data file (newest upload wins).
            if "race" in lower_name:
                for existing in os.listdir(excel_folder):
                    if existing == filename:
                        continue
                    if "race" in existing.lower():
                        try:
                            os.remove(os.path.join(excel_folder, existing))
                        except Exception as e:
                            logging.warning(f"Could not remove old race file {existing}: {e}")
            # Keep one active main log file (newest upload wins).
            elif filename.lower().endswith((".xlsx", ".xls", ".csv")):
                for existing in os.listdir(excel_folder):
                    if existing == filename:
                        continue
                    existing_lower = existing.lower()
                    if "race" in existing_lower:
                        continue
                    if existing_lower.endswith((".xlsx", ".xls", ".csv")):
                        try:
                            os.remove(os.path.join(excel_folder, existing))
                        except Exception as e:
                            logging.warning(f"Could not remove old log file {existing}: {e}")

    if saved_files:
        try:
            conn_lineage = mysql.connector.connect(**database_config)
            cur_lineage = conn_lineage.cursor()
            from dataset_lineage import touch_dataset_source
            for fn in saved_files:
                lk = fn.lower()
                src_key = "race_data" if "race" in lk else "main_log"
                touch_dataset_source(cur_lineage, conn_lineage, src_key, detail=fn)
            cur_lineage.close()
            conn_lineage.close()
        except Exception as lineage_err:
            logging.warning("dataset lineage (excel upload) skipped: %s", lineage_err)
        return jsonify(status='success', message=f"Uploaded {len(saved_files)} Excel files.")
    else:
        return jsonify(status='error', message="No valid files were saved.")

@app.route('/download_files')
def download_all_files():
    """
    Compresses all processed PDF files into a ZIP archive and returns it for download.
    Skips already zipped files and handles empty folder scenarios.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    output_folder = app.config['OUTPUT_FOLDER']
    zip_path = os.path.join(output_folder, 'Corrected_Files.zip')

    # Check if there are files to zip
    files_to_zip = [f for f in os.listdir(output_folder) if f != 'Corrected_Files.zip' and os.path.isfile(os.path.join(output_folder, f))]
    if not files_to_zip:
        return jsonify(status='error', message='No files to download'), 404

    # Remove existing zip file if it exists
    if os.path.exists(zip_path):
        os.remove(zip_path)

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file in files_to_zip:
                zf.write(os.path.join(output_folder, file), file)

        return send_from_directory(output_folder, 'Corrected_Files.zip', as_attachment=True)
    except FileNotFoundError:
        abort(404, description="File not found")
    except Exception as e:
        app.logger.error('Failed to create or send zip file: %s', e)
        abort(500, description="Internal Server Error")


@app.route('/clear_files', methods=['POST'])
def clear_files():
    """
    Deletes all uploaded PDFs, processed files, and extracted OCR data from the server.
    Recreates required directories afterward to prevent errors on future uploads.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401

    try:
        # Clear uploaded and processed files
        shutil.rmtree(app.config['UPLOAD_FOLDER'], ignore_errors=True)
        shutil.rmtree(app.config['OUTPUT_FOLDER'], ignore_errors=True)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
        shutil.rmtree(app.config['EXTRACTIONS'], ignore_errors=True)
        os.makedirs(app.config['EXTRACTIONS'], exist_ok=True)

        return jsonify({"status": "success", "message": "All files have been cleared."})
    except Exception as e:
        logging.error(f"Error clearing files: {e}")
        return jsonify({"status": "error", "message": f"Error clearing files: {str(e)}"}), 500

@app.route('/clear_excel', methods=['POST'])
def clear_excel():
    """
    Clears all uploaded Excel files by deleting and recreating the Excel folder.
    Used for cleanup before a new batch upload.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401

    try:
        excel_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Excel')

        # Remove entire Excel folder and recreate it
        shutil.rmtree(excel_folder, ignore_errors=True)
        os.makedirs(excel_folder, exist_ok=True)

        return jsonify({"status": "success", "message": "Excel files have been cleared."})
    except Exception as e:
        app.logger.error(f"Error clearing Excel files: {e}")
        return jsonify({"status": "error", "message": f"Error clearing Excel files: {str(e)}"}), 500

def allowed_file(filename):
    """
    Validates uploaded file types.
    Only accepts files with a `.pdf` extension.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf'}

def correct_orientation(image_path):
    """
    Uses Tesseract to detect and correct rotation in scanned page images.
    Helps ensure readable OCR results regardless of scan direction.
    """
    try:
        image = Image.open(image_path)
        image = image.convert('RGB')
        osd = pytesseract.image_to_osd(image)
        rotation = int(osd.split("\nRotate: ")[1].split("\n")[0])
        return rotation
    except pytesseract.TesseractError as e:
        logging.error(f"Tesseract failed to process {image_path}: {e}")
        return None  # Return None to indicate an error occurred


def _archive_dir_base():
    """ARCHIVE_DIR with same local-dev fallback as preprocess_pdf / download routes."""
    archive_dir = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
    if not archive_dir.startswith("/home/RSCAP") or os.path.exists("/home/RSCAP"):
        return archive_dir
    return os.path.join(os.getcwd(), "shared", "archive_directory")


def _first_existing_archive_corrected(archive_dir: str, upload_basename: str):
    """
    Return (full_archive_path, log_label) for reuse, or (None, None).

    Tries ``corrected_`` + each basename variant (exact name, then Drive-duplicate
    stripped forms).
    """
    for variant in upload_basename_variants(upload_basename):
        arc_name = f"corrected_{variant}"
        path = os.path.join(archive_dir, arc_name)
        if os.path.isfile(path):
            if variant == upload_basename:
                return path, arc_name
            return path, f"{arc_name} (reusing canonical for duplicate-style name {upload_basename!r})"
    return None, None


def preprocess_pdf(file_path, output_folder):
    """
    Converts each PDF page to an image, corrects orientation, reassembles into a new PDF,
    and applies OCR to make the final output searchable.
    Temporary images are cleaned up after processing.

    If ``corrected_<original_basename>`` (or a **canonical** name after stripping
    Drive duplicate prefixes like ``Copy_of_``) already exists in the archive,
    copy it into ``output_folder`` as ``corrected_<original_basename>`` and skip
    OCR so ``process_uploads`` can still run extract → DB.
    """
    basename = os.path.basename(file_path)
    corrected_name = f"corrected_{basename}"
    archive_dir = _archive_dir_base()
    os.makedirs(archive_dir, exist_ok=True)
    processed_dest = os.path.join(output_folder, corrected_name)

    archive_hit, archive_label = _first_existing_archive_corrected(archive_dir, basename)
    if archive_hit:
        os.makedirs(output_folder, exist_ok=True)
        try:
            shutil.copy2(archive_hit, processed_dest)
            logging.info(
                "Skipping OCR for %s; archive match %s — copied to processed/",
                basename,
                archive_label,
            )
            return
        except OSError as e:
            logging.warning(
                "Archive file exists for %s but copy to processed failed (%s); running full OCR.",
                basename,
                e,
            )

    temp_dir = os.path.join(output_folder, "temp_images")
    os.makedirs(temp_dir, exist_ok=True)
    corrected_images = []

    try:
        pdf_document = fitz.open(file_path)
        for page_num in range(len(pdf_document)):
            try:
                page = pdf_document.load_page(page_num)
                pix = page.get_pixmap(dpi=300)
                image_path = os.path.join(temp_dir, f"page_{page_num+1}.jpg")
                pix.save(image_path)

                # Attempt to get the rotation angle
                rotation = correct_orientation(image_path)
                if rotation is not None and rotation != 0:
                    image = Image.open(image_path)
                    rotated_image = image.rotate(-rotation, expand=True)
                    rotated_image.save(image_path)

                corrected_images.append(image_path)
            except Exception as e:
                logging.error(f"Error processing page {page_num + 1} of {file_path}: {e}")
                continue  # Skip this page and continue to the next one

        if not corrected_images:
            logging.error(f"No valid pages processed for {file_path}. Skipping OCR.")
            return  # Skip OCR processing if no valid pages are found

        corrected_pdf_path = os.path.join(output_folder, f"corrected_{os.path.basename(file_path)}")
        images = [Image.open(img).convert('RGB') for img in corrected_images]

        # Save the corrected images as a single PDF
        images[0].save(corrected_pdf_path, save_all=True, append_images=images[1:])

        # Run OCR on the corrected PDF
        try:
            ocrmypdf.ocr(corrected_pdf_path, corrected_pdf_path, deskew=True, output_type='pdfa')
        except ocrmypdf.exceptions.PriorOcrFoundError:
            logging.warning(f"The file {corrected_pdf_path} already contains OCR text. Skipping OCR process.")
        except Exception as e:
            logging.error(f"Error during OCR processing of {corrected_pdf_path}: {e}")

        # === Archive the final corrected PDF if it doesn't already exist ===
        archive_dir = _archive_dir_base()
        os.makedirs(archive_dir, exist_ok=True)

        archive_path = os.path.join(archive_dir, os.path.basename(corrected_pdf_path))

        if not os.path.exists(corrected_pdf_path):
            logging.error(f"Corrected PDF does not exist: {corrected_pdf_path}")
        elif not os.path.exists(archive_path):
            try:
                shutil.copy2(corrected_pdf_path, archive_path)
                logging.info(f"Archived file to: {archive_path}")
            except Exception as e:
                logging.error(f"Failed to archive {corrected_pdf_path} → {archive_path}: {e}")
        else:
            logging.info(f"File already exists in archive, skipping: {archive_path}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# Backend File Viewer Download Files
@app.route('/download/<filename>')
def download_file(filename):
    # Use environment variable for archive directory, with fallback for local development
    archive_dir = os.getenv('ARCHIVE_DIR', '/home/RSCAP/shared/archive_directory')

    # For local development, use the shared directory in the project
    if not os.path.exists(archive_dir):
        archive_dir = os.path.join(os.getcwd(), 'shared', 'archive_directory')

    if not os.path.exists(os.path.join(archive_dir, filename)):
        return "File not found", 404

    return send_from_directory(archive_dir, filename, as_attachment=True)

# Backend File Viewer
@app.route('/fileviewer')
def file_viewer():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    sort_field = request.args.get('sort', 'uploaded_newest')
    direction = request.args.get('direction', 'desc').lower()
    search_term = request.args.get('search', '').strip()
    allowed_fields = {
        'filename': 'pdfs.filename',
        'case_number': 'm_view.case_number',
        'cdcr_number': 'm_view.cdcr_number',
        'date_stamped': 'm_view.date_stamped',
        'uploaded_newest': 'pdfs.id',
        'uploaded_oldest': 'pdfs.id',
    }
    sort_column = allowed_fields.get(sort_field, 'pdfs.filename')
    if sort_field == 'uploaded_oldest':
        sort_direction = 'ASC'
    elif sort_field == 'uploaded_newest':
        sort_direction = 'DESC'
    else:
        sort_direction = 'ASC' if direction == 'asc' else 'DESC'

    where_clause = ""
    params = []
    if search_term:
        where_clause = ("WHERE pdfs.filename LIKE %s "
                        "OR m_view.case_number LIKE %s "
                        "OR m_view.cdcr_number LIKE %s "
                        "OR m_view.date_stamped LIKE %s")
        like_term = f"%{search_term}%"
        params = [like_term, like_term, like_term, like_term]

    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306))
    )
    try:
        with connection.cursor() as cursor:
            query = f"""
                SELECT
                    pdfs.filename,
                    pdfs.file_path,
                    m_view.case_number,
                    m_view.cdcr_number,
                    m_view.date_stamped
                FROM pdfs
                LEFT JOIN metadata AS m_view
                    ON m_view.id = (
                        SELECT m2.id
                        FROM metadata AS m2
                        WHERE m2.pdf_id = pdfs.id
                        ORDER BY
                            (CASE WHEN m2.case_number IS NOT NULL AND m2.case_number <> '' THEN 1 ELSE 0 END) DESC,
                            (CASE WHEN m2.cdcr_number IS NOT NULL AND m2.cdcr_number <> '' THEN 1 ELSE 0 END) DESC,
                            (CASE WHEN m2.date_stamped IS NOT NULL AND m2.date_stamped <> '' THEN 1 ELSE 0 END) DESC,
                            m2.id DESC
                        LIMIT 1
                    )
                {where_clause}
                ORDER BY {sort_column} {sort_direction}
            """
            cursor.execute(query, params)
            results = cursor.fetchall()
    finally:
        connection.close()

    files = [
        {
            "filename": row[0],
            "file_path": row[1],
            "case_number": row[2],
            "cdcr_number": row[3],
            "date_stamped": row[4]
        }
        for row in results
    ]
    search_info = (
        "Users can search by filename, case number, CDCR number, or date stamped. "
        "Use Uploaded (Newest) to see recently added files first."
    )
    return render_template("fileviewer.html", files=files, sort_field=sort_field, direction=sort_direction.lower(), search_term=search_term, search_info=search_info)

@app.route('/dashboard')
def dashboard():
    """Dashboard with database statistics and system status."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    last_check = _latest_consistency_check_stamp()
    recent_activity = _load_dashboard_recent_activity()
    archive_dir = _archive_dir_resolved()
    archive_ok = os.path.isdir(archive_dir)

    stats = {
        'total_files': 0,
        'with_metadata': 0,
        'missing_total': 0,
        'missing_no_row': 0,
        'needs_refresh': 0,
        'last_check': last_check,
    }
    status = {
        'database': 'Disconnected',
        'archive': 'Accessible' if archive_ok else 'Not found',
        'sync': 'Unknown',
    }
    dashboard_error = None

    connection = None
    try:
        connection = pymysql.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME'),
            port=int(os.getenv('DB_PORT', 3306))
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM pdfs")
            stats['total_files'] = cursor.fetchone()[0]

            # Distinct PDFs with at least one metadata row (avoid inflating on multi-row metadata)
            cursor.execute(
                "SELECT COUNT(DISTINCT p.id) FROM pdfs p "
                "INNER JOIN metadata m ON p.id = m.pdf_id"
            )
            stats['with_metadata'] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM pdfs p "
                "LEFT JOIN metadata m ON p.id = m.pdf_id WHERE m.pdf_id IS NULL"
            )
            stats['missing_no_row'] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(DISTINCT p.id) FROM pdfs p JOIN metadata m ON p.id = m.pdf_id "
                "WHERE (m.notes LIKE %s AND (m.case_number IS NULL OR TRIM(m.case_number) = '')) "
                "OR m.notes LIKE %s",
                ("%Auto-recovered%", "%Partial hints from filename%"),
            )
            stats['needs_refresh'] = cursor.fetchone()[0]

            stats['missing_total'] = stats['missing_no_row'] + stats['needs_refresh']

        status['database'] = 'Connected'
        issues = stats['missing_no_row'] + stats['needs_refresh']
        status['sync'] = 'Synchronized' if issues == 0 else 'Issues found'
    except Exception as e:
        logging.exception("Dashboard database error")
        dashboard_error = str(e)[:240]
        status['database'] = 'Error'
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_activity=recent_activity,
        status=status,
        dashboard_error=dashboard_error,
    )

@app.route('/missing_metadata')
def missing_metadata():
    """Show PDFs with no metadata row, auto-recovered placeholders, and partial filename-only rows."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306))
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.filename, p.file_path, p.id
                FROM pdfs p
                LEFT JOIN metadata m ON p.id = m.pdf_id
                WHERE m.pdf_id IS NULL
                ORDER BY p.filename
            """)
            orphan_rows = cursor.fetchall()

            cursor.execute("""
                SELECT p.filename, p.file_path, m.notes
                FROM pdfs p
                JOIN metadata m ON p.id = m.pdf_id
                WHERE m.notes LIKE %s
                AND (m.case_number IS NULL OR m.case_number = '')
                ORDER BY p.filename
            """, ("%Auto-recovered%",))
            incomplete_rows = cursor.fetchall()

            cursor.execute("""
                SELECT p.filename, p.file_path, m.cdcr_number, m.case_number,
                       m.convict_name, m.judge, m.notes
                FROM pdfs p
                JOIN metadata m ON p.id = m.pdf_id
                WHERE m.notes LIKE %s
                ORDER BY p.filename
            """, ("%Partial hints from filename%",))
            partial_rows = cursor.fetchall()
    finally:
        connection.close()

    orphan_files = [
        {"filename": row[0], "file_path": row[1], "id": row[2]}
        for row in orphan_rows
    ]
    incomplete_files = [
        {"filename": row[0], "file_path": row[1], "notes": row[2]}
        for row in incomplete_rows
    ]
    partial_files = [
        {
            "filename": row[0],
            "file_path": row[1],
            "cdcr_number": row[2],
            "case_number": row[3],
            "convict_name": row[4],
            "judge": row[5],
            "notes": row[6],
        }
        for row in partial_rows
    ]

    return render_template(
        "missing_metadata.html",
        orphan_files=orphan_files,
        incomplete_files=incomplete_files,
        partial_files=partial_files,
    )

@app.route('/recent_uploads')
def recent_uploads():
    """Show recently uploaded files."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306))
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.filename, p.file_path, m.case_number, m.cdcr_number, m.date_stamped
                FROM pdfs p
                LEFT JOIN metadata m ON p.id = m.pdf_id
                ORDER BY p.id DESC
                LIMIT 20
            """)
            results = cursor.fetchall()
    finally:
        connection.close()

    files = [
        {
            "filename": row[0],
            "file_path": row[1],
            "case_number": row[2],
            "cdcr_number": row[3],
            "date_stamped": row[4]
        }
        for row in results
    ]

    return render_template("recent_uploads.html", files=files)

@app.route('/consistency_report')
def consistency_report():
    """Show the latest consistency report."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    log_dir = _dashboard_logs_dir()
    report_content = "No consistency reports found."

    if os.path.exists(log_dir):
        consistency_logs = []
        for file in os.listdir(log_dir):
            if file.startswith('FileConsistencyCheck_') and file.endswith('.log'):
                consistency_logs.append(file)

        if consistency_logs:
            latest_report = max(consistency_logs)
            report_path = os.path.join(log_dir, latest_report)
            try:
                with open(report_path, 'r') as f:
                    report_content = f.read()
            except Exception as e:
                report_content = f"Error reading report: {e}"

    return render_template("consistency_report.html", report_content=report_content)

@app.route('/run_consistency_check', methods=['POST'])
def run_consistency_check():
    """Run a consistency check and generate a report."""
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401

    try:
        result = subprocess.run(
            [_pipeline_python(), "fileconsistencycheck.py"],
            capture_output=True,
            text=True,
            cwd=_mysite_dir(),
            env=_pipeline_subprocess_env(),
            timeout=3600,
        )

        if result.returncode == 0:
            return jsonify({"success": True, "message": "Consistency check completed successfully!"})
        err = (result.stderr or "").strip() or (result.stdout or "").strip() or "Unknown error"
        return jsonify({"success": False, "message": err[:2000]})
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "message": "Consistency check timed out."}), 504
    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route('/dashboard_stats')
def dashboard_stats():
    """Get dashboard statistics for the admin dashboard."""
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401

    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 3306)),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM pdfs")
            total_files = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(DISTINCT p.id) FROM pdfs p "
                "INNER JOIN metadata m ON p.id = m.pdf_id"
            )
            with_metadata = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*)
                FROM pdfs p
                LEFT JOIN metadata m ON p.id = m.pdf_id
                WHERE m.pdf_id IS NULL
            """)
            missing_metadata_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(DISTINCT p.id)
                FROM pdfs p
                JOIN metadata m ON p.id = m.pdf_id
                WHERE (m.notes LIKE '%Auto-recovered%'
                       AND (m.case_number IS NULL OR m.case_number = ''))
                   OR m.notes LIKE '%Partial hints from filename%'
            """)
            needs_refresh_count = cursor.fetchone()[0]

            last_check = _latest_consistency_check_stamp()

            return jsonify({
                "total_files": total_files,
                "with_metadata": with_metadata,
                "missing_metadata_count": missing_metadata_count,
                "needs_refresh_count": needs_refresh_count,
                "missing_total": missing_metadata_count + needs_refresh_count,
                "last_consistency_check": last_check,
            })
    finally:
        connection.close()

@app.route('/refresh_metadata', methods=['GET', 'POST'])
def refresh_metadata():
    """OCR + tag for placeholder metadata, partial filename-hint rows, and orphan PDFs."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Run the metadata refresh script
        try:
            refresh_timeout = int(os.getenv("METADATA_REFRESH_TIMEOUT_SEC", "14400"))
            result = subprocess.run(
                [_pipeline_python(), "metadata_refresh.py"],
                capture_output=True,
                text=True,
                cwd=_mysite_dir(),
                env=_pipeline_subprocess_env(),
                timeout=refresh_timeout,
            )

            if result.returncode == 0:
                return jsonify({"success": True, "message": "Metadata refresh completed successfully!"})
            err = (result.stderr or "").strip() or (result.stdout or "").strip() or "Unknown error"
            return jsonify({"success": False, "message": err[:2000]})
        except subprocess.TimeoutExpired:
            return jsonify(
                {
                    "success": False,
                    "message": "Metadata refresh timed out. For hundreds of PDFs, run "
                    "`python metadata_refresh.py` from a scheduled task or console "
                    f"(HTTP limit {int(os.getenv('METADATA_REFRESH_TIMEOUT_SEC', '14400'))}s).",
                }
            ), 504
        except Exception as e:
            return jsonify({"success": False, "message": f"Error: {str(e)}"})

    # GET request - show the refresh page
    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 3306)),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT filename, file_path, status_note FROM (
                    SELECT p.filename, p.file_path, m.notes AS status_note
                    FROM pdfs p
                    INNER JOIN metadata m ON p.id = m.pdf_id
                    WHERE m.notes LIKE %s
                      AND (m.case_number IS NULL OR TRIM(m.case_number) = '')
                    UNION ALL
                    SELECT p.filename, p.file_path, m.notes AS status_note
                    FROM pdfs p
                    INNER JOIN metadata m ON p.id = m.pdf_id
                    WHERE m.notes LIKE %s
                    UNION ALL
                    SELECT p.filename, p.file_path,
                           'No metadata row yet (orphan)' AS status_note
                    FROM pdfs p
                    LEFT JOIN metadata m ON p.id = m.pdf_id
                    WHERE m.pdf_id IS NULL
                ) AS cohort
                ORDER BY filename
                """,
                ("%Auto-recovered%", "%Partial hints from filename%"),
            )
            results = cursor.fetchall()
    finally:
        connection.close()

    files = [
        {
            "filename": row[0],
            "file_path": row[1],
            "notes": row[2],
        }
        for row in results
    ]

    return render_template("refresh_metadata.html", files=files)


@app.route('/missing_letters_pra')
def missing_letters_pra():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template(
        "missing_letters_pra.html",
        reconcile=_log_reconcile_summary(),
    )


@app.route('/api/log_reconcile')
def api_log_reconcile():
    if not session.get('logged_in'):
        return jsonify({"error": "Login required"}), 403
    from log_reconcile import load_log_reconcile

    try:
        refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")
        return jsonify(load_log_reconcile(force=refresh)), 200
    except Exception as exc:
        logging.error("log_reconcile error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route('/missing_letters_pra/download.xlsx')
def missing_letters_pra_download():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    from log_reconcile import export_reconcile_xlsx

    try:
        data, fname = export_reconcile_xlsx(missing_only=True)
    except Exception as exc:
        logging.error("missing_letters_pra export error: %s", exc)
        return jsonify({"error": str(exc)}), 500
    return send_file(
        io.BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=fname,
    )


if __name__ == '__main__':
    app.run(debug=True)