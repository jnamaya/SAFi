import pytest
import json
from unittest.mock import MagicMock, patch
from safi_app import create_app
from safi_app.config import Config

@pytest.fixture
def app():
    # Patch oauth and db init to speed up testing
    with patch("safi_app.oauth"), \
         patch("safi_app.persistence.database.init_db"), \
         patch("safi_app.cors"):
        
        app = create_app()
        app.config.update({
            "TESTING": True,
            "SECRET_KEY": "test_key",
            "OPENAI_API_KEY": "sk-dummy",
            "GROQ_API_KEY": "gsk-dummy"
        })
        return app

@pytest.fixture
def client(app):
    return app.test_client()

class TestAgentSettings:

    @patch("safi_app.api.agent_api_routes.db")
    @patch("safi_app.api.agent_api_routes.check_permission")
    def test_save_agent_validation(self, mock_check, mock_db, client):
        """
        Verify validation logic:
        - Must have Name
        - Must have Key (valid format)
        - Must have >=1 Value
        - Must have >=1 Rule
        """
        # Session Mocking
        with client.session_transaction() as sess:
            sess["user"] = {"id": "user123", "role": "editor", "org_id": "org1"}
            
        # Permissions: Allow editor
        mock_check.return_value = True 
        
        # 1. Missing Value & Rule
        payload = {
            "key": "bad_agent",
            "name": "Bad Agent",
            "values": [],
            "will_rules": []
        }
        resp = client.post("/api/agents", json=payload)
        assert resp.status_code == 400
        assert "at least one value" in resp.json["error"]
        
        # 2. Valid Agent
        payload_ok = {
            "key": "good_agent",
            "name": "Good Agent",
            "values": [{"value": "Honesty", "weight": 1.0}],
            "will_rules": ["Be honest"],
            "intellect_model": "gpt-4"
        }
        
        # Mock DB specific checks
        mock_db.get_agent.return_value = None # New agent
        
        resp = client.post("/api/agents", json=payload_ok)
        
        assert resp.status_code == 200
        assert resp.json["ok"] is True
        mock_db.create_agent.assert_called_once()
        print("\n✅ API Validation Verified: Enforced Values/Rules constraint.")

    @patch("safi_app.api.agent_api_routes.db")
    @patch("safi_app.api.agent_api_routes.check_permission")
    def test_update_agent_permissions(self, mock_check, mock_db, client):
        """
        Verify permission logic.
        """
        with client.session_transaction() as sess:
            sess["user"] = {"id": "user123"} # role implied by check_permission call
            
        mock_check.return_value = True # Let generic checks pass, rely on internal route logic
        
        # Scenario: Update existing agent
        mock_db.get_agent.return_value = {
            "key": "existing",
            "created_by": "other_user" # Not owner
        }
        
        payload = {
            "key": "existing",
            "name": "Hacked Agent",
            "values": [{"val": "x"}],
            "will_rules": ["rule"]
        }
        
        # If check_permission("admin") is False (default mock behavior if we don't spec it separately?)
        # We need check_permission to return different values based on arg?
        # Routes calls: check_permission('editor') then check_permission('admin')
        
        def side_effect(role):
            if role == 'editor': return True
            if role == 'admin': return False
            return False
            
        mock_check.side_effect = side_effect
        
        resp = client.put("/api/agents", json=payload)
        
        # Should fail 403 because not owner and not admin
        assert resp.status_code == 403
        print("✅ API Permissions Verified: Non-owner/Non-admin blocked.")

