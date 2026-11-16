"""
Offline safety tests for tools/update_fighters.py.

No network access: every test that could reach fetch() replaces the opener
with one that fails the test if it is ever called. All temporary files are
written inside tests/_tmp/ (inside the project).

Run from the project root:
    python -I tests/test_update_fighters.py
"""

import io
import shutil
import sys
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "tools"))

import update_fighters as u  # noqa: E402

TMP = TESTS_DIR / "_tmp"
FIXTURE_ATHLETE = ROOT / "data-sources" / "jon-jones.html"
FIXTURE_RECORD_BOOK = ROOT / "data-sources" / "statleaders.html"


class NoNetworkOpener:
    def open(self, *a, **k):
        raise AssertionError("network access attempted during offline test")


def no_network():
    return mock.patch.object(u, "_OPENER", NoNetworkOpener())


class TmpDirTest(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        TMP.mkdir()

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)


# ---------------------------------------------------------------------------
class UrlSafetyTests(unittest.TestCase):
    def test_allowed_urls_pass(self):
        u.check_url("https://www.ufc.com/athlete/jon-jones")
        u.check_url("https://statleaders.ufc.com/")
        u.check_url("https://WWW.UFC.COM/athlete/jon-jones")  # host case-insensitive

    def test_blocked_urls(self):
        bad = [
            "http://www.ufc.com/athlete/jon-jones",          # not HTTPS
            "https://ufc.com/athlete/jon-jones",              # host not on list
            "https://evil.example/www.ufc.com",               # host in path only
            "https://www.ufc.com.evil.example/",              # suffix spoof
            "https://www.ufc.com@evil.example/",              # userinfo trick
            "https://evil.example/?u=https://www.ufc.com",    # host in query
            "ftp://www.ufc.com/",
            "file:///etc/passwd",
            "",
        ]
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaises(u.UnapprovedURLError):
                    u.check_url(url)

    def test_fetch_checks_url_before_network(self):
        with no_network():
            with self.assertRaises(u.UnapprovedURLError):
                u.fetch("http://www.ufc.com/athlete/jon-jones")

    def test_redirect_to_unapproved_host_blocked(self):
        handler = u.SafeRedirectHandler()
        req = urllib.request.Request("https://www.ufc.com/athlete/x")
        for target in ("https://evil.example/", "http://www.ufc.com/athlete/x"):
            with self.subTest(target=target):
                with self.assertRaises(u.UnapprovedURLError):
                    handler.redirect_request(req, None, 302, "Found", {}, target)

    def test_redirect_to_approved_host_allowed(self):
        handler = u.SafeRedirectHandler()
        req = urllib.request.Request("https://www.ufc.com/athlete/x")
        new = handler.redirect_request(req, None, 301, "Moved", {}, "https://www.ufc.com/athlete/y")
        self.assertEqual(new.full_url, "https://www.ufc.com/athlete/y")

    def test_roster_slugs_are_safe_filenames(self):
        import re
        slugs = [s for s, _ in u.ROSTER]
        self.assertEqual(len(slugs), len(set(slugs)), "duplicate slug in ROSTER")
        for slug in slugs:
            with self.subTest(slug=slug):
                self.assertRegex(slug, r"^[a-z0-9]+(-[a-z0-9]+)*$")
                self.assertFalse(re.search(r"[./\\]", slug))


# ---------------------------------------------------------------------------
class OutputSafetyTests(unittest.TestCase):
    def test_paths_inside_project_allowed(self):
        u.safe_output(u.ROOT / "fighters-data.js")
        u.safe_output(u.ROOT / "data-sources" / "athletes" / "x.html")

    def test_paths_outside_project_refused(self):
        for p in (u.ROOT.parent / "x.js", u.ROOT / ".." / "x.js",
                  u.ROOT / "data-sources" / ".." / ".." / "x.js", Path(u.ROOT.anchor) / "x.js"):
            with self.subTest(path=str(p)):
                with self.assertRaises(RuntimeError):
                    u.safe_output(p)

    def test_configured_outputs_are_inside_project(self):
        for p in (u.JS_OUT, u.JSON_OUT, u.RECORD_BOOK_FILE, u.ATHLETE_DIR):
            u.safe_output(p)


# ---------------------------------------------------------------------------
class AthleteParsingTests(TmpDirTest):
    def parse_fixture(self):
        shutil.copy(FIXTURE_ATHLETE, TMP / "jon-jones.html")
        with mock.patch.object(u, "ATHLETE_DIR", TMP):
            return u.parse_athlete("jon-jones", True)

    def test_values_match_saved_page(self):
        f = self.parse_fixture()
        self.assertEqual(f["name"], "Jon Jones")
        self.assertEqual(f["nickname"], "Bones")
        self.assertEqual(f["division"], "Heavyweight")
        self.assertEqual((f["wins"], f["losses"], f["draws"]), (28, 1, 0))
        self.assertEqual((f["koWins"], f["subWins"], f["decWins"]), (11, 7, 10))
        self.assertTrue(f["methodsComplete"])
        self.assertEqual(f["countryCode"], "USA")
        self.assertEqual(f["height"], 76.0)
        self.assertEqual(f["reach"], 84.5)
        self.assertEqual(f["ufc"]["slpm"], 4.38)
        self.assertEqual(f["ufc"]["strAcc"], 59.0)
        self.assertEqual(f["ufc"]["tdDef"], 95.0)
        self.assertEqual(f["sourceUrl"], "https://www.ufc.com/athlete/jon-jones")

    def test_absent_values_are_null_not_invented(self):
        page = ('<h1 class="hero-profile__name">Test Fighter</h1>'
                '<p class="hero-profile__division-body">5-2-0 (W-L-D)</p>')
        (TMP / "test-fighter.html").write_text(page, encoding="utf-8")
        with mock.patch.object(u, "ATHLETE_DIR", TMP):
            f = u.parse_athlete("test-fighter", False)
        self.assertEqual((f["wins"], f["losses"], f["draws"]), (5, 2, 0))
        for key in ("nickname", "division", "koWins", "subWins", "decWins",
                    "height", "reach", "nationality", "countryCode", "birthDate"):
            self.assertIsNone(f[key], key)
        self.assertTrue(all(v is None for v in f["ufc"].values()))
        self.assertFalse(f["methodsComplete"])

    def test_page_without_name_is_rejected(self):
        (TMP / "junk.html").write_text("<html>Access denied</html>", encoding="utf-8")
        with mock.patch.object(u, "ATHLETE_DIR", TMP):
            self.assertIsNone(u.parse_athlete("junk", False))
            self.assertIsNone(u.parse_athlete("not-downloaded", False))

    def test_method_mismatch_flagged(self):
        page = ('<h1 class="hero-profile__name">X</h1>'
                '<p class="hero-profile__division-body">10-0-0 (W-L-D)</p>'
                '<div class="c-stat-3bar__label">KO/TKO</div> <div class="c-stat-3bar__value">3 (30%)</div>'
                '<div class="c-stat-3bar__label">SUB</div> <div class="c-stat-3bar__value">3 (30%)</div>'
                '<div class="c-stat-3bar__label">DEC</div> <div class="c-stat-3bar__value">3 (30%)</div>')
        (TMP / "x.html").write_text(page, encoding="utf-8")
        with mock.patch.object(u, "ATHLETE_DIR", TMP):
            f = u.parse_athlete("x", False)
        self.assertEqual((f["koWins"], f["subWins"], f["decWins"]), (3, 3, 3))
        self.assertFalse(f["methodsComplete"])


# ---------------------------------------------------------------------------
class RecordBookTests(unittest.TestCase):
    def setUp(self):
        self.entries, self.updated = u.parse_record_book()

    def test_last_update_found(self):
        self.assertTrue(self.updated)

    def test_every_entry_has_integer_rank(self):
        bad = [(slug, e) for slug, es in self.entries.items() for e in es if not isinstance(e["rank"], int)]
        self.assertEqual(bad, [], f"{len(bad)} Record Book entries lost their rank")

    def test_category_leader_is_rank_one(self):
        miller = {e["category"]: e for e in self.entries.get("jim-miller", [])}
        self.assertEqual(miller["Total Fights"]["rank"], 1)
        self.assertEqual(miller["Total Fights"]["value"], "48")

    def test_jon_jones_entries(self):
        jj = {e["category"]: e for e in self.entries.get("jon-jones", [])}
        self.assertEqual(jj["Takedown Defense"]["value"], "95.0%")
        self.assertIsInstance(jj["Title Fight Wins"]["rank"], int)


# ---------------------------------------------------------------------------
class MainOfflineTests(TmpDirTest):
    def run_main(self, athletes):
        adir = TMP / "athletes"
        adir.mkdir()
        for slug in athletes:
            shutil.copy(FIXTURE_ATHLETE, adir / f"{slug}.html")
        js, js_json = TMP / "fighters-data.js", TMP / "fighters.json"
        with no_network(), \
             mock.patch.object(u, "ATHLETE_DIR", adir), \
             mock.patch.object(u, "JS_OUT", js), \
             mock.patch.object(u, "JSON_OUT", js_json), \
             mock.patch.object(sys, "argv", ["update_fighters.py", "--offline"]), \
             redirect_stdout(io.StringIO()):
            u.main()
        return js

    def test_offline_build_makes_no_network_calls_and_writes_js(self):
        js = self.run_main(["jon-jones"])
        text = js.read_text(encoding="utf-8")
        self.assertTrue(text.lstrip().startswith("/* AUTO-GENERATED"))
        self.assertIn("window.FIGHTER_DATA = ", text)
        self.assertIn('"name": "Jon Jones"', text)

    def test_existing_data_not_overwritten_with_empty_roster(self):
        js = TMP / "fighters-data.js"
        js.write_text("previous good data", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_main([])
        self.assertEqual(js.read_text(encoding="utf-8"), "previous good data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
