from datetime import date
import unittest

from services.contribution_history_service import ContributionHistoryService
from services.provider_api import ContributionRepositoryDiscovery
from models.contribution_models import ContributionHistoryQuery, ContributionScope, RepositoryRef


class _FakeProvider:
    provider_name = "bitbucket"

    def __init__(self):
        self.pr_commit_calls = 0
        self.discovery_calls = []
        self.pr_list_calls = 0

    def validate_credentials(self):
        class _User:
            username = "ajamal"
            display_name = "Ameer Jamal"
            email = "ajamal@example.com"

        return _User()

    def list_merged_pull_requests(
        self,
        repository,
        developer,
        start_date,
        end_date,
        search_text="",
        branch_filter="",
        exclude_bots=True,
        cancel_check=None,
    ):
        self.pr_list_calls += 1
        return [
            {
                "id": 42,
                "title": "AD-316 restore launchdarkly flags",
                "state": "MERGED",
                "author": {"display_name": "Ameer Jamal", "username": "ajamal"},
                "source": {"branch": {"name": "feature/AD-316"}},
                "destination": {"branch": {"name": "develop"}},
                "created_on": "2026-02-01T10:00:00+00:00",
                "updated_on": "2026-02-02T10:00:00+00:00",
                "links": {"html": {"href": "https://example/pr/42"}},
                "description": "Implements AD-316",
            }
        ]

    def list_contributed_repositories(
        self,
        developer,
        start_date,
        end_date,
        cancel_check=None,
    ):
        self.discovery_calls.append((developer, start_date, end_date))
        return [
            RepositoryRef(
                provider="bitbucket",
                workspace="example-workspace",
                slug="backend-service",
                display_name="example-workspace/backend-service",
                full_name="example-workspace/backend-service",
            )
        ]

    def discover_contributed_repositories(
        self,
        developer,
        start_date,
        end_date,
        search_text="",
        branch_filter="",
        exclude_bots=True,
        cancel_check=None,
    ):
        repositories = self.list_contributed_repositories(
            developer,
            start_date,
            end_date,
            cancel_check=cancel_check,
        )
        pull_request = {
            "id": 42,
            "title": "AD-316 restore launchdarkly flags",
            "state": "MERGED",
            "author": {"display_name": "Ameer Jamal", "username": "ajamal"},
            "source": {"branch": {"name": "feature/AD-316"}},
            "destination": {"branch": {"name": "develop"}},
            "created_on": "2026-02-01T10:00:00+00:00",
            "updated_on": "2026-02-02T10:00:00+00:00",
            "links": {"html": {"href": "https://example/pr/42"}},
            "description": "Implements AD-316",
        }
        return ContributionRepositoryDiscovery(
            repositories=tuple(repositories),
            pull_requests_by_repository={repositories[0].key: (pull_request,)},
        )

    def list_pull_request_commits(self, repository, pr_record, cancel_check=None):
        self.pr_commit_calls += 1
        return {"abc123"}

    def list_commits(
        self,
        repository,
        developer,
        start_date,
        end_date,
        search_text="",
        branch_filter="",
        exclude_bots=True,
        cancel_check=None,
    ):
        return [
            {
                "hash": "abc123",
                "date": "2026-02-01T09:00:00+00:00",
                "message": "AD-316 restore launchdarkly flags",
                "author": {"user": {"display_name": "Ameer Jamal"}},
                "links": {"html": {"href": "https://example/commit/abc123"}},
            },
            {
                "hash": "def456",
                "date": "2026-02-05T09:00:00+00:00",
                "message": "OPS-21 tweak health checks",
                "author": {"user": {"display_name": "Ameer Jamal"}},
                "links": {"html": {"href": "https://example/commit/def456"}},
            },
        ]


class _FakeScopeManager:
    def __init__(self, repo):
        self.repo = repo

    def resolve_scope(self, scope_type):
        return ContributionScope(scope_type, (self.repo,), self.repo.display_name)


class ContributionHistoryServiceTests(unittest.TestCase):
    def setUp(self):
        repo = RepositoryRef(
            provider="bitbucket",
            workspace="example-workspace",
            slug="backend-service",
            display_name="example-workspace/backend-service",
            full_name="example-workspace/backend-service",
        )
        self.provider = _FakeProvider()
        self.service = ContributionHistoryService(self.provider, _FakeScopeManager(repo))

    def test_prs_and_commits_dedupes_commits_already_in_pr(self):
        result = self.service.execute_query(
            ContributionHistoryQuery(
                developer="ajamal",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                scope_type="current_repo",
                contribution_type="prs_and_commits",
                group_by="repository",
            )
        )

        self.assertEqual(result.total_prs, 1)
        self.assertEqual(result.total_commits, 1)
        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.records[0].record_type, "commit")
        self.assertEqual(result.records[1].record_type, "pr")

    def test_grouping_by_repository_creates_named_group(self):
        result = self.service.execute_query(
            ContributionHistoryQuery(
                developer="ajamal",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                scope_type="current_repo",
                contribution_type="merged_prs",
                group_by="repository",
            )
        )

        self.assertEqual(len(result.grouped_records), 1)
        self.assertEqual(result.grouped_records[0][0], "example-workspace/backend-service")

    def test_merged_prs_only_skips_pr_commit_lookup(self):
        result = self.service.execute_query(
            ContributionHistoryQuery(
                developer="ajamal",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                scope_type="current_repo",
                contribution_type="merged_prs",
                group_by="none",
            )
        )

        self.assertEqual(result.total_prs, 1)
        self.assertEqual(result.total_commits, 0)
        self.assertEqual(self.provider.pr_commit_calls, 0)

    def test_contributed_repo_scope_discovers_repositories_before_scanning(self):
        partial_updates = []
        result = self.service.execute_query(
            ContributionHistoryQuery(
                developer="Ameer Jamal",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                scope_type="contributed_repos",
                contribution_type="merged_prs",
            ),
            partial_result_callback=lambda partial, completed, total: partial_updates.append(
                (partial, completed, total)
            ),
        )

        self.assertEqual(
            self.provider.discovery_calls,
            [("Ameer Jamal", date(2026, 1, 1), date(2026, 12, 31))],
        )
        self.assertEqual(result.scope.scope_type, "contributed_repos")
        self.assertEqual(result.scope.label, "PR-discovered repositories (1)")
        self.assertEqual([repo.slug for repo in result.repositories_scanned], ["backend-service"])
        self.assertEqual(self.provider.pr_list_calls, 0)
        self.assertEqual(len(partial_updates), 1)
        self.assertEqual(partial_updates[0][1:], (1, 1))
        self.assertEqual(partial_updates[0][0].total_prs, 1)


if __name__ == "__main__":
    unittest.main()
