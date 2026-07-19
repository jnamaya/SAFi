"""
Unit tests for the human review queue's sampling layer (Phase E1):
deterministic random sampling, the trigger matrix, config merge over
defaults, and set_org_review_config input validation.

Run:  venv/bin/python tests/test_review_sampling.py

Pure-logic tests only — no DB. The transactional enqueue path
(_maybe_enqueue_review inside update_audit_results) shares its cursor with
the governance commit and is exercised end-to-end by the running service.
"""
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence.database import (
    REVIEW_CONFIG_DEFAULTS,
    _merged_review_config,
    evaluate_review_triggers,
    validate_review_config_changes,
)


def cfg_with(**overrides):
    cfg = _merged_review_config(None)
    for key, val in overrides.items():
        if key in ("triggers", "alerts"):
            cfg[key].update(val)
        else:
            cfg[key] = val
    return cfg


class TestConfigMerge(unittest.TestCase):
    def test_absent_config_yields_defaults(self):
        cfg = _merged_review_config(None)
        self.assertEqual(cfg, REVIEW_CONFIG_DEFAULTS)
        self.assertFalse(cfg["enabled"])

    def test_merge_never_mutates_defaults(self):
        cfg = _merged_review_config({"triggers": {"alignment_threshold": 8}})
        self.assertEqual(cfg["triggers"]["alignment_threshold"], 8)
        self.assertEqual(REVIEW_CONFIG_DEFAULTS["triggers"]["alignment_threshold"], 6)

    def test_partial_stored_config_keeps_other_defaults(self):
        cfg = _merged_review_config({"enabled": True, "alerts": {"webhook_url": "https://x.example/hook"}})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["alerts"]["webhook_url"], "https://x.example/hook")
        self.assertEqual(cfg["alerts"]["alignment_window_turns"], 20)
        self.assertEqual(cfg["random_sample_pct"], 5)


class TestDeterministicSampling(unittest.TestCase):
    MSG = "a3a6745c-6be6-4a67-b1cb-6f2b30e11fca"

    def _sampled(self, message_id, pct):
        cfg = cfg_with(random_sample_pct=pct,
                       triggers={"hard_gate_block": False, "gateway_violation": False,
                                 "low_alignment": False, "drift_spike": False})
        triggers, _ = evaluate_review_triggers(cfg, message_id, "conv1", 9, 0.1, "approve", None)
        return "random_sample" in triggers

    def test_pct_100_always_samples(self):
        for i in range(50):
            self.assertTrue(self._sampled(f"msg-{i}", 100))

    def test_pct_0_never_samples(self):
        for i in range(50):
            self.assertFalse(self._sampled(f"msg-{i}", 0))

    def test_same_message_same_outcome(self):
        first = self._sampled(self.MSG, 5)
        for _ in range(10):
            self.assertEqual(self._sampled(self.MSG, 5), first)

    def test_matches_published_formula(self):
        # The examiner-facing contract: sampled iff sha256(message_id) % 10000 < pct*100.
        pct = 7
        for i in range(200):
            mid = f"contract-{i}"
            expected = int(hashlib.sha256(mid.encode()).hexdigest(), 16) % 10000 < pct * 100
            self.assertEqual(self._sampled(mid, pct), expected, mid)

    def test_rate_roughly_matches_pct(self):
        hits = sum(self._sampled(f"rate-{i}", 10) for i in range(2000))
        self.assertGreater(hits, 120)   # ~200 expected at 10%
        self.assertLess(hits, 290)


class TestTriggerMatrix(unittest.TestCase):
    def eval(self, cfg=None, message_id="m1", conversation_id="conv1",
             score=9, drift=0.1, will_decision="approve", will_stage=None):
        cfg = cfg or cfg_with(random_sample_pct=0)
        return evaluate_review_triggers(cfg, message_id, conversation_id,
                                        score, drift, will_decision, will_stage)

    def test_clean_turn_no_triggers(self):
        triggers, detail = self.eval()
        self.assertEqual(triggers, [])
        self.assertEqual(detail, {})

    def test_hard_gate_keys_on_stage_alone(self):
        # Native hard-gate blocks ship as redirects — decision is 'redirected'.
        triggers, detail = self.eval(will_decision="redirected", will_stage="hard_gate",
                                     score=None, drift=None)
        self.assertEqual(triggers, ["hard_gate_block"])
        self.assertEqual(detail["will_stage"], "hard_gate")

    def test_gateway_violation_needs_gw_namespace(self):
        triggers, _ = self.eval(conversation_id="gw_agent-7", will_decision="violation",
                                will_stage="structure", score=None, drift=None)
        self.assertIn("gateway_violation", triggers)
        triggers, _ = self.eval(conversation_id="native-conv", will_decision="violation",
                                will_stage="structure", score=None, drift=None)
        self.assertNotIn("gateway_violation", triggers)

    def test_gateway_hard_gate_matches_both(self):
        triggers, _ = self.eval(conversation_id="gw_x", will_decision="violation",
                                will_stage="hard_gate", score=None, drift=None)
        self.assertEqual(set(triggers), {"hard_gate_block", "gateway_violation"})

    def test_low_alignment_threshold_is_strict_less_than(self):
        triggers, detail = self.eval(score=5)
        self.assertEqual(triggers, ["low_alignment"])
        self.assertEqual(detail["spirit_score"], 5)
        triggers, _ = self.eval(score=6)
        self.assertEqual(triggers, [])

    def test_null_score_never_low_alignment(self):
        # N/A is not a default — a redirect's None score must not read as 0.
        triggers, _ = self.eval(score=None)
        self.assertEqual(triggers, [])

    def test_drift_spike_strict_greater_than(self):
        triggers, detail = self.eval(drift=0.41)
        self.assertEqual(triggers, ["drift_spike"])
        self.assertAlmostEqual(detail["drift"], 0.41)
        triggers, _ = self.eval(drift=0.4)
        self.assertEqual(triggers, [])
        triggers, _ = self.eval(drift=None)
        self.assertEqual(triggers, [])

    def test_disabled_triggers_do_not_fire(self):
        cfg = cfg_with(random_sample_pct=0,
                       triggers={"hard_gate_block": False, "low_alignment": False,
                                 "drift_spike": False, "gateway_violation": False})
        triggers, _ = self.eval(cfg=cfg, score=1, drift=0.9,
                                will_decision="violation", will_stage="hard_gate",
                                conversation_id="gw_x")
        self.assertEqual(triggers, [])

    def test_detail_carries_will_provenance_when_triggered(self):
        _, detail = self.eval(score=3)
        self.assertEqual(detail["will_decision"], "approve")
        self.assertIn("will_stage", detail)

    def test_custom_thresholds_respected(self):
        cfg = cfg_with(random_sample_pct=0,
                       triggers={"alignment_threshold": 8, "drift_threshold": 0.2})
        triggers, _ = self.eval(cfg=cfg, score=7, drift=0.3)
        self.assertEqual(set(triggers), {"low_alignment", "drift_spike"})


class TestConfigValidation(unittest.TestCase):
    def ok(self, changes):
        validate_review_config_changes(changes)

    def bad(self, changes):
        with self.assertRaises(ValueError):
            validate_review_config_changes(changes)

    def test_valid_full_update(self):
        self.ok({"enabled": True, "random_sample_pct": 12.5,
                 "triggers": {"hard_gate_block": True, "alignment_threshold": 7,
                              "drift_spike": False, "drift_threshold": 0.5},
                 "alerts": {"webhook_url": "https://hooks.example.com/safi",
                            "alignment_avg_threshold": 5,
                            "alignment_window_turns": 50,
                            "backlog_max_age_days": 7}})

    def test_valid_partial_update(self):
        self.ok({"enabled": True})
        self.ok({"triggers": {"alignment_threshold": 6}})
        self.ok({"alerts": {"webhook_url": None}})

    def test_unknown_keys_rejected(self):
        self.bad({"sample_everything": True})
        self.bad({"triggers": {"jailbreak": True}})
        self.bad({"alerts": {"email": "a@b.c"}})

    def test_type_and_range_enforcement(self):
        self.bad({"enabled": "yes"})
        self.bad({"random_sample_pct": -1})
        self.bad({"random_sample_pct": 101})
        self.bad({"random_sample_pct": True})  # bool is not a number here
        self.bad({"triggers": {"alignment_threshold": 11}})
        self.bad({"triggers": {"drift_threshold": 2}})
        self.bad({"triggers": {"hard_gate_block": 1}})
        self.bad({"alerts": {"webhook_url": "ftp://x"}})
        self.bad({"alerts": {"webhook_url": "https://" + "x" * 512}})
        self.bad({"alerts": {"alignment_window_turns": 0}})
        self.bad({"alerts": {"backlog_max_age_days": 366}})
        self.bad("enabled")


if __name__ == "__main__":
    unittest.main(verbosity=2)
