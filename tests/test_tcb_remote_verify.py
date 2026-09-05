"""
TCB remote verification endpoint (org settings "Verify this Install").

Four verdicts plus a fifth off-line answer, and the operator pin surfaced as
advisory evidence:

  * authentic   -- files match the in-tree manifest AND the manifest's
                  fingerprint is in the official release list published on
                  selfalignmentframework.com
  * unreleased  -- intact against the local manifest, but that fingerprint is
                  not an official release (dev snapshot / fork)
  * modified    -- files do not match the in-tree manifest
  * unverifiable -- the local check itself could not run
  * offline     -- intact, but the official list could not be fetched; never
                  a pass, and distinct from the local states

The boot integrity machinery is consumed, never edited: the endpoint reads
get_status(), and nothing in core/integrity.py changes here, so the TCB
fingerprint of the shipped tree is untouched (backlog: remote TCB verify).

Requires the disposable stack (MySQL, real session auth):
    docker compose -f docker-compose.test.yml run --rm --build tests -k tcb_remote
"""
import json
import sys
import uuid
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.api import organizations
from safi_app.persistence import database as db
from support import login_as

F64_A = "a" * 64
F64_B = "b" * 64
F64_C = "c" * 64

INTACT = {
    "state": "intact", "intact": True, "fingerprint": F64_A,
    "expected_fingerprint": F64_B, "modified": [], "missing": [], "findings": [],
}
MODIFIED = {**INTACT, "state": "modified", "intact": False,
            "modified": ["safi_app/core/faculties/will.py"]}
UNVERIFIABLE = {**INTACT, "state": "unverifiable", "intact": False,
                "fingerprint": None}

RELEASES = {
    "releases": [
        {"tag": "v1.0", "date": "2026-06-01", "fingerprint": F64_C},
        {"tag": "v1.4.1", "date": "2026-08-14", "fingerprint": F64_B},
    ],
}


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class StubIntegrity:
    _ROOT = "/safi/root"

    def __init__(self, disk, boot):
        self.disk = disk
        self.boot = boot
        self.calls = []

    def get_status(self, root=None):
        self.calls.append(root)
        return self.disk if root is not None else self.boot


class TestTcbVerify(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.org_id = str(uuid.uuid4())
        cls.uid = f"tcbtest_{uuid.uuid4().hex[:8]}"
        cls.member_uid = f"tcbmember_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'TCB Verify Org')",
              (cls.org_id,))
        _exec("INSERT INTO users (id, email, name, org_id, role) "
              "VALUES (%s, %s, 'TCB Admin', %s, 'admin')",
              (cls.uid, f"{cls.uid}@example.test", cls.org_id))
        _exec("INSERT INTO users (id, email, name, org_id, role) "
              "VALUES (%s, %s, 'TCB Member', %s, 'member')",
              (cls.member_uid, f"{cls.member_uid}@example.test", cls.org_id))

    def setUp(self):
        # A fresh module cache every test: the TTL is 300s and sharing state
        # across tests would let a stale list leak into a later one.
        organizations._tcb_cache.update(at=0.0, releases=None)
        self.client = self.app.test_client()

    @staticmethod
    def _fake_get(resp=None, exc=None):
        def _get(url, timeout):
            if exc is not None:
                raise exc
            return resp
        return _get

    def _post(self, body=None):
        return self.client.post(f"/api/organizations/{self.org_id}/tcb-verify",
                                json=body or {})
        return self.client.post(f"/api/organizations/{self.org_id}/tcb-verify",
                                json=body or {})

    def _last_compliance(self):
        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT event_type, detail FROM org_compliance_log "
                "WHERE org_id=%s ORDER BY id DESC LIMIT 1", (self.org_id,))
            row = cur.fetchone()
        finally:
            cur.close()
            conn.close()
        if not row:
            return None
        detail = row["detail"]
        return {"event_type": row["event_type"],
                "detail": json.loads(detail) if isinstance(detail, str) else detail}

    def test_authentic_official_release(self):
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(resp=_Resp(payload=RELEASES))):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            r = self._post()
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["verdict"], "authentic")
        self.assertEqual(data["remote"]["official_release"]["tag"], "v1.4.1")
        self.assertEqual(data["local"]["state"], "intact")
        self.assertTrue(data["local"]["intact"])
        # The disk view is computed fresh (root=); the boot view is the cached one.
        self.assertEqual(stub.calls, ["/safi/root", None])
        log = self._last_compliance()
        self.assertIsNotNone(log)
        self.assertEqual(log["event_type"], "tcb_verify")
        self.assertEqual(log["detail"]["verdict"], "authentic")

    def test_intact_but_not_an_official_release(self):
        # Files match this branch's manifest, but that manifest's fingerprint
        # is not in the official list: a dev snapshot or a fork.
        state = {**INTACT, "expected_fingerprint": F64_A}
        stub = StubIntegrity(disk=state, boot=state)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(resp=_Resp(payload=RELEASES))):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "unreleased")
        self.assertIsNone(data["remote"]["official_release"])
        self.assertTrue(data["local"]["intact"])

    def test_modified_tree_is_modified_even_when_in_the_list(self):
        stub = StubIntegrity(disk=MODIFIED, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(resp=_Resp(payload=RELEASES))):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "modified")
        self.assertTrue(any("will.py" in m for m in data["local"]["modified_files"]))
        self.assertFalse(data["local"]["intact"])

    def test_unverifiable_is_a_third_local_answer(self):
        stub = StubIntegrity(disk=UNVERIFIABLE, boot=UNVERIFIABLE)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(resp=_Resp(payload=RELEASES))):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "unverifiable")
        self.assertIsNone(data["local"]["fingerprint"])

    def test_unreachable_is_offline_never_a_pass(self):
        import requests as _requests
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(exc=_requests.ConnectionError("no route"))):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "offline")
        self.assertFalse(data["remote"]["reachable"])
        self.assertTrue(data["local"]["intact"])

    def test_malformed_list_is_offline_too(self):
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(resp=_Resp(payload={"releases": []}))):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "offline")
        self.assertIn("malformed", data["remote"]["error"])

    def test_pin_mismatch_is_reported_never_withheld(self):
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(resp=_Resp(payload=RELEASES))), \
             patch.dict("os.environ", {"SAFI_EXPECTED_FINGERPRINT": F64_C}):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "authentic")
        self.assertTrue(data["pin"]["configured"])
        self.assertFalse(data["pin"]["matches"])

    def test_pin_match_identical(self):
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(resp=_Resp(payload=RELEASES))), \
             patch.dict("os.environ", {"SAFI_EXPECTED_FINGERPRINT": F64_A}):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertTrue(data["pin"]["matches"])

    def test_member_is_forbidden(self):
        with patch.object(organizations, "integrity", StubIntegrity(INTACT, INTACT)):
            login_as(self.client, self.member_uid, "member", org_id=self.org_id)
            r = self._post()
        self.assertEqual(r.status_code, 403)

    def test_other_orgs_cannot_run_it(self):
        with patch.object(organizations, "integrity", StubIntegrity(INTACT, INTACT)):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            r = self.client.post(f"/api/organizations/{uuid.uuid4()}/tcb-verify", json={})
        self.assertEqual(r.status_code, 403)

    def test_fetch_is_cached_inside_the_ttl(self):
        """Two clicks in a row hit the site once, not twice: every org admin
        gets the same deployment verdict and the site is not hammered."""
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          Mock(return_value=_Resp(payload=RELEASES))) as mocked:
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            self._post()
            self._post()
            self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)