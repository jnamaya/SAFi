"""
Deep links into the composer: `?q=<text>` and `?agent=<key>`.

WHY. The scheduled agent emails (daily readings, morning IT briefing) arrive with
content the reader may want to act on — a prioritized action item, a reading to
follow up. There was no route back: the front end read no query params at all
except the mobile OAuth `token` callback, so a link could only ever land on the
app root.

The load-bearing property here is that a deep link PREFILLS AND STOPS. The text
arrives from outside the app — an email, a notification, anything that can be
forwarded — and auto-sending would commit a governed turn to the reader's
permanent audit record before they had seen the prompt. That is also why the
params are cleared afterwards: a refresh must not re-fire a stale prompt.

Run:  venv/bin/python tests/test_composer_deep_link.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

APP = (ROOT / "public" / "js" / "core" / "app.js").read_text(encoding="utf-8")

FN = APP[APP.index("async function applyDeepLink"):]
FN = FN[:FN.index("\nfunction handleExamplePromptClick")]


class TheLinkPrefillsAndStops(unittest.TestCase):

    def test_it_never_sends(self):
        """The whole safety property. sendMessage in here would commit a turn
        the reader never saw."""
        self.assertNotIn("sendMessage", FN)

    def test_it_prefills_the_composer(self):
        self.assertIn("messageInput.value = q", FN)
        self.assertIn("autoSize()", FN)
        self.assertIn("sendButton.disabled = false", FN)

    def test_it_clears_the_params_afterwards(self):
        """Otherwise a refresh re-applies the prompt, and the text sits in the
        URL bar and in browser history."""
        self.assertIn("history.replaceState", FN)


class AgentSwitching(unittest.TestCase):

    def test_an_unknown_agent_key_is_ignored_rather_than_applied(self):
        self.assertIn("availableProfiles.some", FN)

    def test_switching_only_happens_when_the_agent_differs(self):
        self.assertIn("agentKey !== activeProfileData.key", FN)

    def test_it_returns_after_a_switch_because_a_reload_is_in_flight(self):
        """handleProfileChange reloads; the prefill has to happen on the way
        back, not before the page is replaced."""
        switch = FN[FN.index("await handleProfileChange(agentKey)"):]
        self.assertIn("return", switch[:switch.index("\n  }")])


class ItIsWiredIn(unittest.TestCase):

    def test_it_is_called_during_bootstrap(self):
        self.assertIn("await applyDeepLink()", APP)

    def test_it_runs_after_the_profiles_and_composer_exist(self):
        """It reads availableProfiles and writes to the composer, so calling it
        earlier gets an empty list and a missing element."""
        self.assertLess(APP.index("initComposerMenu({"), APP.index("await applyDeepLink()"))
        self.assertLess(APP.index("availableProfiles = profilesResponse.available"),
                        APP.index("await applyDeepLink()"))

    def test_no_params_is_a_fast_exit(self):
        self.assertIn("if (!q && !agentKey) return", FN)

    def test_both_params_are_read(self):
        self.assertRegex(FN, r"params\.get\(['\"]q['\"]\)")
        self.assertRegex(FN, r"params\.get\(['\"]agent['\"]\)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
