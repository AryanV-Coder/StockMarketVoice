import psycopg2
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

# Method 1: Direct PostgreSQL connection (if you have direct DB credentials)
def connect_postgres():
    """Connect directly to PostgreSQL database"""
    USER = os.getenv("user")
    PASSWORD = os.getenv("password")
    HOST = os.getenv("host")
    PORT = os.getenv("port")
    DBNAME = os.getenv("dbname")

    try:
        connection = psycopg2.connect(
            user=USER,
            password=PASSWORD,
            host=HOST,
            port=PORT,
            database=DBNAME
        )
        print("✅ PostgreSQL connection successful!")
        
        # Create a cursor to execute SQL queries
        cursor = connection.cursor()
        
        # # Example query
        # cursor.execute("Insert into transcripts(timestamp,transcript) values('2025-08-18 23:22:33','HI')")
        # # result = cursor.fetchone()
        # # print("Current Time:", result)
        # connection.commit()
        # # Close the cursor and connection
        # cursor.close()
        # connection.close()
        # print("Connection closed.")
        
        return connection,cursor

    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        return False