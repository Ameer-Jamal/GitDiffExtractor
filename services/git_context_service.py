from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GitRepositoryContext:
    repo_dir: str
    provider: str
    owner: str
    slug: str
    remote_name: str
    remote_url: str
    current_branch: str
    upstream_branch: str
    default_branch: str
    source_branch_exists: bool | None = None
    target_branch_exists: bool | None = None

    def repository_dict(self) -> dict[str, str]:
        full_name = f"{self.owner}/{self.slug}".strip("/")
        html_url = ""
        clone_url = self.remote_url
        if self.provider == "github" and full_name:
            html_url = f"https://github.com/{full_name}"
            clone_url = f"https://github.com/{full_name}.git"
        elif self.provider == "bitbucket" and full_name:
            html_url = f"https://bitbucket.org/{full_name}"
            clone_url = f"https://bitbucket.org/{full_name}.git"
        return {
            "provider": self.provider,
            "id": full_name,
            "name": self.slug,
            "owner": self.owner,
            "slug": self.slug,
            "full_name": full_name,
            "clone_url": clone_url,
            "html_url": html_url,
            "local_dir": self.repo_dir,
            "default_branch": self.default_branch,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_dir": self.repo_dir,
            "provider": self.provider,
            "owner": self.owner,
            "slug": self.slug,
            "remote_name": self.remote_name,
            "remote_url": self.remote_url,
            "current_branch": self.current_branch,
            "upstream_branch": self.upstream_branch,
            "default_branch": self.default_branch,
            "source_branch_exists": self.source_branch_exists,
            "target_branch_exists": self.target_branch_exists,
            "repository": self.repository_dict(),
        }


class GitContextService:
    def resolve(self, repo_dir: str = "", source_branch: str = "", target_branch: str = "") -> GitRepositoryContext:
        root = self._git_root(repo_dir)
        remote_name = "origin"
        remote_url = self._git(["remote", "get-url", remote_name], root)
        provider, owner, slug = self.parse_remote_url(remote_url)
        current_branch = self._git(["branch", "--show-current"], root, check=False).strip()
        upstream_branch = self._git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root, check=False).strip()
        default_branch = self._default_branch(root, remote_name)

        source_exists = self._remote_branch_exists(root, remote_name, source_branch) if source_branch else None
        target_exists = self._remote_branch_exists(root, remote_name, target_branch) if target_branch else None

        return GitRepositoryContext(
            repo_dir=str(root),
            provider=provider,
            owner=owner,
            slug=slug,
            remote_name=remote_name,
            remote_url=remote_url,
            current_branch=current_branch,
            upstream_branch=upstream_branch,
            default_branch=default_branch,
            source_branch_exists=source_exists,
            target_branch_exists=target_exists,
        )

    @staticmethod
    def parse_remote_url(remote_url: str) -> tuple[str, str, str]:
        text = (remote_url or "").strip()
        patterns = [
            (r"github\.com[:/]([^/]+)/([^/.]+)(?:\.git)?$", "github"),
            (r"bitbucket\.org[:/]([^/]+)/([^/.]+)(?:\.git)?$", "bitbucket"),
        ]
        for pattern, provider in patterns:
            match = re.search(pattern, text)
            if match:
                return provider, match.group(1), match.group(2)
        raise ValueError(f"Unsupported Git remote URL for repository context: {remote_url}")

    def _git_root(self, repo_dir: str) -> Path:
        cwd = Path(repo_dir or os.getcwd()).expanduser().resolve()
        output = self._git(["rev-parse", "--show-toplevel"], cwd)
        return Path(output).resolve()

    def _default_branch(self, repo_dir: Path, remote_name: str) -> str:
        ref = self._git(["symbolic-ref", f"refs/remotes/{remote_name}/HEAD"], repo_dir, check=False).strip()
        prefix = f"refs/remotes/{remote_name}/"
        if ref.startswith(prefix):
            return ref[len(prefix):]
        for candidate in ("main", "master"):
            if self._remote_branch_exists(repo_dir, remote_name, candidate):
                return candidate
        return ""

    def _remote_branch_exists(self, repo_dir: Path, remote_name: str, branch_name: str) -> bool:
        branch = (branch_name or "").strip().replace("origin/", "", 1)
        if not branch:
            return False
        output = self._git(["ls-remote", "--heads", remote_name, branch], repo_dir, check=False)
        return bool(output.strip())

    @staticmethod
    def _git(args: list[str], cwd: Path, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            raise ValueError(details or f"git {' '.join(args)} failed")
        return (result.stdout or "").strip()
