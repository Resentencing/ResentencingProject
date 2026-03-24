#!/usr/bin/env python3
"""
Dropbox Sync for 1172.1 Resentencing Letters

Watches a Dropbox folder for new PDFs, downloads them, and runs the full
OCR + metadata + database upload pipeline. Designed to run via cron on
PythonAnywhere (e.g., every 15–30 minutes).

Setup:
  1. Create a Dropbox app at https://www.dropbox.com/developers/apps
  2. Generate an access token (or use OAuth2 for long-lived token)
  3. Add to .env:
     DROPBOX_ACCESS_TOKEN=your_token
     DROPBOX_FOLDER=/1172.1 Letters   # or your folder path
  4. Run: python dropbox_sync.py (from mysite/ directory)
"""

import os
import sys
import json
import logging
import shutil
from pathlib import Path

# Ensure we run from mysite/ for correct imports and paths
SCRIPT_DIR = Path(__file__).resolve().parent
if os.getcwd() != str(SCRIPT_DIR):
    os.chdir(SCRIPT_DIR)
    sys.path.insert(0, str(SCRIPT_DIR))

from dotenv import load_dotenv
# Load .env from project root (parent of mysite/)
env_path = SCRIPT_DIR.parent / ".env"
loaded = load_dotenv(env_path)
if not loaded and (SCRIPT_DIR / ".env").exists():
    load_dotenv(SCRIPT_DIR / ".env")  # fallback: mysite/.env

# Config
DROPBOX_ACCESS_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN") or os.getenv("DROPBOX_ACCESS_TOOKEN")  # common typo
DROPBOX_FOLDER = os.getenv("DROPBOX_FOLDER", "/1172.1 Letters")
STATE_FILE = SCRIPT_DIR / "dropbox_sync_state.json"
UPLOAD_FOLDER = SCRIPT_DIR / "uploads"
OUTPUT_FOLDER = SCRIPT_DIR / "processed"
EXTRACTIONS = "OCRextractions"
ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
if not os.path.exists(ARCHIVE_DIR):
    # Local dev fallback: use project shared/archive_directory
    _local = SCRIPT_DIR.parent / "shared" / "archive_directory"
    ARCHIVE_DIR = str(_local)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.environ["ARCHIVE_DIR"] = ARCHIVE_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)


def load_processed_state():
    """Load set of Dropbox paths we've already processed."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, TypeError):
            pass
    return set()


def save_processed_state(state):
    """Persist processed paths."""
    with open(STATE_FILE, "w") as f:
        json.dump(list(state), f, indent=2)


def download_from_dropbox(persist_state=True):
    """Download new PDFs from Dropbox folder. Returns list of (local_path, dropbox_path).
    If persist_state=False, does not save processed state (for --dry-run)."""
    try:
        import dropbox
    except ImportError:
        log.error("dropbox package not installed. Run: pip install dropbox")
        return []

    if not DROPBOX_ACCESS_TOKEN:
        env_path = SCRIPT_DIR.parent / ".env"
        log.error("DROPBOX_ACCESS_TOKEN not set. Check %s", env_path)
        log.error("  Variable must be exactly: DROPBOX_ACCESS_TOKEN=sl.xxx (no spaces around =)")
        if env_path.exists():
            log.error("  .env exists at that path - verify the line is present and not commented with #")
        return []

    dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
    processed = load_processed_state()
    downloaded = []

    try:
        result = dbx.files_list_folder(DROPBOX_FOLDER)
    except dropbox.exceptions.ApiError as e:
        if "path/not_found" in str(e).lower():
            log.error("Dropbox folder not found: %s. Create it or fix DROPBOX_FOLDER.", DROPBOX_FOLDER)
        else:
            log.error("Dropbox API error: %s", e)
        return []

    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    entries = list(result.entries)
    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)

    for entry in entries:
        if isinstance(entry, dropbox.files.FileMetadata):
            path_lower = entry.path_display.lower()
            if path_lower.endswith(".pdf") and path_lower not in (p.lower() for p in processed):
                local_path = UPLOAD_FOLDER / os.path.basename(entry.path_display)
                try:
                    md, res = dbx.files_download(entry.path_display)
                    with open(local_path, "wb") as f:
                        f.write(res.content)
                    log.info("Downloaded: %s", entry.path_display)
                    downloaded.append((str(local_path), entry.path_display))
                    processed.add(entry.path_display)
                except Exception as e:
                    log.error("Failed to download %s: %s", entry.path_display, e)

    if persist_state:
        save_processed_state(processed)
    return downloaded


def run_pipeline():
    """Run OCR + extract + metadata + db upload on files in processed/."""
    import extracttext
    import tagextraction
    import dbconnector
    import mysql.connector
    from dbconnector import database_config
    from OCRWebApp import preprocess_pdf

    # 1. Preprocess each PDF in uploads/ (OCR, correct, archive)
    for f in UPLOAD_FOLDER.glob("*.pdf"):
        log.info("Preprocessing: %s", f.name)
        try:
            preprocess_pdf(str(f), str(OUTPUT_FOLDER))
        except Exception as e:
            log.error("Preprocess failed for %s: %s", f.name, e)

    if not list(OUTPUT_FOLDER.glob("corrected_*.pdf")):
        log.info("No corrected PDFs to process. Skipping extraction.")
        return

    # 2. Extract text
    os.makedirs(EXTRACTIONS, exist_ok=True)
    extracttext.extract_text_from_pdfs(str(OUTPUT_FOLDER), EXTRACTIONS)
    log.info("Text extraction done.")

    # 3. Extract metadata
    metadata_file = SCRIPT_DIR / "Jsontags" / "metadata.json"
    os.makedirs(metadata_file.parent, exist_ok=True)
    tagextraction.extract_metadata_from_text_files(EXTRACTIONS, str(metadata_file))
    log.info("Metadata extraction done.")

    # 4. Upload to database
    conn = mysql.connector.connect(**database_config)
    dbconnector.upload_to_database(
        conn,
        ARCHIVE_DIR,
        EXTRACTIONS,
        str(metadata_file),
    )
    conn.close()
    log.info("Database upload done.")

    # 5. Clear working directories
    for d in (UPLOAD_FOLDER, OUTPUT_FOLDER):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
    extractions_path = SCRIPT_DIR / EXTRACTIONS
    if extractions_path.exists():
        shutil.rmtree(extractions_path, ignore_errors=True)
        extractions_path.mkdir(parents=True, exist_ok=True)
    log.info("Cleared working directories.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sync PDFs from Dropbox and run OCR pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Only list/download from Dropbox, skip OCR and DB")
    parser.add_argument("--list-root", action="store_true", help="List root folder to find correct path, then exit")
    args = parser.parse_args()

    if args.list_root:
        try:
            import dropbox
            dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
            result = dbx.files_list_folder("")
            for e in result.entries:
                log.info("  %s: %s", "DIR" if isinstance(e, dropbox.files.FolderMetadata) else "FILE", e.name)
            return
        except Exception as e:
            log.error("List root failed: %s", e)
            return

    log.info("Dropbox sync starting. Folder: %r", DROPBOX_FOLDER or "(root)")
    downloaded = download_from_dropbox(persist_state=not args.dry_run)
    if not downloaded:
        log.info("No new PDFs found. Exiting.")
        return
    log.info("Downloaded %d new file(s).", len(downloaded))
    if args.dry_run:
        log.info("Dry run: skipping OCR and database. Files saved to %s", UPLOAD_FOLDER)
        return
    log.info("Processing with full pipeline...")
    run_pipeline()
    log.info("Dropbox sync complete.")


if __name__ == "__main__":
    main()
