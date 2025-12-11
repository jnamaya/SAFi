
import os
os.environ['DB_HOST'] = '127.0.0.1'
os.environ['FLASK_SECRET_KEY'] = 'dev_key'
from safi_app.persistence import database as db
import json

def check_user():
    user_id = "a22d6afe-7ca8-4825-a5fc-dcd64025c999"
    print(f"Checking User {user_id}...")
    
    try:
        user = db.get_user_details(user_id)
        if user:
            print(json.dumps(user, indent=2, default=str))
        else:
            print("User NOT FOUND in DB.")
            
        # Also check org details
        if user and user.get('org_id'):
            print(f"\nChecking Org {user['org_id']}...")
            org = db.get_organization(user['org_id'])
            print(json.dumps(org, indent=2, default=str))
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_user()
