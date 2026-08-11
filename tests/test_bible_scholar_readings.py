"""
The Bible Scholar's readings plugin: which prompts fire it, which reading they
select, and which day they ask about.

WHY. Trigger detection and reading selection were one tangled block, and the two
questions are not the same. `individual_reading_commands` fired the plugin for
`today's reading`, `daily reading`, `mass reading` and `reading for today`, then
the selection ladder only knew `first reading` / `second reading` / `gospel`, so
those four fetched the day and reported:

    I found the readings for today, but couldn't find a specific 'None'.

Four of the nine documented phrases — the four a person is most likely to type.
Selecting nothing now means "all of them", which is also what makes a weekday
solemnity correct: the Second Reading appears because the day HAS one, not
because the caller guessed the weekday.

The Responsorial Psalm was a third bug in the same block: parsed by
`_READING_LABELS`, mapped by the RSS parser, and unreachable from any prompt.

Run:  venv/bin/python tests/test_bible_scholar_readings.py
"""
import asyncio
import logging
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from safi_app.core.plugins import bible_scholar_readings as R  # noqa: E402

LOG = logging.getLogger("test_readings")
LOG.addHandler(logging.NullHandler())

# A weekday: First Reading, Psalm, Gospel — no Second Reading.
WEEKDAY = {
    "date": "Wednesday August 12, 2026",
    "full_passages": [
        {"title": "First Reading", "citation": "Ezekiel 9:1-7", "text": ""},
        {"title": "Responsorial Psalm", "citation": "Psalm 113:1-6", "text": ""},
        {"title": "Gospel", "citation": "Matthew 18:15-20", "text": ""},
    ],
}
# A Sunday or a solemnity: all four.
SUNDAY = {
    "date": "Sunday August 16, 2026",
    "full_passages": [
        {"title": "First Reading", "citation": "Jeremiah 38:4-6", "text": ""},
        {"title": "Responsorial Psalm", "citation": "Psalm 40:2-4", "text": ""},
        {"title": "Second Reading", "citation": "Hebrews 12:1-4", "text": ""},
        {"title": "Gospel", "citation": "Luke 12:49-53", "text": ""},
    ],
}

PROFILE = "the_bible_scholar"


def run(prompt, source=WEEKDAY, profile=PROFILE):
    """
    Drive the handler with the network stubbed out. Returns the payload, and
    records the date the handler asked for on `run.last_date`.

    The side effect is a PLAIN function on purpose: `_fetch_readings_from_source`
    is an `async def`, so `patch.object` installs an AsyncMock, which awaits the
    side effect's return value for you. An async side effect here hands back an
    unawaited coroutine and the handler fails on `"error" in scraped_data`.
    """
    run.last_date = None

    def _record(log, target_date=None):
        run.last_date = target_date
        return source

    async def _go():
        with patch.object(R, "_fetch_readings_from_source", side_effect=_record):
            _, payload = await R.handle_bible_scholar_commands(prompt, profile, LOG)
            return payload
    return asyncio.run(_go())


class TriggeringIsSeparateFromSelecting(unittest.TestCase):

    def test_a_non_readings_prompt_does_not_fire_at_all(self):
        """The plugin must stay out of ordinary conversation — firing would
        override the RAG query with today's citation and answer a general
        question with today's liturgy."""
        for prompt in ("which psalm is about trust?",
                       "tell me about the gospel of Mark",
                       "what does Amos teach?",
                       "who wrote Hebrews?"):
            with self.subTest(prompt=prompt):
                self.assertIsNone(run(prompt))

    def test_the_plugin_only_runs_for_its_own_profile(self):
        self.assertIsNone(run("first reading", profile="the_fiduciary"))

    def test_every_documented_phrase_produces_a_usable_payload(self):
        """The regression this file exists for: no phrase may come back as an
        error mentioning None."""
        for prompt in ("first reading", "second reading", "gospel reading",
                       "today's gospel", "today's reading", "daily reading",
                       "mass reading", "reading for today", "gospel for today",
                       "today's readings", "all the readings"):
            with self.subTest(prompt=prompt):
                payload = run(prompt, source=SUNDAY)
                self.assertIsNotNone(payload, "phrase no longer triggers")
                self.assertNotIn("None", str(payload.get("plugin_error", "")))
                self.assertIn("rag_query_override", payload)


class SelectingNothingMeansEverything(unittest.TestCase):

    def test_unqualified_phrases_return_every_reading(self):
        for prompt in ("today's reading", "daily reading", "mass reading",
                       "reading for today", "today's readings"):
            with self.subTest(prompt=prompt):
                payload = run(prompt, source=SUNDAY)
                self.assertEqual(payload["rag_query_override"],
                                 ["Jeremiah 38:4-6", "Psalm 40:2-4",
                                  "Hebrews 12:1-4", "Luke 12:49-53"])

    def test_the_manifest_names_each_reading_for_the_model(self):
        ctx = run("today's readings", source=SUNDAY)["preformatted_context_string"]
        for fragment in ("First Reading — Jeremiah 38:4-6",
                         "Responsorial Psalm — Psalm 40:2-4",
                         "Second Reading — Hebrews 12:1-4",
                         "Gospel — Luke 12:49-53"):
            self.assertIn(fragment, ctx)

    def test_a_weekday_digest_has_no_second_reading_and_says_so_by_omission(self):
        """Driven by what the source lists, not by the weekday — which is what
        makes a weekday solemnity come out right without a calendar."""
        payload = run("today's readings", source=WEEKDAY)
        self.assertEqual(len(payload["rag_query_override"]), 3)
        self.assertNotIn("Second Reading", payload["preformatted_context_string"])

    def test_a_solemnity_on_a_weekday_keeps_its_second_reading(self):
        payload = run("today's readings", source=SUNDAY)
        self.assertIn("Hebrews 12:1-4", payload["rag_query_override"])


class SingleReadingSelection(unittest.TestCase):

    def test_each_selector_picks_its_own_reading(self):
        cases = [
            ("first reading", "Ezekiel 9:1-7"),
            ("gospel reading", "Matthew 18:15-20"),
            ("today's gospel", "Matthew 18:15-20"),
            ("responsorial psalm", "Psalm 113:1-6"),
            ("today's psalm", "Psalm 113:1-6"),
        ]
        for prompt, citation in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(run(prompt)["rag_query_override"], citation)

    def test_the_psalm_is_reachable(self):
        """It was parsed and mapped, and no prompt could ask for it."""
        self.assertEqual(run("responsorial psalm")["rag_query_override"],
                         "Psalm 113:1-6")

    def test_a_single_reading_override_stays_a_string(self):
        """Only the all-readings branch returns a list; the Intellect branches on
        the type, so a one-element list here would change the retrieval path."""
        self.assertIsInstance(run("first reading")["rag_query_override"], str)

    def test_asking_for_a_reading_the_day_lacks_is_answered_liturgically(self):
        """A weekday has no Second Reading. That is a fact about the day, not a
        lookup failure, so the payload names what the day does have."""
        payload = run("second reading", source=WEEKDAY)
        err = payload["plugin_error"]
        self.assertIn("no Second Reading", err)
        self.assertIn("First Reading", err)
        self.assertIn("Gospel", err)
        self.assertNotIn("None", err)


class DateRequests(unittest.TestCase):

    def test_no_cue_means_today(self):
        run("today's readings")
        self.assertIsNone(run.last_date)

    def test_iso_dates_pass_straight_through(self):
        """The form a scheduled caller uses, because it needs no interpreting."""
        run("the readings for 2026-08-15")
        self.assertEqual(run.last_date, date(2026, 8, 15))

    def test_an_impossible_iso_date_does_not_crash(self):
        run("the readings for 2026-13-45")
        self.assertIsNone(run.last_date)

    def test_relative_and_weekday_cues(self):
        today = date(2026, 8, 12)  # a Wednesday
        self.assertEqual(R._requested_date("readings for tomorrow", today), date(2026, 8, 13))
        self.assertEqual(R._requested_date("yesterday's readings", today), date(2026, 8, 11))
        self.assertEqual(R._requested_date("sunday's readings", today), date(2026, 8, 16))
        self.assertIsNone(R._requested_date("today's readings", today))

    def test_a_weekday_cue_naming_today_resolves_to_today(self):
        today = date(2026, 8, 12)  # Wednesday
        self.assertEqual(R._requested_date("wednesday readings", today), today)

    def test_a_dated_request_is_refused_rather_than_answered_with_today(self):
        """The fallback source serves one page — always today's. Returning it
        under another day's heading is undetectable to the caller, so a dated
        request that USCCB cannot satisfy fails instead."""
        async def _go():
            with patch.object(R, "_fetch_usccb_rss", return_value=None):
                return await R._fetch_readings_from_source(LOG, target_date=date(2099, 1, 1))
        out = asyncio.run(_go())
        self.assertIn("error", out)
        self.assertIn("2099", out["error"])

    def test_an_undated_request_still_uses_the_fallback(self):
        async def _go():
            with patch.object(R, "_fetch_usccb_rss", return_value=None), \
                 patch.object(R, "_fetch_livingwithchrist", return_value=WEEKDAY) as fb:
                out = await R._fetch_readings_from_source(LOG)
                return out, fb.called
        out, called = asyncio.run(_go())
        self.assertTrue(called, "the fallback source must still be reachable")
        self.assertEqual(out, WEEKDAY)


class EmptyAndBrokenSources(unittest.TestCase):

    def test_a_source_error_is_passed_through(self):
        payload = run("today's readings", source={"error": "the source timed out"})
        self.assertEqual(payload["plugin_error"], "the source timed out")

    def test_a_source_with_no_readings_is_not_reported_as_a_digest(self):
        payload = run("today's readings", source={"date": "Monday", "full_passages": []})
        self.assertIn("plugin_error", payload)
        self.assertNotIn("rag_query_override", payload)

    def test_passages_without_a_citation_are_dropped(self):
        source = {"date": "Monday", "full_passages": [
            {"title": "First Reading", "citation": "", "text": ""},
            {"title": "Gospel", "citation": "Mark 1:1-8", "text": ""},
        ]}
        self.assertEqual(run("today's readings", source=source)["rag_query_override"],
                         ["Mark 1:1-8"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
