import sys
import os
import secrets
import hashlib
import uuid
from safi_app.persistence import database as db

def test_key_cycle():
    print("--- Starting Key Cycle Test ---")
    
    # 1. Create Policy
    pid = f"debug_policy_{uuid.uuid4().hex[:8]}"
    print(f"Creating Policy: {pid}")
    try:
        db.create_policy(name="Debug Policy", policy_id=pid)
        print("Policy Created.")
    except Exception as e:
        print(f"Failed to create policy: {e}")
        return

    # 2. Generate Key
    label = "Debug Key"
    print(f"Generating Key for {pid}...")
    try:
        raw_key = db.create_api_key(pid, label)
        print(f"Generated Raw Key: {raw_key}")
    except Exception as e:
        print(f"Failed to generate key: {e}")
        return

    # 3. Verify Key
    print(f"Verifying Key: {raw_key}")
    found_pid = db.get_policy_id_by_api_key(raw_key)
    
    if found_pid:
        print(f"SUCCESS: Key verified. Mapped to Policy ID: {found_pid}")
        if found_pid == pid:
            print("Policy ID matches.")
        else:
            print(f"MISMATCH: Expected {pid}, got {found_pid}")
    else:
        print("FAILURE: Key verification returned None (401).")
        
        # Debug Hash
        h = hashlib.sha256(raw_key.encode()).hexdigest()
        print(f"Computed Hash: {h}")
        
        conn = db.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM api_keys WHERE policy_id=%s", (pid,))
        stored = cursor.fetchone()
        print(f"Stored in DB: {stored}")
        conn.close()

if __name__ == "__main__":
    test_key_cycle()
