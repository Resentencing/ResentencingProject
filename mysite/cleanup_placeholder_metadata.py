"""
Remove auto-recovery *placeholder* metadata rows (fake date_stamped, NULL case/CDCR).

Leaves the corresponding ``pdfs`` row in place so files show under Missing metadata
and can be re-ingested after tagging / refresh fixes.

Usage (PA / local, from ``mysite/``):

    python3 cleanup_placeholder_metadata.py              # dry-run (default)
    python3 cleanup_placeholder_metadata.py --apply       # execute DELETEs
"""

from __future__ import annotations

import argparse
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

SELECT_SQL = """
SELECT m.id, p.id AS pdf_id, p.filename
FROM metadata m
JOIN pdfs p ON p.id = m.pdf_id
WHERE m.notes LIKE %s
  AND (m.case_number IS NULL OR TRIM(m.case_number) = '')
  AND (m.cdcr_number IS NULL OR TRIM(m.cdcr_number) = '')
ORDER BY p.filename
"""

DELETE_SQL = """
DELETE m FROM metadata m
JOIN pdfs p ON p.id = m.pdf_id
WHERE m.notes LIKE %s
  AND (m.case_number IS NULL OR TRIM(m.case_number) = '')
  AND (m.cdcr_number IS NULL OR TRIM(m.cdcr_number) = '')
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete placeholder auto-recovered metadata rows.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete rows (default is dry-run listing only).",
    )
    parser.add_argument(
        "--notes-like",
        default="%Auto-recovered%",
        help="SQL LIKE pattern for notes column (default: %%Auto-recovered%%).",
    )
    args = parser.parse_args()

    conn = pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(SELECT_SQL, (args.notes_like,))
            rows = cur.fetchall()
            print(f"Rows matching placeholder criteria: {len(rows)}")
            for mid, _pid, fn in rows[:50]:
                print(f"  metadata_id={mid}  {fn}")
            if len(rows) > 50:
                print(f"  … and {len(rows) - 50} more")

            if not args.apply:
                print("\nDry-run only. Pass --apply to delete these metadata rows.")
                return

            cur.execute(DELETE_SQL, (args.notes_like,))
            conn.commit()
            print(f"\nDeleted {cur.rowcount} metadata row(s). pdfs rows unchanged.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
