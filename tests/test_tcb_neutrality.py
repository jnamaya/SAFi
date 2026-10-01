"""Architecture guards for the neutral enforcement/data boundary."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safi_app.core.faculties.synderesis import compile_profile
from safi_app.core import pii_validators
from safi_app.security_policy import PII_CATALOGUE


class NeutralSynderesisTests(unittest.TestCase):
    def test_compiler_uses_only_supplied_data(self):
        rubric = {"description": "Whether the response is accurate.", "scoring_guide": [
            {"score": -1.0, "descriptor": "Incorrect."},
            {"score": 0.0, "descriptor": "Unclear."},
            {"score": 1.0, "descriptor": "Accurate."},
        ]}
        compiled = compile_profile(
            {"key": "example", "name": "Example", "values": [
                {"value": "Accuracy", "weight": 1.0, "rubric": rubric},
            ], "will_rules": {}, "tools": ["lookup"]},
            {"global_worldview": "Use the supplied rules.", "global_values": []},
            tool_catalog={"lookup": ("lookup_one", "lookup_two")},
        )
        self.assertEqual(compiled["allowed_tools"], ["lookup_one", "lookup_two"])
        self.assertEqual(compiled["values"][0]["value"], "Accuracy")

    def test_compiler_does_not_import_catalogs_persistence_or_runtime_configuration(self):
        source = (ROOT / "safi_app/core/faculties/synderesis.py").read_text()
        for forbidden in (
            "from .. import agents", "from ...persistence", "from ...config",
            "import importlib", "import pkgutil", "tool_connectors",
            "SAFI_EXTENSIONS_DIR", "GOVERNANCE_MAP",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class SuppliedSecurityDataTests(unittest.TestCase):
    def test_sensitive_identifier_engine_requires_a_host_catalogue(self):
        prompt = "SSN 123-45-6789"
        self.assertEqual(pii_validators.scan(prompt, ["ssn"]), [])
        self.assertEqual(
            len(pii_validators.scan(prompt, ["ssn"], PII_CATALOGUE)), 1
        )

    def test_sensitive_identifier_patterns_live_outside_the_engine(self):
        source = (ROOT / "safi_app/core/pii_validators.py").read_text()
        self.assertNotIn(r"\d{3})-(\d{2})", source)
        self.assertNotIn("US Social Security number", source)

    def test_security_catalogue_is_json_serializable_profile_data(self):
        json.dumps(PII_CATALOGUE)

    def test_request_pipeline_uses_injected_adapters(self):
        orchestrator = (ROOT / "safi_app/core/orchestrator.py").read_text()
        intellect = (ROOT / "safi_app/core/faculties/intellect.py").read_text()
        for forbidden in (
            "from ..persistence", "from .services", "from openai", "from google",
            "db.", "BackgroundTasksMixin", "from .orchestrator_mixins",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, orchestrator)
        self.assertNotIn("from ...persistence", intellect)
        self.assertNotIn("from ..services.retriever", intellect)

    def test_agent_and_plugin_content_do_not_import_tcb_implementation(self):
        agent_files = (ROOT / "safi_app/core/agents").glob("*.py")
        plugin_files = (ROOT / "safi_app/core/plugins").glob("*.py")
        for path in list(agent_files) + list(plugin_files):
            if path.name == "registry.py":
                continue
            source = path.read_text()
            with self.subTest(path=path.name):
                self.assertNotIn("faculties.synderesis", source)
                self.assertNotIn("from .registry import register_plugin", source)


class TcbBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        checker = {}
        exec(compile((ROOT / "scripts/verify_integrity.py").read_text(),
                     "verify_integrity.py", "exec"), checker)
        cls.core_files = set(checker["CORE_FILES"])

    def test_non_governance_features_are_not_in_the_tcb(self):
        self.assertNotIn("safi_app/core/orchestrator_mixins/tasks.py", self.core_files)
        self.assertNotIn("safi_app/core/orchestrator_mixins/tts.py", self.core_files)

    def test_locally_executed_enforcement_dependencies_are_attested(self):
        self.assertIn("safi_app/core/pii_validators.py", self.core_files)
        self.assertIn("safi_app/persistence/crypto.py", self.core_files)

    def test_profile_and_seed_content_live_outside_the_tcb(self):
        self.assertNotIn("safi_app/profile_resolver.py", self.core_files)
        self.assertNotIn("safi_app/role_config.py", self.core_files)
        self.assertIn("safi_app/security_policy.py", self.core_files)
        self.assertNotIn("safi_app/core/threat_intel.py", self.core_files)
        database = (ROOT / "safi_app/persistence/database.py").read_text()
        for content_import in (
            "DEMO_AGENT_POLICIES", "SAFI_DEFAULT_POLICY", "_seed_local_admin",
            "_ensure_demo_agent_policies_exist", "security_incidents",
        ):
            with self.subTest(content_import=content_import):
                self.assertNotIn(content_import, database)

    def test_global_security_rules_are_supplied_data(self):
        phase_zero = (ROOT / "safi_app/core/faculties/phase_zero.py").read_text()
        self.assertNotIn("from ..threat_intel import", phase_zero)
        self.assertIn("threat_rules", phase_zero)

    def test_role_names_and_rankings_are_not_embedded_in_core(self):
        rbac = (ROOT / "safi_app/core/rbac.py").read_text()
        database = (ROOT / "safi_app/persistence/database.py").read_text()
        self.assertNotIn("ROLES =", rbac)
        self.assertNotIn("ENUM('admin'", database)
        self.assertNotIn("role IN ('admin'", database)

    def test_neutral_faculty_files_have_no_agent_specific_examples(self):
        sources = {
            "safi_app/core/faculties/conscience.py": ("Bible", "Scripture", "Tesla", "fiduciary"),
            "safi_app/core/faculties/will.py": ("get_stock_price", "not a doctor", "Yahoo Finance"),
            "safi_app/core/orchestrator.py": ("get_stock_price", "Tesla", "SharePoint", "Slack"),
            "safi_app/core/system_prompts.json": ("49ers", "Comcast", "Yahoo Finance", "Papias"),
        }
        for filename, forbidden_terms in sources.items():
            source = (ROOT / filename).read_text()
            for term in forbidden_terms:
                with self.subTest(filename=filename, term=term):
                    self.assertNotIn(term, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
