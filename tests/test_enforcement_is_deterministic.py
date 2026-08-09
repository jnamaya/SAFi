"""
The load-bearing invariant: enforcement is deterministic, discernment is not.

WHY. SAFi's entire claim is that the model is a component it governs, not the
thing it is. That holds only while the enforcing faculties decide nothing by
judgement:

  * Enforcement — every block, approval, redirect, retry and threshold decision
    — is a fixed rule evaluated in Python. Phase Zero, Will, Spirit, Synderesis.
  * Discernment — meaning, semantics, "is this actually harmful" — belongs to
    the Intellect and the Conscience, the only two faculties that may call a
    model.

The line is NOT "the Will is independent of the models". Two of its passes
consume the Conscience's ledger, which is correct and intended. The line is:

    The Will may CONSUME the output of discernment. It must never PRODUCE it.

Given the ledger, the Will is a pure function. That is what makes "anyone
holding the audit record can recompute the outcome" true, and it is the only
determinism claim this repo makes (DEVELOPER_GUIDE.md §5).

This guards it mechanically because the prose version lives in CLAUDE.md, which
is gitignored — it binds this working copy and nothing else. A source-level test
is tracked, runs in CI, and survives a fresh clone.

Two specific regressions this exists to stop, both real:

  * Reviving the LLM-judged Will. `system_prompts.json` still carries a
    "will_gate" prompt and `llm_provider.run_will` still exists; both are dead
    and must stay dead. Reintroducing that call was proposed on 2026-08-09 and
    rejected — it would put non-determinism back into the one component whose
    value is that it has none.
  * A deterministic check quietly migrating into a rubric because it was easier
    to express there, which moves it from the Will's tier to the Conscience's.

Run:  venv/bin/python tests/test_enforcement_is_deterministic.py
"""
import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO = Path(__file__).resolve().parent.parent
FACULTIES = REPO / "safi_app" / "core" / "faculties"

# Faculties that must reach a decision without ever consulting a model.
DETERMINISTIC = ["phase_zero.py", "will.py", "spirit.py", "synderesis.py"]

# The only two allowed to call one.
DISCERNMENT = ["intellect.py", "conscience.py"]

# Provider SDKs and the internal dispatch helper. A deterministic faculty that
# imports any of these has already crossed the line, whatever it does with them.
PROVIDER_IMPORTS = {"openai", "anthropic", "google", "groq", "mistralai", "cohere"}
DISPATCH_CALLS = ("_chat_completion", "run_conscience", "run_intellect", "run_will")


def source(name):
    return (FACULTIES / name).read_text(encoding="utf-8")


def code_only(text):
    """Strip comments and docstrings so prose explaining a removed call — which
    is useful history — cannot fail the guard."""
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body.pop(0)
    return ast.unparse(tree)


class DeterministicFacultiesCallNoModel(unittest.TestCase):

    def test_01_no_provider_sdk_imports(self):
        for name in DETERMINISTIC:
            with self.subTest(faculty=name):
                tree = ast.parse(source(name))
                for node in ast.walk(tree):
                    roots = []
                    if isinstance(node, ast.Import):
                        roots = [a.name.split(".")[0] for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                        roots = [node.module.split(".")[0]]
                    for root in roots:
                        self.assertNotIn(
                            root, PROVIDER_IMPORTS,
                            f"{name} imports '{root}'. Enforcement faculties decide by rule, "
                            "not by model — move anything needing judgement to the "
                            "Intellect or the Conscience.",
                        )

    def test_02_no_dispatch_calls(self):
        for name in DETERMINISTIC:
            with self.subTest(faculty=name):
                code = code_only(source(name))
                for call in DISPATCH_CALLS:
                    self.assertNotIn(
                        call, code,
                        f"{name} calls {call}(). The Will may CONSUME the ledger; "
                        "it must never PRODUCE a judgement.",
                    )

    def test_03_will_never_uses_its_llm_provider_handle(self):
        """WillGate keeps an llm_provider for interface symmetry with the other
        faculties. Storing it is fine; using it is the violation."""
        code = code_only(source("will.py"))
        uses = re.findall(r"self\.llm_provider\s*\.", code)
        self.assertEqual(
            uses, [],
            "will.py dereferences self.llm_provider. It is retained only so the "
            "constructor matches the other faculties, and must stay unused.",
        )

    def test_04_deterministic_faculties_await_nothing(self):
        """An await in this tier means an I/O boundary, which in this codebase
        means a model call. WillGate.evaluate_tool_intent is `async def` for the
        caller's convenience and awaits nothing — that must stay true."""
        for name in DETERMINISTIC:
            with self.subTest(faculty=name):
                tree = ast.parse(source(name))
                awaits = [n for n in ast.walk(tree) if isinstance(n, ast.Await)]
                self.assertEqual(
                    awaits, [],
                    f"{name} contains an await. Enforcement runs to completion "
                    "in-process with no external dependency.",
                )

    def test_05_the_llm_will_stays_dead(self):
        """`run_will` and the "will_gate" prompt are vestigial. Wiring either back
        in is the exact regression this file exists to catch."""
        hits = []
        for path in (REPO / "safi_app").rglob("*.py"):
            if "__pycache__" in str(path) or path.name == "llm_provider.py":
                continue
            if re.search(r"\brun_will\s*\(", path.read_text(encoding="utf-8")):
                hits.append(str(path.relative_to(REPO)))
        self.assertEqual(
            hits, [],
            f"run_will() is called from {hits}. An LLM-judged Will was considered "
            "and rejected on 2026-08-09: it reintroduces non-determinism into the "
            "one component whose value is that it has none.",
        )


class DiscernmentFacultiesAreTheOnlyOnesThatThink(unittest.TestCase):
    """The other half of the invariant — stated positively so the split is
    documented by the test suite rather than only by prohibition."""

    def test_intellect_and_conscience_do_dispatch(self):
        found = False
        for name in DISCERNMENT:
            code = code_only(source(name))
            if any(call in code for call in DISPATCH_CALLS):
                found = True
        self.assertTrue(
            found,
            "Neither the Intellect nor the Conscience dispatches to a model. "
            "Either the dispatch moved somewhere it does not belong, or the "
            "call names in DISPATCH_CALLS drifted and this file now guards nothing.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
