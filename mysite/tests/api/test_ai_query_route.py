"""
API tests for the /query_ai route.

Tests AI-powered database query functionality.
"""
import pytest
from unittest.mock import patch, MagicMock
import mysql.connector

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
        with client.session_transaction() as sess:
            sess['logged_in'] = True
        yield client


class TestQueryAIRoute:
    """Tests for the /query_ai route."""
    
    def test_query_ai_no_query_provided(self, client):
        """Test query_ai with no query in request."""
        response = client.post('/query_ai', json={})
        assert response.status_code == 400
        assert response.is_json
        data = response.get_json()
        assert 'error' in data
        assert 'no query' in data['error'].lower() or 'query provided' in data['error'].lower()
    
    def test_query_ai_off_topic_response(self, client):
        """Unrelated queries get guidance, not open-ended chat."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '"OFF_TOPIC"'

        with patch('OCRWebApp.client.chat.completions.create', return_value=mock_response):
            response = client.post('/query_ai', json={'query': 'Write my homework essay about cats'})

            assert response.status_code == 200
            data = response.get_json()
            assert 'response' in data
            assert 'database' in data['response'].lower()

    def test_query_ai_site_help_resentencing_laws(self, client):
        """Project/methods questions use website-grounded answers with sources."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "This site covers CDCR-initiated resentencing under PC 1172.1.\n\n"
            "**Sources:** [Methods & GitHub](https://rscap.pythonanywhere.com/methods)"
        )

        with patch('OCRWebApp.client.chat.completions.create', return_value=mock_response):
            response = client.post('/query_ai', json={'query': 'Tell me about resentencing laws'})

            assert response.status_code == 200
            data = response.get_json()
            assert '1172.1' in data['response'] or 'Sources' in data['response']

    def test_query_ai_letters_count_uses_sql_heuristic(self, client):
        """Letter/count questions skip open chat and use the SQL pipeline."""
        mock_sql_gen = MagicMock()
        mock_sql_gen.choices = [MagicMock()]
        mock_sql_gen.choices[0].message.content = 'SELECT COUNT(*) AS total FROM pdfs'

        mock_interpretation = MagicMock()
        mock_interpretation.choices = [MagicMock()]
        mock_interpretation.choices[0].message.content = "The database contains 100 letters."

        with patch('OCRWebApp.client.chat.completions.create') as mock_openai:
            mock_openai.side_effect = [mock_sql_gen, mock_interpretation]

            with patch('OCRWebApp.query_database') as mock_db:
                mock_db.return_value = {
                    'status': 'success',
                    'data': [{'total': 100}],
                }

                response = client.post('/query_ai', json={'query': 'how many letters in database'})

                assert response.status_code == 200
                data = response.get_json()
                assert '100' in data['response']
                assert mock_openai.call_count == 2
    
    def test_query_ai_sql_query_success(self, client):
        """Test query_ai with a SQL query that succeeds."""
        # Mock classification response
        mock_classification = MagicMock()
        mock_classification.choices = [MagicMock()]
        mock_classification.choices[0].message.content = '"SQL_QUERY"'
        
        # Mock SQL generation response
        mock_sql_gen = MagicMock()
        mock_sql_gen.choices = [MagicMock()]
        mock_sql_gen.choices[0].message.content = 'SELECT COUNT(*) FROM pdfs'
        
        # Mock database query
        mock_db_results = [{'count': 10}]
        
        # Mock interpretation response
        mock_interpretation = MagicMock()
        mock_interpretation.choices = [MagicMock()]
        mock_interpretation.choices[0].message.content = "There are 10 cases in the database."
        
        with patch('OCRWebApp.client.chat.completions.create') as mock_openai:
            mock_openai.side_effect = [mock_classification, mock_sql_gen, mock_interpretation]
            
            with patch('OCRWebApp.mysql.connector.connect') as mock_connect:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_cursor.fetchall.return_value = mock_db_results
                mock_connect.return_value = mock_conn
                
                response = client.post('/query_ai', json={'query': 'How many cases are in the database?'})
                
                assert response.status_code == 200
                assert response.is_json
                data = response.get_json()
                assert 'response' in data
    
    def test_query_ai_sql_query_no_results(self, client):
        """Test query_ai with SQL query that returns no results."""
        mock_classification = MagicMock()
        mock_classification.choices = [MagicMock()]
        mock_classification.choices[0].message.content = '"SQL_QUERY"'
        
        mock_sql_gen = MagicMock()
        mock_sql_gen.choices = [MagicMock()]
        mock_sql_gen.choices[0].message.content = 'SELECT * FROM pdfs WHERE id = 99999'
        
        with patch('OCRWebApp.client.chat.completions.create') as mock_openai:
            mock_openai.side_effect = [mock_classification, mock_sql_gen]
            
            with patch('OCRWebApp.mysql.connector.connect') as mock_connect:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_cursor.fetchall.return_value = []  # No results
                mock_connect.return_value = mock_conn
                
                response = client.post('/query_ai', json={'query': 'Find case with ID 99999'})
                
                assert response.status_code == 200
                assert response.is_json
                data = response.get_json()
                # Should indicate no results found
                assert 'response' in data or 'error' in data or 'message' in data
    
    def test_query_ai_database_error(self, client):
        """Test query_ai with database connection error."""
        mock_classification = MagicMock()
        mock_classification.choices = [MagicMock()]
        mock_classification.choices[0].message.content = '"SQL_QUERY"'
        
        mock_sql_gen = MagicMock()
        mock_sql_gen.choices = [MagicMock()]
        mock_sql_gen.choices[0].message.content = 'SELECT COUNT(*) FROM pdfs'
        
        with patch('OCRWebApp.client.chat.completions.create') as mock_openai:
            mock_openai.side_effect = [mock_classification, mock_sql_gen]
            
            with patch('OCRWebApp.mysql.connector.connect', side_effect=mysql.connector.Error("DB error")):
                response = client.post('/query_ai', json={'query': 'How many cases?'})
                
                assert response.status_code == 200
                assert response.is_json
                data = response.get_json()
                # Should handle database error gracefully
                assert 'response' in data or 'error' in data or 'message' in data
    
    def test_query_ai_classification_failure(self, client):
        """Test query_ai when classification API fails."""
        mock_response = MagicMock()
        mock_response.choices = []  # No choices returned
        
        with patch('OCRWebApp.client.chat.completions.create', return_value=mock_response):
            response = client.post('/query_ai', json={'query': 'Test query'})
            
            assert response.status_code == 500
            assert response.is_json
            data = response.get_json()
            assert 'error' in data
            assert 'classify' in data['error'].lower() or 'failed' in data['error'].lower()
    
    def test_query_ai_invalid_classification(self, client):
        """Test query_ai with invalid classification response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '"INVALID_TYPE"'
        
        with patch('OCRWebApp.client.chat.completions.create', return_value=mock_response):
            response = client.post('/query_ai', json={'query': 'Test query'})
            
            assert response.status_code == 500
            assert response.is_json
            data = response.get_json()
            assert 'error' in data
            assert 'unexpected' in data['error'].lower() or 'classification' in data['error'].lower()
    
    def test_query_ai_sql_generation_failure(self, client):
        """Test query_ai when SQL generation fails."""
        mock_classification = MagicMock()
        mock_classification.choices = [MagicMock()]
        mock_classification.choices[0].message.content = '"SQL_QUERY"'
        
        mock_sql_gen = MagicMock()
        mock_sql_gen.choices = []  # No SQL generated
        
        with patch('OCRWebApp.client.chat.completions.create') as mock_openai:
            mock_openai.side_effect = [mock_classification, mock_sql_gen]
            
            response = client.post('/query_ai', json={'query': 'How many cases?'})
            
            assert response.status_code == 500
            assert response.is_json
            data = response.get_json()
            assert 'error' in data
            assert 'sql' in data['error'].lower() or 'generate' in data['error'].lower()
    
    def test_query_ai_invalid_sql(self, client):
        """Test query_ai when SQL is marked as invalid."""
        mock_classification = MagicMock()
        mock_classification.choices = [MagicMock()]
        mock_classification.choices[0].message.content = '"SQL_QUERY"'
        
        mock_sql_gen = MagicMock()
        mock_sql_gen.choices = [MagicMock()]
        mock_sql_gen.choices[0].message.content = 'INVALID'
        
        with patch('OCRWebApp.client.chat.completions.create') as mock_openai:
            mock_openai.side_effect = [mock_classification, mock_sql_gen]
            
            response = client.post('/query_ai', json={'query': 'Invalid query'})
            
            # Should handle invalid SQL gracefully
            assert response.status_code in [200, 400, 500]
            assert response.is_json


class TestQueryAIEdgeCases:
    """Tests for edge cases in query_ai route."""
    
    def test_query_ai_empty_string(self, client):
        """Test query_ai with empty string query."""
        response = client.post('/query_ai', json={'query': ''})
        assert response.status_code == 400
        assert response.is_json
    
    def test_query_ai_very_long_query(self, client):
        """Test query_ai with very long query string."""
        long_query = 'a' * 10000
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '"NATURAL_RESPONSE"'
        
        with patch('OCRWebApp.client.chat.completions.create', return_value=mock_response):
            response = client.post('/query_ai', json={'query': long_query})
            # Should handle long queries (may timeout or process)
            assert response.status_code in [200, 400, 500, 504]
    
    def test_query_ai_special_characters(self, client):
        """Test query_ai with special characters in query."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '"NATURAL_RESPONSE"'
        
        mock_response2 = MagicMock()
        mock_response2.choices = [MagicMock()]
        mock_response2.choices[0].message.content = "Response with special chars"
        
        with patch('OCRWebApp.client.chat.completions.create') as mock_openai:
            mock_openai.side_effect = [mock_response, mock_response2]
            
            response = client.post('/query_ai', json={'query': 'Test query with "quotes" and <tags>'})
            assert response.status_code == 200
            assert response.is_json











