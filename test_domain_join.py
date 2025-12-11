
import unittest
from unittest.mock import MagicMock, patch
import json
import sys
import os

# Set required env vars BEFORE imports
os.environ['FLASK_SECRET_KEY'] = 'test_key_for_unit_tests'
os.environ['FLASK_ENV'] = 'development'
os.environ['DB_HOST'] = '127.0.0.1' # Prevent localhost lookup lag/issues

# Add parent dir to path so we can import safi_app
sys.path.append(os.getcwd())

# Mock the database module BEFORE importing safi_app because safi_app imports it
sys.modules['mysql.connector'] = MagicMock()

from safi_app.persistence import database as db

class TestDomainJoin(unittest.TestCase):
    
    @patch('safi_app.persistence.database.get_db_connection')
    def test_get_organization_by_domain(self, mock_get_conn):
        # Setup mock cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Setup return value
        expected_org = {"id": "org123", "name": "Test Org", "domain_verified": 1, "domain_to_verify": "test.com"}
        mock_cursor.fetchone.return_value = expected_org
        
        # Call function
        domain = "test.com"
        result = db.get_organization_by_domain(domain)
        
        # Verify SQL query
        mock_cursor.execute.assert_called_with(
            "SELECT * FROM organizations WHERE domain_verified=TRUE AND domain_to_verify=%s", 
            (domain,)
        )
        
        # Verify result
        self.assertEqual(result, expected_org)
        print("Success: get_organization_by_domain executed correct query.")

if __name__ == '__main__':
    unittest.main()
