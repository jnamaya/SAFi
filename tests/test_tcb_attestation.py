import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from safi_app.core import integrity

DB_SRC = (ROOT / "safi_app" / "persistence" / "database.py").read_text(encoding="utf-8")
APP_INIT = (ROOT / "safi_app" / "__init__.py").read_text(encoding="utf-8")


class BootVerification(unittest.TestCase):

    def test_the_shipped_tree_attests_intact(self):
        s = integrity.get_status(refresh=True)
        self.assertEqual(s["state"], "intact", s)
        self.assertTrue(s["intact"])
        self.assertEqual(len(s["fingerprint"]), 64)
        self.assertEqual(s["fingerprint"], s["expected_fingerprint"])

    def test_the_status_agrees_with_the_canonical_checker(self):
        import json as j, subprocess
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_integrity.py"),
                            "--json"], capture_output=True, text=True, timeout=120)
        by_hand = j.loads(p.stdout)
        self.assertEqual(integrity.get_status()["fingerprint"],
                         by_hand["root_fingerprint_actual"])

    def test_a_tampered_tree_attests_modified(self):
        with tempfile.TemporaryDirectory(prefix="safi-att-") as d:
            root = Path(d)
            (root / "scripts").mkdir()
            shutil.copytree(ROOT / "safi_app", root / "safi_app",
                            ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy(ROOT / "scripts" / "core_integrity_manifest.json",
                        root / "scripts" / "core_integrity_manifest.json")
            f = root / "safi_app" / "core" / "faculties" / "will.py"
            f.write_text(f.read_text() + "\n# tampered\n")
            s = integrity.get_status(root=root)
            self.assertEqual(s["state"], "modified")
            self.assertIn("safi_app/core/faculties/will.py", s["modified"])
            self.assertFalse(s["intact"])

    def test_an_unverifiable_tree_is_a_third_answer(self):
        with tempfile.TemporaryDirectory(prefix="safi-att-") as d:
            s = integrity.get_status(root=Path(d))
            self.assertEqual(s["state"], "unverifiable")
            self.assertFalse(s["intact"])
            self.assertIsNone(s["fingerprint"])


class TheTcbStamp(unittest.TestCase):

    def test_the_stamp_carries_exactly_the_evidence_fields(self):
        stamp = integrity.tcb_stamp()
        self.assertEqual(set(stamp), {"fingerprint", "intact", "state"})
        self.assertTrue(stamp["intact"])

    def test_every_governance_record_is_stamped_at_the_single_writer(self):
        at = DB_SRC.index("def _insert_governance_record")
        body = DB_SRC[at:DB_SRC.index("def ", at + 10)]
        self.assertIn("tcb_stamp", body)
        self.assertIn('record.setdefault("tcb", tcb_stamp())', body)
        self.assertLess(body.index("tcb_stamp()"), body.index("encrypt_value"),
                        "the stamp must be inside the encrypted capture")


class StrictMode(unittest.TestCase):

    INTACT = {"state": "intact", "intact": True, "fingerprint": "f" * 64,
              "expected_fingerprint": "f" * 64, "modified": [], "missing": [], "findings": []}
    TAINTED = {**INTACT, "state": "modified", "intact": False,
               "modified": ["safi_app/core/faculties/will.py"]}
    UNVERIFIABLE = {**INTACT, "state": "unverifiable", "intact": False, "fingerprint": None}

    def _boot(self, status, mode):
        with patch.dict(os.environ, {"SAFI_ENFORCE_INTEGRITY": mode, "SAFI_EXPECTED_FINGERPRINT": ""}):
            return integrity.enforce_at_boot(logging.getLogger("t"), status=status)

    def test_default_mode_boots_tainted_loudly(self):
        s = self._boot(self.TAINTED, "")
        self.assertEqual(s["state"], "modified")

    def test_strict_refuses_a_tainted_tcb(self):
        with self.assertRaises(RuntimeError) as cm:
            self._boot(self.TAINTED, "strict")
        self.assertIn("refusing", str(cm.exception))

    def test_strict_refuses_unverifiable_too(self):
        with self.assertRaises(RuntimeError):
            self._boot(self.UNVERIFIABLE, "strict")

    def test_strict_boots_an_intact_tcb(self):
        s = self._boot(self.INTACT, "strict")
        self.assertTrue(s["intact"])

    def test_create_app_runs_the_boot_check(self):
        self.assertIn("enforce_at_boot(app.logger)", APP_INIT)
        self.assertLess(APP_INIT.index("Config.validate()"),
                        APP_INIT.index("enforce_at_boot"),
                        "config validation first, then attestation")


class FingerprintPin(unittest.TestCase):

    INTACT = StrictMode.INTACT

    def _boot(self, status, mode, pin):
        env = {"SAFI_ENFORCE_INTEGRITY": mode, "SAFI_EXPECTED_FINGERPRINT": pin}
        with patch.dict(os.environ, env):
            return integrity.enforce_at_boot(logging.getLogger("t"), status=status)

    def test_no_pin_changes_nothing(self):
        s = self._boot(self.INTACT, "strict", "")
        self.assertTrue(s["intact"])

    def test_matching_pin_boots(self):
        s = self._boot(self.INTACT, "strict", "f" * 64)
        self.assertTrue(s["intact"])

    def test_mismatched_pin_boots_loudly_in_default_mode(self):
        s = self._boot(self.INTACT, "", "a" * 64)
        self.assertTrue(s["intact"])

    def test_strict_refuses_a_mismatched_pin(self):
        with self.assertRaises(RuntimeError) as cm:
            self._boot(self.INTACT, "strict", "a" * 64)
        self.assertIn("SAFI_EXPECTED_FINGERPRINT", str(cm.exception))

    def test_unverifiable_tree_does_not_count_as_a_pin_match(self):
        with self.assertRaises(RuntimeError):
            self._boot(StrictMode.UNVERIFIABLE, "strict", "a" * 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
