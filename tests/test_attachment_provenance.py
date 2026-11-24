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
        before = DOCS_API.index("hashlib.sha256")
        self.assertIn("file.seek(0)", DOCS_API[:before])
        self.assertIn("file.seek(0)", DOCS_API[before:before + 200])

    def test_the_bytes_are_never_persisted(self):
        for forbidden in ("file.save(", "save_uploaded", "INSERT INTO attachments"):
            self.assertNotIn(forbidden, DOCS_API,
                             "chat attachments must not be stored; the digest is the record")


def _truncation_branch():
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
        code = _truncation_branch()
        self.assertIn("chars_used", code)
        self.assertIn("total_chars", code)

    def test_the_agent_is_told_too(self):
        self.assertIn("This document was truncated", CHAT)


class TheRecordCarriesTheProvenance(unittest.TestCase):

    def test_the_digest_travels_with_the_analysed_text(self):
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
