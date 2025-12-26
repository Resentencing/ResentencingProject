# Backend Testing Guide

This directory contains unit tests for the backend modules.

## Setup

1. **Install testing dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Verify pytest is installed:**
   ```bash
   pytest --version
   ```

## Running Tests

### Run all tests:
```bash
# From project root
pytest

# Or from mysite directory
cd mysite
pytest
```

### Run specific test file:
```bash
pytest tests/unit/test_dbconnector.py
pytest tests/unit/test_extracttext.py
pytest tests/unit/test_tagextraction.py
```

### Run with coverage report:
```bash
pytest --cov=mysite --cov-report=html
```

This will generate an HTML coverage report in `htmlcov/index.html`.

### Run with verbose output:
```bash
pytest -v
```

### Run specific test class or function:
```bash
pytest tests/unit/test_dbconnector.py::TestSanitizeValue
pytest tests/unit/test_dbconnector.py::TestSanitizeValue::test_sanitize_normal_values
```

## Test Structure

```
tests/
├── __init__.py
├── conftest.py          # Shared fixtures and configuration
├── unit/                 # Unit tests
│   ├── test_dbconnector.py
│   ├── test_extracttext.py
│   └── test_tagextraction.py
└── README.md
```

## Test Coverage

Current Phase 1 tests cover:

1. **dbconnector.py**
   - `sanitize_value()` - NaN handling
   - `connect_to_database()` - Connection success/failure
   - `upload_to_database()` - Full upload pipeline with various edge cases

2. **extracttext.py**
   - `extract_text_from_pdfs()` - PDF processing, skipping logic, multi-page handling

3. **tagextraction.py**
   - Metadata extraction logic (judge, county, address, names, dates)
   - CDCR number extraction from filenames
   - Case number parsing
   - Date extraction

## Writing New Tests

When adding new tests:

1. **Follow naming conventions:**
   - Test files: `test_*.py`
   - Test classes: `Test*`
   - Test functions: `test_*`

2. **Use fixtures from conftest.py:**
   - `temp_dir` - Temporary directory for file operations
   - `sample_metadata` - Sample metadata dictionary
   - `mock_db_connection` - Mock database connection
   - `mock_db_config` - Mock database configuration

3. **Mark tests appropriately:**
   ```python
   @pytest.mark.unit
   def test_something():
       pass
   
   @pytest.mark.integration
   def test_integration():
       pass
   ```

4. **Mock external dependencies:**
   - Database connections
   - File system operations
   - External API calls (OpenAI, etc.)

## Common Patterns

### Testing with temporary files:
```python
def test_with_temp_files(temp_dir):
    file_path = os.path.join(temp_dir, "test.txt")
    with open(file_path, 'w') as f:
        f.write("test content")
    # ... test logic
```

### Testing with mocked database:
```python
def test_database_operation(mock_db_connection):
    mock_conn, mock_cursor = mock_db_connection
    # ... test logic
```

### Testing with mocked file operations:
```python
@patch('module.os.path.exists')
def test_file_operation(mock_exists):
    mock_exists.return_value = True
    # ... test logic
```

## Continuous Integration

To run tests in CI/CD:

```bash
pytest --cov=mysite --cov-report=xml --junitxml=test-results.xml
```

## Troubleshooting

### Import errors:
- Make sure you're running tests from the project root
- Check that `sys.path` includes the `mysite` directory

### Database connection errors:
- Tests use mocked database connections, so real DB credentials aren't needed
- If you see connection errors, check that mocks are set up correctly

### File not found errors:
- Use the `temp_dir` fixture for temporary file operations
- Make sure file paths are constructed correctly

