"""RBAC mechanics consume host-provided role data."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, session

from safi_app.core.rbac import check_permission, check_any_role, get_current_role
from safi_app.role_config import ROLE_CONFIG


class RbacConfiguration(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test"
        self.app.config["ROLE_CONFIG"] = ROLE_CONFIG

    def test_hierarchy_is_supplied_by_host_configuration(self):
        with self.app.test_request_context("/"):
            session["user"] = {"role": "editor"}
            self.assertTrue(check_permission("auditor"))
            self.assertFalse(check_permission("admin"))

    def test_unknown_role_fails_closed(self):
        with self.app.test_request_context("/"):
            session["user"] = {"role": "unknown"}
            self.assertFalse(check_permission("member"))
            self.assertFalse(check_any_role({"admin", "member"}))

    def test_default_role_is_data(self):
        with self.app.test_request_context("/"):
            session["user"] = {}
            self.assertEqual(get_current_role(), ROLE_CONFIG["default_role"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
