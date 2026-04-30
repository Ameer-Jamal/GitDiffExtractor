import unittest
from unittest.mock import MagicMock

from mcp_server import GitDiffMCPBackend


class MCPBackendTicketDiffTests(unittest.TestCase):
    def test_get_ticket_diffs_groups_multiple_tickets_and_truncates_per_pr(self):
        backend = object.__new__(GitDiffMCPBackend)
        backend.config = MagicMock()
        backend.pr_service = MagicMock()
        backend.diff_service = MagicMock()

        repo = {
            "provider": "bitbucket",
            "id": "repo-1",
            "owner": "etqdev",
            "slug": "mt-backend",
            "local_dir": "/tmp/mt-backend",
        }
        backend._ticket_search_repositories = MagicMock(return_value=[repo])
        backend._repo_dir = MagicMock(return_value="/tmp/mt-backend")
        backend.pr_service.extract_ticket_id.side_effect = lambda value: value.split(":", 1)[0].upper()
        backend.pr_service.find_pull_requests_by_ticket.side_effect = [
            [
                {
                    "id": 2315,
                    "title": "RU-25463: Fix Open redirect issues",
                    "repo_id": "repo-1",
                    "repo_label": "etqdev/mt-backend",
                }
            ],
            [],
        ]

        diff_result = MagicMock()
        diff_result.diff_text = "abcdef"
        diff_result.merge_base = "base"
        diff_result.resolved_source = "source"
        diff_result.resolved_destination = "destination"
        backend.diff_service.generate_pr_diff.return_value = diff_result

        payload = backend.get_ticket_diffs(
            tickets_json='["RU-25463: Fix Open redirect issues", "RU-00000"]',
            max_chars_per_pr=3,
        )

        self.assertEqual(len(payload["tickets"]), 2)
        self.assertEqual(payload["tickets"][0]["ticket"], "RU-25463")
        self.assertEqual(payload["tickets"][0]["count"], 1)
        self.assertEqual(payload["tickets"][0]["pull_requests"][0]["diff_text"], "abc")
        self.assertTrue(payload["tickets"][0]["pull_requests"][0]["truncated"])
        self.assertEqual(payload["tickets"][1]["ticket"], "RU-00000")
        self.assertEqual(payload["tickets"][1]["count"], 0)

    def test_get_ticket_diffs_requires_json_array(self):
        backend = object.__new__(GitDiffMCPBackend)
        with self.assertRaisesRegex(ValueError, "JSON array"):
            backend.get_ticket_diffs(tickets_json='"RU-25463"')


if __name__ == "__main__":
    unittest.main()
