"""
Negative tests for the chat_audit_trail hash chain: corrupt a stored chain and
assert detection fires, at the right entry.

WHY THIS FILE EXISTS. Every other chain assertion in tests/ is positive — 15
occurrences of assertTrue(...["valid"]) on untouched chains. That tests the
happy path of a function whose only job is the unhappy path. Demonstrated
2026-07-30: replacing _verify_chain_entries with a stub that recomputes nothing
and returns valid=True still passed all 33 test files. An untested detector is
an unevidenced control, and tamper-evidence is the load-bearing claim in
docs/SEC_COMPLIANCE_READINESS.md.

Chains are built through the real write path (insert_turn_atomic ->
update_message_content -> update_audit_results), not hand-assembled rows —
otherwise this tests the fixture. Tampering is raw SQL, restored in finally.

Two cases are asserted to PASS, deliberately: a full re-chain and a tail
truncation. Those are the real limits of an unkeyed per-message chain, and
pinning them as known-passing is what stops a later reader assuming they are
covered. See the class docstring for TestKnownForgeryLimits.

Requires local MySQL. Run:  venv/bin/python tests/test_tamper_detection.py
"""
import json
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db
from safi_app.persistence import crypto


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def _rows(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    out = cur.fetchall()
    cur.close()
    conn.close()
    return out


_TRAIL_COLS = ("id", "message_pk", "message_id", "conversation_id", "action",
               "actor", "state", "event_at", "prev_hash", "entry_hash",
               "org_id", "created_at")


class _ChainFixture(unittest.TestCase):
    """Builds a real multi-entry chain per test and restores it afterwards."""

    @classmethod
    def setUpClass(cls):
        cls.org_id = str(uuid.uuid4())
        cls.uid = f"tamper_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Tamper Test Org')",
              (cls.org_id,))
        _exec("INSERT INTO users (id, email, name, org_id, role) "
              "VALUES (%s, %s, 'Tamper Test', %s, 'admin')",
              (cls.uid, f"{cls.uid}@example.test", cls.org_id))
        cls.cid = str(uuid.uuid4())
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'tamper test')",
              (cls.cid, cls.uid))
        # Two turns: one under test, one to source a foreign entry from.
        cls.mid = cls._turn("TAMPER prompt one", "TAMPER answer one")
        cls.mid_other = cls._turn("TAMPER prompt two", "TAMPER answer two")
        cls.pk = cls._pk(cls.mid)
        cls.pk_other = cls._pk(cls.mid_other)

    @classmethod
    def _turn(cls, prompt, answer):
        mid = str(uuid.uuid4())
        assert db.insert_turn_atomic(cls.cid, prompt, mid)
        db.update_message_content(mid, answer, audit_status="complete")
        # A SECOND content write, so the 'update' entry journals the previous
        # value — which is Fernet ciphertext. Without this, every state in the
        # fixture records a prior value of NULL and test_10 skips instead of
        # exercising the ciphertext path.
        db.update_message_content(mid, answer + " (revised)", audit_status="complete")
        db.update_audit_results(mid, [{"value": "honesty", "score": 1}], 9,
                                "tamper note", "tamper_agent", ["honesty"],
                                drift=0.1, policy_id="pol-tamper", policy_version=1,
                                model_attribution='{"intellect": "t/m"}',
                                will_decision="approve", will_stage="spirit")
        return mid

    @classmethod
    def _pk(cls, mid):
        return _rows("SELECT id FROM chat_history WHERE message_id=%s", (mid,))[0]["id"]

    @classmethod
    def tearDownClass(cls):
        for sql, params in [
            ("DELETE FROM chat_audit_trail WHERE conversation_id=%s", (cls.cid,)),
            ("DELETE FROM chat_history WHERE conversation_id=%s", (cls.cid,)),
            ("DELETE FROM conversations WHERE id=%s", (cls.cid,)),
            ("DELETE FROM users WHERE id=%s", (cls.uid,)),
            ("DELETE FROM organizations WHERE id=%s", (cls.org_id,)),
        ]:
            _exec(sql, params)

    # --- helpers -------------------------------------------------------------

    def entries(self, pk=None):
        return _rows("SELECT * FROM chat_audit_trail WHERE message_pk=%s ORDER BY id",
                     (pk or self.pk,))

    def snapshot(self, pk=None):
        return self.entries(pk)

    def restore(self, saved, pk=None):
        _exec("DELETE FROM chat_audit_trail WHERE message_pk=%s", (pk or self.pk,))
        for e in saved:
            _exec(f"INSERT INTO chat_audit_trail ({','.join(_TRAIL_COLS)}) "
                  f"VALUES ({','.join(['%s'] * len(_TRAIL_COLS))})",
                  tuple(e[c] for c in _TRAIL_COLS))

    def setUp(self):
        self._saved = self.snapshot()
        self.assertGreaterEqual(len(self._saved), 3,
                                "fixture needs a multi-entry chain to be meaningful")
        self.assertTrue(db.verify_message_audit_trail(self.pk)["valid"],
                        "chain must verify BEFORE tampering, or the test proves nothing")

    def tearDown(self):
        self.restore(self._saved)
        self.assertTrue(db.verify_message_audit_trail(self.pk)["valid"],
                        "restore must leave the chain verifying again")


class TestTamperIsDetected(_ChainFixture):
    """Each test mutates one thing and asserts WHERE detection fires. A bare
    'valid is False' is not evidence — 'entry N is where it diverges' is."""

    def assert_detected_at(self, entry_id, msg=""):
        v = db.verify_message_audit_trail(self.pk)
        self.assertIs(v["valid"], False, f"tampering went undetected — {msg}")
        self.assertEqual(v["first_bad_id"], entry_id,
                         f"detected, but blamed the wrong entry — {msg}")

    def test_01_record_contents_cannot_be_edited(self):
        """The compliance case: someone rewrites what the system decided."""
        target = self._saved[1]
        state = json.loads(target["state"]) if target["state"] else {}
        state["_injected"] = "will_decision was never approve"
        _exec("UPDATE chat_audit_trail SET state=%s WHERE id=%s",
              (json.dumps(state), target["id"]))
        self.assert_detected_at(target["id"], "state edited")

    def test_02_attribution_cannot_be_rewritten(self):
        """Who approved this is the question an examiner asks first."""
        target = self._saved[1]
        _exec("UPDATE chat_audit_trail SET actor=%s WHERE id=%s",
              ("user:somebody-else", target["id"]))
        self.assert_detected_at(target["id"], "actor edited")

    def test_03_timing_cannot_be_backdated(self):
        target = self._saved[1]
        _exec("UPDATE chat_audit_trail SET event_at=%s WHERE id=%s",
              ("2020-01-01T00:00:00+00:00", target["id"]))
        self.assert_detected_at(target["id"], "event_at backdated")

    def test_04_message_binding_cannot_be_swapped(self):
        """message_id is inside the payload, so an entry cannot be re-pointed
        at a different message and keep its hash."""
        target = self._saved[1]
        _exec("UPDATE chat_audit_trail SET message_id=%s WHERE id=%s",
              (self.mid_other, target["id"]))
        self.assert_detected_at(target["id"], "message_id swapped")

    def test_05_stored_hash_cannot_be_forged_by_hand(self):
        target = self._saved[1]
        _exec("UPDATE chat_audit_trail SET entry_hash=%s WHERE id=%s",
              ("0" * 64, target["id"]))
        self.assert_detected_at(target["id"], "entry_hash overwritten")

    def test_06_broken_link_is_detected(self):
        """prev_hash is the link itself; cutting it must not pass."""
        target = self._saved[2]
        _exec("UPDATE chat_audit_trail SET prev_hash=%s WHERE id=%s",
              ("f" * 64, target["id"]))
        self.assert_detected_at(target["id"], "prev_hash rewritten")

    def test_07_deleting_a_middle_entry_is_detected(self):
        """Removing the inconvenient step. Detection lands on the FOLLOWING
        entry, whose prev_hash no longer matches the recomputed tip."""
        removed, following = self._saved[1], self._saved[2]
        _exec("DELETE FROM chat_audit_trail WHERE id=%s", (removed["id"],))
        self.assert_detected_at(following["id"], "middle entry deleted")

    def test_08_reordering_two_entries_is_detected(self):
        """Order is by id, so swapping ids reorders the chain."""
        a, b = self._saved[1], self._saved[2]
        spare = 10 ** 9 + 7
        _exec("UPDATE chat_audit_trail SET id=%s WHERE id=%s", (spare, a["id"]))
        _exec("UPDATE chat_audit_trail SET id=%s WHERE id=%s", (a["id"], b["id"]))
        _exec("UPDATE chat_audit_trail SET id=%s WHERE id=%s", (spare, b["id"]))
        v = db.verify_message_audit_trail(self.pk)
        self.assertIs(v["valid"], False, "reordering went undetected")

    def test_09_foreign_entry_spliced_in_is_detected(self):
        """A genuine, internally valid entry from ANOTHER message, inserted into
        this chain. Its hash was computed over a different message_pk."""
        alien = self.entries(self.pk_other)[1]
        cols = [c for c in _TRAIL_COLS if c != "id"]
        vals = [self.pk if c == "message_pk" else alien[c] for c in cols]
        _exec(f"INSERT INTO chat_audit_trail ({','.join(cols)}) "
              f"VALUES ({','.join(['%s'] * len(cols))})", tuple(vals))
        v = db.verify_message_audit_trail(self.pk)
        self.assertIs(v["valid"], False, "spliced foreign entry went undetected")

    def test_10_ciphertext_tampering_is_detected_without_the_key(self):
        """The chain covers encrypted state as stored, so corruption is caught
        without decrypting anything — the verifier never needs the Fernet key."""
        if not crypto.is_enabled():
            self.skipTest("encryption not configured in this environment")
        target = next((e for e in self._saved
                       if e["state"] and "gAAAA" in e["state"]), None)
        if target is None:
            self.skipTest("no encrypted field present in this fixture's states")
        garbled = target["state"].replace("gAAAA", "gAAAB", 1)
        _exec("UPDATE chat_audit_trail SET state=%s WHERE id=%s",
              (garbled, target["id"]))
        self.assert_detected_at(target["id"], "ciphertext in state altered")

    def test_11_empty_chain_is_not_a_pass(self):
        """Deleting the WHOLE chain leaves nothing to verify. Absence of
        evidence must not report as verified (fixed in b1479db)."""
        _exec("DELETE FROM chat_audit_trail WHERE message_pk=%s", (self.pk,))
        v = db.verify_message_audit_trail(self.pk)
        self.assertIsNone(v["valid"], "0 entries must be null, never true")
        self.assertEqual(v["entries"], 0)
        self.assertIsNone(v["entry_hash"])


class TestKnownForgeryLimits(_ChainFixture):
    """Cases that PASS verification, on purpose.

    These are the real limits of an unkeyed per-message chain. They are asserted
    here so the limits are pinned and visible rather than assumed to be covered:
    if either of these ever starts failing, the threat model changed and this
    file should be revisited, not 'fixed'.
    """

    def test_12_full_rechain_is_NOT_detected(self):
        """Edit an entry, then recompute it and every successor. The chain is
        unkeyed and we recompute with the same public function an attacker has,
        so the result verifies clean. This is what an out-of-DB HMAC key closes:
        without the key the attacker cannot produce the successor hashes.
        """
        import hashlib
        target_idx = 1
        entries = [dict(e) for e in self._saved]
        state = json.loads(entries[target_idx]["state"]) if entries[target_idx]["state"] else {}
        state["_forged"] = "rewritten history"
        entries[target_idx]["state"] = json.dumps(state)

        prev = None
        for e in entries:
            payload = db.trail_payload(e["message_pk"], e["message_id"],
                                       e["conversation_id"], e["action"],
                                       e["actor"], e["state"], e["event_at"], prev)
            e["prev_hash"] = prev
            e["entry_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            prev = e["entry_hash"]
        self.restore(entries)

        v = db.verify_message_audit_trail(self.pk)
        self.assertIs(v["valid"], True,
                      "a consistently re-chained forgery is expected to pass — "
                      "if this now fails, the chain gained a key and this test "
                      "should be inverted")
        forged = _rows("SELECT state FROM chat_audit_trail WHERE id=%s",
                       (self._saved[target_idx]["id"],))[0]["state"]
        self.assertIn("_forged", forged,
                      "the forgery must actually be present, or this proves nothing")

    def test_13_tail_truncation_is_NOT_detected(self):
        """Delete the most recent entries. The surviving prefix is internally
        consistent, so per-chain verification cannot see the loss — nothing in
        the table records how many entries there should be. This is a SECOND,
        independent reason to anchor an entry COUNT externally, not just a root.
        """
        tail = self._saved[-1]
        _exec("DELETE FROM chat_audit_trail WHERE id=%s", (tail["id"],))
        v = db.verify_message_audit_trail(self.pk)
        self.assertIs(v["valid"], True,
                      "truncation is expected to pass per-chain verification")
        self.assertEqual(v["entries"], len(self._saved) - 1,
                         "the only visible symptom is a lower entry count, which "
                         "is why the external anchor must record the count")


if __name__ == "__main__":
    unittest.main(verbosity=2)
