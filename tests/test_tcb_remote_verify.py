"""
TCB remote verification endpoint (org settings "Verify this Install").

Four verdicts plus a fifth off-line answer, and the operator pin surfaced as
advisory evidence:

  * authentic   -- files match the in-tree manifest AND the manifest's
                  fingerprint is in the official release list published on
                  selfalignmentframework.com AND that list's signature
                  authenticated against the pinned registry key
  * unreleased  -- intact against the local manifest, but that fingerprint is
                  not an official release (dev snapshot / fork)
  * modified    -- files do not match the in-tree manifest
  * unverifiable -- no verdict is possible: the local check failed, OR the
                  official list was reachable but did not authenticate
                  (bad/missing signature, unusable pubkey, empty list)
  * offline     -- intact, but the official list could not be fetched; never
                  a pass, and distinct from the local states

The list is only trusted after a minisign (legacy, raw-message) ed25519 check
over the exact published bytes, using the key pinned in this image. Tests
generate an in-memory keypair, write a minisign-format public key to a temp
file, sign the payload exactly as `scripts/tcb_sign.py` does, and the fake
transport serves it per URL.

The boot integrity machinery is consumed, never edited: the endpoint reads
get_status(), and nothing in core/integrity.py changes here, so the TCB
fingerprint of the shipped tree is untouched (backlog: remote TCB verify).

Requires the disposable stack (MySQL, real session auth):
    docker compose -f docker-compose.test.yml run --rm --build tests -k tcb_remote
"""
import base64
import json
import os
import sys
import tempfile
import uuid
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
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


def _ed25519_keypair():
    """An in-memory minisign-compatible keypair: (keynum8, pub32, priv32)."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    keynum = pub[:8]  # a stable binding, like minisign's key number
    return keynum, pub, priv


def _minisign_pubkey_file(keynum, pub):
    """The public key file layout minisign 0.12 reads: a comment line, then
    base64(b"Ed" + keynum(8) + pub(32))."""
    return ("untrusted comment: minisign public key test\n"
            + base64.b64encode(b"Ed" + keynum + pub).decode() + "\n")


def _minisig(payload, keynum, priv):
    """Sign the exact payload bytes the way scripts/tcb_sign.py does: raw
    ed25519 over the message, wrapped in minisign's signature layout
    base64(b"Ed" + keynum(8) + sig(64))."""
    sig = priv.sign(payload)
    return ("untrusted comment: test signature\n"
            + base64.b64encode(b"Ed" + keynum + sig).decode() + "\n")


class _BytesResp:
    """A requests.Response stand-in exposing .status_code and .content; the
    endpoint no longer calls .json() on the wire payload, it reads bytes."""

    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.content = content


class StubIntegrity:
    _ROOT = "/safi/root"

    def __init__(self, disk, boot):
        self.disk = disk
        self.boot = boot
        self.calls = []

    def get_status(self, root=None):
        self.calls.append(root)
        return self.disk if root is not None else self.boot


class BrokenIntegrity:
    """Models the only realistic failure of the local check: get_status and
    _ROOT both raising or the files being unreadable. Returns a 500 with the
    error body, not a verdict."""

    _ROOT = "/safi/root"

    def get_status(self, root=None):
        raise RuntimeError("integrity check could not run")


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
        cls.keynum, cls.pub, cls.priv = _ed25519_keypair()
        cls.pubkey_dir = tempfile.TemporaryDirectory()
        cls.pubkey_path = os.path.join(cls.pubkey_dir.name, "TCB_KEY.pub")
        with open(cls.pubkey_path, "w") as f:
            f.write(_minisign_pubkey_file(cls.keynum, cls.pub))
        # The exact bytes the endpoint will fetch and verify, and the matching
        # signature, mirroring how the real site serves releases.json.
        cls.payload = json.dumps(RELEASES).encode()
        cls.valid_sig = _minisig(cls.payload, cls.keynum, cls.priv)

    @classmethod
    def tearDownClass(cls):
        cls.pubkey_dir.cleanup()

    def setUp(self):
        # A fresh module cache every test: the TTL is 300s and sharing state
        # across tests would let a stale list leak into a later one.
        organizations._tcb_cache.update(at=0.0, releases=None)
        self._old_pubkey_path = organizations._TCB_PUBKEY_PATH
        organizations._TCB_PUBKEY_PATH = self.pubkey_path
        self.client = self.app.test_client()

    def tearDown(self):
        organizations._TCB_PUBKEY_PATH = self._old_pubkey_path

    @staticmethod
    def _fake_get(payload=None, sig=None, exc=None, release_status=200,
                  sig_status=200, sig_exc=None):
        """URL-aware transport fake: the releases URL serves `payload`
        (bytes), the signature URL serves `sig`. Raise `exc` for any URL when
        given, or `sig_exc` for the signature URL only."""
        def _get(url, timeout):
            if exc is not None:
                raise exc
            if url.endswith(".minisig"):
                if sig_exc is not None:
                    raise sig_exc
                if sig_status != 200:
                    return _BytesResp(status_code=sig_status)
                return _BytesResp(status_code=200, content=sig)
            if release_status != 200:
                return _BytesResp(status_code=release_status)
            return _BytesResp(status_code=200, content=payload)
        return _get

    def _signed_get(self):
        return self._fake_get(payload=self.payload, sig=self.valid_sig)

    def _post(self, body=None):
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
             patch.object(organizations.requests, "get", self._signed_get()):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            r = self._post()
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["verdict"], "authentic")
        self.assertTrue(data["remote"]["verified"])
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
             patch.object(organizations.requests, "get", self._signed_get()):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "unreleased")
        self.assertTrue(data["remote"]["verified"])
        self.assertIsNone(data["remote"]["official_release"])
        self.assertTrue(data["local"]["intact"])

    def test_modified_tree_is_modified_even_when_in_the_list(self):
        stub = StubIntegrity(disk=MODIFIED, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get", self._signed_get()):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "modified")
        self.assertTrue(any("will.py" in m for m in data["local"]["modified_files"]))
        self.assertFalse(data["local"]["intact"])

    def test_unverifiable_is_a_third_local_answer(self):
        stub = StubIntegrity(disk=UNVERIFIABLE, boot=UNVERIFIABLE)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get", self._signed_get()):
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

    def test_signed_list_with_no_releases_is_unverifiable(self):
        """A valid signature over an empty registry proves nothing; membership
        cannot be established, so it must not fall through to 'unreleased'."""
        empty = json.dumps({"releases": []}).encode()
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(payload=empty,
                                         sig=_minisig(empty, self.keynum, self.priv))):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "unverifiable")
        self.assertIn("no releases", data["remote"]["error"])

    def test_tampered_list_is_unverifiable_never_authentic(self):
        """The whole point of signing: a modified list that still carries the
        old signature must not authenticate, no matter how official it looks."""
        tampered = self.payload + b"\n"
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(payload=tampered, sig=self.valid_sig)):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "unverifiable")
        self.assertFalse(data["remote"]["verified"])
        self.assertIn("signature", data["remote"]["error"])

    def test_missing_signature_is_unverifiable(self):
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(payload=self.payload, sig=None,
                                         sig_status=404)):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "unverifiable")
        self.assertTrue(data["remote"]["reachable"])
        self.assertFalse(data["remote"]["verified"])
        self.assertIn("signature missing", data["remote"]["error"])

    def test_signature_by_another_key_is_unverifiable(self):
        other_keynum, other_pub, other_priv = _ed25519_keypair()
        other_sig = _minisig(self.payload, other_keynum, other_priv)
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          self._fake_get(payload=self.payload, sig=other_sig)):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "unverifiable")
        self.assertIn("different key", data["remote"]["error"])

    def test_missing_pinned_key_fails_closed(self):
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations, "_TCB_PUBKEY_PATH",
                          "/nonexistent/TCB_KEY.pub"), \
             patch.object(organizations.requests, "get", self._signed_get()):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "unverifiable")
        self.assertFalse(data["remote"]["verified"])
        self.assertIn("pinned registry key is unavailable", data["remote"]["error"])

    def test_pin_mismatch_is_reported_never_withheld(self):
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get", self._signed_get()), \
             patch.dict("os.environ", {"SAFI_EXPECTED_FINGERPRINT": F64_C}):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["verdict"], "authentic")
        self.assertTrue(data["pin"]["configured"])
        self.assertFalse(data["pin"]["matches"])

    def test_pin_match_identical(self):
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get", self._signed_get()), \
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
        gets the same deployment verdict and the site is not hammered. The
        signed deployment now costs two requests (list + signature) on the
        first click, then zero while the TTL holds."""
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get",
                          Mock(side_effect=self._signed_get())) as mocked:
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            self._post()
            self._post()
            self.assertEqual(mocked.call_count, 2)

    def test_branch_is_reported_when_git_metadata_present(self):
        """The dev/demo compose binds .git read-only, so the button can say
        which tree this instance is on. A hint, never part of the verdict."""
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get", self._signed_get()), \
             patch.object(organizations, "_detect_git_branch",
                          return_value={"branch": "dev", "revision": "82c7caf"}):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertEqual(data["local"]["branch"], "dev")
        self.assertEqual(data["local"]["revision"], "82c7caf")

    def test_branch_is_absent_without_git_metadata(self):
        """A stock image has no .git (the Dockerfile never copies it), so the
        field is null and the UI falls back to the snapshot/fork wording."""
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get", self._signed_get()), \
             patch.object(organizations, "_detect_git_branch",
                          return_value={"branch": None, "revision": None}):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            data = self._post().get_json()
        self.assertIsNone(data["local"]["branch"])
        self.assertIsNone(data["local"]["revision"])

    def test_error_response_carries_the_branch(self):
        """When the local check itself fails, the 500 body still names the
        tree, so the UI can say "this instance is on the dev tree"."""
        with patch.object(organizations, "integrity", BrokenIntegrity()), \
             patch.object(organizations, "_detect_git_branch",
                          return_value={"branch": "dev", "revision": None}):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            r = self._post()
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.get_json()["branch"], "dev")

    def test_last_returns_the_stored_verdict(self):
        """The settings card persists: the last run's full result is stored
        in the compliance log and replayed by GET /tcb-verify/last, so a
        reload shows the stored verdict without re-verifying."""
        stub = StubIntegrity(disk=INTACT, boot=INTACT)
        with patch.object(organizations, "integrity", stub), \
             patch.object(organizations.requests, "get", self._signed_get()):
            login_as(self.client, self.uid, "admin", org_id=self.org_id)
            r = self._post()
            self.assertEqual(r.status_code, 200)
            stored = r.get_json()
            last = self.client.get(
                f"/api/organizations/{self.org_id}/tcb-verify/last").get_json()
        self.assertTrue(last["found"])
        self.assertEqual(last["verdict"], stored["verdict"])
        # The full result is the evidence record, not just a verdict string.
        self.assertEqual(last["local"]["fingerprint"], stored["local"]["fingerprint"])
        self.assertEqual(last["remote"]["reachable"], stored["remote"]["reachable"])
        self.assertEqual(last["checked_at"], stored["checked_at"])

    def test_last_is_empty_before_any_run(self):
        org = str(uuid.uuid4())
        uid = f"tcbfresh_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Fresh Org')", (org,))
        _exec("INSERT INTO users (id, email, name, org_id, role) "
              "VALUES (%s, %s, 'Fresh Admin', %s, 'admin')",
              (uid, f"{uid}@example.test", org))
        with patch.object(organizations, "integrity",
                          StubIntegrity(INTACT, INTACT)):
            login_as(self.client, uid, "admin", org_id=org)
            last = self.client.get(
                f"/api/organizations/{org}/tcb-verify/last").get_json()
        self.assertFalse(last["found"])
        self.assertIsNone(last["verdict"])

    def test_last_is_org_scoped_and_admin_only(self):
        other = str(uuid.uuid4())
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Other Org')", (other,))
        login_as(self.client, self.uid, "admin", org_id=self.org_id)
        cross = self.client.get(
            f"/api/organizations/{other}/tcb-verify/last")
        self.assertEqual(cross.status_code, 403)
        login_as(self.client, self.member_uid, "member", org_id=self.org_id)
        member = self.client.get(
            f"/api/organizations/{self.org_id}/tcb-verify/last")
        self.assertEqual(member.status_code, 403)


class TestDetectGitBranch(unittest.TestCase):
    """The helper walks up from the module directory reading .git/HEAD as a
    plain text file, so it works without a git binary and never raises."""

    def _make(self, head_contents=None, head_missing=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        git = os.path.join(tmp.name, ".git")
        if not head_missing:
            os.makedirs(git, exist_ok=True)
            if head_contents is not None:
                with open(os.path.join(git, "HEAD"), "w") as f:
                    f.write(head_contents)
        return tmp.name

    def test_finds_the_branch_ref(self):
        self.assertEqual(
            organizations._detect_git_branch(start=self._make("ref: refs/heads/dev\n")),
            {"branch": "dev", "revision": None})

    def test_detached_head_reports_revision(self):
        self.assertEqual(
            organizations._detect_git_branch(
                start=self._make("82c7cafdeadbeef000011112222333344445555\n")),
            {"branch": None, "revision": "82c7cafdeadb"})

    def test_walks_up_by_max_parents(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        nested = os.path.join(tmp.name, "a", "b", "c")
        os.makedirs(nested)
        git = os.path.join(tmp.name, ".git")
        os.makedirs(git)
        with open(os.path.join(git, "HEAD"), "w") as f:
            f.write("ref: refs/heads/main\n")
        self.assertEqual(
            organizations._detect_git_branch(start=nested, max_parents=4),
            {"branch": "main", "revision": None})

    def test_no_git_returns_nothing(self):
        self.assertEqual(
            organizations._detect_git_branch(start=self._make(head_missing=True)),
            {"branch": None, "revision": None})

    def test_inaccessible_head_never_raises(self):
        self.assertEqual(
            organizations._detect_git_branch(start=self._make(head_contents=None)),
            {"branch": None, "revision": None})


if __name__ == "__main__":
    unittest.main(verbosity=2)