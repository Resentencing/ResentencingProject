"""
PythonAnywhere Setup Script for RSCAP Data Management System
Purpose:
    Automates the setup of scheduled tasks and configuration for the data management system.

Usage:
    Run this script on PythonAnywhere to set up:
    - Daily consistency checks
    - Automated file recovery
    - Email alerts (if configured)
    - Log directory structure
"""

import os
import sys
from datetime import datetime

def create_log_directory():
    """Create the logs directory if it doesn't exist."""
    log_dir = '/home/RSCAP/mysite/logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        print(f"✅ Created log directory: {log_dir}")
    else:
        print(f"📁 Log directory already exists: {log_dir}")

def check_environment():
    """Check if environment variables are properly configured."""
    required_vars = [
        'DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_NAME',
        'ARCHIVE_DIR', 'LOG_DIR'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print("❌ Missing environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        return False
    else:
        print("✅ All required environment variables are set")
        return True

def create_scheduled_tasks_guide():
    """Create a guide for setting up scheduled tasks on PythonAnywhere."""
    guide = """
=== PythonAnywhere Scheduled Tasks Setup ===

To set up automated data management, add these tasks in your PythonAnywhere Tasks tab:

1. DAILY CONSISTENCY CHECK (2:00 AM UTC)
   Command: python3 /home/RSCAP/mysite/fileconsistencycheck.py
   Schedule: Daily at 02:00 UTC

2. AUTOMATED FILE RECOVERY (2:15 AM UTC)
   Command: python3 /home/RSCAP/mysite/file_recovery_auto.py
   Schedule: Daily at 02:15 UTC

=== Email Configuration (Optional) ===

To enable email alerts, add these to your .env file:

EMAIL_ENABLED=true
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
ALERT_EMAIL=caitlin@example.com

=== Manual Testing ===

Test the scripts manually first:

1. Test consistency check:
   python3 /home/RSCAP/mysite/fileconsistencycheck.py

2. Test file recovery:
   python3 /home/RSCAP/mysite/file_recovery_auto.py

=== Log Files ===

Check logs in: /home/RSCAP/mysite/logs/
- FileConsistencyCheck_*.log
- AutoFileRecovery_*.log
- MissedEntriesCheck_*.log

=== Dashboard Access ===

Access the dashboard at: https://yourusername.pythonanywhere.com/dashboard

"""
    
    guide_path = '/home/RSCAP/setup_guide.txt'
    with open(guide_path, 'w') as f:
        f.write(guide)
    
    print(f"📋 Setup guide saved to: {guide_path}")
    return guide

def main():
    """Main setup function."""
    print("=== RSCAP Data Management System Setup ===")
    print(f"Timestamp: {datetime.now()}")
    print()
    
    # Check environment
    if not check_environment():
        print("❌ Setup failed: Environment not properly configured")
        return False
    
    # Create log directory
    create_log_directory()
    
    # Create setup guide
    guide = create_scheduled_tasks_guide()
    
    print()
    print("=== Setup Complete ===")
    print("✅ Environment checked")
    print("✅ Log directory created")
    print("✅ Setup guide created")
    print()
    print("Next steps:")
    print("1. Review the setup guide at /home/RSCAP/setup_guide.txt")
    print("2. Configure scheduled tasks in PythonAnywhere")
    print("3. Test the scripts manually")
    print("4. Access the dashboard at /dashboard")
    
    return True

if __name__ == '__main__':
    main() 