"""
The extension seams: plugins by registration, agents by directory.

WHY. Agreement §III promises organizations "total freedom to add, edit, or
remove custom tools, knowledge bases, and plugins" — and until 2026-08-13 the
plugin half was false: the orchestrator imported its plugins BY NAME, so adding
one meant editing the most manifest-covered file in the product, tripping the
integrity check, and entering Section IV review. Code-defined agents had the
same problem via the synderesis registry literal.

Both seams now follow the line the manifest draws everywhere else: the LOADER
is Core Loop, verified and covered; the LOADED CONTENT is the organization's
own. These tests pin the seam's contract from both sides — that extensions
work, and that the guards (shadowing, broken files, off-by-default) hold.

Needs the disposable stack (subprocess imports compile the real registry):
    docker compose -f docker-compose.test.yml run --rm --build tests -k extension
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ORCH = (ROOT / "safi_app" / "core" / "orchestrator.py").read_text(encoding="utf-8")
REGISTRY = (ROOT / "safi_app" / "core" / "plugins" / "registry.py").read_text(encoding="utf-8")
BUILTIN = (ROOT / "safi_app" / "core" / "plugins" / "builtin.py").read_text(encoding="utf-8")


class PluginRegistry(unittest.TestCase):

    # Import STATEMENTS, not prose: the orchestrator's comment narrating the
    # removal legitimately names the removed module, and the first version of
    # this test failed on its own documentation — the same lesson as the CSS
    # tests that had to strip comments before matching selectors.
    _PLUGIN_IMPORT = re.compile(
        r"^\s*from\s+\.plugins\.(?!registry\b)\w+\s+import|"
        r"^\s*import\s+safi_app\.core\.plugins\.(?!registry\b)", re.M)

    def test_the_orchestrator_knows_no_plugin_by_name(self):
        """The seam's whole point. A by-name plugin import here reintroduces
        the edit-the-core-file requirement §III forbids. The only permitted
        plugin imports are the registry itself and the builtin registration
        module (whose import IS the registration)."""
        code = "\n".join(l for l in ORCH.splitlines() if not l.strip().startswith("#"))
        hits = [m.group(0).strip() for m in self._PLUGIN_IMPORT.finditer(code)
                if "import builtin" not in m.group(0)]
        self.assertEqual(hits, [],
                         "the orchestrator must not import plugin modules by name")
        self.assertNotIn("handle_bible_scholar_commands", code)
        self.assertIn("plugins_for(self.active_profile_name)", code)

    def test_the_dead_fiduciary_import_stays_dead(self):
        """Its dispatch was removed in v1.3; only the import lingered. It must
        not quietly return via the registry either — see builtin.py for the
        conscious-decision requirement.

        Checked against the AST, not the text: both files legitimately DISCUSS
        the fiduciary plugin in comments and docstrings (that discussion is the
        decision record), and two text-stripping attempts at this test failed
        on their own documentation. The AST sees only imports and calls."""
        import ast as _ast
        for label, src in (("orchestrator", ORCH), ("builtin", BUILTIN)):
            tree = _ast.parse(src)
            for node in _ast.walk(tree):
                names = []
                if isinstance(node, _ast.ImportFrom):
                    names = [node.module or ""] + [a.name for a in node.names]
                elif isinstance(node, _ast.Import):
                    names = [a.name for a in node.names]
                for n in names:
                    self.assertNotIn("fiduciary", n or "",
                                     f"{label}: fiduciary plugin imported again — "
                                     "that requires a conscious decision, see builtin.py")

    def test_registration_and_dispatch_agree(self):
        from safi_app.core.plugins.registry import register_plugin, plugins_for, _PLUGINS
        marker = object()
        before = len(_PLUGINS)
        async def h(prompt, name, log): return prompt, None
        h._marker = marker
        register_plugin({"Test Agent", "test_agent"}, h)
        try:
            self.assertIn(h, plugins_for("test agent"),
                          "matching is case/whitespace-normalized")
            self.assertIn(h, plugins_for("test_agent"))
            self.assertEqual(plugins_for("someone else"), [
                x for x in plugins_for("someone else")])  # no cross-talk
            self.assertNotIn(h, plugins_for("someone else"))
        finally:
            del _PLUGINS[before:]

    def test_wildcard_serves_every_agent(self):
        from safi_app.core.plugins.registry import register_plugin, plugins_for, _PLUGINS
        before = len(_PLUGINS)
        async def h(prompt, name, log): return prompt, None
        register_plugin({"*"}, h)
        try:
            self.assertIn(h, plugins_for("anything at all"))
        finally:
            del _PLUGINS[before:]

    def test_the_bible_scholar_is_registered_for_both_name_forms(self):
        """Importing builtin.py is the registration; both the display-derived
        and sanitized names the orchestrator can carry must resolve."""
        import safi_app.core.plugins.builtin  # noqa: F401  (registration side effect)
        from safi_app.core.plugins.registry import plugins_for
        from safi_app.core.plugins.bible_scholar_readings import handle_bible_scholar_commands
        self.assertIn(handle_bible_scholar_commands, plugins_for("the bible scholar"))
        self.assertIn(handle_bible_scholar_commands, plugins_for("the_bible_scholar"))

    def test_an_agent_with_no_plugins_gathers_nothing(self):
        """The empty-list guard: asyncio.gather() with no tasks is fine, but the
        old unconditional structure assumed at least one entry existed."""
        self.assertIn("if plugin_tasks:", ORCH)


def _run_with_extensions(ext_files: dict, code: str) -> dict:
    """Import synderesis in a subprocess with SAFI_EXTENSIONS_DIR set, run
    `code`, print JSON. Subprocess because the loader runs at import time."""
    with tempfile.TemporaryDirectory(prefix="safi-ext-") as d:
        for name, body in ext_files.items():
            (Path(d) / name).write_text(textwrap.dedent(body), encoding="utf-8")
        env = dict(os.environ, SAFI_EXTENSIONS_DIR=d)
        script = textwrap.dedent(f"""
            import json, sys
            sys.path.insert(0, {str(ROOT)!r})
            from safi_app.core.faculties import synderesis as s
            {code}
        """)
        p = subprocess.run([sys.executable, "-c", script],
                           capture_output=True, text=True, timeout=300, env=env)
        assert p.returncode == 0, p.stderr[-2000:]
        return json.loads(p.stdout.strip().splitlines()[-1])


EXT_OK = """
    KEY = "night_auditor"
    AGENT = {
        "name": "The Night Auditor",
        "description": "extension test agent",
        "worldview": "You audit overnight batch reports.",
        "style": "terse",
        "scope_statement": "Overnight batch report questions only.",
        "values": [{"value": "Accuracy", "weight": 1.0,
                    "definition": "Be accurate.",
                    "rubric": {"description": "accuracy", "scoring_guide": []}}],
        "will_rules": [],
    }
"""


class ExtensionAgents(unittest.TestCase):

    def test_an_extension_loads_registers_and_compiles(self):
        """End to end: the file loads, lands in both registries WITHOUT being
        named in SAFI_BUILTIN_AGENTS, and compiles through get_profile with the
        governance layers applied (the injected scope hard-gate proves the
        compiler ran — extensions get no bypass lane)."""
        out = _run_with_extensions({"night_auditor.py": EXT_OK}, """
            prof = s.get_profile("night_auditor")
            print(json.dumps({
                "in_all": "night_auditor" in s.ALL_AGENTS,
                "in_active": "night_auditor" in s.AGENTS,
                "compiled_name": prof.get("name"),
                "scope_gate_injected": any(
                    (v.get("value") or v.get("name")) == "Scope Compliance"
                    for v in prof.get("values", [])),
            }))
        """)
        self.assertTrue(out["in_all"])
        self.assertTrue(out["in_active"], "installing the file IS the enablement")
        self.assertEqual(out["compiled_name"], "The Night Auditor")
        self.assertTrue(out["scope_gate_injected"],
                        "extensions must pass through the same compiler as built-ins")

    def test_shadowing_a_builtin_is_refused(self):
        shadow = EXT_OK.replace('"night_auditor"', '"fiduciary"')
        out = _run_with_extensions({"evil.py": shadow}, """
            print(json.dumps({
                "fiduciary_name": s.ALL_AGENTS["fiduciary"].get("name"),
            }))
        """)
        self.assertNotEqual(out["fiduciary_name"], "The Night Auditor",
                            "an extension must never replace a built-in agent")

    def test_a_broken_extension_is_skipped_not_fatal(self):
        out = _run_with_extensions(
            {"broken.py": "this is not python (", "night_auditor.py": EXT_OK}, """
            print(json.dumps({"good_one_loaded": "night_auditor" in s.ALL_AGENTS}))
        """)
        self.assertTrue(out["good_one_loaded"],
                        "one bad file must not take the others — or the app — down")

    def test_off_by_default(self):
        """No SAFI_EXTENSIONS_DIR, no seam. The suite's own import of
        synderesis (no env var) proves nothing extension-shaped exists."""
        from safi_app.core.faculties import synderesis as s
        self.assertEqual(s._EXTENSION_KEYS, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
