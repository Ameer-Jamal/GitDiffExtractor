from __future__ import annotations

import base64
import json
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ConfigManager import ConfigManager
from models.contribution_models import RepositoryRef
from services.RepositoryProvider import RepositoryProvider
from services.pr_creation_service import PullRequestCreateRequest, PullRequestCreationService
from services.provider_api import build_provider_client_for_name


@dataclass(frozen=True)
class FileChange:
    path: str
    content: Optional[str] = None
    encoding: str = "utf-8"
    delete: bool = False


@dataclass(frozen=True)
class PullRequestFromChangesRequest:
    title: str
    target_branch: str
    source_branch: str = ""
    description: str = ""
    commit_message: str = ""
    draft: bool = False
    files: tuple[FileChange, ...] = ()
    patch: str = ""


class PullRequestPatchService:
    """Create a branch, apply local changes, push it, and open a pull request."""

    def __init__(
        self,
        config: ConfigManager,
        creation_service: Optional[PullRequestCreationService] = None,
    ):
        self.config = config
        self.creation_service = creation_service or PullRequestCreationService(config)

    @staticmethod
    def parse_changes(changes_json: str) -> tuple[FileChange, ...]:
        text = (changes_json or "").strip()
        if not text:
            return ()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                'changes_json must be a JSON array, for example [{"path": "a.py", "content": "..."}].'
            ) from exc
        if not isinstance(parsed, list):
            raise ValueError(
                'changes_json must be a JSON array, for example [{"path": "a.py", "content": "..."}].'
            )
        changes: list[FileChange] = []
        for item in parsed:
            if not isinstance(item, dict):
                raise ValueError("Each entry in changes_json must be an object with a 'path'.")
            path = str(item.get("path") or "").strip()
            if not path:
                raise ValueError("Each entry in changes_json requires a non-empty 'path'.")
            changes.append(
                FileChange(
                    path=path,
                    content=item.get("content"),
                    encoding=str(item.get("encoding") or "utf-8"),
                    delete=bool(item.get("delete")),
                )
            )
        return tuple(changes)

    def create_pull_request_from_changes(
        self,
        repo: dict,
        request: PullRequestFromChangesRequest,
    ) -> dict[str, Any]:
        title = request.title.strip()
        target_branch = request.target_branch.strip().replace("origin/", "", 1)
        description = request.description.strip()
        patch = request.patch or ""

        if not title:
            raise ValueError("Pull request title is required.")
        if not target_branch:
            raise ValueError("Target branch is required.")
        if not request.files and not patch.strip():
            raise ValueError("Provide at least one file change or a patch.")

        provider_name = (repo.get("provider") or self.config.get_provider() or "bitbucket").lower()
        provider = build_provider_client_for_name(provider_name, self.config)
        provider.validate_credentials()

        repo_ref = RepositoryRef.from_dict(repo)
        if not provider.branch_exists(repo_ref, target_branch):
            raise ValueError(f"Remote target branch '{target_branch}' does not exist.")

        source_branch = request.source_branch.strip().replace("origin/", "", 1)
        if not source_branch:
            source_branch = self._default_source_branch(title)
        if provider.branch_exists(repo_ref, source_branch):
            raise ValueError(
                f"Remote branch '{source_branch}' already exists. "
                "Choose a different source_branch or update the existing pull request."
            )

        local_dir = (repo.get("local_dir") or "").strip()
        if not local_dir:
            local_dir = RepositoryProvider.ensure_local_checkout(repo, self.config)

        self._ensure_clean_working_tree(local_dir)
        original_branch = self._current_branch(local_dir)

        try:
            RepositoryProvider.run_git(
                ["git", "fetch", "origin", target_branch, "--prune"],
                cwd=local_dir,
            )
            RepositoryProvider.run_git(
                ["git", "checkout", "-B", source_branch, f"origin/{target_branch}"],
                cwd=local_dir,
            )
            self._apply_files(Path(local_dir), request.files)
            if patch.strip():
                RepositoryProvider.run_git(
                    ["git", "apply", "--whitespace=nowarn", "-"],
                    cwd=local_dir,
                    input_text=patch,
                )

            RepositoryProvider.run_git(["git", "add", "-A"], cwd=local_dir)
            changed_paths = self._staged_paths(local_dir)
            if not changed_paths:
                raise ValueError("The provided files and patch produced no changes to commit.")

            commit_message = request.commit_message.strip() or title
            RepositoryProvider.run_git(
                ["git", "commit", "-m", commit_message],
                cwd=local_dir,
            )
            RepositoryProvider.push_branch(
                repo,
                self.config,
                local_dir=local_dir,
                branch=source_branch,
            )
        except Exception:
            self._rollback(local_dir, original_branch, source_branch)
            raise

        self._wait_for_remote_branch(provider, repo_ref, source_branch)
        result = self.creation_service.create_pull_request(
            repo,
            PullRequestCreateRequest(
                title=title,
                description=description,
                source_branch=source_branch,
                target_branch=target_branch,
                draft=request.draft,
            ),
        )
        result["commit_message"] = request.commit_message.strip() or title
        result["changed_paths"] = changed_paths
        return result

    @staticmethod
    def _wait_for_remote_branch(provider, repo_ref, branch: str, attempts: int = 5) -> None:
        # Providers can take a moment to expose a freshly pushed branch.
        for attempt in range(attempts):
            if provider.branch_exists(repo_ref, branch):
                return
            if attempt < attempts - 1:
                time.sleep(1.0)
        raise ValueError(
            f"Pushed branch '{branch}' is not visible on the provider yet. "
            "Retry with create_pull_request shortly."
        )

    @staticmethod
    def _default_source_branch(title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:40] or "update"
        return f"repolens/{slug}-{secrets.token_hex(3)}"

    def _apply_files(self, root: Path, files: tuple[FileChange, ...]) -> None:
        for change in files:
            relative = (change.path or "").strip().replace("\\", "/")
            if not relative:
                raise ValueError("Each file change requires a 'path'.")
            target = (root / relative).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"Refusing to write outside the repository: {relative}")

            if change.delete:
                if target.exists():
                    target.unlink()
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            if (change.encoding or "").lower() == "base64":
                target.write_bytes(base64.b64decode(change.content or ""))
            else:
                target.write_text(change.content or "", encoding="utf-8")

    @staticmethod
    def _ensure_clean_working_tree(local_dir: str) -> None:
        status = RepositoryProvider.git_output(["git", "status", "--porcelain"], cwd=local_dir)
        if status.strip():
            raise ValueError(
                "The local checkout has uncommitted changes. Commit or stash them before "
                "creating a pull request from changes."
            )

    @staticmethod
    def _current_branch(local_dir: str) -> str:
        return RepositoryProvider.git_output(["git", "branch", "--show-current"], cwd=local_dir).strip()

    @staticmethod
    def _staged_paths(local_dir: str) -> list[str]:
        output = RepositoryProvider.git_output(["git", "diff", "--cached", "--name-only"], cwd=local_dir)
        return [line.strip() for line in output.splitlines() if line.strip()]

    @staticmethod
    def _rollback(local_dir: str, original_branch: str, source_branch: str) -> None:
        restore = original_branch or "HEAD"
        RepositoryProvider.run_git(["git", "checkout", "-f", restore], cwd=local_dir, check=False)
        RepositoryProvider.run_git(["git", "branch", "-D", source_branch], cwd=local_dir, check=False)
