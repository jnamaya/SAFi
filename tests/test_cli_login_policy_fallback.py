"""Regression test for CLI login policy key fallback on newly provisioned users."""
from unittest.mock import MagicMock, patch

from safi_app.persistence import database as db


def test_new_org_user_without_global_policy_falls_back_to_seeded_policy():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    # 1: created_by -> None, 2: org_id -> None, 3: is_demo=TRUE -> ('prod_software_engineer_policy',)
    cursor.fetchone.side_effect = [None, None, ("prod_software_engineer_policy",)]

    user = {"id": "user-123", "org_id": "org-1", "active_profile": None}
    with patch.object(db, "get_organization", return_value={"id": "org-1", "global_policy_id": None}), \
         patch.object(db, "get_db_connection", return_value=conn), \
         patch.object(db, "delete_policy_keys_by_label") as del_mock, \
         patch.object(db, "create_api_key", return_value="safi_raw_key"):
        res = db.get_or_create_policy_key_for_user(user, label="safi-cli")

    assert res == {"api_key": "safi_raw_key", "policy_id": "prod_software_engineer_policy"}
    del_mock.assert_called_once_with("prod_software_engineer_policy", "safi-cli:user-123")
