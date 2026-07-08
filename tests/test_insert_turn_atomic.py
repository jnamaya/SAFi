"""
Concurrency test for db.insert_turn_atomic (double-submit proper fix).

Fires many threads inserting a turn with the SAME message_id at once — the
double-submit race. Exactly one must win; every loser must leave NOTHING
behind (no orphaned duplicate user row), and message ordering must stay
user-before-assistant.

Requires the local MySQL instance (uses a throwaway conversation, cleaned up).

Run:  venv/bin/python tests/test_insert_turn_atomic.py
"""
import sys
import uuid
import unittest
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db

# A public-widget user id that exists in the DB (FK target for conversations).
TEST_USER = "public_wp_safi_chat_1779847195268"
THREADS = 8


class TestInsertTurnAtomic(unittest.TestCase):

    def setUp(self):
        self.conv = db.create_conversation(TEST_USER)["id"]

    def tearDown(self):
        db.delete_conversation(self.conv)

    def _rows(self):
        return db.fetch_chat_history_for_conversation(self.conv, limit=50)

    def test_sequential_double_submit_dropped(self):
        mid = str(uuid.uuid4())
        self.assertTrue(db.insert_turn_atomic(self.conv, "hello", mid))
        self.assertFalse(db.insert_turn_atomic(self.conv, "hello", mid))
        rows = self._rows()
        self.assertEqual(len(rows), 2, "exactly one user + one ai row")
        self.assertEqual(sum(1 for r in rows if r["role"] == "user"), 1)
        self.assertEqual(sum(1 for r in rows if r["role"] == "ai"), 1)

    def test_ordering_user_before_ai(self):
        db.insert_turn_atomic(self.conv, "hi", str(uuid.uuid4()))
        rows = self._rows()  # returned in id order
        self.assertEqual(rows[0]["role"], "user")
        self.assertEqual(rows[1]["role"], "ai")

    def test_concurrent_same_id_leaves_one_turn(self):
        mid = str(uuid.uuid4())
        results = []
        lock = threading.Lock()

        def submit():
            ok = db.insert_turn_atomic(self.conv, "concurrent prompt", mid)
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=submit) for _ in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sum(1 for r in results if r), 1, "exactly one insert wins")
        rows = self._rows()
        user_rows = [r for r in rows if r["role"] == "user"]
        ai_rows = [r for r in rows if r["role"] == "ai"]
        self.assertEqual(len(user_rows), 1, "no orphaned duplicate user row")
        self.assertEqual(len(ai_rows), 1)

    def test_distinct_ids_are_separate_turns(self):
        db.insert_turn_atomic(self.conv, "first", str(uuid.uuid4()))
        db.insert_turn_atomic(self.conv, "second", str(uuid.uuid4()))
        rows = self._rows()
        self.assertEqual(len(rows), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
