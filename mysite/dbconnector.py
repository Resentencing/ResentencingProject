import mysql.connector
import json
import os
import logging
import math  # Needed to check for NaN
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Database Configuration from environment variables
database_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
}

def connect_to_database():
    """
    Establishes a connection to the MySQL database using credentials from environment variables.
    Returns:
        connection (MySQLConnection): A live connection to the database, or None if connection fails.
    """
    try:
        connection = mysql.connector.connect(**database_config)
        logging.info("Successfully connected to the database.")
        return connection
    except mysql.connector.Error as err:
        logging.error(f"Database connection error: {err}")
        return None

def sanitize_value(value):
    """
    Checks for NaN (Not-a-Number) float values and converts them to `None`.

    This is important to prevent insertion errors into SQL tables since MySQL does not allow NaN values.

    Args:
        value: Any single value from the metadata dictionary.

    Returns:
        The same value unless it is a NaN float, in which case returns None.
    """
    if isinstance(value, float) and math.isnan(value):  # Check for NaN
        return None
    return value

def upload_to_database(connection, pdf_folder, text_folder, metadata_file):
    """
    Uploads PDF file references and their associated metadata into two tables:
    - `pdfs` table: Stores filename and file path.
    - `metadata` table: Stores case-related information linked by `pdf_id`.

    This function performs the following operations:
    1. Loads and sanitizes metadata from a JSON file.
    2. Skips entries with missing required fields.
    3. Skips inserting duplicate metadata based on existing `pdf_id`s.
    4. Inserts new PDF filenames and metadata into their respective tables.

    Args:
        connection (MySQLConnection): An active database connection.
        pdf_folder (str): Directory where PDF files are stored.
        text_folder (str): (Currently unused in this function but part of the full pipeline).
        metadata_file (str): Path to the JSON file containing extracted metadata.

    Returns:
        None. Commits changes directly to the database.
    """
    try:
        cursor = connection.cursor()

        if not os.path.exists(metadata_file):
            logging.error(f"Metadata file not found: {metadata_file}")
            return

        # Load metadata from JSON file
        with open(metadata_file, "r", encoding="utf-8") as file:
            try:
                metadata_list = json.load(file)
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing JSON metadata file: {e}")
                return

        if not metadata_list:
            logging.error("No metadata found in JSON file.")
            return

        for metadata in metadata_list:
            # Ensure all required fields are present
            required_fields = [
                "filename", "DATE STAMPED", "JUDGE", "COUNTY", "ADDRESS", "CNAME",
                "CDCR NO", "CASE NO", "SENTENCE DATE"
            ]
            optional_fields = [
                "COHORT", "PID NO", "INSTITUTION", "OLD RELEASE DATE", "DOCUMENTS PRINTED DATE",
                "LETTER CREATION DATE", "SECRETARY SEND DATE", "SEC DECISION", "COURT MAIL DATE",
                "COURT RESPONSE DATE", "RESENTENCING HEARING DATE", "ACTION TAKEN", "DAYS REDUCED",
                "YEARS REDUCED", "COST SAVINGS", "NOTES", "COMPLETION DATE", "POST RELEASE",
                "ISL DSL", "PAROLE ELIGIBILITY DATE", "RACE", "ETHNICITY"
            ]

            # Assign `None` to missing fields
            for field in required_fields + optional_fields:
                metadata.setdefault(field, None)

            # Convert NaN values to None
            for key in metadata:
                metadata[key] = sanitize_value(metadata[key])

            pdf_filename = metadata["filename"]
            archive_base_path = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
            pdf_path = os.path.join(archive_base_path, pdf_filename)

            # Insert PDF (if not exists)
            cursor.execute("""
                INSERT IGNORE INTO pdfs (filename, file_path) VALUES (%s, %s)
            """, (pdf_filename, pdf_path))
            cursor.execute("SELECT id FROM pdfs WHERE filename = %s", (pdf_filename,))
            pdf_id_result = cursor.fetchone()

            if pdf_id_result:
                pdf_id = pdf_id_result[0]
            else:
                logging.error(f"Failed to retrieve pdf_id for {pdf_filename}. Skipping entry.")
                continue

            # Check if metadata entry already exists
            cursor.execute("SELECT COUNT(*) FROM metadata WHERE pdf_id = %s", (pdf_id,))
            existing_metadata = cursor.fetchone()[0]

            if existing_metadata > 0:
                logging.info(f" Metadata already exists for PDF ID {pdf_id} ({pdf_filename}). Skipping entry.")
                continue  # Skip duplicate metadata

            # Insert metadata if no duplicate exists
            query = """
                INSERT INTO metadata (
                    pdf_id, date_stamped, judge, county, address, convict_name, cdcr_number,
                    case_number, sentence_date, cohort, pid_no, institution, old_release_date,
                    documents_printed_date, letter_creation_date, secretary_send_date, sec_decision,
                    court_mail_date, court_response_date, resentencing_hearing_date, action_taken,
                    days_reduced, years_reduced, cost_savings, notes, completion_date,
                    post_release, isl_dsl, parole_eligibility_date, race, ethnicity
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """

            values = (
                pdf_id, metadata["DATE STAMPED"], metadata["JUDGE"], metadata["COUNTY"], metadata["ADDRESS"],
                metadata["CNAME"], metadata["CDCR NO"], metadata["CASE NO"], metadata["SENTENCE DATE"],
                metadata.get("COHORT"), metadata.get("PID NO"), metadata.get("INSTITUTION"),
                metadata.get("OLD RELEASE DATE"), metadata.get("DOCUMENTS PRINTED DATE"), metadata.get("LETTER CREATION DATE"),
                metadata.get("SECRETARY SEND DATE"), metadata.get("SEC DECISION"), metadata.get("COURT MAIL DATE"),
                metadata.get("COURT RESPONSE DATE"), metadata.get("RESENTENCING HEARING DATE"), metadata.get("ACTION TAKEN"),
                metadata.get("DAYS REDUCED"), metadata.get("YEARS REDUCED"), metadata.get("COST SAVINGS"),
                metadata.get("NOTES"), metadata.get("COMPLETION DATE"), metadata.get("POST RELEASE"), metadata.get("ISL DSL"),
                metadata.get("PAROLE ELIGIBILITY DATE"), metadata.get("RACE"), metadata.get("ETHNICITY")
            )

            cursor.execute(query, values)

        connection.commit()
        logging.info("Data uploaded successfully.")

    except mysql.connector.Error as err:
        logging.error(f"Database error: {err}")
    finally:
        cursor.close()


if __name__ == "__main__":
    connection = connect_to_database()
    if connection:
        upload_to_database(connection, "OutputPDFsv2", "OCRextractions", "./Tag extraction related stuff/outputarrays.json")
        connection.close()
        logging.info("Database connection closed.")
