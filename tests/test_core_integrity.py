import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "verify_integrity.py"
MANIFEST = ROOT / "scripts" / "core_integrity_manifest.json"


def run_check(*args):
    p = subprocess.run([sys.executable, str(SCRIPT), *args],
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


def run_json(*args):
    code, out, _ = run_check("--json", *args)
    return code, json.loads(out)


class TheShippedTreeIsIntact(unittest.TestCase):

    def test_the_shipped_tree_verifies_intact(self):
        code, data = run_json()
        self.assertEqual(data["modified"], [],
                         "core files changed without a manifest update: "
                         f"{data['modified']} — run scripts/verify_integrity.py --update")
        self.assertEqual(data["missing"], [])
        self.assertEqual(data["structural_findings"], [])
        self.assertTrue(data["intact"])
        self.assertEqual(code, 0)

    def test_the_fingerprints_agree_on_a_clean_tree(self):
        _, data = run_json()
        self.assertEqual(data["root_fingerprint_expected"],
                         data["root_fingerprint_actual"])


class TamperDetection(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="safi-integrity-"))
        (self.tmp / "scripts").mkdir()
        shutil.copytree(ROOT / "safi_app", self.tmp / "safi_app",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(MANIFEST, self.tmp / "scripts" / MANIFEST.name)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_pristine_copy_passes(self):
        code, data = run_json("--root", str(self.tmp))
        self.assertTrue(data["intact"], data)
        self.assertEqual(code, 0)

    def test_a_benign_edit_is_modified_but_invariants_hold(self):
        f = self.tmp / "safi_app/core/faculties/conscience.py"
        f.write_text(f.read_text() + "\n# fork-local comment\n")
        code, data = run_json("--root", str(self.tmp))
        self.assertEqual(code, 1)
        self.assertEqual(data["modified"], ["safi_app/core/faculties/conscience.py"])
        self.assertEqual(data["structural_findings"], [],
                         "a comment must not read as an architectural violation")

    def test_a_model_call_in_the_will_is_a_named_finding(self):
        f = self.tmp / "safi_app/core/faculties/will.py"
        f.write_text(f.read_text() + "\nimport openai\n")
        code, data = run_json("--root", str(self.tmp))
        self.assertEqual(code, 1)
        self.assertTrue(any("will.py" in x and "model-provider" in x
                            for x in data["structural_findings"]), data["structural_findings"])

    def test_an_llm_provider_call_in_a_deterministic_faculty_is_caught(self):
        f = self.tmp / "safi_app/core/faculties/will.py"
        f.write_text(f.read_text()
                     + "\ndef _sneak(self):\n    return self.llm_provider.run_will('x')\n")
        _, data = run_json("--root", str(self.tmp))
        self.assertTrue(any("calls self.llm_provider" in x
                            for x in data["structural_findings"]), data["structural_findings"])

    def test_a_deleted_core_file_is_reported_missing(self):
        (self.tmp / "safi_app/core/faculties/utils.py").unlink()
        code, data = run_json("--root", str(self.tmp))
        self.assertEqual(code, 1)
        self.assertIn("safi_app/core/faculties/utils.py", data["missing"])

    def test_exit_code_2_when_the_manifest_is_absent(self):
        (self.tmp / "scripts" / MANIFEST.name).unlink()
        code, _, err = run_check("--root", str(self.tmp))
        self.assertEqual(code, 2)
        self.assertIn("manifest not found", err)


class TheManifestIsWellFormed(unittest.TestCase):

    def test_it_names_the_agreement_and_carries_the_fingerprint(self):
        m = json.loads(MANIFEST.read_text())
        self.assertIn("Governance Agreement", m["comment"])
        self.assertEqual(len(m["root_fingerprint"]), 64)
        self.assertGreaterEqual(len(m["files"]), 14)

    def test_every_deterministic_faculty_is_covered_by_a_hash(self):
        m = json.loads(MANIFEST.read_text())["files"]
        for rel in ("safi_app/core/faculties/phase_zero.py",
                    "safi_app/core/faculties/will.py",
                    "safi_app/core/faculties/spirit.py",
                    "safi_app/core/faculties/synderesis.py"):
            self.assertIn(rel, m)

    def test_generic_audit_template_and_shipped_security_baseline_are_covered(self):
        m = json.loads(MANIFEST.read_text())["files"]
        self.assertIn("safi_app/core/system_prompts.json", m)
        self.assertIn("safi_app/security_policy.py", m)
        self.assertNotIn("safi_app/core/threat_intel.py", m)

    def test_the_human_side_will_is_covered_and_auth_is_deliberately_not(self):
        m = json.loads(MANIFEST.read_text())["files"]
        self.assertIn("safi_app/core/rbac.py", m)
        self.assertNotIn("safi_app/api/auth.py", m)


if __name__ == "__main__":
    unittest.main(verbosity=2)
