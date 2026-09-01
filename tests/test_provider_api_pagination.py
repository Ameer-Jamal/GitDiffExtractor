from datetime import date
import unittest
from unittest.mock import MagicMock, patch

import requests

from models.contribution_models import RepositoryRef
from services.provider_api import BitbucketProviderClient, GitHubProviderClient, _get_json_with_retry


class _FakeConfig:
    def get_bitbucket_username(self):
        return "user"

    def get_bitbucket_api_token(self):
        return "pass"

    def get_bitbucket_workspace(self):
        return "workspace"

    def get_github_token(self):
        return ""

    def get_github_owner(self):
        return "acme"

    def get_github_repo(self):
        return "repo"


class ProviderPaginationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.config = _FakeConfig()

    @patch("services.provider_api.requests.get")
    def test_non_transient_client_error_is_not_retried(self, mock_get):
        response = MagicMock()
        response.status_code = 404
        error = requests.HTTPError(response=response)
        response.raise_for_status.side_effect = error
        mock_get.return_value = response

        with self.assertRaises(requests.HTTPError):
            _get_json_with_retry("https://api.github.com/missing", max_attempts=12)

        self.assertEqual(mock_get.call_count, 1)

    @patch("services.provider_api._get_json_with_retry")
    def test_github_merged_prs_does_not_short_circuit_on_old_merged_at(self, mock_get_json):
        repo = RepositoryRef(
            provider="github",
            workspace="acme",
            slug="repo",
            display_name="acme/repo",
            full_name="acme/repo",
        )

        # API returns updated-desc pages. First item has old merged_at but recent updated_at.
        # A valid in-range merged PR appears later and must still be returned.
        page1 = [
            {
                "number": 1,
                "title": "old merge recently updated",
                "body": "",
                "merged_at": "2025-12-20T10:00:00Z",
                "user": {"login": "alice"},
                "head": {"ref": "feature/old"},
                "base": {"ref": "main"},
            },
            {
                "number": 2,
                "title": "in range on same page",
                "body": "",
                "merged_at": "2026-01-10T12:00:00Z",
                "user": {"login": "alice"},
                "head": {"ref": "feature/new"},
                "base": {"ref": "main"},
            },
        ]
        page2 = [
            {
                "number": 3,
                "title": "in range on later page",
                "body": "",
                "merged_at": "2026-01-11T15:00:00Z",
                "user": {"login": "alice"},
                "head": {"ref": "feature/newer"},
                "base": {"ref": "main"},
            }
        ]
        mock_get_json.side_effect = [page1, page2, []]

        client = GitHubProviderClient(self.config)
        records = client.list_merged_pull_requests(
            repository=repo,
            developer="alice",
            start_date=date(2026, 1, 1),
            end_date=None,
        )

        self.assertEqual([record["number"] for record in records], [2, 3])
        self.assertEqual(mock_get_json.call_count, 3)

    @patch("services.provider_api._get_bitbucket_page_with_resume")
    def test_bitbucket_merged_prs_does_not_short_circuit_on_old_updated_on(self, mock_get_page):
        repo = RepositoryRef(
            provider="bitbucket",
            workspace="acme",
            slug="repo",
            display_name="acme/repo",
            full_name="acme/repo",
        )

        page1 = {
            "values": [
                {
                    "id": 11,
                    "title": "old merge recently updated",
                    "description": "",
                    "updated_on": "2025-12-20T10:00:00+00:00",
                    "author": {"display_name": "Alice", "username": "alice"},
                    "source": {"branch": {"name": "feature/old"}},
                    "destination": {"branch": {"name": "main"}},
                }
            ],
            "next": "https://api.bitbucket.org/2.0/repositories/acme/repo/pullrequests?page=2",
        }
        page2 = {
            "values": [
                {
                    "id": 12,
                    "title": "in range on later page",
                    "description": "",
                    "updated_on": "2026-01-10T12:00:00+00:00",
                    "author": {"display_name": "Alice", "username": "alice"},
                    "source": {"branch": {"name": "feature/new"}},
                    "destination": {"branch": {"name": "main"}},
                }
            ],
            "next": None,
        }
        mock_get_page.side_effect = [page1, page2]

        client = BitbucketProviderClient(self.config)
        records = client.list_merged_pull_requests(
            repository=repo,
            developer="alice",
            start_date=date(2026, 1, 1),
            end_date=None,
        )

        self.assertEqual([record["id"] for record in records], [12])
        self.assertEqual(mock_get_page.call_count, 2)

    @patch("services.provider_api._get_bitbucket_page_with_resume")
    @patch("services.provider_api._get_json_with_retry")
    def test_bitbucket_discovers_distinct_contributed_repositories_from_workspace_prs(
        self,
        mock_get_json,
        mock_get_page,
    ):
        mock_get_json.return_value = {
            "display_name": "Ameer Jamal",
            "nickname": "ameerjamal",
            "uuid": "{user-uuid}",
        }
        mock_get_page.side_effect = [
            {
                "values": [
                    {
                        "id": 10,
                        "destination": {
                            "repository": {
                                "slug": "api",
                                "full_name": "workspace/api",
                                "workspace": {"slug": "workspace"},
                                "links": {
                                    "html": {"href": "https://bitbucket.org/workspace/api"}
                                },
                            }
                        },
                    }
                ],
                "next": "https://api.bitbucket.org/2.0/workspaces/workspace/pullrequests/page-2",
            },
            {
                "values": [
                    {
                        "id": 11,
                        "destination": {
                            "repository": {
                                "slug": "api",
                                "full_name": "workspace/api",
                            }
                        },
                    },
                    {
                        "id": 12,
                        "destination": {
                            "repository": {
                                "slug": "web",
                                "full_name": "workspace/web",
                            }
                        },
                    },
                ],
                "next": None,
            },
        ]

        client = BitbucketProviderClient(self.config)
        repositories = client.list_contributed_repositories(
            developer="Ameer Jamal",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
        )

        self.assertEqual([repo.full_name for repo in repositories], ["workspace/api", "workspace/web"])
        first_url = mock_get_page.call_args_list[0].args[0]
        self.assertIn("/workspaces/workspace/pullrequests/%7Buser-uuid%7D", first_url)
        self.assertIn("state=MERGED", first_url)
        self.assertIn("updated_on%20%3E%3D", first_url)
        self.assertIn("updated_on%20%3C", first_url)

    @patch("services.provider_api._get_bitbucket_page_with_resume")
    @patch("services.provider_api._get_json_with_retry")
    def test_bitbucket_resolves_another_developer_from_workspace_members(
        self,
        mock_get_json,
        mock_get_page,
    ):
        mock_get_json.return_value = {
            "display_name": "Current User",
            "nickname": "current-user",
            "uuid": "{current-uuid}",
        }
        mock_get_page.side_effect = [
            {
                "values": [
                    {
                        "user": {
                            "display_name": "Alice Example",
                            "nickname": "alice",
                            "uuid": "{alice-uuid}",
                        }
                    }
                ],
                "next": None,
            },
            {"values": [], "next": None},
        ]

        client = BitbucketProviderClient(self.config)
        repositories = client.list_contributed_repositories(
            developer="Alice Example",
            start_date=None,
            end_date=None,
        )

        self.assertEqual(repositories, [])
        member_url = mock_get_page.call_args_list[0].args[0]
        pr_url = mock_get_page.call_args_list[1].args[0]
        self.assertIn("/members?pagelen=100", member_url)
        self.assertIn("/pullrequests/%7Balice-uuid%7D", pr_url)


if __name__ == "__main__":
    unittest.main()
