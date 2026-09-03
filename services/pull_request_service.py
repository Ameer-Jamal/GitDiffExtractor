from __future__ import annotations

import os
import re
from typing import Any, Optional

import requests

from services.PRAggregationService import PRAggregationService
from services.provider_api import ProviderClient


_TICKET_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b", re.IGNORECASE)


class PullRequestService:
    def __init__(self, config):
        self.config = config

    def aggregate_pull_requests(
        self,
        selected_repos: list[dict],
        filter_mode: str,
        cursor_state: dict[str, str],
        reset: bool,
        developer: str = "",
    ) -> tuple[list[dict], dict[str, str]]:
        aggregated_records: list[dict] = []
        next_tokens: dict[str, str] = {}
        repo_fetch_pairs = PRAggregationService.repos_for_page(selected_repos, cursor_state, reset)
        resolved_developer = self.resolve_developer_filter(developer)

        for repo, repo_next in repo_fetch_pairs:
            repo_records, repo_next_token = self.list_pull_requests_for_repo(
                repo,
                filter_mode=filter_mode,
                next_cursor=repo_next or None,
                developer=resolved_developer,
            )
            aggregated_records.extend(repo_records)
            next_tokens[str((repo or {}).get("id", ""))] = repo_next_token or ""

        aggregated_records.sort(key=lambda pr: pr.get("updated_on") or "", reverse=True)
        normalized_state = PRAggregationService.normalize_next_state(selected_repos, next_tokens)
        return aggregated_records, normalized_state

    def list_pull_requests_for_repo(
        self,
        repo: dict,
        *,
        filter_mode: str = "open",
        next_cursor: Optional[str] = None,
        search_text: str = "",
        developer: str = "",
    ) -> tuple[list[dict], Optional[str]]:
        provider = (repo.get("provider") or self.config.get_provider() or "bitbucket").lower()
        resolved_developer = self.resolve_developer_filter(developer)
        if search_text:
            return self.search_pull_requests([repo], filter_mode, search_text, developer=resolved_developer), None
        if resolved_developer:
            return self.search_pull_requests([repo], filter_mode, "", developer=resolved_developer), None
        if provider == "github":
            config = self._get_github_config(repo)
            records, cursor = self._fetch_github_pull_requests_page(filter_mode, config, next_cursor=next_cursor)
        else:
            config = self._get_bitbucket_config(repo)
            records, cursor = self._fetch_bitbucket_pull_requests_page(filter_mode, config, next_cursor=next_cursor)
        records = [self._attach_repo_context(pr, repo) for pr in records]
        return self._filter_by_developer(records, resolved_developer), cursor

    def search_pull_requests(
        self,
        selected_repos: list[dict],
        filter_mode: str,
        query: str,
        developer: str = "",
    ) -> list[dict]:
        provider = (self.config.get_provider() or "bitbucket").lower()
        results: list[dict] = []
        resolved_developer = self.resolve_developer_filter(developer)
        if provider == "bitbucket":
            username = (self.config.get_bitbucket_username() or "").strip()
            password = (self.config.get_bitbucket_api_token() or "").strip()
            if not username or not password:
                return results

            state_clause = ""
            if filter_mode == "open":
                state_clause = ' AND state = "OPEN"'
            elif filter_mode == "merged":
                state_clause = ' AND state = "MERGED"'

            expression = self._bitbucket_query_expression(query, "", state_clause)

            for repo in selected_repos:
                workspace = (repo.get("owner") or "").strip()
                slug = (repo.get("slug") or "").strip()
                if not workspace or not slug:
                    continue
                next_url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{slug}/pullrequests"
                params = {"pagelen": 50}
                if expression:
                    params["q"] = expression
                while next_url:
                    response = requests.get(
                        next_url,
                        params=params,
                        auth=(username, password),
                        timeout=15,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    for pr in payload.get("values", []):
                        results.append(self._attach_repo_context(self._map_bitbucket_pr(pr), repo))
                    next_url = payload.get("next")
                    params = None
            return self._filter_by_developer(results, resolved_developer)

        token = (self.config.get_github_token() or "").strip()
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"token {token}"

        state_term = ""
        if filter_mode == "open":
            state_term = "state:open"
        elif filter_mode == "merged":
            state_term = "state:closed"

        for repo in selected_repos:
            owner = (repo.get("owner") or "").strip()
            slug = (repo.get("slug") or repo.get("name") or "").strip()
            if not owner or not slug:
                continue
            search_query = self._github_search_query(owner, slug, state_term, query, resolved_developer)
            response = requests.get(
                "https://api.github.com/search/issues",
                params={"q": search_query, "per_page": 30},
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            for issue in response.json().get("items", []):
                pr_url = (issue.get("pull_request") or {}).get("url")
                if not pr_url:
                    continue
                pr_response = requests.get(pr_url, headers=headers, timeout=15)
                pr_response.raise_for_status()
                results.append(self._attach_repo_context(self._map_github_pr(pr_response.json()), repo))

        return self._filter_by_developer(results, resolved_developer)

    def find_pull_requests_by_ticket(
        self,
        selected_repos: list[dict],
        ticket: str,
        *,
        filter_mode: str = "all",
    ) -> list[dict]:
        ticket_id = self.extract_ticket_id(ticket)
        if not ticket_id:
            raise ValueError("A ticket id like RU-25463 is required.")

        results = self.search_pull_requests(selected_repos, filter_mode, ticket_id)
        exact_matches = [
            pr
            for pr in results
            if self._pull_request_matches_ticket(pr, ticket_id)
        ]
        exact_matches.sort(
            key=lambda pr: (
                pr.get("updated_on") or "",
                str(pr.get("repo_label") or ""),
                str(pr.get("id") or ""),
            ),
            reverse=True,
        )
        return exact_matches

    def resolve_developer_filter(self, developer: str) -> str:
        value = (developer or "").strip()
        if value.lower() not in {"me", "@me", "self", "mine"}:
            return value
        provider = self._provider_client()
        user = provider.validate_credentials()
        aliases = [
            user.username,
            user.display_name,
            user.email,
        ]
        return ", ".join(alias for alias in aliases if alias)

    def get_pull_request(self, repo: dict, pr_id: str | int) -> dict:
        provider = (repo.get("provider") or self.config.get_provider() or "bitbucket").lower()
        if provider == "github":
            config = self._get_github_config(repo)
            response = requests.get(
                f"https://api.github.com/repos/{config['owner']}/{config['repo']}/pulls/{pr_id}",
                headers=config["headers"],
                timeout=15,
            )
            response.raise_for_status()
            return self._attach_repo_context(self._map_github_pr(response.json()), repo)

        config = self._get_bitbucket_config(repo)
        response = requests.get(
            f"https://api.bitbucket.org/2.0/repositories/{config['workspace']}/{config['slug']}/pullrequests/{pr_id}",
            auth=(config["username"], config["password"]),
            timeout=15,
        )
        response.raise_for_status()
        return self._attach_repo_context(self._map_bitbucket_pr(response.json()), repo)

    def _get_bitbucket_config(self, repo: dict) -> dict:
        username = (self.config.get_bitbucket_username() or "").strip()
        password = (self.config.get_bitbucket_api_token() or "").strip()
        workspace = (repo.get("owner") or self.config.get_bitbucket_workspace() or "").strip()
        slug = (repo.get("slug") or "").strip()
        if not username or not password:
            raise ValueError("Atlassian account email and Bitbucket API token are required.")
        if not workspace or not slug:
            raise ValueError("Bitbucket workspace and repository slug are required.")
        return {
            "username": username,
            "password": password,
            "workspace": workspace,
            "slug": slug,
        }

    def _get_github_config(self, repo: dict) -> dict:
        owner = (repo.get("owner") or self.config.get_github_owner() or "").strip()
        repo_name = (repo.get("slug") or repo.get("name") or "").strip()
        if not owner or not repo_name:
            raise ValueError("GitHub owner and repository are required.")
        headers = {"Accept": "application/vnd.github+json"}
        token = (self.config.get_github_token() or "").strip()
        if token:
            headers["Authorization"] = f"token {token}"
        return {
            "owner": owner,
            "repo": repo_name,
            "headers": headers,
        }

    def _fetch_bitbucket_pull_requests_page(
        self,
        filter_mode: str,
        config: dict,
        next_cursor: Optional[str] = None,
    ) -> tuple[list[dict], Optional[str]]:
        if next_cursor:
            request_url = next_cursor
            request_params = None
        else:
            states = ["OPEN"] if filter_mode == "open" else ["MERGED"] if filter_mode == "merged" else ["OPEN", "MERGED"]
            request_url = f"https://api.bitbucket.org/2.0/repositories/{config['workspace']}/{config['slug']}/pullrequests"
            request_params = [("pagelen", "50")]
            request_params.extend(("state", state) for state in states)

        response = requests.get(
            request_url,
            params=request_params,
            auth=(config["username"], config["password"]),
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        return [self._map_bitbucket_pr(pr) for pr in data.get("values", [])], data.get("next")

    def _fetch_github_pull_requests_page(
        self,
        filter_mode: str,
        config: dict,
        next_cursor: Optional[str] = None,
    ) -> tuple[list[dict], Optional[str]]:
        if next_cursor:
            request_url = next_cursor
            request_params = None
        else:
            state_param = "open" if filter_mode == "open" else "closed" if filter_mode == "merged" else "all"
            request_url = f"https://api.github.com/repos/{config['owner']}/{config['repo']}/pulls"
            request_params = {"per_page": 50, "state": state_param}

        response = requests.get(
            request_url,
            params=request_params,
            headers=config["headers"],
            timeout=15,
        )
        response.raise_for_status()
        records: list[dict] = []
        for pr_record in response.json():
            is_merged = bool(pr_record.get("merged_at"))
            state = pr_record.get("state", "open")
            if filter_mode == "merged" and not is_merged:
                continue
            if filter_mode == "open" and state != "open":
                continue
            records.append(self._map_github_pr(pr_record))
        return records, self._github_next_link(response.headers.get("Link"))

    @staticmethod
    def _attach_repo_context(pr: dict, repo: dict) -> dict:
        repo_copy = dict(pr)
        owner = (repo.get("owner") or "").strip()
        slug = (repo.get("slug") or repo.get("name") or "").strip()
        repo_copy["repo_id"] = str(repo.get("id", ""))
        repo_copy["repo_label"] = f"{owner}/{slug}".strip("/")
        repo_copy["repo_local_dir"] = (repo.get("local_dir") or "").strip()
        return repo_copy

    @staticmethod
    def _matches_developer(*candidates: str, developer: str) -> bool:
        developer = (developer or "").strip()
        if not developer:
            return True
        terms = [part.strip().lower() for part in re.split(r"[,\n;]+", developer) if part.strip()]
        values = [value.strip().lower() for value in candidates if value]
        for term in terms:
            if any(term in value for value in values):
                return True
            normalized_term = re.sub(r"[^a-z0-9]+", "", term)
            if not normalized_term:
                continue
            for value in values:
                normalized_value = re.sub(r"[^a-z0-9]+", "", value)
                if normalized_value and (
                    normalized_term in normalized_value or normalized_value in normalized_term
                ):
                    return True
        return False

    def _filter_by_developer(self, records: list[dict], developer: str) -> list[dict]:
        if not (developer or "").strip():
            return records
        return [
            pr
            for pr in records
            if self._matches_developer(
                pr.get("author") or "",
                pr.get("author_username") or "",
                pr.get("author_nickname") or "",
                pr.get("author_email") or "",
                pr.get("author_account_id") or "",
                developer=developer,
            )
        ]

    def _provider_client(self) -> ProviderClient:
        from services.provider_api import build_provider_client

        return build_provider_client(self.config)

    @staticmethod
    def _bitbucket_query_expression(query: str, developer: str, state_clause: str) -> str:
        clauses: list[str] = []
        query = (query or "").strip()
        if query:
            escaped_query = query.replace('"', '\\"')
            clauses.append(
                f'(title ~ "{escaped_query}" OR source.branch.name ~ "{escaped_query}" '
                f'OR destination.branch.name ~ "{escaped_query}")'
            )
        expression = " AND ".join(clauses) if clauses else ""
        if state_clause:
            expression = f"{expression}{state_clause}" if expression else state_clause.replace(" AND ", "", 1)
        return expression

    @staticmethod
    def _github_search_query(owner: str, slug: str, state_term: str, query: str, developer: str) -> str:
        terms = [f"repo:{owner}/{slug}", "is:pr"]
        if state_term:
            terms.append(state_term)
        query = (query or "").strip()
        if query:
            terms.append(query)
        developer_terms = [
            part.strip()
            for part in re.split(r"[,\n;]+", developer or "")
            if part.strip()
        ]
        if developer_terms:
            # GitHub search only supports exact login for author. Use the first alias
            # and keep local filtering as a backstop for non-login aliases.
            terms.append(f"author:{developer_terms[0]}")
        return " ".join(terms).strip()

    @staticmethod
    def extract_ticket_id(value: str) -> str:
        match = _TICKET_PATTERN.search(value or "")
        return match.group(0).upper() if match else ""

    @staticmethod
    def _pull_request_matches_ticket(pr: dict, ticket_id: str) -> bool:
        haystack = " ".join(
            str(pr.get(field) or "")
            for field in (
                "title",
                "source_branch",
                "destination_branch",
                "description",
                "link",
            )
        )
        return ticket_id.upper() in haystack.upper()

    @staticmethod
    def _map_bitbucket_pr(pr_record: dict) -> dict:
        source = pr_record.get("source") or {}
        destination = pr_record.get("destination") or {}
        links = pr_record.get("links") or {}
        merge_commit = pr_record.get("merge_commit") or {}
        summary = pr_record.get("summary") or {}
        return {
            "id": pr_record.get("id"),
            "title": pr_record.get("title"),
            "state": (pr_record.get("state") or "").upper(),
            "author": ((pr_record.get("author") or {}).get("display_name")),
            "author_username": ((pr_record.get("author") or {}).get("username")),
            "author_nickname": ((pr_record.get("author") or {}).get("nickname")),
            "author_account_id": ((pr_record.get("author") or {}).get("account_id")),
            "source_branch": (source.get("branch") or {}).get("name"),
            "destination_branch": (destination.get("branch") or {}).get("name"),
            "source_commit": (source.get("commit") or {}).get("hash"),
            "destination_commit": (destination.get("commit") or {}).get("hash"),
            "merge_commit": merge_commit.get("hash"),
            "link": (links.get("html") or {}).get("href"),
            "description": summary.get("raw") or pr_record.get("description"),
            "updated_on": pr_record.get("updated_on"),
            "provider": "bitbucket",
        }

    @staticmethod
    def _map_github_pr(pr_record: dict) -> dict:
        head = pr_record.get("head") or {}
        base = pr_record.get("base") or {}
        user = pr_record.get("user") or {}
        merged = bool(pr_record.get("merged_at"))
        state = "MERGED" if merged else (pr_record.get("state") or "open").upper()
        return {
            "id": pr_record.get("number"),
            "title": pr_record.get("title"),
            "state": state,
            "author": user.get("login"),
            "author_username": user.get("login"),
            "source_branch": head.get("ref"),
            "destination_branch": base.get("ref"),
            "source_commit": head.get("sha"),
            "destination_commit": base.get("sha"),
            "merge_commit": pr_record.get("merge_commit_sha"),
            "link": pr_record.get("html_url"),
            "description": pr_record.get("body"),
            "updated_on": pr_record.get("updated_at"),
            "provider": "github",
        }

    def _github_next_link(self, link_header: Optional[str]) -> Optional[str]:
        if not link_header:
            return None
        for part in link_header.split(","):
            section = part.strip().split(";")
            if len(section) < 2:
                continue
            if section[1].strip() == 'rel="next"':
                return section[0].strip().strip("<>")
        return None

    def parse_pr_url(self, url: str) -> Optional[dict[str, str]]:
        """Parses a PR URL and returns a dict with provider, workspace, slug, and pr_id."""
        url = url.strip()
        # Bitbucket: https://bitbucket.org/{workspace}/{slug}/pull-requests/{id}
        bb_match = re.search(r"bitbucket\.org/([^/]+)/([^/]+)/pull-requests/(\d+)", url)
        if bb_match:
            return {
                "provider": "bitbucket",
                "workspace": bb_match.group(1),
                "slug": bb_match.group(2),
                "pr_id": bb_match.group(3),
            }
        
        # GitHub: https://github.com/{owner}/{repo}/pull/{id}
        gh_match = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
        if gh_match:
            return {
                "provider": "github",
                "workspace": gh_match.group(1),
                "slug": gh_match.group(2),
                "pr_id": gh_match.group(3),
            }
        
        return None

    def get_pull_request_comments(
        self,
        repo: dict,
        pr_id: str | int,
        *,
        unresolved_only: bool = False,
        comment_type: str = "all",
        file_path: str = "",
        repo_dir: str = "",
        include_code_context: bool = True,
    ) -> dict[str, Any]:
        """Fetch normalized comments and threads for a PR with code context and AI summary."""
        provider = (repo.get("provider") or self.config.get_provider() or "bitbucket").lower()
        effective_repo_dir = repo_dir or repo.get("local_dir") or ""

        try:
            pr = self.get_pull_request(repo, pr_id)
        except Exception:
            pr = {"id": pr_id, "title": f"Pull Request #{pr_id}", "state": "OPEN", "author": ""}

        reviews_data: list[dict] = []
        if provider == "github":
            raw_review_comments, raw_issue_comments, raw_reviews = self._fetch_github_comments(repo, pr_id)
            resolution_map = self._fetch_github_resolution_status(repo, pr_id)
            normalized_comments = [
                self._map_github_review_comment(c, resolution_map)
                for c in raw_review_comments
            ]
            normalized_comments.extend(
                self._map_github_issue_comment(c)
                for c in raw_issue_comments
            )
            for r in raw_reviews:
                rev = self._map_github_review_summary(r)
                if rev:
                    reviews_data.append(rev)
                    normalized_comments.append(rev)
        else:
            raw_comments = self._fetch_bitbucket_comments(repo, pr_id)
            child_parent_ids = {
                c.get("parent", {}).get("id")
                for c in raw_comments
                if c.get("parent", {}).get("id")
            }
            normalized_comments = [
                self._map_bitbucket_comment(c)
                for c in raw_comments
                if not c.get("deleted") or c.get("id") in child_parent_ids
            ]

        # Extract local code snippet for inline comments if requested
        if include_code_context and effective_repo_dir:
            for c in normalized_comments:
                if c.get("file_path") and c.get("line"):
                    c["code_snippet"] = self._extract_local_code_context(
                        effective_repo_dir, c["file_path"], c["line"]
                    )

        # Build threads and apply filters
        threads, filtered_comments = self._build_comment_threads(
            normalized_comments,
            unresolved_only=unresolved_only,
            comment_type=comment_type,
            file_path_filter=file_path,
        )

        all_threads, _ = self._build_comment_threads(normalized_comments)
        files_with_comments = sorted(list({
            t["file_path"] for t in all_threads if t.get("file_path")
        }))
        unresolved_count = sum(1 for t in all_threads if not t["resolved"])
        resolved_count = sum(1 for t in all_threads if t["resolved"])
        inline_count = sum(1 for t in all_threads if t["comment_type"] == "inline")
        general_count = sum(1 for t in all_threads if t["comment_type"] != "inline")

        summary = {
            "total_comments": len(normalized_comments),
            "total_threads": len(all_threads),
            "unresolved_threads": unresolved_count,
            "resolved_threads": resolved_count,
            "inline_threads": inline_count,
            "general_threads": general_count,
            "filtered_threads": len(threads),
            "filtered_comments": len(filtered_comments),
            "files_with_comments": files_with_comments,
        }

        formatted_summary = self._format_ai_comments_summary(repo, pr, threads, summary)

        return {
            "repository": self._attach_repo_context({}, repo),
            "pr": pr,
            "repo_dir": effective_repo_dir,
            "summary": summary,
            "threads": threads,
            "comments": filtered_comments,
            "reviews": reviews_data,
            "formatted_summary": formatted_summary,
        }

    def _fetch_bitbucket_comments(self, repo: dict, pr_id: str | int) -> list[dict]:
        config = self._get_bitbucket_config(repo)
        url = (
            f"https://api.bitbucket.org/2.0/repositories/"
            f"{config['workspace']}/{config['slug']}/pullrequests/{pr_id}/comments"
        )
        params = {"pagelen": 100}
        comments: list[dict] = []
        while url:
            response = requests.get(
                url,
                params=params,
                auth=(config["username"], config["password"]),
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            comments.extend(payload.get("values", []))
            url = payload.get("next")
            params = None
        return comments

    def _fetch_github_comments(
        self, repo: dict, pr_id: str | int
    ) -> tuple[list[dict], list[dict], list[dict]]:
        config = self._get_github_config(repo)
        headers = config["headers"]

        review_comments: list[dict] = []
        url = f"https://api.github.com/repos/{config['owner']}/{config['repo']}/pulls/{pr_id}/comments"
        params = {"per_page": 100}
        while url:
            response = requests.get(url, params=params, headers=headers, timeout=20)
            response.raise_for_status()
            review_comments.extend(response.json())
            url = self._github_next_link(response.headers.get("Link"))
            params = None

        issue_comments: list[dict] = []
        url = f"https://api.github.com/repos/{config['owner']}/{config['repo']}/issues/{pr_id}/comments"
        params = {"per_page": 100}
        while url:
            response = requests.get(url, params=params, headers=headers, timeout=20)
            response.raise_for_status()
            issue_comments.extend(response.json())
            url = self._github_next_link(response.headers.get("Link"))
            params = None

        reviews: list[dict] = []
        url = f"https://api.github.com/repos/{config['owner']}/{config['repo']}/pulls/{pr_id}/reviews"
        params = {"per_page": 100}
        while url:
            response = requests.get(url, params=params, headers=headers, timeout=20)
            response.raise_for_status()
            reviews.extend(response.json())
            url = self._github_next_link(response.headers.get("Link"))
            params = None

        return review_comments, issue_comments, reviews

    def _fetch_github_resolution_status(self, repo: dict, pr_id: str | int) -> dict[int, bool]:
        config = self._get_github_config(repo)
        token = (self.config.get_github_token() or "").strip()
        if not token:
            return {}

        try:
            pr_number = int(pr_id)
        except (ValueError, TypeError):
            return {}

        query = """
        query($owner: String!, $repo: String!, $pr: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pr) {
              reviewThreads(first: 100) {
                nodes {
                  id
                  isResolved
                  isOutdated
                  comments(first: 100) {
                    nodes {
                      databaseId
                    }
                  }
                }
              }
            }
          }
        }
        """
        try:
            resp = requests.post(
                "https://api.github.com/graphql",
                headers={
                    "Authorization": f"bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "variables": {
                        "owner": config["owner"],
                        "repo": config["repo"],
                        "pr": pr_number,
                    },
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                threads = (
                    data.get("data", {})
                    .get("repository", {})
                    .get("pullRequest", {})
                    .get("reviewThreads", {})
                    .get("nodes", [])
                )
                resolved_map: dict[int, bool] = {}
                for t in threads:
                    is_res = bool(t.get("isResolved"))
                    for c in t.get("comments", {}).get("nodes", []):
                        cid = c.get("databaseId")
                        if cid is not None:
                            resolved_map[cid] = is_res
                return resolved_map
        except Exception:
            pass
        return {}

    @staticmethod
    def _map_bitbucket_comment(raw: dict) -> dict:
        user = raw.get("user") or {}
        content = raw.get("content") or {}
        inline = raw.get("inline")
        parent = raw.get("parent") or {}
        links = raw.get("links") or {}
        resolution = raw.get("resolution")

        is_inline = inline is not None and isinstance(inline, dict)
        file_path = inline.get("path") if is_inline else None
        line_to = inline.get("to") if is_inline else None
        line_from = inline.get("from") if is_inline else None
        line = line_to if line_to is not None else line_from
        side = "to" if line_to is not None else ("from" if line_from is not None else None)
        outdated = bool(inline.get("outdated")) if is_inline else False

        resolved = resolution is not None
        resolved_by = None
        resolved_on = None
        if isinstance(resolution, dict):
            resolved_by = (resolution.get("resolved_by") or {}).get("display_name")
            resolved_on = resolution.get("resolved_on")

        author = (
            user.get("display_name")
            or user.get("nickname")
            or user.get("username")
            or "Unknown"
        )
        author_username = user.get("nickname") or user.get("username") or user.get("display_name") or ""
        html_url = (links.get("html") or {}).get("href") or ""

        body = content.get("raw") or ""
        if raw.get("deleted") and not body:
            body = "*(comment deleted)*"

        return {
            "id": raw.get("id"),
            "parent_id": parent.get("id"),
            "comment_type": "inline" if is_inline else "general",
            "author": author,
            "author_username": author_username,
            "author_display_name": user.get("display_name") or "",
            "body": body,
            "created_at": raw.get("created_on") or "",
            "updated_at": raw.get("updated_on") or "",
            "html_url": html_url,
            "file_path": file_path,
            "line": line,
            "original_line": line,
            "start_line": None,
            "side": side,
            "diff_hunk": None,
            "code_snippet": None,
            "resolved": resolved,
            "resolved_by": resolved_by,
            "resolved_on": resolved_on,
            "outdated": outdated,
            "deleted": bool(raw.get("deleted")),
        }

    @staticmethod
    def _map_github_review_comment(raw: dict, resolved_map: dict[int, bool] | None = None) -> dict:
        user = raw.get("user") or {}
        cid = raw.get("id")
        resolved = (resolved_map or {}).get(cid, False)

        return {
            "id": cid,
            "parent_id": raw.get("in_reply_to_id"),
            "comment_type": "inline",
            "author": user.get("login") or "Unknown",
            "author_username": user.get("login") or "",
            "author_display_name": user.get("login") or "",
            "body": raw.get("body") or "",
            "created_at": raw.get("created_at") or "",
            "updated_at": raw.get("updated_at") or "",
            "html_url": raw.get("html_url") or "",
            "file_path": raw.get("path"),
            "line": raw.get("line") or raw.get("original_line"),
            "original_line": raw.get("original_line"),
            "start_line": raw.get("start_line") or raw.get("original_start_line"),
            "side": raw.get("side") or "RIGHT",
            "diff_hunk": raw.get("diff_hunk"),
            "code_snippet": None,
            "resolved": resolved,
            "resolved_by": None,
            "resolved_on": None,
            "outdated": raw.get("position") is None,
            "review_id": raw.get("pull_request_review_id"),
            "deleted": False,
        }

    @staticmethod
    def _map_github_issue_comment(raw: dict) -> dict:
        user = raw.get("user") or {}
        return {
            "id": raw.get("id"),
            "parent_id": None,
            "comment_type": "general",
            "author": user.get("login") or "Unknown",
            "author_username": user.get("login") or "",
            "author_display_name": user.get("login") or "",
            "body": raw.get("body") or "",
            "created_at": raw.get("created_at") or "",
            "updated_at": raw.get("updated_at") or "",
            "html_url": raw.get("html_url") or "",
            "file_path": None,
            "line": None,
            "original_line": None,
            "start_line": None,
            "side": None,
            "diff_hunk": None,
            "code_snippet": None,
            "resolved": False,
            "resolved_by": None,
            "resolved_on": None,
            "outdated": False,
            "review_id": None,
            "deleted": False,
        }

    @staticmethod
    def _map_github_review_summary(raw: dict) -> Optional[dict]:
        body = (raw.get("body") or "").strip()
        state = (raw.get("state") or "").upper()
        if not body and state not in {"CHANGES_REQUESTED", "COMMENTED"}:
            return None
        user = raw.get("user") or {}
        text = body if body else f"Review submitted with state: {state}"
        return {
            "id": raw.get("id"),
            "parent_id": None,
            "comment_type": "review",
            "review_state": state,
            "author": user.get("login") or "Unknown",
            "author_username": user.get("login") or "",
            "author_display_name": user.get("login") or "",
            "body": text,
            "created_at": raw.get("submitted_at") or "",
            "updated_at": raw.get("submitted_at") or "",
            "html_url": raw.get("html_url") or "",
            "file_path": None,
            "line": None,
            "original_line": None,
            "start_line": None,
            "side": None,
            "diff_hunk": None,
            "code_snippet": None,
            "resolved": state == "APPROVED",
            "resolved_by": None,
            "resolved_on": None,
            "outdated": False,
            "review_id": raw.get("id"),
            "deleted": False,
        }

    @staticmethod
    def _extract_local_code_context(
        repo_dir: str,
        file_path: str,
        line: int,
        context_lines: int = 3,
    ) -> Optional[str]:
        if not repo_dir or not file_path or not line or line <= 0:
            return None
        try:
            full_path = os.path.join(repo_dir, file_path)
            if not os.path.isfile(full_path):
                return None
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            start = max(1, line - context_lines)
            end = min(len(lines), line + context_lines)
            formatted = []
            for l_num in range(start, end + 1):
                marker = ">" if l_num == line else " "
                line_content = lines[l_num - 1].rstrip("\r\n")
                formatted.append(f"{marker} {l_num:4d} | {line_content}")
            return "\n".join(formatted)
        except Exception:
            return None

    @staticmethod
    def _build_comment_threads(
        comments: list[dict],
        *,
        unresolved_only: bool = False,
        comment_type: str = "all",
        file_path_filter: str = "",
    ) -> tuple[list[dict], list[dict]]:
        comments_by_id = {c["id"]: c for c in comments if c.get("id") is not None}

        def get_root_id(comment: dict) -> Any:
            curr = comment
            visited = set()
            while curr.get("parent_id") and curr["parent_id"] in comments_by_id and curr["id"] not in visited:
                visited.add(curr["id"])
                curr = comments_by_id[curr["parent_id"]]
            return curr.get("parent_id") if (curr.get("parent_id") and curr.get("parent_id") not in comments_by_id) else curr["id"]

        thread_map: dict[Any, list[dict]] = {}
        for c in comments:
            root_id = get_root_id(c)
            thread_map.setdefault(root_id, []).append(c)

        threads: list[dict] = []
        for root_id, thread_comments in thread_map.items():
            thread_comments.sort(key=lambda x: str(x.get("created_at") or ""))
            root = thread_comments[0]
            for c in thread_comments:
                if c.get("parent_id") is None or c.get("id") == root_id:
                    root = c
                    break

            replies = [c for c in thread_comments if c != root]

            file_path = root.get("file_path")
            line = root.get("line")
            start_line = root.get("start_line")
            side = root.get("side")
            diff_hunk = root.get("diff_hunk")
            code_snippet = root.get("code_snippet")
            comment_kind = root.get("comment_type") or "general"

            if not file_path:
                for c in thread_comments:
                    if c.get("file_path"):
                        file_path = c.get("file_path")
                        line = c.get("line")
                        start_line = c.get("start_line")
                        side = c.get("side")
                        diff_hunk = c.get("diff_hunk")
                        code_snippet = c.get("code_snippet")
                        comment_kind = "inline"
                        break

            is_resolved = any(bool(c.get("resolved")) for c in thread_comments)
            is_outdated = any(bool(c.get("outdated")) for c in thread_comments)
            resolved_by = next((c.get("resolved_by") for c in thread_comments if c.get("resolved_by")), None)
            resolved_on = next((c.get("resolved_on") for c in thread_comments if c.get("resolved_on")), None)

            thread = {
                "thread_id": root.get("id") or root_id,
                "comment_type": comment_kind,
                "file_path": file_path,
                "line": line,
                "start_line": start_line,
                "side": side,
                "diff_hunk": diff_hunk,
                "code_snippet": code_snippet,
                "resolved": is_resolved,
                "resolved_by": resolved_by,
                "resolved_on": resolved_on,
                "outdated": is_outdated,
                "root_comment": root,
                "replies": replies,
                "reply_count": len(replies),
                "latest_comment": thread_comments[-1],
            }
            threads.append(thread)

        filtered_threads: list[dict] = []
        for t in threads:
            if unresolved_only and t["resolved"]:
                continue
            if comment_type == "inline" and t["comment_type"] != "inline":
                continue
            if comment_type == "general" and t["comment_type"] == "inline":
                continue
            if file_path_filter:
                t_path = (t["file_path"] or "").lower()
                filter_path = file_path_filter.strip().lower()
                if filter_path not in t_path:
                    continue
            filtered_threads.append(t)

        def thread_sort_key(t: dict):
            return (
                0 if t["comment_type"] == "inline" else 1,
                t["file_path"] or "",
                t["line"] or 0,
                str(t["root_comment"].get("created_at") or ""),
            )
        filtered_threads.sort(key=thread_sort_key)

        filtered_comments: list[dict] = []
        for t in filtered_threads:
            filtered_comments.append(t["root_comment"])
            filtered_comments.extend(t["replies"])

        return filtered_threads, filtered_comments

    @staticmethod
    def _format_ai_comments_summary(
        repo: dict,
        pr: dict,
        threads: list[dict],
        summary: dict,
    ) -> str:
        repo_label = (
            repo.get("full_name")
            or repo.get("repo_label")
            or f"{repo.get('owner', '')}/{repo.get('slug', '')}".strip("/")
        )
        pr_id = pr.get("id") or ""
        pr_title = pr.get("title") or ""
        pr_state = pr.get("state") or ""
        author = pr.get("author") or ""

        lines = [
            f"# PR #{pr_id}: {pr_title}".strip(),
            f"**Repository**: {repo_label} | **State**: {pr_state} | **Author**: {author}",
            f"**Summary**: {summary['total_comments']} comments across {summary['total_threads']} threads "
            f"({summary['unresolved_threads']} unresolved, {summary['resolved_threads']} resolved)",
        ]

        if summary.get("files_with_comments"):
            files_str = ", ".join(f"`{f}`" for f in summary["files_with_comments"])
            lines.append(f"**Files with Comments**: {files_str}")
        lines.append("")

        if not threads:
            lines.append("No comments matching the requested criteria.")
            return "\n".join(lines)

        unresolved = [t for t in threads if not t["resolved"]]
        resolved = [t for t in threads if t["resolved"]]

        if unresolved:
            lines.append(f"## Unresolved Threads ({len(unresolved)})")
            lines.append("")
            for idx, t in enumerate(unresolved, 1):
                status_tags = ["[UNRESOLVED]"]
                if t["comment_type"] == "inline":
                    status_tags.append(f"[INLINE: `{t['file_path']}`:{t['line']}]")
                else:
                    status_tags.append("[GENERAL]")
                if t.get("outdated"):
                    status_tags.append("[OUTDATED DIFF]")

                lines.append(f"### Thread {idx} {' '.join(status_tags)}")
                if t["comment_type"] == "inline":
                    lines.append(f"- **File**: `{t['file_path']}`")
                    line_info = f"{t['line']}"
                    if t.get("side"):
                        line_info += f" (side: {t['side']})"
                    lines.append(f"- **Line**: {line_info}")

                    if t.get("code_snippet"):
                        lines.append("- **Code Context**:")
                        lines.append("```")
                        lines.append(t["code_snippet"])
                        lines.append("```")
                    elif t.get("diff_hunk"):
                        lines.append("- **Diff Context**:")
                        lines.append("```diff")
                        lines.append(t["diff_hunk"])
                        lines.append("```")

                root = t["root_comment"]
                lines.append(f"- **Reviewer (@{root.get('author')})** ({root.get('created_at', '')}):")
                body_lines = (root.get("body") or "").splitlines()
                quoted_body = "\n".join(f"  > {line}" for line in body_lines) if body_lines else "  > *(empty comment)*"
                lines.append(quoted_body)

                if t.get("replies"):
                    lines.append(f"- **Replies ({len(t['replies'])})**:")
                    for reply in t["replies"]:
                        reply_body = (reply.get("body") or "").strip()
                        lines.append(f"  - **@{reply.get('author')}** ({reply.get('created_at', '')}): {reply_body}")
                lines.append("")

        if resolved:
            lines.append(f"## Resolved Threads ({len(resolved)})")
            lines.append("")
            for idx, t in enumerate(resolved, 1):
                target = f"`{t['file_path']}`:{t['line']}" if t["comment_type"] == "inline" else "General"
                root = t["root_comment"]
                snippet = (root.get("body") or "").strip().replace("\n", " ")[:100]
                lines.append(f"- **[RESOLVED]** {target} by @{root.get('author')}: {snippet}")
            lines.append("")

        return "\n".join(lines).strip()

