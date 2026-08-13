"""
The Core Loop integrity check (scripts/verify_integrity.py), and the manifest
that must never go stale.

WHY THIS IS IN THE SUITE. The manifest is a hash snapshot, and every legitimate
core change invalidates it. Without enforcement it would go stale on the first
edit after release and every deployment would then fail verification against
code that is genuinely upstream. This suite runs in CI on every push, so
test_the_shipped_tree_verifies_intact is the mechanism that forces
`--update` to be part of any core-touching commit — the check fails HERE first,
not in a customer's deployment.

The tamper tests pin the two verdicts that give the trademark policy (agreement
Section IV) its teeth: a benign edit is MODIFIED-but-invariants-intact (submit
for review), while a model call inside a deterministic faculty is a named
structural finding (the thing the architecture forbids outright).

Run:  docker compose -f docker-compose.test.yml run --rm --build tests -k core_integrity
"""
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
        """THE STALENESS GUARD. If this fails, a Core Loop file was changed
        without regenerating the manifest — run:
            python scripts/verify_integrity.py --update
        and commit the manifest in the same change."""
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
    """Runs against a disposable copy — the real tree is never touched."""

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
        """The Section IV middle ground: hash fails, architecture intact —
        the org must submit for review, but nothing was collapsed."""
        f = self.tmp / "safi_app/core/faculties/conscience.py"
        f.write_text(f.read_text() + "\n# fork-local comment\n")
        code, data = run_json("--root", str(self.tmp))
        self.assertEqual(code, 1)
        self.assertEqual(data["modified"], ["safi_app/core/faculties/conscience.py"])
        self.assertEqual(data["structural_findings"], [],
                         "a comment must not read as an architectural violation")

    def test_a_model_call_in_the_will_is_a_named_finding(self):
        """The violation the agreement exists to prevent — and the check must
        say WHICH commitment broke, not just that bytes differ."""
        f = self.tmp / "safi_app/core/faculties/will.py"
        f.write_text(f.read_text() + "\nimport openai\n")
        code, data = run_json("--root", str(self.tmp))
        self.assertEqual(code, 1)
        self.assertTrue(any("will.py" in x and "model-provider" in x
                            for x in data["structural_findings"]), data["structural_findings"])

    def test_an_llm_provider_call_in_a_deterministic_faculty_is_caught(self):
        """The subtler bypass: no new import, just invoking the reference the
        Will already holds for interface symmetry."""
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
        """A deployment that lost its manifest must get 'cannot verify', which
        is a different answer from 'verified' or 'modified'."""
        (self.tmp / "scripts" / MANIFEST.name).unlink()
        code, _, err = run_check("--root", str(self.tmp))
        self.assertEqual(code, 2)
        self.assertIn("manifest not found", err)


class TheManifestIsWellFormed(unittest.TestCase):

    def test_it_names_the_agreement_and_carries_the_fingerprint(self):
        m = json.loads(MANIFEST.read_text())
        self.assertIn("Governance Agreement", m["comment"])
        self.assertEqual(len(m["root_fingerprint"]), 64)
        # 14 files: orchestrator + 2 mixins + 7 faculty files (the Coach lives
        # inside spirit.py since the 2026-08-13 merge) + database schema +
        # threat_intel + system_prompts.
        self.assertGreaterEqual(len(m["files"]), 14)

    def test_every_deterministic_faculty_is_covered_by_a_hash(self):
        """The invariant checks only diagnose; the hash layer is the verdict.
        A deterministic faculty missing from the manifest would let an edit
        there pass silently as long as it avoided the regexes."""
        m = json.loads(MANIFEST.read_text())["files"]
        for rel in ("safi_app/core/faculties/phase_zero.py",
                    "safi_app/core/faculties/will.py",
                    "safi_app/core/faculties/spirit.py",
                    "safi_app/core/faculties/synderesis.py"):
            self.assertIn(rel, m)

    def test_the_enforcement_content_is_covered_too(self):
        """Decided 2026-08-13 (backlog 34b): the files that FEED the gates are
        Core Loop, not variables. Phase Zero's authority is its signature
        list, and the Conscience's strictness is its audit prompt — a fork
        that guts either must fail verification, not verify INTACT while
        running materially weakened governance. Org customization stays at
        the layer above: per-agent blacklists and worldviews are Section III
        variables; these shipped floors are not."""
        m = json.loads(MANIFEST.read_text())["files"]
        self.assertIn("safi_app/core/threat_intel.py", m)
        self.assertIn("safi_app/core/system_prompts.json", m)


if __name__ == "__main__":
    unittest.main(verbosity=2)
