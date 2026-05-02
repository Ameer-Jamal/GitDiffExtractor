from datetime import datetime
import unittest

from services.contribution_exporter import ContributionExportService
from models.contribution_models import ContributionHistoryResult, ContributionRecord, ContributionScope, RepositoryRef


class ContributionExporterTests(unittest.TestCase):
    def setUp(self):
        repo = RepositoryRef(
            provider="github",
            workspace="openai",
            slug="demo",
            display_name="openai/demo",
            full_name="openai/demo",
        )
        self.scope = ContributionScope("current_repo", (repo,), "openai/demo")
        self.record = ContributionRecord(
            record_type="pr",
            provider="github",
            workspace="openai",
            repository="openai/demo",
            repository_display="openai/demo",
            author="ajamal",
            created_at=datetime(2026, 3, 1, 10, 0, 0),
            merged_at=datetime(2026, 3, 2, 10, 0, 0),
            title="AD-316 Improve provider abstraction",
            state="MERGED",
            pr_id="99",
            source_branch="feature/AD-316",
            destination_branch="main",
            link="https://github.com/openai/demo/pull/99",
            ticket_id="AD-316",
        )
        self.result = ContributionHistoryResult(
            records=[self.record],
            repositories_scanned=(repo,),
            scope=self.scope,
            grouped_records=[("openai/demo", [self.record])],
            total_prs=1,
            total_commits=0,
        )
        self.exporter = ContributionExportService()

    def test_csv_titles_only_contains_compact_headers(self):
        content = self.exporter.export_csv([self.record], titles_only=True)
        self.assertIn("date,repository,type,ticket_id,text,link", content)
        self.assertIn("AD-316 Improve provider abstraction", content)

    def test_markdown_grouped_summary_uses_group_heading(self):
        content = self.exporter.export_markdown(
            self.result,
            [self.record],
            titles_only=False,
            grouped_summary=True,
        )
        self.assertIn("## openai/demo", content)
        self.assertIn("feature/AD-316 -> main", content)


if __name__ == "__main__":
    unittest.main()
