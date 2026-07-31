"""
The Will's verdict on a tool call must reach the tamper-evident chain.

WHY. The README's fifth principle claims "the action taken is recorded alongside
the decision". When that was challenged, the decision half turned out to be
false. Every reasoning step was journaled into the hash-chained
`chat_audit_trail` — but a step carried only what `_tool_status()` returns, and
that is, by its own docstring, "a human-friendly thinking-indicator message":

    {"step": "Fetching stock data...", "timestamp": "...", "phase": "gather"}

Which tool, with what arguments, and above all the Will's verdict were absent.
Worse, the label was written BEFORE the gate ran, so an APPROVED and a BLOCKED
tool call left identical entries. A denial existed only as
`self.log.warning(...)` — in a log file that is neither append-only nor
hash-chained — while the product's whole claim is a tamper-evident record of
enforcement.

These tests pin the record, not the plumbing:
  * a tool step names the tool and the verdict
  * a denial is distinguishable from an approval BY CONTENT, not by entry count
  * the chain still verifies with the enriched step in it
  * parameter values are capped, so no payload lands in an append-only chain
  * `step`/`timestamp`/`phase` cannot be overwritten by a caller

Needs the disposable stack (it writes real turns and chain entries):
    docker compose -f docker-compose.test.yml run --rm --build tests -k tool_verdict
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
    try:
        cur.execute(sql, params)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _rows(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


class ToolVerdictReachesTheChain(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.org_id = str(uuid.uuid4())
        cls.uid = f"toolaudit_{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO organizations (id, name) VALUES (%s, 'Tool Audit Org')",
              (cls.org_id,))
        _exec("INSERT INTO users (id, email, name, org_id, role) "
              "VALUES (%s, %s, 'Tool Audit', %s, 'admin')",
              (cls.uid, f"{cls.uid}@example.test", cls.org_id))
        cls.cid = str(uuid.uuid4())
        _exec("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, 'tool audit')",
              (cls.cid, cls.uid))
        cls.mid = str(uuid.uuid4())
        assert db.insert_turn_atomic(cls.cid, "What is AAPL trading at?", cls.mid)
        cls.pk = _rows("SELECT id FROM chat_history WHERE message_id=%s AND role='ai'",
                       (cls.mid,))[0]["id"]

    @classmethod
    def tearDownClass(cls):
        _exec("DELETE FROM chat_audit_trail WHERE conversation_id=%s", (cls.cid,))
        _exec("DELETE FROM chat_history WHERE conversation_id=%s", (cls.cid,))
        _exec("DELETE FROM conversations WHERE id=%s", (cls.cid,))
        _exec("DELETE FROM users WHERE id=%s", (cls.uid,))
        _exec("DELETE FROM organizations WHERE id=%s", (cls.org_id,))

    def _steps(self):
        """Every reasoning step, decrypted, as the auditor would read them."""
        raw = _rows("SELECT reasoning_log FROM chat_history WHERE message_id=%s AND role='ai'",
                    (self.mid,))[0]["reasoning_log"]
        log = crypto.decrypt_value(raw)
        log = json.loads(log) if isinstance(log, str) else log
        return log or []

    def _chain_states(self):
        """Decrypted reasoning steps as they appear in the hash chain itself."""
        out = []
        for r in _rows("SELECT action, state FROM chat_audit_trail "
                       "WHERE message_id=%s ORDER BY id", (self.mid,)):
            st = r["state"]
            if isinstance(st, str):
                try:
                    st = json.loads(st)
                except Exception:
                    st = {}
            enc = (st or {}).get("reasoning_step_enc")
            if enc:
                dec = crypto.decrypt_value(enc)
                out.append(json.loads(dec) if isinstance(dec, str) else dec)
        return out

    def test_01_an_approved_tool_call_names_the_tool_and_the_verdict(self):
        db.update_message_reasoning(
            self.mid, "Fetching stock data...", phase="gather",
            extra={"tool": "get_stock_price", "decision": "approve",
                   "reason": "Read-only fast pass.",
                   "params": {"ticker": "AAPL"}})
        step = self._steps()[-1]
        self.assertEqual(step.get("tool"), "get_stock_price",
                         "the tool name must be recorded — the label alone buckets "
                         "every write verb into 'Taking an action'")
        self.assertEqual(step.get("decision"), "approve")
        self.assertEqual(step.get("phase"), "gather")

    def test_02_a_denial_is_recorded_and_distinguishable_by_content(self):
        """The property that was missing. Not by entry count — by content."""
        db.update_message_reasoning(
            self.mid, "Blocked a tool call", phase="gather",
            extra={"tool": "upload_item", "decision": "violation",
                   "reason": "Tool 'upload_item' is not authorized for this agent profile.",
                   "params": {"name": "q3.txt", "content": "x" * 40}})
        steps = [s for s in self._steps() if s.get("tool") == "upload_item"]
        self.assertTrue(steps, "the denied tool call was not journaled at all")
        denial = steps[-1]
        self.assertEqual(denial.get("decision"), "violation")
        self.assertIn("not authorized", denial.get("reason", ""),
                      "the reason must survive — 'it was blocked' without why is "
                      "not an audit record")
        approvals = [s for s in self._steps() if s.get("decision") == "approve"]
        self.assertTrue(approvals, "sanity: an approval should also be present")
        self.assertNotEqual(denial.get("decision"), approvals[-1].get("decision"),
                            "an approval and a denial must not read identically")

    def test_03_the_verdict_is_in_the_HASH_CHAIN_not_only_the_message_row(self):
        """chat_history.reasoning_log is not the tamper-evident artefact. The
        claim is about the chain, so assert on the chain."""
        chain_steps = self._chain_states()
        tools = {s.get("tool") for s in chain_steps if isinstance(s, dict)}
        self.assertIn("get_stock_price", tools,
                      "the approved tool never reached chat_audit_trail")
        self.assertIn("upload_item", tools,
                      "the DENIED tool never reached chat_audit_trail — it would "
                      "exist only in the application log")
        denied = [s for s in chain_steps
                  if isinstance(s, dict) and s.get("tool") == "upload_item"]
        self.assertEqual(denied[-1].get("decision"), "violation")

    def test_04_the_chain_still_verifies_with_the_enriched_steps(self):
        v = db.verify_message_audit_trail(self.pk)
        self.assertTrue(v["valid"],
                        f"chain broke after journaling tool verdicts: {v}")

    def test_05_parameter_values_are_capped(self):
        """chat_audit_trail is append-only and hash-chained. A megabyte of upload
        `content` copied in would bloat the chain permanently."""
        from safi_app.core.orchestrator import _audit_params, AUDIT_PARAM_MAXLEN
        big = _audit_params({"name": "big.txt", "content": "y" * 50_000})
        self.assertLessEqual(len(big["content"]), AUDIT_PARAM_MAXLEN + 40,
                             "a large parameter value was not clipped")
        self.assertIn("chars]", big["content"], "truncation should be marked")
        self.assertEqual(big["name"], "big.txt", "short values must pass through")

    def test_06_reserved_keys_cannot_be_overwritten_by_extra(self):
        """A caller must not be able to rewrite the step label or its timestamp
        through `extra` — that would let a tool step forge its own history."""
        db.update_message_reasoning(
            self.mid, "Genuine label", phase="gather",
            extra={"step": "FORGED", "timestamp": "1970-01-01T00:00:00+00:00",
                   "phase": "audit", "tool": "web_search", "decision": "approve"})
        step = self._steps()[-1]
        self.assertEqual(step["step"], "Genuine label")
        self.assertNotEqual(step["timestamp"], "1970-01-01T00:00:00+00:00")
        self.assertEqual(step["phase"], "gather")
        self.assertEqual(step["tool"], "web_search", "non-reserved keys still apply")


class BothGateSitesJournalAfterTheVerdict(unittest.TestCase):
    """There are two gate sites — the first intent and each follow-up in the
    agent loop — and both used to write the label BEFORE the verdict, which is
    what made an approval and a denial indistinguishable."""

    @classmethod
    def setUpClass(cls):
        cls.src = (Path(__file__).resolve().parent.parent / "safi_app" / "core"
                   / "orchestrator.py").read_text(encoding="utf-8", errors="replace")

    def test_07_every_gate_call_is_followed_by_a_journal_write(self):
        import re
        gates = [m.start() for m in re.finditer(r"evaluate_tool_intent\(", self.src)]
        self.assertGreaterEqual(len(gates), 2,
                                "expected both the first-intent and follow-up gate sites")
        for pos in gates:
            with self.subTest(offset=pos):
                after = self.src[pos:pos + 1200]
                self.assertIn("update_message_reasoning", after,
                              "a gate verdict is not journaled after this call")
                self.assertIn('"decision"', after,
                              "the verdict itself must be journaled, not just a label")

    def test_08_no_bare_pre_gate_label_write_remains(self):
        """The regression to guard: writing `_tool_status(...)` immediately before
        the gate reintroduces identical entries for approve and block."""
        import re
        bad = re.search(
            r"update_message_reasoning\([^)]*_tool_status\([^)]*\)[^)]*\)\s*\n\s*"
            r"(tool_decision|follow_decision)[^\n]*=\s*await",
            self.src)
        self.assertIsNone(
            bad, "a label is written before the gate again — an approved and a "
                 "blocked tool call will leave identical audit entries")


if __name__ == "__main__":
    unittest.main(verbosity=2)
