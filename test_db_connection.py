#!/usr/bin/env python3
"""
Test script to debug database connection and environment variables
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print("=== Environment Variables ===")
print(f"DB_HOST: {os.getenv('DB_HOST')}")
print(f"DB_USER: {os.getenv('DB_USER')}")
print(f"DB_NAME: {os.getenv('DB_NAME')}")
print(f"DB_PASSWORD: {'***' if os.getenv('DB_PASSWORD') else 'NOT SET'}")

print("\n=== Testing Database Connection ===")
try:
    import pymysql
    
    # Get environment variables with fallbacks
    db_host = os.getenv('DB_HOST')
    db_user = os.getenv('DB_USER')
    db_password = os.getenv('DB_PASSWORD')
    db_name = os.getenv('DB_NAME')
    
    # Check if all required variables are set
    if not all([db_host, db_user, db_password, db_name]):
        print("❌ Missing required environment variables!")
        exit(1)
    
    connection = pymysql.connect(
        host=db_host,
        user=db_user,
        password=db_password,
        database=db_name
    )
    
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM pdfs")
        result = cursor.fetchone()
        count = result[0] if result else 0
        print(f"✅ Database connection successful! Found {count} files in pdfs table.")
    
    connection.close()
    
except Exception as e:
    print(f"❌ Database connection failed: {e}")
    print(f"Error type: {type(e).__name__}") 