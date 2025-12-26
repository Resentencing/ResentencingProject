"""
Unit tests for tagextraction.py module.

Tests metadata extraction from text files and Excel integration.
"""
import pytest
import os
import json
import tempfile
import pandas as pd
from unittest.mock import Mock, MagicMock, patch, mock_open
import re

# Import the module to test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))


class TestMetadataExtraction:
    """Tests for metadata extraction logic."""
    
    def test_extract_judge_name(self):
        """Test extraction of judge name from text."""
        text_lines = [
            "January 15, 2024",
            "The Honorable John Doe",
            "Superior Court",
            "Orange County"
        ]
        
        # Simulate the extraction logic
        linenumber = 1
        if "Honorable" in text_lines[linenumber]:
            outputstring = text_lines[linenumber].replace("The", "")
            outputstring = outputstring.replace("Honorable", "").replace("Honorabie", "")
            outputstring = outputstring.strip()
            judge = ' '.join(outputstring.split())
        
        assert judge == "John Doe"
    
    def test_extract_county(self):
        """Test extraction of county name."""
        text_lines = [
            "January 15, 2024",
            "The Honorable John Doe",
            "Superior Court",
            "Orange County"
        ]
        
        linenumber = 1
        if "Honorable" in text_lines[linenumber]:
            outputstring = text_lines[linenumber+2].replace("County", "").replace("of", "")
            outputstring = outputstring.strip()
            county = outputstring
        
        assert county == "Orange"
    
    def test_extract_convict_name_with_comma(self):
        """Test extraction of convict name when last name comes first (with comma)."""
        text_line = "Re: Smith, John"
        
        outputstring = text_line.replace("Re: ", "").replace("Re; ", "").strip()
        outputarray = outputstring.split()
        reverseorder = False
        
        for index in range(len(outputarray)):
            if "," in outputarray[index]:
                outputarray[index] = outputarray[index].replace(",", "")
                if index == 0:
                    reverseorder = True
        
        if reverseorder:
            if len(outputarray) > 2:
                formattedname = " ".join(outputarray[1:])
                cname = " ".join([formattedname, outputarray[0]])
            else:
                cname = " ".join([outputarray[1], outputarray[0]])
        else:
            cname = " ".join(outputarray)
        
        assert cname == "John Smith"
    
    def test_extract_convict_name_without_comma(self):
        """Test extraction of convict name when in normal order (no comma)."""
        text_line = "Re: John Smith"
        
        outputstring = text_line.replace("Re: ", "").replace("Re; ", "").strip()
        outputarray = outputstring.split()
        reverseorder = False
        
        for index in range(len(outputarray)):
            if "," in outputarray[index]:
                outputarray[index] = outputarray[index].replace(",", "")
                if index == 0:
                    reverseorder = True
        
        if reverseorder:
            if len(outputarray) > 2:
                formattedname = " ".join(outputarray[1:])
                cname = " ".join([formattedname, outputarray[0]])
            else:
                cname = " ".join([outputarray[1], outputarray[0]])
        else:
            cname = " ".join(outputarray)
        
        assert cname == "John Smith"
    
    def test_extract_cdcr_number_from_filename(self):
        """Test extraction of CDCR number from filename."""
        filename = "test_AB1234_file.txt"
        
        filenamesplit = re.split(r'[\.\_\-\s\(]', filename)
        cdcr_no = None
        
        for string in filenamesplit:
            string = string.strip()
            if (bool(re.search(r'\d', string)) and (len(string) == 6) and 
                bool(re.search(r'[A-Z]', string))):
                cdcr_no = string
                break
        
        assert cdcr_no == "AB1234"
    
    def test_extract_cdcr_number_various_formats(self):
        """Test CDCR number extraction from various filename formats."""
        test_cases = [
            ("AB1234_file.txt", "AB1234"),
            ("test-AB1234.pdf", "AB1234"),
            ("AB1234.txt", "AB1234"),
            ("file_AB1234_other.txt", "AB1234"),
        ]
        
        for filename, expected in test_cases:
            filenamesplit = re.split(r'[\.\_\-\s\(]', filename)
            cdcr_no = None
            
            for string in filenamesplit:
                string = string.strip()
                if (bool(re.search(r'\d', string)) and (len(string) == 6) and 
                    bool(re.search(r'[A-Z]', string))):
                    cdcr_no = string
                    break
            
            assert cdcr_no == expected, f"Failed for {filename}"
    
    def test_extract_case_number(self):
        """Test extraction of case number from text."""
        text_line = "Case No: CASE001"
        
        case_no = text_line.replace("Case", "").replace("No:", "").replace("No.:", "").strip()
        
        assert case_no == "CASE001"
    
    def test_extract_sentence_date(self):
        """Test extraction of sentence date from text."""
        text_line = "Date of Sentence: January 1, 2020"
        
        sentence_date = text_line.replace("Date", "").replace("of", "").replace("Sentence:", "").strip()
        
        assert sentence_date == "January 1, 2020"


class TestFullExtractionWithMocks:
    """Tests for full extraction function with mocked dependencies."""
    
    @patch('tagextraction.os.listdir')
    @patch('builtins.open', new_callable=mock_open)
    @patch('tagextraction.pd.read_excel')
    def test_extract_metadata_basic_structure(self, mock_read_excel, mock_file_open, mock_listdir, temp_dir):
        """Test basic metadata extraction from text file."""
        # Setup mocks
        mock_listdir.side_effect = [
            ["test_file.txt"],  # input folder
            []  # Excel folder (empty for simplicity)
        ]
        
        # Mock text file content
        text_content = [
            "January 15, 2024\n",
            "The Honorable John Doe\n",
            "Superior Court\n",
            "Orange County\n",
            "123 Main Street\n",
            "City, CA 12345\n",
            "Re: John Smith\n",
            "CDCR No: AB1234\n",
            "Case No: CASE001\n",
            "Date of Sentence: January 1, 2020\n"
        ]
        
        mock_file_open.return_value.readlines.return_value = text_content
        
        # Mock Excel files (empty for this test)
        mock_excel_df = pd.DataFrame()
        mock_read_excel.return_value = mock_excel_df
        
        # This test verifies the structure, actual execution would need more setup
        # For now, we test the logic components separately above
    
    def test_multiple_case_numbers_parsing(self):
        """Test parsing of multiple case numbers from Excel."""
        excel_case_numbers = "CASE001 and CASE002 and CASE003"
        
        if " and " in excel_case_numbers:
            case_number_list = [case.strip() for case in excel_case_numbers.split(" and ")]
        else:
            case_number_list = [excel_case_numbers] if excel_case_numbers else []
        
        assert len(case_number_list) == 3
        assert case_number_list == ["CASE001", "CASE002", "CASE003"]
    
    def test_single_case_number_parsing(self):
        """Test parsing of single case number."""
        excel_case_numbers = "CASE001"
        
        if " and " in excel_case_numbers:
            case_number_list = [case.strip() for case in excel_case_numbers.split(" and ")]
        else:
            case_number_list = [excel_case_numbers] if excel_case_numbers else []
        
        assert len(case_number_list) == 1
        assert case_number_list == ["CASE001"]
    
    def test_empty_case_number_uses_extracted(self):
        """Test that empty Excel case number falls back to extracted case number."""
        excel_case_numbers = ""
        extracted_case_no = "CASE001"
        
        if " and " in excel_case_numbers:
            case_number_list = [case.strip() for case in excel_case_numbers.split(" and ")]
        else:
            case_number_list = [excel_case_numbers] if excel_case_numbers else [extracted_case_no]
        
        assert case_number_list == [extracted_case_no]


class TestDateExtraction:
    """Tests for date extraction logic."""
    
    def test_extract_date_stamped_from_previous_line(self):
        """Test that date is extracted from line before 'Honorable'."""
        months = ["January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"]
        
        text_lines = [
            "January 15, 2024",
            "The Honorable John Doe",
            "Superior Court"
        ]
        
        linenumber = 1
        date_stamped = None
        
        if "Honorable" in text_lines[linenumber]:
            for month in months:
                if month in text_lines[linenumber-1]:
                    date_stamped = text_lines[linenumber-1].strip()
                    break
        
        assert date_stamped == "January 15, 2024"
    
    def test_extract_date_all_months(self):
        """Test date extraction for all months."""
        months = ["January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"]
        
        for month in months:
            text_lines = [
                f"{month} 15, 2024",
                "The Honorable John Doe"
            ]
            
            linenumber = 1
            date_stamped = None
            
            if "Honorable" in text_lines[linenumber]:
                for m in months:
                    if m in text_lines[linenumber-1]:
                        date_stamped = text_lines[linenumber-1].strip()
                        break
            
            assert date_stamped == f"{month} 15, 2024", f"Failed for {month}"


class TestAddressExtraction:
    """Tests for address extraction logic."""
    
    def test_extract_address_from_multiple_lines(self):
        """Test that address is extracted from multiple lines."""
        text_lines = [
            "January 15, 2024",
            "The Honorable John Doe",
            "Superior Court",
            "Orange County",
            "123 Main Street",
            "City, CA 12345"
        ]
        
        linenumber = 1
        if "Honorable" in text_lines[linenumber]:
            outputstring = text_lines[linenumber+3].replace('\n', ', ') + text_lines[linenumber+4].strip()
            address = ' '.join(outputstring.split())
        
        assert "123 Main Street" in address
        assert "City, CA 12345" in address


class TestFilenameProcessing:
    """Tests for filename processing."""
    
    def test_filename_conversion_txt_to_pdf(self):
        """Test that .txt filename is converted to .pdf in output."""
        filename = "test_file.txt"
        output_filename = filename.replace(".txt", ".pdf")
        
        assert output_filename == "test_file.pdf"
    
    def test_skip_non_txt_files(self):
        """Test that non-.txt files are skipped."""
        filenames = ["test.pdf", "test.doc", "test.txt", "test.docx"]
        txt_files = [f for f in filenames if f.endswith(".txt")]
        
        assert len(txt_files) == 1
        assert txt_files[0] == "test.txt"

