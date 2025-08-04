"""
File Consistency Check with Email Alerts
Purpose:
    Comprehensive validation of file-database synchronization with email notifications.
    Runs automatically every 24 hours on PythonAnywhere.

Features:
    - Compares database records with actual files
    - Sends email alerts for mismatches
    - Detailed logging with timestamps
    - Recovery option for missing database entries
"""

import os
import pymysql
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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

# Email configuration (optional)
EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'false').lower() == 'true'
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
ALERT_EMAIL = os.getenv('ALERT_EMAIL', 'caitlin@example.com')

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
    if not os.path.exists(ARCHIVE_DIR):
        return []
    return [f for f in os.listdir(ARCHIVE_DIR) if f.endswith('.pdf')]

def send_email_alert(subject, body):
    """Send email alert if email is configured."""
    if not EMAIL_ENABLED or not EMAIL_USER or not EMAIL_PASSWORD:
        print("Email alerts not configured. Skipping email notification.")
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = ALERT_EMAIL
        msg['Subject'] = f"[RSCAP Alert] {subject}"
        
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Email alert sent to {ALERT_EMAIL}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email alert: {e}")
        return False

def run_consistency_check():
    """File consistency check with email alerts."""
    timestamp = datetime.now()
    print("=== File Consistency Check ===")
    print(f"Timestamp: {timestamp}")
    
    # Get current files in database and archive
    db_files = set(get_db_filenames())
    archive_files = set(get_archive_filenames())
    
    # Find discrepancies
    missing_in_db = archive_files - db_files
    missing_in_archive = db_files - archive_files
    
    # Prepare report
    report_lines = []
    report_lines.append("=== File Consistency Check ===")
    report_lines.append(f"Timestamp: {timestamp}")
    report_lines.append(f"Database files: {len(db_files)}")
    report_lines.append(f"Archive files: {len(archive_files)}")
    report_lines.append("")
    
    # Check for issues
    has_issues = len(missing_in_db) > 0 or len(missing_in_archive) > 0
    
    if not has_issues:
        report_lines.append("✅ All files are synchronized!")
        print("✅ All files are synchronized!")
    else:
        report_lines.append("⚠️  Synchronization issues found:")
        print("⚠️  Synchronization issues found:")
        
        if missing_in_db:
            report_lines.append(f"\nFiles missing in database ({len(missing_in_db)}):")
            print(f"\nFiles missing in database ({len(missing_in_db)}):")
            for filename in sorted(missing_in_db):
                report_lines.append(f"  - {filename}")
                print(f"  - {filename}")
        
        if missing_in_archive:
            report_lines.append(f"\nFiles missing in archive ({len(missing_in_archive)}):")
            print(f"\nFiles missing in archive ({len(missing_in_archive)}):")
            for filename in sorted(missing_in_archive):
                report_lines.append(f"  - {filename}")
                print(f"  - {filename}")
    
    # Save detailed report
    report_filename = f"FileConsistencyCheck_{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}.log"
    report_path = os.path.join(LOG_DIR, report_filename)
    
    with open(report_path, 'w') as report:
        report.write('\n'.join(report_lines))
        report.write(f"\n\nDetailed Analysis:")
        report.write(f"\n- Total database files: {len(db_files)}")
        report.write(f"\n- Total archive files: {len(archive_files)}")
        report.write(f"\n- Files missing in DB: {len(missing_in_db)}")
        report.write(f"\n- Files missing in archive: {len(missing_in_archive)}")
        report.write(f"\n- Synchronization status: {'✅ OK' if not has_issues else '❌ ISSUES FOUND'}")
    
    print(f"Detailed report saved to: {report_path}")
    
    # Send email alert if issues found
    if has_issues and EMAIL_ENABLED:
        email_body = f"""
RSCAP File Consistency Check Alert

Timestamp: {timestamp}

Issues Found:
- Files missing in database: {len(missing_in_db)}
- Files missing in archive: {len(missing_in_archive)}

Missing in Database:
{chr(10).join(f"- {f}" for f in sorted(missing_in_db)) if missing_in_db else "- None"}

Missing in Archive:
{chr(10).join(f"- {f}" for f in sorted(missing_in_archive)) if missing_in_archive else "- None"}

Please check the detailed report at: {report_path}
        """
        
        send_email_alert("File Synchronization Issues Detected", email_body.strip())
    
    return has_issues

if __name__ == '__main__':
    run_consistency_check() 