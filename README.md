# Resentencing Project

A small open-source Flask stack that powers a research database of California Penal Code §1170(d)(1) resentencing recall letters, plus a public dashboard and a gated Tool Hub.

The project is developed by student developers under faculty supervision as part of a university research initiative. Letters are stored as OCR'd PDFs, their case-level metadata is extracted and reconciled against tracking spreadsheets, and the resulting database powers both public aggregate charts and authenticated case-level lookups.

The system recognises four roles:

- **Developer** — student dev (or future maintainer) with full repo + server access.
- **Faculty supervisor** — the research lead; can do everything an admin/developer can do on the deployed system.
- **Public user** — anyone visiting the public site. No login. Sees aggregate charts only.
- **Tool Hub approved user** — a visitor who has been approved via the magic-link access flow. Can use the gated lookup / browse / variable / AI / reconciliation tools.

This README is the single source of technical truth on GitHub. The full team handoff package — a transition memo, a deep system maintainer guide, and a non-technical frontend user guide — lives in the project's Google Drive and is shared with new contributors by the faculty supervisor.

---

## Table of contents

1. [What this repo contains](#1-what-this-repo-contains)
2. [System architecture](#2-system-architecture)
3. [Quick start — local development](#3-quick-start--local-development)
4. [Production deployment — PythonAnywhere](#4-production-deployment--pythonanywhere)
5. [Letter upload pipeline](#5-letter-upload-pipeline)
6. [Metadata refresh (bulk repair)](#6-metadata-refresh-bulk-repair)
7. [Bulk OCR escape hatch](#7-bulk-ocr-escape-hatch)
8. [Public site & gated Tool Hub](#8-public-site--gated-tool-hub)
9. [Database schema](#9-database-schema)
10. [Migrations](#10-migrations)
11. [Scheduled tasks](#11-scheduled-tasks)
12. [Common operations — top commands](#12-common-operations--top-commands)
13. [Troubleshooting](#13-troubleshooting)
14. [Security & secrets](#14-security--secrets)
15. [Further documentation](#15-further-documentation)
16. [License & acknowledgments](#16-license--acknowledgments)

---

## 1. What this repo contains

```
ResentencingProject/
├── mysite/                # Backend (developer / faculty supervisor): OCR webapp, dashboard, ingest API
│   ├── OCRWebApp.py       # Main Flask app (default port 5000)
│   ├── process_uploads.py # Drains the upload queue → archive + DB
│   ├── metadata_refresh.py# Repairs partial / placeholder rows from OCR + Excel
│   ├── dbconnector.py     # MySQL access layer
│   ├── add_*_column.py    # One-time schema migrations
│   ├── Excel/             # Tracking workbooks read by metadata refresh
│   ├── logs/              # Pipeline logs
│   └── templates/         # Backend UI (developer / faculty supervisor)
├── frontend/              # Public site + gated Tool Hub (default port 5001)
│   ├── flask_app.py       # Public + authenticated routes
│   ├── audit.log          # Per-session search/download audit (sensitive)
│   └── templates/         # Public UI + Tool Hub
├── shared/
│   └── archive_directory/ # Source of truth for processed letter PDFs
├── uploads/               # Transient: PDFs awaiting OCR + ingest
├── processed/             # Transient: post-OCR PDFs awaiting metadata extraction
├── OCRextractions/        # Transient: OCR'd text awaiting tag extraction
├── DATABASE_SCHEMA.sql    # Canonical MySQL schema
├── env.template           # Reference for required environment variables
├── requirements.txt       # Pinned Python dependencies
└── README.md              # This file
```

Working notes, design docs, and the team's Google-Drive-facing handoff documents are kept in a local `Documentation/` directory that is intentionally not published to GitHub.

---

## 2. System architecture

```
                    ┌─────────────────────────────┐
                    │   Google Drive (letters)    │
                    └──────────────┬──────────────┘
                                   │ Apps Script `checkForNewFiles()`
                                   │ runs every ~10 minutes
                                   ▼
              POST /queue_pdfs  (X-API-Key required)
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │  PythonAnywhere — backend   │
                    │   (mysite/OCRWebApp.py)     │
                    │                             │
                    │   uploads/  ◀── queued PDFs │
                    │       │                     │
                    │       │ process_uploads.py  │
                    │       ▼                     │
                    │   processed/ → archive/     │ ──► shared/archive_directory/
                    │       ▼                     │
                    │   MySQL (pdfs, metadata)    │
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
   ┌──────────────────────┐                ┌─────────────────────────┐
   │  Frontend Flask app  │ ── /api/stats ─│   Public visitors        │
   │  (frontend/)         │                │   (no login)             │
   │                      │                │   Aggregate charts only  │
   │   Tool Hub (gated)   │                └─────────────────────────┘
   │   Browse / Lookup    │ ── magic link ─┌─────────────────────────┐
   │   Variable / AI      │                │  Tool Hub approved users │
   │   Reconciliation     │                │  (magic-link login)      │
   └──────────────────────┘                └─────────────────────────┘
              ▲
              │ Google Form → Sheet → Apps Script magic-link email
```

### Durable design decisions

- **Two Flask processes**, even in development. The developer/faculty backend (`mysite/`) and the public/Tool-Hub frontend (`frontend/`) are separated for security and so they can be hosted on different services if needed.
- **Python 3.11 recommended**, 3.10 acceptable. Python 3.12 may break pinned numpy; 3.9 is too old for some pinned libs.
- `OPENAI_API_KEY` is required at import time — the backend exits on startup if it is missing.
- The **AI assistant classifies questions first**, then either generates a safe `SELECT`-only SQL query and runs it, or replies in general-chat mode. There is no vector store or external RAG in this repo.
- **The archive directory is the source of truth for PDFs.** Everything else (`uploads/`, `processed/`, `OCRextractions/`) is transient.
- **`mysite/uploads/` is only cleared after a fully successful `process_uploads.py` run**, so the queue is resumable when something fails partway.

---

## 3. Quick start — local development

### Prerequisites

- Git
- Python **3.10+** (3.11 recommended)
- MySQL access (the project DB, a local MySQL, or any compatible test DB)
- An OpenAI API key
- macOS: `brew install tesseract` (for local OCR via `ocrmypdf`)
- Linux: install Tesseract and Ghostscript via your package manager
- Windows: install Tesseract and Ghostscript from official Windows builds

### Clone and create a virtual environment

```bash
git clone git@github.com:Resentencing/ResentencingProject.git
cd ResentencingProject

python3.11 -m venv .venv
source .venv/bin/activate                 # macOS / Linux
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1
# Windows cmd:         .venv\Scripts\activate.bat

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install Flask-Cors
```

### Configure environment variables

```bash
cp env.template .env
# Windows PowerShell:  Copy-Item env.template .env
```

Open `.env` and fill in real values. The variables you must set for the app to start are:

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | AI assistant; backend will not start without it |
| `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | MySQL connection used by both apps |
| `FLASK_SECRET_KEY` | Flask session signing |
| `ADMIN_PASSWORD` | Login gate for the backend (developer / faculty supervisor only) — **set a real value; never ship the template default** |
| `ARCHIVE_DIR` | Absolute path to where processed PDFs live on this machine |
| `LOG_DIR` | Absolute path for pipeline logs on this machine |

Optional / context-dependent:

| Variable | Purpose |
|----------|---------|
| `INGEST_API_KEY` / `API_KEY` | Shared secret for `X-API-Key` on `/queue_pdfs` and a few internal endpoints |
| `PYTHONANYWHERE_USERNAME`, `PYTHONANYWHERE_PASSWORD`, `SSH_HOST`, `PYTHONANYWHERE_DB_*` | Only needed if you use the SSH-tunnel helper scripts |
| `BACKEND_BASE_URL` | URL the frontend uses to call the backend (default `http://127.0.0.1:5000`) |
| `METADATA_REFRESH_TIMEOUT_SEC` | Max wall-clock for an in-browser metadata refresh |
| `ACCESS_HANDOFF_SECRET`, `APPS_SCRIPT_WEB_APP_EXEC_URL`, `STREAMLIT_*` | Only needed if you use the Streamlit RAG handoff |
| `ROLE_LIMITS_JSON`, `UNLIMITED_ACCESS_ROLE` | Override default per-role download rate limits |
| `PUBLIC_FRESHNESS_*` | Fallback "data as of" strings shown on the public homepage |

`.env` is gitignored. Never commit it.

### Run both apps

   ```bash
# Terminal A — backend (developer / faculty supervisor), default port 5000
   cd ResentencingProject
python mysite/OCRWebApp.py

# Terminal B — frontend (public site + Tool Hub), default port 5001
cd ResentencingProject/frontend
python flask_app.py
   ```

Health check:

   ```bash
curl http://127.0.0.1:5001/ping
# {"ok": true}
   ```

### Run the test suite

   ```bash
cd ResentencingProject
pytest
# Or just the backend suite:
cd mysite && pytest
```

---

## 4. Production deployment — PythonAnywhere

The reference deployment runs both apps on PythonAnywhere (paid plan, for the always-on tasks and SSH). The current production replica is at `rscap.pythonanywhere.com`.

Throughout this section `<your_pa_user>` is the PythonAnywhere account name. Substitute your own.

### Recommended layout

| Item | Path |
|------|------|
| Backend code | `/home/<your_pa_user>/mysite/` |
| Frontend code | `/home/<your_pa_user>/frontend/` |
| Virtual environment | `/home/<your_pa_user>/.virtualenvs/myvirtualenv/` |
| Archive of processed PDFs | `/home/<your_pa_user>/shared/archive_directory/` |
| Pipeline logs | `/home/<your_pa_user>/mysite/logs/` |
| WSGI entry (backend) | `OCRWebApp.py` under `mysite/` |

### Standard deploy

```bash
ssh <your_pa_user>@ssh.pythonanywhere.com
cd /home/<your_pa_user>/mysite
git pull
source ~/.virtualenvs/myvirtualenv/bin/activate

# Run any one-time migrations announced for this commit (most deploys: none).
# Examples:
# python add_uploaded_at_column.py
# python add_manual_review_columns.py
```

Then in the PythonAnywhere **Web** tab:

1. Find each web app (backend; frontend if hosted on PA).
2. Click **Reload**.
3. Confirm the "Web app was reloaded" timestamp updated.

**Code changes do not take effect until you reload.** If `git pull` reports "Already up to date" but the branch should have new commits, check `git status`, `git fetch`, and that you are on `main`.

### Production environment variables

All variables from § 3 plus the production-only items below. Set these in the PythonAnywhere **Web** tab → "Environment variables" for each web app (not in `.env` on the server).

- `INGEST_API_KEY` — must match the value stored in the Apps Script that posts new PDFs.
- `FLASK_SECRET_KEY` — rotated only when you mean to invalidate every session.
- `ADMIN_PASSWORD` — change from any historical or template value.
- `ARCHIVE_DIR`, `LOG_DIR` — set to the production paths above.

---

## 5. Letter upload pipeline

### End-to-end flow

```
Drive new PDF
  → Apps Script (every ~10 min) → POST /queue_pdfs  (X-API-Key)
  → mysite/uploads/   (HTTP 200, JSON: {saved, skipped})
  → process_uploads.py  (scheduled and/or manual)
      1. preprocess_pdf  → corrected_*.pdf in processed/
      2. extracttext     → OCRextractions/*.txt
      3. tagextraction   → Jsontags/metadata.json
      4. dbconnector.upload_to_database → MySQL  (uploaded_at = NOW())
      5. ON FULL SUCCESS ONLY: clear uploads/, processed/, OCRextractions/
```

### Manual run

   ```bash
cd /home/<your_pa_user>/mysite
source ~/.virtualenvs/myvirtualenv/bin/activate
python process_uploads.py

# Or from the backend home page: "Run OCR & upload to database"
# That kicks /run_process_uploads (HTTP 202 + a status JSON the browser polls).
```

### Apps Script (Drive automation)

A Google Apps Script bound to the team Drive folder uploads new PDFs to the backend. The script lives outside this repo (in the Google Apps Script project). It expects:

| Script Property | Value |
|-----------------|-------|
| `FLASK_URL` | The backend base URL, no trailing slash |
| `INGEST_API_KEY` | Same secret as the backend environment |
| `DRIVE_FOLDER_ID` | The watched Drive folder |

Trigger: `checkForNewFiles` every 10 minutes. Optional monthly: `monthlyMaintenance` (Drive dedupe, Excel sync). Manual recovery: `clearProcessedCache()` resets the script's "already processed" memory if a sync failed and files need to be re-driven after the server is fixed.

### Recovery cheat sheet

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| New uploads never appear | Apps Script trigger paused | Re-enable the trigger and run `checkForNewFiles` manually |
| `/queue_pdfs` returns 401 | `INGEST_API_KEY` mismatch | Sync the values; reload the web app |
| `uploads/` keeps growing | OCR or DB step failing | Read `process_uploads.status.json` and `logs/process_uploads.last.log`; fix; rerun |
| Stale lock present | `process_uploads.lock` left behind | Confirm no Python process is running, then remove the lock file |
| PDF >~50 pages is killed | PA worker memory/CPU limits | OCR offline (see § 7), rsync into the archive, then run `metadata_refresh.py` |
| **`unable to load configuration from metadata_refresh.py`** (browser Refresh Metadata) | uWSGI `sys.executable` used as subprocess interpreter | Deploy current `OCRWebApp.py` (`_pipeline_python()`); reload web app; or run `metadata_refresh.py` from Bash (§ 6) |

`process_uploads.status.json` statuses are `idle`, `running`, `done`, `error`, and `no_corrected_pdfs`. Always read this file before kicking another run.

---

## 6. Metadata refresh (bulk repair)

Run `metadata_refresh.py` when many rows have placeholder metadata, after rsyncing a batch into the archive, or after updating the tracking spreadsheets in `mysite/Excel/` (Excel changes do **not** automatically refresh DB rows).

   ```bash
cd /home/<your_pa_user>/mysite
source ~/.virtualenvs/myvirtualenv/bin/activate

# Small cohort:
python metadata_refresh.py

# Big cohort — wrap in screen/tmux so an SSH drop doesn't kill the run:
screen -S refresh
python metadata_refresh.py 2>&1 | tee -a logs/MetadataRefresh_manual_$(date +%F).log
# detach with Ctrl-A D; reattach later with: screen -r refresh
```

For very large batches, **do not** kick the refresh from the backend's browser route — even with a generous `METADATA_REFRESH_TIMEOUT_SEC`, the browser or the PA proxy can cut you off. Use the console.

On PythonAnywhere, `/refresh_metadata` must spawn the venv Python, not uwsgi (`sys.executable` under uWSGI). Optional env: `PYTHON_EXECUTABLE=~/.virtualenvs/myvirtualenv/bin/python3`.

### What gets written

| File | Contents |
|------|----------|
| `logs/MetadataRefresh_full_YYYY-MM-DD_HH-MM-SS.log` | Full stdout/stderr — OCR, Excel warnings, success/failure per file |
| `logs/MetadataRefresh_results_YYYY-MM-DD_HH-MM-SS.jsonl` | One JSON line per file (`filename`, `ok`, `pdf_id`, timestamp) |
| `logs/MetadataRefresh_YYYY-MM-DD.log` | Short summary appended at the end of each run |

Rows are committed **per file**. If a job dies at file 60 of 565, files 1–59 are already in MySQL.

### Problem rows after refresh

Rows that still cannot be confidently filled in (no CDC number in filename or OCR, no Excel row, batch PDFs the heuristics could not split, poor scans) appear in the backend **Missing Metadata** screen. **Refresh Metadata** after a new CDCR log re-merges log + PDF extraction. A Manual Review hand-edit UI was **deferred** — the CDCR log and OCR already supply metadata automatically; see handoff Transition Memo § II.E.

---

## 7. Bulk OCR escape hatch

PythonAnywhere's per-task CPU and memory ceilings make OCR of hundreds or thousands of PDFs at once impractical. The escape hatch is: OCR offline on a workstation, then rsync the results into the archive.

```bash
# 1) On a workstation with ocrmypdf + Tesseract installed:
python batch_ocr_parallel.py --input ./raw --output ./corrected --workers 8

# 2) rsync the corrected_<original>.pdf files into the production archive:
rsync -avz ./corrected/ <your_pa_user>@ssh.pythonanywhere.com:/home/<your_pa_user>/shared/archive_directory/

# 3) On PA, repair / attach DB rows:
cd /home/<your_pa_user>/mysite && source ~/.virtualenvs/myvirtualenv/bin/activate
python metadata_refresh.py 2>&1 | tee -a logs/MetadataRefresh_bulk_$(date +%F).log
```

This workflow does **not** drain `mysite/uploads/`. If the queue is also stuck, drain it via `process_uploads.py` (§ 5) — that is a separate concern.

For brand-new files that do not yet have a `pdfs` row, either run a one-time `file_recovery_auto.py` to insert inventory rows (placeholder metadata off by default — it just creates the `pdfs` row), or use a small inventory script that scans the archive and does `INSERT IGNORE`. After that, `metadata_refresh.py` can pick them up.

---

## 8. Public site & gated Tool Hub

### Public surfaces (no login)

- **Home** — overview, dataset freshness, §1170(d) reconciliation summary, stat cards, Letters by County chart, request-access CTA, Privacy/Terms links.
- **Charts** — aggregate only. **No personal names ever leave the public API.**
- **Request access** — a Google Form linked from the home page and `/access`.
- **About / Privacy / Terms / Contact** — static text.

### Gated Tool Hub (magic-link login)

- **Browse** — aggregate counts by category. No names, no downloads.
- **Lookup** — search by case number or CDCR number → details and a signed download URL (15-minute expiry); a "Download all letters for this person" action zips them.
- **Variable Explorer** — build comparison charts from chosen variables.
- **AI assistant** — natural-language Q&A; answers should always be verified against source PDFs.
- **Letter reconciliation** — compares the tracking log to the DB; surfaces matched / pending counts.

### Access flow

1. A visitor submits the public request-access Google Form.
2. A response row lands in a Google Sheet.
3. A bound Apps Script reads the row, auto-approves trusted domains (configurable list — typically `.edu`, `.gov`, etc.), and emails everyone else's request to the faculty supervisor for manual approval.
4. On approval the script emails the requester a signed magic link. The link routes through the public site first (which avoids Gmail's URL rewriting) and exchanges the token for a Flask session.
5. The requester's `role` column in the sheet determines their download rate limits.

### Rate limits (defaults)

- ~10 downloads/hour, 50/day, 3 ZIPs/day per session.
- Role overrides via the access sheet — trusted institutional domains or explicitly flagged `priority_access` roles get higher limits.

### Audit log

`frontend/audit.log` records one line per search and per download: email, IP, timestamp, action, target. Treat it as **sensitive personal data**: never publish raw audit logs, never commit them, never paste them into chat without redaction.

---

## 9. Database schema

Full schema and example queries: `DATABASE_SCHEMA.sql` at the repo root.

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `pdfs` | Inventory of letter PDFs | `id`, `filename` (unique), `file_path` |
| `metadata` | Extracted case-level data | `pdf_id` (FK), `cdcr_number`, `case_number`, `county`, `judge`, all date / sentence / cohort / cost-savings fields, `notes`, `uploaded_at`, `manual_review_needed`, `manual_review_reason` |
| `text_files` | OCR'd text references | `pdf_id` (FK), `text_file_path` |
| `dataset_source_refresh` | UTC "data as of" stamps for the public homepage | `source_key`, `refreshed_at`, `detail` |

### Safe console queries

Read-only when poking around:

```sql
SELECT id, filename FROM pdfs ORDER BY id DESC LIMIT 20;

SELECT pdf_id, cdcr_number, case_number, county, manual_review_needed
FROM metadata
WHERE manual_review_needed = 1
LIMIT 50;
```

Never run `UPDATE` / `DELETE` / `DROP` against the production DB without taking a snapshot first — PythonAnywhere does not auto-snapshot MySQL.

---

## 10. Migrations

Run once per environment after pulling code that introduces them:

```bash
cd /home/<your_pa_user>/mysite
source ~/.virtualenvs/myvirtualenv/bin/activate

python add_uploaded_at_column.py        # adds metadata.uploaded_at
python add_manual_review_columns.py     # adds manual_review_needed + manual_review_reason
```

Migration scripts are idempotent — running them a second time is a no-op if the column already exists.

---

## 11. Scheduled tasks

A typical PythonAnywhere → **Tasks** schedule, staggered so jobs don't collide:

| Order | Task | Frequency | Purpose |
|------:|------|-----------|---------|
| 1 | `Missedentryclear.py` | every 24 h | Housekeeping for `Jsontags/Metadata.json` |
| 2 | `fileconsistencycheck.py` | nightly ~02:00 | DB ↔ archive consistency report + email alert |
| 3 | `file_recovery_auto.py` | nightly ~02:30 | Insert `pdfs` rows for orphaned archive files (placeholders off by default) |
| 4 | `process_uploads.py` | daily ~10:00 UTC | Drain the Drive queue → archive + DB |
| 5 | `cleanup_metadata_duplicates.py --apply` | weekly | Drop Drive `Copy_of …` duplicates |
| 6 | `metadata_refresh.py` | as needed | Bulk repair; usually manual after Excel updates or rsync batches |

Example scheduled-task command:

```bash
cd /home/<your_pa_user>/mysite && /home/<your_pa_user>/.virtualenvs/myvirtualenv/bin/python3 process_uploads.py
```

Always `cd` into `mysite/` first so relative paths resolve the same way they do when the web app reads them.

---

## 12. Common operations — top commands

```bash
# Drain the Drive queue
cd /home/<your_pa_user>/mysite && source ~/.virtualenvs/myvirtualenv/bin/activate
python process_uploads.py

# Fix partial / placeholder rows
python metadata_refresh.py 2>&1 | tee -a logs/MetadataRefresh_manual_$(date +%F).log

# Duplicate cleanup — always dry-run first
python cleanup_metadata_duplicates.py
python cleanup_metadata_duplicates.py --apply --delete-archive-files

# Inspect what's stuck in the queue
ls /home/<your_pa_user>/mysite/uploads/ | wc -l
cat /home/<your_pa_user>/mysite/process_uploads.status.json
tail -80 /home/<your_pa_user>/mysite/logs/process_uploads.last.log

# Check the last 100 audit log entries
tail -100 /home/<your_pa_user>/frontend/audit.log
```

---

## 13. Troubleshooting

| Symptom | Likely cause | What to check / do |
|---------|--------------|--------------------|
| Backend won't start | Missing `OPENAI_API_KEY`; broken venv; wrong Python version | PA Web tab error log; confirm `.env` on disk; reactivate venv |
| Frontend `/api/stats` returns 500 | DB connection failed; `metadata.uploaded_at` not migrated | Check the error log; run `add_uploaded_at_column.py`; verify `DB_*` |
| Public homepage shows "0 letters" | Frontend can't reach the DB, or `metadata` is empty in this env | Hit `/api/stats` directly; verify `DB_*` in the frontend's environment |
| Magic-link sign-in fails with "Invalid token" | Token expired; `FLASK_SECRET_KEY` rotated since the link was issued | Re-issue link; rotate `FLASK_SECRET_KEY` only when you mean to invalidate sessions |
| Tool Hub Lookup returns no rows for a known CDCR # | Search-form parameter mismatch; backend filter regression; signed-URL issue | Reproduce against `/api/lookup` directly; inspect the Network tab |
| ZIP download fails partway | Per-session ZIP cap exceeded; or a source PDF missing from archive | Check rate-limit headers; verify the PDF exists in `archive_directory/` |
| AI returns nonsense | LLM hallucination, or DB has placeholder values the model trusts | Always verify against source PDFs; consider RAG for future |
| `nan can not be used with MySQL` | NaN sanitizer not in the bind path | Confirm latest code is deployed; redeploy and rerun |
| `process_uploads.py` ended but `uploads/` didn't clear | Final status was not `done`; failure in OCR or DB step | Re-read `status.json`; check `logs/process_uploads.last.log` |
| Apps Script can't see the Drive folder | Wrong folder ID, or scope missing | Check Script Properties; re-grant Drive scope |
| Sheet rows don't trigger emails | Trigger not installed, or daily quota exhausted | Apps Script → Triggers; confirm `onFormSubmit` exists; rerun manually |
| Tool Hub session expires too quickly | Cookie TTL too short, or `FLASK_SECRET_KEY` rotated | Adjust TTL; only rotate `FLASK_SECRET_KEY` intentionally |
| `git pull` fails on PA with a merge conflict | Something was edited directly on the server | Stash or discard the local edit, then pull again |
| Tests fail with "no module named X" | Wrong venv active, or `requirements.txt` updated without reinstall | Reactivate the venv; reinstall requirements |
| `ocrmypdf` complains about Ghostscript / jbig2enc | Missing system dependency | Install via the OS package manager (apt / brew / Chocolatey) |
| Apps Script "Service invoked too many times" | Hitting Google quota | Wait the cooldown; reduce trigger frequency; batch differently |

---

## 14. Security & secrets

- `.env` is gitignored. **Never** commit it.
- Use `env.template` as the reference for which variables must exist. Do **not** put real values in the template.
- Always change `ADMIN_PASSWORD` away from any historical or template value before exposing the backend.
- Rotate `OPENAI_API_KEY` and `INGEST_API_KEY` if they have been shared too broadly or shown up in any public log or screenshot.
- `frontend/audit.log` contains personal data (emails, IPs). Treat it as sensitive: do not export, commit, or share without redaction.
- Download rate limits and the audit log are intentional anti-abuse measures. Disable them only with explicit supervision approval.
- For new contributors, share secrets via a password manager. Never paste secrets into chat, email, or issue trackers.

---

## 15. Further documentation

This README is intentionally the only developer documentation published to GitHub. Deeper materials — the project transition memo, a longer system maintainer guide with full operations procedures, a non-technical frontend user guide, internal policy memos, and the team's working notes — are maintained in the project's Google Drive and are shared with new contributors by the faculty supervisor.

If you have forked or cloned this repository and need access to the deeper handoff materials, please contact the faculty supervisor.

---

## 16. License & acknowledgments

This project is a university research initiative. Source code is published here so the system can be audited and so the methodology can be replicated by other research teams.

Built and maintained by student developers under faculty supervision.

If you reuse this code or methodology in your own work, please cite the project and credit the research team.
