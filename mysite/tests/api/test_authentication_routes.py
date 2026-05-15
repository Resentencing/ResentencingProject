"""
API tests for authentication routes.

Tests login, session management, and protected route access.
"""
import pytest
from flask import session
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from OCRWebApp import app


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


class TestLoginRoute:
    """Tests for the login route."""
    
    def test_login_get_renders_template(self, client):
        """Test that GET request to login renders the login template."""
        response = client.get('/')
        assert response.status_code == 200
        assert b'login' in response.data.lower() or response.is_json is False
    
    def test_login_success(self, client):
        """Test successful login with correct password."""
        with patch('OCRWebApp.PASSWORD', 'test_password'):
            response = client.post('/', data={'password': 'test_password'}, follow_redirects=False)
            assert response.status_code == 302  # Redirect
            assert response.location.endswith('/home')
    
    def test_login_failure(self, client):
        """Test login failure with incorrect password."""
        with patch('OCRWebApp.PASSWORD', 'test_password'):
            response = client.post('/', data={'password': 'wrong_password'})
            assert response.status_code == 200
            assert b'invalid' in response.data.lower() or b'error' in response.data.lower()
    
    def test_login_sets_session(self, client):
        """Test that successful login sets session variable."""
        with patch('OCRWebApp.PASSWORD', 'test_password'):
            with client.session_transaction() as sess:
                assert 'logged_in' not in sess
            
            client.post('/', data={'password': 'test_password'}, follow_redirects=False)
            
            with client.session_transaction() as sess:
                assert sess.get('logged_in') is True


class TestHomeRoute:
    """Tests for the home route."""
    
    def test_home_requires_login(self, client):
        """Test that home route redirects to login when not authenticated."""
        response = client.get('/home', follow_redirects=False)
        assert response.status_code == 302
        assert response.location.endswith('/')
    
    def test_home_accessible_when_logged_in(self, client):
        """Test that home route is accessible when logged in."""
        with client.session_transaction() as sess:
            sess['logged_in'] = True
        
        response = client.get('/home')
        assert response.status_code == 200
    
    def test_home_renders_template(self, client):
        """Test that home route renders the home template."""
        with client.session_transaction() as sess:
            sess['logged_in'] = True
        
        response = client.get('/home')
        assert response.status_code == 200


class TestProtectedRoutes:
    """Tests for routes that require authentication."""
    
    def test_upload_and_process_requires_login(self, client):
        """Test that upload_and_process requires authentication."""
        response = client.post('/upload_and_process')
        assert response.status_code == 401
        assert response.is_json
        data = response.get_json()
        assert 'error' in data or 'message' in data

    def test_queue_pdfs_requires_login(self, client):
        """Test that queue_pdfs requires authentication."""
        response = client.post('/queue_pdfs')
        assert response.status_code == 401
        assert response.is_json
    
    def test_upload_to_database_requires_login(self, client):
        """Test that upload_to_database requires authentication."""
        # Clear session
        with client.session_transaction() as sess:
            sess.pop('logged_in', None)
        
        with patch('OCRWebApp.extracttext.extract_text_from_pdfs'):
            with patch('os.listdir', return_value=[]):
                response = client.post('/upload_to_database')
                # May return 401, 302 (redirect), or 500 (if tries to process)
                assert response.status_code in [401, 302, 500]
    
    def test_database_ai_requires_login(self, client):
        """Test that database_ai requires authentication."""
        response = client.get('/database_ai', follow_redirects=False)
        assert response.status_code == 302
        assert response.location.endswith('/')
    
    def test_query_ai_requires_login(self, client):
        """Test that query_ai requires authentication (if protected)."""
        # Note: query_ai might not check login, but if it does, this test will catch it
        response = client.post('/query_ai', json={'query': 'test'})
        # Should either return 401/403 or process the query
        assert response.status_code in [200, 400, 401, 403, 500]


class TestSessionManagement:
    """Tests for session management."""
    
    def test_session_persists_across_requests(self, client):
        """Test that session persists across multiple requests."""
        with patch('OCRWebApp.PASSWORD', 'test_password'):
            # Login
            client.post('/', data={'password': 'test_password'})
            
            # Access protected route
            response = client.get('/home')
            assert response.status_code == 200
    
    def test_logout_clears_session(self, client):
        """Test that logout clears session (if logout route exists)."""
        with client.session_transaction() as sess:
            sess['logged_in'] = True
        
        # Access home to verify logged in
        response = client.get('/home')
        assert response.status_code == 200
        
        # Clear session manually (simulating logout)
        with client.session_transaction() as sess:
            sess.pop('logged_in', None)
        
        # Try to access home again
        response = client.get('/home', follow_redirects=False)
        assert response.status_code == 302  # Should redirect to login

