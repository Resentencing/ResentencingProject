#!/usr/bin/env python3
"""
Daily cleanup: remove duplicate DB rows for Drive \"Copy of\" corrected PDFs and junk filenames.

When ``corrected_Copy_of_Foo.pdf`` exists in ``pdfs`` and ``corrected_Foo.pdf`` already
represents the same letter, drop the Copy row (``metadata`` / ``text_files`` CASCADE).

Without ``--apply``, only logs what would be deleted (safe default).

Usage (PythonAnywhere scheduled task, after backups):
    cd /home/RSCAP/mysite && \\
      /home/RSCAP/.virtualenvs/myvirtualenv/bin/python3 cleanup_metadata_duplicates.py \\
        --apply --delete-archive-files

Env: same as other mysite scripts (DB_*, ARCHIVE_DIR).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

from drive_duplicate_names import canonical_corrected_pdf_filename

SCRIPT_DIR = Path(__file__).resolve().parent
if os.getcwd() != str(SCRIPT_DIR):
    os.chdir(SCRIPT_DIR)
    sys.path.insert(0, str(SCRIPT_DIR))

env_path = SCRIPT_DIR.parent / ".env"
if not load_dotenv(env_path) and (SCRIPT_DIR / ".env").exists():
    load_dotenv(SCRIPT_DIR / ".env")


def _connect():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", "3306")),
    )


def _meta_row(cursor, pdf_id: int):
    cursor.execute(
        "SELECT case_number, date_stamped, cdcr_number FROM metadata WHERE pdf_id = %s LIMIT 1",
        (pdf_id,),
    )
    return cursor.fetchone()


def _meta_compatible(canonical_meta, dup_meta) -> bool:
    """Both non-None and same case + date_stamped (normalized strings)."""
    if canonical_meta is None or dup_meta is None:
        return False

    def norm(x):
        if x is None:
            return ""
        return str(x).strip()

    c_case, c_date, c_cdcr = canonical_meta[:3]
    d_case, d_date, d_cdcr = dup_meta[:3]
    if norm(c_case) != norm(d_case) or norm(c_date) != norm(d_date):
        return False
    if norm(c_cdcr) and norm(d_cdcr) and norm(c_cdcr) != norm(d_cdcr):
        return False
    return True


def cleanup_copy_duplicates(conn, apply: bool, delete_archive_files: bool) -> dict:
    archive_dir = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
    stats = {"candidates": 0, "deleted": 0, "skipped": 0, "would_delete": 0}
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, filename, file_path FROM pdfs WHERE filename LIKE 'corrected_%'")
        rows = cursor.fetchall()
        for pdf_id, filename, file_path in rows:
            canon_name = canonical_corrected_pdf_filename(filename)
            if not canon_name:
                continue
            stats["candidates"] += 1
            cursor.execute("SELECT id FROM pdfs WHERE filename = %s", (canon_name,))
            canon = cursor.fetchone()
            if not canon:
                stats["skipped"] += 1
                logging.info("No canonical row for duplicate-style %s (expected %s)", filename, canon_name)
                continue
            canon_id = canon[0]
            canon_meta = _meta_row(cursor, canon_id)
            dup_meta = _meta_row(cursor, pdf_id)

            if dup_meta and canon_meta and not _meta_compatible(canon_meta, dup_meta):
                stats["skipped"] += 1
                logging.warning(
                    "Skip delete %s: metadata differs from canonical %s", filename, canon_name
                )
                continue
            if dup_meta and not canon_meta:
                stats["skipped"] += 1
                logging.warning(
                    "Skip delete %s: duplicate has metadata but canonical %s has none",
                    filename,
                    canon_name,
                )
                continue

            stats["would_delete"] += 1
            path_to_unlink = file_path if delete_archive_files else None
            if path_to_unlink and not os.path.isfile(path_to_unlink):
                alt = os.path.join(archive_dir, os.path.basename(filename))
                if os.path.isfile(alt):
                    path_to_unlink = alt
                else:
                    path_to_unlink = None

            if apply:
                cursor.execute("DELETE FROM pdfs WHERE id = %s", (pdf_id,))
                if path_to_unlink:
                    try:
                        os.unlink(path_to_unlink)
                        logging.info("Removed archive file %s", path_to_unlink)
                    except OSError as e:
                        logging.warning("Could not unlink %s: %s", path_to_unlink, e)
                stats["deleted"] += 1
                logging.info("Deleted duplicate pdf row id=%s filename=%s", pdf_id, filename)
            else:
                logging.info(
                    "[dry-run] Would delete pdf id=%s %s (canonical id=%s %s)",
                    pdf_id,
                    filename,
                    canon_id,
                    canon_name,
                )
        if apply:
            conn.commit()
        else:
            conn.rollback()
    finally:
        cursor.close()
    return stats


def cleanup_junk_filenames(conn, apply: bool, delete_archive_files: bool) -> dict:
    """Remove pdfs whose filename indicates non-letters (e.g. __DISREGARD)."""
    patterns = ("%DISREGARD%",)
    stats = {"candidates": 0, "deleted": 0}
    archive_dir = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
    cursor = conn.cursor()
    try:
        for pat in patterns:
            cursor.execute(
                "SELECT id, filename, file_path FROM pdfs WHERE filename LIKE %s",
                (pat,),
            )
            for pdf_id, filename, file_path in cursor.fetchall():
                stats["candidates"] += 1
                path_to_unlink = None
                if delete_archive_files:
                    path_to_unlink = file_path if os.path.isfile(file_path) else None
                    if not path_to_unlink:
                        alt = os.path.join(archive_dir, os.path.basename(filename))
                        if os.path.isfile(alt):
                            path_to_unlink = alt
                if apply:
                    cursor.execute("DELETE FROM pdfs WHERE id = %s", (pdf_id,))
                    stats["deleted"] += 1
                    if path_to_unlink:
                        try:
                            os.unlink(path_to_unlink)
                            logging.info("Removed junk archive file %s", path_to_unlink)
                        except OSError as e:
                            logging.warning("Could not unlink %s: %s", path_to_unlink, e)
                    logging.info("Deleted junk pdf id=%s %s", pdf_id, filename)
                else:
                    logging.info("[dry-run] Would delete junk pdf id=%s %s", pdf_id, filename)
        if apply:
            conn.commit()
        else:
            conn.rollback()
    finally:
        cursor.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform deletes (default is dry-run only)",
    )
    parser.add_argument(
        "--delete-archive-files",
        action="store_true",
        help="Also remove matching PDFs under ARCHIVE_DIR when deleting a row",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.apply:
        logging.info("Dry-run mode (no DB changes). Pass --apply to execute.")

    conn = _connect()
    try:
        dup_stats = cleanup_copy_duplicates(conn, args.apply, args.delete_archive_files)
        junk_stats = cleanup_junk_filenames(conn, args.apply, args.delete_archive_files)
        logging.info(
            "Copy-style duplicates: candidates=%s deleted=%s skipped=%s dry_would=%s",
            dup_stats["candidates"],
            dup_stats["deleted"],
            dup_stats["skipped"],
            dup_stats["would_delete"],
        )
        logging.info(
            "Junk filenames: candidates=%s deleted=%s",
            junk_stats["candidates"],
            junk_stats["deleted"],
        )
    except mysql.connector.Error as e:
        logging.error("Database error: %s", e)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
