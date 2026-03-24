# What teammates need — local laptops + PythonAnywhere

Two surfaces: **frontend** (`frontend/flask_app.py`, port **5001**) and **staff backend** (`mysite/OCRWebApp.py`, port **5000**). PythonAnywhere usually hosts **at least** the backend + DB; the frontend may be Netlify or another host — match whatever your team actually deploys.

---

## Everyone (clone + run locally)

| Need | Why |
|------|-----|
| **Git access** to this repo | Clone / pull |
| **Python 3.11** (recommended) | `requirements.txt` installs reliably (avoid 3.9; 3.12 had numpy pin issues). Install via Homebrew, python.org, or `pyenv`. |
| **Virtualenv** | `python3.11 -m venv .venv` → `source .venv/bin/activate` |
| **`pip install -r requirements.txt`** + **`pip install Flask-Cors`** | See `frontend/README.md` |
| **`.env` from `env.template`** (each person’s copy, **never commit**) | DB credentials, `OPENAI_API_KEY` (required for **OCRWebApp**), `ADMIN_PASSWORD`, optional `API_KEY`, Dropbox vars if using sync |
| **MySQL reachable** | Same DB as the project (often **PythonAnywhere MySQL** — teammates use **remote** host/user/password from `.env`). Or a shared dev DB URL from the lead. |
| **macOS only (OCR locally):** `brew install tesseract` | If anyone runs OCR routes on a laptop |

**Docs:** `frontend/README.md` (frontend), `mysite/README.md` (backend).

---

## PythonAnywhere (whoever maintains the server)

| Need | Why |
|------|-----|
| **Paid/hosting account** with web app + MySQL (team policy) | Run Flask 24/7 + DB |
| **Repo deployed** under e.g. `/home/USERNAME/ResentencingProject/` | Git pull or upload |
| **Virtualenv on PA** tied to **same Python** as local (3.10+ / 3.11) | `mkvirtualenv` or PA dashboard venv + `pip install -r requirements.txt` + `Flask-Cors` for frontend if hosted there |
| **`.env` on the server** (PA “Files” or env in dashboard) | **Secrets only on PA** — `DB_*`, `OPENAI_API_KEY`, `API_KEY`, paths like `ARCHIVE_DIR`, `LOG_DIR` for **that** machine |
| **Web app → WSGI** pointing at `OCRWebApp`’s `app` | Standard Flask on PA; **working directory** = `mysite` or project root as your `import` paths expect |
| **Static / template paths** | Match how `Flask` is configured (templates under `mysite/templates`) |
| **MySQL** | Create DB + user in PA MySQL tab; **whitelist** if connecting from outside (or use SSH tunnel for local dev) |
| **Scheduled tasks** (optional) | See `mysite/setup_pythonanywhere.py` / consistency scripts |

Paths like **`/home/RSCAP/...`** in some scripts are **PythonAnywhere-specific** — adjust `USERNAME` for your account.

---

## Secrets & coordination (lead / admin)

- **One source of truth** for: MySQL host, DB name, user, password (rotate if someone leaves).
- **OpenAI API key** — who pays / which org key; don’t commit.
- **`API_KEY`** — shared secret if Netlify (or similar) calls the backend with **X-API-Key**; generate a long random string and share via password manager.
- **Dropbox** (if `dropbox_sync.py` is used): app token + folder path — only people who need it.

---

## Quick “does it work?” checks

| Where | Command / URL |
|-------|----------------|
| Local frontend | `cd frontend && python flask_app.py` → http://127.0.0.1:5001/ping |
| Local backend | `python mysite/OCRWebApp.py` from repo root → http://127.0.0.1:5000/ (needs `OPENAI_API_KEY`) |
| PA | Your team’s production URL + login/API as configured |

---

## Optional

- **pytest** — `python -m pip install -r requirements.txt` already includes test deps; run `pytest` from repo root (`mysite/tests/conftest.py` sets test env vars).
- **Jupyter** — `mysite/test_db_connection.ipynb` for ad hoc SQL (see root `README.md`).

If something differs for your team (e.g. **only** frontend on Netlify), add one line here so the next person isn’t guessing.
