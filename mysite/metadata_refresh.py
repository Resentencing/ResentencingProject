"""
Script: metadata_refresh.py
Purpose:
    Refreshes metadata for files that were auto-recovered with basic information.
    Re-processes PDFs through OCR and metadata extraction to get full information.

Usage:
    - Run manually: python3 metadata_refresh.py
    - Can be scheduled to run after file recovery
"""

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

def get_files_needing_refresh():
    """Get files that have basic metadata (auto-recovered) and need full metadata."""
    connection = pymysql.connect(
        host=DB_HOST,
        port=int(os.getenv('DB_PORT', 3306)),
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    
    try:
        with connection.cursor() as cursor:
            # Find files where metadata has only basic info (notes contains "Auto-recovered")
            cursor.execute("""
                SELECT p.id, p.filename, p.file_path, m.id as metadata_id
                FROM pdfs p
                JOIN metadata m ON p.id = m.pdf_id
                WHERE m.notes LIKE '%Auto-recovered%'
                AND (m.case_number IS NULL OR m.case_number = '')
                ORDER BY p.filename
            """)
            return cursor.fetchall()
    finally:
        connection.close()

def apply_filename_only_refresh(pdf_id, filename):
    """
    When OCR/tag excel-merge did not produce a row, still persist CDCR/case hints
    parsed from the archive basename (see tagextraction.filename_metadata_hints).
    """
    hints = tagextraction.filename_metadata_hints(filename)
    if not hints:
        return False
    connection = pymysql.connect(
        host=DB_HOST,
        port=int(os.getenv("DB_PORT", 3306)),
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )
    try:
        with connection.cursor() as cursor:
            parts = []
            vals = []
            if hints.get("CDCR NO"):
                parts.append("cdcr_number = %s")
                vals.append(hints["CDCR NO"])
            if hints.get("CASE NO"):
                parts.append("case_number = %s")
                vals.append(hints["CASE NO"])
            note = (
                f"Partial hints from filename on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                "(re-run refresh after Excel/CDCR updates for full merge)."
            )
            parts.append("notes = %s")
            vals.append(note)
            vals.append(pdf_id)
            sql = f"UPDATE metadata SET {', '.join(parts)} WHERE pdf_id = %s"
            cursor.execute(sql, tuple(vals))
        connection.commit()
        print(f"  📝 Filename hints applied for {filename}: {hints}")
        return True
    finally:
        connection.close()


def refresh_metadata_for_file(pdf_id, filename, file_path):
    """Refresh metadata for a single file by re-processing it."""
    print(f"Refreshing metadata for: {filename}", flush=True)
    
    temp_output_dir = f"temp_ocr_{pdf_id}"
    metadata_file = f"temp_metadata_{pdf_id}.json"
    
    try:
        # Step 1: Create a temporary directory with the PDF file
        os.makedirs(temp_output_dir, exist_ok=True)
        
        # Copy the PDF to the temp directory (since extracttext expects a directory)
        import shutil
        temp_pdf_path = os.path.join(temp_output_dir, filename)
        shutil.copy2(file_path, temp_pdf_path)
        
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
        
        # Step 5: Update the database with new metadata
        connection = pymysql.connect(
            host=DB_HOST,
            port=int(os.getenv('DB_PORT', 3306)),
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        
        try:
            with connection.cursor() as cursor:
                metadata = metadata_list[0]  # Take first result
                
                # Update metadata with full information
                cursor.execute("""
                    UPDATE metadata SET
                        date_stamped = %s,
                        judge = %s,
                        county = %s,
                        address = %s,
                        convict_name = %s,
                        cdcr_number = %s,
                        case_number = %s,
                        sentence_date = %s,
                        cohort = %s,
                        pid_no = %s,
                        institution = %s,
                        old_release_date = %s,
                        documents_printed_date = %s,
                        letter_creation_date = %s,
                        secretary_send_date = %s,
                        sec_decision = %s,
                        court_mail_date = %s,
                        court_response_date = %s,
                        resentencing_hearing_date = %s,
                        action_taken = %s,
                        days_reduced = %s,
                        years_reduced = %s,
                        cost_savings = %s,
                        notes = %s,
                        completion_date = %s,
                        post_release = %s,
                        isl_dsl = %s,
                        parole_eligibility_date = %s,
                        race = %s,
                        ethnicity = %s
                    WHERE pdf_id = %s
                """, (
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
                    f"Metadata refreshed on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    metadata.get("COMPLETION DATE"),
                    metadata.get("POST RELEASE"),
                    metadata.get("ISL DSL"),
                    metadata.get("PAROLE ELIGIBILITY DATE"),
                    metadata.get("RACE"),
                    metadata.get("ETHNICITY"),
                    pdf_id
                ))
                
                connection.commit()
                print(f"  ✅ Successfully refreshed metadata for {filename}")
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
        if refresh_metadata_for_file(pdf_id, filename, file_path):
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