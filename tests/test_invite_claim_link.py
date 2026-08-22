"""
Backlog 51: an invite-claim link lets a member with no Google/Microsoft
account on their domain join anyway, by setting a password themselves.

WHY. SAFi's only login mechanisms were Google OAuth, Microsoft OAuth, and one
hardcoded local-admin account, so an invitee on neither Workspace nor
Microsoft 365 had no way to ever claim their invitation — it just expired
silently. The fix has to actually verify the invitee controls that mailbox,
which is why the claim token is only ever meant to reach them via SMTP
delivered straight to the invited address (organizations.py's
_send_invite_claim_email) — there is no "copy invite link" path anywhere. A
link handed over any other way would prove nothing about who is claiming it.

This file tests the verification and claim mechanics (auth.py's
issue_invite_claim_token/verify_invite_claim_token, database.py's
claim_invitation_with_password, and POST /api/invite/claim), not the SMTP
transport itself.

Needs the disposable stack:
    docker compose -f docker-compose.test.yml run --rm tests -k invite_claim
"""
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.config import Config
from safi_app.persistence import database as db
from safi_app.api import auth as auth_api

from support import new_user, login_as


class InviteClaimLink(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def setUp(self):
        tag = uuid.uuid4().hex[:8]
        self.org_id = db.create_organization(f"Claim Test Org {tag}")
        self.actor = "user:test-admin"
        self.client = self.app.test_client()

    def tearDown(self):
        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM sessions WHERE org_id=%s", (self.org_id,))
            cur.execute("DELETE FROM org_invitations WHERE org_id=%s", (self.org_id,))
            cur.execute("DELETE FROM auth_events WHERE org_id=%s", (self.org_id,))
            cur.execute("DELETE FROM users WHERE org_id=%s", (self.org_id,))
            cur.execute("DELETE FROM organizations WHERE id=%s", (self.org_id,))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def _email(self, tag):
        return f"{tag}-{uuid.uuid4().hex[:6]}@weirddomain.example"

    def _invite(self, email, role="member"):
        return db.create_org_invitation(self.org_id, email, role, self.actor)

    def _token(self, inv, expires_days=14):
        with self.app.app_context():
            return auth_api.issue_invite_claim_token(inv["id"], inv["email"], expires_days)

    def _claim(self, token, password="correct-horse-battery", name="Test Invitee"):
        return self.client.post("/api/invite/claim",
                                json={"token": token, "name": name, "password": password})

    # ---- token round trip ----

    def test_token_round_trips_to_the_right_invite(self):
        inv = self._invite(self._email("a"))
        token = self._token(inv)
        with self.app.app_context():
            claim = auth_api.verify_invite_claim_token(token)
        self.assertEqual(claim["invite_id"], inv["id"])
        self.assertEqual(claim["email"], inv["email"])

    def test_a_differently_typed_token_is_rejected(self):
        with self.app.app_context():
            mfa_token = auth_api._issue_mfa_token("some-user-id")
            self.assertIsNone(auth_api.verify_invite_claim_token(mfa_token))

    # ---- the claim endpoint ----

    def test_claiming_joins_the_org_with_the_invited_role(self):
        email = self._email("b")
        inv = self._invite(email, role="editor")
        res = self._claim(self._token(inv))
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertTrue(res.get_json().get("ok"))

        user = db.get_user_by_email(email)
        self.assertIsNotNone(user)
        self.assertEqual(str(user["org_id"]), str(self.org_id))
        self.assertEqual(user["role"], "editor")
        self.assertIsNotNone(user.get("password_hash"))

    def test_claiming_establishes_a_real_session(self):
        email = self._email("c")
        inv = self._invite(email)
        self._claim(self._token(inv))

        me = self.client.get("/api/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json().get("user", {}).get("email"), email)

    def test_the_invitation_row_is_stamped_accepted(self):
        inv = self._invite(self._email("d"))
        self._claim(self._token(inv))

        conn = db.get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT accepted_at FROM org_invitations WHERE id=%s", (inv["id"],))
            row = cur.fetchone()
        finally:
            cur.close()
            conn.close()
        self.assertIsNotNone(row["accepted_at"])

    def test_a_short_password_is_rejected(self):
        inv = self._invite(self._email("e"))
        res = self._claim(self._token(inv), password="short")
        self.assertEqual(res.status_code, 400)

    def test_the_same_link_cannot_be_claimed_twice(self):
        inv = self._invite(self._email("f"))
        token = self._token(inv)
        first = self._claim(token)
        self.assertEqual(first.status_code, 200)
        second = self._claim(token, password="a-different-password")
        self.assertEqual(second.status_code, 400)

    def test_revoking_the_invitation_kills_the_link_before_the_token_expires(self):
        inv = self._invite(self._email("g"))
        token = self._token(inv)  # still valid for 14 days
        db.revoke_org_invitation(self.org_id, inv["id"], self.actor)

        res = self._claim(token)
        self.assertEqual(res.status_code, 400)

    def test_an_expired_token_is_rejected_even_though_the_row_is_still_live(self):
        inv = self._invite(self._email("h"))
        token = self._token(inv, expires_days=-1)
        res = self._claim(token)
        self.assertEqual(res.status_code, 400)

    def test_claiming_adds_a_password_to_an_existing_oauth_account(self):
        """An invitee who already has a SAFi account via Google keeps it —
        the claim link adds a password credential rather than duplicating
        the user row."""
        email = self._email("i")
        uid = new_user(email=email)  # simulates a prior Google/Microsoft login
        inv = self._invite(email)

        res = self._claim(self._token(inv))
        self.assertEqual(res.status_code, 200, res.get_json())

        user = db.get_user_by_email(email)
        self.assertEqual(user["id"], uid, "must reuse the existing user row, not create a new one")
        self.assertEqual(str(user["org_id"]), str(self.org_id))
        self.assertIsNotNone(user["password_hash"])
        self.assertEqual(user["name"], "Test User",
                         "an existing account's real display name must not be overwritten "
                         "by whatever the claim form happened to be filled with")

    def test_claiming_sets_the_display_name_on_a_new_account(self):
        email = self._email("l")
        inv = self._invite(email)
        res = self._claim(self._token(inv), name="Jane Q. Invitee")
        self.assertEqual(res.status_code, 200, res.get_json())

        user = db.get_user_by_email(email)
        self.assertEqual(user["name"], "Jane Q. Invitee")

    def test_a_missing_name_is_rejected(self):
        inv = self._invite(self._email("m"))
        res = self.client.post("/api/invite/claim",
                               json={"token": self._token(inv), "password": "correct-horse-battery"})
        self.assertEqual(res.status_code, 400)

    def test_reinviting_the_same_email_returns_an_id_the_new_token_can_claim(self):
        """Regression: create_org_invitation's ON DUPLICATE KEY UPDATE path
        (uq_org_email) used to return a freshly generated id that was never
        actually written — the existing row keeps its own id. Delete +
        re-invite is the everyday way to hit this: claim, delete the user,
        invite the same email again, claim the NEW link."""
        email = self._email("j")
        first_inv = self._invite(email)
        first_claim = self._claim(self._token(first_inv))
        self.assertEqual(first_claim.status_code, 200, first_claim.get_json())

        conn = db.get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM users WHERE email=%s", (email,))
            conn.commit()
        finally:
            cur.close()
            conn.close()

        second_inv = self._invite(email)  # hits uq_org_email — the update path
        second_claim = self._claim(self._token(second_inv))
        self.assertEqual(second_claim.status_code, 200, second_claim.get_json())

        user = db.get_user_by_email(email)
        self.assertEqual(str(user["org_id"]), str(self.org_id))

    # ---- repeat login after claiming (not the link — the ordinary form) ----

    def test_claimed_account_can_log_in_again_with_login_local(self):
        email = self._email("k")
        password = "correct-horse-battery"
        inv = self._invite(email)
        claim_res = self._claim(self._token(inv), password=password)
        self.assertEqual(claim_res.status_code, 200, claim_res.get_json())

        # A fresh client: the claim response's session must not be what
        # makes this work, or it isn't testing repeat login at all.
        fresh_client = self.app.test_client()
        res = fresh_client.post("/api/login/local", json={"email": email, "password": password})
        self.assertEqual(res.status_code, 200, res.get_json())

        me = fresh_client.get("/api/me")
        self.assertEqual(me.get_json().get("user", {}).get("email"), email)

    # ---- password_login_available() gates /login/local + app-config ----

    def test_password_login_available_when_only_smtp_is_configured(self):
        orig_local, orig_host, orig_from = (
            Config.ENABLE_LOCAL_LOGIN, Config.SMTP_HOST, Config.SMTP_FROM)
        try:
            Config.ENABLE_LOCAL_LOGIN = False
            Config.SMTP_HOST, Config.SMTP_FROM = "smtp.example.test", "noreply@example.test"
            self.assertTrue(Config.password_login_available(),
                            "an invite-claim account can only exist if SMTP was "
                            "configured, so the login form must stay reachable")
        finally:
            Config.ENABLE_LOCAL_LOGIN, Config.SMTP_HOST, Config.SMTP_FROM = (
                orig_local, orig_host, orig_from)

    def test_password_login_unavailable_with_neither_configured(self):
        orig_local, orig_host, orig_from = (
            Config.ENABLE_LOCAL_LOGIN, Config.SMTP_HOST, Config.SMTP_FROM)
        try:
            Config.ENABLE_LOCAL_LOGIN = False
            Config.SMTP_HOST, Config.SMTP_FROM = "", ""
            self.assertFalse(Config.password_login_available())
        finally:
            Config.ENABLE_LOCAL_LOGIN, Config.SMTP_HOST, Config.SMTP_FROM = (
                orig_local, orig_host, orig_from)

    # ---- invite creation reports whether a claim email actually went out ----

    def test_creating_an_invitation_reports_no_claim_email_when_smtp_is_unconfigured(self):
        # The disposable test stack sets no SMTP_* vars, matching a fresh
        # self-hosted install before an operator configures outbound email.
        admin_uid = new_user(org_id=self.org_id, role="admin")
        login_as(self.client, admin_uid, "admin", org_id=self.org_id)

        res = self.client.post(f"/api/organizations/{self.org_id}/invitations",
                               json={"email": self._email("j"), "role": "member"})
        self.assertEqual(res.status_code, 201, res.get_json())
        self.assertFalse(res.get_json()["invitation"]["claim_email_sent"],
                         "no SMTP configured — no claim email should be attempted")


if __name__ == "__main__":
    unittest.main()
