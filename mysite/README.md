# Backend (`OCRWebApp.py`) — local run

Staff/admin Flask app: uploads, OCR pipeline, DB tools, **`/database_ai`**, **`/query_ai`**, etc. (not the same as the coalition **frontend** on port 5001).

## 1. Same venv as the rest of the project

From the **repo root** (Python **3.11** venv recommended — see `frontend/README.md`):

```bash
cd path/to/ResentencingProject
source .venv/bin/activate
```

(`path/to/ResentencingProject` = **your** machine’s folder where you cloned the repo — not a literal username.)

## 2. Environment (`.env` in repo root)

```bash
cp env.template .env
```

**Required for the app to start:** `OPENAI_API_KEY` — `OCRWebApp.py` raises on import if this is missing.

**Strongly recommended:**

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | **Required** — OpenAI client + NL features |
| `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | MySQL (e.g. PythonAnywhere remote DB) |
| `API_KEY` | Shared secret for **X-API-Key** (e.g. Netlify → backend); if unset, proxy routes log a warning |
| `ADMIN_PASSWORD` | Login to the staff UI (default in code is weak — set in `.env` for real use) |

`load_dotenv()` loads **`.env` from the current working directory**, so run the backend from a directory where `.env` is visible, or export vars in the shell.

**Easiest:** always start from the **repository root** and invoke the app so paths resolve:

```bash
cd path/to/ResentencingProject
source .venv/bin/activate
python mysite/OCRWebApp.py
```

## 3. URL and port

- Default Flask dev server: **http://127.0.0.1:5000/** (port **5000**, `debug=True` in code).
- **Frontend** (if also running) uses **5001** — no conflict.

## 4. Optional: explicit env file path

If you start from `mysite/` and `.env` is only in the parent folder:

```bash
cd mysite
set -a && source ../.env && set +a
python OCRWebApp.py
```

(or copy/link `.env` into `mysite/` — not ideal for secrets duplication).

## 5. Notes

- **Tesseract / OCR:** `ocrmypdf` / `pytesseract` need **Tesseract** installed on the Mac (`brew install tesseract`) for OCR routes to work locally.
- **Line 51 in `OCRWebApp.py`** prepends a **PythonAnywhere** path to `PATH`; on a Mac it usually doesn’t break anything, but if CLI tools act odd, check `PATH`.
- **MySQL:** point `DB_*` at your real DB (often remote). Without DB, many routes will error when they connect.

## 6. Alternative: Flask CLI

```bash
cd path/to/ResentencingProject
export FLASK_APP=mysite/OCRWebApp.py
export FLASK_ENV=development
flask run
```

(Ensure project root is on `PYTHONPATH` if imports fail — running `python mysite/OCRWebApp.py` from repo root is simpler.)
