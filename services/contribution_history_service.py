from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from models.contribution_models import (
    ContributionHistoryQuery,
    ContributionHistoryResult,
    ContributionRecord,
    ContributionScope,
    RepositoryRef,
    normalize_record_datetime,
)
from services.provider_api import ProviderClient
from services.scope_manager import ScopeManager

_TICKET_PATTERN = re.compile(r"\b([A-Z]{2,10}-\d+)\b")


@dataclass
class CancelToken:
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True

    def is_cancelled(self) -> bool:
        return self.cancelled


class ContributionHistoryService:
    def __init__(self, provider: ProviderClient, scope_manager: ScopeManager):
        self.provider = provider
        self.scope_manager = scope_manager
        self._query_cache: dict[tuple, list[dict]] = {}
        self._pr_commit_cache: dict[tuple, set[str]] = {}

    def build_default_developer(self) -> str:
        user = self.provider.validate_credentials()
        return user.username or user.display_name or user.email

    def execute_query(
        self,
        query: ContributionHistoryQuery,
        progress_callback: Optional[Callable[[str], None]] = None,
        cancel_token: Optional[CancelToken] = None,
    ) -> ContributionHistoryResult:
        def notify(message: str) -> None:
            if progress_callback:
                progress_callback(message)

        self.provider.validate_credentials()
        # Always run with fresh fetch state so previous partial/rate-limited
        # snapshots do not pin future runs to incomplete results.
        self._query_cache.clear()
        self._pr_commit_cache.clear()
        if query.scope_repositories is not None:
            repositories = tuple(query.scope_repositories)
            scope = ContributionScope(
                scope_type=query.scope_type,
                repositories=repositories,
                label=query.scope_label_override or f"{query.scope_type} ({len(repositories)})",
            )
        else:
            scope = self.scope_manager.resolve_scope(query.scope_type)
        if not scope.repositories:
            raise ValueError("No repositories available for the selected scope.")

        records: list[ContributionRecord] = []
        partial_errors: list[str] = []
        represented_commits: set[str] = set()
        repositories = list(scope.repositories)
        rate_limited_repos: list[RepositoryRef] = []

        if len(repositories) <= 1:
            for index, repository in enumerate(repositories, start=1):
                if cancel_token and cancel_token.is_cancelled():
                    break
                notify(f"Scanning {repository.display_name} ({index}/{len(repositories)})")
                try:
                    repo_records, repo_pr_commits = self._query_repository(repository, query, cancel_token)
                    records.extend(repo_records)
                    represented_commits.update(repo_pr_commits)
                except Exception as exc:  # noqa: BLE001 - partial failure handling
                    partial_errors.append(f"{repository.display_name}: {exc}")
                    if self._is_rate_limited_error(exc):
                        rate_limited_repos.append(repository)
        else:
            if (self.provider.provider_name or "").lower() == "bitbucket":
                # Bitbucket rate limits can trigger even on small multi-repo batches.
                # Use adaptive concurrency to favor completeness over throughput.
                if len(repositories) >= 4 or query.scope_type == "all_repos":
                    max_workers = 1
                else:
                    max_workers = min(2, len(repositories))
            else:
                max_workers = min(6, len(repositories))
            future_to_repo = {}
            completed = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for repository in repositories:
                    if cancel_token and cancel_token.is_cancelled():
                        break
                    future = executor.submit(self._query_repository, repository, query, cancel_token)
                    future_to_repo[future] = repository

                pending = set(future_to_repo.keys())
                while pending:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        repository = future_to_repo[future]
                        completed += 1
                        notify(f"Scanned {repository.display_name} ({completed}/{len(repositories)})")
                        try:
                            repo_records, repo_pr_commits = future.result()
                            records.extend(repo_records)
                            represented_commits.update(repo_pr_commits)
                        except Exception as exc:  # noqa: BLE001 - partial failure handling
                            partial_errors.append(f"{repository.display_name}: {exc}")
                            if self._is_rate_limited_error(exc):
                                rate_limited_repos.append(repository)
                    if cancel_token and cancel_token.is_cancelled():
                        for future in pending:
                            future.cancel()
                        break

        if (
            (self.provider.provider_name or "").lower() == "bitbucket"
            and rate_limited_repos
            and not (cancel_token and cancel_token.is_cancelled())
        ):
            # Additional passes for 429 repos, fully sequential with cooldown.
            dedup_retry: dict[str, RepositoryRef] = {repo.key: repo for repo in rate_limited_repos}
            remaining = list(dedup_retry.values())
            max_rounds = 3
            for round_index in range(max_rounds):
                if not remaining or (cancel_token and cancel_token.is_cancelled()):
                    break
                next_remaining: list[RepositoryRef] = []
                cooldown = min(20.0, 2.0 * (2 ** round_index))
                for index, repository in enumerate(remaining, start=1):
                    if cancel_token and cancel_token.is_cancelled():
                        break
                    notify(
                        f"Retry round {round_index + 1}/{max_rounds} for rate-limited repo "
                        f"{index}/{len(remaining)}: {repository.display_name}"
                    )
                    time.sleep(cooldown)
                    try:
                        repo_records, repo_pr_commits = self._query_repository(repository, query, cancel_token)
                        records.extend(repo_records)
                        represented_commits.update(repo_pr_commits)
                        partial_errors = [
                            message
                            for message in partial_errors
                            if not message.startswith(f"{repository.display_name}:")
                        ]
                    except Exception as exc:  # noqa: BLE001
                        partial_errors.append(f"{repository.display_name}: {exc}")
                        if self._is_rate_limited_error(exc):
                            next_remaining.append(repository)
                remaining = next_remaining

        records = self._deduplicate_records(records, represented_commits, query)
        records.sort(
            key=lambda record: (
                record.effective_date or datetime.min,
                record.repository_display.lower(),
                record.primary_text.lower(),
            ),
            reverse=True,
        )
        grouped_records = self._group_records(records, query.group_by)

        return ContributionHistoryResult(
            records=records,
            repositories_scanned=scope.repositories,
            scope=scope,
            partial_errors=partial_errors,
            grouped_records=grouped_records,
            total_prs=sum(1 for record in records if record.record_type == "pr"),
            total_commits=sum(1 for record in records if record.record_type == "commit"),
            active_repositories=tuple(sorted({record.repository_display for record in records})),
            top_repositories=self._top_repositories(records),
            ticket_prefixes=self._top_ticket_prefixes(records),
        )

    @staticmethod
    def _is_rate_limited_error(exc: Exception) -> bool:
        text = str(exc or "").lower()
        return "429" in text or "too many requests" in text or "rate limit" in text

    def _query_repository(
        self,
        repository: RepositoryRef,
        query: ContributionHistoryQuery,
        cancel_token: Optional[CancelToken],
    ) -> tuple[list[ContributionRecord], set[str]]:
        records: list[ContributionRecord] = []
        represented_commits: set[str] = set()
        wants_prs = query.contribution_type in {"merged_prs", "prs_and_commits"}
        wants_commits = query.contribution_type in {"commits", "prs_and_commits"}
        needs_pr_commit_dedupe = query.contribution_type == "prs_and_commits"

        if wants_prs:
            pull_requests = self._get_or_fetch(
                "prs",
                repository,
                query,
                lambda: self.provider.list_merged_pull_requests(
                    repository,
                    developer=query.developer,
                    start_date=query.start_date,
                    end_date=query.end_date,
                    search_text=query.search_text,
                    branch_filter=query.branch_filter,
                    exclude_bots=query.exclude_bots,
                    cancel_check=cancel_token.is_cancelled if cancel_token else None,
                ),
            )
            for pr in pull_requests:
                if cancel_token and cancel_token.is_cancelled():
                    break
                record = self._map_pr_record(repository, pr)
                records.append(record)
                if needs_pr_commit_dedupe:
                    commit_hashes = self._get_or_fetch_pr_commits(repository, pr, cancel_token)
                    for commit_hash in commit_hashes:
                        represented_commits.add(
                            f"{repository.provider}:{repository.full_name.lower()}:{commit_hash.lower()}"
                        )

        if wants_commits and not (cancel_token and cancel_token.is_cancelled()):
            commits = self._get_or_fetch(
                "commits",
                repository,
                query,
                lambda: self.provider.list_commits(
                    repository,
                    developer=query.developer,
                    start_date=query.start_date,
                    end_date=query.end_date,
                    search_text=query.search_text,
                    branch_filter=query.branch_filter,
                    exclude_bots=query.exclude_bots,
                    cancel_check=cancel_token.is_cancelled if cancel_token else None,
                ),
            )
            for commit in commits:
                records.append(self._map_commit_record(repository, commit))

        return records, represented_commits

    def _get_or_fetch(self, kind: str, repository: RepositoryRef, query: ContributionHistoryQuery, fetcher):
        key = (
            kind,
            repository.key,
            (query.developer or "").strip().lower(),
            query.start_date.isoformat() if query.start_date else "",
            query.end_date.isoformat() if query.end_date else "",
            (query.search_text or "").strip().lower(),
            (query.branch_filter or "").strip().lower(),
            bool(query.exclude_bots),
        )
        cached = self._query_cache.get(key)
        if cached is not None:
            return list(cached)
        records = list(fetcher() or [])
        self._query_cache[key] = list(records)
        return records

    def _get_or_fetch_pr_commits(
        self,
        repository: RepositoryRef,
        pr_record: dict,
        cancel_token: Optional[CancelToken],
    ) -> set[str]:
        pr_id = str(pr_record.get("id") or pr_record.get("number") or "")
        if not pr_id:
            return set()
        key = (repository.key, pr_id)
        cached = self._pr_commit_cache.get(key)
        if cached is not None:
            return set(cached)
        commit_hashes = self.provider.list_pull_request_commits(
            repository,
            pr_record,
            cancel_check=cancel_token.is_cancelled if cancel_token else None,
        )
        commit_hashes = {hash_value.lower() for hash_value in (commit_hashes or set())}
        self._pr_commit_cache[key] = set(commit_hashes)
        return set(commit_hashes)

    def _deduplicate_records(
        self,
        records: list[ContributionRecord],
        represented_commits: set[str],
        query: ContributionHistoryQuery,
    ) -> list[ContributionRecord]:
        deduped: list[ContributionRecord] = []
        seen: set[str] = set()

        for record in records:
            if record.record_type == "commit" and query.contribution_type == "prs_and_commits":
                commit_key = f"{record.provider}:{record.repository.lower()}:{record.commit_hash.lower()}"
                if commit_key in represented_commits:
                    continue

            if record.unique_key in seen:
                continue
            seen.add(record.unique_key)
            deduped.append(record)

        return deduped

    def _group_records(
        self,
        records: list[ContributionRecord],
        group_by: str,
    ) -> list[tuple[str, list[ContributionRecord]]]:
        group_by = (group_by or "none").lower()
        if group_by == "none":
            return [("All results", records)]

        grouped: dict[str, list[ContributionRecord]] = defaultdict(list)
        for record in records:
            key = self._group_label_for_record(record, group_by)
            grouped[key].append(record)

        ordered = sorted(grouped.items(), key=lambda item: item[0].lower())
        if group_by in {"month", "year", "quarter"}:
            ordered = sorted(
                grouped.items(),
                key=lambda item: self._sort_key_for_group(item[0], group_by),
                reverse=True,
            )
        return ordered

    @staticmethod
    def _group_label_for_record(record: ContributionRecord, group_by: str) -> str:
        if group_by == "repository":
            return record.repository_display
        if group_by == "type":
            return "Merged PRs" if record.record_type == "pr" else "Standalone commits"
        if group_by == "ticket":
            return record.ticket_id or "No ticket"
        effective_date = record.effective_date
        if not effective_date:
            return "Unknown date"
        if group_by == "month":
            return effective_date.strftime("%Y-%m")
        if group_by == "year":
            return effective_date.strftime("%Y")
        if group_by == "quarter":
            quarter = ((effective_date.month - 1) // 3) + 1
            return f"{effective_date.year}-Q{quarter}"
        return "All results"

    @staticmethod
    def _sort_key_for_group(label: str, group_by: str):
        if group_by == "year":
            return int(label)
        if group_by == "quarter":
            year, quarter = label.split("-Q", 1)
            return int(year), int(quarter)
        if group_by == "month":
            return tuple(int(part) for part in label.split("-", 1))
        return label

    @staticmethod
    def _map_pr_record(repository: RepositoryRef, pr: dict) -> ContributionRecord:
        title = pr.get("title") or ""
        description = (pr.get("summary") or {}).get("raw") or pr.get("description") or pr.get("body") or ""
        ticket_id = _extract_ticket_id(title, description)

        if repository.provider == "github":
            labels = tuple(label.get("name") or "" for label in pr.get("labels", []))
            pr_id = str(pr.get("number") or "")
            author = ((pr.get("user") or {}).get("login")) or ""
            source_branch = ((pr.get("head") or {}).get("ref")) or ""
            destination_branch = ((pr.get("base") or {}).get("ref")) or ""
            created_at = normalize_record_datetime(pr.get("created_at"))
            merged_at = normalize_record_datetime(pr.get("merged_at"))
            link = pr.get("html_url") or ""
            state = "MERGED" if pr.get("merged_at") else (pr.get("state") or "").upper()
            file_count = pr.get("changed_files")
            additions = pr.get("additions")
            deletions = pr.get("deletions")
        else:
            labels = ()
            pr_id = str(pr.get("id") or "")
            author = ((pr.get("author") or {}).get("display_name")) or ((pr.get("author") or {}).get("username")) or ""
            source_branch = ((pr.get("source") or {}).get("branch") or {}).get("name") or ""
            destination_branch = ((pr.get("destination") or {}).get("branch") or {}).get("name") or ""
            created_at = normalize_record_datetime(pr.get("created_on"))
            merged_at = normalize_record_datetime(pr.get("updated_on"))
            link = ((pr.get("links") or {}).get("html") or {}).get("href") or ""
            state = (pr.get("state") or "").upper()
            file_count = None
            additions = None
            deletions = None

        return ContributionRecord(
            record_type="pr",
            provider=repository.provider,
            workspace=repository.workspace,
            repository=repository.full_name,
            repository_display=repository.display_name,
            author=author,
            created_at=created_at,
            merged_at=merged_at,
            title=title,
            description=description,
            state=state,
            pr_id=pr_id,
            source_branch=source_branch,
            destination_branch=destination_branch,
            link=link,
            labels=labels,
            ticket_id=ticket_id,
            file_count=file_count,
            additions=additions,
            deletions=deletions,
        )

    @staticmethod
    def _map_commit_record(repository: RepositoryRef, commit: dict) -> ContributionRecord:
        if repository.provider == "github":
            inner_commit = commit.get("commit") or {}
            author_obj = inner_commit.get("author") or {}
            message = inner_commit.get("message") or ""
            commit_hash = commit.get("sha") or ""
            author = ((commit.get("author") or {}).get("login")) or author_obj.get("name") or ""
            created_at = normalize_record_datetime(author_obj.get("date"))
            link = commit.get("html_url") or ""
            branch = ""
        else:
            message = commit.get("message") or ""
            commit_hash = commit.get("hash") or ""
            author = (((commit.get("author") or {}).get("user")) or {}).get("display_name") or ((commit.get("author") or {}).get("raw")) or ""
            created_at = normalize_record_datetime(commit.get("date"))
            link = ((commit.get("links") or {}).get("html") or {}).get("href") or ""
            branch = commit.get("branch") or ""

        ticket_id = _extract_ticket_id(message)
        return ContributionRecord(
            record_type="commit",
            provider=repository.provider,
            workspace=repository.workspace,
            repository=repository.full_name,
            repository_display=repository.display_name,
            author=author,
            created_at=created_at,
            message=message.splitlines()[0].strip(),
            commit_hash=commit_hash,
            link=link,
            branch=branch,
            ticket_id=ticket_id,
        )

    @staticmethod
    def _top_repositories(records: list[ContributionRecord]) -> tuple[str, ...]:
        counter = Counter(record.repository_display for record in records)
        return tuple(f"{name} ({count})" for name, count in counter.most_common(3))

    @staticmethod
    def _top_ticket_prefixes(records: list[ContributionRecord]) -> tuple[str, ...]:
        counter = Counter()
        for record in records:
            if record.ticket_id and "-" in record.ticket_id:
                prefix = record.ticket_id.split("-", 1)[0]
                counter[prefix] += 1
        return tuple(f"{prefix} ({count})" for prefix, count in counter.most_common(3))


def _extract_ticket_id(*values: str) -> str:
    for value in values:
        if not value:
            continue
        match = _TICKET_PATTERN.search(value)
        if match:
            return match.group(1)
    return ""
