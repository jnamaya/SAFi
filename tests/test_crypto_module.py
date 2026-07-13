"""
Unit tests for safi_app.persistence.crypto (no DB required).

Covers: passthrough mode, enabled round-trips, dual-read of legacy plaintext,
idempotent double-encrypt guard, InvalidToken fallback, and MultiFernet key
rotation (old key still decrypts).

Run:  venv/bin/python tests/test_crypto_module.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.fernet import Fernet

from safi_app.config import Config
from safi_app.persistence import crypto


class CryptoTestBase(unittest.TestCase):
    def setUp(self):
        self._saved_key = Config.ENCRYPTION_KEY
        crypto._fernet = None

    def tearDown(self):
        Config.ENCRYPTION_KEY = self._saved_key
        crypto._fernet = None

    def set_key(self, key):
        Config.ENCRYPTION_KEY = key
        crypto._fernet = None


class TestPassthrough(CryptoTestBase):
    def test_disabled_is_noop(self):
        self.set_key("")
        self.assertFalse(crypto.is_enabled())
        self.assertEqual(crypto.encrypt_value("hello"), "hello")
        self.assertEqual(crypto.decrypt_value("hello"), "hello")

    def test_none_and_empty(self):
        self.set_key(Fernet.generate_key().decode())
        self.assertIsNone(crypto.encrypt_value(None))
        self.assertEqual(crypto.encrypt_value(""), "")
        self.assertIsNone(crypto.decrypt_value(None))


class TestEnabled(CryptoTestBase):
    def test_round_trip(self):
        self.set_key(Fernet.generate_key().decode())
        plain = "The capital of France is Paris. Ünïcode ✓"
        token = crypto.encrypt_value(plain)
        self.assertTrue(crypto.is_token(token))
        self.assertNotEqual(token, plain)
        self.assertEqual(crypto.decrypt_value(token), plain)

    def test_dual_read_legacy_plaintext(self):
        self.set_key(Fernet.generate_key().decode())
        self.assertEqual(crypto.decrypt_value("legacy plaintext row"), "legacy plaintext row")

    def test_double_encrypt_is_idempotent(self):
        self.set_key(Fernet.generate_key().decode())
        token = crypto.encrypt_value("once")
        self.assertEqual(crypto.encrypt_value(token), token)
        self.assertEqual(crypto.decrypt_value(token), "once")

    def test_invalid_token_returns_raw(self):
        self.set_key(Fernet.generate_key().decode())
        bogus = "gAAAA-not-a-real-token"
        self.assertEqual(crypto.decrypt_value(bogus), bogus)

    def test_foreign_key_token_returns_raw(self):
        self.set_key(Fernet.generate_key().decode())
        token = crypto.encrypt_value("secret")
        self.set_key(Fernet.generate_key().decode())  # different key entirely
        self.assertEqual(crypto.decrypt_value(token), token)

    def test_rotation_old_key_still_decrypts(self):
        old = Fernet.generate_key().decode()
        self.set_key(old)
        token = crypto.encrypt_value("rotate me")
        new = Fernet.generate_key().decode()
        self.set_key(f"{new},{old}")
        self.assertEqual(crypto.decrypt_value(token), "rotate me")
        # New writes use the first (new) key
        token2 = crypto.encrypt_value("fresh")
        self.set_key(new)
        self.assertEqual(crypto.decrypt_value(token2), "fresh")

    def test_decrypt_fields(self):
        self.set_key(Fernet.generate_key().decode())
        row = {"a": crypto.encrypt_value("x"), "b": "plain", "c": None}
        out = crypto.decrypt_fields(row, ("a", "b", "c", "missing"))
        self.assertEqual(out["a"], "x")
        self.assertEqual(out["b"], "plain")
        self.assertIsNone(out["c"])
        self.assertIsNone(crypto.decrypt_fields(None, ("a",)))

    def test_malformed_key_raises_clearly(self):
        self.set_key("not-a-valid-key")
        with self.assertRaises(ValueError):
            crypto.encrypt_value("boom")


if __name__ == "__main__":
    unittest.main(verbosity=2)
