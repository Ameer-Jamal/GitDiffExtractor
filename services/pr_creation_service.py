from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ConfigManager import ConfigManager
from models.contribution_models import RepositoryRef
from services.provider_api import build_provider_client_for_name


@dataclass(frozen=True)
class PullRequestCreateRequest:
    title: str
    source_branch: str
    target_branch: str
    description: str = ""
    draft: bool = False


@dataclass(frozen=True)
class PullRequestUpdateRequest:
    pr_id: str | int
    title: Optional[str] = None
    description: Optional[str] = None
    target_branch: Optional[str] = None


class PullRequestCreationService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def create_pull_request(self, repo: dict, request: PullRequestCreateRequest) -> dict[str, Any]:
        provider_name = (repo.get("provider") or self.config.get_provider() or "bitbucket").lower()
        title = request.title.strip()
        source_branch = request.source_branch.strip().replace("origin/", "", 1)
        target_branch = request.target_branch.strip().replace("origin/", "", 1)
        description = request.description.strip()
        warnings: list[str] = []

        if not title:
            raise ValueError("Pull request title is required.")
        if not source_branch or not target_branch:
            raise ValueError("Source and target branches are required.")

        repo_ref = RepositoryRef.from_dict(repo)
        provider = build_provider_client_for_name(provider_name, self.config)
        try:
            provider.validate_credentials()
        except ValueError as exc:
            if provider_name == "github" and "token" in str(exc).lower():
                raise ValueError(
                    "GitHub token is required to create pull requests. "
                    "Set REPOLENS_GITHUB_TOKEN for the MCP server or save a token in RepoLens Settings."
                ) from exc
            if provider_name == "bitbucket" and any(
                term in str(exc).lower() for term in ("token", "password", "username", "email")
            ):
                raise ValueError(
                    "Atlassian account email and Bitbucket API token are required to create pull requests. "
                    "Set REPOLENS_BITBUCKET_USERNAME and REPOLENS_BITBUCKET_API_TOKEN for the MCP server "
                    "or save credentials in RepoLens Settings."
                ) from exc
            raise

        if not provider.branch_exists(repo_ref, source_branch):
            raise ValueError(f"Remote source branch '{source_branch}' does not exist.")
        if not provider.branch_exists(repo_ref, target_branch):
            raise ValueError(f"Remote target branch '{target_branch}' does not exist.")

        payload = provider.create_pull_request(
            repo_ref,
            title=title,
            description=description,
            source_branch=source_branch,
            target_branch=target_branch,
            draft=request.draft,
        )
        draft_created = bool(payload.get("draft"))
        if request.draft and not draft_created:
            warnings.append("Provider did not report the created pull request as draft.")

        url = ""
        links = payload.get("links") or {}
        if isinstance(links, dict):
            html_link = links.get("html") or {}
            if isinstance(html_link, dict):
                url = html_link.get("href") or ""
        if not url:
            url = payload.get("html_url") or ""

        return {
            "repository": {
                "provider": provider_name,
                "owner": repo.get("owner", ""),
                "slug": repo.get("slug") or repo.get("name") or "",
                "full_name": repo.get("full_name") or "",
            },
            "pr_id": payload.get("id") or payload.get("number") or "",
            "number": payload.get("number") or payload.get("id") or "",
            "title": payload.get("title") or title,
            "url": url,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "state": payload.get("state") or ("OPEN" if not draft_created else "DRAFT"),
            "draft": draft_created,
            "warnings": warnings,
        }

    def update_pull_request(self, repo: dict, request: PullRequestUpdateRequest) -> dict[str, Any]:
        provider_name = (repo.get("provider") or self.config.get_provider() or "bitbucket").lower()
        repo_ref = RepositoryRef.from_dict(repo)
        provider = build_provider_client_for_name(provider_name, self.config)

        # Validate target branch if provided
        if request.target_branch:
            target_branch = request.target_branch.strip().replace("origin/", "", 1)
            if not provider.branch_exists(repo_ref, target_branch):
                raise ValueError(f"Remote target branch '{target_branch}' does not exist.")
        else:
            target_branch = None

        payload = provider.update_pull_request(
            repo_ref,
            request.pr_id,
            title=request.title.strip() if request.title is not None else None,
            description=request.description.strip() if request.description is not None else None,
            target_branch=target_branch,
        )

        url = ""
        links = payload.get("links") or {}
        if isinstance(links, dict):
            html_link = links.get("html") or {}
            if isinstance(html_link, dict):
                url = html_link.get("href") or ""
        if not url:
            url = payload.get("html_url") or ""

        return {
            "repository": {
                "provider": provider_name,
                "owner": repo.get("owner", ""),
                "slug": repo.get("slug") or repo.get("name") or "",
                "full_name": repo.get("full_name") or "",
            },
            "pr_id": payload.get("id") or payload.get("number") or "",
            "number": payload.get("number") or payload.get("id") or "",
            "title": payload.get("title") or (request.title if request.title is not None else ""),
            "url": url,
            "target_branch": payload.get("destination", {}).get("branch", {}).get("name") or payload.get("base", {}).get("ref") or (request.target_branch if request.target_branch is not None else ""),
            "state": (payload.get("state") or "OPEN").upper(),
        }
