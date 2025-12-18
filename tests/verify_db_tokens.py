
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from safi_app.persistence import database as db
from safi_app.config import Config

print("--- DB TOKEN VERIFICATION ---")
print(f"DB Host: {Config.DB_HOST}")
print(f"DB User: {Config.DB_USER}")
print(f"DB Name: {Config.DB_NAME}")

try:
    conn = db.get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Check Table Existence
    cursor.execute("SHOW TABLES LIKE 'oauth_tokens'")
    if not cursor.fetchone():
        print("CRITICAL: 'oauth_tokens' table does NOT exist!")
        sys.exit(1)
        
    # 2. List all tokens
    cursor.execute("SELECT user_id, provider, created_at, expires_at FROM oauth_tokens")
    rows = cursor.fetchall()
    
    print(f"\nFound {len(rows)} token(s):")
    for r in rows:
        print(f" - User: {r['user_id']} | Provider: {r['provider']} | Expires: {r['expires_at']}")
        
    if not rows:
        print("\n[WARNING] No tokens found in database. The 'Connect' flow has not completed successfully for any user.")

except Exception as e:
    print(f"\nERROR: {e}")
finally:
    if 'cursor' in locals() and cursor: cursor.close()
    if 'conn' in locals() and conn: conn.close()
