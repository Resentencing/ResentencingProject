from flask import Flask, render_template
import pymysql

app = Flask(__name__)

DB_CONFIG = {
    'host': 'RSCAP.mysql.pythonanywhere-services.com',
    'user': 'RSCAP',
    'password': 'fosvYz-bykci9-juzwek',
    'database': 'RSCAP$RSCAPTester'
}

@app.route("/fileviewer")
def fileviewer():
    connection = pymysql.connect(**DB_CONFIG)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT filename, file_path FROM pdfs")
            results = cursor.fetchall()
    finally:
        connection.close()

    files = [{"filename": r[0], "path": r[1]} for r in results]
    return render_template("fileviewer.html", files=files)

if __name__ == "__main__":
    app.run(debug=True, port=5050)

