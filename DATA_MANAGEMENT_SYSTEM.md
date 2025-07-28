# RSCAP Data Management System

## Overview

A comprehensive data management system for the RSCAP project that ensures file-database synchronization, provides recovery mechanisms, and offers a user-friendly dashboard for monitoring system health.

## 🎯 Problem Solved

The system addresses these key issues:
- **File-Database Desynchronization**: PDFs exist in archive but missing from database
- **Metadata Issues**: Incomplete or missing metadata records
- **Silent Failures**: Duplicate entries or incomplete uploads
- **Poor Visibility**: Difficult to view uploaded files and system status
- **No Monitoring**: Lack of system responsiveness indicators

## 🏗️ System Components

### 1. File Consistency Check
**Files**: `fileconsistencycheck.py`, `enhanced_consistency_check.py`

**Features**:
- Compares database records with actual archive files
- Identifies missing files in database vs archive
- Detailed logging with timestamps
- Email alerts for mismatches (optional)
- Runs automatically every 24 hours

### 2. Recovery System
**Files**: `file_recovery.py`, `file_recovery_auto.py`

**Features**:
- Automatically re-inserts missing files into database
- Creates basic metadata entries with timestamps
- Interactive and automated versions
- Logs all recovery actions

### 3. Enhanced File Viewer
**Files**: `OCRWebApp.py` (updated), `templates/fileviewer.html`

**Features**:
- Sort by filename, case number, CDCR number, date
- Search across all fields
- Download functionality
- Real-time filtering

### 4. Dashboard System
**Files**: `templates/dashboard.html`, `templates/missing_metadata.html`, `templates/recent_uploads.html`, `templates/consistency_report.html`

**Features**:
- Real-time statistics (total files, metadata status)
- Quick action buttons
- Recent activity tracking
- System status monitoring
- Missing metadata identification

## 📊 Dashboard Features

### Statistics Cards
- **Total Files**: Count of all files in database
- **With Metadata**: Files that have complete metadata
- **Missing Metadata**: Files needing metadata attention
- **Last Check**: Timestamp of last consistency check

### Quick Actions
- **View All Files**: Access the file viewer
- **Missing Metadata**: Show files needing metadata
- **Recent Uploads**: Latest 20 uploaded files
- **Consistency Report**: Latest system check results

### System Status
- **Database**: Connection status
- **Archive**: File system accessibility
- **Sync Status**: Synchronization health

## 🔧 Setup Instructions

### 1. Environment Configuration
Add these to your `.env` file:
```bash
# Required
DB_HOST=RSCAP.mysql.pythonanywhere-services.com
DB_USER=RSCAP
DB_PASSWORD=your_password
DB_NAME=RSCAP$RSCAPTester
ARCHIVE_DIR=/home/RSCAP/shared/archive_directory
LOG_DIR=/home/RSCAP/mysite/logs

# Optional (for email alerts)
EMAIL_ENABLED=false
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
ALERT_EMAIL=caitlin@example.com
```

### 2. PythonAnywhere Setup
Run the setup script:
```bash
python3 /home/RSCAP/mysite/setup_pythonanywhere.py
```

### 3. Scheduled Tasks
Configure these tasks in PythonAnywhere:

**Daily Consistency Check (2:00 AM UTC)**
```bash
python3 /home/RSCAP/mysite/enhanced_consistency_check.py
```

**Automated File Recovery (2:15 AM UTC)**
```bash
python3 /home/RSCAP/mysite/file_recovery_auto.py
```

**Basic Consistency Check (3:00 AM UTC)**
```bash
python3 /home/RSCAP/mysite/fileconsistencycheck.py
```

## 📁 File Structure

```
mysite/
├── OCRWebApp.py                    # Main Flask app (updated)
├── fileconsistencycheck.py         # Basic consistency check
├── enhanced_consistency_check.py   # Enhanced check with email alerts
├── file_recovery.py               # Interactive recovery
├── file_recovery_auto.py          # Automated recovery
├── setup_pythonanywhere.py        # Setup script
├── templates/
│   ├── dashboard.html             # Main dashboard
│   ├── missing_metadata.html      # Missing metadata view
│   ├── recent_uploads.html        # Recent uploads view
│   ├── consistency_report.html    # Report viewer
│   └── fileviewer.html           # Enhanced file viewer
└── logs/                         # Log directory
    ├── EnhancedConsistencyCheck_*.log
    ├── AutoFileRecovery_*.log
    └── MissedEntriesCheck_*.log
```

## 🚀 Usage

### Manual Testing
```bash
# Test consistency check
python3 /home/RSCAP/mysite/enhanced_consistency_check.py

# Test file recovery
python3 /home/RSCAP/mysite/file_recovery_auto.py

# Run setup
python3 /home/RSCAP/mysite/setup_pythonanywhere.py
```

### Web Interface
- **Dashboard**: `/dashboard` - System overview and statistics
- **File Viewer**: `/fileviewer` - Browse and search all files
- **Missing Metadata**: `/missing_metadata` - Files needing attention
- **Recent Uploads**: `/recent_uploads` - Latest uploads
- **Consistency Report**: `/consistency_report` - Latest check results

## 📈 Benefits

### For Caitlin (Project Manager)
- **Real-time Visibility**: See system health at a glance
- **Proactive Monitoring**: Email alerts for issues
- **Easy File Management**: Sort, search, and download files
- **Issue Identification**: Quickly spot missing metadata

### For System Health
- **Automated Recovery**: Self-healing system
- **Comprehensive Logging**: Full audit trail
- **Scheduled Maintenance**: Daily consistency checks
- **Error Prevention**: Catch issues before they become problems

### For Data Integrity
- **File-Database Sync**: Ensures consistency
- **Metadata Tracking**: Monitors completeness
- **Recovery Mechanisms**: Automatic problem resolution
- **Backup Systems**: Multiple consistency check methods

## 🔍 Monitoring

### Log Files
- **EnhancedConsistencyCheck_*.log**: Detailed consistency reports
- **AutoFileRecovery_*.log**: Recovery action logs
- **MissedEntriesCheck_*.log**: Basic consistency logs

### Dashboard Metrics
- File counts and metadata status
- System connection health
- Recent activity tracking
- Synchronization status

### Email Alerts (Optional)
- Immediate notification of issues
- Detailed problem descriptions
- Actionable recommendations

## 🛠️ Troubleshooting

### Common Issues
1. **Database Connection Failed**: Check `.env` configuration
2. **Archive Directory Not Found**: Verify `ARCHIVE_DIR` path
3. **Email Alerts Not Working**: Check SMTP configuration
4. **Scheduled Tasks Not Running**: Verify PythonAnywhere task setup

### Manual Recovery
```bash
# Check system status
python3 /home/RSCAP/mysite/enhanced_consistency_check.py

# Recover missing files
python3 /home/RSCAP/mysite/file_recovery_auto.py

# View logs
ls -la /home/RSCAP/mysite/logs/
```

## 🎉 Success Metrics

- **Zero Data Loss**: All archive files have database records
- **Complete Metadata**: All files have proper metadata
- **Real-time Monitoring**: Issues detected within 24 hours
- **Automated Recovery**: Self-healing system reduces manual intervention
- **User Satisfaction**: Easy-to-use dashboard for file management

This system transforms the RSCAP project from a manual, error-prone process into a robust, automated, and user-friendly data management solution. 