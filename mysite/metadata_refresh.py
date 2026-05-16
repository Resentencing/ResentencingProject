"""
Script: metadata_refresh.py
Purpose:
    OCR + tag extraction for PDFs that need real metadata:

    - Placeholder rows (auto-recovered notes, empty case), or
    - Partial rows (``Partial hints from filename`` after a failed merge / fallback), or
    - Orphan ``pdfs`` rows (no ``metadata`` row at all).

    For each extracted JSON record, **upserts** by ``(pdf_id, case_number, date_stamped)``
    (NULL-safe), matching SafeUpload dedup rules—supports **multi-letter / batch PDFs**
    when ``ENABLE_BATCH_METADATA_EXPANSION`` is on (default in ``tagextraction``).

Usage:
    - Run manually: python3 metadata_refresh.py
    - Large batches: run from PA console/scheduled task (not the web button).
"""

import math
import os
import pymysql
from datetime import datetime
from dotenv import load_dotenv
import extracttext
import tagextraction
import json
import logging

# Load environment variables
load_dotenv()

# Configuration
DB_HOST = os.getenv('DB_HOST')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAME = os.getenv('DB_NAME')
ARCHIVE_DIR = os.getenv('ARCHIVE_DIR', '/home/RSCAP/shared/archive_directory')
LOG_DIR = os.getenv('LOG_DIR', './logs')

def _sanitize_for_mysql(value):
    """
    Coerce pandas/Excel NaN and numpy scalar NaN to None — PyMySQL rejects float('nan').
    Matches intent of ``dbconnector.sanitize_value`` / SafeUpload.
    """
    if value is None:
        return None
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return _sanitize_for_mysql(value.item())
    except ImportError:
        pass
    try:
        import pandas as pd

        if value is pd.NA:
            return None
        if not isinstance(value, (list, dict, str, bytes)):
            try:
                if pd.isna(value):
                    return None
            except (TypeError, ValueError):
                pass
    except ImportError:
        pass
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
    try:
        from decimal import Decimal

        if isinstance(value, Decimal) and not value.is_finite():
            return None
    except (ImportError, AttributeError):
        pass
    return value


def _resolve_open_pdf_path(filename: str, file_path: str):
    """
    Prefer DB ``file_path`` when the file exists; otherwise ``ARCHIVE_DIR/filename``.
    Some rows were inserted with a developer machine path and break on the server.
    """
    if file_path and os.path.isfile(file_path):
        return file_path, None
    fallback = os.path.join(ARCHIVE_DIR, filename)
    if os.path.isfile(fallback):
        hint = None
        if file_path and os.path.normpath(file_path) != os.path.normpath(fallback):
            hint = (
                f"using archive path (DB file_path missing or not on this host: "
                f"{file_path!r} → {fallback!r})"
            )
        return fallback, hint
    return file_path or fallback, None


def get_files_needing_refresh():
    """
    PDFs that should go through OCR + tagging:

    - Placeholder metadata (auto-recovered, no case), or
    - Filename-only hint rows (notes contain ``Partial hints from filename``), or
    - No metadata row (orphan inventory rows).
    """
    connection = pymysql.connect(
        host=DB_HOST,
        port=int(os.getenv("DB_PORT", 3306)),
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, filename, file_path, metadata_id FROM (
                    SELECT p.id, p.filename, p.file_path, m.id AS metadata_id
                    FROM pdfs p
                    INNER JOIN metadata m ON p.id = m.pdf_id
                    WHERE m.notes LIKE %s
                      AND (m.case_number IS NULL OR TRIM(m.case_number) = '')
                    UNION ALL
                    SELECT p.id, p.filename, p.file_path, m.id AS metadata_id
                    FROM pdfs p
                    INNER JOIN metadata m ON p.id = m.pdf_id
                    WHERE m.notes LIKE %s
                    UNION ALL
                    SELECT p.id, p.filename, p.file_path, NULL AS metadata_id
                    FROM pdfs p
                    LEFT JOIN metadata m ON p.id = m.pdf_id
                    WHERE m.pdf_id IS NULL
                ) AS cohort
                ORDER BY filename
                """,
                ("%Auto-recovered%", "%Partial hints from filename%"),
            )
            return cursor.fetchall()
    finally:
        connection.close()

def apply_filename_only_refresh(pdf_id, filename):
    """
    When OCR/tag excel-merge did not produce a row, still persist CDCR/case hints
    parsed from the archive basename (see tagextraction.filename_metadata_hints).
    Inserts a minimal metadata row if none exists yet.
    """
    hints = tagextraction.filename_metadata_hints(filename)
    if not hints:
        return False
    note = (
        f"Partial hints from filename on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        "(re-run refresh after Excel/CDCR updates for full merge)."
    )
    connection = pymysql.connect(
        host=DB_HOST,
        port=int(os.getenv("DB_PORT", 3306)),
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM metadata WHERE pdf_id = %s LIMIT 1", (pdf_id,))
            exists = cursor.fetchone()
            if exists:
                parts = []
                vals = []
                if hints.get("CDCR NO"):
                    parts.append("cdcr_number = %s")
                    vals.append(hints["CDCR NO"])
                if hints.get("CASE NO"):
                    parts.append("case_number = %s")
                    vals.append(hints["CASE NO"])
                parts.append("notes = %s")
                vals.append(note)
                vals.append(pdf_id)
                sql = f"UPDATE metadata SET {', '.join(parts)} WHERE pdf_id = %s"
                cursor.execute(sql, tuple(vals))
            else:
                cursor.execute(
                    """
                    INSERT INTO metadata (pdf_id, cdcr_number, case_number, notes)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        pdf_id,
                        hints.get("CDCR NO"),
                        hints.get("CASE NO"),
                        note,
                    ),
                )
        connection.commit()
        print(f"  📝 Filename hints applied for {filename}: {hints}")
        return True
    finally:
        connection.close()


_FULL_METADATA_COLUMNS = (
    "date_stamped, judge, county, address, convict_name, cdcr_number, case_number, "
    "sentence_date, cohort, pid_no, institution, old_release_date, documents_printed_date, "
    "letter_creation_date, secretary_send_date, sec_decision, court_mail_date, "
    "court_response_date, resentencing_hearing_date, action_taken, days_reduced, "
    "years_reduced, cost_savings, notes, completion_date, post_release, isl_dsl, "
    "parole_eligibility_date, race, ethnicity"
)


def _delete_partial_filename_hint_rows(cursor, pdf_id: int) -> int:
    """Remove filename-only fallback metadata so a full Excel merge row can replace it cleanly."""
    cursor.execute(
        """
        DELETE FROM metadata
        WHERE pdf_id = %s AND notes LIKE %s
        """,
        (pdf_id, "%Partial hints from filename%"),
    )
    return cursor.rowcount


def _delete_auto_recovered_placeholders(cursor, pdf_id: int) -> int:
    """Remove shell metadata rows for this PDF so real batch rows can replace them."""
    cursor.execute(
        """
        DELETE FROM metadata
        WHERE pdf_id = %s
          AND notes LIKE %s
          AND (case_number IS NULL OR TRIM(case_number) = '')
        """,
        (pdf_id, "%Auto-recovered%"),
    )
    return cursor.rowcount


def _upsert_all_extracted_metadata(cursor, pdf_id: int, metadata_list: list, per_file_note: str) -> tuple:
    """
    Insert or update one DB row per JSON object. Match key: pdf_id + case_number + date_stamped (NULL-safe).
    Returns (insert_count, update_count).
    """
    inserted = 0
    updated = 0
    set_clause = """
        date_stamped = %s, judge = %s, county = %s, address = %s,
        convict_name = %s, cdcr_number = %s, case_number = %s, sentence_date = %s,
        cohort = %s, pid_no = %s, institution = %s, old_release_date = %s,
        documents_printed_date = %s, letter_creation_date = %s,
        secretary_send_date = %s, sec_decision = %s, court_mail_date = %s,
        court_response_date = %s, resentencing_hearing_date = %s, action_taken = %s,
        days_reduced = %s, years_reduced = %s, cost_savings = %s, notes = %s,
        completion_date = %s, post_release = %s, isl_dsl = %s,
        parole_eligibility_date = %s, race = %s, ethnicity = %s
    """
    for i, metadata in enumerate(metadata_list):
        note = per_file_note if len(metadata_list) == 1 else f"{per_file_note} (entry {i + 1}/{len(metadata_list)})"
        row_vals = _full_metadata_tuple(metadata, note)
        case_no = _sanitize_for_mysql(metadata.get("CASE NO"))
        date_st = _sanitize_for_mysql(metadata.get("DATE STAMPED"))
        cursor.execute(
            """
            SELECT id FROM metadata
            WHERE pdf_id = %s AND case_number <=> %s AND date_stamped <=> %s
            LIMIT 1
            """,
            (pdf_id, case_no, date_st),
        )
        found = cursor.fetchone()
        if found:
            meta_id = found[0]
            cursor.execute(
                f"UPDATE metadata SET {set_clause} WHERE id = %s",
                row_vals + (meta_id,),
            )
            updated += 1
        else:
            placeholders = ", ".join(["%s"] * (1 + len(row_vals)))
            cursor.execute(
                f"""
                INSERT INTO metadata (pdf_id, {_FULL_METADATA_COLUMNS})
                VALUES ({placeholders})
                """,
                (pdf_id,) + row_vals,
            )
            inserted += 1
    return inserted, updated


def _full_metadata_tuple(metadata: dict, notes: str):
    raw = (
        metadata.get("DATE STAMPED"),
        metadata.get("JUDGE"),
        metadata.get("COUNTY"),
        metadata.get("ADDRESS"),
        metadata.get("CNAME"),
        metadata.get("CDCR NO"),
        metadata.get("CASE NO"),
        metadata.get("SENTENCE DATE"),
        metadata.get("COHORT"),
        metadata.get("PID NO"),
        metadata.get("INSTITUTION"),
        metadata.get("OLD RELEASE DATE"),
        metadata.get("DOCUMENTS PRINTED DATE"),
        metadata.get("LETTER CREATION DATE"),
        metadata.get("SECRETARY SEND DATE"),
        metadata.get("SEC DECISION"),
        metadata.get("COURT MAIL DATE"),
        metadata.get("COURT RESPONSE DATE"),
        metadata.get("RESENTENCING HEARING DATE"),
        metadata.get("ACTION TAKEN"),
        metadata.get("DAYS REDUCED"),
        metadata.get("YEARS REDUCED"),
        metadata.get("COST SAVINGS"),
        notes,
        metadata.get("COMPLETION DATE"),
        metadata.get("POST RELEASE"),
        metadata.get("ISL DSL"),
        metadata.get("PAROLE ELIGIBILITY DATE"),
        metadata.get("RACE"),
        metadata.get("ETHNICITY"),
    )
    return tuple(_sanitize_for_mysql(v) for v in raw)


def refresh_metadata_for_file(pdf_id, filename, file_path, metadata_row_exists=True):
    """OCR + tag; upsert every JSON record (batch-PDF safe). Placeholder shells removed when replacing."""
    print(f"Refreshing metadata for: {filename}", flush=True)
    
    temp_output_dir = f"temp_ocr_{pdf_id}"
    metadata_file = f"temp_metadata_{pdf_id}.json"
    
    try:
        # Step 1: Create a temporary directory with the PDF file
        os.makedirs(temp_output_dir, exist_ok=True)
        
        # Copy the PDF to the temp directory (since extracttext expects a directory)
        import shutil
        open_path, path_hint = _resolve_open_pdf_path(filename, file_path)
        if path_hint:
            print(f"  ℹ️  {path_hint}", flush=True)
        if not open_path or not os.path.isfile(open_path):
            print(
                f"  ❌ PDF not found for {filename} (tried DB path and "
                f"{os.path.join(ARCHIVE_DIR, filename)!r})",
                flush=True,
            )
            if apply_filename_only_refresh(pdf_id, filename):
                return True
            return False

        temp_pdf_path = os.path.join(temp_output_dir, filename)
        shutil.copy2(open_path, temp_pdf_path)
        
        # Step 2: Extract text from PDF using your existing OCR pipeline
        extracttext.extract_text_from_pdfs(temp_output_dir, temp_output_dir)
        
        # Step 3: Extract metadata from text
        tagextraction.extract_metadata_from_text_files(temp_output_dir, metadata_file)
        
        # Step 4: Load the extracted metadata
        if not os.path.exists(metadata_file):
            print(f"  ⚠️  No metadata file created for {filename}")
            if apply_filename_only_refresh(pdf_id, filename):
                return True
            return False
            
        with open(metadata_file, 'r') as f:
            metadata_list = json.load(f)
        
        if not metadata_list:
            print(f"  ⚠️  No metadata extracted for {filename}")
            if apply_filename_only_refresh(pdf_id, filename):
                return True
            return False
        
        # Step 5: Upsert all extracted rows (same rules as SafeUpload: key = pdf + case + date_stamped)
        connection = pymysql.connect(
            host=DB_HOST,
            port=int(os.getenv('DB_PORT', 3306)),
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )

        try:
            with connection.cursor() as cursor:
                if metadata_row_exists:
                    removed_ph = _delete_partial_filename_hint_rows(cursor, pdf_id)
                    if removed_ph:
                        print(
                            f"  🗑 Removed {removed_ph} partial filename-hint row(s) for {filename}",
                            flush=True,
                        )
                    removed = _delete_auto_recovered_placeholders(cursor, pdf_id)
                    if removed:
                        print(f"  🗑 Removed {removed} auto-recovered placeholder row(s) for {filename}", flush=True)

                refreshed_note = f"Metadata refreshed on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                ins, upd = _upsert_all_extracted_metadata(
                    cursor, pdf_id, metadata_list, refreshed_note
                )
                connection.commit()
                print(
                    f"  ✅ {filename}: inserted {ins}, updated {upd} metadata row(s) "
                    f"({len(metadata_list)} from extraction)",
                    flush=True,
                )
                return True

        finally:
            connection.close()
            
    except Exception as e:
        print(f"  ❌ Error refreshing metadata for {filename}: {e}")
        if apply_filename_only_refresh(pdf_id, filename):
            return True
        return False
    finally:
        # Clean up temporary files
        if os.path.exists(temp_output_dir):
            import shutil
            shutil.rmtree(temp_output_dir)
        if os.path.exists(metadata_file):
            os.remove(metadata_file)

def run_metadata_refresh():
    """Main function to refresh metadata for all files that need it."""
    print("=== Metadata Refresh System ===")
    print(f"Timestamp: {datetime.now()}")
    
    # Get files needing refresh
    files_to_refresh = get_files_needing_refresh()
    
    if not files_to_refresh:
        print("✅ No files need metadata refresh!")
        return
    
    print(f"Found {len(files_to_refresh)} files needing metadata refresh:")
    for file_info in files_to_refresh:
        print(f"  - {file_info[1]}")
    
    # Refresh metadata for each file
    successful = 0
    failed = 0
    
    for n, (pdf_id, filename, file_path, metadata_id) in enumerate(files_to_refresh, start=1):
        print(f"[{n}/{len(files_to_refresh)}] …", flush=True)
        has_row = metadata_id is not None
        if refresh_metadata_for_file(pdf_id, filename, file_path, metadata_row_exists=has_row):
            successful += 1
        else:
            failed += 1
    
    # Summary
    print(f"\n=== Metadata Refresh Summary ===")
    print(f"Files successfully refreshed: {successful}")
    print(f"Files failed: {failed}")
    print(f"Total processed: {len(files_to_refresh)}")
    
    # Log the refresh
    log_filename = f"MetadataRefresh_{datetime.now().strftime('%Y-%m-%d')}.log"
    log_path = os.path.join(LOG_DIR, log_filename)
    
    # Ensure log directory exists
    os.makedirs(LOG_DIR, exist_ok=True)
    
    with open(log_path, 'a') as log:
        log.write(f"=== Metadata Refresh Log ===\n")
        log.write(f"Timestamp: {datetime.now()}\n")
        log.write(f"Files refreshed: {successful}\n")
        log.write(f"Files failed: {failed}\n")
        log.write(f"Refreshed files:\n")
        for file_info in files_to_refresh:
            log.write(f"  - {file_info[1]}\n")
        log.write("\n")
    
    print(f"Refresh log saved to: {log_path}")

if __name__ == '__main__':
    run_metadata_refresh() 