import sys, os
sys.path.append(os.path.abspath('safi_app'))
from safi_app.persistence import database as db
from safi_app import create_app
from safi_app.core.permissions import ROLES

app = create_app()
with app.app_context():
    # Trigger migration
    db.init_db()
    
    conn = db.get_db_connection()
    cursor = conn.cursor()
    
    print('--- Check Tables ---')
    cursor.execute("SHOW TABLES LIKE 'org_members'")
    print(f'org_members exists: {cursor.fetchone()}')
    
    cursor.execute("SHOW COLUMNS FROM agents LIKE 'org_id'")
    print(f'agents.org_id exists: {cursor.fetchone()}')
    
    print('--- Check Migration Data ---')
    cursor.execute("SELECT * FROM org_members LIMIT 5")
    print(f'Memberships: {cursor.fetchall()}')
    
    cursor.execute("SELECT agent_key, org_id, visibility FROM agents LIMIT 5")
    print(f'Agents: {cursor.fetchall()}')

    print('--- Ensure Admin Role Exists ---')
    print(f'Admin capabilities: {ROLES["admin"]}')
