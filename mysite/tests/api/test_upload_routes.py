"""
API tests for upload routes.

Tests file upload, processing, and database upload functionality.
"""
import pytest
import os
import tempfile
import shutil
from io import BytesIO
from unittest.mock import patch, MagicMock, mock_open
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
    extractions_dir = os.path.join(temp_dir, 'extractions')
    
    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(extractions_dir, exist_ok=True)
    
    yield {
        'upload': upload_dir,
        'output': output_dir,
        'extractions': extractions_dir,
        'temp': temp_dir
    }
    
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestUploadAndProcessRoute:
    """Tests for the /upload_and_process route."""
    
    def test_upload_and_process_success(self, client, temp_upload_dirs):
        """Test successful file upload and processing."""
        # Mock the app config
        original_config = app.config.copy()
        app.config['UPLOAD_FOLDER'] = temp_upload_dirs['upload']
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        
        try:
            with patch('OCRWebApp.preprocess_pdf') as mock_preprocess:
                # Create a mock PDF file
                pdf_content = b"%PDF-1.4\n"
                file_obj = BytesIO(pdf_content)
                file_obj.filename = 'test.pdf'
                
                data = {
                    'files[]': [(file_obj, 'test.pdf')]
                }
                
                response = client.post('/upload_and_process', 
                                     data=data,
                                     content_type='multipart/form-data')
                
                assert response.status_code == 200
                assert response.is_json
                result = response.get_json()
                assert result.get('status') == 'success'
        finally:
            app.config.update(original_config)
    
    def test_upload_and_process_no_files(self, client):
        """Test upload with no files."""
        response = client.post('/upload_and_process', data={})
        assert response.status_code == 200
        assert response.is_json
    
    def test_upload_and_process_invalid_file_type(self, client, temp_upload_dirs):
        """Test upload with invalid file type."""
        original_config = app.config.copy()
        app.config['UPLOAD_FOLDER'] = temp_upload_dirs['upload']
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        
        try:
            # Try to upload non-PDF file
            file_obj = BytesIO(b'not a pdf')
            file_obj.filename = 'test.txt'
            data = {
                'files[]': [(file_obj, 'test.txt')]
            }
            
            response = client.post('/upload_and_process', 
                                 data=data,
                                 content_type='multipart/form-data')
            
            # Should still return success (invalid files are skipped)
            assert response.status_code == 200
        finally:
            app.config.update(original_config)
    
    def test_upload_and_process_multiple_files(self, client, temp_upload_dirs):
        """Test uploading multiple files."""
        original_config = app.config.copy()
        app.config['UPLOAD_FOLDER'] = temp_upload_dirs['upload']
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        
        try:
            with patch('OCRWebApp.preprocess_pdf') as mock_preprocess:
                pdf_content = b"%PDF-1.4\n"
                file1 = BytesIO(pdf_content)
                file1.filename = 'file1.pdf'
                file2 = BytesIO(pdf_content)
                file2.filename = 'file2.pdf'
                
                data = {
                    'files[]': [
                        (file1, 'file1.pdf'),
                        (file2, 'file2.pdf')
                    ]
                }
                
                response = client.post('/upload_and_process', 
                                     data=data,
                                     content_type='multipart/form-data')
                
                assert response.status_code == 200
                assert mock_preprocess.call_count == 2
        finally:
            app.config.update(original_config)


class TestUploadToDatabaseRoute:
    """Tests for the /upload_to_database route."""
    
    def test_upload_to_database_success(self, client, temp_upload_dirs):
        """Test successful database upload."""
        original_config = app.config.copy()
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        app.config['EXTRACTIONS'] = temp_upload_dirs['extractions']
        
        try:
            with patch('OCRWebApp.extracttext.extract_text_from_pdfs'):
                with patch('OCRWebApp.tagextraction.extract_metadata_from_text_files'):
                    with patch('OCRWebApp.mysql.connector.connect') as mock_connect:
                        mock_conn = MagicMock()
                        mock_connect.return_value = mock_conn
                        
                        with patch('OCRWebApp.dbconnector.upload_to_database'):
                            with patch('OCRWebApp.clear_files'):
                                with patch('os.path.getsize', return_value=0):
                                    with patch('os.listdir', return_value=[]):
                                        response = client.post('/upload_to_database')
                                        
                                        assert response.status_code == 200
                                        assert response.is_json
                                        data = response.get_json()
                                        assert 'message' in data
                                        assert 'successfully' in data['message'].lower()
        finally:
            app.config.update(original_config)
    
    def test_upload_to_database_with_missed_entries(self, client, temp_upload_dirs):
        """Test database upload when there are missed entries."""
        original_config = app.config.copy()
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        app.config['EXTRACTIONS'] = temp_upload_dirs['extractions']
        
        try:
            with patch('OCRWebApp.extracttext.extract_text_from_pdfs'):
                with patch('OCRWebApp.tagextraction.extract_metadata_from_text_files'):
                    with patch('OCRWebApp.mysql.connector.connect') as mock_connect:
                        mock_conn = MagicMock()
                        mock_connect.return_value = mock_conn
                        
                        with patch('OCRWebApp.dbconnector.upload_to_database'):
                            with patch('OCRWebApp.clear_files'):
                                with patch('os.path.getsize', return_value=100):
                                    with patch('os.listdir', return_value=[]):
                                        response = client.post('/upload_to_database')
                                        
                                        assert response.status_code == 200
                                        assert response.is_json
                                        data = response.get_json()
                                        assert 'message' in data
                                        assert 'missed' in data['message'].lower() or 'couldn\'t find' in data['message'].lower()
        finally:
            app.config.update(original_config)
    
    def test_upload_to_database_db_error(self, client, temp_upload_dirs):
        """Test database upload with database error."""
        original_config = app.config.copy()
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        app.config['EXTRACTIONS'] = temp_upload_dirs['extractions']
        
        try:
            with patch('OCRWebApp.extracttext.extract_text_from_pdfs'):
                with patch('OCRWebApp.tagextraction.extract_metadata_from_text_files'):
                    with patch('OCRWebApp.mysql.connector.connect') as mock_connect:
                        mock_connect.side_effect = mysql.connector.Error("Database connection failed")
                        
                        with patch('os.listdir', return_value=[]):
                            response = client.post('/upload_to_database')
                            
                            assert response.status_code == 500
                            assert response.is_json
                            data = response.get_json()
                            assert 'error' in data
                            assert 'database' in data['error'].lower()
        finally:
            app.config.update(original_config)
    
    def test_upload_to_database_file_error(self, client, temp_upload_dirs):
        """Test database upload with file not found error."""
        original_config = app.config.copy()
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        app.config['EXTRACTIONS'] = temp_upload_dirs['extractions']
        
        try:
            with patch('OCRWebApp.extracttext.extract_text_from_pdfs', side_effect=FileNotFoundError("File not found")):
                with patch('os.listdir', return_value=[]):
                    response = client.post('/upload_to_database')
                    
                    assert response.status_code == 500
                    assert response.is_json
                    data = response.get_json()
                    assert 'error' in data
                    assert 'not found' in data['error'].lower()
        finally:
            app.config.update(original_config)
    
    def test_upload_to_database_unexpected_error(self, client, temp_upload_dirs):
        """Test database upload with unexpected error."""
        original_config = app.config.copy()
        app.config['OUTPUT_FOLDER'] = temp_upload_dirs['output']
        app.config['EXTRACTIONS'] = temp_upload_dirs['extractions']
        
        try:
            with patch('OCRWebApp.extracttext.extract_text_from_pdfs', side_effect=Exception("Unexpected error")):
                with patch('os.listdir', return_value=[]):
                    response = client.post('/upload_to_database')
                    
                    assert response.status_code == 500
                    assert response.is_json
                    data = response.get_json()
                    assert 'error' in data
        finally:
            app.config.update(original_config)

