import os
import tempfile
import unittest

from toolhub import tools
from toolhub.registry import Installed


def tool(repo, prefix, latest="1.0.0"):
    return tools.Tool(repo=repo, title=prefix.replace("-", " "), description="", private=False, html_url="",
                      latest=latest, asset={"name": f"{prefix}-Setup-{latest}.exe"}, prefix=prefix)


def entry(key, name, version="1.0.0", location="", icon="", uninstall=""):
    return Installed(key, name, version, location, icon, uninstall)


class Versions(unittest.TestCase):
    def test_newer(self):
        self.assertTrue(tools.is_newer("1.10.0", "1.9.9"))
        self.assertTrue(tools.is_newer("2026.10.29.1", "2026.10.29"))
        self.assertFalse(tools.is_newer("1.0", "1.0.0"))
        self.assertFalse(tools.is_newer("0.8.0", "0.8.0"))
        self.assertTrue(tools.is_newer("1.5.0", ""))


class PickSetup(unittest.TestCase):
    def test_prefers_matching_name(self):
        assets = [{"name": n} for n in ("MP3-Organizer-Setup-0.21.0.exe", "music-renamer_0.21.0_amd64.deb",
                                        "Music-Renamer-Setup-0.21.0.exe", "Music-Renamer-Setup-0.21.0.exe.sha256")]
        prefix, asset = tools.pick_setup("music-renamer", assets)
        self.assertEqual(asset["name"], "Music-Renamer-Setup-0.21.0.exe")
        self.assertEqual(prefix, "Music-Renamer")

    def test_other_prefix(self):
        prefix, asset = tools.pick_setup("logistik-map", [{"name": "LogistikMap-Setup-0.8.0.exe"}])
        self.assertEqual(prefix, "LogistikMap")

    def test_without_setup(self):
        self.assertEqual(tools.pick_setup("gesetzesbot", [{"name": "GesetzesBot-Setup-1.8.0.zip"}]), (None, None))
        self.assertEqual(tools.pick_setup("x", None), (None, None))


class Matching(unittest.TestCase):
    ENTRIES = [
        entry("Canio-testserver_is1", "Canio (testserver)", "2.53.0"),
        entry("{9C3F}_is1", "Alvea 1.3.4", "1.3.4"),
        entry("{B6E4}_is1", "Logistik Map", "0.8.0"),
        entry("Git_is1", "Git", "2.56"),
        entry("{MR}_is1", "Music Renamer", "0.20.0"),
    ]

    def test_names(self):
        self.assertEqual(tools.match_installed(tool("alvea", "Alvea"), self.ENTRIES)[0].key, "{9C3F}_is1")
        self.assertEqual(tools.match_installed(tool("logistik-map", "LogistikMap"), self.ENTRIES)[0].key, "{B6E4}_is1")
        self.assertEqual(tools.match_installed(tool("Canio", "Canio"), self.ENTRIES)[0].key, "Canio-testserver_is1")
        self.assertIsNone(tools.match_installed(tool("RetroRenamer", "RetroRenamer"), self.ENTRIES)[0])

    def test_learned_key_wins(self):
        entries = self.ENTRIES + [entry("Canio_is1", "Canio", "2.64.0")]
        main, extra = tools.match_installed(tool("Canio", "Canio"), entries)
        self.assertEqual(main.key, "Canio_is1")
        self.assertEqual([e.key for e in extra], ["Canio-testserver_is1"])
        main, _ = tools.match_installed(tool("Canio", "Canio"), entries, "Canio-testserver_is1")
        self.assertEqual(main.key, "Canio-testserver_is1")

    def test_update_available(self):
        t = tool("music-renamer", "Music-Renamer", "0.21.0")
        t.installed, _ = tools.match_installed(t, self.ENTRIES)
        self.assertTrue(t.update_available)


class StartTarget(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name

    def tearDown(self):
        self.dir.cleanup()

    def touch(self, *parts):
        path = os.path.join(self.root, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path

    def test_url_in_setup_folder(self):
        self.touch("setup", "unins000.exe")
        url = self.touch("setup", "Canio.url")
        self.touch("start.bat")
        self.touch("update.bat")
        e = entry("k", "Canio", location=self.root + "\\", icon=os.path.join(self.root, "setup", "app.ico"))
        self.assertEqual(tools.start_target(e, "Canio", start_menu_dirs=[]), url)

    def test_lnk_prefers_start(self):
        self.touch("OpenDeskSharing beenden.lnk")
        start = self.touch("OpenDeskSharing starten.lnk")
        e = entry("k", "OpenDeskSharing", location=self.root, icon=os.path.join(self.root, "unins000.exe"))
        self.assertEqual(tools.start_target(e, "OpenDeskSharing", start_menu_dirs=[]), start)

    def test_exe_from_icon(self):
        exe = self.touch("MusicRenamer.exe")
        self.touch("unins000.exe")
        e = entry("k", "Music Renamer", location=self.root, icon=exe)
        self.assertEqual(tools.start_target(e, "Music Renamer", start_menu_dirs=[]), exe)

    def test_start_menu(self):
        menu = os.path.join(self.root, "menu")
        self.touch("menu", "OpenRisk", "OpenRisk deinstallieren.lnk")
        lnk = self.touch("menu", "OpenRisk", "OpenRisk.lnk")
        app = os.path.join(self.root, "app")
        self.touch("app", "OpenRisk.bat")
        self.touch("app", "other.bat")
        e = entry("k", "OpenRisk", location=app, icon=os.path.join(app, "app.ico"))
        self.assertEqual(tools.start_target(e, "OpenRisk", start_menu_dirs=[menu]), lnk)

    def test_nothing(self):
        self.touch("unins000.exe")
        e = entry("k", "Risikomonitor", location=self.root, icon=os.path.join(self.root, "app.ico"))
        self.assertIsNone(tools.start_target(e, "Risikomonitor", start_menu_dirs=[]))


class FakeApi:
    def __init__(self, repos, releases):
        self._repos, self.releases, self.calls = repos, releases, []

    def repos(self):
        return self._repos

    def latest_release(self, name):
        self.calls.append(name)
        return self.releases.get(name)


class Discover(unittest.TestCase):
    def test_discover(self):
        repos = [
            {"name": "alvea", "private": True, "pushed_at": "a", "description": "Alvea"},
            {"name": "DiCi", "pushed_at": "b"},
            {"name": "tool-hub", "pushed_at": "c"},
            {"name": "old", "archived": True},
        ]
        releases = {
            "alvea": {"tag_name": "v1.5.0", "assets": [{"name": "Alvea-Setup-1.5.0.exe", "url": "u", "digest": "d"}]},
            "tool-hub": {"tag_name": "v1.1.0", "assets": []},
        }
        no_setup = {}
        api = FakeApi(repos, releases)
        found, own = tools.discover(api, no_setup)
        self.assertEqual([t.repo for t in found], ["alvea"])
        self.assertTrue(found[0].private)
        self.assertEqual(found[0].latest, "1.5.0")
        self.assertEqual(own["tag_name"], "v1.1.0")
        self.assertEqual(list(no_setup), ["DiCi"])
        api.calls.clear()
        tools.discover(api, no_setup)
        self.assertNotIn("DiCi", api.calls)
        # Neues Release ohne Push: spätestens nach 6 Stunden wird wieder nachgesehen
        no_setup["DiCi"]["checked"] -= tools.RECHECK_SECONDS + 1
        releases["DiCi"] = {"tag_name": "v1.0.0", "assets": [{"name": "DiCi-Setup-1.0.0.exe", "url": "u"}]}
        found, _ = tools.discover(api, no_setup)
        self.assertIn("DiCi", [t.repo for t in found])
        self.assertNotIn("DiCi", no_setup)


if __name__ == "__main__":
    unittest.main()
