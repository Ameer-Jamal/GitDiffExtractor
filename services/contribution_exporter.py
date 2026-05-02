from __future__ import annotations

import csv
import io
import json
from typing import Iterable

from models.contribution_models import ContributionHistoryResult, ContributionRecord


class ContributionExportService:
    def export_csv(
        self,
        records: Iterable[ContributionRecord],
        titles_only: bool = False,
    ) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        headers = self._headers(titles_only)
        writer.writerow(headers)
        for record in records:
            writer.writerow(self._row_for_record(record, titles_only))
        return buffer.getvalue()

    def export_json(self, records: Iterable[ContributionRecord]) -> str:
        return json.dumps([record.to_dict() for record in records], indent=2)

    def export_markdown(
        self,
        result: ContributionHistoryResult,
        records: Iterable[ContributionRecord],
        titles_only: bool = False,
        grouped_summary: bool = False,
    ) -> str:
        if grouped_summary and result.grouped_records:
            return self._grouped_markdown(result, titles_only)

        lines = [
            "# Contribution History",
            "",
            f"- Scope: {result.scope.label}",
            f"- Total merged PRs: {result.total_prs}",
            f"- Total standalone commits: {result.total_commits}",
            "",
        ]

        for record in records:
            lines.extend(self._markdown_lines_for_record(record, titles_only))
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _headers(titles_only: bool) -> list[str]:
        if titles_only:
            return ["date", "repository", "type", "ticket_id", "text", "link"]
        return [
            "date",
            "repository",
            "type",
            "author",
            "ticket_id",
            "title_or_message",
            "description",
            "state",
            "source_branch",
            "destination_branch",
            "branch",
            "identifier",
            "link",
        ]

    @staticmethod
    def _row_for_record(record: ContributionRecord, titles_only: bool) -> list[str]:
        date_value = (record.effective_date or record.created_at)
        date_text = date_value.isoformat() if date_value else ""
        if titles_only:
            return [
                date_text,
                record.repository_display,
                record.record_type,
                record.ticket_id,
                record.primary_text,
                record.link,
            ]

        identifier = record.pr_id if record.record_type == "pr" else record.commit_hash
        return [
            date_text,
            record.repository_display,
            record.record_type,
            record.author,
            record.ticket_id,
            record.primary_text,
            record.description,
            record.state,
            record.source_branch,
            record.destination_branch,
            record.branch,
            identifier,
            record.link,
        ]

    @staticmethod
    def _markdown_lines_for_record(record: ContributionRecord, titles_only: bool) -> list[str]:
        date_value = record.effective_date or record.created_at
        date_text = date_value.strftime("%Y-%m-%d") if date_value else "Unknown date"
        line = f"- {date_text} | {record.repository_display} | {record.record_type.upper()} | {record.primary_text}"
        extras = []
        if record.ticket_id:
            extras.append(f"ticket {record.ticket_id}")
        if record.link:
            extras.append(f"[link]({record.link})")
        if not titles_only:
            identifier = record.pr_id if record.record_type == "pr" else record.commit_hash[:12]
            if identifier:
                extras.append(identifier)
            if record.record_type == "pr" and (record.source_branch or record.destination_branch):
                extras.append(f"{record.source_branch} -> {record.destination_branch}")
            if record.record_type == "commit" and record.branch:
                extras.append(record.branch)
        if extras:
            line = f"{line} ({'; '.join(extras)})"
        lines = [line]
        if (
            not titles_only
            and record.record_type == "pr"
            and (record.description or "").strip()
        ):
            description = " ".join((record.description or "").strip().splitlines())
            lines.append(f"  Description: {description}")
        return lines

    def _grouped_markdown(self, result: ContributionHistoryResult, titles_only: bool) -> str:
        lines = [
            "# Contribution History",
            "",
            f"- Scope: {result.scope.label}",
            "",
        ]
        for label, group in result.grouped_records:
            lines.append(f"## {label}")
            lines.append("")
            for record in group:
                lines.extend(self._markdown_lines_for_record(record, titles_only))
            lines.append("")
        return "\n".join(lines).strip() + "\n"
