import unittest
import urllib.request

from toolhub import github


class Links(unittest.TestCase):
    def test_next_link(self):
        header = '<https://api.github.com/user/repos?page=2>; rel="next", <https://api.github.com/user/repos?page=3>; rel="last"'
        self.assertEqual(github.next_link(header), "https://api.github.com/user/repos?page=2")
        self.assertIsNone(github.next_link('<x>; rel="last"'))
        self.assertIsNone(github.next_link(None))


class Redirect(unittest.TestCase):
    def redirect(self, target):
        req = urllib.request.Request("https://api.github.com/repos/o/r/releases/assets/1",
                                     headers={"Authorization": "Bearer geheim", "Accept": "application/octet-stream"})
        return github._KeepAuthOnSameHost().redirect_request(req, None, 302, "Found", {}, target)

    def test_token_not_sent_to_other_host(self):
        new = self.redirect("https://objects.githubusercontent.com/file?sig=x")
        self.assertFalse(new.has_header("Authorization"))

    def test_token_kept_on_same_host(self):
        new = self.redirect("https://api.github.com/other")
        self.assertTrue(new.has_header("Authorization"))


if __name__ == "__main__":
    unittest.main()
