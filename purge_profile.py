import json
from safi_app import create_app
from safi_app.persistence import database as db

# 1. Initialize the app context to access the DB
app = create_app()

with app.app_context():
    # 2. Find your User ID
    # If you don't know it, we can look it up by email.
    email = "jnamaya@gmail.com"  # <--- REPLACE THIS WITH YOUR EMAIL
    user = db.get_user_by_email(email)
    
    if not user:
        print(f"❌ User not found for email: {email}")
        exit()

    user_id = user['id']
    print(f"Found User ID: {user_id}")

    # 3. Define the clean profile
    clean_profile = {
        "stated_values": ["Honesty", "Courage"],
        "interests": ["Coding", "Philosophy"],
        "stated_goals": [],
        "family_status": []
    }

    # 4. Overwrite the memory
    db.upsert_user_profile_memory(user_id, json.dumps(clean_profile))
    print("✅ SUCCESS: Profile memory has been wiped and reset.")