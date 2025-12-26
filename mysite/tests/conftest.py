"""
Shared pytest fixtures and configuration for backend tests.
"""
import pytest
import os
import tempfile
import shutil
import json
from unittest.mock import Mock, MagicMock
from pathlib import Path


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_path = tempfile.mkdtemp()
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def sample_metadata():
    """Sample metadata dictionary for testing."""
    return {
        "filename": "test_file.pdf",
        "DATE STAMPED": "January 15, 2024",
        "JUDGE": "Honorable John Doe",
        "COUNTY": "Orange County",
        "ADDRESS": "123 Main St, City, CA 12345",
        "CNAME": "John Smith",
        "CDCR NO": "AB1234",
        "CASE NO": "CASE001",
        "SENTENCE DATE": "January 1, 2020",
        "COHORT": "2024-01",
        "RACE": "White",
        "ETHNICITY": "Non-Hispanic"
    }


@pytest.fixture
def sample_metadata_list(sample_metadata):
    """List of sample metadata entries."""
    return [sample_metadata]


@pytest.fixture
def metadata_json_file(temp_dir, sample_metadata_list):
    """Create a temporary JSON metadata file."""
    metadata_file = os.path.join(temp_dir, "metadata.json")
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(sample_metadata_list, f, indent=2)
    return metadata_file


@pytest.fixture
def mock_db_connection():
    """Mock database connection."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.commit = MagicMock()
    return mock_conn, mock_cursor


@pytest.fixture
def mock_db_config():
    """Mock database configuration."""
    return {
        "host": "localhost",
        "user": "test_user",
        "password": "test_password",
        "database": "test_db"
    }


@pytest.fixture
def sample_text_file(temp_dir):
    """Create a sample text file for extraction testing."""
    text_file = os.path.join(temp_dir, "test_file.txt")
    with open(text_file, 'w', encoding='utf-8') as f:
        f.write("This is a test text file.\n")
        f.write("It contains multiple lines.\n")
        f.write("For testing text extraction.")
    return text_file


@pytest.fixture
def sample_pdf_structure():
    """Sample text structure that mimics OCR output from a resentencing letter."""
    return [
        "January 15, 2024",
        "The Honorable John Doe",
        "Superior Court",
        "Orange County",
        "123 Main Street",
        "City, CA 12345",
        "Re: John Smith",
        "CDCR No: AB1234",
        "Case No: CASE001",
        "Date of Sentence: January 1, 2020",
        "",
        "Dear Judge Doe,",
        "This is a sample resentencing letter..."
    ]


@pytest.fixture
def env_vars(monkeypatch):
    """Set up environment variables for testing."""
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_USER", "test_user")
    monkeypatch.setenv("DB_PASSWORD", "test_password")
    monkeypatch.setenv("DB_NAME", "test_db")
    monkeypatch.setenv("ARCHIVE_DIR", "/test/archive")
    monkeypatch.setenv("OPENAI_API_KEY", "test_key_12345")

