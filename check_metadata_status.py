#!/usr/bin/env python3
"""
Script to check the current metadata status of all files in the database.
"""

import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

def check_metadata_status():
    """Check the metadata status of all files in the database."""
    
    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 3306)),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )
    
    try:
        with connection.cursor() as cursor:
            # Get total files
            cursor.execute("SELECT COUNT(*) FROM pdfs")
            total_files = cursor.fetchone()[0]
            
            # Get files with metadata
            cursor.execute("SELECT COUNT(*) FROM pdfs p JOIN metadata m ON p.id = m.pdf_id")
            with_metadata = cursor.fetchone()[0]
            
            # Get files with basic metadata (auto-recovered)
            cursor.execute("""
                SELECT COUNT(*) FROM pdfs p 
                JOIN metadata m ON p.id = m.pdf_id 
                WHERE m.notes LIKE '%Auto-recovered%'
            """)
            auto_recovered = cursor.fetchone()[0]
            
            # Get files with refreshed metadata
            cursor.execute("""
                SELECT COUNT(*) FROM pdfs p 
                JOIN metadata m ON p.id = m.pdf_id 
                WHERE m.notes LIKE '%Metadata refreshed%'
            """)
            refreshed = cursor.fetchone()[0]
            
            # Get files with full metadata (have case_number and cdcr_number)
            cursor.execute("""
                SELECT COUNT(*) FROM pdfs p 
                JOIN metadata m ON p.id = m.pdf_id 
                WHERE m.case_number IS NOT NULL 
                AND m.case_number != '' 
                AND m.cdcr_number IS NOT NULL 
                AND m.cdcr_number != ''
            """)
            full_metadata = cursor.fetchone()[0]
            
            # Get files missing metadata completely
            cursor.execute("""
                SELECT COUNT(*) FROM pdfs p 
                LEFT JOIN metadata m ON p.id = m.pdf_id 
                WHERE m.pdf_id IS NULL
            """)
            missing_metadata = cursor.fetchone()[0]
            
            # Get sample of files with different metadata statuses
            cursor.execute("""
                SELECT p.filename, m.case_number, m.cdcr_number, m.notes
                FROM pdfs p 
                JOIN metadata m ON p.id = m.pdf_id 
                WHERE m.notes LIKE '%Auto-recovered%'
                LIMIT 5
            """)
            auto_recovered_samples = cursor.fetchall()
            
            cursor.execute("""
                SELECT p.filename, m.case_number, m.cdcr_number, m.notes
                FROM pdfs p 
                JOIN metadata m ON p.id = m.pdf_id 
                WHERE m.notes LIKE '%Metadata refreshed%'
                LIMIT 5
            """)
            refreshed_samples = cursor.fetchall()
            
            print("=== METADATA STATUS REPORT ===")
            print(f"Total files in database: {total_files}")
            print(f"Files with any metadata: {with_metadata}")
            print(f"Files with auto-recovered metadata: {auto_recovered}")
            print(f"Files with refreshed metadata: {refreshed}")
            print(f"Files with full metadata (case_number + cdcr_number): {full_metadata}")
            print(f"Files missing metadata completely: {missing_metadata}")
            
            print(f"\n=== SAMPLE AUTO-RECOVERED FILES ===")
            for filename, case_num, cdcr_num, notes in auto_recovered_samples:
                print(f"  {filename}")
                print(f"    Case Number: {case_num or 'None'}")
                print(f"    CDCR Number: {cdcr_num or 'None'}")
                print(f"    Notes: {notes}")
                print()
            
            print(f"=== SAMPLE REFRESHED FILES ===")
            for filename, case_num, cdcr_num, notes in refreshed_samples:
                print(f"  {filename}")
                print(f"    Case Number: {case_num or 'None'}")
                print(f"    CDCR Number: {cdcr_num or 'None'}")
                print(f"    Notes: {notes}")
                print()
            
            # Summary
            print("=== SUMMARY ===")
            if full_metadata == total_files:
                print("✅ ALL FILES HAVE FULL METADATA!")
            elif with_metadata == total_files:
                print("⚠️  All files have basic metadata, but some may need full extraction")
            else:
                print("❌ Some files are missing metadata completely")
                
    finally:
        connection.close()

if __name__ == '__main__':
    check_metadata_status() 