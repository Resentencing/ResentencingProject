from flask import Flask, render_template, Response, request, url_for, send_file, abort, jsonify
from flask_cors import CORS
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd
import mysql.connector
from io import BytesIO
import os
import logging
import hashlib
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


app = Flask(__name__)

# Enable CORS for frontend -> backend communication (v1 for testing)
CORS(app, resources={
    r"/query_ai": {
        "origins": ["null", "http://localhost:8000", "http://127.0.0.1:8000"]
    }
})

# Cache directory for faster visualization loading
CACHE_DIR = 'static/cache'
os.makedirs(CACHE_DIR, exist_ok=True)


# Configure Logging
logging.basicConfig(level=logging.DEBUG)

# Database Configuration - use environment variables with fallback to hardcoded values
database_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
}

# ----------------------------------------------------------------------------- #
# --------- Temp Test Functions For Frontend -> Backend Communication --------- #

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True}), 200

@app.route("/query_ai", methods=["POST"])
def query_ai():
    data = request.get_json(silent=True) or {}
    q = (data.get("query") or "").strip()
    return jsonify({"response": f"echo: {q or '[empty query]'}"}), 200

# ----------------------------------------------------------------------------- #
# ----------------------------------------------------------------------------- #

@app.route('/about')
def about():
    """
    Renders the 'About' page.
    """
    return render_template('about.html')

@app.route('/archive')
def archive():
    """
    Renders the archive search page without search results.
    """
    return render_template('archive.html')

@app.route('/archive_search', methods=['POST'])
def archive_search():
    """
    Handles search requests from the archive page.

    Extracts user input from a form, queries the database for matching metadata entries,
    and renders the archive page with the filtered results.
    """
    search_term = request.form.get("search_term")
    search_field = request.form.get("search_field")

    conn = mysql.connector.connect(**database_config)
    cursor = conn.cursor(dictionary=True)

    # Base query to join metadata and pdfs table
    query = "SELECT m.*, p.file_path FROM metadata m JOIN pdfs p ON m.pdf_id = p.id WHERE 1=1"
    params = []

    # Add dynamic WHERE clause only if both field and term are provided
    if search_term and search_field:
        query += f" AND m.{search_field} LIKE %s"
        params.append(f"%{search_term}%")

    cursor.execute(query, params)
    results = cursor.fetchall()
    conn.close()

    return render_template('archive.html', results=results)

@app.route('/download/<int:file_id>')
def download_file(file_id):
    """
    Serves a requested PDF file for download by file ID.

    Args:
        file_id (int): The ID of the file in the 'pdfs' table.

    Returns:
        Flask Response: Sends the file if it exists or a 404 error if not found.
    """
    conn = mysql.connector.connect(**database_config)
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM pdfs WHERE id = %s", (file_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        # Ensure this matches where the PDFs are located
        pdf_directory = os.path.join(os.getcwd(), 'static')  # or 'processed' or the right folder
        filepath = os.path.join(pdf_directory, result[0])

        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True)
        else:
            return f"File not found at {filepath}", 404
    else:
        return "Invalid file ID", 404

@app.route('/templates/privacy')
def privacy():
    """
    Renders the 'Privacy Policy' page.
    """
    return render_template('privacy.html')

@app.route('/templates/terms')
def terms():
    """
    Renders the 'Terms of Use' page.
    """
    return render_template('terms.html')

@app.route('/templates/contact')
def contact():
    """
    Renders the 'Contact Us' page.
    """
    return render_template('contact.html')

@app.route('/')
def home():
    """
    Renders the homepage.
    """
    return render_template('index.html')

@app.route('/visualize')
def visualize():
    """
    Generates or serves cached data visualizations based on the selected dataset type.

    Dataset types supported:
        - 'years_reduced': Bar chart of years reduced by county.
        - 'sentence_type': Pie chart of ISL/DSL sentence types.
        - 'parole_eligibility': Histogram of parole eligibility years.

    Returns:
        Flask Response: A PNG image of the visualization or a 404/500 error response.
    """
    import logging
    logging.basicConfig(level=logging.DEBUG)

    dataset_type = request.args.get('dataset', 'years_reduced')
    cache_filename = generate_cache_filename(dataset_type)
    cache_path = os.path.join(CACHE_DIR, cache_filename)

    # Check if the cache file already exists
    if os.path.exists(cache_path):
        logging.info(f"Loading cached visualization for {dataset_type}")
        with open(cache_path, 'rb') as f:
            return Response(f.read(), mimetype='image/png')

    # Generate new visualization if not cached
    try:
        df = fetch_data_from_db(dataset_type)

        if df.empty:
            logging.warning(f"No data found for dataset: {dataset_type}")
            return Response("No data available for the requested visualization.", status=404)

        sns.set(rc={'axes.facecolor': '#F9F9F9', 'figure.facecolor': '#F9F9F9'})
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.set_facecolor('#F9F9F9')

        if dataset_type == 'years_reduced':
            sns.barplot(data=df, x='county', y='years_reduced', estimator=sum, ax=ax)
            ax.set_title('Years Reduced by County')
            plt.xticks(rotation=45)

        elif dataset_type == 'sentence_type':
            df = df.groupby('isl_dsl').size().reset_index(name='count')
            ax.pie(df['count'], labels=df['isl_dsl'], autopct='%1.1f%%', startangle=90)
            ax.set_title('Sentence Type Distribution')
            ax.axis('equal')

        elif dataset_type == 'parole_eligibility':
            df['parole_eligibility_date'] = pd.to_datetime(df['parole_eligibility_date'])
            df['parole_eligibility_date'] = df['parole_eligibility_date'].dt.year  # Group by year instead of exact date
            sns.histplot(data=df, x='parole_eligibility_date', kde=True, ax=ax)
            ax.set_title('Parole Eligibility Distribution')
            plt.xticks(rotation=45)

        else:
            logging.error(f"Unknown dataset type requested: {dataset_type}")
            return Response("Invalid dataset type requested.", status=400)

        plt.tight_layout()

        # Save the plot to a cache file
        fig.savefig(cache_path)
        plt.close(fig)

        with open(cache_path, 'rb') as f:
            return Response(f.read(), mimetype='image/png')
    except Exception as e:
        logging.error(f"Error generating visualization: {e}")
        return Response("An error occurred while generating the visualization.", status=500)


def fetch_data_from_db(dataset_type):
    """
    Fetches relevant data from the database for the specified dataset type.

    Args:
        dataset_type (str): One of 'years_reduced', 'sentence_type', 'parole_eligibility'.

    Returns:
        pandas.DataFrame: DataFrame containing the required dataset.
    """
    conn = mysql.connector.connect(**database_config)

    if dataset_type == 'years_reduced':
        query = "SELECT county, years_reduced FROM metadata WHERE years_reduced IS NOT NULL;"
    elif dataset_type == 'sentence_type':
        query = "SELECT isl_dsl FROM metadata WHERE isl_dsl IS NOT NULL;"
    elif dataset_type == 'parole_eligibility':
        query = "SELECT parole_eligibility_date FROM metadata WHERE parole_eligibility_date IS NOT NULL;"
    else:
        query = "SELECT county, years_reduced FROM metadata WHERE years_reduced IS NOT NULL;"

    df = pd.read_sql(query, conn)
    conn.close()
    return df


def generate_cache_filename(dataset_type):
    """
    Generates a unique filename for caching a dataset visualization.

    Args:
        dataset_type (str): Name of the dataset (e.g., 'years_reduced').

    Returns:
        str: A hashed filename ending in '.png'.
    """
    hash_object = hashlib.md5(dataset_type.encode())
    return f"{hash_object.hexdigest()}.png"

if __name__ == '__main__':
    app.run(debug=True)