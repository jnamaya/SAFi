
import os
# Force IPv4 to avoid ::1 connection refusal
os.environ['DB_HOST'] = '127.0.0.1'
os.environ['FLASK_SECRET_KEY'] = 'dev_key'

from safi_app.persistence import database as db
import json

def check():
    domain = "safinstitute.org"
    print(f"Testing get_organization_by_domain('{domain}')...")
    
    try:
        org = db.get_organization_by_domain(domain)
        if org:
            print("SUCCESS: Found Organization:")
            print(json.dumps(org, indent=2, default=str))
        else:
            print("FAILURE: Organization not found for domain.")
            
            # Debugging why
            print("DEBUG: Checking verified orgs...")
            conn = db.get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id, name, domain_verified, domain_to_verify FROM organizations WHERE domain_verified=1")
            verified_orgs = cursor.fetchall()
            print("\nList of Verified Orgs in DB:")
            print(json.dumps(verified_orgs, indent=2, default=str))
            
            # Also check unverified containing the string
            cursor.execute("SELECT id, name, domain_verified, domain_to_verify FROM organizations WHERE domain_to_verify LIKE %s", (f"%{domain}%",))
            unverified = cursor.fetchall()
            print("\nMatching Unverified/Other Orgs:")
            print(json.dumps(unverified, indent=2, default=str))
            
            cursor.close()
            conn.close()

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check()
