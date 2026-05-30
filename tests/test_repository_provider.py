import unittest
from unittest.mock import patch

from services.RepositoryProvider import RepositoryProvider, RepositoryProviderError


class RepositoryProviderTests(unittest.TestCase):
    def test_inject_basic_auth_replaces_existing_userinfo(self):
        url = "https://olduser@bitbucket.org/example-workspace/frontend-service.git"
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
            "bitbucket", {"workspace": "Example-Workspace"}
        )
        self.assertEqual(key, "example-workspace")

    def test_discovery_context_key_github(self):
        key = RepositoryProvider.discovery_context_key(
            "github", {"owner": ""}
        )
        self.assertEqual(key, "*")

    def test_update_existing_checkout_recovers_stale_remote_refs(self):
        stale_error = RepositoryProviderError(
            "Git command failed: error: fetching ref refs/remotes/origin/develop failed: incorrect old value provided"
        )

        with patch.object(
            RepositoryProvider,
            "_run_git",
            side_effect=[stale_error, None, None, None],
        ) as run_git, patch.object(
            RepositoryProvider,
            "_run_git_output",
            side_effect=[
                "abc\trefs/heads/develop\n",
                "refs/remotes/origin/develop\nrefs/remotes/origin/Feature/stale\n",
            ],
        ) as run_git_output:
            RepositoryProvider._update_existing_checkout("/tmp/repo")

        self.assertEqual(
            [call.args[0] for call in run_git.call_args_list],
            [
                ["git", "fetch", "--all", "--prune"],
                ["git", "update-ref", "-d", "refs/remotes/origin/Feature/stale"],
                ["git", "remote", "prune", "origin"],
                ["git", "fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*"],
            ],
        )
        self.assertEqual(
            [call.args[0] for call in run_git_output.call_args_list],
            [
                ["git", "ls-remote", "--heads", "origin"],
                ["git", "for-each-ref", "refs/remotes/origin", "--format=%(refname)"],
            ],
        )

    def test_update_existing_checkout_does_not_recover_unrelated_fetch_error(self):
        auth_error = RepositoryProviderError("Git command failed: authentication failed")

        with patch.object(RepositoryProvider, "_run_git", side_effect=auth_error):
            with self.assertRaises(RepositoryProviderError) as context:
                RepositoryProvider._update_existing_checkout("/tmp/repo")

        self.assertIs(context.exception, auth_error)


if __name__ == "__main__":
    unittest.main()
