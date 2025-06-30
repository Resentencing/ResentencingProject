import mysql.connector
import json
import os
import logging
import math
from sshtunnel import SSHTunnelForwarder
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Set timeouts as recommended by PythonAnywhere
SSHTunnelForwarder.SSH_TIMEOUT = 10.0
SSHTunnelForwarder.TUNNEL_TIMEOUT = 10.0

def test_connection():
    """
    Test the SSH tunnel and database connection using environment variables.
    """
    try:
        # Get credentials from environment variables
        username = os.getenv('PYTHONANYWHERE_USERNAME')
        password = os.getenv('PYTHONANYWHERE_PASSWORD')
        db_password = os.getenv('PYTHONANYWHERE_DB_PASSWORD')
        db_name = os.getenv('PYTHONANYWHERE_DB_NAME')
        
        if not all([username, password, db_password, db_name]):
            print("❌ ERROR: Missing environment variables. Please check your .env file.")
            return False
            
        with SSHTunnelForwarder(
            ('ssh.pythonanywhere.com'),
            ssh_username=username, 
            ssh_password=password,
            remote_bind_address=(f'{username}.mysql.pythonanywhere-services.com', 3306)
        ) as tunnel:
            connection = mysql.connector.connect(
                user=username,
                passwd=db_password,
                host='127.0.0.1', 
                port=tunnel.local_bind_port,
                db=db_name,
            )
            
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM pdfs")
            pdf_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM metadata")
            metadata_count = cursor.fetchone()[0]
            cursor.close()
            
            print(f"✅ SUCCESS: Connected to PythonAnywhere database!")
            print(f"📊 PDFs in database: {pdf_count}")
            print(f"📊 Metadata entries: {metadata_count}")
            
            connection.close()
            return True
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

if __name__ == "__main__":
    test_connection() 