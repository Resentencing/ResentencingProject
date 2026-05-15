#!/usr/bin/env python3
"""
One-time migration: add `uploaded_at` to the `metadata` table.

`date_stamped` holds the date written on the letter (from OCR text), not when
the row was ingested. The public dashboard uses MAX(uploaded_at) for
"Letter database last synced".

Usage (PythonAnywhere bash, same venv as the app):
    cd /home/RSCAP/mysite
    python add_uploaded_at_column.py 2026-04-24    # optional backfill date
    python add_uploaded_at_column.py --no-backfill
"""

import argparse
import datetime
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
env_path = SCRIPT_DIR.parent / ".env"
if not load_dotenv(env_path) and (SCRIPT_DIR / ".env").exists():
    load_dotenv(SCRIPT_DIR / ".env")

import mysql.connector


def _config():
    return {
        "host": os.getenv("DB_HOST"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME"),
    }


def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone()[0] > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "date",
        nargs="?",
        default=None,
        help="Backfill date for NULL uploaded_at (YYYY-MM-DD); default today",
    )
    parser.add_argument(
        "--no-backfill",
        action="store_true",
        help="Do not UPDATE existing rows",
    )
    args = parser.parse_args()

    backfill_date = args.date or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(backfill_date)
    except ValueError:
        print(f"Invalid date: {backfill_date!r}. Use YYYY-MM-DD.", file=sys.stderr)
        return 1

    conn = mysql.connector.connect(**_config())
    cur = conn.cursor()

    if column_exists(cur, "metadata", "uploaded_at"):
        print("Column `uploaded_at` already exists. Nothing to alter.")
    else:
        cur.execute(
            "ALTER TABLE metadata "
            "ADD COLUMN uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP"
        )
        conn.commit()
        print("Added `uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP` to metadata.")

    if args.no_backfill:
        print("Skipping backfill (--no-backfill).")
    else:
        cur.execute(
            "UPDATE metadata SET uploaded_at = %s WHERE uploaded_at IS NULL",
            (f"{backfill_date} 00:00:00",),
        )
        conn.commit()
        print(f"Set uploaded_at where NULL for {cur.rowcount} row(s) → {backfill_date}.")

    cur.execute("SELECT MAX(uploaded_at) FROM metadata")
    print("MAX(uploaded_at) is now:", cur.fetchone()[0])

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
