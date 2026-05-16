#!/usr/bin/env python3
"""
Enhanced Upload Route with Safety Measures

This module provides an enhanced version of the upload_to_database route
with comprehensive safety measures and fail-safe mechanisms.
"""

import os
import json
import logging
import mysql.connector
import datetime
from typing import Dict, List
from upload_safety import UploadSafetyManager, log_upload_step, log_upload_error
from safe_upload_pipeline import SafeUploadPipeline


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _run_auto_recovery(connection, archive_dir: str) -> Dict:
    """
    Recover archive files missing from DB by inserting minimal placeholder records.
    Also ensures each PDF row has at least one metadata row.
    """
    stats = {
        "missing_pdfs_inserted": 0,
        "metadata_placeholders_inserted": 0,
        "errors": [],
    }
    if not os.path.isdir(archive_dir):
        return stats

    cursor = connection.cursor()
    try:
        # Build a quick lookup of PDF rows currently in DB.
        cursor.execute("SELECT id, filename FROM pdfs")
        db_rows = cursor.fetchall()
        filename_to_pdf_id = {row[1]: row[0] for row in db_rows if row and len(row) >= 2}

        archive_files = [f for f in os.listdir(archive_dir) if f.lower().endswith(".pdf")]
        now_stamp = datetime.datetime.now().strftime("%B %d, %Y")
        note_stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Insert missing PDF rows + minimal metadata placeholders.
        for filename in archive_files:
            try:
                if filename in filename_to_pdf_id:
                    continue
                file_path = os.path.join(archive_dir, filename)
                cursor.execute(
                    "INSERT INTO pdfs (filename, file_path) VALUES (%s, %s)",
                    (filename, file_path),
                )
                pdf_id = cursor.lastrowid
                cursor.execute(
                    """
                    INSERT INTO metadata (pdf_id, date_stamped, notes)
                    VALUES (%s, %s, %s)
                    """,
                    (pdf_id, now_stamp, f"Auto-recovered on {note_stamp} - Metadata pending refresh"),
                )
                filename_to_pdf_id[filename] = pdf_id
                stats["missing_pdfs_inserted"] += 1
                stats["metadata_placeholders_inserted"] += 1
            except Exception as row_error:
                stats["errors"].append(f"{filename}: {row_error}")

        # Ensure existing pdf rows have at least one metadata row.
        cursor.execute(
            """
            SELECT p.id, p.filename
            FROM pdfs p
            LEFT JOIN metadata m ON p.id = m.pdf_id
            WHERE m.pdf_id IS NULL
            """
        )
        orphaned_pdf_rows = cursor.fetchall()
        for pdf_id, filename in orphaned_pdf_rows:
            try:
                cursor.execute(
                    """
                    INSERT INTO metadata (pdf_id, date_stamped, notes)
                    VALUES (%s, %s, %s)
                    """,
                    (pdf_id, now_stamp, f"Auto-recovered on {note_stamp} - Metadata pending refresh"),
                )
                stats["metadata_placeholders_inserted"] += 1
            except Exception as meta_error:
                stats["errors"].append(f"{filename} metadata: {meta_error}")

        connection.commit()
        return stats
    except Exception as e:
        connection.rollback()
        stats["errors"].append(str(e))
        return stats
    finally:
        cursor.close()


def enhanced_upload_to_database_route(
    database_config: Dict,
    output_folder: str = "processed",
    extractions_folder: str = "OCRextractions",
    metadata_file: str = "./Jsontags/metadata.json",
    archive_dir: str = "/home/RSCAP/shared/archive_directory",
    skip_extract_and_tag: bool = False,
) -> Dict:
    """
    Enhanced version of upload_to_database_route with comprehensive safety measures.
    
    Args:
        database_config: Database connection configuration
        output_folder: Folder containing processed PDFs
        extractions_folder: Folder containing text extractions
        metadata_file: Path to metadata JSON file
        archive_dir: Archive directory path
        skip_extract_and_tag: If True, assume text + ``metadata_file`` are already
            built (caller ran extract/tag). Only DB upload, cleanup hooks, and
            auto-recovery run.

    Returns:
        Dict containing upload results and status
    """

    # Initialize safety systems
    safety_manager = UploadSafetyManager()
    upload_pipeline = SafeUploadPipeline(safety_manager)

    results = {
        "success": False,
        "message": "",
        "files_processed": 0,
        "files_succeeded": 0,
        "files_failed": 0,
        "errors": [],
        "safety_report": None,
        "extract_stats": None,
    }
    
    connection = None
    processed_files = []
    upload_results = None

    try:
        log_upload_step("Enhanced Upload Started", "SUCCESS", 
                       f"Processing files from {output_folder}")

        if not skip_extract_and_tag:
            # Step 1: Extract text from PDFs
            try:
                from extracttext import extract_text_from_pdfs
                xt_stats = extract_text_from_pdfs(output_folder, extractions_folder)
                results["extract_stats"] = xt_stats if isinstance(xt_stats, dict) else {}
                failed_xt = (results["extract_stats"] or {}).get("failed") or []
                if failed_xt:
                    log_upload_step(
                        "Text Extraction",
                        "PARTIAL",
                        f"Completed with {len(failed_xt)} PDF(s) unreadable — see logs",
                    )
                    for row in failed_xt[:50]:
                        log_upload_error(
                            "TEXT_EXTRACTION_SKIPPED",
                            row.get("error", ""),
                            row.get("file") or "",
                        )
                else:
                    log_upload_step("Text Extraction", "SUCCESS", "Text extraction completed")
            except Exception as e:
                error_msg = f"Text extraction failed: {str(e)}"
                log_upload_error("TEXT_EXTRACTION_FAILED", error_msg, traceback_info=str(e))
                results["errors"].append(error_msg)
                return results

            # Step 2: Extract metadata from text files
            try:
                from tagextraction import extract_metadata_from_text_files
                text_files = os.listdir(extractions_folder) if os.path.exists(extractions_folder) else []
                log_upload_step("Metadata Extraction Started", "SUCCESS", 
                               f"Found {len(text_files)} text files for processing")

                metadata_dir = os.path.dirname(metadata_file)
                if metadata_dir:
                    os.makedirs(metadata_dir, exist_ok=True)
                extract_metadata_from_text_files(extractions_folder, metadata_file)
                log_upload_step("Metadata Extraction", "SUCCESS", "Metadata extraction completed")
            except Exception as e:
                error_msg = f"Metadata extraction failed: {str(e)}"
                log_upload_error("METADATA_EXTRACTION_FAILED", error_msg, traceback_info=str(e))
                results["errors"].append(error_msg)
                return results
        else:
            log_upload_step("Extract/Tag", "SKIPPED", "skip_extract_and_tag=True")

        # Step 3: Connect to database
        try:
            connection = mysql.connector.connect(**database_config)
            log_upload_step("Database Connection", "SUCCESS", "Connected to database successfully")
        except mysql.connector.Error as db_error:
            error_msg = f"Database connection failed: {str(db_error)}"
            log_upload_error("DB_CONNECTION_FAILED", error_msg, traceback_info=str(db_error))
            results["errors"].append(error_msg)
            return results
        
        # Step 4: Get list of processed files for safety tracking
        if os.path.exists(output_folder):
            processed_files = [os.path.join(output_folder, f) for f in os.listdir(output_folder) 
                             if f.endswith('.pdf')]
            log_upload_step("File Inventory", "SUCCESS", 
                           f"Found {len(processed_files)} processed files")
        
        # Step 5: Safe database upload
        upload_results = upload_pipeline.safe_upload_to_database(
            connection, archive_dir, extractions_folder, metadata_file
        )
        
        # Update results with upload statistics
        results.update({
            "files_processed": upload_results["files_processed"],
            "files_succeeded": upload_results["files_succeeded"],
            "files_failed": upload_results["files_failed"],
            "errors": results["errors"] + upload_results["errors"]
        })
        
        # Step 6: Check for missed entries
        missed_entries_size = 0
        missed_entries_file = './logs/Missedentries.json'
        if os.path.exists(missed_entries_file):
            missed_entries_size = os.path.getsize(missed_entries_file)
        
        # Step 7: Determine if upload was successful
        if upload_results["success"] and missed_entries_size == 0:
            results["success"] = True
            results["message"] = "Data successfully uploaded to the database."
            log_upload_step("Upload Complete", "SUCCESS", "All files uploaded successfully")
            
            # Step 8: Safe file cleanup (only if upload was successful)
            clear_results = upload_pipeline.safe_clear_files(processed_files)
            if clear_results["success"]:
                log_upload_step("File Cleanup", "SUCCESS", 
                               f"Cleared {clear_results['files_cleared']} files")
            else:
                log_upload_error("FILE_CLEANUP_FAILED", 
                               f"File cleanup had errors: {clear_results['errors']}")
                
        elif missed_entries_size > 0:
            results["message"] = "File(s) couldn't find a matching entry in the logs. Please check Missedentries.json"
            log_upload_step("Upload Complete", "PARTIAL", 
                           "Upload completed but some entries were missed")
            
            # Keep files for manual investigation
            log_upload_step("File Retention", "SUCCESS", 
                           f"Keeping {len(processed_files)} files for manual investigation")
            
        else:
            results["message"] = f"Upload failed. {upload_results['files_failed']} files failed to upload."
            log_upload_error("UPLOAD_FAILED", results["message"])
            
            # Keep all files for manual investigation
            log_upload_step("File Retention", "SUCCESS", 
                           f"Keeping {len(processed_files)} files due to upload failures")
        
        # Step 9: Generate safety report
        try:
            results["safety_report"] = safety_manager.generate_safety_report()
            log_upload_step("Safety Report Generated", "SUCCESS", "Safety report created")
        except Exception as e:
            log_upload_error("SAFETY_REPORT_ERROR", f"Failed to generate safety report: {str(e)}")
        
        # Step 10: Cleanup old shadow copies
        try:
            safety_manager.cleanup_old_shadow_copies(max_age_hours=48)
            log_upload_step("Shadow Copy Cleanup", "SUCCESS", "Old shadow copies cleaned up")
        except Exception as e:
            log_upload_error("SHADOW_CLEANUP_ERROR", f"Shadow copy cleanup failed: {str(e)}")

        # Step 11: Optional auto-recovery for archive-vs-DB drift.
        # Enabled by default to match current operational preference.
        if _env_flag("ENABLE_AUTO_RECOVERY", "true"):
            try:
                recovery_stats = _run_auto_recovery(connection, archive_dir)
                log_upload_step(
                    "Auto Recovery",
                    "SUCCESS" if not recovery_stats["errors"] else "PARTIAL",
                    f"missing_pdfs_inserted={recovery_stats['missing_pdfs_inserted']}, "
                    f"metadata_placeholders_inserted={recovery_stats['metadata_placeholders_inserted']}, "
                    f"errors={len(recovery_stats['errors'])}",
                )
                if recovery_stats["errors"]:
                    for err in recovery_stats["errors"][:25]:
                        log_upload_error("AUTO_RECOVERY_ERROR", err)
            except Exception as e:
                log_upload_error("AUTO_RECOVERY_FAILED", f"Auto recovery failed: {str(e)}")

        if connection and connection.is_connected() and upload_results is not None:
            try:
                fs = int(upload_results.get("files_succeeded") or 0)
                if fs > 0:
                    cur_ln = connection.cursor()
                    from dataset_lineage import touch_dataset_source
                    touch_dataset_source(
                        cur_ln,
                        connection,
                        "letters_db",
                        detail=f"enhanced upload, {fs} file(s) succeeded",
                    )
                    cur_ln.close()
            except Exception as lineage_err:
                logging.warning("dataset lineage (letters) skipped: %s", lineage_err)

    except Exception as e:
        error_msg = f"Critical error in enhanced upload: {str(e)}"
        log_upload_error("CRITICAL_UPLOAD_ERROR", error_msg, traceback_info=str(e))
        results["errors"].append(error_msg)
        results["message"] = f"Critical error occurred: {str(e)}"
        
    finally:
        # Ensure database connection is closed
        if connection:
            try:
                connection.close()
                log_upload_step("Database Connection Closed", "SUCCESS", "Connection closed safely")
            except Exception as e:
                log_upload_error("DB_CLOSE_ERROR", f"Error closing database connection: {str(e)}")
    
    return results


def get_upload_safety_status() -> Dict:
    """
    Get current status of upload safety system.
    
    Returns:
        Dict containing safety system status
    """
    try:
        safety_manager = UploadSafetyManager()
        
        # Get failed uploads
        failed_uploads = safety_manager.get_failed_uploads()
        
        # Generate safety report
        safety_report = safety_manager.generate_safety_report()
        
        # Check shadow copy directory
        shadow_dir = safety_manager.shadow_dir
        shadow_files = []
        if os.path.exists(shadow_dir):
            shadow_files = [f for f in os.listdir(shadow_dir) if os.path.isfile(os.path.join(shadow_dir, f))]
        
        return {
            "status": "healthy" if len(failed_uploads) == 0 else "issues_detected",
            "failed_uploads_count": len(failed_uploads),
            "shadow_copies_count": len(shadow_files),
            "failed_uploads": failed_uploads,
            "safety_report": safety_report,
            "recommendations": safety_report.get("recommendations", [])
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def cleanup_failed_uploads() -> Dict:
    """
    Clean up failed uploads and provide recovery options.
    
    Returns:
        Dict containing cleanup results
    """
    try:
        safety_manager = UploadSafetyManager()
        failed_uploads = safety_manager.get_failed_uploads()
        
        results = {
            "success": False,
            "cleaned_count": 0,
            "errors": []
        }
        
        if not failed_uploads:
            results["success"] = True
            results["message"] = "No failed uploads to clean up"
            return results
        
        # For now, just log the failed uploads for manual review
        # In the future, this could implement automatic retry logic
        log_upload_step("Failed Upload Cleanup", "SUCCESS", 
                       f"Found {len(failed_uploads)} failed uploads for manual review")
        
        results["success"] = True
        results["cleaned_count"] = len(failed_uploads)
        results["message"] = f"Found {len(failed_uploads)} failed uploads requiring manual review"
        
        return results
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
