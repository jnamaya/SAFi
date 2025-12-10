
import os
os.environ['FLASK_SECRET_KEY'] = 'migration_temp_key'
from safi_app.config import Config
import mysql.connector
import uuid
import json

def migrate():
    print("Connecting to database...")
    try:
        conn = mysql.connector.connect(
            host="127.0.0.1",
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME
        )
        cursor = conn.cursor(dictionary=True)

        # --- SCHEMA UPDATE (Apply if missing) ---
        print("Checking schema...")
        
        # 1. Update Users Table
        cursor.execute("SHOW COLUMNS FROM users LIKE 'org_id'")
        if not cursor.fetchone():
            print("Adding org_id and role to users table...")
            cursor.execute("ALTER TABLE users ADD COLUMN org_id CHAR(36)")
            cursor.execute("ALTER TABLE users ADD COLUMN role ENUM('admin', 'editor', 'auditor', 'member') DEFAULT 'member'")
            cursor.execute("CREATE INDEX idx_user_org ON users(org_id)")

        # 2. Update Organizations Table
        cursor.execute("SHOW COLUMNS FROM organizations LIKE 'owner_id'")
        if not cursor.fetchone():
             print("Adding owner_id and settings to organizations table...")
             cursor.execute("ALTER TABLE organizations ADD COLUMN owner_id VARCHAR(255)")
             cursor.execute("ALTER TABLE organizations ADD COLUMN settings JSON")
             cursor.execute("ALTER TABLE organizations ADD CONSTRAINT fk_org_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL")
        
        conn.commit()
        # ----------------------------------------

    except mysql.connector.Error as err:
        print(f"Error connecting/updating schema: {err}")
        return

    print("Fetching users without organization...")
    # Get users who have no org_id
    cursor.execute("SELECT * FROM users WHERE org_id IS NULL")
    users = cursor.fetchall()
    
    print(f"Found {len(users)} users to migrate.")

    for user in users:
        try:
            user_id = user['id']
            user_name = user['name'] or "User"
            org_name = f"{user_name}'s Organization"
            
            print(f"Migrating user {user_id} -> {org_name}")

            # 1. Create IDs
            org_id = str(uuid.uuid4())
            policy_id = str(uuid.uuid4())

            # 2. Create Org (Must exist before Policy can reference it)
            cursor.execute("""
                INSERT INTO organizations (id, name, owner_id, global_policy_id, settings, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (org_id, org_name, user_id, policy_id, json.dumps({"allow_auto_join": False})))

            # 3. Create Default Policy for this Org
            cursor.execute("""
                INSERT INTO policies (id, org_id, name, worldview, will_rules, values_weights, created_by) 
                VALUES (%s, %s, %s, %s, '[]', '[]', %s)
            """, (policy_id, org_id, "Default Policy", f"AI for {org_name}", user_id))

            # 4. Update User (Assign to Org as Admin)
            cursor.execute("""
                UPDATE users SET org_id=%s, role='admin' WHERE id=%s
            """, (org_id, user_id))

            conn.commit()
            print(f"v Success: {user_name} migrated.")

        except Exception as e:
            print(f"x Failed to migrate {user['id']}: {e}")
            conn.rollback()

    cursor.close()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
