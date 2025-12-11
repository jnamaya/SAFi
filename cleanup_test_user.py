
import os
# Force IPv4 and secret key
os.environ['DB_HOST'] = '127.0.0.1'
os.environ['FLASK_SECRET_KEY'] = 'dev_key'

from safi_app.persistence import database as db
import json

def cleanup():
    user_id = "a22d6afe-7ca8-4825-a5fc-dcd64025c999"
    org_id = "fb0db04e-2903-4cea-8f9a-30aa90197d2b"

    print(f"Checking Org {org_id}...")
    org = db.get_organization(org_id)
    if org:
        print("Found Org:")
        print(json.dumps(org, indent=2, default=str))
        
        # Check if this org is owned by the user we are deleting
        if org.get('owner_id') == user_id:
            print("Org is owned by this user. Deleting Org as well...")
            conn = db.get_db_connection()
            cursor = conn.cursor()
            try:
                # Delete policies first if foreign keys exist (though DB usually handles CASCADE or SET NULL)
                # But let's be safe.
                if org.get('global_policy_id'):
                     cursor.execute("DELETE FROM policies WHERE id=%s", (org['global_policy_id'],))
                     
                cursor.execute("DELETE FROM organizations WHERE id=%s", (org_id,))
                conn.commit()
                print("Organization deleted.")
            except Exception as e:
                print(f"Error deleting org: {e}")
            finally:
                cursor.close()
                conn.close()
        else:
            print("Org is NOT owned by this user (or owner_id mismatch). LEAVING ORG ALONE.")
    else:
        print("Org not found (maybe already deleted?)")

    print(f"Deleting User {user_id}...")
    try:
        db.delete_user(user_id)
        print("User deleted successfully.")
    except Exception as e:
        print(f"Error deleting user: {e}")

if __name__ == "__main__":
    cleanup()
