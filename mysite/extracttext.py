import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError

log = logging.getLogger(__name__)


def _extract_with_pypdf(file_path: str) -> str:
    reader = PdfReader(file_path, strict=False)
    parts: List[str] = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            parts.append(t)
    return "".join(parts)


def _extract_with_pymupdf(file_path: str) -> str:
    import fitz

    doc = fitz.open(file_path)
    try:
        parts: List[str] = []
        for page in doc:
            parts.append(page.get_text() or "")
        return "".join(parts)
    finally:
        doc.close()


def _extract_with_pdfminer(file_path: str) -> str:
    from pdfminer.high_level import extract_text as pdfminer_extract

    return pdfminer_extract(file_path) or ""


def extract_pdf_text(file_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Best-effort text extraction. Tries PyPDF2 (non-strict), PyMuPDF, pdfminer.

    Returns:
        (text, None) on success, or (None, combined_error_message) if every backend failed.
    """
    errors: List[str] = []
    for name, fn in (
        ("PyPDF2", _extract_with_pypdf),
        ("PyMuPDF", _extract_with_pymupdf),
        ("pdfminer", _extract_with_pdfminer),
    ):
        try:
            return fn(file_path), None
        except (PdfReadError, OSError, ValueError) as e:
            errors.append(f"{name}: {e}")
        except Exception as e:
            errors.append(f"{name}: {e}")
    return None, "; ".join(errors)


def extract_text_from_pdfs(
    input_folder: str, output_folder: str
) -> Dict[str, Any]:
    """
    Extracts text from all PDFs in the input folder and saves as text files in the output folder.
    Skips files that are already processed.

    Corrupt or unreadable PDFs are logged and omitted from output so the rest of the batch can finish.

    Returns:
        Stats dict: extracted, skipped_existing, failed (list of {file, error}).
    """
    os.makedirs(output_folder, exist_ok=True)
    stats: Dict[str, Any] = {"extracted": 0, "skipped_existing": 0, "failed": []}

    for filename in sorted(os.listdir(input_folder)):
        if not filename.endswith(".pdf"):
            continue
        file_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, filename.replace(".pdf", ".txt"))

        if Path(output_path).is_file():
            log.info("Skipping already processed file: %s", filename)
            print(f"Skipping already processed file: {filename}")
            stats["skipped_existing"] += 1
            continue

        text, err = extract_pdf_text(file_path)
        if err:
            log.error("Text extraction failed for %s (%s)", filename, err)
            stats["failed"].append({"file": filename, "error": err})
            continue

        with open(output_path, "w", encoding="utf-8", errors="ignore") as textfile:
            textfile.write(text)
        log.info("Processed and saved: %s", output_path)
        print(f"Processed and saved: {output_path}")
        stats["extracted"] += 1

    return stats


if __name__ == "__main__":
    input_folder = "OutputPDFsv2"  # Folder containing OCR'd PDFs
    output_folder = "OCRextractions"  # Folder to save extracted text files
    extract_text_from_pdfs(input_folder, output_folder)
