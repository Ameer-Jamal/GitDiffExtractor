from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
import re
import threading
import time
from typing import Callable, Optional

import requests

from ConfigManager import ConfigManager
from contribution_models import RepositoryRef, normalize_record_datetime


CancelCheck = Optional[Callable[[], bool]]
_BITBUCKET_HOST = "api.bitbucket.org"
_BITBUCKET_CONCURRENCY = threading.Semaphore(1)
_BITBUCKET_RATE_LOCK = threading.Lock()
_BITBUCKET_NEXT_REQUEST_TS = 0.0


def _should_cancel(cancel_check: CancelCheck) -> bool:
    return bool(cancel_check and cancel_check())


def _apply_bitbucket_rate_limit(url: str):
    global _BITBUCKET_NEXT_REQUEST_TS
    if _BITBUCKET_HOST not in (url or ""):
        return
    with _BITBUCKET_RATE_LOCK:
        now = time.monotonic()
        if now < _BITBUCKET_NEXT_REQUEST_TS:
            time.sleep(_BITBUCKET_NEXT_REQUEST_TS - now)
        # Keep a conservative gap between outbound Bitbucket requests.
        _BITBUCKET_NEXT_REQUEST_TS = time.monotonic() + 0.35


def _is_rate_limited_exception(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return "429" in text or "too many requests" in text or "rate limit" in text


def _get_bitbucket_page_with_resume(
    url: str,
    *,
    auth,
    timeout: int = 20,
    max_resume_attempts: int = 4,
):
    attempt = 0
    while True:
        try:
            return _get_json_with_retry(url, auth=auth, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limited_exception(exc) and attempt < max_resume_attempts:
                # Cursor-aware continuation: keep the same page URL and retry later.
                cooldown = min(90.0, 6.0 * (2 ** attempt))
                time.sleep(cooldown)
                attempt += 1
                continue
            raise


def _get_json_with_retry(
    url: str,
    *,
    params=None,
    auth=None,
    headers=None,
    timeout: int = 20,
    max_attempts: int = 12,
):
    last_error = None
    is_bitbucket = _BITBUCKET_HOST in (url or "")
    for attempt in range(max_attempts):
        _apply_bitbucket_rate_limit(url)
        if is_bitbucket:
            with _BITBUCKET_CONCURRENCY:
                response = requests.get(url, params=params, auth=auth, headers=headers, timeout=timeout)
        else:
            response = requests.get(url, params=params, auth=auth, headers=headers, timeout=timeout)

        if response.status_code in {429, 500, 502, 503, 504} and attempt < (max_attempts - 1):
            retry_after = response.headers.get("Retry-After")
            try:
                sleep_seconds = float(retry_after) if retry_after else (0.8 * (2 ** attempt))
            except ValueError:
                sleep_seconds = 0.8 * (2 ** attempt)
            if response.status_code == 429:
                sleep_seconds = max(sleep_seconds, 3.0 + (attempt * 1.5))
            time.sleep(min(90.0, max(0.7, sleep_seconds)))
            continue
        try:
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < (max_attempts - 1):
                time.sleep(min(45.0, 0.8 * (2 ** attempt)))
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("Failed to fetch provider data.")


@dataclass(frozen=True)
class ProviderUser:
    username: str
    display_name: str = ""
    email: str = ""


class ProviderClient(ABC):
    provider_name = ""

    def __init__(self, config: ConfigManager):
        self.config = config

    @abstractmethod
    def validate_credentials(self) -> ProviderUser:
        raise NotImplementedError

    @abstractmethod
    def list_repositories(self, cancel_check: CancelCheck = None) -> list[RepositoryRef]:
        raise NotImplementedError

    @abstractmethod
    def current_repository(self) -> Optional[RepositoryRef]:
        raise NotImplementedError

    @abstractmethod
    def list_merged_pull_requests(
        self,
        repository: RepositoryRef,
        developer: str,
        start_date: Optional[date],
        end_date: Optional[date],
        search_text: str = "",
        branch_filter: str = "",
        exclude_bots: bool = True,
        cancel_check: CancelCheck = None,
    ) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_pull_request_commits(
        self,
        repository: RepositoryRef,
        pr_record: dict,
        cancel_check: CancelCheck = None,
    ) -> set[str]:
        raise NotImplementedError

    @abstractmethod
    def list_commits(
        self,
        repository: RepositoryRef,
        developer: str,
        start_date: Optional[date],
        end_date: Optional[date],
        search_text: str = "",
        branch_filter: str = "",
        exclude_bots: bool = True,
        cancel_check: CancelCheck = None,
    ) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_developer_candidates(
        self,
        repository: RepositoryRef,
        limit: int = 50,
        cancel_check: CancelCheck = None,
    ) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def context_key(self) -> str:
        raise NotImplementedError

    @staticmethod
    def _matches_developer(*candidates: str, developer: str) -> bool:
        developer = (developer or "").strip()
        if not developer:
            return True
        terms = [part.strip().lower() for part in re.split(r"[,\n;]+", developer) if part.strip()]
        if not terms:
            return True
        values = [value.strip().lower() for value in candidates if value]
        for term in terms:
            if any(term in value for value in values):
                return True
            # Normalize identity aliases so "Ameer Jamal", "ameerjamal", and
            # similar punctuation/spacing variants match consistently across repos.
            normalized_term = re.sub(r"[^a-z0-9]+", "", term)
            if not normalized_term:
                continue
            for value in values:
                normalized_value = re.sub(r"[^a-z0-9]+", "", value)
                if not normalized_value:
                    continue
                if normalized_term in normalized_value or normalized_value in normalized_term:
                    return True
        return False

    @staticmethod
    def _matches_search(*candidates: str, search_text: str) -> bool:
        search_text = (search_text or "").strip().lower()
        if not search_text:
            return True
        haystack = " ".join(value.strip().lower() for value in candidates if value)
        return search_text in haystack

    @staticmethod
    def _matches_branch(branch_filter: str, *branches: str) -> bool:
        branch_filter = (branch_filter or "").strip().lower()
        if not branch_filter:
            return True
        normalized = [branch.strip().lower() for branch in branches if branch]
        return any(branch_filter in branch for branch in normalized)

    @staticmethod
    def _is_date_in_range(
        record_date,
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> bool:
        if not record_date:
            return False
        dt = normalize_record_datetime(record_date)
        if not dt:
            return False
        value = dt.date()
        if start_date and value < start_date:
            return False
        if end_date and value > end_date:
            return False
        return True

    @staticmethod
    def _exclude_bot(author: str, exclude_bots: bool) -> bool:
        if not exclude_bots:
            return False
        author = (author or "").strip().lower()
        return author.endswith("[bot]") or "bot" in author


class BitbucketProviderClient(ProviderClient):
    provider_name = "bitbucket"

    def _auth(self) -> tuple[str, str]:
        return (
            (self.config.get_bitbucket_username() or "").strip(),
            (self.config.get_bitbucket_app_password() or "").strip(),
        )

    def _workspace(self) -> str:
        return (self.config.get_bitbucket_workspace() or "").strip()

    def validate_credentials(self) -> ProviderUser:
        username, password = self._auth()
        workspace = self._workspace()
        if not username or not password:
            raise ValueError("Bitbucket username and app password are required.")
        if not workspace:
            raise ValueError("Bitbucket workspace is required.")

        # Validate against repository access in the configured workspace instead of
        # the user profile endpoint, which may be forbidden for app passwords that
        # only have repository scopes.
        try:
            data = _get_json_with_retry(
                f"https://api.bitbucket.org/2.0/repositories/{workspace}",
                params={"pagelen": 1},
                auth=(username, password),
                timeout=20,
            )
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            if status in {401, 403}:
                raise ValueError(
                    "Bitbucket credentials were rejected for workspace access. "
                    "Verify username/app-password and ensure repository read access "
                    f"for workspace '{workspace}'."
                ) from exc
            raise
        if not isinstance(data, dict):
            raise ValueError("Bitbucket workspace validation failed.")
        return ProviderUser(
            username=username,
            display_name="",
            email="",
        )

    def context_key(self) -> str:
        return self._workspace() or "default"

    def current_repository(self) -> Optional[RepositoryRef]:
        active_repo = self.config.get_active_repository() or {}
        provider = (active_repo.get("provider") or "").strip().lower()
        if provider == "bitbucket" and active_repo.get("owner") and active_repo.get("slug"):
            workspace = active_repo.get("owner") or ""
            slug = active_repo.get("slug") or ""
            full_name = active_repo.get("full_name") or f"{workspace}/{slug}"
            return RepositoryRef(
                provider="bitbucket",
                workspace=workspace,
                slug=slug,
                display_name=full_name,
                full_name=full_name,
                web_url=active_repo.get("html_url") or f"https://bitbucket.org/{workspace}/{slug}",
            )

        workspace = self._workspace()
        slug = (self.config.get_repo_slug() or "").strip()
        if not workspace or not slug:
            return None
        full_name = f"{workspace}/{slug}"
        return RepositoryRef(
            provider="bitbucket",
            workspace=workspace,
            slug=slug,
            display_name=full_name,
            full_name=full_name,
            web_url=f"https://bitbucket.org/{workspace}/{slug}",
        )

    def list_repositories(self, cancel_check: CancelCheck = None) -> list[RepositoryRef]:
        username, password = self._auth()
        workspace = self._workspace()
        if not workspace:
            raise ValueError("Bitbucket workspace is required.")

        repositories: list[RepositoryRef] = []
        next_url = f"https://api.bitbucket.org/2.0/repositories/{workspace}?pagelen=100"

        while next_url:
            if _should_cancel(cancel_check):
                break
            try:
                data = _get_bitbucket_page_with_resume(next_url, auth=(username, password), timeout=20)
            except Exception as exc:  # noqa: BLE001
                if repositories and _is_rate_limited_exception(exc):
                    break
                raise
            for repo in data.get("values", []):
                slug = repo.get("slug") or ""
                full_name = repo.get("full_name") or f"{workspace}/{slug}"
                repositories.append(
                    RepositoryRef(
                        provider="bitbucket",
                        workspace=workspace,
                        slug=slug,
                        display_name=full_name,
                        full_name=full_name,
                        web_url=((repo.get("links") or {}).get("html") or {}).get("href", ""),
                    )
                )
            next_url = data.get("next")

        return repositories

    def list_merged_pull_requests(
        self,
        repository: RepositoryRef,
        developer: str,
        start_date: Optional[date],
        end_date: Optional[date],
        search_text: str = "",
        branch_filter: str = "",
        exclude_bots: bool = True,
        cancel_check: CancelCheck = None,
    ) -> list[dict]:
        username, password = self._auth()
        next_url = (
            f"https://api.bitbucket.org/2.0/repositories/"
            f"{repository.workspace}/{repository.slug}/pullrequests?state=MERGED&pagelen=50"
        )
        records: list[dict] = []

        while next_url:
            if _should_cancel(cancel_check):
                break
            try:
                data = _get_bitbucket_page_with_resume(next_url, auth=(username, password), timeout=20)
            except Exception as exc:  # noqa: BLE001
                if records and _is_rate_limited_exception(exc):
                    break
                raise
            for pr in data.get("values", []):
                author_obj = pr.get("author") or {}
                author = (author_obj.get("display_name")) or ""
                username_value = (author_obj.get("username")) or ""
                nickname_value = (author_obj.get("nickname")) or ""
                account_id_value = (author_obj.get("account_id")) or ""
                summary = (pr.get("summary") or {}).get("raw") or pr.get("description") or ""
                source_branch = ((pr.get("source") or {}).get("branch") or {}).get("name") or ""
                destination_branch = ((pr.get("destination") or {}).get("branch") or {}).get("name") or ""
                merged_on = pr.get("updated_on")
                if self._exclude_bot(author or nickname_value or username_value, exclude_bots):
                    continue
                if not self._matches_developer(
                    author,
                    username_value,
                    nickname_value,
                    account_id_value,
                    developer=developer,
                ):
                    continue
                if not self._matches_search(pr.get("title") or "", summary, search_text=search_text):
                    continue
                if not self._matches_branch(branch_filter, source_branch, destination_branch):
                    continue
                if not self._is_date_in_range(merged_on, start_date, end_date):
                    continue
                records.append(pr)
            next_url = data.get("next")
        return records

    def list_pull_request_commits(
        self,
        repository: RepositoryRef,
        pr_record: dict,
        cancel_check: CancelCheck = None,
    ) -> set[str]:
        username, password = self._auth()
        pr_id = pr_record.get("id")
        if not pr_id:
            return set()
        next_url = (
            f"https://api.bitbucket.org/2.0/repositories/"
            f"{repository.workspace}/{repository.slug}/pullrequests/{pr_id}/commits?pagelen=100"
        )
        commit_hashes: set[str] = set()
        while next_url:
            if _should_cancel(cancel_check):
                break
            try:
                data = _get_bitbucket_page_with_resume(next_url, auth=(username, password), timeout=20)
            except Exception as exc:  # noqa: BLE001
                if commit_hashes and _is_rate_limited_exception(exc):
                    break
                raise
            for commit in data.get("values", []):
                hash_value = commit.get("hash")
                if hash_value:
                    commit_hashes.add(hash_value.lower())
            next_url = data.get("next")
        return commit_hashes

    def list_commits(
        self,
        repository: RepositoryRef,
        developer: str,
        start_date: Optional[date],
        end_date: Optional[date],
        search_text: str = "",
        branch_filter: str = "",
        exclude_bots: bool = True,
        cancel_check: CancelCheck = None,
    ) -> list[dict]:
        username, password = self._auth()
        next_url = (
            f"https://api.bitbucket.org/2.0/repositories/"
            f"{repository.workspace}/{repository.slug}/commits?pagelen=100"
        )
        records: list[dict] = []
        while next_url:
            if _should_cancel(cancel_check):
                break
            try:
                data = _get_bitbucket_page_with_resume(next_url, auth=(username, password), timeout=20)
            except Exception as exc:  # noqa: BLE001
                if records and _is_rate_limited_exception(exc):
                    break
                raise
            for commit in data.get("values", []):
                author_user = (((commit.get("author") or {}).get("user")) or {})
                author_display = author_user.get("display_name") or ""
                author_nickname = author_user.get("nickname") or ""
                author_account_id = author_user.get("account_id") or ""
                raw_author = ((commit.get("author") or {}).get("raw")) or ""
                if self._exclude_bot(author_display or author_nickname or raw_author, exclude_bots):
                    continue
                if not self._matches_developer(
                    author_display,
                    author_nickname,
                    author_account_id,
                    raw_author,
                    developer=developer,
                ):
                    continue
                if not self._matches_search(commit.get("message") or "", search_text=search_text):
                    continue
                if branch_filter:
                    branch_name = commit.get("branch") or ""
                    if not self._matches_branch(branch_filter, branch_name):
                        continue
                if not self._is_date_in_range(commit.get("date"), start_date, end_date):
                    continue
                records.append(commit)
            next_url = data.get("next")
        return records

    def list_developer_candidates(
        self,
        repository: RepositoryRef,
        limit: int = 50,
        cancel_check: CancelCheck = None,
    ) -> list[str]:
        username, password = self._auth()
        seen: set[str] = set()
        candidates: list[str] = []

        # Keep suggestions responsive: sample recent open PRs first, then recent
        # merged PRs. Full history scans belong to contribution queries.
        for state in ("OPEN", "MERGED"):
            next_url = (
                f"https://api.bitbucket.org/2.0/repositories/"
                f"{repository.workspace}/{repository.slug}/pullrequests"
                f"?state={state}&pagelen=50&sort=-updated_on"
            )
            pages_read = 0
            while next_url and len(candidates) < limit and pages_read < 1:
                if _should_cancel(cancel_check):
                    break
                try:
                    data = _get_bitbucket_page_with_resume(next_url, auth=(username, password), timeout=20)
                except Exception as exc:  # noqa: BLE001
                    if candidates and _is_rate_limited_exception(exc):
                        break
                    raise
                pages_read += 1
                for pr in data.get("values", []):
                    author = pr.get("author") or {}
                    for value in (
                        author.get("display_name") or "",
                        author.get("username") or "",
                        author.get("nickname") or "",
                    ):
                        item = (value or "").strip()
                        key = item.lower()
                        if not item or key in seen:
                            continue
                        seen.add(key)
                        candidates.append(item)
                        if len(candidates) >= limit:
                            break
                    if len(candidates) >= limit:
                        break
                next_url = data.get("next")
            if len(candidates) >= limit or _should_cancel(cancel_check):
                break
        return candidates


class GitHubProviderClient(ProviderClient):
    provider_name = "github"

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        token = (self.config.get_github_token() or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _owner(self) -> str:
        return (self.config.get_github_owner() or "").strip()

    def validate_credentials(self) -> ProviderUser:
        headers = self._headers()
        response = requests.get("https://api.github.com/user", headers=headers, timeout=20)
        if response.status_code == 401:
            raise ValueError("GitHub token is required to query contribution history.")
        response.raise_for_status()
        payload = response.json()
        return ProviderUser(
            username=payload.get("login") or self._owner(),
            display_name=payload.get("name") or "",
            email=payload.get("email") or "",
        )

    def context_key(self) -> str:
        return self._owner() or "default"

    def current_repository(self) -> Optional[RepositoryRef]:
        active_repo = self.config.get_active_repository() or {}
        provider = (active_repo.get("provider") or "").strip().lower()
        if provider == "github" and active_repo.get("owner") and active_repo.get("slug"):
            owner = active_repo.get("owner") or ""
            repo = active_repo.get("slug") or ""
            full_name = active_repo.get("full_name") or f"{owner}/{repo}"
            return RepositoryRef(
                provider="github",
                workspace=owner,
                slug=repo,
                display_name=full_name,
                full_name=full_name,
                web_url=active_repo.get("html_url") or f"https://github.com/{owner}/{repo}",
            )

        owner = self._owner()
        repo = (self.config.get_github_repo() or "").strip()
        if not owner or not repo:
            return None
        full_name = f"{owner}/{repo}"
        return RepositoryRef(
            provider="github",
            workspace=owner,
            slug=repo,
            display_name=full_name,
            full_name=full_name,
            web_url=f"https://github.com/{owner}/{repo}",
        )

    def list_repositories(self, cancel_check: CancelCheck = None) -> list[RepositoryRef]:
        owner = self._owner()
        if not owner:
            raise ValueError("GitHub owner/org is required.")
        headers = self._headers()
        page = 1
        repositories: list[RepositoryRef] = []
        request_urls = [
            f"https://api.github.com/orgs/{owner}/repos",
            f"https://api.github.com/users/{owner}/repos",
        ]
        seen_full_names: set[str] = set()
        for request_url in request_urls:
            page = 1
            while True:
                if _should_cancel(cancel_check):
                    break
                response = requests.get(
                    request_url,
                    params={"per_page": 100, "page": page, "sort": "updated"},
                    headers=headers,
                    timeout=20,
                )
                if response.status_code == 404:
                    break
                response.raise_for_status()
                values = response.json()
                if not values:
                    break
                for repo in values:
                    full_name = repo.get("full_name") or f"{owner}/{repo.get('name') or ''}"
                    if full_name.lower() in seen_full_names:
                        continue
                    seen_full_names.add(full_name.lower())
                    repositories.append(
                        RepositoryRef(
                            provider="github",
                            workspace=owner,
                            slug=repo.get("name") or "",
                            display_name=full_name,
                            full_name=full_name,
                            web_url=repo.get("html_url") or "",
                        )
                    )
                page += 1
        return repositories

    def list_merged_pull_requests(
        self,
        repository: RepositoryRef,
        developer: str,
        start_date: Optional[date],
        end_date: Optional[date],
        search_text: str = "",
        branch_filter: str = "",
        exclude_bots: bool = True,
        cancel_check: CancelCheck = None,
    ) -> list[dict]:
        headers = self._headers()
        page = 1
        records: list[dict] = []
        while True:
            if _should_cancel(cancel_check):
                break
            values = _get_json_with_retry(
                f"https://api.github.com/repos/{repository.workspace}/{repository.slug}/pulls",
                params={"state": "closed", "per_page": 100, "page": page, "sort": "updated", "direction": "desc"},
                headers=headers,
                timeout=20,
            )
            if not values:
                break
            for pr in values:
                author = ((pr.get("user") or {}).get("login")) or ""
                if self._exclude_bot(author, exclude_bots):
                    continue
                if not pr.get("merged_at"):
                    continue
                if not self._matches_developer(author, developer=developer):
                    continue
                if not self._matches_search(pr.get("title") or "", pr.get("body") or "", search_text=search_text):
                    continue
                if not self._matches_branch(
                    branch_filter,
                    (pr.get("head") or {}).get("ref") or "",
                    (pr.get("base") or {}).get("ref") or "",
                ):
                    continue
                if not self._is_date_in_range(pr.get("merged_at"), start_date, end_date):
                    continue
                records.append(pr)
            page += 1
        return records

    def list_pull_request_commits(
        self,
        repository: RepositoryRef,
        pr_record: dict,
        cancel_check: CancelCheck = None,
    ) -> set[str]:
        headers = self._headers()
        number = pr_record.get("number")
        if not number:
            return set()
        page = 1
        hashes: set[str] = set()
        while True:
            if _should_cancel(cancel_check):
                break
            values = _get_json_with_retry(
                f"https://api.github.com/repos/{repository.workspace}/{repository.slug}/pulls/{number}/commits",
                params={"per_page": 100, "page": page},
                headers=headers,
                timeout=20,
            )
            if not values:
                break
            for commit in values:
                sha = commit.get("sha")
                if sha:
                    hashes.add(sha.lower())
            page += 1
        return hashes

    def list_commits(
        self,
        repository: RepositoryRef,
        developer: str,
        start_date: Optional[date],
        end_date: Optional[date],
        search_text: str = "",
        branch_filter: str = "",
        exclude_bots: bool = True,
        cancel_check: CancelCheck = None,
    ) -> list[dict]:
        headers = self._headers()
        page = 1
        records: list[dict] = []
        params = {"per_page": 100, "page": page}
        if branch_filter:
            params["sha"] = branch_filter
        if start_date:
            params["since"] = f"{start_date.isoformat()}T00:00:00Z"
        if end_date:
            params["until"] = f"{end_date.isoformat()}T23:59:59Z"

        while True:
            if _should_cancel(cancel_check):
                break
            params["page"] = page
            values = _get_json_with_retry(
                f"https://api.github.com/repos/{repository.workspace}/{repository.slug}/commits",
                params=params,
                headers=headers,
                timeout=20,
            )
            if not values:
                break
            for commit in values:
                inner_commit = commit.get("commit") or {}
                author_obj = inner_commit.get("author") or {}
                author_login = ((commit.get("author") or {}).get("login")) or ""
                author_email = author_obj.get("email") or ""
                author_name = author_obj.get("name") or author_login
                if self._exclude_bot(author_login or author_name, exclude_bots):
                    continue
                if not self._matches_developer(author_login, author_name, author_email, developer=developer):
                    continue
                if not self._matches_search(inner_commit.get("message") or "", search_text=search_text):
                    continue
                commit_date = author_obj.get("date")
                if not self._is_date_in_range(commit_date, start_date, end_date):
                    continue
                records.append(commit)
            page += 1
        return records

    def list_developer_candidates(
        self,
        repository: RepositoryRef,
        limit: int = 50,
        cancel_check: CancelCheck = None,
    ) -> list[str]:
        headers = self._headers()
        seen: set[str] = set()
        candidates: list[str] = []

        for state in ("open", "closed"):
            page = 1
            while len(candidates) < limit and page <= 1:
                if _should_cancel(cancel_check):
                    break
                values = _get_json_with_retry(
                    f"https://api.github.com/repos/{repository.workspace}/{repository.slug}/pulls",
                    params={"state": state, "per_page": 100, "page": page, "sort": "updated", "direction": "desc"},
                    headers=headers,
                    timeout=20,
                )
                if not values:
                    break
                for pr in values:
                    login = ((pr.get("user") or {}).get("login")) or ""
                    item = login.strip()
                    key = item.lower()
                    if not item or key in seen:
                        continue
                    seen.add(key)
                    candidates.append(item)
                    if len(candidates) >= limit:
                        break
                page += 1
            if len(candidates) >= limit or _should_cancel(cancel_check):
                break
        return candidates


def build_provider_client(config: ConfigManager) -> ProviderClient:
    provider = (config.get_provider() or "bitbucket").lower()
    if provider == "github":
        return GitHubProviderClient(config)
    return BitbucketProviderClient(config)
