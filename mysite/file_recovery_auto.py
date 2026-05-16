"""
Script: file_recovery_auto.py
Purpose:
    Automated version of file recovery that runs without user interaction.
    Suitable for scheduled tasks on PythonAnywhere.

Usage:
    - Run manually: python3 file_recovery_auto.py
    - Schedule to run daily after fileconsistencycheck.py
"""

import os
import pymysql
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DB_HOST = os.getenv('DB_HOST')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAME = os.getenv('DB_NAME')
ARCHIVE_DIR = os.getenv('ARCHIVE_DIR', '/home/RSCAP/shared/archive_directory')
LOG_DIR = os.getenv('LOG_DIR', '/home/RSCAP/mysite/logs')

# Match enhanced upload auto-recovery: inventory-only inserts avoid misleading
# metadata (today's date + NULL case/CDCR). Set true for legacy placeholder rows.
def _placeholder_metadata_enabled() -> bool:
    v = (os.getenv('AUTO_RECOVERY_PLACEHOLDER_METADATA') or '').lower()
    return v in {'1', 'true', 'yes'}

def get_db_filenames():
    """Get list of filenames currently in the database."""
    connection = pymysql.connect(
        host=DB_HOST,
        port=int(os.getenv('DB_PORT', 3306)),
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT filename FROM pdfs")
            result = cursor.fetchall()
            return [row[0] for row in result]
    finally:
        connection.close()

def get_archive_filenames():
    """Get list of PDF filenames in the archive directory."""
    return [f for f in os.listdir(ARCHIVE_DIR) if f.endswith('.pdf')]

def insert_file_to_db(filename):
    """Insert a file record into the database with basic information."""
    connection = pymysql.connect(
        host=DB_HOST,
        port=int(os.getenv('DB_PORT', 3306)),
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    try:
        with connection.cursor() as cursor:
            # Insert into pdfs table
            file_path = os.path.join(ARCHIVE_DIR, filename)
            cursor.execute(
                "INSERT INTO pdfs (filename, file_path) VALUES (%s, %s)",
                (filename, file_path)
            )
            
            pdf_id = cursor.lastrowid
            if _placeholder_metadata_enabled():
                cursor.execute("""
                    INSERT INTO metadata (pdf_id, date_stamped, notes)
                    VALUES (%s, %s, %s)
                """, (
                    pdf_id,
                    datetime.now().strftime('%B %d, %Y'),
                    f"Auto-recovered on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Metadata pending refresh"
                ))

            connection.commit()
            return True
    except Exception as e:
        print(f"Error inserting {filename}: {e}")
        connection.rollback()
        return False
    finally:
        connection.close()

def run_auto_recovery():
    """Automated recovery function - no user interaction required."""
    print("=== Automated File Recovery System ===")
    print(f"Timestamp: {datetime.now()}")
    
    # Get current files in database and archive
    db_files = set(get_db_filenames())
    archive_files = set(get_archive_filenames())
    
    # Find files missing from database
    missing_in_db = archive_files - db_files
    
    if not missing_in_db:
        print("✅ No files need recovery - all archive files are in the database.")
        return
    
    print(f"Found {len(missing_in_db)} files missing from database:")
    for filename in sorted(missing_in_db):
        print(f"  - {filename}")
    
    # Automatically recover files
    recovered_count = 0
    failed_count = 0
    
    for filename in sorted(missing_in_db):
        print(f"Auto-recovering: {filename}")
        if insert_file_to_db(filename):
            recovered_count += 1
            print(f"  ✅ Successfully recovered: {filename}")
        else:
            failed_count += 1
            print(f"  ❌ Failed to recover: {filename}")
    
    # Summary
    print(f"\n=== Auto-Recovery Summary ===")
    print(f"Files recovered: {recovered_count}")
    print(f"Files failed: {failed_count}")
    print(f"Total processed: {len(missing_in_db)}")
    
    # Log the recovery
    log_filename = f"AutoFileRecovery_{datetime.now().strftime('%Y-%m-%d')}.log"
    log_path = os.path.join(LOG_DIR, log_filename)
    
    with open(log_path, 'a') as log:
        log.write(f"=== Automated File Recovery Log ===\n")
        log.write(f"Timestamp: {datetime.now()}\n")
        log.write(f"Files recovered: {recovered_count}\n")
        log.write(f"Files failed: {failed_count}\n")
        log.write(f"Recovered files:\n")
        for filename in sorted(missing_in_db):
            log.write(f"  - {filename}\n")
        log.write("\n")
    
    print(f"Recovery log saved to: {log_path}")

if __name__ == '__main__':
    run_auto_recovery() 