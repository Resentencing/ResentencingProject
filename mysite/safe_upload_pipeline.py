#!/usr/bin/env python3
"""
Safe Upload Pipeline for RSCAP Data Management

This module provides a fail-safe upload pipeline that prevents data loss
by implementing comprehensive safety measures and rollback capabilities.
"""

import os
import shutil
import json
import logging
import mysql.connector
from typing import Dict, List, Tuple, Optional
from upload_safety import UploadSafetyManager, log_upload_step, log_upload_error

class SafeUploadPipeline:
    """
    Implements a fail-safe upload pipeline with comprehensive error handling.
    """
    
    def __init__(self, safety_manager: UploadSafetyManager = None):
        self.safety_manager = safety_manager or UploadSafetyManager()
        self.processed_files_backup = []
        self.failed_files = []
    
    def safe_upload_to_database(self, connection, pdf_folder: str, text_folder: str, 
                               metadata_file: str) -> Dict[str, any]:
        """
        Safe version of upload_to_database with comprehensive error handling.
        
        Args:
            connection: Database connection
            pdf_folder: Directory containing PDF files
            text_folder: Directory containing text files
            metadata_file: Path to metadata JSON file
            
        Returns:
            Dict containing upload results and statistics
        """
        results = {
            "success": False,
            "files_processed": 0,
            "files_succeeded": 0,
            "files_failed": 0,
            "errors": [],
            "failed_files": []
        }
        
        try:
            log_upload_step("Database Upload Started", "SUCCESS", 
                           f"Processing metadata file: {metadata_file}")
            
            cursor = connection.cursor()
            
            if not os.path.exists(metadata_file):
                error_msg = f"Metadata file not found: {metadata_file}"
                log_upload_error("METADATA_FILE_NOT_FOUND", error_msg, metadata_file)
                results["errors"].append(error_msg)
                return results
            
            # Load metadata from JSON file
            with open(metadata_file, "r", encoding="utf-8") as file:
                try:
                    metadata_list = json.load(file)
                except json.JSONDecodeError as e:
                    error_msg = f"Error parsing JSON metadata file: {e}"
                    log_upload_error("JSON_PARSE_ERROR", error_msg, metadata_file)
                    results["errors"].append(error_msg)
                    return results
            
            if not metadata_list:
                error_msg = "No metadata found in JSON file"
                log_upload_error("NO_METADATA_FOUND", error_msg, metadata_file)
                results["errors"].append(error_msg)
                return results
            
            log_upload_step("Metadata Loaded", "SUCCESS", 
                           f"Loaded {len(metadata_list)} metadata entries")
            
            # Process each metadata entry
            for i, metadata in enumerate(metadata_list):
                try:
                    file_result = self._process_single_metadata_entry(
                        cursor, metadata, pdf_folder, i + 1, len(metadata_list)
                    )
                    
                    results["files_processed"] += 1
                    if file_result["success"]:
                        results["files_succeeded"] += 1
                    else:
                        results["files_failed"] += 1
                        results["failed_files"].append(file_result)
                        results["errors"].extend(file_result.get("errors", []))
                        
                except Exception as e:
                    error_msg = f"Unexpected error processing metadata entry {i+1}: {str(e)}"
                    log_upload_error("METADATA_PROCESSING_ERROR", error_msg, 
                                   traceback_info=str(e))
                    results["errors"].append(error_msg)
                    results["files_failed"] += 1
            
            # Commit all changes if no critical errors
            if results["files_failed"] == 0:
                connection.commit()
                log_upload_step("Database Commit", "SUCCESS", 
                               f"Committed {results['files_succeeded']} entries")
                results["success"] = True
            else:
                # Rollback on errors
                connection.rollback()
                log_upload_step("Database Rollback", "SUCCESS", 
                               f"Rolled back due to {results['files_failed']} failures")
            
            log_upload_step("Database Upload Completed", "SUCCESS" if results["success"] else "FAILED",
                           f"Processed: {results['files_processed']}, "
                           f"Succeeded: {results['files_succeeded']}, "
                           f"Failed: {results['files_failed']}")
            
        except Exception as e:
            error_msg = f"Critical error in database upload: {str(e)}"
            log_upload_error("CRITICAL_UPLOAD_ERROR", error_msg, traceback_info=str(e))
            results["errors"].append(error_msg)
            
            # Attempt rollback
            try:
                connection.rollback()
                log_upload_step("Emergency Rollback", "SUCCESS", "Rolled back due to critical error")
            except:
                pass
        
        return results
    
    def _process_single_metadata_entry(self, cursor, metadata: Dict, pdf_folder: str, 
                                     entry_num: int, total_entries: int) -> Dict:
        """
        Process a single metadata entry with comprehensive error handling.
        
        Args:
            cursor: Database cursor
            metadata: Metadata dictionary
            pdf_folder: PDF folder path
            entry_num: Current entry number
            total_entries: Total number of entries
            
        Returns:
            Dict containing processing results
        """
        result = {
            "success": False,
            "filename": metadata.get("filename", "unknown"),
            "errors": []
        }
        
        try:
            # Validate required fields
            required_fields = [
                "filename", "DATE STAMPED", "JUDGE", "COUNTY", "ADDRESS", "CNAME",
                "CDCR NO", "CASE NO", "SENTENCE DATE"
            ]
            
            missing_fields = [field for field in required_fields if not metadata.get(field)]
            if missing_fields:
                error_msg = f"Missing required fields: {missing_fields}"
                log_upload_error("MISSING_REQUIRED_FIELDS", error_msg, result["filename"])
                result["errors"].append(error_msg)
                return result
            
            # Sanitize metadata values
            from dbconnector import sanitize_value
            for key in metadata:
                metadata[key] = sanitize_value(metadata[key])
            
            pdf_filename = metadata["filename"]
            archive_base_path = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
            pdf_path = os.path.join(archive_base_path, pdf_filename)
            
            # Verify PDF file exists in archive
            if not os.path.exists(pdf_path):
                error_msg = f"PDF file not found in archive: {pdf_path}"
                log_upload_error("PDF_NOT_FOUND", error_msg, pdf_filename)
                result["errors"].append(error_msg)
                return result
            
            log_upload_step("PDF Verification", "SUCCESS", 
                           f"PDF file verified: {pdf_filename}", pdf_path)
            
            # Insert PDF (if not exists)
            cursor.execute("""
                INSERT IGNORE INTO pdfs (filename, file_path) VALUES (%s, %s)
            """, (pdf_filename, pdf_path))
            
            cursor.execute("SELECT id FROM pdfs WHERE filename = %s", (pdf_filename,))
            pdf_id_result = cursor.fetchone()
            
            if not pdf_id_result:
                error_msg = f"Failed to retrieve pdf_id for {pdf_filename}"
                log_upload_error("PDF_ID_RETRIEVAL_FAILED", error_msg, pdf_filename)
                result["errors"].append(error_msg)
                return result
            
            pdf_id = pdf_id_result[0]
            log_upload_step("PDF Database Entry", "SUCCESS", 
                           f"PDF ID {pdf_id} for {pdf_filename}")
            
            # Check for duplicate metadata
            cursor.execute("SELECT COUNT(*) FROM metadata WHERE pdf_id = %s AND case_number = %s", 
                         (pdf_id, metadata["CASE NO"]))
            existing_metadata = cursor.fetchone()[0]
            
            if existing_metadata > 0:
                log_upload_step("Duplicate Check", "SKIPPED", 
                               f"Metadata already exists for PDF ID {pdf_id} with case {metadata['CASE NO']}")
                result["success"] = True  # Not an error, just skipped
                return result
            
            # Insert metadata
            query = """
                INSERT INTO metadata (
                    pdf_id, date_stamped, judge, county, address, convict_name, cdcr_number,
                    case_number, sentence_date, cohort, pid_no, institution, old_release_date,
                    documents_printed_date, letter_creation_date, secretary_send_date, sec_decision,
                    court_mail_date, court_response_date, resentencing_hearing_date, action_taken,
                    days_reduced, years_reduced, cost_savings, notes, completion_date,
                    post_release, isl_dsl, parole_eligibility_date, race, ethnicity
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """
            
            values = (
                pdf_id, metadata["DATE STAMPED"], metadata["JUDGE"], metadata["COUNTY"],
                metadata["ADDRESS"], metadata["CNAME"], metadata["CDCR NO"], metadata["CASE NO"],
                metadata["SENTENCE DATE"], metadata.get("COHORT"), metadata.get("PID NO"),
                metadata.get("INSTITUTION"), metadata.get("OLD RELEASE DATE"),
                metadata.get("DOCUMENTS PRINTED DATE"), metadata.get("LETTER CREATION DATE"),
                metadata.get("SECRETARY SEND DATE"), metadata.get("SEC DECISION"),
                metadata.get("COURT MAIL DATE"), metadata.get("COURT RESPONSE DATE"),
                metadata.get("RESENTENCING HEARING DATE"), metadata.get("ACTION TAKEN"),
                metadata.get("DAYS REDUCED"), metadata.get("YEARS REDUCED"),
                metadata.get("COST SAVINGS"), metadata.get("NOTES"),
                metadata.get("COMPLETION DATE"), metadata.get("POST RELEASE"),
                metadata.get("ISL DSL"), metadata.get("PAROLE ELIGIBILITY DATE"),
                metadata.get("RACE"), metadata.get("ETHNICITY")
            )
            
            cursor.execute(query, values)
            
            # Verify the insert was successful
            verification_success = self.safety_manager.verify_database_entry(
                cursor.connection, pdf_filename, metadata["CASE NO"]
            )
            
            if verification_success:
                log_upload_step("Metadata Insert", "SUCCESS", 
                               f"Entry {entry_num}/{total_entries}: {pdf_filename} - {metadata['CASE NO']}")
                result["success"] = True
            else:
                error_msg = f"Database verification failed for {pdf_filename}"
                log_upload_error("DB_VERIFICATION_FAILED", error_msg, pdf_filename)
                result["errors"].append(error_msg)
            
        except Exception as e:
            error_msg = f"Error processing metadata entry: {str(e)}"
            log_upload_error("METADATA_ENTRY_ERROR", error_msg, result["filename"], 
                           traceback_info=str(e))
            result["errors"].append(error_msg)
        
        return result
    
    def safe_clear_files(self, processed_files: List[str], 
                        force_clear: bool = False) -> Dict[str, any]:
        """
        Safely clear files only after successful upload verification.
        
        Args:
            processed_files: List of files that were processed
            force_clear: If True, clear files even if some uploads failed
            
        Returns:
            Dict containing clear operation results
        """
        results = {
            "success": False,
            "files_cleared": 0,
            "files_kept": 0,
            "errors": []
        }
        
        try:
            # Check if we should clear files
            failed_uploads = self.safety_manager.get_failed_uploads()
            
            if failed_uploads and not force_clear:
                log_upload_step("File Clear", "SKIPPED", 
                               f"Keeping {len(processed_files)} files due to {len(failed_uploads)} failed uploads")
                results["files_kept"] = len(processed_files)
                results["success"] = True
                return results
            
            # Clear files safely
            for file_path in processed_files:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        results["files_cleared"] += 1
                        log_upload_step("File Cleared", "SUCCESS", f"Removed: {file_path}")
                    else:
                        log_upload_step("File Clear", "SKIPPED", f"File not found: {file_path}")
                        
                except Exception as e:
                    error_msg = f"Failed to clear file {file_path}: {str(e)}"
                    log_upload_error("FILE_CLEAR_ERROR", error_msg, file_path)
                    results["errors"].append(error_msg)
            
            log_upload_step("File Clear Complete", "SUCCESS", 
                           f"Cleared {results['files_cleared']} files, kept {results['files_kept']} files")
            results["success"] = True
            
        except Exception as e:
            error_msg = f"Critical error during file clear: {str(e)}"
            log_upload_error("CRITICAL_CLEAR_ERROR", error_msg, traceback_info=str(e))
            results["errors"].append(error_msg)
        
        return results


def create_safe_upload_pipeline() -> SafeUploadPipeline:
    """Create and return a new SafeUploadPipeline instance."""
    return SafeUploadPipeline()
