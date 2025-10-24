from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, jsonify, abort
import os
import mysql
import openai
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import ocrmypdf
import shutil
import logging
import zipfile
import dbconnector
import extracttext
import tagextraction
from dbconnector import database_config, connect_to_database
import secrets
from openai import OpenAI
from dotenv import load_dotenv
import re
import json
import decimal
import datetime
import pymysql


Image.MAX_IMAGE_PIXELS = None


# from mysite.dbconnector_ssh import connect_to_database as connect_to_database_ssh

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI()

# TEMPORARY: Disable database connections for UI testing
DATABASE_DISABLED = False

# Maintain a queue of files to process
processing_queue = []

# Set up logging for easier debugging
logging.basicConfig(level=logging.DEBUG)

# Debug the actual key value
api_key = os.getenv("OPENAI_API_KEY")

# Ensure environment variables and API key setup
os.environ['PATH'] = '/home/RSCAP/.virtualenvs/myvirtualenv/bin:' + os.environ['PATH']

# Load OpenAI API key from environment variables
openai_api_key = os.getenv("OPENAI_API_KEY")
# Set To Required Variable
openai.api_key = openai_api_key
if not openai.api_key:
    logging.error("OpenAI API key not set. Please set OPENAI_API_KEY in environment variables.")
    raise RuntimeError("OpenAI API key not configured!")

# Flask app configuration
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # Securely generate a random secret key
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'processed'
app.config['EXTRACTIONS']='OCRextractions'

API_KEY = "samplekey12345678910657492756739205756382095866392028576820920101010101"

def _api_key_ok() -> bool:
    """
    Validates the incoming request by checking the 'X-API-Key' header against the fixed API_KEY.
    Uses constant-time comparison to avoid timing attacks.
    Returns:
        bool: True if header matches API_KEY, False otherwise.
    """
    incoming = request.headers.get("X-API-Key", "")
    return secrets.compare_digest(incoming, API_KEY)

def authorized() -> bool:
    """
    Determines if the current request is authorized.
    Authorization passes if EITHER:
      - the user is logged in on PythonAnywhere (session['logged_in'] is True), OR
      - the request provides a valid 'X-API-Key' header.
    Returns:
        bool: True if the request is authorized, False otherwise.
    """
    return bool(session.get("logged_in")) or _api_key_ok()

def require_auth_json():
    """
    Short-circuits unauthorized requests for JSON APIs.
    If the request is not authorized, returns a (401, JSON) response.
    If authorized, returns None so the route can continue.
    Returns:
        (Response | None): 401 JSON response if unauthorized, else None.
    """
    if not authorized():
        return jsonify({"error": "Unauthorized"}), 401

# Ensure upload and processed folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Temp Password
PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")

@app.route('/', methods=['GET', 'POST'])
def login():
    """
    Handles user login via a simple password form.
    If the submitted password matches the preset one, the user is logged in and redirected to the home page.
    Otherwise, it re-renders the login page with an error message.
    """
    if request.method == 'POST':
        if request.form['password'] == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error='Invalid password.')
    return render_template('login.html')

@app.route('/home')
def home():
    """
    Renders the main homepage only if the user is logged in.
    Otherwise, redirects the user to the login screen.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('home.html')

@app.route('/upload_and_process', methods=['POST'])
def upload_and_process_files():
    """
    Accepts and saves uploaded PDF files, then immediately processes them for OCR.
    This function verifies login, validates file type, and triggers the OCR pipeline.
    """
    if not session.get('logged_in'):
        return jsonify(status='error', message='User not logged in'), 401

    uploaded_files = request.files.getlist('files[]')
    for file in uploaded_files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            # Start processing right after saving
            preprocess_pdf(file_path, app.config['OUTPUT_FOLDER'])

    return jsonify(status='success', message='Files uploaded and processed successfully')

@app.route('/database_ai')
def database_ai():
    """
    Displays the AI-assisted database interface page if the user is logged in.
    Redirects to login otherwise.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('database_ai.html')

@app.route('/upload_to_database', methods=['POST'])
def upload_to_database_route():
    """
    Coordinates the full ETL (Extract, Transform, Load) pipeline:
    - Extracts text from processed PDFs
    - Generates metadata from text
    - Uploads both to the MySQL database
    Errors are caught and logged at each stage.
    """
    try:
        logging.info("Starting database upload process...")

        # Extract text from PDFs
        extracttext.extract_text_from_pdfs(app.config['OUTPUT_FOLDER'], app.config['EXTRACTIONS'])
        logging.info("Text extraction completed.")

        # Extract metadata from text files
        logging.info(f"Text files found for tagging: {os.listdir('OCRextractions')}")
        tagextraction.extract_metadata_from_text_files("OCRextractions", "./Jsontags/metadata.json")
        logging.info("Metadata extraction completed.")

        # Connect to the MySQL database
        conn = mysql.connector.connect(**database_config)
        logging.info("Connected to database successfully.")

        # Upload to database
        dbconnector.upload_to_database(conn, "/home/RSCAP/shared/archive_directory", "OCRextractions", "./Jsontags/metadata.json")
        conn.close()

        logging.info("Database upload completed successfully.")
        clear_files()
        ME_json_size=os.path.getsize('./logs/Missedentries.json')
        if(ME_json_size>0):
            return jsonify({"message": "file(s) couldn't find a matching entry in the logs.  Please check Missedentries.json"})
        else:
            return jsonify({"message": "Data successfully uploaded to the database."})

    except mysql.connector.Error as db_error:
        logging.error(f"Database error: {db_error}")
        return jsonify({"error": f"Database error: {str(db_error)}"}), 500

    except FileNotFoundError as file_error:
        logging.error(f"File error: {file_error}")
        return jsonify({"error": f"File not found: {str(file_error)}"}), 500

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

def query_database(ai_generated_sql):
    """
    Executes a given SQL query and returns structured results.
    Handles errors and ensures proper cleanup of connections and cursors.
    """
    try:
        conn = mysql.connector.connect(**database_config)
        cursor = conn.cursor(dictionary=True)

        logging.info(f"Executing SQL Query: {ai_generated_sql}")
        cursor.execute(ai_generated_sql)
        results = cursor.fetchall()
        cursor.close()
        conn.close()

        if not results:
            return {"status": "error", "message": "No relevant data found in the database."}

        return {"status": "success", "data": results}

    except mysql.connector.Error as e:
        logging.error(f"Database query error: {e}")
        return {"status": "error", "message": "Database unavailable at this time. Please try again later."}

def make_serializable(obj):
    """
    Ensures all Python objects returned from SQL queries are JSON-serializable.
    Converts Decimal to float and datetime to ISO format strings.
    """
    if isinstance(obj, decimal.Decimal):
        return float(obj)  # Convert Decimal → float
    elif isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()  # Convert datetime → string
    return obj  # Return unchanged for other types

@app.route('/query_ai', methods=['POST'])
def query_ai():
    """
    Main AI interface for user queries:
    - Classifies input as SQL-based or general
    - Generates SQL (if applicable) using OpenAI
    - Executes SQL query and interprets the result in natural language
    """

    # Auth Guard
    auth_fail = require_auth_json()
    if auth_fail:
        return auth_fail
    # /Auth Guard

    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    user_query = request.json.get('query')
    if not user_query:
        return jsonify({"error": "No query provided"}), 400

    try:
        # **Step 1: Classify Query Type**
        system_message_classification = """
        You are an AI assistant that determines whether a user query requires
        a database query or is a general natural language question.

        **Rules:**
        - A query should be classified as `"SQL_QUERY"` if it meets **at least one** of the following:
           **The question can be directly answered using existing database columns.**
           **The question is explicitly defined in your instructions as a database-related query.**

        - If neither condition is met, classify the query as `"NATURAL_RESPONSE"`.

        **Examples:**
        - `"How many cases are in the database?"` → `"SQL_QUERY"` (Explicitly defined + column count)
        - `"What is the success rate of resentencing?"` → `"SQL_QUERY"` (Interpreted from database columns)
        - `"Which judge presided over case RIF102091?"` → `"SQL_QUERY"` (Column-based query)
        - `"Tell me about the history of resentencing laws?"` → `"NATURAL_RESPONSE"` (No database match)
        - `"Explain the ethical implications of AI in law."` → `"NATURAL_RESPONSE"` (Not database-related)

        **Now classify this user query:**
        """

        classification_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_message_classification},
                {"role": "user", "content": user_query}
            ],
        )

        if not classification_response.choices:
            logging.error("Classification API did not return a response.")
            return jsonify({"error": "Failed to classify query. Try again later."}), 500

        query_type = classification_response.choices[0].message.content.strip().strip('"').strip("'")
        logging.info(f"Query Classification: {query_type}")

        # Ensure valid classification before proceeding
        if query_type not in ["SQL_QUERY", "NATURAL_RESPONSE"]:
            logging.error(f"Unexpected query classification: {query_type}")
            return jsonify({"error": "Unexpected classification response. Try again."}), 500

        # **Handle General AI Response (Non-SQL)**
        if query_type == "NATURAL_RESPONSE":
            logging.info("Processing as a general AI response.")
            chat_completion = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful legal assistant."},
                    {"role": "user", "content": user_query}
                ],
            )

            if not chat_completion.choices:
                logging.error("AI response failed.")
                return jsonify({"error": "Failed to generate AI response. Try again later."}), 500

            response_message = chat_completion.choices[0].message.content.strip()
            logging.debug(f"AI Response: {response_message}")
            return jsonify({"response": response_message})  # **EARLY RETURN**

        # **If AI Cannot Determine a Query Type, Alert the User**
        if query_type == "INVALID":
            logging.warning("AI could not classify the query.")
            return jsonify({"error": "I couldn't process your query. Please rephrase and try again."}), 400  # **EARLY RETURN**

        # **Only Proceed if Classified as "SQL_QUERY"**
        if query_type == "SQL_QUERY":
            logging.info("Recognized as a database-related query.")

            system_message_generate_sql = """
            You are an SQL assistant. Your task is to generate **ONLY valid, safe SQL queries**.

            **RULES:**
            - **You must ONLY use these tables and columns:**
              - `pdfs` (columns: `id`, `filename`, `file_path`)
              - `metadata` (columns: `id`, `pdf_id`, `date_stamped`, `judge`, `county`, `address`, `convict_name`, `cdcr_number`, `case_number`, `sentence_date`, `cohort`, `pid_no`, `institution`, `old_release_date`, `documents_printed_date`, `letter_creation_date`, `secretary_send_date`, `sec_decision`, `court_mail_date`, `court_response_date`, `resentencing_hearing_date`, `action_taken`, `days_reduced`, `years_reduced`, `cost_savings`, `notes`, `completion_date`, `post_release`, `isl_dsl`, `parole_eligibility_date`, "race", "ethnicity")
            - **You may only generate `SELECT`, `SHOW`, `DESCRIBE`, or `EXPLAIN` queries.**
            - **Do NOT generate `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, or `CREATE` statements.**
            - **If the query is not possible using the given schema, return "INVALID"**.
            - **Use `LIMIT 20` for listing results.**
            - **Do not use the word "Convict" in your response, use the word "Incarcerated person(s)" to describe such people.**
            - **Use `COUNT(DISTINCT column_name)` for unique counts.**

            **Now generate an SQL query based on this user request:**
            """

            sql_generation_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_message_generate_sql},
                    {"role": "user", "content": user_query}
                ],
            )

            if not sql_generation_response.choices:
                logging.error(" AI failed to generate an SQL query.")
                return jsonify({"error": "Failed to generate SQL query. Try again later."}), 500

            ai_generated_sql = sql_generation_response.choices[0].message.content.strip()
            logging.debug(f" AI-Generated SQL Query (Raw): {ai_generated_sql}")

            # Sanitize and Validate AI-Generated SQL
            ai_generated_sql = re.sub(r"```(sql)?", "", ai_generated_sql).strip()
            ai_generated_sql = ai_generated_sql.strip("`")

            if ai_generated_sql.upper() == "INVALID":
                logging.warning("AI could not generate a valid SQL query.")

                # **New Response: AI Doesn't Know How to Define Query**
                system_message_unknown_query = f"""
                You are an AI assistant responding to a user who asked a question that you couldn't translate into a database query.

                The question was: "{user_query}"

                You should explain to the user that you do not have a definition for the requested term. Do **NOT** apologize unnecessarily. If the term is ambiguous (like "success rate"), guide the user to rephrase.

                **Example Responses:**
                - User: "What is the success rate of Orange County?"
                  AI: "I don't have a clear definition for success rate in this context. Could you clarify what aspect of success you're referring to?"
                - User: "How effective is resentencing?"
                  AI: "I'm not sure how to measure effectiveness in this case. Could you specify a metric, like reduced prison time or cost savings?"

                **Now generate a response based on the user's original query:**
                """

                unknown_query_response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_message_unknown_query}
                    ],
                )

                if not unknown_query_response.choices:
                    logging.error("AI failed to generate a response for an unknown query.")
                    return jsonify({"error": "I'm not sure how to define that query. Could you clarify?"}), 200  # **SAFE RESPONSE**

                final_unknown_response = unknown_query_response.choices[0].message.content.strip()
                logging.debug(f"AI Unknown Query Response: {final_unknown_response}")

                return jsonify({"response": final_unknown_response})  # **EARLY RETURN**


            # **Step 3: Execute AI-Generated SQL**
            database_response = query_database(ai_generated_sql)

            if database_response["status"] == "error":
                return jsonify({"error": database_response["message"]})  # **EARLY RETURN**

            # **Ensure database response has data**
            if "data" not in database_response or not database_response["data"]:
                return jsonify({"response": "No relevant data found in the database."})  # **EARLY RETURN**

            # Convert the list of dictionaries into a string to prevent frontend errors
            formatted_response = json.dumps(database_response["data"], default=str)

            # **Step 4: AI-Interpret Database Results into Natural Language**
            system_message_interpret_results = """
            You are an AI assistant that translates structured database results into natural language.
            Your goal is to take raw SQL output and respond with a **clear, concise, and human-readable answer**.

            **Examples:**
            - Input: `[{"total_cases": 147}]`
              Output: `"The database contains 147 cases."`
            - Input: `[{"judge": "Alan M. Simpson"}]`
              Output: `"The judge presiding over the case was Alan M. Simpson."`
            - Input: `[{"unique_counties": 22}]`
              Output: `"There are 22 unique counties represented in the database."`
            - Input: `[{"cost_savings": 500000}]`
              Output: `"The total cost savings recorded is $500,000."`

            **Do not use the word "Convict" in your response, use the word "Incarcerated person(s)" to describe such people.**

            **Now, convert this SQL result into a user-friendly response:**
            """

            ai_interpretation_prompt = f"{system_message_interpret_results}\nResults: {json.dumps(database_response['data'], default=str)}"

            interpretation_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": ai_interpretation_prompt}
                ],
            )

            if not interpretation_response.choices:
                logging.error("AI interpretation failed.")
                return jsonify({"error": "Failed to interpret database results. Try again later."}), 500

            final_response = interpretation_response.choices[0].message.content.strip()
            logging.debug(f"AI Final Interpretation: {final_response}")

            return jsonify({"response": final_response})  # **EARLY RETURN**

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": "An unexpected error occurred. Please try again later."}), 500


@app.route('/upload_excel', methods=['POST'])
def upload_excel_files():
    """
    Accepts uploaded Excel files and saves them to a server-side directory.
    Ensures the folder exists and returns a success/failure response.
    """
    if not session.get('logged_in'):
        return jsonify(status='error', message='User not logged in'), 401

    # Create the folder if it doesn't exist
    excel_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Excel')
    os.makedirs(excel_folder, exist_ok=True)

    # 'excel_files[]' is the field name from the JS
    if 'excel_files[]' not in request.files:
        return jsonify(status='error', message='No Excel files uploaded'), 400

    uploaded_excel_files = request.files.getlist('excel_files[]')
    if not uploaded_excel_files:
        return jsonify(status='error', message='No Excel files selected'), 400

    saved_files = []
    for file in uploaded_excel_files:
        filename = secure_filename(file.filename)
        # Save each file to the Excel folder
        if filename:  # Make sure it's not empty
            save_path = os.path.join(excel_folder, filename)
            file.save(save_path)
            saved_files.append(filename)

    if saved_files:
        return jsonify(status='success', message=f"Uploaded {len(saved_files)} Excel files.")
    else:
        return jsonify(status='error', message="No valid files were saved.")

@app.route('/download_files')
def download_all_files():
    """
    Compresses all processed PDF files into a ZIP archive and returns it for download.
    Skips already zipped files and handles empty folder scenarios.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    output_folder = app.config['OUTPUT_FOLDER']
    zip_path = os.path.join(output_folder, 'Corrected_Files.zip')

    # Check if there are files to zip
    files_to_zip = [f for f in os.listdir(output_folder) if f != 'Corrected_Files.zip' and os.path.isfile(os.path.join(output_folder, f))]
    if not files_to_zip:
        return jsonify(status='error', message='No files to download'), 404

    # Remove existing zip file if it exists
    if os.path.exists(zip_path):
        os.remove(zip_path)

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file in files_to_zip:
                zf.write(os.path.join(output_folder, file), file)

        return send_from_directory(output_folder, 'Corrected_Files.zip', as_attachment=True)
    except FileNotFoundError:
        abort(404, description="File not found")
    except Exception as e:
        app.logger.error('Failed to create or send zip file: %s', e)
        abort(500, description="Internal Server Error")


@app.route('/clear_files', methods=['POST'])
def clear_files():
    """
    Deletes all uploaded PDFs, processed files, and extracted OCR data from the server.
    Recreates required directories afterward to prevent errors on future uploads.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401

    try:
        # Clear uploaded and processed files
        shutil.rmtree(app.config['UPLOAD_FOLDER'], ignore_errors=True)
        shutil.rmtree(app.config['OUTPUT_FOLDER'], ignore_errors=True)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
        shutil.rmtree(app.config['EXTRACTIONS'], ignore_errors=True)
        os.makedirs(app.config['EXTRACTIONS'], exist_ok=True)

        return jsonify({"status": "success", "message": "All files have been cleared."})
    except Exception as e:
        logging.error(f"Error clearing files: {e}")
        return jsonify({"status": "error", "message": f"Error clearing files: {str(e)}"}), 500

@app.route('/clear_excel', methods=['POST'])
def clear_excel():
    """
    Clears all uploaded Excel files by deleting and recreating the Excel folder.
    Used for cleanup before a new batch upload.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401

    try:
        excel_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Excel')

        # Remove entire Excel folder and recreate it
        shutil.rmtree(excel_folder, ignore_errors=True)
        os.makedirs(excel_folder, exist_ok=True)

        return jsonify({"status": "success", "message": "Excel files have been cleared."})
    except Exception as e:
        app.logger.error(f"Error clearing Excel files: {e}")
        return jsonify({"status": "error", "message": f"Error clearing Excel files: {str(e)}"}), 500

def allowed_file(filename):
    """
    Validates uploaded file types.
    Only accepts files with a `.pdf` extension.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf'}

def correct_orientation(image_path):
    """
    Uses Tesseract to detect and correct rotation in scanned page images.
    Helps ensure readable OCR results regardless of scan direction.
    """
    try:
        image = Image.open(image_path)
        image = image.convert('RGB')
        osd = pytesseract.image_to_osd(image)
        rotation = int(osd.split("\nRotate: ")[1].split("\n")[0])
        return rotation
    except pytesseract.TesseractError as e:
        logging.error(f"Tesseract failed to process {image_path}: {e}")
        return None  # Return None to indicate an error occurred

def preprocess_pdf(file_path, output_folder):
    """
    Converts each PDF page to an image, corrects orientation, reassembles into a new PDF,
    and applies OCR to make the final output searchable.
    Temporary images are cleaned up after processing.
    """
    temp_dir = os.path.join(output_folder, "temp_images")
    os.makedirs(temp_dir, exist_ok=True)
    corrected_images = []

    try:
        pdf_document = fitz.open(file_path)
        for page_num in range(len(pdf_document)):
            try:
                page = pdf_document.load_page(page_num)
                pix = page.get_pixmap(dpi=300)
                image_path = os.path.join(temp_dir, f"page_{page_num+1}.jpg")
                pix.save(image_path)

                # Attempt to get the rotation angle
                rotation = correct_orientation(image_path)
                if rotation is not None and rotation != 0:
                    image = Image.open(image_path)
                    rotated_image = image.rotate(-rotation, expand=True)
                    rotated_image.save(image_path)

                corrected_images.append(image_path)
            except Exception as e:
                logging.error(f"Error processing page {page_num + 1} of {file_path}: {e}")
                continue  # Skip this page and continue to the next one

        if not corrected_images:
            logging.error(f"No valid pages processed for {file_path}. Skipping OCR.")
            return  # Skip OCR processing if no valid pages are found

        corrected_pdf_path = os.path.join(output_folder, f"corrected_{os.path.basename(file_path)}")
        images = [Image.open(img).convert('RGB') for img in corrected_images]

        # Save the corrected images as a single PDF
        images[0].save(corrected_pdf_path, save_all=True, append_images=images[1:])

        # Run OCR on the corrected PDF
        try:
            ocrmypdf.ocr(corrected_pdf_path, corrected_pdf_path, deskew=True, output_type='pdfa')
        except ocrmypdf.exceptions.PriorOcrFoundError:
            logging.warning(f"The file {corrected_pdf_path} already contains OCR text. Skipping OCR process.")
        except Exception as e:
            logging.error(f"Error during OCR processing of {corrected_pdf_path}: {e}")

        # === Archive the final corrected PDF if it doesn't already exist ===
        archive_dir = '/home/RSCAP/shared/archive_directory'
        os.makedirs(archive_dir, exist_ok=True)

        archive_path = os.path.join(archive_dir, os.path.basename(corrected_pdf_path))

        if not os.path.exists(corrected_pdf_path):
            logging.error(f"Corrected PDF does not exist: {corrected_pdf_path}")
        elif not os.path.exists(archive_path):
            try:
                shutil.copy2(corrected_pdf_path, archive_path)
                logging.info(f"Archived file to: {archive_path}")
            except Exception as e:
                logging.error(f"Failed to archive {corrected_pdf_path} → {archive_path}: {e}")
        else:
            logging.info(f"File already exists in archive, skipping: {archive_path}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# Backend File Viewer Download Files
@app.route('/download/<filename>')
def download_file(filename):
    # Use environment variable for archive directory, with fallback for local development
    archive_dir = os.getenv('ARCHIVE_DIR', '/home/RSCAP/shared/archive_directory')

    # For local development, use the shared directory in the project
    if not os.path.exists(archive_dir):
        archive_dir = os.path.join(os.getcwd(), 'shared', 'archive_directory')

    if not os.path.exists(os.path.join(archive_dir, filename)):
        return "File not found", 404

    return send_from_directory(archive_dir, filename, as_attachment=True)

# Backend File Viewer
@app.route('/fileviewer')
def file_viewer():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    sort_field = request.args.get('sort', 'filename')
    direction = request.args.get('direction', 'desc').lower()
    search_term = request.args.get('search', '').strip()
    allowed_fields = {
        'filename': 'pdfs.filename',
        'case_number': 'metadata.case_number',
        'cdcr_number': 'metadata.cdcr_number',
        'date_stamped': 'metadata.date_stamped'
    }
    sort_column = allowed_fields.get(sort_field, 'pdfs.filename')
    sort_direction = 'ASC' if direction == 'asc' else 'DESC'

    where_clause = ""
    params = []
    if search_term:
        where_clause = ("WHERE pdfs.filename LIKE %s "
                        "OR metadata.case_number LIKE %s "
                        "OR metadata.cdcr_number LIKE %s "
                        "OR metadata.date_stamped LIKE %s")
        like_term = f"%{search_term}%"
        params = [like_term, like_term, like_term, like_term]

    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306))
    )
    try:
        with connection.cursor() as cursor:
            query = f"""
                SELECT pdfs.filename, pdfs.file_path, metadata.case_number, metadata.cdcr_number, metadata.date_stamped
                FROM pdfs
                LEFT JOIN metadata ON pdfs.id = metadata.pdf_id
                {where_clause}
                ORDER BY {sort_column} {sort_direction}
            """
            cursor.execute(query, params)
            results = cursor.fetchall()
    finally:
        connection.close()

    files = [
        {
            "filename": row[0],
            "file_path": row[1],
            "case_number": row[2],
            "cdcr_number": row[3],
            "date_stamped": row[4]
        }
        for row in results
    ]
    search_info = "Users can search by filename, case number, CDCR number, or date stamped. The search will work together with your sort and direction dropdowns."
    return render_template("fileviewer.html", files=files, sort_field=sort_field, direction=sort_direction.lower(), search_term=search_term, search_info=search_info)

@app.route('/dashboard')
def dashboard():
    """Dashboard with database statistics and system status."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306))
    )

    try:
        with connection.cursor() as cursor:
            # Get total files
            cursor.execute("SELECT COUNT(*) FROM pdfs")
            total_files = cursor.fetchone()[0]

            # Get files with metadata
            cursor.execute("SELECT COUNT(*) FROM pdfs p JOIN metadata m ON p.id = m.pdf_id")
            with_metadata = cursor.fetchone()[0]

            # Get files missing metadata (no metadata entry at all)
            cursor.execute("SELECT COUNT(*) FROM pdfs p LEFT JOIN metadata m ON p.id = m.pdf_id WHERE m.pdf_id IS NULL")
            missing_metadata = cursor.fetchone()[0]

            # Get files needing metadata refresh (auto-recovered with incomplete metadata)
            cursor.execute("SELECT COUNT(*) FROM pdfs p JOIN metadata m ON p.id = m.pdf_id WHERE m.notes LIKE '%Auto-recovered%' AND (m.case_number IS NULL OR m.case_number = '')")
            needs_refresh = cursor.fetchone()[0]

            # Get last consistency check
            log_dir = os.getenv('LOG_DIR', '/home/RSCAP/mysite/logs')
            consistency_logs = []
            if os.path.exists(log_dir):
                for file in os.listdir(log_dir):
                    if file.startswith('FileConsistencyCheck_'):
                        consistency_logs.append(file)

            last_check = "Never" if not consistency_logs else max(consistency_logs).replace('FileConsistencyCheck_', '').replace('.log', '')

    finally:
        connection.close()

    # Dashboard statistics
    stats = {
        'total_files': total_files,
        'with_metadata': with_metadata,
        'missing_metadata': missing_metadata + needs_refresh,  # Include both types of issues
        'needs_refresh': needs_refresh,
        'last_check': last_check
    }

    recent_activity = [
        {'timestamp': '2025-07-28 05:22', 'type': 'CHECK', 'description': 'Consistency check completed'},
        {'timestamp': '2025-07-28 05:15', 'type': 'RECOVERY', 'description': 'Auto-recovered 5 missing files'},
        {'timestamp': '2025-07-28 04:30', 'type': 'UPLOAD', 'description': 'New file uploaded: corrected_Gonzalez-AA9449_Barriga.pdf'}
    ]

    status = {
        'database': 'Connected',
        'archive': 'Accessible',
        'sync': 'Synchronized' if missing_metadata == 0 else 'Issues Found'
    }

    return render_template("dashboard.html", stats=stats, recent_activity=recent_activity, status=status)

@app.route('/missing_metadata')
def missing_metadata():
    """Show files that are missing metadata."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306))
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.filename, p.file_path, p.id
                FROM pdfs p
                LEFT JOIN metadata m ON p.id = m.pdf_id
                WHERE m.pdf_id IS NULL
                ORDER BY p.filename
            """)
            results = cursor.fetchall()
    finally:
        connection.close()

    files = [
        {
            "filename": row[0],
            "file_path": row[1],
            "id": row[2]
        }
        for row in results
    ]

    return render_template("missing_metadata.html", files=files)

@app.route('/recent_uploads')
def recent_uploads():
    """Show recently uploaded files."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306))
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.filename, p.file_path, m.case_number, m.cdcr_number, m.date_stamped
                FROM pdfs p
                LEFT JOIN metadata m ON p.id = m.pdf_id
                ORDER BY p.id DESC
                LIMIT 20
            """)
            results = cursor.fetchall()
    finally:
        connection.close()

    files = [
        {
            "filename": row[0],
            "file_path": row[1],
            "case_number": row[2],
            "cdcr_number": row[3],
            "date_stamped": row[4]
        }
        for row in results
    ]

    return render_template("recent_uploads.html", files=files)

@app.route('/consistency_report')
def consistency_report():
    """Show the latest consistency report."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    log_dir = os.getenv('LOG_DIR', '/home/RSCAP/mysite/logs')
    report_content = "No consistency reports found."

    if os.path.exists(log_dir):
        consistency_logs = []
        for file in os.listdir(log_dir):
            if file.startswith('FileConsistencyCheck_'):
                consistency_logs.append(file)

        if consistency_logs:
            latest_report = max(consistency_logs)
            report_path = os.path.join(log_dir, latest_report)
            try:
                with open(report_path, 'r') as f:
                    report_content = f.read()
            except Exception as e:
                report_content = f"Error reading report: {e}"

    return render_template("consistency_report.html", report_content=report_content)

@app.route('/run_consistency_check', methods=['POST'])
def run_consistency_check():
    """Run a consistency check and generate a report."""
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401

    try:
        import subprocess
        result = subprocess.run(['python3', 'fileconsistencycheck.py'],
                              capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))

        if result.returncode == 0:
            return jsonify({"success": True, "message": "Consistency check completed successfully!"})
        else:
            return jsonify({"success": False, "message": f"Error: {result.stderr}"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route('/dashboard_stats')
def dashboard_stats():
    """Get dashboard statistics for the admin dashboard."""
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401

    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 3306)),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

    try:
        with connection.cursor() as cursor:
            # Count files missing metadata (no metadata entry at all)
            cursor.execute("""
                SELECT COUNT(*)
                FROM pdfs p
                LEFT JOIN metadata m ON p.id = m.pdf_id
                WHERE m.pdf_id IS NULL
            """)
            missing_metadata_count = cursor.fetchone()[0]

            # Count files needing metadata refresh (auto-recovered with incomplete metadata)
            cursor.execute("""
                SELECT COUNT(*)
                FROM pdfs p
                JOIN metadata m ON p.id = m.pdf_id
                WHERE m.notes LIKE '%Auto-recovered%'
                AND (m.case_number IS NULL OR m.case_number = '')
            """)
            needs_refresh_count = cursor.fetchone()[0]

            # Get last consistency check time
            log_dir = os.getenv('LOG_DIR', '/home/RSCAP/mysite/logs')
            last_check = "Never"
            if os.path.exists(log_dir):
                consistency_logs = [f for f in os.listdir(log_dir) if f.startswith('FileConsistencyCheck_')]
                if consistency_logs:
                    latest_log = max(consistency_logs)
                    # Extract timestamp from filename
                    try:
                        timestamp_str = latest_log.replace('FileConsistencyCheck_', '').replace('.log', '')
                        last_check = timestamp_str
                    except:
                        last_check = "Recently"

            return jsonify({
                "missing_metadata_count": missing_metadata_count,
                "needs_refresh_count": needs_refresh_count,
                "last_consistency_check": last_check
            })
    finally:
        connection.close()

@app.route('/refresh_metadata', methods=['GET', 'POST'])
def refresh_metadata():
    """Refresh metadata for files that were auto-recovered."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Run the metadata refresh script
        try:
            import subprocess
            result = subprocess.run(['python3', 'metadata_refresh.py'],
                                  capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))

            if result.returncode == 0:
                return jsonify({"success": True, "message": "Metadata refresh completed successfully!"})
            else:
                return jsonify({"success": False, "message": f"Error: {result.stderr}"})
        except Exception as e:
            return jsonify({"success": False, "message": f"Error: {str(e)}"})

    # GET request - show the refresh page
    connection = pymysql.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 3306)),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.filename, p.file_path, m.notes
                FROM pdfs p
                JOIN metadata m ON p.id = m.pdf_id
                WHERE m.notes LIKE '%Auto-recovered%'
                AND (m.case_number IS NULL OR m.case_number = '')
                ORDER BY p.filename
            """)
            results = cursor.fetchall()
    finally:
        connection.close()

    files = [
        {
            "filename": row[0],
            "file_path": row[1],
            "notes": row[2]
        }
        for row in results
    ]

    return render_template("refresh_metadata.html", files=files)

if __name__ == '__main__':
    app.run(debug=True)