import mysql.connector
import json
import os
import logging
import math
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Database Configuration from environment variables
database_config = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "resentencing_db"),
}

def connect_to_database():
    """
    Establishes a connection to the MySQL database using credentials from environment variables.
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
    """
    if isinstance(value, float) and math.isnan(value):
        return None
    return value

def upload_to_database(connection, pdf_folder, text_folder, metadata_file):
    """
    Uploads PDF file references and their associated metadata into the database.
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

        # Get archive directory from environment
        archive_base_path = os.getenv("ARCHIVE_DIR", "./shared/archive_directory")

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
                continue

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