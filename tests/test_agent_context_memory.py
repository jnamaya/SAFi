"""
Work-context memory: deterministic merge, stamps, eviction, and the budget.

The durability rules under test are the ones the docstrings promise:

- Anti-shrink: entries the delta does not mention are carried forward.
- Stamps are applied in Python, never requested from the model: every entry an
  upsert creates or actually CHANGES gets {updated, src}; an upsert that
  changes nothing must not refresh the stamp (fake freshness would defeat
  staleness-based eviction).
- Cap eviction keeps the most recently UPDATED entries, not the last-listed
  ones; unstamped (pre-stamp) entries count as oldest.
- apply_memory_budget bounds the PROMPT copy only: whole entries, oldest
  first, valid JSON out, an in-band truncation notice, and fail-open on
  garbage input. The stored memory is never touched by it.

Run:  venv/bin/python tests/test_agent_context_memory.py
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.orchestrator_mixins.tasks import (
    merge_agent_context, apply_memory_budget, _CTX_CAP,
)

STAMP = {"updated": "2026-08-15", "src": "msg-123"}


def task(text, **kw):
    return {"task": text, "status": "todo", "owner": "", "due": "", **kw}


class StampsAreDeterministic(unittest.TestCase):

    def test_new_entries_get_the_stamp(self):
        out = merge_agent_context({}, {"upserts": {"tasks": [task("Call Comcast")]}}, stamp=STAMP)
        self.assertEqual(out["tasks"][0]["updated"], "2026-08-15")
        self.assertEqual(out["tasks"][0]["src"], "msg-123")

    def test_a_real_change_refreshes_the_stamp(self):
        current = {"tasks": [task("Call Comcast", updated="2026-01-01", src="msg-old")]}
        out = merge_agent_context(
            current, {"upserts": {"tasks": [{"task": "Call Comcast", "status": "done"}]}},
            stamp=STAMP)
        self.assertEqual(out["tasks"][0]["status"], "done")
        self.assertEqual(out["tasks"][0]["updated"], "2026-08-15")
        self.assertEqual(out["tasks"][0]["src"], "msg-123")

    def test_a_no_op_upsert_does_not_fake_freshness(self):
        current = {"tasks": [task("Call Comcast", updated="2026-01-01", src="msg-old")]}
        out = merge_agent_context(
            current, {"upserts": {"tasks": [{"task": "Call Comcast", "status": "todo"}]}},
            stamp=STAMP)
        self.assertEqual(out["tasks"][0]["updated"], "2026-01-01",
                         "an upsert that changed nothing must not refresh the stamp")

    def test_no_stamp_means_no_new_keys(self):
        out = merge_agent_context({}, {"upserts": {"tasks": [task("Call Comcast")]}})
        self.assertNotIn("updated", out["tasks"][0])

    def test_notes_stay_plain_strings(self):
        out = merge_agent_context({}, {"upserts": {"notes": ["prefers Fridays"]}}, stamp=STAMP)
        self.assertEqual(out["notes"], ["prefers Fridays"])

    def test_anti_shrink_still_holds(self):
        current = {"projects": [{"name": "Fiber rollout", "status": "on_track"}]}
        out = merge_agent_context(current, {"upserts": {"tasks": [task("Call Comcast")]}},
                                  stamp=STAMP)
        self.assertEqual(len(out["projects"]), 1)


class EvictionPrefersStaleness(unittest.TestCase):

    def test_the_stale_entry_is_evicted_not_the_first_listed(self):
        # Position 0 is ACTIVE (recent stamp); position 1 is stale. Old
        # tail-keeping would evict position 0.
        tasks = [task("active", updated="2026-08-14"), task("stale", updated="2025-01-01")]
        tasks += [task(f"t{i}", updated="2026-06-01") for i in range(_CTX_CAP - 1)]
        out = merge_agent_context({"tasks": tasks}, {}, stamp=STAMP)
        names = [t["task"] for t in out["tasks"]]
        self.assertEqual(len(names), _CTX_CAP)
        self.assertIn("active", names)
        self.assertNotIn("stale", names)

    def test_unstamped_entries_count_as_oldest(self):
        tasks = [task("prestamp")] + [task(f"t{i}", updated="2026-06-01")
                                      for i in range(_CTX_CAP)]
        out = merge_agent_context({"tasks": tasks}, {}, stamp=STAMP)
        self.assertNotIn("prestamp", [t["task"] for t in out["tasks"]])


class TheBudgetBoundsThePromptCopyOnly(unittest.TestCase):

    def _big_memory(self, n=60):
        return json.dumps({"tasks": [task(f"task number {i} with some padding text") for i in range(n)],
                           "projects": [], "decisions": [], "people": [],
                           "milestones": [], "vendors": [], "notes": []})

    def test_under_budget_passes_through_byte_identical(self):
        m = self._big_memory(3)
        self.assertEqual(apply_memory_budget(m, 100000), m)

    def test_over_budget_output_is_valid_json_within_budget_with_notice(self):
        m = self._big_memory()
        out = apply_memory_budget(m, 1500)
        parsed = json.loads(out)
        self.assertLessEqual(len(json.dumps(parsed, ensure_ascii=False)), 1500)
        self.assertIn("omitted", parsed["truncation_notice"])

    def test_oldest_entries_go_first(self):
        m = self._big_memory()
        parsed = json.loads(apply_memory_budget(m, 1500))
        kept = [t["task"] for t in parsed["tasks"]]
        self.assertIn("task number 59 with some padding text", kept)
        self.assertNotIn("task number 0 with some padding text", kept)

    def test_zero_disables_the_budget(self):
        m = self._big_memory()
        self.assertEqual(apply_memory_budget(m, 0), m)

    def test_fails_open_on_garbage(self):
        self.assertEqual(apply_memory_budget("not json {", 10), "not json {")


class UserFacingMemoryManagement(unittest.TestCase):
    """The view+delete surface (backlog 50b): list, per-item removal through
    the same deterministic merge machinery the extractor uses, and clear.
    Needs the disposable stack (writes agent_context_memory rows)."""

    def setUp(self):
        import uuid
        from safi_app.persistence import database as db
        self.db = db
        self.user = f"test_user_{uuid.uuid4().hex[:8]}"
        self.agent = "test_agent"
        mem = {"tasks": [task("Call Comcast", updated="2026-08-15", src="m1"),
                         task("Ship the report")],
               "milestones": [{"event": "Go-live", "date": "2026-09-01"}]}
        db.upsert_agent_context_memory(self.user, self.agent,
                                       json.dumps(mem, ensure_ascii=False))

    def tearDown(self):
        self.db.delete_agent_context_memory(self.user, self.agent)

    def test_list_shows_the_agent(self):
        rows = self.db.list_agent_context_agents(self.user)
        self.assertEqual([r["agent_id"] for r in rows], [self.agent])

    def test_item_delete_via_merge_removals_and_roundtrip(self):
        current = json.loads(self.db.fetch_agent_context_memory(self.user, self.agent))
        merged = merge_agent_context(current, {"removals": {"tasks": ["Call Comcast"]}})
        self.assertEqual([t["task"] for t in merged["tasks"]], ["Ship the report"])
        # Milestones remove by dict identity (event+date).
        merged = merge_agent_context(merged, {"removals": {
            "milestones": [{"event": "Go-live", "date": "2026-09-01"}]}})
        self.assertEqual(merged["milestones"], [])
        self.db.upsert_agent_context_memory(self.user, self.agent,
                                            json.dumps(merged, ensure_ascii=False))
        back = json.loads(self.db.fetch_agent_context_memory(self.user, self.agent))
        self.assertEqual([t["task"] for t in back["tasks"]], ["Ship the report"])

    def test_clear_deletes_the_row_and_only_for_the_owner(self):
        self.assertFalse(self.db.delete_agent_context_memory("someone_else", self.agent),
                         "another user's delete must not reach this row")
        self.assertTrue(self.db.delete_agent_context_memory(self.user, self.agent))
        self.assertEqual(self.db.list_agent_context_agents(self.user), [])
        self.assertEqual(self.db.fetch_agent_context_memory(self.user, self.agent), "{}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
