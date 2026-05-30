import unittest

from mcp_server import DEFAULT_DIFF_CHAR_LIMIT, create_mcp_server

try:
    from mcp.shared.memory import create_connected_server_and_client_session
except ImportError:  # pragma: no cover - dependency installation is validated in test execution
    create_connected_server_and_client_session = None


class _FakeBackend:
    def get_active_context(self):
        return {"provider": "github", "active_repository": {"slug": "demo"}}

    def list_repositories(self, force_refresh=False):
        return [{"provider": "github", "owner": "openai", "slug": "demo"}]

    def get_selected_repositories(self):
        return [{"provider": "github", "owner": "openai", "slug": "demo"}]

    def list_pull_requests(self, **kwargs):
        return {"repository": {"slug": kwargs.get("slug", "demo")}, "records": [{"id": 1}], "next_cursor": ""}

    def list_my_pull_requests(self, **kwargs):
        return {"developer": "me", "records": [{"id": 3}], "count": 1}

    def find_pull_requests_by_ticket(self, **kwargs):
        return {"ticket": kwargs["ticket"], "records": [{"id": 2, "title": kwargs["ticket"]}], "count": 1}

    def get_ticket_diffs(self, **kwargs):
        return {
            "tickets": [
                {
                    "ticket": "RU-25463",
                    "count": 1,
                    "pull_requests": [{"pr": {"id": 2}, "diff_text": "diff --git", "truncated": False}],
                }
            ]
        }

    def get_pr_diff(self, **kwargs):
        return {"diff_text": "x" * (DEFAULT_DIFF_CHAR_LIMIT + 10), "truncated": True, "pr": {"id": kwargs["pr_id"]}}

    def get_commit_diff(self, **kwargs):
        return {"commit_hash": kwargs["commit_hash"], "diff_text": "diff --git", "truncated": False}

    def query_contribution_history(self, **kwargs):
        return {"total_prs": 1, "total_commits": 0, "records": [], "grouped_records": []}

    def list_developer_candidates(self, **kwargs):
        return {"candidates": ["ajamal"]}

    def create_pull_request(self, **kwargs):
        return {"url": "https://example.com/pr/1", "number": 1, "draft": kwargs.get("draft", False)}


@unittest.skipIf(create_connected_server_and_client_session is None, "mcp dependency is unavailable")
class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_are_callable_over_in_memory_transport(self):
        app = create_mcp_server(_FakeBackend())
        async with create_connected_server_and_client_session(app, raise_exceptions=True) as session:
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            self.assertIn("get_active_context", tool_names)
            self.assertIn("get_pr_diff", tool_names)
            self.assertIn("find_pull_requests_by_ticket", tool_names)
            self.assertIn("get_ticket_diffs", tool_names)
            self.assertIn("list_my_pull_requests", tool_names)
            self.assertIn("create_pull_request", tool_names)

            active_result = await session.call_tool("get_active_context", {})
            self.assertEqual(active_result.structuredContent["provider"], "github")

            pr_result = await session.call_tool("get_pr_diff", {"pr_id": "7"})
            self.assertTrue(pr_result.structuredContent["truncated"])
            self.assertEqual(pr_result.structuredContent["pr"]["id"], "7")

            ticket_result = await session.call_tool(
                "find_pull_requests_by_ticket",
                {"ticket": "RU-25463"},
            )
            self.assertEqual(ticket_result.structuredContent["count"], 1)

            ticket_diffs_result = await session.call_tool(
                "get_ticket_diffs",
                {"tickets_json": '["RU-25463"]'},
            )
            self.assertEqual(ticket_diffs_result.structuredContent["tickets"][0]["count"], 1)

            my_prs_result = await session.call_tool("list_my_pull_requests", {})
            self.assertEqual(my_prs_result.structuredContent["count"], 1)

            create_pr_result = await session.call_tool(
                "create_pull_request",
                {"title": "Test PR", "source_branch": "feature/test", "target_branch": "main"},
            )
            self.assertEqual(create_pr_result.structuredContent["number"], 1)


if __name__ == "__main__":
    unittest.main()
