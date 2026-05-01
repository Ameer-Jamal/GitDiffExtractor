import unittest
from unittest.mock import MagicMock, patch

from pull_request_service import PullRequestService


class _Config:
    def get_provider(self):
        return "github"

    def get_github_token(self):
        return "secret"

    def get_github_owner(self):
        return "openai"

    def get_bitbucket_username(self):
        return "user"

    def get_bitbucket_app_password(self):
        return "pass"

    def get_bitbucket_workspace(self):
        return "workspace"


class PullRequestServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = PullRequestService(_Config())
        self.repo = {
            "provider": "github",
            "id": "1",
            "owner": "openai",
            "slug": "demo",
            "local_dir": "/tmp/demo",
        }

    @patch("pull_request_service.requests.get")
    def test_list_pull_requests_for_repo_attaches_context(self, mock_get):
        response = MagicMock()
        response.json.return_value = [
            {
                "number": 99,
                "title": "Improve tests",
                "state": "open",
                "merged_at": None,
                "updated_at": "2026-01-01T00:00:00Z",
                "head": {"ref": "feature/x", "sha": "abc"},
                "base": {"ref": "main", "sha": "def"},
                "user": {"login": "ajamal"},
                "html_url": "https://example/pr/99",
                "body": "Details",
            }
        ]
        response.headers = {}
        mock_get.return_value = response

        records, next_cursor = self.service.list_pull_requests_for_repo(self.repo, filter_mode="open")

        self.assertEqual(next_cursor, None)
        self.assertEqual(records[0]["repo_label"], "openai/demo")
        self.assertEqual(records[0]["repo_local_dir"], "/tmp/demo")
        self.assertEqual(records[0]["id"], 99)

    @patch("pull_request_service.requests.get")
    def test_list_pull_requests_for_repo_uses_provider_query_for_developer(self, mock_get):
        search_response = MagicMock()
        search_response.json.return_value = {
            "items": [
                {
                    "pull_request": {"url": "https://api.github.com/repos/openai/demo/pulls/99"},
                }
            ]
        }
        pr_response = MagicMock()
        pr_response.json.return_value = {
            "number": 99,
            "title": "Mine",
            "state": "open",
            "merged_at": None,
            "updated_at": "2026-01-01T00:00:00Z",
            "head": {"ref": "feature/x", "sha": "abc"},
            "base": {"ref": "main", "sha": "def"},
            "user": {"login": "ajamal"},
            "html_url": "https://example/pr/99",
            "body": "Details",
        }
        mock_get.side_effect = [search_response, pr_response]

        records, next_cursor = self.service.list_pull_requests_for_repo(
            self.repo,
            filter_mode="open",
            developer="ajamal",
        )

        self.assertIsNone(next_cursor)
        self.assertEqual(records[0]["id"], 99)
        self.assertIn("author:ajamal", mock_get.call_args_list[0].kwargs["params"]["q"])

    def test_bitbucket_query_expression_omits_author_fields_for_api_compatibility(self):
        expression = PullRequestService._bitbucket_query_expression(
            "RU-123",
            "Zaid",
            ' AND state = "OPEN"',
        )

        self.assertIn('title ~ "RU-123"', expression)
        self.assertNotIn("author.", expression)
        self.assertIn('state = "OPEN"', expression)

    @patch("pull_request_service.requests.get")
    def test_search_pull_requests_uses_issue_search_and_pr_fetch(self, mock_get):
        search_response = MagicMock()
        search_response.json.return_value = {
            "items": [
                {
                    "pull_request": {"url": "https://api.github.com/repos/openai/demo/pulls/99"},
                }
            ]
        }
        pr_response = MagicMock()
        pr_response.json.return_value = {
            "number": 99,
            "title": "Fix bug",
            "state": "open",
            "merged_at": None,
            "updated_at": "2026-01-01T00:00:00Z",
            "head": {"ref": "feature/x", "sha": "abc"},
            "base": {"ref": "main", "sha": "def"},
            "user": {"login": "ajamal"},
            "html_url": "https://example/pr/99",
            "body": "Details",
        }
        mock_get.side_effect = [search_response, pr_response]

        records = self.service.search_pull_requests([self.repo], "open", "fix")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], 99)
        self.assertEqual(records[0]["repo_id"], "1")

    @patch("pull_request_service.requests.get")
    def test_find_pull_requests_by_ticket_extracts_ticket_and_filters_exact_matches(self, mock_get):
        search_response = MagicMock()
        search_response.json.return_value = {
            "items": [
                {"pull_request": {"url": "https://api.github.com/repos/openai/demo/pulls/99"}},
                {"pull_request": {"url": "https://api.github.com/repos/openai/demo/pulls/100"}},
            ]
        }
        matching_pr_response = MagicMock()
        matching_pr_response.json.return_value = {
            "number": 99,
            "title": "RU-25463: Fix Open redirect issues",
            "state": "open",
            "merged_at": None,
            "updated_at": "2026-01-01T00:00:00Z",
            "head": {"ref": "feature/RU-25463-open-redirect", "sha": "abc"},
            "base": {"ref": "main", "sha": "def"},
            "user": {"login": "ajamal"},
            "html_url": "https://example/pr/99",
            "body": "Details",
        }
        non_matching_pr_response = MagicMock()
        non_matching_pr_response.json.return_value = {
            "number": 100,
            "title": "RU-2546 unrelated nearby ticket",
            "state": "open",
            "merged_at": None,
            "updated_at": "2026-01-01T00:00:00Z",
            "head": {"ref": "feature/RU-2546", "sha": "abc"},
            "base": {"ref": "main", "sha": "def"},
            "user": {"login": "ajamal"},
            "html_url": "https://example/pr/100",
            "body": "Details",
        }
        mock_get.side_effect = [search_response, matching_pr_response, non_matching_pr_response]

        records = self.service.find_pull_requests_by_ticket(
            [self.repo],
            "RU-25463: Fix Open redirect issues",
            filter_mode="all",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], 99)

    def test_find_pull_requests_by_ticket_requires_ticket_id(self):
        with self.assertRaisesRegex(ValueError, "ticket id"):
            self.service.find_pull_requests_by_ticket([self.repo], "no ticket here")


if __name__ == "__main__":
    unittest.main()
