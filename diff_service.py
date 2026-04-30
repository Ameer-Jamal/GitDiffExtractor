from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PullRequestDiffResult:
    pr_id: str
    title: str
    state: str
    diff_text: str
    merge_base: str
    resolved_source: str
    resolved_destination: str
    source_branch: str = ""
    destination_branch: str = ""
    source_commit: str = ""
    destination_commit: str = ""
    merge_commit: str = ""


@dataclass(frozen=True)
class CommitDiffResult:
    commit_hash: str
    parent_commit: str
    diff_text: str


class DiffService:
    def generate_pr_diff(self, pr: dict, repo_dir: str) -> PullRequestDiffResult:
        pr_id = str(pr.get("id") or "unknown")
        title = pr.get("title") or ""
        state = pr.get("state") or ""
        source_branch = pr.get("source_branch") or ""
        destination_branch = pr.get("destination_branch") or ""

        if self._has_remote(repo_dir, "origin"):
            self._run_git(["git", "fetch", "origin"], cwd=repo_dir)

        resolved_source = self._resolve_commit(repo_dir, pr.get("source_commit"), source_branch)
        resolved_destination = self._resolve_commit(repo_dir, pr.get("destination_commit"), destination_branch)

        if not resolved_source:
            raise RuntimeError(f"Unable to resolve the source commit for PR #{pr_id} ({title}).")
        if not resolved_destination:
            raise RuntimeError(f"Unable to resolve the destination commit for PR #{pr_id} ({title}).")

        merge_base = self._merge_base(repo_dir, resolved_destination, resolved_source) or resolved_destination
        diff_text = self._run_git(
            ["git", "diff", merge_base, resolved_source],
            cwd=repo_dir,
            capture_output=True,
        )

        return PullRequestDiffResult(
            pr_id=pr_id,
            title=title,
            state=state,
            diff_text=diff_text,
            merge_base=merge_base,
            resolved_source=resolved_source,
            resolved_destination=resolved_destination,
            source_branch=source_branch,
            destination_branch=destination_branch,
            source_commit=pr.get("source_commit") or "",
            destination_commit=pr.get("destination_commit") or "",
            merge_commit=pr.get("merge_commit") or "",
        )

    def save_pr_diff(self, pr: dict, repo_dir: str, output_dir: str) -> tuple[str, str]:
        result = self.generate_pr_diff(pr, repo_dir)
        diff_path = self._build_pr_diff_filename(pr, output_dir)
        self._write_text_file(diff_path, result.diff_text)
        return diff_path, result.state

    def generate_commit_diff(self, repo_dir: str, commit_hash: str) -> CommitDiffResult:
        parent_commit = self._parent_commit(repo_dir, commit_hash)
        if not parent_commit:
            raise RuntimeError(f"Commit {commit_hash} has no parents (initial commit).")

        diff_text = self._run_git(
            ["git", "diff", parent_commit, commit_hash],
            cwd=repo_dir,
            capture_output=True,
        )
        return CommitDiffResult(
            commit_hash=commit_hash,
            parent_commit=parent_commit,
            diff_text=diff_text,
        )

    def save_commit_diffs(self, repo_dir: str, commit_hashes: list[str], output_dir: str) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        diff_paths: list[str] = []

        for commit_hash in commit_hashes:
            try:
                result = self.generate_commit_diff(repo_dir, commit_hash)
            except RuntimeError as exc:
                if "has no parents" in str(exc):
                    warnings.append(f"Commit {commit_hash} has no parents (initial commit). Skipped.")
                    continue
                raise

            diff_file_path = os.path.join(output_dir, f"{result.commit_hash}_diff.txt")
            self._write_text_file(diff_file_path, result.diff_text)
            diff_paths.append(diff_file_path)

        if not diff_paths:
            raise RuntimeError("No diff files were generated for the provided commits.")

        return diff_paths, warnings

    def _resolve_commit(self, repo_dir: str, commit_hash: str | None, branch_name: str | None) -> str | None:
        candidates: list[str] = []
        if commit_hash:
            candidates.append(commit_hash)
        if branch_name:
            candidates.append(branch_name)
            if not branch_name.startswith("origin/"):
                candidates.append(f"origin/{branch_name}")

        for candidate in candidates:
            resolved = self._verify_commit(repo_dir, candidate)
            if resolved:
                return resolved

        return None

    def _verify_commit(self, repo_dir: str, identifier: str | None) -> str | None:
        if not identifier:
            return None

        try:
            return self._run_git(
                ["git", "rev-parse", "--verify", f"{identifier}^{{commit}}"],
                cwd=repo_dir,
                capture_output=True,
            ).strip()
        except RuntimeError:
            return None

    def _merge_base(self, repo_dir: str, destination_commit: str, source_commit: str) -> str | None:
        if not destination_commit or not source_commit:
            return None

        try:
            merge_base = self._run_git(
                ["git", "merge-base", destination_commit, source_commit],
                cwd=repo_dir,
                capture_output=True,
            ).strip()
            return merge_base or None
        except RuntimeError:
            return None

    def _parent_commit(self, repo_dir: str, commit_hash: str) -> str | None:
        parents_output = self._run_git(
            ["git", "rev-list", "--parents", "-n", "1", commit_hash],
            cwd=repo_dir,
            capture_output=True,
        )
        parts = parents_output.strip().split()
        if len(parts) <= 1:
            return None
        return parts[1]

    def _has_remote(self, repo_dir: str, remote_name: str) -> bool:
        try:
            self._run_git(
                ["git", "remote", "get-url", remote_name],
                cwd=repo_dir,
                capture_output=True,
            )
            return True
        except RuntimeError:
            return False

    def _build_pr_diff_filename(self, pr: dict, output_dir: str) -> str:
        pr_id = pr.get("id", "unknown")
        state = (pr.get("state") or "unknown").lower()
        safe_title = self._safe_filename(pr.get("title"), fallback="pr")
        filename = f"pr_{pr_id}_{state}_{safe_title}.diff"
        return os.path.join(output_dir, filename)

    @staticmethod
    def _safe_filename(value: str | None, fallback: str = "file") -> str:
        text = (value or "").strip() or fallback
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")
        return (sanitized or fallback)[:60]

    @staticmethod
    def _write_text_file(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    @staticmethod
    def _run_git(command: list[str], cwd: str, capture_output: bool = False) -> str:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            details = stderr or stdout or str(exc)
            if "fetch" in command:
                raise RuntimeError(f"git fetch failed: {details}") from exc
            if "diff" in command:
                raise RuntimeError(f"git diff failed: {details}") from exc
            raise RuntimeError(f"Git command failed: {details}") from exc

        return result.stdout if capture_output else ""
