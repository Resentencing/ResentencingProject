"""
Unit tests for extracttext.py module.

Tests PDF text extraction functionality.
"""
import pytest
import os
import tempfile
import shutil
from unittest.mock import Mock, MagicMock, patch, mock_open
from pathlib import Path

from PyPDF2.errors import PdfReadError

# Import the module to test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from extracttext import extract_text_from_pdfs


class TestExtractTextFromPdfs:
    """Tests for the extract_text_from_pdfs function."""
    
    def test_extract_creates_output_folder(self, temp_dir):
        """Test that output folder is created if it doesn't exist."""
        input_folder = os.path.join(temp_dir, "input")
        output_folder = os.path.join(temp_dir, "output")
        os.makedirs(input_folder, exist_ok=True)
        
        # Output folder should not exist initially
        assert not os.path.exists(output_folder)
        
        # Create a dummy PDF file
        pdf_file = os.path.join(input_folder, "test.pdf")
        with open(pdf_file, 'wb') as f:
            f.write(b"%PDF-1.4\n")  # Minimal PDF header
        
        with patch('extracttext.PdfReader') as mock_pdf_reader:
            mock_reader = MagicMock()
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Sample text"
            mock_reader.pages = [mock_page]
            mock_pdf_reader.return_value = mock_reader
            
            extract_text_from_pdfs(input_folder, output_folder)
        
        # Output folder should now exist
        assert os.path.exists(output_folder)
    
    def test_extract_processes_pdf_files(self, temp_dir):
        """Test that PDF files are processed and text is extracted."""
        input_folder = os.path.join(temp_dir, "input")
        output_folder = os.path.join(temp_dir, "output")
        os.makedirs(input_folder, exist_ok=True)
        
        pdf_file = os.path.join(input_folder, "test.pdf")
        with open(pdf_file, 'wb') as f:
            f.write(b"%PDF-1.4\n")
        
        expected_text = "This is extracted text from the PDF"
        
        with patch('extracttext.PdfReader') as mock_pdf_reader:
            mock_reader = MagicMock()
            mock_page = MagicMock()
            mock_page.extract_text.return_value = expected_text
            mock_reader.pages = [mock_page]
            mock_pdf_reader.return_value = mock_reader
            
            extract_text_from_pdfs(input_folder, output_folder)
        
        # Check that text file was created
        output_text_file = os.path.join(output_folder, "test.txt")
        assert os.path.exists(output_text_file)
        
        # Check that text was written correctly
        with open(output_text_file, 'r', encoding='utf-8') as f:
            content = f.read()
            assert expected_text in content
    
    def test_extract_skips_non_pdf_files(self, temp_dir):
        """Test that non-PDF files are skipped."""
        input_folder = os.path.join(temp_dir, "input")
        output_folder = os.path.join(temp_dir, "output")
        os.makedirs(input_folder, exist_ok=True)
        
        # Create non-PDF files
        txt_file = os.path.join(input_folder, "test.txt")
        with open(txt_file, 'w') as f:
            f.write("Some text")
        
        doc_file = os.path.join(input_folder, "test.doc")
        with open(doc_file, 'w') as f:
            f.write("Some doc content")
        
        with patch('extracttext.PdfReader') as mock_pdf_reader:
            extract_text_from_pdfs(input_folder, output_folder)
        
        # PdfReader should not be called for non-PDF files
        mock_pdf_reader.assert_not_called()
    
    def test_extract_skips_already_processed_files(self, temp_dir):
        """Test that already processed files are skipped."""
        input_folder = os.path.join(temp_dir, "input")
        output_folder = os.path.join(temp_dir, "output")
        os.makedirs(input_folder, exist_ok=True)
        os.makedirs(output_folder, exist_ok=True)
        
        pdf_file = os.path.join(input_folder, "test.pdf")
        with open(pdf_file, 'wb') as f:
            f.write(b"%PDF-1.4\n")
        
        # Create existing output file (already processed)
        output_text_file = os.path.join(output_folder, "test.txt")
        with open(output_text_file, 'w') as f:
            f.write("Already processed")
        
        with patch('extracttext.PdfReader') as mock_pdf_reader:
            extract_text_from_pdfs(input_folder, output_folder)
        
        # PdfReader should not be called for already processed files
        mock_pdf_reader.assert_not_called()
        
        # Original content should remain unchanged
        with open(output_text_file, 'r') as f:
            assert f.read() == "Already processed"
    
    def test_extract_handles_multiple_pages(self, temp_dir):
        """Test extraction from PDFs with multiple pages."""
        input_folder = os.path.join(temp_dir, "input")
        output_folder = os.path.join(temp_dir, "output")
        os.makedirs(input_folder, exist_ok=True)
        
        pdf_file = os.path.join(input_folder, "multipage.pdf")
        with open(pdf_file, 'wb') as f:
            f.write(b"%PDF-1.4\n")
        
        page1_text = "Page 1 content"
        page2_text = "Page 2 content"
        page3_text = "Page 3 content"
        
        with patch('extracttext.PdfReader') as mock_pdf_reader:
            mock_reader = MagicMock()
            mock_page1 = MagicMock()
            mock_page1.extract_text.return_value = page1_text
            mock_page2 = MagicMock()
            mock_page2.extract_text.return_value = page2_text
            mock_page3 = MagicMock()
            mock_page3.extract_text.return_value = page3_text
            mock_reader.pages = [mock_page1, mock_page2, mock_page3]
            mock_pdf_reader.return_value = mock_reader
            
            extract_text_from_pdfs(input_folder, output_folder)
        
        # Check that all pages were extracted
        output_text_file = os.path.join(output_folder, "multipage.txt")
        assert os.path.exists(output_text_file)
        
        with open(output_text_file, 'r', encoding='utf-8') as f:
            content = f.read()
            assert page1_text in content
            assert page2_text in content
            assert page3_text in content
    
    def test_extract_handles_empty_pdf(self, temp_dir):
        """Test handling of PDFs with no extractable text."""
        input_folder = os.path.join(temp_dir, "input")
        output_folder = os.path.join(temp_dir, "output")
        os.makedirs(input_folder, exist_ok=True)
        
        pdf_file = os.path.join(input_folder, "empty.pdf")
        with open(pdf_file, 'wb') as f:
            f.write(b"%PDF-1.4\n")
        
        with patch('extracttext.PdfReader') as mock_pdf_reader:
            mock_reader = MagicMock()
            mock_page = MagicMock()
            mock_page.extract_text.return_value = ""  # Empty text
            mock_reader.pages = [mock_page]
            mock_pdf_reader.return_value = mock_reader
            
            extract_text_from_pdfs(input_folder, output_folder)
        
        # Text file should still be created (even if empty)
        output_text_file = os.path.join(output_folder, "empty.txt")
        assert os.path.exists(output_text_file)
    
    def test_extract_handles_encoding_errors(self, temp_dir):
        """Test that encoding errors are handled gracefully."""
        input_folder = os.path.join(temp_dir, "input")
        output_folder = os.path.join(temp_dir, "output")
        os.makedirs(input_folder, exist_ok=True)
        
        pdf_file = os.path.join(input_folder, "test.pdf")
        with open(pdf_file, 'wb') as f:
            f.write(b"%PDF-1.4\n")
        
        # Text with potential encoding issues
        problematic_text = "Text with special chars: éñ中文"
        
        with patch('extracttext.PdfReader') as mock_pdf_reader:
            mock_reader = MagicMock()
            mock_page = MagicMock()
            mock_page.extract_text.return_value = problematic_text
            mock_reader.pages = [mock_page]
            mock_pdf_reader.return_value = mock_reader
            
            # Should not raise encoding errors
            extract_text_from_pdfs(input_folder, output_folder)
        
        # File should be created successfully
        output_text_file = os.path.join(output_folder, "test.txt")
        assert os.path.exists(output_text_file)
    
    def test_extract_processes_multiple_pdfs(self, temp_dir):
        """Test that multiple PDF files in folder are all processed."""
        input_folder = os.path.join(temp_dir, "input")
        output_folder = os.path.join(temp_dir, "output")
        os.makedirs(input_folder, exist_ok=True)
        
        # Create multiple PDF files
        pdf1 = os.path.join(input_folder, "file1.pdf")
        pdf2 = os.path.join(input_folder, "file2.pdf")
        pdf3 = os.path.join(input_folder, "file3.pdf")
        
        for pdf_file in [pdf1, pdf2, pdf3]:
            with open(pdf_file, 'wb') as f:
                f.write(b"%PDF-1.4\n")
        
        call_count = 0
        
        def mock_pdf_reader_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            file_path = args[0] if args else ""
            mock_reader = MagicMock()
            mock_page = MagicMock()
            mock_page.extract_text.return_value = f"Text from {os.path.basename(file_path)}"
            mock_reader.pages = [mock_page]
            return mock_reader
        
        with patch('extracttext.PdfReader', side_effect=mock_pdf_reader_side_effect):
            extract_text_from_pdfs(input_folder, output_folder)
        
        # All three PDFs should be processed
        assert call_count == 3
        
        # All three text files should be created
        assert os.path.exists(os.path.join(output_folder, "file1.txt"))
        assert os.path.exists(os.path.join(output_folder, "file2.txt"))
        assert os.path.exists(os.path.join(output_folder, "file3.txt"))

    def test_extract_pymupdf_fallback_when_pypdf_fails(self, temp_dir):
        """PyPDF2 may reject marginally broken PDFs; later backends can still extract."""
        input_folder = os.path.join(temp_dir, "input")
        output_folder = os.path.join(temp_dir, "output")
        os.makedirs(input_folder, exist_ok=True)
        pdf_file = os.path.join(input_folder, "eof_bad.pdf")
        with open(pdf_file, "wb") as f:
            f.write(b"%PDF bogus")

        with patch("extracttext._extract_with_pypdf", side_effect=PdfReadError("EOF marker not found")), patch(
            "extracttext._extract_with_pymupdf", return_value="Recovered via PyMuPDF"
        ), patch("extracttext._extract_with_pdfminer", side_effect=AssertionError("should not need pdfminer")):
            stats = extract_text_from_pdfs(input_folder, output_folder)

        out = os.path.join(output_folder, "eof_bad.txt")
        assert os.path.exists(out)
        with open(out, "r", encoding="utf-8") as f:
            assert "Recovered via PyMuPDF" in f.read()
        assert stats["extracted"] == 1
        assert stats["failed"] == []

    def test_extract_records_failure_when_all_backends_fail(self, temp_dir):
        input_folder = os.path.join(temp_dir, "input")
        output_folder = os.path.join(temp_dir, "output")
        os.makedirs(input_folder, exist_ok=True)
        pdf_file = os.path.join(input_folder, "dead.pdf")
        with open(pdf_file, "wb") as f:
            f.write(b"%PDF")

        with patch("extracttext._extract_with_pypdf", side_effect=PdfReadError("x")), patch(
            "extracttext._extract_with_pymupdf", side_effect=RuntimeError("y")
        ), patch("extracttext._extract_with_pdfminer", side_effect=RuntimeError("z")):
            stats = extract_text_from_pdfs(input_folder, output_folder)

        assert stats["extracted"] == 0
        assert len(stats["failed"]) == 1
        assert stats["failed"][0]["file"] == "dead.pdf"
        assert not os.path.exists(os.path.join(output_folder, "dead.txt"))

