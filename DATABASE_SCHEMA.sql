-- =====================================================
-- DATABASE SCHEMA DOCUMENTATION
-- =====================================================
-- 
-- This file contains the complete database schema for the
-- OCR Resentencing Project database.
--
-- Tables: pdfs, metadata, text_files
-- Created: 2025-07-28
-- Purpose: Document database structure for developers
-- =====================================================

-- =====================================================
-- TABLE: pdfs
-- =====================================================
-- Purpose: Stores PDF file references and file paths
-- Relationships: One-to-One with metadata (via pdf_id)

CREATE TABLE pdfs (
    id INT NOT NULL AUTO_INCREMENT,
    filename VARCHAR(255) NOT NULL UNIQUE,
    file_path VARCHAR(500) NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_filename (filename),
    INDEX idx_file_path (file_path)
);

-- Sample data:
-- INSERT INTO pdfs (filename, file_path) VALUES 
-- ('corrected_Gonzalez-G46407_Rodarte.pdf', '/home/RSCAP/shared/archive_directory/corrected_Gonzalez-G46407_Rodarte.pdf'),
-- ('corrected_Gonzalez-G49528_Navarro.pdf', '/home/RSCAP/shared/archive_directory/corrected_Gonzalez-G49528_Navarro.pdf');

-- =====================================================
-- TABLE: metadata
-- =====================================================
-- Purpose: Stores extracted case information and resentencing data
-- Relationships: Many-to-One with pdfs (via pdf_id)

CREATE TABLE metadata (
    id INT NOT NULL AUTO_INCREMENT,
    pdf_id INT NOT NULL,
    date_stamped VARCHAR(50),
    judge VARCHAR(255),
    county VARCHAR(255),
    address TEXT,
    convict_name VARCHAR(255),
    cdcr_number VARCHAR(50),
    case_number VARCHAR(50),
    sentence_date VARCHAR(50),
    cohort VARCHAR(255),
    pid_no VARCHAR(50),
    institution VARCHAR(255),
    old_release_date VARCHAR(50),
    documents_printed_date VARCHAR(50),
    letter_creation_date VARCHAR(50),
    secretary_send_date VARCHAR(50),
    sec_decision VARCHAR(255),
    court_mail_date VARCHAR(50),
    court_response_date VARCHAR(50),
    resentencing_hearing_date VARCHAR(50),
    action_taken VARCHAR(255),
    days_reduced INT,
    years_reduced INT,
    cost_savings DECIMAL(10,2),
    notes TEXT,
    completion_date VARCHAR(50),
    post_release VARCHAR(255),
    isl_dsl VARCHAR(50),
    parole_eligibility_date VARCHAR(50),
    race VARCHAR(100),
    ethnicity VARCHAR(100),
    PRIMARY KEY (id),
    FOREIGN KEY (pdf_id) REFERENCES pdfs(id) ON DELETE CASCADE,
    INDEX idx_pdf_id (pdf_id),
    INDEX idx_date_stamped (date_stamped),
    INDEX idx_judge (judge),
    INDEX idx_county (county),
    INDEX idx_cdcr_number (cdcr_number),
    INDEX idx_case_number (case_number),
    INDEX idx_convict_name (convict_name),
    INDEX idx_action_taken (action_taken),
    INDEX idx_race (race),
    INDEX idx_ethnicity (ethnicity)
);

-- Sample data:
-- INSERT INTO metadata (pdf_id, date_stamped, judge, county, address, convict_name, cdcr_number, case_number, sentence_date, cohort, pid_no, institution, old_release_date, documents_printed_date, letter_creation_date, secretary_send_date, sec_decision, court_mail_date, court_response_date, resentencing_hearing_date, action_taken, days_reduced, years_reduced, cost_savings, notes, completion_date, post_release, isl_dsl, parole_eligibility_date, race, ethnicity) VALUES 
-- (1, 'July 16, 2018', 'Michael L. Schuur', 'Los Angeles', '12720 Norwalk Boulevard, Norwalk, CA 90650', 'Rodarte Jr. Jose Luis', 'G46407', 'VA106941-02', 'December 11. 2008', 'vs. Gonzalez', '11639215', 'SATF-Facility D', '2022-07-12 00:00:00', '2018-06-19 00:00:00', '2018-06-19 00:00:00', '2018-07-11 00:00:00', 'Approved', '2018-07-18 00:00:00', NULL, NULL, NULL, NULL, NULL, NULL, 'Paroled on 12/28/2021', '2022-08-10 00:00:00', NULL, 'DSL', '2021-12-15 00:00:00', 'Hispanic', 'Hispanic');

-- =====================================================
-- TABLE: dataset_source_refresh
-- =====================================================
-- Purpose: UTC timestamps for public "data as of" copy (log, race, letters DB).
-- Updated by mysite on /upload_excel (main_log, race_data) and successful DB letter ingest.

CREATE TABLE dataset_source_refresh (
    source_key VARCHAR(32) NOT NULL PRIMARY KEY,
    refreshed_at DATETIME NOT NULL,
    detail VARCHAR(512) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================
-- TABLE: text_files
-- =====================================================
-- Purpose: Stores references to extracted text files
-- Relationships: Many-to-One with pdfs (via pdf_id)

CREATE TABLE text_files (
    id INT NOT NULL AUTO_INCREMENT,
    pdf_id INT NOT NULL,
    text_file_path VARCHAR(500) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (pdf_id) REFERENCES pdfs(id) ON DELETE CASCADE,
    INDEX idx_pdf_id (pdf_id),
    INDEX idx_text_file_path (text_file_path)
);

-- =====================================================
-- USEFUL QUERIES
-- =====================================================

-- Get all files with metadata
SELECT p.filename, m.date_stamped, m.judge, m.county, m.convict_name, m.cdcr_number, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
ORDER BY p.filename;

-- Get files missing metadata
SELECT p.filename, p.file_path
FROM pdfs p
LEFT JOIN metadata m ON p.id = m.pdf_id
WHERE m.pdf_id IS NULL;

-- Get files by judge
SELECT p.filename, m.date_stamped, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.judge LIKE '%Schuur%'
ORDER BY m.date_stamped;

-- Get files by county
SELECT p.filename, m.judge, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.county = 'Los Angeles'
ORDER BY p.filename;

-- Get files by CDCR number
SELECT p.filename, m.date_stamped, m.judge, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.cdcr_number = 'G46407';

-- Get files by case number
SELECT p.filename, m.date_stamped, m.judge, m.convict_name, m.cdcr_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.case_number = 'VA106941-02';

-- Get files by date range
SELECT p.filename, m.judge, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.date_stamped >= 'July 1, 2018'
AND m.date_stamped <= 'July 31, 2018'
ORDER BY m.date_stamped;

-- Get files by action taken
SELECT p.filename, m.date_stamped, m.judge, m.convict_name, m.case_number
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.action_taken = 'Approved'
ORDER BY m.date_stamped;

-- Get files by race/ethnicity
SELECT p.filename, m.date_stamped, m.judge, m.convict_name, m.race, m.ethnicity
FROM pdfs p
JOIN metadata m ON p.id = m.pdf_id
WHERE m.race = 'Hispanic'
ORDER BY m.date_stamped;

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

-- =====================================================
-- MAINTENANCE QUERIES
-- =====================================================

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

-- Clean up orphaned metadata
DELETE m FROM metadata m
LEFT JOIN pdfs p ON m.pdf_id = p.id
WHERE p.id IS NULL;

-- =====================================================
-- BACKUP AND RESTORE
-- =====================================================

-- Backup all data
-- mysqldump -u username -p database_name > backup_$(date +%Y%m%d_%H%M%S).sql

-- Restore from backup
-- mysql -u username -p database_name < backup_file.sql

-- =====================================================
-- DEVELOPER NOTES
-- =====================================================

-- IMPORTANT CONSTRAINTS:
-- 1. pdfs.filename must be UNIQUE
-- 2. metadata.pdf_id must reference valid pdfs.id
-- 3. text_files.pdf_id must reference valid pdfs.id

-- DATA TYPES:
-- - VARCHAR fields: Use for text with known max length
-- - TEXT fields: Use for longer text content
-- - INT fields: Use for whole numbers
-- - DECIMAL fields: Use for monetary values
-- - VARCHAR(50) for dates: Store as text for flexibility

-- INDEXING STRATEGY:
-- - Primary keys are automatically indexed
-- - Foreign keys should be indexed for performance
-- - Frequently queried fields should be indexed
-- - Consider composite indexes for complex queries

-- PERFORMANCE TIPS:
-- 1. Use LIMIT for large result sets
-- 2. Add WHERE clauses to reduce data scanned
-- 3. Use appropriate indexes
-- 4. Consider partitioning for very large tables
-- 5. Regular maintenance (OPTIMIZE TABLE)

-- SECURITY CONSIDERATIONS:
-- 1. Use parameterized queries to prevent SQL injection
-- 2. Validate all input data
-- 3. Use least privilege database users
-- 4. Regular backups
-- 5. Monitor for suspicious activity

-- ===================================================== 