"""
Sidebar sharing legibility (backlog 56c).

Two decisions are pinned here, both easy to undo by accident later:

1. **"Shared with me" is one collapsed row at the TOP of the Folders
   section.** It used to render inline below the user's own folders, one
   full row per shared folder and per directly-shared conversation, so
   somebody in three shared folders had their own Pinned/History pushed
   down by a dozen rows they did not create.

2. **There is no "Shared by me" section, deliberately.** Everything the
   user shared already lives in their own folders and history; a section
   would list every one of them a second time, with both copies linking to
   the same conversation. What the owner needs ("what am I sharing") is a
   mark on the row where the item already is, fed by ids from
   `GET /api/conversations/my-shares`, with the existing share dialog as
   the place to see grantees and revoke.

Parses the sources rather than executing them — there is no JS runtime in
the test image. Requires no database.

Run:  venv/bin/python tests/test_sidebar_sharing_layout.py
"""
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
        # The loop that renders the user's own project folders.
        own_at = self.chat.index("projects.forEach(project => {\n        const projConvos")
        self.assertLess(shared_at, own_at,
                        "'Shared with me' must render above the user's own folders")

    def test_it_is_collapsed_by_default(self):
        # Expansion rides on the same store as real folders, keyed by a
        # sentinel that cannot collide with a project id. Absent from that
        # store means collapsed, so a first-time user gets one row.
        self.assertIn("SHARED_SECTION_KEY = '__shared_with_me__'", self.chat)
        self.assertIn("expanded.has(SHARED_SECTION_KEY)", self.chat)

    def test_no_empty_row_when_nothing_is_shared(self):
        self.assertIn("if (sharedProjects.length > 0 || sharedConversations.length > 0)", self.chat)

    def test_owner_only_actions_stay_owner_only(self):
        # Unchanged by 56c, and the reason the shared handlers exist at all.
        for verb in ("pin", "rename", "delete"):
            self.assertIn(f"notOwner('{verb}')", self.chat)


class SharedByMeIsAMarkNotASection(unittest.TestCase):

    def setUp(self):
        self.chat = CHAT.read_text(encoding="utf-8")
        self.sidebar = SIDEBAR.read_text(encoding="utf-8")

    def test_there_is_no_shared_by_me_section(self):
        # The phrase appears in the comments explaining WHY there is no such
        # section, so this looks for it as a rendered label instead.
        for source in (self.chat, self.sidebar):
            self.assertNotIn("'Shared by me'", source)
            self.assertNotIn("`Shared by me`", source)
            self.assertNotIn("textContent = \"Shared by me\"", source)

    def test_owned_rows_carry_the_mark(self):
        # Conversations: through the handlers, so a conversation inside a
        # folder and a loose one are marked by the same route.
        self.assertIn("sharedConvoIds: mySharedConvoIds", self.chat)
        self.assertIn("handlers.sharedConvoIds", self.sidebar)
        # Folders: through opts.
        self.assertIn("shared: mySharedProjectIds.has(project.id)", self.chat)
        self.assertIn("opts.shared", self.sidebar)

    def test_a_grantee_never_sees_the_mark_on_someone_elses_item(self):
        # The handlers used for the shared-with-me subtree deliberately carry
        # no sharedConvoIds, and the shared folders are rendered read-only.
        block = self.chat[self.chat.index("const sharedConvoHandlers = {"):
                          self.chat.index("readOnly: true")]
        self.assertNotIn("sharedConvoIds", block)

    def test_the_mark_refreshes_when_a_grant_changes(self):
        # Granting or revoking must not need a reload to change the mark.
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
        # Both halves must join the resource table and filter on the owner —
        # without that this leaks which of OTHER people's items are shared.
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
