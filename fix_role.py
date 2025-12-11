
import os
import sys
from safi_app.persistence import database as db

# Manually set the user ID from the debug output
# ID: 89fd3e7d-8605-49b0-b13b-6656082c3a7a
TARGET_USER_ID = "89fd3e7d-8605-49b0-b13b-6656082c3a7a"

def fix_role():
    print(f"Checking user {TARGET_USER_ID}...")
    user = db.get_user_details(TARGET_USER_ID)
    if not user:
        print("User not found!")
        return

    print(f"Current Role: {user.get('role')}")
    print(f"Current Org: {user.get('org_id')}")

    if user.get('role') != 'admin':
        print("Updating role to ADMIN...")
        conn = db.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET role='admin' WHERE id=%s", (TARGET_USER_ID,))
            conn.commit()
            print("Role updated successfully.")
        except Exception as e:
            print(f"Error updating role: {e}")
        finally:
            cursor.close()
            conn.close()
    else:
        print("User is already admin.")

if __name__ == "__main__":
    fix_role()
