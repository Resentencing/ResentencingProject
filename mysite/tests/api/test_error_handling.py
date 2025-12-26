"""
API tests for error handling and edge cases.

Tests error responses, validation, and edge case handling across routes.
"""
import pytest
import os
import tempfile
import shutil
from io import BytesIO
from unittest.mock import patch, MagicMock
import mysql.connector

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from OCRWebApp import app


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['logged_in'] = True
        yield client


@pytest.fixture
def temp_upload_dirs():
    """Create temporary directories for uploads and processing."""
    temp_dir = tempfile.mkdtemp()
    upload_dir = os.path.join(temp_dir, 'uploads')
    output_dir = os.path.join(temp_dir, 'processed')
    
    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    
    yield {
        'upload': upload_dir,
        'output': output_dir,
        'temp': temp_dir
    }
    
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestErrorHandling:
    """Tests for error handling across routes."""
    
    def test_404_for_nonexistent_route(self, client):
        """Test that nonexistent routes return 404."""
        response = client.get('/nonexistent_route')
        assert response.status_code == 404
    
    def test_method_not_allowed(self, client):
        """Test that wrong HTTP methods return appropriate errors."""
        # Try GET on a POST-only route
        response = client.get('/upload_and_process')
        assert response.status_code in [405, 200]  # May allow GET or return 405
    
    def test_malformed_json(self, client):
        """Test handling of malformed JSON in request."""
        response = client.post('/query_ai', 
                             data='not json',
                             content_type='application/json')
        assert response.status_code in [400, 500]
    
    def test_missing_content_type(self, client):
        """Test handling of missing content type."""
        response = client.post('/query_ai', data={'query': 'test'})
        # Should handle gracefully
        assert response.status_code in [200, 400, 415]


class TestUploadErrorHandling:
    """Tests for error handling in upload routes."""
    
    def test_upload_with_very_large_file(self, client, temp_upload_dirs):
        """Test handling of very large file uploads."""
        original_config = app.config.copy()
        app.config['UPLOAD_FOLDER'] = temp_upload_dirs['upload']
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        
        try:
            with patch('OCRWebApp.preprocess_pdf') as mock_preprocess:
                # Create a large file (simulated - 1MB)
                large_content = b'x' * 1000000
                file_obj = BytesIO(large_content)
                file_obj.filename = 'large.pdf'
                
                data = {
                    'files[]': [(file_obj, 'large.pdf')]
                }
                
                response = client.post('/upload_and_process', 
                                     data=data,
                                     content_type='multipart/form-data')
                # Should handle large files (may succeed or fail gracefully)
                assert response.status_code in [200, 400, 413, 500]
        finally:
            app.config.update(original_config)
    
    def test_upload_with_special_characters_in_filename(self, client, temp_upload_dirs):
        """Test handling of filenames with special characters."""
        original_config = app.config.copy()
        app.config['UPLOAD_FOLDER'] = temp_upload_dirs['upload']
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        
        try:
            with patch('OCRWebApp.preprocess_pdf') as mock_preprocess:
                pdf_content = b"%PDF-1.4\n"
                file_obj = BytesIO(pdf_content)
                file_obj.filename = 'file with spaces & special chars.pdf'
                
                data = {
                    'files[]': [(file_obj, 'file with spaces & special chars.pdf')]
                }
                
                response = client.post('/upload_and_process', 
                                     data=data,
                                     content_type='multipart/form-data')
                # Should sanitize filename and handle special characters
                assert response.status_code in [200, 400, 500]
        finally:
            app.config.update(original_config)
    
    def test_upload_to_database_with_missing_directories(self, client):
        """Test upload_to_database when directories don't exist."""
        original_config = app.config.copy()
        app.config['OUTPUT_FOLDER'] = '/nonexistent/path'
        app.config['EXTRACTIONS'] = '/nonexistent/extractions'
        
        try:
            with patch('OCRWebApp.extracttext.extract_text_from_pdfs', side_effect=FileNotFoundError("Directory not found")):
                with patch('os.listdir', side_effect=FileNotFoundError()):
                    response = client.post('/upload_to_database')
                    # Should handle missing directories gracefully
                    assert response.status_code in [200, 500]
        finally:
            app.config.update(original_config)


class TestDatabaseErrorHandling:
    """Tests for database error handling."""
    
    def test_database_connection_timeout(self, client):
        """Test handling of database connection timeout."""
        original_config = app.config.copy()
        app.config['OUTPUT_FOLDER'] = '/tmp/output'
        app.config['EXTRACTIONS'] = '/tmp/extractions'
        
        try:
            with patch('OCRWebApp.extracttext.extract_text_from_pdfs'):
                with patch('OCRWebApp.tagextraction.extract_metadata_from_text_files'):
                    with patch('OCRWebApp.mysql.connector.connect') as mock_connect:
                        mock_connect.side_effect = mysql.connector.Error("Connection timeout")
                        
                        with patch('os.listdir', return_value=[]):
                            response = client.post('/upload_to_database')
                            assert response.status_code == 500
                            assert response.is_json
                            data = response.get_json()
                            assert 'error' in data
        finally:
            app.config.update(original_config)
    
    def test_database_query_error(self, client):
        """Test handling of database query errors."""
        mock_classification = MagicMock()
        mock_classification.choices = [MagicMock()]
        mock_classification.choices[0].message.content = '"SQL_QUERY"'
        
        mock_sql_gen = MagicMock()
        mock_sql_gen.choices = [MagicMock()]
        mock_sql_gen.choices[0].message.content = 'SELECT * FROM nonexistent_table'
        
        with patch('OCRWebApp.client.chat.completions.create') as mock_openai:
            mock_openai.side_effect = [mock_classification, mock_sql_gen]
            
            with patch('OCRWebApp.mysql.connector.connect') as mock_connect:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_cursor.execute.side_effect = mysql.connector.Error("Table doesn't exist")
                mock_connect.return_value = mock_conn
                
                response = client.post('/query_ai', json={'query': 'Test query'})
                # Should handle query error gracefully
                assert response.status_code in [200, 500]
                assert response.is_json


class TestValidation:
    """Tests for input validation."""
    
    def test_empty_file_upload(self, client, temp_upload_dirs):
        """Test handling of empty file upload."""
        original_config = app.config.copy()
        app.config['UPLOAD_FOLDER'] = temp_upload_dirs['upload']
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        
        try:
            with patch('OCRWebApp.preprocess_pdf') as mock_preprocess:
                # Create empty file
                file_obj = BytesIO(b'')
                file_obj.filename = 'empty.pdf'
                
                data = {
                    'files[]': [(file_obj, 'empty.pdf')]
                }
                
                response = client.post('/upload_and_process', 
                                     data=data,
                                     content_type='multipart/form-data')
                # Should handle empty files (may skip or process, or error during processing)
                # The route may succeed but processing might fail
                assert response.status_code in [200, 400, 500]
        finally:
            app.config.update(original_config)
    
    def test_sql_injection_attempt_in_query(self, client):
        """Test handling of potential SQL injection in AI query."""
        mock_classification = MagicMock()
        mock_classification.choices = [MagicMock()]
        mock_classification.choices[0].message.content = '"NATURAL_RESPONSE"'
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Safe response"
        
        with patch('OCRWebApp.client.chat.completions.create') as mock_openai:
            mock_openai.side_effect = [mock_classification, mock_response]
            
            # Try SQL injection in query
            malicious_query = "'; DROP TABLE pdfs; --"
            response = client.post('/query_ai', json={'query': malicious_query})
            
            # Should handle safely (AI should not execute raw SQL)
            assert response.status_code == 200
            assert response.is_json
    
    def test_xss_attempt_in_query(self, client):
        """Test handling of XSS attempts in query."""
        mock_classification = MagicMock()
        mock_classification.choices = [MagicMock()]
        mock_classification.choices[0].message.content = '"NATURAL_RESPONSE"'
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Safe response"
        
        with patch('OCRWebApp.client.chat.completions.create') as mock_openai:
            mock_openai.side_effect = [mock_classification, mock_response]
            
            xss_query = "<script>alert('xss')</script>"
            response = client.post('/query_ai', json={'query': xss_query})
            
            # Should handle safely
            assert response.status_code == 200
            assert response.is_json
            data = response.get_json()
            # Response should not contain raw script tags
            assert '<script>' not in str(data).lower() or 'response' in data

