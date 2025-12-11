
import os
import sys
import mysql.connector
from dotenv import load_dotenv

# Load .env explicitly
load_dotenv()

def get_db_connection():
    try:
        return mysql.connector.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            user=os.getenv("DB_USER", "safi"),
            password=os.getenv("DB_PASSWORD", "@CCion56admin"),
            database=os.getenv("DB_NAME", "safi")
        )
    except Exception as e:
        print(f"Connection failed: {e}")
        return mysql.connector.connect(
            host="127.0.0.1",
            user="safi",
            password="@CCion56admin",
            database="safi"
        )

def fix_schema():
    print("Checking Schema for 'organizations' table...")
    conn = get_db_connection()
    if not conn:
        print("Failed to connect to DB.")
        return

    cursor = conn.cursor()
    try:
        # Check domain_verified
        cursor.execute("SHOW COLUMNS FROM organizations LIKE 'domain_verified'")
        if not cursor.fetchone():
            print("Adding column: domain_verified")
            cursor.execute("ALTER TABLE organizations ADD COLUMN domain_verified BOOLEAN DEFAULT FALSE")
        else:
            print("Column 'domain_verified' exists.")

        # Check domain_to_verify
        cursor.execute("SHOW COLUMNS FROM organizations LIKE 'domain_to_verify'")
        if not cursor.fetchone():
            print("Adding column: domain_to_verify")
            cursor.execute("ALTER TABLE organizations ADD COLUMN domain_to_verify VARCHAR(255)")
        else:
             print("Column 'domain_to_verify' exists.")

        # Check verification_token
        cursor.execute("SHOW COLUMNS FROM organizations LIKE 'verification_token'")
        if not cursor.fetchone():
            print("Adding column: verification_token")
            cursor.execute("ALTER TABLE organizations ADD COLUMN verification_token VARCHAR(255)")
        else:
             print("Column 'verification_token' exists.")

        conn.commit()
        print("Schema update complete.")

    except Exception as e:
        print(f"Error updating schema: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    fix_schema()
