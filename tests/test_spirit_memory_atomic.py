"""
Concurrency test for db.update_spirit_memory_atomic (Phase 4).

Hammers the atomic read-modify-write from many threads on a scratch profile
row. compute_fn deliberately sleeps between read and write to widen the race
window — with the old load-then-save pattern most increments were lost to
last-write-wins; under the row lock every one must land and the turn counter
must equal the thread count.

Requires the local MySQL instance (uses a throwaway profile row, cleaned up).

Run:  venv/bin/python tests/test_spirit_memory_atomic.py
"""
import sys
import time
import uuid
import unittest
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.persistence import database as db

THREADS = 8


class TestSpiritMemoryAtomic(unittest.TestCase):

    def setUp(self):
        self.profile = f"test-atomic-{uuid.uuid4().hex[:12]}"

    def tearDown(self):
        db.reset_spirit_memory(self.profile)

    def test_concurrent_updates_all_land(self):
        errors = []

        def one_turn():
            def compute_fn(fresh_memory):
                mu = dict(fresh_memory.get("mu") or {})
                time.sleep(0.05)  # widen the read-modify-write race window
                mu["counter"] = float(mu.get("counter", 0.0)) + 1.0
                return mu, None

            try:
                db.update_spirit_memory_atomic(self.profile, compute_fn)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=one_turn) for _ in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        final = db.load_spirit_memory(self.profile)
        self.assertIsNotNone(final)
        self.assertEqual(final["turn"], THREADS, "every turn increment must land")
        self.assertEqual(final["mu"].get("counter"), float(THREADS),
                         "every EMA contribution must land (no last-write-wins)")

    def test_result_and_turn_passthrough(self):
        def compute_fn(fresh_memory):
            return {"x": 1.0}, ("score", 7)

        result, turn = db.update_spirit_memory_atomic(self.profile, compute_fn)
        self.assertEqual(result, ("score", 7))
        self.assertEqual(turn, 1)
        result, turn = db.update_spirit_memory_atomic(self.profile, compute_fn)
        self.assertEqual(turn, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
