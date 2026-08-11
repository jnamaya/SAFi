"""
The My Profile tab names who you are signed in as, your org, and your role.

WHY. SAFi's UI is already role-dependent — Knowledge is hidden from members,
renaming a knowledge base is owner-only, several tabs are admin/auditor gated —
but until now nothing on screen ever stated what your role WAS. A tab you
cannot see was indistinguishable from a tab that is broken. Role changes are
written to the compliance log (`member_role_changed`); the person they happened
to should be able to see the result.

The org NAME was the missing piece server-side: `get_user_details` is
`SELECT * FROM users`, so `/me` carried `org_id` but nothing could name the
organization. `db.get_organization` was already fetched in that handler, but
only for non-admins, inside the owner self-correction branch.

Two properties this pins beyond "the fields exist":

  * Read-only. This tab is what SAFi remembers about you, not where you edit
    your account. Form styling here would promise an edit that does not exist.
  * No remote avatar placeholder. The sidebar falls back to placehold.co; in
    the header that request is exactly the one that fails offline and in the
    Capacitor shell, so the fallback is a locally-rendered monogram.

Source-level, like the other front-end guards. Run:
    venv/bin/python tests/test_profile_identity_header.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AUTH = (ROOT / "safi_app" / "api" / "auth.py").read_text(encoding="utf-8")
JS = (ROOT / "public" / "js" / "ui" / "settings" / "ui-settings-user.js").read_text(
    encoding="utf-8")
CORE = (ROOT / "public" / "js" / "ui" / "settings" / "ui-settings-core.js").read_text(
    encoding="utf-8")

HEADER = JS[JS.index("function _buildIdentityHeader"):JS.index("export async function renderSettingsMyProfileTab")]


class MeExposesTheOrganization(unittest.TestCase):

    def test_org_name_and_ownership_are_returned(self):
        self.assertIn("user_details['org_name'] = org.get('name')", AUTH)
        self.assertIn("user_details['is_org_owner'] = (org.get('owner_id') == user_id)", AUTH)

    def test_they_default_to_absent_not_missing(self):
        """A personal account must get explicit nulls, so the client renders
        'Personal account' rather than reading undefined."""
        self.assertIn("user_details['org_name'] = None", AUTH)
        self.assertIn("user_details['is_org_owner'] = False", AUTH)

    def test_owner_self_correction_survived_the_refactor(self):
        """The org row is now fetched for every org member, not only
        non-admins. The auto-promotion that used to live in that branch must
        still fire."""
        self.assertIn("Auto-promoting to ADMIN", AUTH)
        self.assertIn("db.update_user_org_and_role(user_id, user_details['org_id'], 'admin')", AUTH)
        i = AUTH.index("is_org_owner'] = (org.get")
        j = AUTH.index("Auto-promoting to ADMIN")
        self.assertLess(i, j, "ownership must be resolved before it is acted on")


class TheHeaderShowsRoleAndOrg(unittest.TestCase):

    def test_owner_outranks_the_role_column(self):
        """An owner is always an admin, so 'Administrator' would be true but
        useless — 'Owner' is the answer to 'why can I rename this and my
        colleague cannot'."""
        self.assertIn("is_org_owner", HEADER)
        self.assertIn("'Owner'", HEADER)

    def test_every_role_has_a_human_label(self):
        for role in ("admin", "editor", "auditor", "member"):
            self.assertIn(f"{role}:", JS[JS.index("const ROLE_LABELS"):JS.index("export function setProfileIdentity")])

    def test_unknown_role_falls_back_to_member(self):
        """Least privilege in the display too: an unrecognised role must not
        render blank or as something more senior."""
        self.assertIn("ROLE_LABELS.member", HEADER)

    def test_a_personal_account_is_named_as_such(self):
        self.assertIn("Personal account", HEADER)

    def test_personal_account_is_decided_by_org_id_not_org_name(self):
        """Regression, 2026-08-11: keyed off org_name, so a member of
        safinstitute.org whose /me predated the org_name field was shown
        "Personal account" — a false claim about governance membership. Only
        org_id decides whether someone belongs to an organization; a missing
        name degrades to the role alone, which is still true."""
        cond = HEADER[HEADER.index("const affiliation"):]
        cond = cond[:cond.index(";")]
        self.assertIn("_identity.org_id", cond)
        self.assertLess(cond.index("_identity.org_id"), cond.index("org_name"),
                        "org_id must be the outer test")
        self.assertLess(cond.index("org_name"), cond.index("Personal account"),
                        "'Personal account' must be the no-org_id branch only")


class TheHeaderIsReadOnlyAndOffline(unittest.TestCase):

    def test_no_form_controls(self):
        for tag in ("<input", "<textarea", "<select", "contenteditable"):
            self.assertNotIn(tag, HEADER,
                             f"{tag} promises an edit this tab does not support")

    def test_no_remote_placeholder_image(self):
        """placehold.co is the sidebar's fallback; in the Capacitor shell and
        offline it is the request that fails."""
        self.assertNotIn("placehold.co", HEADER)
        self.assertIn("rounded-full bg-neutral-200", HEADER)

    def test_untrusted_fields_are_escaped(self):
        """Name, email and org name are all user- or admin-supplied."""
        for expr in ("_identity.name", "_identity.email", "_identity.org_name"):
            self.assertRegex(HEADER, r"escapeHtml\([^)]*" + re.escape(expr.split(".")[-1]))


class ItIsWiredToTheExistingUserPropagation(unittest.TestCase):

    def test_identity_rides_update_current_user(self):
        """Rather than a second setter threaded through both call sites
        (app.js on open, ui-settings-core.js on tab click)."""
        self.assertIn("setProfileIdentity(u);", CORE)
        block = CORE[CORE.index("export function updateCurrentUser"):]
        self.assertIn("setProfileIdentity(u);", block[:block.index("}")])

    def test_header_renders_above_the_editable_sections(self):
        build = JS[JS.index("function _buildProfileUI"):]
        self.assertLess(build.index("_buildIdentityHeader()"),
                        build.index("_buildCompletenessBar()"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
