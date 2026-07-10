import os
import re
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit, urlunsplit

import requests


class RepositoryProviderError(Exception):
    pass


class ProviderAdapter(ABC):
    name: str

    @abstractmethod
    def validate_config(self, config) -> Tuple[bool, str, Optional[dict]]:
        raise NotImplementedError

    @abstractmethod
    def context_key(self, provider_config: dict) -> str:
        raise NotImplementedError

    @abstractmethod
    def discover(self, provider_config: dict) -> List[dict]:
        raise NotImplementedError

    @abstractmethod
    def authenticated_clone_url(self, clone_url: str, config) -> str:
        raise NotImplementedError


class BitbucketProvider(ProviderAdapter):
    name = "bitbucket"

    def validate_config(self, config) -> Tuple[bool, str, Optional[dict]]:
        username = (config.get_bitbucket_username() or "").strip()
        password = (config.get_bitbucket_api_token() or "").strip()
        workspace = (config.get_bitbucket_workspace() or "").strip()

        if not username or not password:
            return False, "Atlassian account email and Bitbucket API token are required.", None
        if not workspace:
            return False, "Bitbucket workspace is required.", None

        return True, "", {
            "username": username,
            "password": password,
            "workspace": workspace,
        }

    def context_key(self, provider_config: dict) -> str:
        return (provider_config.get("workspace") or "").strip().lower()

    def discover(self, provider_config: dict) -> List[dict]:
        workspace = provider_config["workspace"]
        username = provider_config["username"]
        password = provider_config["password"]

        repos: List[dict] = []
        next_url = f"https://api.bitbucket.org/2.0/repositories/{workspace}?pagelen=100"

        while next_url:
            response = requests.get(next_url, auth=(username, password), timeout=20)
            response.raise_for_status()
            payload = response.json()

            for item in payload.get("values", []):
                slug = item.get("slug") or ""
                owner = ((item.get("workspace") or {}).get("slug") or workspace)
                links = item.get("links") or {}
                clone_links = links.get("clone") or []

                https_clone = ""
                for link in clone_links:
                    if link.get("name") == "https":
                        https_clone = link.get("href") or ""
                        break

                repos.append(
                    {
                        "provider": self.name,
                        "id": item.get("uuid") or slug,
                        "name": item.get("name") or slug,
                        "owner": owner,
                        "slug": slug,
                        "full_name": item.get("full_name") or f"{owner}/{slug}",
                        "clone_url": https_clone,
                        "html_url": ((links.get("html") or {}).get("href") or ""),
                        "default_branch": (((item.get("mainbranch") or {}).get("name")) or ""),
                    }
                )

            next_url = payload.get("next")

        repos.sort(key=lambda x: (x.get("owner", ""), x.get("slug", "")))
        return repos

    def authenticated_clone_url(self, clone_url: str, config) -> str:
        password = (config.get_bitbucket_api_token() or "").strip()
        # Bitbucket API tokens use an Atlassian email for REST authentication,
        # but Git-over-HTTPS requires a Bitbucket username. Its documented
        # x-bitbucket-api-token-auth alias avoids asking users for both IDs.
        return RepositoryProvider._inject_basic_auth(
            clone_url, "x-bitbucket-api-token-auth", password
        )


class GitHubProvider(ProviderAdapter):
    name = "github"

    def validate_config(self, config) -> Tuple[bool, str, Optional[dict]]:
        token = (config.get_github_token() or "").strip()
        owner = (config.get_github_owner() or "").strip()

        if not token:
            return False, "GitHub token is required for repository discovery.", None

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"token {token}",
        }
        return True, "", {
            "token": token,
            "owner": owner,
            "headers": headers,
        }

    def context_key(self, provider_config: dict) -> str:
        return (provider_config.get("owner") or "*").strip().lower()

    def discover(self, provider_config: dict) -> List[dict]:
        owner_filter = (provider_config.get("owner") or "").strip().lower()
        headers = provider_config["headers"]

        repos: List[dict] = []
        next_url = "https://api.github.com/user/repos?per_page=100&affiliation=owner,collaborator,organization_member"

        while next_url:
            response = requests.get(next_url, headers=headers, timeout=20)
            response.raise_for_status()
            payload = response.json()

            for item in payload:
                owner = ((item.get("owner") or {}).get("login") or "")
                if owner_filter and owner.lower() != owner_filter:
                    continue

                repos.append(
                    {
                        "provider": self.name,
                        "id": str(item.get("id") or ""),
                        "name": item.get("name") or "",
                        "owner": owner,
                        "slug": item.get("name") or "",
                        "full_name": item.get("full_name") or f"{owner}/{item.get('name', '')}",
                        "clone_url": item.get("clone_url") or "",
                        "html_url": item.get("html_url") or "",
                        "default_branch": item.get("default_branch") or "",
                    }
                )

            next_url = RepositoryProvider._parse_next_link(response.headers.get("Link"))

        repos.sort(key=lambda x: (x.get("owner", ""), x.get("slug", "")))
        return repos

    def authenticated_clone_url(self, clone_url: str, config) -> str:
        token = (config.get_github_token() or "").strip()
        return RepositoryProvider._inject_token_auth(clone_url, token)


class RepositoryProvider:
    _adapters = {
        "bitbucket": BitbucketProvider(),
        "github": GitHubProvider(),
    }

    @classmethod
    def _adapter(cls, provider: str) -> ProviderAdapter:
        adapter = cls._adapters.get((provider or "").lower())
        if not adapter:
            raise RepositoryProviderError(f"Unsupported provider: {provider}")
        return adapter

    @classmethod
    def validate_provider_config(cls, provider: str, config) -> Tuple[bool, str, Optional[dict]]:
        try:
            return cls._adapter(provider).validate_config(config)
        except RepositoryProviderError as exc:
            return False, str(exc), None

    @classmethod
    def discovery_context_key(cls, provider: str, provider_config: dict) -> str:
        return cls._adapter(provider).context_key(provider_config or {})

    @classmethod
    def discover_repositories(cls, provider: str, provider_config: dict) -> List[dict]:
        return cls._adapter(provider).discover(provider_config or {})

    @classmethod
    def ensure_local_checkout(cls, repo: dict, config) -> str:
        clone_url = (repo.get("clone_url") or "").strip()
        if not clone_url:
            raise RepositoryProviderError("Selected repository is missing a clone URL.")

        provider = (repo.get("provider") or "").lower()
        adapter = cls._adapter(provider)

        owner = cls._safe_name(repo.get("owner") or "unknown")
        slug = cls._safe_name(repo.get("slug") or repo.get("name") or "repo")

        base_root = config.get_managed_repo_root()
        local_dir = os.path.join(base_root, provider, owner, slug)
        os.makedirs(os.path.dirname(local_dir), exist_ok=True)

        if not os.path.exists(local_dir):
            clone_target = adapter.authenticated_clone_url(clone_url, config)
            cls._run_git(["git", "clone", clone_target, local_dir])
            # Never persist a token in .git/config after cloning.
            cls._run_git(["git", "remote", "set-url", "origin", cls._strip_userinfo(clone_url)], cwd=local_dir)
        else:
            cls._update_existing_checkout(local_dir, clone_url, adapter, config)

        return local_dir

    @classmethod
    def ensure_local_checkouts(cls, repos: List[dict], config) -> List[dict]:
        prepared = []
        for repo in repos:
            repo_copy = dict(repo)
            repo_copy["local_dir"] = cls.ensure_local_checkout(repo_copy, config)
            prepared.append(repo_copy)
        return prepared

    @classmethod
    def _update_existing_checkout(cls, local_dir: str, clone_url: str = "", adapter: Optional[ProviderAdapter] = None, config=None) -> None:
        # Existing checkouts may contain an expired credential. Temporarily set
        # the current API-token URL for network operations, then restore a clean
        # credential-free origin even when fetch fails.
        clean_url = cls._strip_userinfo(clone_url) if clone_url else ""
        authenticated_url = adapter.authenticated_clone_url(clean_url, config) if adapter and config and clean_url else ""
        if authenticated_url:
            cls._run_git(["git", "remote", "set-url", "origin", authenticated_url], cwd=local_dir)
        try:
            cls._run_git(["git", "fetch", "--all", "--prune"], cwd=local_dir)
        except RepositoryProviderError as exc:
            if not cls._is_stale_remote_ref_error(str(exc)):
                raise
            first_error = exc
            recovery_steps = (
                lambda: cls._remove_stale_remote_tracking_refs(local_dir, "origin"),
                ["git", "remote", "prune", "origin"],
                ["git", "fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*"],
            )
            for step in recovery_steps:
                try:
                    if callable(step):
                        step()
                    else:
                        cls._run_git(step, cwd=local_dir)
                except RepositoryProviderError as recovery_exc:
                    raise RepositoryProviderError(
                        f"{first_error}\n\nAutomatic stale remote-ref recovery failed: {recovery_exc}"
                    ) from recovery_exc
        finally:
            if authenticated_url:
                cls._run_git(["git", "remote", "set-url", "origin", clean_url], cwd=local_dir)

    @classmethod
    def _remove_stale_remote_tracking_refs(cls, local_dir: str, remote: str) -> None:
        remote_output = cls._run_git_output(["git", "ls-remote", "--heads", remote], cwd=local_dir)
        remote_refs = {
            line.split("\t", 1)[1].replace("refs/heads/", f"refs/remotes/{remote}/", 1)
            for line in remote_output.splitlines()
            if "\trefs/heads/" in line
        }

        local_output = cls._run_git_output(
            ["git", "for-each-ref", f"refs/remotes/{remote}", "--format=%(refname)"],
            cwd=local_dir,
        )
        stale_refs = [
            ref.strip()
            for ref in local_output.splitlines()
            if ref.strip() and ref.strip() not in remote_refs and not ref.strip().endswith("/HEAD")
        ]

        for ref in stale_refs:
            cls._run_git(["git", "update-ref", "-d", ref], cwd=local_dir)

    @staticmethod
    def _is_stale_remote_ref_error(message: str) -> bool:
        text = (message or "").lower()
        return (
            "incorrect old value" in text
            or "cannot lock ref" in text
            or "is at" in text and "but expected" in text
        )

    @staticmethod
    def _parse_next_link(link_header: Optional[str]) -> Optional[str]:
        if not link_header:
            return None

        parts = link_header.split(",")
        for part in parts:
            section = part.strip().split(";")
            if len(section) < 2:
                continue
            url_part = section[0].strip()
            rel_part = section[1].strip()
            if rel_part == 'rel="next"':
                return url_part.strip("<>")
        return None

    @staticmethod
    def _safe_name(value: str) -> str:
        text = (value or "").strip()
        if not text:
            return "repo"
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
        return cleaned.strip("_") or "repo"

    @staticmethod
    def _inject_basic_auth(url: str, username: str, password: str) -> str:
        if not username or not password:
            return url
        parts = urlsplit(url)
        if not parts.netloc:
            return url

        host = parts.hostname or ""
        if not host:
            return url

        port = f":{parts.port}" if parts.port else ""
        safe_user = quote(username, safe="")
        safe_password = quote(password, safe="")
        netloc = f"{safe_user}:{safe_password}@{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    @staticmethod
    def _strip_userinfo(url: str) -> str:
        parts = urlsplit(url)
        if not parts.netloc:
            return url
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        return urlunsplit((parts.scheme, f"{host}{port}", parts.path, parts.query, parts.fragment))

    @staticmethod
    def _inject_token_auth(url: str, token: str) -> str:
        if not token:
            return url
        parts = urlsplit(url)
        if not parts.netloc:
            return url

        host = parts.hostname or ""
        if not host:
            return url

        port = f":{parts.port}" if parts.port else ""
        safe_token = quote(token, safe="")
        netloc = f"{safe_token}@{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    @staticmethod
    def _run_git(command: List[str], cwd: Optional[str] = None) -> None:
        try:
            subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            details = stderr or stdout or str(exc)
            raise RepositoryProviderError(f"Git command failed: {details}") from exc

    @staticmethod
    def _run_git_output(command: List[str], cwd: Optional[str] = None) -> str:
        try:
            result = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            details = stderr or stdout or str(exc)
            raise RepositoryProviderError(f"Git command failed: {details}") from exc
        return result.stdout
