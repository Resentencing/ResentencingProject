"""
Script: fileconsistencycheck.py
Purpose:
    Compares filenames between the MySQL 'pdfs' table and the archived PDFs in /shared/archive_directory
    to identify missing or mismatched entries.

Output:
    - A log file named MissedEntriesCheck_YYYY-MM-DD.log
    - Saved to /home/RSCAP/mysite/logs/
    - Contains:
        * Files present in the archive but missing from the database
        * Files present in the database but missing from the archive

Schedule:
    Intended to be run daily at 2:00 AM PST (09:00 UTC) via PythonAnywhere's Tasks tab

Dependencies:
    - pymysql (installed in myvirtualenv)
"""

import os
import pymysql
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
DB_HOST = os.getenv('DB_HOST')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAME = os.getenv('DB_NAME')
TABLE_NAME = os.getenv('PDFS_TABLE', 'pdfs')
ARCHIVE_DIR = os.getenv('ARCHIVE_DIR', '/home/RSCAP/shared/archive_directory')
LOG_DIR = os.getenv('LOG_DIR', '/home/RSCAP/mysite/logs')
LOG_FILENAME = f"MissedEntriesCheck_{datetime.now().strftime('%Y-%m-%d')}.log"
LOG_PATH = os.path.join(LOG_DIR, LOG_FILENAME)

# --- Connect to the database and fetch filenames ---
def get_db_filenames():
    connection = pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT filename FROM {TABLE_NAME}")
            result = cursor.fetchall()
            return [row[0] for row in result]
    finally:
        connection.close()

# --- Get filenames from archive directory ---
def get_archive_filenames():
    return [f for f in os.listdir(ARCHIVE_DIR) if f.endswith('.pdf')]

# --- Compare and log results ---
def run_consistency_check():
    db_files = set(get_db_filenames())
    archive_files = set(get_archive_filenames())

    missing_in_db = archive_files - db_files
    missing_in_files = db_files - archive_files

    with open(LOG_PATH, 'w') as log:
        log.write("=== File Consistency Check ===\n")
        log.write(f"Timestamp: {datetime.now()}\n\n")
        log.write("Files missing in database (present in archive only):\n")
        for f in sorted(missing_in_db):
            log.write(f"- {f}\n")
        log.write("\nFiles missing in archive (present in database only):\n")
        for f in sorted(missing_in_files):
            log.write(f"- {f}\n")

    print(f"Check complete. Log saved to {LOG_PATH}")

# --- Run script ---
if __name__ == '__main__':
    run_consistency_check()
