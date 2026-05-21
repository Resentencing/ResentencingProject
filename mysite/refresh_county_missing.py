"""
Re-run OCR + tag extraction for PDFs that still have no county on any metadata row.

Targets rows where county is NULL/blank (includes "Partial hints from filename" cohort).

Usage (PythonAnywhere console):
    cd /home/RSCAP/mysite
    source ~/.virtualenvs/myvirtualenv/bin/activate
    python3 refresh_county_missing.py

Usage (Mac + SSH tunnel — keep tunnel open in another terminal):
    ssh -N -L 3307:RSCAP.mysql.pythonanywhere-services.com:3306 RSCAP@ssh.pythonanywhere.com

    cd mysite
    export ARCHIVE_DIR="/path/to/ResentencingProject/shared/archive_directory"
    python3 refresh_county_missing.py

    (.env should use DB_HOST=127.0.0.1 and DB_PORT=3307.)

PDFs not present under ARCHIVE_DIR are skipped (run on PA or rsync archive for full cohort).
"""

import os

import pymysql
from dotenv import load_dotenv

import metadata_refresh as mr

load_dotenv()


def get_pdfs_missing_county():
    connection = pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT p.id, p.filename, p.file_path
                FROM pdfs p
                INNER JOIN metadata m ON m.pdf_id = p.id
                WHERE m.county IS NULL OR TRIM(m.county) = ''
                ORDER BY p.filename
                """
            )
            return cursor.fetchall()
    finally:
        connection.close()


def _split_cohort_by_local_pdf(cohort):
    ready = []
    missing = []
    archive = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
    for pdf_id, filename, file_path in cohort:
        open_path, _ = mr._resolve_open_pdf_path(filename, file_path)
        if open_path and os.path.isfile(open_path):
            ready.append((pdf_id, filename, file_path))
        else:
            missing.append(filename)
    return ready, missing, archive


def main():
    cohort = get_pdfs_missing_county()
    if not cohort:
        print("No PDFs with missing county.")
        return

    ready, missing, archive = _split_cohort_by_local_pdf(cohort)
    print(f"=== County refresh ({len(cohort)} PDFs in DB, {len(ready)} on disk) ===")
    print(f"ARCHIVE_DIR={archive!r}")
    if missing:
        print(f"Skipping {len(missing)} PDF(s) not found locally (run on PA or rsync archive):")
        for name in missing[:25]:
            print(f"  - {name}")
        if len(missing) > 25:
            print(f"  ... and {len(missing) - 25} more")

    if not ready:
        print("Nothing to process on this machine.")
        return

    ok = 0
    fail = 0
    for pdf_id, filename, file_path in ready:
        if mr.refresh_metadata_for_file(pdf_id, filename, file_path, metadata_row_exists=True):
            ok += 1
        else:
            fail += 1
    print(f"\nDone: {ok} ok, {fail} failed (processed {len(ready)} of {len(cohort)} PDFs)")


if __name__ == "__main__":
    main()
