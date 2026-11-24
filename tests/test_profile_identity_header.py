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
        self.assertIn("user_details['org_name'] = None", AUTH)
        self.assertIn("user_details['is_org_owner'] = False", AUTH)

    def test_owner_self_correction_survived_the_refactor(self):
        self.assertIn("Auto-promoting to ADMIN", AUTH)
        self.assertIn("db.update_user_org_and_role(user_id, user_details['org_id'], 'admin')", AUTH)
        i = AUTH.index("is_org_owner'] = (org.get")
        j = AUTH.index("Auto-promoting to ADMIN")
        self.assertLess(i, j, "ownership must be resolved before it is acted on")


class TheHeaderShowsRoleAndOrg(unittest.TestCase):

    def test_owner_outranks_the_role_column(self):
        self.assertIn("is_org_owner", HEADER)
        self.assertIn("'Owner'", HEADER)

    def test_every_role_has_a_human_label(self):
        for role in ("admin", "editor", "auditor", "member"):
            self.assertIn(f"{role}:", JS[JS.index("const ROLE_LABELS"):JS.index("export function setProfileIdentity")])

    def test_unknown_role_falls_back_to_member(self):
        self.assertIn("ROLE_LABELS.member", HEADER)

    def test_a_personal_account_is_named_as_such(self):
        self.assertIn("Personal account", HEADER)

    def test_personal_account_is_decided_by_org_id_not_org_name(self):
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
        self.assertNotIn("placehold.co", HEADER)
        self.assertIn("rounded-full bg-neutral-200", HEADER)

    def test_untrusted_fields_are_escaped(self):
        for expr in ("_identity.name", "_identity.email", "_identity.org_name"):
            self.assertRegex(HEADER, r"escapeHtml\([^)]*" + re.escape(expr.split(".")[-1]))


class ItIsWiredToTheExistingUserPropagation(unittest.TestCase):

    def test_identity_rides_update_current_user(self):
        self.assertIn("setProfileIdentity(u);", CORE)
        block = CORE[CORE.index("export function updateCurrentUser"):]
        self.assertIn("setProfileIdentity(u);", block[:block.index("}")])

    def test_header_renders_above_the_editable_sections(self):
        build = JS[JS.index("function _buildProfileUI"):]
        self.assertLess(build.index("_buildIdentityHeader()"),
                        build.index("_buildCompletenessBar()"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
