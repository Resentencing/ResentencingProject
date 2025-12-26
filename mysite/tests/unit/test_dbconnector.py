"""
Unit tests for dbconnector.py module.

Tests database connection, sanitization, and upload functionality.
"""
import pytest
import math
import os
import json
import tempfile
from unittest.mock import Mock, MagicMock, patch, mock_open
import mysql.connector

# Import the module to test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from dbconnector import sanitize_value, connect_to_database, upload_to_database


class TestSanitizeValue:
    """Tests for the sanitize_value function."""
    
    def test_sanitize_normal_values(self):
        """Test that normal values pass through unchanged."""
        assert sanitize_value("test") == "test"
        assert sanitize_value(123) == 123
        assert sanitize_value(3.14) == 3.14
        assert sanitize_value(None) is None
        assert sanitize_value([]) == []
        assert sanitize_value({}) == {}
    
    def test_sanitize_nan_float(self):
        """Test that NaN float values are converted to None."""
        nan_value = float('nan')
        result = sanitize_value(nan_value)
        assert result is None
        assert math.isnan(nan_value)  # Original value is still NaN
    
    def test_sanitize_infinity(self):
        """Test that infinity values pass through (not converted)."""
        inf_value = float('inf')
        result = sanitize_value(inf_value)
        assert result == inf_value
    
    def test_sanitize_negative_infinity(self):
        """Test that negative infinity values pass through."""
        neg_inf = float('-inf')
        result = sanitize_value(neg_inf)
        assert result == neg_inf


class TestConnectToDatabase:
    """Tests for the connect_to_database function."""
    
    @patch('dbconnector.mysql.connector.connect')
    @patch('dbconnector.database_config', {
        'host': 'localhost',
        'user': 'test_user',
        'password': 'test_password',
        'database': 'test_db'
    })
    def test_connect_success(self, mock_connect):
        """Test successful database connection."""
        mock_connection = MagicMock()
        mock_connect.return_value = mock_connection
        
        result = connect_to_database()
        
        assert result == mock_connection
        mock_connect.assert_called_once_with(
            host='localhost',
            user='test_user',
            password='test_password',
            database='test_db'
        )
    
    @patch('dbconnector.mysql.connector.connect')
    @patch('dbconnector.database_config', {
        'host': 'localhost',
        'user': 'test_user',
        'password': 'test_password',
        'database': 'test_db'
    })
    def test_connect_failure(self, mock_connect):
        """Test database connection failure."""
        mock_connect.side_effect = mysql.connector.Error("Connection failed")
        
        result = connect_to_database()
        
        assert result is None


class TestUploadToDatabase:
    """Tests for the upload_to_database function."""
    
    def test_upload_metadata_file_not_found(self, mock_db_connection, temp_dir):
        """Test that function returns early if metadata file doesn't exist."""
        mock_conn, mock_cursor = mock_db_connection
        metadata_file = os.path.join(temp_dir, "nonexistent.json")
        
        upload_to_database(mock_conn, temp_dir, temp_dir, metadata_file)
        
        # Should not execute any database operations
        mock_cursor.execute.assert_not_called()
    
    def test_upload_invalid_json(self, mock_db_connection, temp_dir):
        """Test handling of invalid JSON file."""
        mock_conn, mock_cursor = mock_db_connection
        metadata_file = os.path.join(temp_dir, "invalid.json")
        
        with open(metadata_file, 'w') as f:
            f.write("invalid json content {")
        
        upload_to_database(mock_conn, temp_dir, temp_dir, metadata_file)
        
        # Should not execute any database operations
        mock_cursor.execute.assert_not_called()
    
    def test_upload_empty_metadata_list(self, mock_db_connection, metadata_json_file):
        """Test handling of empty metadata list."""
        mock_conn, mock_cursor = mock_db_connection
        
        # Create empty metadata file
        with open(metadata_json_file, 'w') as f:
            json.dump([], f)
        
        upload_to_database(mock_conn, os.path.dirname(metadata_json_file), 
                          os.path.dirname(metadata_json_file), metadata_json_file)
        
        # Should not execute any database operations
        mock_cursor.execute.assert_not_called()
    
    def test_upload_sanitizes_nan_values(self, mock_db_connection, temp_dir, metadata_json_file):
        """Test that NaN values in metadata are sanitized before database insertion."""
        mock_conn, mock_cursor = mock_db_connection
        
        # Create metadata with NaN value
        metadata_with_nan = {
            "filename": "test.pdf",
            "DATE STAMPED": "January 1, 2024",
            "JUDGE": "Judge Doe",
            "COUNTY": "Orange",
            "ADDRESS": "123 Main St",
            "CNAME": "John Doe",
            "CDCR NO": "AB1234",
            "CASE NO": "CASE001",
            "SENTENCE DATE": "2020-01-01",
            "DAYS REDUCED": float('nan')  # NaN value
        }
        
        with open(metadata_json_file, 'w') as f:
            json.dump([metadata_with_nan], f)
        
        # Mock cursor responses
        mock_cursor.fetchone.side_effect = [
            (1,),  # pdf_id result
            (0,)   # existing_metadata count (no duplicates)
        ]
        
        # Mock file existence check
        archive_dir = os.path.join(temp_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        test_pdf_path = os.path.join(archive_dir, "test.pdf")
        with open(test_pdf_path, 'w') as f:
            f.write("dummy pdf content")
        
        with patch('dbconnector.os.path.exists', return_value=True):
            with patch('dbconnector.os.getenv', return_value=archive_dir):
                upload_to_database(mock_conn, temp_dir, temp_dir, metadata_json_file)
        
        # Verify that execute was called (indicating processing occurred)
        assert mock_cursor.execute.called
    
    def test_upload_skips_missing_required_fields(self, mock_db_connection, temp_dir, metadata_json_file):
        """Test that entries with missing required fields are skipped."""
        mock_conn, mock_cursor = mock_db_connection
        
        # Create metadata missing required field
        incomplete_metadata = {
            "filename": "test.pdf",
            "DATE STAMPED": "January 1, 2024",
            # Missing JUDGE, COUNTY, etc.
            "CDCR NO": "AB1234",
        }
        
        with open(metadata_json_file, 'w') as f:
            json.dump([incomplete_metadata], f)
        
        # Mock cursor to return None for pdf_id (simulating skip)
        mock_cursor.fetchone.return_value = None
        
        archive_dir = os.path.join(temp_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        test_pdf_path = os.path.join(archive_dir, "test.pdf")
        with open(test_pdf_path, 'w') as f:
            f.write("dummy pdf content")
        
        with patch('dbconnector.os.path.exists', return_value=True):
            with patch('dbconnector.os.getenv', return_value=archive_dir):
                upload_to_database(mock_conn, temp_dir, temp_dir, metadata_json_file)
        
        # Should attempt to insert PDF but skip metadata if pdf_id is None
        assert mock_cursor.execute.called
    
    def test_upload_skips_duplicate_metadata(self, mock_db_connection, temp_dir, metadata_json_file):
        """Test that duplicate metadata entries are skipped."""
        mock_conn, mock_cursor = mock_db_connection
        
        metadata = {
            "filename": "test.pdf",
            "DATE STAMPED": "January 1, 2024",
            "JUDGE": "Judge Doe",
            "COUNTY": "Orange",
            "ADDRESS": "123 Main St",
            "CNAME": "John Doe",
            "CDCR NO": "AB1234",
            "CASE NO": "CASE001",
            "SENTENCE DATE": "2020-01-01"
        }
        
        with open(metadata_json_file, 'w') as f:
            json.dump([metadata], f)
        
        # Mock cursor responses: pdf_id exists, and metadata already exists (count > 0)
        mock_cursor.fetchone.side_effect = [
            (1,),  # pdf_id result
            (1,)   # existing_metadata count (duplicate exists)
        ]
        
        archive_dir = os.path.join(temp_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        test_pdf_path = os.path.join(archive_dir, "test.pdf")
        with open(test_pdf_path, 'w') as f:
            f.write("dummy pdf content")
        
        with patch('dbconnector.os.path.exists', return_value=True):
            with patch('dbconnector.os.getenv', return_value=archive_dir):
                upload_to_database(mock_conn, temp_dir, temp_dir, metadata_json_file)
        
        # Should check for duplicates but not insert
        # The INSERT INTO metadata should not be called if duplicate exists
        insert_calls = [call for call in mock_cursor.execute.call_args_list 
                       if len(call[0]) > 0 and 'INSERT INTO metadata' in str(call[0][0])]
        assert len(insert_calls) == 0
    
    def test_upload_successful_insert(self, mock_db_connection, temp_dir, metadata_json_file):
        """Test successful metadata insertion."""
        mock_conn, mock_cursor = mock_db_connection
        
        metadata = {
            "filename": "test.pdf",
            "DATE STAMPED": "January 1, 2024",
            "JUDGE": "Judge Doe",
            "COUNTY": "Orange County",
            "ADDRESS": "123 Main St, City, CA",
            "CNAME": "John Doe",
            "CDCR NO": "AB1234",
            "CASE NO": "CASE001",
            "SENTENCE DATE": "2020-01-01",
            "COHORT": "2024-01",
            "RACE": "White",
            "ETHNICITY": "Non-Hispanic"
        }
        
        with open(metadata_json_file, 'w') as f:
            json.dump([metadata], f)
        
        # Mock cursor responses
        mock_cursor.fetchone.side_effect = [
            (1,),  # pdf_id result
            (0,)   # existing_metadata count (no duplicates)
        ]
        
        archive_dir = os.path.join(temp_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        test_pdf_path = os.path.join(archive_dir, "test.pdf")
        with open(test_pdf_path, 'w') as f:
            f.write("dummy pdf content")
        
        with patch('dbconnector.os.path.exists', return_value=True):
            with patch('dbconnector.os.getenv', return_value=archive_dir):
                upload_to_database(mock_conn, temp_dir, temp_dir, metadata_json_file)
        
        # Verify commit was called
        mock_conn.commit.assert_called_once()
        
        # Verify INSERT INTO metadata was called
        insert_calls = [call for call in mock_cursor.execute.call_args_list 
                       if len(call[0]) > 0 and 'INSERT INTO metadata' in str(call[0][0])]
        assert len(insert_calls) > 0
    
    def test_upload_handles_database_error(self, mock_db_connection, temp_dir, metadata_json_file):
        """Test handling of database errors during upload."""
        mock_conn, mock_cursor = mock_db_connection
        
        metadata = {
            "filename": "test.pdf",
            "DATE STAMPED": "January 1, 2024",
            "JUDGE": "Judge Doe",
            "COUNTY": "Orange",
            "ADDRESS": "123 Main St",
            "CNAME": "John Doe",
            "CDCR NO": "AB1234",
            "CASE NO": "CASE001",
            "SENTENCE DATE": "2020-01-01"
        }
        
        with open(metadata_json_file, 'w') as f:
            json.dump([metadata], f)
        
        # Simulate database error
        mock_cursor.execute.side_effect = mysql.connector.Error("Database error")
        
        archive_dir = os.path.join(temp_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        test_pdf_path = os.path.join(archive_dir, "test.pdf")
        with open(test_pdf_path, 'w') as f:
            f.write("dummy pdf content")
        
        with patch('dbconnector.os.path.exists', return_value=True):
            with patch('dbconnector.os.getenv', return_value=archive_dir):
                # Should not raise exception, should handle gracefully
                upload_to_database(mock_conn, temp_dir, temp_dir, metadata_json_file)
        
        # Cursor should still be closed even on error
        mock_cursor.close.assert_called_once()

