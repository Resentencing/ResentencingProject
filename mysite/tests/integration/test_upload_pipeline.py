"""
Integration tests for the complete upload pipeline.

Tests end-to-end file processing from PDF upload to database insertion.
"""
import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

# Import modules to test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from enhanced_upload_route import enhanced_upload_to_database_route
from safe_upload_pipeline import SafeUploadPipeline
from upload_safety import UploadSafetyManager
from extracttext import extract_text_from_pdfs
from tagextraction import extract_metadata_from_text_files


class TestEndToEndUploadPipeline:
    """Tests for complete upload pipeline from files to database."""
    
    def test_full_pipeline_success(self, temp_dir, mock_db_connection, sample_metadata_list):
        """Test complete upload pipeline with successful flow."""
        # Setup directories
        output_folder = os.path.join(temp_dir, "processed")
        extractions_folder = os.path.join(temp_dir, "extractions")
        archive_dir = os.path.join(temp_dir, "archive")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        
        os.makedirs(output_folder, exist_ok=True)
        os.makedirs(extractions_folder, exist_ok=True)
        os.makedirs(archive_dir, exist_ok=True)
        
        # Create sample PDF file
        pdf_file = os.path.join(output_folder, "test_file.pdf")
        with open(pdf_file, 'wb') as f:
            f.write(b"%PDF-1.4\n")  # Minimal PDF
        
        # Create sample text file (simulating extracted text)
        text_file = os.path.join(extractions_folder, "test_file.txt")
        with open(text_file, 'w') as f:
            f.write("Sample extracted text content")
        
        # Create metadata file
        with open(metadata_file, 'w') as f:
            json.dump(sample_metadata_list, f)
        
        # Create archive PDF
        archive_pdf = os.path.join(archive_dir, "test_file.pdf")
        shutil.copy2(pdf_file, archive_pdf)
        
        # Mock database connection
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.side_effect = [
            (1,),  # pdf_id
            (0,),  # duplicate check
        ]
        
        database_config = {
            "host": "localhost",
            "user": "test",
            "password": "test",
            "database": "test_db"
        }
        
        with patch('enhanced_upload_route.mysql.connector.connect', return_value=mock_conn):
            with patch('extracttext.extract_text_from_pdfs'):
                with patch('tagextraction.extract_metadata_from_text_files'):
                    with patch('enhanced_upload_route.os.path.exists', return_value=True):
                        with patch('enhanced_upload_route.os.getenv', return_value=archive_dir):
                            results = enhanced_upload_to_database_route(
                                database_config,
                                output_folder,
                                extractions_folder,
                                metadata_file,
                                archive_dir
                            )
        
        # Verify results
        assert results["files_processed"] >= 0
        assert "errors" in results
        assert "safety_report" in results
    
    def test_pipeline_text_extraction_failure(self, temp_dir, mock_db_config):
        """Test pipeline handles text extraction failures gracefully."""
        output_folder = os.path.join(temp_dir, "processed")
        extractions_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        archive_dir = os.path.join(temp_dir, "archive")
        
        os.makedirs(output_folder, exist_ok=True)
        
        with patch('extracttext.extract_text_from_pdfs', side_effect=Exception("Extraction failed")):
            results = enhanced_upload_to_database_route(
                mock_db_config,
                output_folder,
                extractions_folder,
                metadata_file,
                archive_dir
            )
        
        assert not results["success"]
        assert len(results["errors"]) > 0
        assert "extraction" in results["errors"][0].lower()
    
    def test_pipeline_metadata_extraction_failure(self, temp_dir, mock_db_config):
        """Test pipeline handles metadata extraction failures gracefully."""
        output_folder = os.path.join(temp_dir, "processed")
        extractions_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        archive_dir = os.path.join(temp_dir, "archive")
        
        os.makedirs(output_folder, exist_ok=True)
        os.makedirs(extractions_folder, exist_ok=True)
        
        with patch('extracttext.extract_text_from_pdfs'):
            with patch('tagextraction.extract_metadata_from_text_files', 
                      side_effect=Exception("Metadata extraction failed")):
                results = enhanced_upload_to_database_route(
                    mock_db_config,
                    output_folder,
                    extractions_folder,
                    metadata_file,
                    archive_dir
                )
        
        assert not results["success"]
        assert len(results["errors"]) > 0
        assert "metadata" in results["errors"][0].lower()
    
    def test_pipeline_database_connection_failure(self, temp_dir, mock_db_config):
        """Test pipeline handles database connection failures."""
        output_folder = os.path.join(temp_dir, "processed")
        extractions_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        archive_dir = os.path.join(temp_dir, "archive")
        
        os.makedirs(output_folder, exist_ok=True)
        os.makedirs(extractions_folder, exist_ok=True)
        
        import mysql.connector
        
        with patch('extracttext.extract_text_from_pdfs'):
            with patch('tagextraction.extract_metadata_from_text_files'):
                with patch('enhanced_upload_route.mysql.connector.connect', 
                          side_effect=mysql.connector.Error("Connection failed")):
                    results = enhanced_upload_to_database_route(
                        mock_db_config,
                        output_folder,
                        extractions_folder,
                        metadata_file,
                        archive_dir
                    )
        
        assert not results["success"]
        assert len(results["errors"]) > 0
        assert "connection" in results["errors"][0].lower() or "database" in results["errors"][0].lower()


class TestSafeUploadPipelineIntegration:
    """Integration tests for SafeUploadPipeline."""
    
    def test_safe_upload_single_file(self, temp_dir, mock_db_connection, sample_metadata):
        """Test safe upload of a single file."""
        mock_conn, mock_cursor = mock_db_connection
        
        # Setup
        pdf_folder = os.path.join(temp_dir, "archive")
        text_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        
        os.makedirs(pdf_folder, exist_ok=True)
        
        # Create PDF in archive
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
        
        # Create pipeline and test
        with patch('safe_upload_pipeline.os.getenv', return_value=pdf_folder):
            pipeline = SafeUploadPipeline()
            results = pipeline.safe_upload_to_database(
                mock_conn, pdf_folder, text_folder, metadata_file
            )
        
        # Verify
        assert results["files_processed"] == 1
        assert results["files_succeeded"] == 1
        assert results["files_failed"] == 0
        assert results["success"] is True
    
    def test_safe_upload_multiple_files(self, temp_dir, mock_db_connection):
        """Test safe upload of multiple files."""
        mock_conn, mock_cursor = mock_db_connection
        
        # Setup
        pdf_folder = os.path.join(temp_dir, "archive")
        text_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        
        os.makedirs(pdf_folder, exist_ok=True)
        
        # Create multiple metadata entries
        metadata_list = [
            {
                "filename": "file1.pdf",
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
                "filename": "file2.pdf",
                "DATE STAMPED": "January 2, 2024",
                "JUDGE": "Judge B",
                "COUNTY": "County B",
                "ADDRESS": "456 Oak Ave",
                "CNAME": "Jane Smith",
                "CDCR NO": "CD5678",
                "CASE NO": "CASE002",
                "SENTENCE DATE": "2020-02-01"
            }
        ]
        
        # Create PDFs
        for metadata in metadata_list:
            pdf_path = os.path.join(pdf_folder, metadata["filename"])
            with open(pdf_path, 'wb') as f:
                f.write(b"%PDF-1.4\n")
        
        # Create metadata file
        with open(metadata_file, 'w') as f:
            json.dump(metadata_list, f)
        
        # Mock cursor responses (2 files, each needs pdf_id and duplicate check)
        mock_cursor.fetchone.side_effect = [
            (1,), (0,),  # File 1: pdf_id, duplicate check
            (2,), (0,),  # File 2: pdf_id, duplicate check
        ]
        
        # Test
        with patch('safe_upload_pipeline.os.getenv', return_value=pdf_folder):
            pipeline = SafeUploadPipeline()
            results = pipeline.safe_upload_to_database(
                mock_conn, pdf_folder, text_folder, metadata_file
            )
        
        # Verify
        assert results["files_processed"] == 2
        assert results["files_succeeded"] == 2
        assert results["files_failed"] == 0
    
    def test_safe_upload_with_missing_pdf(self, temp_dir, mock_db_connection, sample_metadata):
        """Test safe upload when PDF file is missing."""
        mock_conn, mock_cursor = mock_db_connection
        
        pdf_folder = os.path.join(temp_dir, "archive")
        text_folder = os.path.join(temp_dir, "extractions")
        metadata_file = os.path.join(temp_dir, "metadata.json")
        
        os.makedirs(pdf_folder, exist_ok=True)
        # Don't create the PDF file
        
        with open(metadata_file, 'w') as f:
            json.dump([sample_metadata], f)
        
        pipeline = SafeUploadPipeline()
        results = pipeline.safe_upload_to_database(
            mock_conn, pdf_folder, text_folder, metadata_file
        )
        
        # Should fail for missing PDF
        assert results["files_processed"] == 1
        assert results["files_failed"] == 1
        assert results["files_succeeded"] == 0
        assert len(results["errors"]) > 0
    
    def test_safe_upload_rollback_on_error(self, temp_dir, mock_db_connection, sample_metadata):
        """Test that upload rolls back on critical errors."""
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
        
        # Simulate database error
        mock_cursor.execute.side_effect = Exception("Database error")
        
        pipeline = SafeUploadPipeline()
        results = pipeline.safe_upload_to_database(
            mock_conn, pdf_folder, text_folder, metadata_file
        )
        
        # Should rollback
        assert mock_conn.rollback.called
        assert not results["success"]
        assert results["files_failed"] > 0

