# Database Quick Reference Guide

## 📊 **Table Structure Overview**

### **📁 pdfs Table**
| Column | Type | Purpose | Index |
|--------|------|---------|-------|
| `id` | INT | Primary key | ✅ |
| `filename` | VARCHAR(255) | PDF filename | ✅ |
| `file_path` | VARCHAR(500) | Full file path | ✅ |

### **📋 metadata Table**
| Column | Type | Purpose | Index |
|--------|------|---------|-------|
| `id` | INT | Primary key | ✅ |
| `pdf_id` | INT | Foreign key to pdfs | ✅ |
| `date_stamped` | VARCHAR(50) | Letter date | ✅ |
| `judge` | VARCHAR(255) | Judge name | ✅ |
| `county` | VARCHAR(255) | County | ✅ |
| `address` | TEXT | Court address | ❌ |
| `convict_name` | VARCHAR(255) | Person name | ✅ |
| `cdcr_number` | VARCHAR(50) | CDCR ID | ✅ |
| `case_number` | VARCHAR(50) | Case number | ✅ |
| `sentence_date` | VARCHAR(50) | Original sentence date | ❌ |
| `cohort` | VARCHAR(255) | Cohort group | ❌ |
| `pid_no` | VARCHAR(50) | PID number | ❌ |
| `institution` | VARCHAR(255) | Prison facility | ❌ |
| `old_release_date` | VARCHAR(50) | Original release date | ❌ |
| `documents_printed_date` | VARCHAR(50) | Documents printed | ❌ |
| `letter_creation_date` | VARCHAR(50) | Letter created | ❌ |
| `secretary_send_date` | VARCHAR(50) | Secretary sent | ❌ |
| `sec_decision` | VARCHAR(255) | Secretary decision | ❌ |
| `court_mail_date` | VARCHAR(50) | Court mailed | ❌ |
| `court_response_date` | VARCHAR(50) | Court responded | ❌ |
| `resentencing_hearing_date` | VARCHAR(50) | Hearing date | ❌ |
| `action_taken` | VARCHAR(255) | Action taken | ✅ |
| `days_reduced` | INT | Days reduced | ❌ |
| `years_reduced` | INT | Years reduced | ❌ |
| `cost_savings` | DECIMAL(10,2) | Cost savings | ❌ |
| `notes` | TEXT | Notes | ❌ |
| `completion_date` | VARCHAR(50) | Completion date | ❌ |
| `post_release` | VARCHAR(255) | Post-release status | ❌ |
| `isl_dsl` | VARCHAR(50) | ISL/DSL status | ❌ |
| `parole_eligibility_date` | VARCHAR(50) | Parole date | ❌ |
| `race` | VARCHAR(100) | Race | ✅ |
| `ethnicity` | VARCHAR(100) | Ethnicity | ✅ |

### **📄 text_files Table**
| Column | Type | Purpose | Index |
|--------|------|---------|-------|
| `id` | INT | Primary key | ✅ |
| `pdf_id` | INT | Foreign key to pdfs | ✅ |
| `text_file_path` | VARCHAR(500) | Text file path | ✅ |

---

## 🔍 **Common Queries**

### **Basic Data Retrieval**
```sql
-- Get all files with metadata
SELECT p.filename, m.date_stamped, m.judge, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
ORDER BY p.filename;

-- Get files missing metadata
SELECT p.filename, p.file_path
FROM pdfs p
LEFT JOIN metadata m ON p.id = m.pdf_id
WHERE m.pdf_id IS NULL;
```

### **Search by Specific Fields**
```sql
-- By judge
SELECT p.filename, m.date_stamped, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.judge LIKE '%Schuur%';

-- By county
SELECT p.filename, m.judge, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.county = 'Los Angeles';

-- By CDCR number
SELECT p.filename, m.date_stamped, m.judge, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.cdcr_number = 'G46407';

-- By case number
SELECT p.filename, m.date_stamped, m.judge, m.convict_name, m.cdcr_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.case_number = 'VA106941-02';
```

### **Date Range Queries**
```sql
-- By date range (text format)
SELECT p.filename, m.judge, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.date_stamped >= 'July 1, 2018'
AND m.date_stamped <= 'July 31, 2018'
ORDER BY m.date_stamped;
```

### **Action and Outcome Queries**
```sql
-- By action taken
SELECT p.filename, m.date_stamped, m.judge, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.action_taken = 'Approved';

-- By race/ethnicity
SELECT p.filename, m.date_stamped, m.judge, m.convict_name, m.race, m.ethnicity
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.race = 'Hispanic';
```

---

## 📈 **Data Analysis Queries**

### **Counts and Statistics**
```sql
-- Count files by judge
SELECT m.judge, COUNT(*) as file_count
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
GROUP BY m.judge
ORDER BY file_count DESC;

-- Count files by county
SELECT m.county, COUNT(*) as file_count
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
GROUP BY m.county
ORDER BY file_count DESC;

-- Count files by action taken
SELECT m.action_taken, COUNT(*) as file_count
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
GROUP BY m.action_taken
ORDER BY file_count DESC;

-- Count files by race
SELECT m.race, COUNT(*) as file_count
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
GROUP BY m.race
ORDER BY file_count DESC;
```

### **Summary Statistics**
```sql
-- Total files with metadata
SELECT COUNT(*) as total_files_with_metadata
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id;

-- Files missing metadata
SELECT COUNT(*) as files_missing_metadata
FROM pdfs p
LEFT JOIN metadata m ON p.id = m.pdf_id
WHERE m.pdf_id IS NULL;

-- Total cost savings
SELECT SUM(cost_savings) as total_cost_savings
FROM metadata
WHERE cost_savings IS NOT NULL;
```

---

## 🔧 **Maintenance Queries**

### **Data Integrity Checks**
```sql
-- Find duplicate PDF entries
SELECT filename, COUNT(*) as count
FROM pdfs
GROUP BY filename
HAVING COUNT(*) > 1;

-- Find orphaned metadata (no PDF)
SELECT m.id, m.pdf_id
FROM metadata m
LEFT JOIN pdfs p ON m.pdf_id = p.id
WHERE p.id IS NULL;

-- Find PDFs without metadata
SELECT p.id, p.filename
FROM pdfs p
LEFT JOIN metadata m ON p.id = m.pdf_id
WHERE m.pdf_id IS NULL;
```

### **Cleanup Operations**
```sql
-- Clean up orphaned metadata
DELETE m FROM metadata m
LEFT JOIN pdfs p ON m.pdf_id = p.id
WHERE p.id IS NULL;

-- Remove duplicate PDF entries (keep first)
DELETE p1 FROM pdfs p1
INNER JOIN pdfs p2
WHERE p1.id > p2.id AND p1.filename = p2.filename;
```

---

## 🔗 **Connection Details**

### **Local Development (SSH Tunnel)**
```python
DB_HOST = '127.0.0.1'
DB_PORT = 3307
DB_USER = 'RSCAP'
DB_NAME = 'RSCAP$RSCAPTester'
```

### **Production (PythonAnywhere)**
```python
DB_HOST = 'RSCAP.mysql.pythonanywhere-services.com'
DB_PORT = 3306
DB_USER = 'RSCAP'
DB_NAME = 'RSCAP$RSCAPTester'
```

---

## 🤖 **AI Query Integration**

### **Supported Table References**
- `pdfs` (columns: `id`, `filename`, `file_path`)
- `metadata` (all columns listed above)

### **AI Query Examples**
- "How many cases are in the database?"
- "Which judge presided over case RIF102091?"
- "What is the success rate of resentencing?"
- "Show me all cases from Los Angeles County"

### **AI Query Restrictions**
- Only `SELECT`, `SHOW`, `DESCRIBE`, or `EXPLAIN` queries
- No `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, or `CREATE`
- Uses `LIMIT 20` for listing results
- Avoids word "Convict" (uses "Incarcerated person(s)")

---

## 📋 **Automated Processes**

### **Daily Consistency Check**
- **Script:** `fileconsistencycheck.py`
- **Purpose:** Validates database-archive synchronization
- **Schedule:** Daily at 9:01 AM
- **Output:** Log file in `/home/RSCAP/mysite/logs/`

### **File Recovery System**
- **Script:** `file_recovery_auto.py`
- **Purpose:** Auto-recover missing files
- **Trigger:** After consistency check
- **Action:** Creates basic database entries

### **Metadata Refresh**
- **Script:** `metadata_refresh.py`
- **Purpose:** Re-process files with basic metadata
- **Trigger:** Manual or scheduled
- **Action:** Full OCR re-processing

---

## 🚨 **Troubleshooting**

### **Common Issues**
1. **Connection Refused:** Check SSH tunnel (local) or credentials (production)
2. **Duplicate Entry:** Use enhanced duplicate detection
3. **Missing Metadata:** Run consistency check and recovery
4. **Slow Queries:** Add appropriate indexes

### **Debug Commands**
```bash
# Test database connection
python3 test_db_connection.py

# Check schema
python3 check_schema.py

# Run consistency check
python3 mysite/fileconsistencycheck.py
```

---

## 📚 **Related Files**
- `DATABASE_SCHEMA.sql` - Complete schema documentation
- `mysite/OCRWebApp.py` - Main application with database routes
- `mysite/dbconnector.py` - Database connection and upload functions
- `mysite/fileconsistencycheck.py` - Basic consistency checking
- `mysite/fileconsistencycheck.py` - Enhanced consistency checking with email alerts
- `mysite/file_recovery_auto.py` - Automated file recovery
- `mysite/metadata_refresh.py` - Metadata refresh system

---

*Last updated: 2025-07-28* 