#!/usr/bin/env python3
"""
Process pending PDF uploads end-to-end.

This script is the "heavy work" half of the upload pipeline when PDFs were
queued with ``POST /queue_pdfs`` (e.g. Google Apps Script). It also processes
anything sitting in ``uploads/`` from other sources.

Admins who use ``POST /upload_and_process`` get immediate OCR into ``processed/``
without needing this script for that file — they then use ``/upload_to_database``.

    uploads/*.pdf  --(preprocess_pdf / OCR)-->   processed/corrected_*.pdf
    processed/     --(extracttext)-->            OCRextractions/*.txt
    OCRextractions --(tagextraction)-->          Jsontags/metadata.json
    metadata.json  --(dbconnector.upload)-->     MySQL `metadata` table
                                                 (uploaded_at = NOW() auto)

After a successful run the working folders are cleared.

Invocation
----------
    python process_uploads.py                # normal run
    python process_uploads.py --quiet        # less log output
    python process_uploads.py --force        # ignore the lockfile

Triggers
--------
    - PythonAnywhere "Scheduled task" tab (runs once a day)
    - The OCR backend home page: POST ``/run_process_uploads`` (button:
      "Run OCR & upload to database"), which starts this script in the
      background

Lockfile
--------
A file lock at `mysite/process_uploads.lock` prevents the cron job and the
backend trigger from running concurrently. If a previous run died without
releasing it, pass --force.
"""

import argparse
import contextlib
import datetime
import logging
import os
import shutil
import signal
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if os.getcwd() != str(SCRIPT_DIR):
    os.chdir(SCRIPT_DIR)
    sys.path.insert(0, str(SCRIPT_DIR))

from dotenv import load_dotenv

env_path = SCRIPT_DIR.parent / ".env"
if not load_dotenv(env_path) and (SCRIPT_DIR / ".env").exists():
    load_dotenv(SCRIPT_DIR / ".env")

UPLOAD_FOLDER = SCRIPT_DIR / "uploads"
OUTPUT_FOLDER = SCRIPT_DIR / "processed"
EXTRACTIONS = SCRIPT_DIR / "OCRextractions"
METADATA_FILE = SCRIPT_DIR / "Jsontags" / "metadata.json"
ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
LOCKFILE = SCRIPT_DIR / "process_uploads.lock"
STATUS_FILE = SCRIPT_DIR / "process_uploads.status.json"

log = logging.getLogger("process_uploads")


def _write_status(state: str, **extra) -> None:
    """Write a small JSON status blob the Tool Hub can poll."""
    import json
    payload = {
        "state": state,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    payload.update(extra)
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        log.warning("Could not write status file: %s", e)


@contextlib.contextmanager
def _file_lock(force: bool = False):
    """Best-effort file lock; raises RuntimeError if held."""
    if LOCKFILE.exists() and not force:
        try:
            pid = int(LOCKFILE.read_text().strip())
        except (ValueError, OSError):
            pid = 0
        # If the PID is gone, treat the lock as stale.
        if pid > 0 and _pid_alive(pid):
            raise RuntimeError(f"Another run is in progress (pid={pid}). Use --force to override.")
        log.warning("Stale lockfile detected (pid=%s); replacing.", pid)
    try:
        LOCKFILE.write_text(str(os.getpid()))
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            LOCKFILE.unlink()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user
    return True


def _ensure_dirs() -> None:
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    EXTRACTIONS.mkdir(parents=True, exist_ok=True)
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not os.path.exists(ARCHIVE_DIR):
        # Local-dev fallback so this script also works on a Mac.
        _local = SCRIPT_DIR.parent / "shared" / "archive_directory"
        _local.mkdir(parents=True, exist_ok=True)
        os.environ["ARCHIVE_DIR"] = str(_local)


def run_once(force: bool = False) -> dict:
    """Run the full pipeline once. Returns a small summary dict."""
    _ensure_dirs()

    pdfs = sorted(p for p in UPLOAD_FOLDER.glob("*.pdf"))
    if not pdfs:
        log.info("No PDFs in %s. Nothing to do.", UPLOAD_FOLDER)
        _write_status("idle", pdfs_pending=0, last_finished=datetime.datetime.now(datetime.timezone.utc).isoformat())
        return {"status": "idle", "pdfs": 0}

    log.info("Found %d pending PDF(s) in %s.", len(pdfs), UPLOAD_FOLDER)
    _write_status("running", pdfs_pending=len(pdfs))

    started = time.monotonic()
    results = {
        "status": "ok",
        "pdfs_seen": len(pdfs),
        "pdfs_preprocessed": 0,
        "pdfs_failed": [],
        "duration_seconds": 0,
    }

    # Lazy imports so importing this module is cheap (the manual route does
    # `subprocess.Popen` so this only matters for in-process callers).
    import mysql.connector

    import dbconnector
    import extracttext
    import tagextraction
    from OCRWebApp import preprocess_pdf  # OCR + correct + archive

    # 1) OCR / preprocess
    for pdf in pdfs:
        log.info("Preprocessing: %s", pdf.name)
        try:
            preprocess_pdf(str(pdf), str(OUTPUT_FOLDER))
            results["pdfs_preprocessed"] += 1
        except Exception as e:
            log.exception("Preprocess failed for %s: %s", pdf.name, e)
            results["pdfs_failed"].append({"file": pdf.name, "stage": "ocr", "error": str(e)})

    corrected = list(OUTPUT_FOLDER.glob("corrected_*.pdf"))
    if not corrected:
        log.warning("No corrected PDFs produced. Skipping extraction & DB insert.")
        results["status"] = "no_corrected_pdfs"
        results["duration_seconds"] = round(time.monotonic() - started, 1)
        _write_status("error", **results)
        return results

    # 2) Text extraction
    log.info("Extracting text from %d corrected PDF(s)...", len(corrected))
    extracttext.extract_text_from_pdfs(str(OUTPUT_FOLDER), str(EXTRACTIONS))

    # 3) Tag extraction
    log.info("Extracting metadata tags...")
    tagextraction.extract_metadata_from_text_files(str(EXTRACTIONS), str(METADATA_FILE))

    # 4) DB upload (uploaded_at auto-fills via DEFAULT CURRENT_TIMESTAMP)
    log.info("Uploading metadata to database...")
    database_config = {
        "host": os.getenv("DB_HOST"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME"),
    }
    conn = mysql.connector.connect(**database_config)
    try:
        dbconnector.upload_to_database(
            conn,
            os.getenv("ARCHIVE_DIR", ARCHIVE_DIR),
            str(EXTRACTIONS),
            str(METADATA_FILE),
        )
        # Best-effort lineage stamp for the Public Dashboard freshness card.
        try:
            from dataset_lineage import touch_dataset_source
            cur = conn.cursor()
            touch_dataset_source(cur, conn, "letters_db", detail="process_uploads")
            cur.close()
        except Exception as lineage_err:
            log.warning("Lineage stamp skipped: %s", lineage_err)
    finally:
        conn.close()

    # 5) Clear working folders so the next run starts clean
    for d in (UPLOAD_FOLDER, OUTPUT_FOLDER, EXTRACTIONS):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
    log.info("Cleared working folders.")

    results["duration_seconds"] = round(time.monotonic() - started, 1)
    log.info("Done. %s", results)
    _write_status("done", **results, last_finished=datetime.datetime.now(datetime.timezone.utc).isoformat())
    return results


def _setup_logging(quiet: bool) -> None:
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _install_signal_handlers():
    """Make sure the lockfile is released on SIGTERM (PA task killed)."""
    def _handler(signum, _frame):
        log.warning("Received signal %s; releasing lock and exiting.", signum)
        with contextlib.suppress(FileNotFoundError):
            LOCKFILE.unlink()
        sys.exit(130)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="Less log output")
    parser.add_argument("--force", action="store_true", help="Ignore the lockfile")
    args = parser.parse_args()

    _setup_logging(args.quiet)
    _install_signal_handlers()

    try:
        with _file_lock(force=args.force):
            run_once(force=args.force)
    except RuntimeError as e:
        log.error(str(e))
        return 2
    except Exception:
        log.exception("Pipeline failed.")
        _write_status("error", error="see logs")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
