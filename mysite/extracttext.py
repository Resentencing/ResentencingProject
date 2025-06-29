import os
from pathlib import Path
from PyPDF2 import PdfReader

def extract_text_from_pdfs(input_folder, output_folder):
    """
    Extracts text from all PDFs in the input folder and saves as text files in the output folder.
    Skips files that are already processed.
    """
    os.makedirs(output_folder, exist_ok=True)

    for filename in os.listdir(input_folder):
        if filename.endswith(".pdf"):
            file_path = os.path.join(input_folder, filename)
            output_path = os.path.join(output_folder, filename.replace(".pdf", ".txt"))

            # Skip already processed files
            if Path(output_path).is_file():
                print(f"Skipping already processed file: {filename}")
                continue

            reader = PdfReader(file_path)
            with open(output_path, "w", encoding="utf-8", errors="ignore") as textfile:
                for page in reader.pages:
                    textfile.write(page.extract_text())
            print(f"Processed and saved: {output_path}")

if __name__ == "__main__":
    input_folder = "OutputPDFsv2"  # Folder containing OCR'd PDFs
    output_folder = "OCRextractions"  # Folder to save extracted text files
    extract_text_from_pdfs(input_folder, output_folder)
