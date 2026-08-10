"""
An attached document must be traceable, and a truncated one must be announced.

WHY. Uploading a file to a conversation extracts its text into the prompt and
then discards the file. That is the right call — the extracted text is already
encrypted into chat_history and the audit trail, and keeping the original would
put a second copy of the same sensitive data somewhere needing its own purge,
legal-hold and export coverage.

But two things were missing from it.

**Provenance.** Nothing recorded that a file existed: no digest, no size. "The
agent misread my contract" had no answer, because there was no way to show the
analysed text came from the document that was uploaded.

**Truncation was silent.** `chat.js` announced it with
`ui.showToast(..., 'info')`, and `ui.js` returns early on `'info'` — so a
document over MAX_DOCUMENT_CHARS was cut, the agent answered on part of it, and
nobody was told. The audit record was honest about what the agent saw; the user
was not.

Run:  venv/bin/python tests/test_attachment_provenance.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
DOCS_API = (ROOT / "safi_app" / "api" / "documents.py").read_text(encoding="utf-8")
CHAT = (ROOT / "public" / "js" / "core" / "chat.js").read_text(encoding="utf-8")
UI = (ROOT / "public" / "js" / "ui" / "ui.js").read_text(encoding="utf-8")


class TheFileIsDigestedNotStored(unittest.TestCase):

    def test_the_endpoint_returns_a_sha256(self):
        self.assertIn("hashlib.sha256(file.read()).hexdigest()", DOCS_API)
        self.assertIn('"sha256": digest', DOCS_API)

    def test_the_stream_is_rewound_around_hashing(self):
        """extract_text consumes the stream. Hashing without rewinding either
        yields the digest of nothing or leaves extraction with an empty file."""
        before = DOCS_API.index("hashlib.sha256")
        self.assertIn("file.seek(0)", DOCS_API[:before])
        self.assertIn("file.seek(0)", DOCS_API[before:before + 200])

    def test_the_bytes_are_never_persisted(self):
        """The design decision, pinned: a digest, not a copy."""
        for forbidden in ("file.save(", "save_uploaded", "INSERT INTO attachments"):
            self.assertNotIn(forbidden, DOCS_API,
                             "chat attachments must not be stored; the digest is the record")


def _truncation_branch():
    """The `if (extracted.was_truncated)` block, comments stripped.

    Stripping matters: the block explains WHY it must not use the suppressed
    toast type, so a naive search for 'info' matches the explanation and fails
    on correct code."""
    start = CHAT.index("if (extracted.was_truncated) {")
    seg = CHAT[start:start + 1400]
    return "\n".join(l.split("//", 1)[0] for l in seg.splitlines())


class TruncationIsAnnounced(unittest.TestCase):

    def test_the_notice_is_not_a_suppressed_toast_type(self):
        self.assertIn("if (type === 'info') return;", UI,
                      "if info toasts stop being suppressed, this guard can relax")
        code = _truncation_branch()
        self.assertNotIn("'info'", code,
                         "the truncation notice must not use the suppressed toast type")
        self.assertIn("'warning'", code)

    def test_the_notice_says_how_much_was_lost(self):
        """"Truncated to fit context window" does not tell anyone whether they
        lost a paragraph or two hundred pages."""
        code = _truncation_branch()
        self.assertIn("chars_used", code)
        self.assertIn("total_chars", code)

    def test_the_agent_is_told_too(self):
        """The user knowing is not enough: an agent asked about page 400 of a
        truncated document should say it cannot see it, rather than answering
        from the part it happened to get."""
        self.assertIn("This document was truncated", CHAT)


class TheRecordCarriesTheProvenance(unittest.TestCase):

    def test_the_digest_travels_with_the_analysed_text(self):
        """Inside the prompt on purpose: the prompt is encrypted into
        chat_history and the audit trail, so the digest lands wherever the text
        lands, with no second store to purge, hold or export."""
        self.assertIn("[PROVENANCE:", CHAT)
        self.assertIn("sha256 ${extracted.sha256", CHAT)

    def test_an_attachment_leaves_org_level_evidence(self):
        self.assertIn("'chat_document_attached'", DOCS_API)
        self.assertIn('"sha256": digest', DOCS_API)

    def test_logging_failure_cannot_cost_the_user_their_upload(self):
        after = DOCS_API[DOCS_API.index("'chat_document_attached'"):]
        self.assertIn("except Exception", after[:700])


if __name__ == "__main__":
    unittest.main(verbosity=2)
