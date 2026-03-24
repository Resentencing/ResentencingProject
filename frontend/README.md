# Frontend (Resentence and Decarcerate / RAD) — local run

## 1. Python version (required)

This repo’s `requirements.txt` needs **Python 3.10+** (e.g. **click 8.2.x**). Apple’s default `python3` is often **3.9** — install a newer Python.

### Use Python 3.11 for the venv (recommended)

Pinned **`numpy==1.25.2`** has **pre-built wheels for 3.11**, so `pip install` is quick and reliable.

**Do not use Python 3.12** for this venv unless you change pins: **`numpy==1.25.2` has no usable wheel on 3.12**, so pip tries to compile from source and the build fails (e.g. `pkgutil` has no attribute `ImpImporter`).

Replace `path/to/ResentencingProject` with **your** clone directory (e.g. `~/Projects/ResentencingProject`).

```bash
brew install python@3.11
cd path/to/ResentencingProject
rm -rf .venv
/opt/homebrew/opt/python@3.11/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install Flask-Cors
```

Intel Homebrew path is often `/usr/local/opt/python@3.11/bin/python3.11`.

---

### macOS: `python3.12: command not found` (only if you insist on 3.12)

**Option A — Homebrew (recommended)**

```bash
brew install python@3.12
```

Then use the full path (Apple Silicon Macs):

```bash
/opt/homebrew/opt/python@3.12/bin/python3.12 --version
```

Intel Macs often use:

```bash
/usr/local/opt/python@3.12/bin/python3.12 --version
```

If `python3.12` still isn’t on your PATH, add this to `~/.zshrc` (adjust for Intel vs Apple Silicon):

```bash
export PATH="/opt/homebrew/opt/python@3.12/libexec/bin:$PATH"
```

Reload: `source ~/.zshrc`, then `python3.12 --version`.

**Option B — python.org**

Download the **macOS installer** for Python 3.12.x from [python.org](https://www.python.org/downloads/). After install, use **“Python Launcher”** or:

```bash
/usr/local/bin/python3.12 --version
```

(or check `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12`)

**If you already used 3.12 and `Flask-Cors` pulled in Flask 3.x**, after a successful `pip install -r requirements.txt` with 3.11 you should have **Flask 2.3.3** from the file; uninstall stray packages if needed: `python -m pip install -r requirements.txt` again.

**Do not paste comments on the same line as `pip install`** in the terminal — a trailing `# ...` can break the command.

## 2. Environment (from repo root)

Same as §1 — use **Python 3.11** and the block above. On **Windows**, prefer `py -3.11 -m venv .venv` then `.venv\Scripts\activate`.

## 3. Config

```bash
cp env.template .env
```

Edit **`.env`** and set at least:

- `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` — needed for **Archive search**, **charts** (`/visualize`), **`/api/stats`**, and **downloads**.

Without a working MySQL connection, you can still open **static pages** (home, about, privacy, terms, contact) — but archive search and visualizations will error when they hit the DB.

## 4. Start the app

```bash
cd frontend
python flask_app.py
```

- **URL:** [http://127.0.0.1:5001](http://127.0.0.1:5001)  
- Debug mode is on; the server listens on `0.0.0.0:5001`.

## 5. Quick checks

| URL | Needs DB? |
|-----|-----------|
| `/` | No |
| `/about`, `/templates/privacy`, `/templates/terms`, `/templates/contact` | No |
| `/archive` (page only) | No |
| `/archive_search` (submit form) | Yes |
| `/visualize`, `/api/stats` | Yes |

`GET /ping` should return `{"ok": true}`.
