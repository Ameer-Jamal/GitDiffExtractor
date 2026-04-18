import unittest

from RepositoryProvider import RepositoryProvider


class RepositoryProviderTests(unittest.TestCase):
    def test_inject_basic_auth_replaces_existing_userinfo(self):
        url = "https://olduser@bitbucket.org/etqdev/mt-frontend.git"
        out = RepositoryProvider._inject_basic_auth(url, "newuser", "p@ss word")
        self.assertTrue(out.startswith("https://newuser:p%40ss%20word@bitbucket.org/"))
        self.assertNotIn("olduser@", out)

    def test_parse_next_link(self):
        link = '<https://api.github.com/resource?page=2>; rel="next", <https://api.github.com/resource?page=4>; rel="last"'
        self.assertEqual(
            RepositoryProvider._parse_next_link(link),
            "https://api.github.com/resource?page=2",
        )

    def test_discovery_context_key_bitbucket(self):
        key = RepositoryProvider.discovery_context_key(
            "bitbucket", {"workspace": "EtQDev"}
        )
        self.assertEqual(key, "etqdev")

    def test_discovery_context_key_github(self):
        key = RepositoryProvider.discovery_context_key(
            "github", {"owner": ""}
        )
        self.assertEqual(key, "*")


if __name__ == "__main__":
    unittest.main()
