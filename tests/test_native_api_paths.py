"""
Every API path must reach the server from the native shell too.

WHY. In a browser a bare "/api/..." is same-origin and correct. Inside the
Capacitor WebView the page is served from capacitor://localhost, so the same
string resolves against THAT and the request never reaches the server.

The `urls` table wraps its entries in j() for exactly this reason. Seventeen
endpoints built their path inline and were never wrapped — the org charter, AI
standards, members, role changes, invitations, identity config, member removal
and message cancel. Each worked in a mobile browser and failed silently in the
app: httpGet rejects, the caller's .catch() turns it into null, and the settings
tab renders "Not set" as though the organization had simply never set one.

Reported as "I can see the charter in the mobile browser but not the app", and
it took clearing app data and reinstalling before the difference between the two
made the cause obvious.

Fixed by normalising inside httpGet/httpJSON rather than at each call site: a
caller cannot forget something it does not have to remember. This pins that,
because patching the seventeen would leave the eighteenth free to reintroduce it.

Run:  venv/bin/python tests/test_native_api_paths.py
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API = (Path(__file__).resolve().parent.parent / "public" / "js" / "core" / "api.js").read_text(
    encoding="utf-8")


class TheNormaliserExists(unittest.TestCase):

    def test_apiurl_prefixes_only_on_native(self):
        self.assertIn("const apiUrl =", API)
        self.assertIn("isNative", API[API.index("const apiUrl ="):API.index("const apiUrl =") + 260])

    def test_it_only_touches_root_relative_paths(self):
        """An already-absolute URL (the j()-wrapped ones) must pass through, or
        every one of them becomes https://hosthttps://host/..."""
        seg = API[API.index("const apiUrl ="):API.index("const apiUrl =") + 260]
        self.assertIn("startsWith('/')", seg)

    def test_both_transports_normalise(self):
        """httpGet and httpJSON are the only two paths to the API; missing
        either leaves half the endpoints broken on native."""
        for fn in ("async function httpGet(", "async function httpJSON("):
            i = API.index(fn)
            self.assertIn("url = apiUrl(url);", API[i:i + 400],
                          f"{fn.strip()} does not normalise its url")


class NoEndpointCanBypassIt(unittest.TestCase):

    def test_direct_fetch_calls_use_an_absolute_url(self):
        """fetch() skips httpGet/httpJSON entirely, so those call sites must
        carry j() or a urls.* entry themselves."""
        for m in re.finditer(r"await fetch\(\s*([^,\)]+)", API):
            arg = m.group(1).strip()
            ok = arg.startswith("urls.") or arg.startswith("j(") or arg.startswith("request")
            self.assertTrue(ok, f"direct fetch with a non-absolute url: {arg}")

    def test_the_urls_table_still_wraps_its_entries(self):
        """Belt and braces: apiUrl would now catch these too, but the table is
        the documented pattern and other modules read from it."""
        table = API[API.index("export const urls = {"):API.index("// --- CORE HYBRID FETCHING")]
        bare = re.findall(r"^\s+[A-Z_]+:\s*'(/api[^']*)'", table, re.M)
        self.assertEqual(bare, [], f"urls entries missing j(): {bare}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
