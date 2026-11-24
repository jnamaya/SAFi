import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "public" / "js" / "core" / "chat.js"
SIDEBAR = ROOT / "public" / "js" / "ui" / "ui-auth-sidebar.js"
API_JS = ROOT / "public" / "js" / "core" / "api.js"
SHARE_DIALOG = ROOT / "public" / "js" / "ui" / "ui-share-dialog.js"
API_PY = ROOT / "safi_app" / "api" / "conversations.py"
STORE = ROOT / "safi_app" / "persistence" / "conversation_sharing_store.py"


class SharedWithMeIsOneCollapsedRowAtTheTop(unittest.TestCase):

    def setUp(self):
        self.chat = CHAT.read_text(encoding="utf-8")
        self.sidebar = SIDEBAR.read_text(encoding="utf-8")

    def test_section_renders_through_the_collapsible_row(self):
        self.assertIn("export function renderSidebarSection", self.sidebar)
        self.assertIn("renderSidebarSection(", self.chat)
        self.assertIn("'Shared with me'", self.chat)

    def test_it_is_rendered_before_the_users_own_folders(self):
        shared_at = self.chat.index("'Shared with me'")
        own_at = self.chat.index("projects.forEach(project => {\n        const projConvos")
        self.assertLess(shared_at, own_at,
                        "'Shared with me' must render above the user's own folders")

    def test_it_is_collapsed_by_default(self):
        self.assertIn("SHARED_SECTION_KEY = '__shared_with_me__'", self.chat)
        self.assertIn("expanded.has(SHARED_SECTION_KEY)", self.chat)

    def test_no_empty_row_when_nothing_is_shared(self):
        self.assertIn("if (sharedProjects.length > 0 || sharedConversations.length > 0)", self.chat)

    def test_owner_only_actions_stay_owner_only(self):
        for verb in ("pin", "rename", "delete"):
            self.assertIn(f"notOwner('{verb}')", self.chat)


class SharedByMeIsAMarkNotASection(unittest.TestCase):

    def setUp(self):
        self.chat = CHAT.read_text(encoding="utf-8")
        self.sidebar = SIDEBAR.read_text(encoding="utf-8")

    def test_there_is_no_shared_by_me_section(self):
        for source in (self.chat, self.sidebar):
            self.assertNotIn("'Shared by me'", source)
            self.assertNotIn("`Shared by me`", source)
            self.assertNotIn("textContent = \"Shared by me\"", source)

    def test_owned_rows_carry_the_mark(self):
        self.assertIn("sharedConvoIds: mySharedConvoIds", self.chat)
        self.assertIn("handlers.sharedConvoIds", self.sidebar)
        self.assertIn("shared: mySharedProjectIds.has(project.id)", self.chat)
        self.assertIn("opts.shared", self.sidebar)

    def test_a_grantee_never_sees_the_mark_on_someone_elses_item(self):
        block = self.chat[self.chat.index("const sharedConvoHandlers = {"):
                          self.chat.index("readOnly: true")]
        self.assertNotIn("sharedConvoIds", block)

    def test_the_mark_refreshes_when_a_grant_changes(self):
        self.assertIn("onChange", SHARE_DIALOG.read_text(encoding="utf-8"))
        self.assertIn("openConversationShareDialog(\n            id, title, () => refreshConvoListOnly", self.chat)


class MySharesEndpoint(unittest.TestCase):

    def test_route_exists_and_returns_ids_only(self):
        api = API_PY.read_text(encoding="utf-8")
        self.assertIn("'/conversations/my-shares'", api)
        self.assertIn("conversation_sharing_store.list_shared_by_me", api)

    def test_the_client_calls_it(self):
        self.assertIn("my-shares", API_JS.read_text(encoding="utf-8"))
        self.assertIn("api.fetchMySharedIds()", CHAT.read_text(encoding="utf-8"))

    def test_the_query_is_scoped_to_the_callers_own_resources(self):
        store = STORE.read_text(encoding="utf-8")
        body = store[store.index("def _list_shared_by_me_query"):]
        self.assertIn("JOIN conversations c ON c.id = g.conversation_id", body)
        self.assertIn("c.user_id = %s", body)
        self.assertIn("JOIN projects p ON p.id = g.project_id", body)
        self.assertIn("p.user_id = %s", body)

    def test_it_fails_empty_rather_than_loud(self):
        store = STORE.read_text(encoding="utf-8")
        body = store[store.index("def list_shared_by_me"):store.index("def _list_shared_by_me_query")]
        self.assertIn("except Exception", body)
        self.assertIn("return empty", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
