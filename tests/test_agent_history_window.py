import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.profile_resolver import get_profile
from support import new_user


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def _make_agent(key, created_by, org_id, history_turns=None, history_max_chars=None):
    db.create_agent(
        key=key, name=key.replace('_', ' ').title(), description='t', avatar='',
        worldview='', style='', values=[], rules=[], policy_id='standalone',
        created_by=created_by, org_id=org_id, visibility='private',
        history_turns=history_turns, history_max_chars=history_max_chars)


class HistoryWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.org = str(uuid.uuid4())
        self.owner = new_user(f"hist_owner_{suffix}", org_id=self.org, role='editor')
        self.agent_key = f"hist_agent_{suffix}"

    def tearDown(self):
        _exec("DELETE FROM agents WHERE agent_key=%s", (self.agent_key,))
        _exec("DELETE FROM sessions WHERE user_id=%s", (self.owner,))

    def test_create_and_update_round_trip(self):
        _make_agent(self.agent_key, self.owner, self.org, history_turns=5, history_max_chars=10000)
        got = db.get_agent(self.agent_key)
        self.assertEqual(got['history_turns'], 5)
        self.assertEqual(got['history_max_chars'], 10000)

        db.update_agent(
            key=self.agent_key, name='Renamed', description='t', avatar='',
            worldview='', style='', values=[], rules=[], policy_id='standalone',
            visibility='private', history_turns=12, history_max_chars=20000)
        got = db.get_agent(self.agent_key)
        self.assertEqual(got['history_turns'], 12)
        self.assertEqual(got['history_max_chars'], 20000)

    def test_blank_means_null(self):
        _make_agent(self.agent_key, self.owner, self.org, history_turns=None, history_max_chars=None)
        got = db.get_agent(self.agent_key)
        self.assertIsNone(got['history_turns'])
        self.assertIsNone(got['history_max_chars'])

    def test_zero_round_trips_as_zero(self):
        _make_agent(self.agent_key, self.owner, self.org, history_turns=0, history_max_chars=None)
        got = db.get_agent(self.agent_key)
        self.assertEqual(got['history_turns'], 0)

    def test_profile_surfaces_fields(self):
        _make_agent(self.agent_key, self.owner, self.org, history_turns=7, history_max_chars=15000)
        prof = get_profile(self.agent_key)
        self.assertEqual(prof.get('history_turns'), 7)
        self.assertEqual(prof.get('history_max_chars'), 15000)


if __name__ == '__main__':
    unittest.main()
