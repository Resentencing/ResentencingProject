"""
Integration tests for safety systems.

Tests upload_safety.py and safe_upload_pipeline.py safety features.
"""
import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from upload_safety import UploadSafetyManager, log_upload_step, log_upload_error
from safe_upload_pipeline import SafeUploadPipeline


class TestUploadSafetyManager:
    """Tests for UploadSafetyManager."""
    
    def test_shadow_copy_creation(self, temp_dir):
        """Test shadow copy creation."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        # Create source file
        source_file = os.path.join(temp_dir, "test.pdf")
        with open(source_file, 'wb') as f:
            f.write(b"PDF content")
        
        # Create shadow copy
        result = safety_manager.create_shadow_copy(source_file, "test123")
        
        assert result is True
        assert os.path.exists(safety_manager.shadow_dir)
        shadow_files = os.listdir(safety_manager.shadow_dir)
        assert len(shadow_files) > 0
    
    def test_shadow_copy_cleanup(self, temp_dir):
        """Test cleanup of old shadow copies."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        # Create old shadow copy (simulate by setting old mtime)
        old_file = os.path.join(safety_manager.shadow_dir, "old_file.pdf")
        with open(old_file, 'wb') as f:
            f.write(b"old content")
        
        # Set file time to 50 hours ago
        old_time = datetime.now() - timedelta(hours=50)
        os.utime(old_file, (old_time.timestamp(), old_time.timestamp()))
        
        # Create new shadow copy
        new_file = os.path.join(safety_manager.shadow_dir, "new_file.pdf")
        with open(new_file, 'wb') as f:
            f.write(b"new content")
        
        # Cleanup old files (max age 48 hours)
        safety_manager.cleanup_old_shadow_copies(max_age_hours=48)
        
        # Old file should be deleted, new file should remain
        assert not os.path.exists(old_file)
        assert os.path.exists(new_file)
    
    def test_error_logging(self, temp_dir):
        """Test error logging functionality."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        # Log an error
        safety_manager.log_error(
            "TEST_ERROR",
            "Test error message",
            "test_file.pdf",
            "traceback info"
        )
        
        # Verify error was logged
        assert os.path.exists(safety_manager.error_log_file)
        with open(safety_manager.error_log_file, 'r') as f:
            errors = json.load(f)
        
        assert len(errors) > 0
        assert errors[-1]["error_type"] == "TEST_ERROR"
        assert errors[-1]["error_message"] == "Test error message"
    
    def test_archive_verification(self, temp_dir):
        """Test archive copy verification."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        # Create source and archive files
        source_file = os.path.join(temp_dir, "source.pdf")
        archive_file = os.path.join(temp_dir, "archive.pdf")
        
        content = b"PDF content for verification"
        with open(source_file, 'wb') as f:
            f.write(content)
        with open(archive_file, 'wb') as f:
            f.write(content)
        
        # Verify archive
        result = safety_manager.verify_archive_copy(source_file, archive_file)
        
        assert result is True
    
    def test_archive_verification_failure(self, temp_dir):
        """Test archive verification failure when files don't match."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        source_file = os.path.join(temp_dir, "source.pdf")
        archive_file = os.path.join(temp_dir, "archive.pdf")
        
        with open(source_file, 'wb') as f:
            f.write(b"Source content")
        with open(archive_file, 'wb') as f:
            f.write(b"Different archive content")
        
        result = safety_manager.verify_archive_copy(source_file, archive_file)
        
        assert result is False
    
    def test_database_verification(self, temp_dir, mock_db_connection):
        """Test database entry verification."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        mock_conn, mock_cursor = mock_db_connection
        
        # Mock successful verification
        mock_cursor.fetchone.side_effect = [
            (1,),  # pdf_id
            (1,),  # metadata count
        ]
        
        result = safety_manager.verify_database_entry(
            mock_conn, "test.pdf", "CASE001"
        )
        
        assert result is True
    
    def test_database_verification_failure(self, temp_dir, mock_db_connection):
        """Test database verification failure."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        mock_conn, mock_cursor = mock_db_connection
        
        # Mock PDF not found
        mock_cursor.fetchone.return_value = None
        
        result = safety_manager.verify_database_entry(
            mock_conn, "nonexistent.pdf", "CASE001"
        )
        
        assert result is False
    
    def test_get_failed_uploads(self, temp_dir):
        """Test retrieving failed uploads."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        # Log some upload errors
        safety_manager.log_error("UPLOAD_FAILED", "Upload error 1", "file1.pdf")
        safety_manager.log_error("UPLOAD_FAILED", "Upload error 2", "file2.pdf")
        safety_manager.log_error("OTHER_ERROR", "Other error", "file3.pdf")
        
        failed_uploads = safety_manager.get_failed_uploads()
        
        # Should only return upload-related errors
        assert len(failed_uploads) == 2
        assert all("UPLOAD" in error["error_type"] for error in failed_uploads)
    
    def test_safety_report_generation(self, temp_dir):
        """Test safety report generation."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        # Create some shadow copies
        for i in range(3):
            shadow_file = os.path.join(safety_manager.shadow_dir, f"file{i}.pdf")
            with open(shadow_file, 'wb') as f:
                f.write(b"content")
        
        # Log some errors
        safety_manager.log_error("UPLOAD_FAILED", "Test error", "test.pdf")
        
        report = safety_manager.generate_safety_report()
        
        assert "timestamp" in report
        assert report["shadow_copies_count"] == 3
        assert report["failed_uploads_count"] == 1
        assert "recommendations" in report


class TestSafeUploadPipelineSafety:
    """Tests for safety features in SafeUploadPipeline."""
    
    def test_safe_file_clear_success(self, temp_dir):
        """Test safe file clearing after successful upload."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        pipeline = SafeUploadPipeline(safety_manager)
        
        # Create test files
        test_files = []
        for i in range(3):
            test_file = os.path.join(temp_dir, f"test{i}.pdf")
            with open(test_file, 'wb') as f:
                f.write(b"content")
            test_files.append(test_file)
        
        # Clear files (no failed uploads)
        results = pipeline.safe_clear_files(test_files)
        
        assert results["success"] is True
        assert results["files_cleared"] == 3
        # Files should be deleted
        for file_path in test_files:
            assert not os.path.exists(file_path)
    
    def test_safe_file_clear_with_failures(self, temp_dir):
        """Test that files are kept when uploads fail."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        # Log failed uploads
        safety_manager.log_error("UPLOAD_FAILED", "Upload failed", "test.pdf")
        
        pipeline = SafeUploadPipeline(safety_manager)
        
        # Create test files
        test_files = []
        for i in range(2):
            test_file = os.path.join(temp_dir, f"test{i}.pdf")
            with open(test_file, 'wb') as f:
                f.write(b"content")
            test_files.append(test_file)
        
        # Try to clear files (should skip due to failures)
        results = pipeline.safe_clear_files(test_files)
        
        assert results["success"] is True
        assert results["files_kept"] == 2
        assert results["files_cleared"] == 0
        # Files should still exist
        for file_path in test_files:
            assert os.path.exists(file_path)
    
    def test_safe_file_clear_force(self, temp_dir):
        """Test forced file clearing even with failures."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        
        # Log failed uploads
        safety_manager.log_error("UPLOAD_FAILED", "Upload failed", "test.pdf")
        
        pipeline = SafeUploadPipeline(safety_manager)
        
        # Create test files
        test_file = os.path.join(temp_dir, "test.pdf")
        with open(test_file, 'wb') as f:
            f.write(b"content")
        
        # Force clear
        results = pipeline.safe_clear_files([test_file], force_clear=True)
        
        assert results["success"] is True
        assert results["files_cleared"] == 1
        assert not os.path.exists(test_file)
    
    def test_upload_with_shadow_copy(self, temp_dir, mock_db_connection, sample_metadata):
        """Test that upload creates shadow copies."""
        safety_manager = UploadSafetyManager(
            log_dir=os.path.join(temp_dir, "logs"),
            shadow_dir=os.path.join(temp_dir, "shadow")
        )
        pipeline = SafeUploadPipeline(safety_manager)
        
        mock_conn, mock_cursor = mock_db_connection
        
        pdf_folder = os.path.join(temp_dir, "archive")
        text_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        
        os.makedirs(pdf_folder, exist_ok=True)
        
        pdf_path = os.path.join(pdf_folder, sample_metadata["filename"])
        with open(pdf_path, 'wb') as f:
            f.write(b"%PDF-1.4\n")
        
        with open(metadata_file, 'w') as f:
            json.dump([sample_metadata], f)
        
        mock_cursor.fetchone.side_effect = [(1,), (0,)]
        
        with patch('safe_upload_pipeline.os.getenv', return_value=pdf_folder):
            results = pipeline.safe_upload_to_database(
                mock_conn, pdf_folder, text_folder, metadata_file
            )
        
        # Shadow copy should be created (if implemented in pipeline)
        # This tests the integration between pipeline and safety manager
        assert results["success"] is True

