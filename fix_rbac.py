import sys, os
import uuid
import mysql.connector

# Ensure we can find the app config
sys.path.append(os.path.abspath('safi_app'))
from safi_app.config import Config

def get_db_connection():
    print(f"DEBUG: Connecting to {Config.DB_HOST} as {Config.DB_USER} on db {Config.DB_NAME}")
    return mysql.connector.connect(
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        host=Config.DB_HOST,
        database=Config.DB_NAME
    )

conn = get_db_connection()
cursor = conn.cursor(dictionary=True)

print("--- Fixing RBAC Data (Standalone) ---")

# 1. Get all users
cursor.execute("SELECT id, name, email FROM users")
users = cursor.fetchall()
print(f"Found {len(users)} users.")

for u in users:
    uid = u['id']
    name = u['name'] or u['email'] or "User"
    
    # 2. Check if they have an org
    cursor.execute("SELECT * FROM org_members WHERE user_id = %s", (uid,))
    membership = cursor.fetchone()
    
    if membership:
        print(f"[OK] {name} is in org {membership['org_id']} with role {membership['role']}")
    else:
        print(f"[FIX] {name} has NO organization. Creating default...")
        
        org_id = str(uuid.uuid4())
        org_name = f"{name}'s Organization"
        
        # DEBUG: Check columns first if we fail later
        try:
             # Create Organization (Removing created_by as it seems to be missing)
             cursor.execute("INSERT INTO organizations (id, name) VALUES (%s, %s)", (org_id, org_name))
        except Exception as e:
             print(f"Error inserting org: {e}")
             print("DEBUG: Table structure:")
             cursor.execute("DESCRIBE organizations")
             print(cursor.fetchall())
             raise e
        
        # Add Member as Admin
        cursor.execute("INSERT INTO org_members (org_id, user_id, role) VALUES (%s, %s, 'admin')", (org_id, uid))
        
        conn.commit()
        print(f"      -> Created '{org_name}' ({org_id}) and assigned Admin.")

print("--- Done ---")
cursor.close()
conn.close()
