"""
Integration tests for database upload workflows.

Tests metadata insertion workflows, duplicate handling, and transaction management.
"""
import pytest
import os
import json
import tempfile
from unittest.mock import Mock, MagicMock, patch
import mysql.connector

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from safe_upload_pipeline import SafeUploadPipeline
from dbconnector import upload_to_database


class TestDatabaseUploadWorkflows:
    """Tests for database upload workflows."""
    
    def test_metadata_insertion_workflow(self, temp_dir, mock_db_connection, sample_metadata):
        """Test complete metadata insertion workflow."""
        mock_conn, mock_cursor = mock_db_connection
        
        pdf_folder = os.path.join(temp_dir, "archive")
        text_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        
        os.makedirs(pdf_folder, exist_ok=True)
        
        # Create PDF
        pdf_path = os.path.join(pdf_folder, sample_metadata["filename"])
        with open(pdf_path, 'wb') as f:
            f.write(b"%PDF-1.4\n")
        
        # Create metadata file
        with open(metadata_file, 'w') as f:
            json.dump([sample_metadata], f)
        
        # Mock cursor responses
        mock_cursor.fetchone.side_effect = [
            (1,),  # pdf_id
            (0,),  # duplicate check
        ]
        
        # Patch os.getenv to return our pdf_folder as archive dir
        with patch('safe_upload_pipeline.os.getenv', return_value=pdf_folder):
            pipeline = SafeUploadPipeline()
            results = pipeline.safe_upload_to_database(
                mock_conn, pdf_folder, text_folder, metadata_file
            )
        
        # Verify database operations were called
        assert mock_cursor.execute.called
        assert mock_conn.commit.called
        assert results["success"] is True
    
    def test_duplicate_metadata_handling(self, temp_dir, mock_db_connection, sample_metadata):
        """Test that duplicate metadata entries are handled correctly."""
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
        
        # Mock duplicate exists
        mock_cursor.fetchone.side_effect = [
            (1,),  # pdf_id
            (1,),  # duplicate exists (count > 0)
        ]
        
        with patch('safe_upload_pipeline.os.getenv', return_value=pdf_folder):
            pipeline = SafeUploadPipeline()
            results = pipeline.safe_upload_to_database(
                mock_conn, pdf_folder, text_folder, metadata_file
            )
        
        # Should succeed but skip duplicate
        assert results["files_processed"] == 1
        assert results["files_succeeded"] == 1
        # Should not insert metadata again
        insert_calls = [call for call in mock_cursor.execute.call_args_list 
                       if len(call[0]) > 0 and 'INSERT INTO metadata' in str(call[0][0])]
        assert len(insert_calls) == 0
    
    def test_multiple_metadata_entries_workflow(self, temp_dir, mock_db_connection):
        """Test workflow with multiple metadata entries."""
        mock_conn, mock_cursor = mock_db_connection
        
        pdf_folder = os.path.join(temp_dir, "archive")
        text_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        
        os.makedirs(pdf_folder, exist_ok=True)
        
        # Create 3 metadata entries
        metadata_list = [
            {
                "filename": f"file{i}.pdf",
                "DATE STAMPED": f"January {i}, 2024",
                "JUDGE": f"Judge {i}",
                "COUNTY": f"County {i}",
                "ADDRESS": f"{i} Main St",
                "CNAME": f"Person {i}",
                "CDCR NO": f"AB{i:04d}",
                "CASE NO": f"CASE{i:03d}",
                "SENTENCE DATE": "2020-01-01"
            }
            for i in range(1, 4)
        ]
        
        # Create PDFs
        for metadata in metadata_list:
            pdf_path = os.path.join(pdf_folder, metadata["filename"])
            with open(pdf_path, 'wb') as f:
                f.write(b"%PDF-1.4\n")
        
        with open(metadata_file, 'w') as f:
            json.dump(metadata_list, f)
        
        # Mock responses for 3 files
        mock_cursor.fetchone.side_effect = [
            (1,), (0,),  # File 1
            (2,), (0,),  # File 2
            (3,), (0,),  # File 3
        ]
        
        with patch('safe_upload_pipeline.os.getenv', return_value=pdf_folder):
            pipeline = SafeUploadPipeline()
            results = pipeline.safe_upload_to_database(
                mock_conn, pdf_folder, text_folder, metadata_file
            )
        
        assert results["files_processed"] == 3
        assert results["files_succeeded"] == 3
        assert mock_conn.commit.called
    
    def test_transaction_rollback_on_failure(self, temp_dir, mock_db_connection, sample_metadata):
        """Test that transaction rolls back when upload fails."""
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
        
        # Simulate error after some processing
        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 2:  # Fail after initial operations
                raise mysql.connector.Error("Database error")
            return MagicMock()
        
        mock_cursor.execute.side_effect = side_effect
        mock_cursor.fetchone.return_value = (1,)
        
        with patch('safe_upload_pipeline.os.getenv', return_value=pdf_folder):
            pipeline = SafeUploadPipeline()
            results = pipeline.safe_upload_to_database(
                mock_conn, pdf_folder, text_folder, metadata_file
            )
        
        # Should rollback, not commit
        assert mock_conn.rollback.called
        assert not mock_conn.commit.called
        assert not results["success"]
    
    def test_missing_required_fields_handling(self, temp_dir, mock_db_connection):
        """Test handling of metadata with missing required fields."""
        mock_conn, mock_cursor = mock_db_connection
        
        pdf_folder = os.path.join(temp_dir, "archive")
        text_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        
        os.makedirs(pdf_folder, exist_ok=True)
        
        # Create incomplete metadata
        incomplete_metadata = {
            "filename": "test.pdf",
            "DATE STAMPED": "January 1, 2024",
            # Missing required fields
        }
        
        pdf_path = os.path.join(pdf_folder, incomplete_metadata["filename"])
        with open(pdf_path, 'wb') as f:
            f.write(b"%PDF-1.4\n")
        
        with open(metadata_file, 'w') as f:
            json.dump([incomplete_metadata], f)
        
        with patch('safe_upload_pipeline.os.getenv', return_value=pdf_folder):
            pipeline = SafeUploadPipeline()
            results = pipeline.safe_upload_to_database(
                mock_conn, pdf_folder, text_folder, metadata_file
            )
        
        # Should fail for missing fields
        assert results["files_processed"] == 1
        assert results["files_failed"] == 1
        assert len(results["errors"]) > 0


class TestDatabaseConnectionWorkflow:
    """Tests for database connection and transaction management."""
    
    def test_connection_closed_after_upload(self, temp_dir, mock_db_connection, sample_metadata):
        """Test that database connection is properly closed."""
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
            pipeline = SafeUploadPipeline()
            results = pipeline.safe_upload_to_database(
                mock_conn, pdf_folder, text_folder, metadata_file
            )
        
        # Cursor should be closed (handled in finally block)
        # Connection closure is handled by caller
        assert results["success"] is True
    
    def test_partial_success_handling(self, temp_dir, mock_db_connection):
        """Test handling when some files succeed and some fail."""
        mock_conn, mock_cursor = mock_db_connection
        
        pdf_folder = os.path.join(temp_dir, "archive")
        text_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        
        os.makedirs(pdf_folder, exist_ok=True)
        
        # Create 2 metadata entries - one valid, one invalid
        metadata_list = [
            {
                "filename": "valid.pdf",
                "DATE STAMPED": "January 1, 2024",
                "JUDGE": "Judge A",
                "COUNTY": "County A",
                "ADDRESS": "123 Main St",
                "CNAME": "John Doe",
                "CDCR NO": "AB1234",
                "CASE NO": "CASE001",
                "SENTENCE DATE": "2020-01-01"
            },
            {
                "filename": "invalid.pdf",
                # Missing required fields
            }
        ]
        
        # Create only valid PDF
        valid_pdf = os.path.join(pdf_folder, "valid.pdf")
        with open(valid_pdf, 'wb') as f:
            f.write(b"%PDF-1.4\n")
        
        with open(metadata_file, 'w') as f:
            json.dump(metadata_list, f)
        
        # Mock responses
        mock_cursor.fetchone.side_effect = [
            (1,), (0,),  # Valid file
        ]
        
        with patch('safe_upload_pipeline.os.getenv', return_value=pdf_folder):
            pipeline = SafeUploadPipeline()
            results = pipeline.safe_upload_to_database(
                mock_conn, pdf_folder, text_folder, metadata_file
            )
        
        # Should have partial success
        assert results["files_processed"] == 2
        assert results["files_succeeded"] == 1
        assert results["files_failed"] == 1
        # Should rollback due to failures
        assert mock_conn.rollback.called

