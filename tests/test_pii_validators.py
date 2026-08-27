"""The PII detectors: they must catch real identifiers and, more importantly,
must not fire on things that merely look like them.

GOVERNANCE_BACKLOG 83. False positives are the design constraint here. A
detector that blocks a support ticket because it contains a 16-digit order
number produces a refusal the user cannot explain, which is worse than a miss.
So roughly half of these tests assert that nothing fires.

No model is involved in any of this, and no test here needs a database.

Run:  python tests/test_pii_validators.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core import pii_validators as pv  # noqa: E402

ALL = list(pv.VALIDATOR_KEYS)


class NothingIsEnabledByDefault(unittest.TestCase):
    """The product decision (Nelson, 2026-08-26): SAFi blocks nothing until an
    admin ticks a box. These pin that an empty or absent config is inert."""

    def test_no_config_finds_nothing(self):
        text = "SSN 123-45-6789 card 4111111111111111"
        self.assertEqual(pv.scan(text, None), [])
        self.assertEqual(pv.scan(text, []), [])

    def test_no_config_redacts_nothing(self):
        text = "SSN 123-45-6789"
        self.assertEqual(pv.redact(text, None), text)
        self.assertEqual(pv.redact(text, []), text)


class OnlyKnownValidatorKeys(unittest.TestCase):
    """The settings surface is a fixed menu. Anything else is a bug or an
    attempt to smuggle a pattern in, and must not silently become a rule."""

    def test_unknown_keys_are_dropped(self):
        self.assertEqual(pv.normalize(["ssn", "not_a_validator", r"\d+"]), ["ssn"])

    def test_an_unknown_key_cannot_disable_a_valid_one(self):
        findings = pv.scan("123-45-6789", ["ssn", "bogus"])
        self.assertEqual(len(findings), 1)

    def test_normalize_is_order_stable(self):
        self.assertEqual(pv.normalize(["aba", "ssn"]), pv.normalize(["ssn", "aba"]))


class CreditCards(unittest.TestCase):

    def test_valid_test_numbers_are_caught(self):
        for pan in ("4111111111111111", "5500005555555559", "378282246310005"):
            with self.subTest(pan=pan):
                self.assertEqual(len(pv.scan(pan, ["credit_card"])), 1)

    def test_separators_do_not_hide_it(self):
        self.assertEqual(len(pv.scan("4111 1111 1111 1111", ["credit_card"])), 1)
        self.assertEqual(len(pv.scan("4111-1111-1111-1111", ["credit_card"])), 1)

    def test_one_digit_off_does_not_fire(self):
        """The whole point of a checksum. 4111111111111112 fails Luhn."""
        self.assertEqual(pv.scan("4111111111111112", ["credit_card"]), [])

    def test_a_long_number_that_fails_luhn_is_ignored(self):
        self.assertEqual(pv.scan("Order 1234567890123456", ["credit_card"]), [])


class IBANs(unittest.TestCase):

    def test_a_valid_iban_is_caught(self):
        self.assertEqual(len(pv.scan("GB82WEST12345698765432", ["iban"])), 1)

    def test_a_corrupted_iban_is_not(self):
        self.assertEqual(pv.scan("GB82WEST12345698765433", ["iban"]), [])


class RoutingNumbers(unittest.TestCase):

    def test_a_valid_routing_number_is_caught(self):
        self.assertEqual(len(pv.scan("021000021", ["aba"])), 1)

    def test_a_bad_checksum_is_not(self):
        self.assertEqual(pv.scan("021000022", ["aba"]), [])


class SocialSecurityNumbers(unittest.TestCase):
    """No checksum exists, so this detector is structure plus the SSA
    allocation rules, and deliberately narrow."""

    def test_a_well_formed_ssn_is_caught(self):
        self.assertEqual(len(pv.scan("123-45-6789", ["ssn"])), 1)

    def test_a_bare_nine_digit_run_is_NOT_matched(self):
        """Deliberate. Unformatted 9-digit strings collide with order numbers,
        part numbers and phone digits; a refusal the user cannot explain is
        worse than a miss. Documented in the module docstring."""
        self.assertEqual(pv.scan("123456789", ["ssn"]), [])

    def test_the_SSA_invalid_ranges_do_not_fire(self):
        for bad in ("000-45-6789",     # area 000
                    "666-45-6789",     # area 666
                    "900-45-6789",     # area 9xx
                    "123-00-6789",     # group 00
                    "123-45-0000"):    # serial 0000
            with self.subTest(value=bad):
                self.assertEqual(pv.scan(bad, ["ssn"]), [],
                                 "%s is not an issuable SSN and must not fire" % bad)


class Redaction(unittest.TestCase):
    """Redaction, not masking. A governance record is retained for years and a
    partial identifier is still an identifier."""

    def test_the_value_is_replaced_entirely(self):
        out = pv.redact("my ssn is 123-45-6789 ok", ["ssn"])
        self.assertNotIn("123-45-6789", out)
        self.assertNotIn("6789", out, "no trailing digits may survive")
        self.assertIn("[REDACTED:ssn]", out)

    def test_the_reason_survives_the_value(self):
        """An examiner needs to know WHY the turn was blocked; the key stays."""
        self.assertIn("ssn", pv.redact("123-45-6789", ["ssn"]))

    def test_surrounding_text_is_untouched(self):
        out = pv.redact("before 123-45-6789 after", ["ssn"])
        self.assertTrue(out.startswith("before "))
        self.assertTrue(out.endswith(" after"))

    def test_several_hits_in_one_string(self):
        out = pv.redact("a 123-45-6789 b 4111111111111111 c", ["ssn", "credit_card"])
        self.assertNotIn("123-45-6789", out)
        self.assertNotIn("4111111111111111", out)
        self.assertEqual(out.count("[REDACTED:"), 2)

    def test_redacting_with_nothing_enabled_is_a_no_op(self):
        text = "123-45-6789"
        self.assertEqual(pv.redact(text, []), text)


class OrdinaryTextIsLeftAlone(unittest.TestCase):
    """The cost of a false positive is a blocked turn the user cannot explain,
    so this is the class that matters most in daily use."""

    SAMPLES = [
        "Please review the Q3 budget by 2026-08-26.",
        "Call me on 555-123-4567 or ext 4821.",
        "Invoice 8841-22, PO 44120099, tracking 1Z999AA10123456784.",
        "The meeting is 09-15-2026 at 14:30.",
        "Version 1.2.3 shipped, build 20260826.",
    ]

    def test_no_detector_fires_on_ordinary_business_text(self):
        for s in self.SAMPLES:
            with self.subTest(text=s):
                self.assertEqual(pv.scan(s, ALL), [], "false positive on: %s" % s)


class TheAuditReason(unittest.TestCase):

    def test_summary_names_types_and_counts_never_values(self):
        findings = pv.scan("123-45-6789 and 987-65-4320", ["ssn"])
        summary = pv.summarize(findings)
        self.assertIn("Social Security", summary)
        self.assertNotIn("123-45-6789", summary, "the reason must not carry the value")
        self.assertNotIn("6789", summary)

    def test_empty_findings_give_an_empty_reason(self):
        self.assertEqual(pv.summarize([]), "")


class TheCatalogueDrivesTheUI(unittest.TestCase):

    def test_every_key_has_a_label_and_an_honest_note(self):
        entries = pv.catalogue()
        self.assertEqual(len(entries), len(pv.VALIDATOR_KEYS))
        for e in entries:
            with self.subTest(key=e["key"]):
                self.assertTrue(e["label"])
                self.assertTrue(e["note"], "each detector states its precision")

    def test_the_loosest_detector_says_so(self):
        """aba is ~1 in 10 on random 9-digit runs. An admin ticking it should
        be able to see that from the UI, not discover it in production."""
        aba = next(e for e in pv.catalogue() if e["key"] == "aba")
        self.assertIn("1 in 10", aba["note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
