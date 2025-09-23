import json
import os
import shutil
import tempfile
from typing import Any, Optional

from PyQt5.QtCore import QSettings


class ConfigManager:
    """Central storage for user preferences and per-repository settings."""

    ORG_NAME = "GitDiffExtractor"
    APP_NAME = "GitDiffExtractor"
    LEGACY_CONFIG_FILE = "diff_extractor_default_config.json"
    REPO_CONFIG_FILE = ".git_diff_extractor.json"

    DEFAULT_REPO_CONFIG = {
        "last_repo_dir": "",
        "last_output_dir": "",
        "origin_branch": "",
        "bitbucket_username": "",
        "bitbucket_app_password": "",
        "repo_slug": "",
        "commit_hashes": "",
        "pr_title": "",
        "source_branch": "",
        "target_branch": "",
        "provider": "bitbucket",
        "bitbucket_workspace": "",
        "github_owner": "",
        "github_repo": "",
        "github_token": ""
    }

    def __init__(self):
        self.settings = QSettings(self.ORG_NAME, self.APP_NAME)
        self.current_repo = self.settings.value("last_repo_dir", "", str)
        self.repo_config = dict(self.DEFAULT_REPO_CONFIG)

        # Support migrating values from the legacy JSON file on first run
        self._migrate_legacy_settings()

        if self.current_repo:
            self._load_repo_config(self.current_repo)

    # ------------------------------------------------------------------
    # Internal helpers
    def _migrate_legacy_settings(self) -> None:
        """Import values from the previous JSON configuration if present."""
        if self.settings.value("_legacy_migrated", False, bool):
            return

        if not os.path.exists(self.LEGACY_CONFIG_FILE):
            self.settings.setValue("_legacy_migrated", True)
            return

        try:
            with open(self.LEGACY_CONFIG_FILE, "r") as legacy_file:
                legacy_data = json.load(legacy_file)
        except Exception as exc:  # noqa: BLE001 - best effort migration
            print(f"Error migrating legacy config: {exc}")
            self.settings.setValue("_legacy_migrated", True)
            return

        if isinstance(legacy_data, dict):
            repo_dir = legacy_data.get("last_repo_dir", "")
            output_dir = legacy_data.get("last_output_dir", "")
            self.settings.setValue("last_repo_dir", repo_dir)
            self.settings.setValue("last_output_dir", output_dir)
            self.current_repo = repo_dir

            if repo_dir:
                self.repo_config = dict(self.DEFAULT_REPO_CONFIG)
                for key, value in legacy_data.items():
                    if key in self.repo_config:
                        self.repo_config[key] = value
                self.repo_config["last_repo_dir"] = repo_dir
                self._save_repo_config(repo_dir)

        self.settings.setValue("_legacy_migrated", True)

    def _repo_config_path(self, repo_dir: str) -> str:
        return os.path.join(repo_dir, self.REPO_CONFIG_FILE)

    def _load_repo_config(self, repo_dir: str) -> None:
        """Load per-repository configuration if available."""
        self.repo_config = dict(self.DEFAULT_REPO_CONFIG)

        if not repo_dir:
            return

        config_path = self._repo_config_path(repo_dir)
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as repo_file:
                    data = json.load(repo_file)
                    if isinstance(data, dict):
                        self.repo_config.update({k: data.get(k, v)
                                                 for k, v in self.DEFAULT_REPO_CONFIG.items()})
            except Exception as exc:  # noqa: BLE001 - prefer resilience
                print(f"Error reading repo config '{config_path}': {exc}")
        else:
            # Initialize an empty config for the repository
            self.repo_config["last_repo_dir"] = repo_dir
            self._save_repo_config(repo_dir)

        self.repo_config["last_repo_dir"] = repo_dir

    def _save_repo_config(self, repo_dir: Optional[str] = None) -> None:
        """Persist the current repository configuration to disk."""
        repo_dir = repo_dir or self.current_repo
        if not repo_dir or not os.path.isdir(repo_dir):
            return

        config_path = self._repo_config_path(repo_dir)
        config_dir = os.path.dirname(config_path)

        try:
            if config_dir and not os.path.exists(config_dir):
                os.makedirs(config_dir)

            with tempfile.NamedTemporaryFile("w", delete=False, dir=config_dir or None) as tmp_file:
                json.dump(self.repo_config, tmp_file, indent=4)
                temp_path = tmp_file.name

            shutil.move(temp_path, config_path)
        except Exception as exc:  # noqa: BLE001 - avoid hard failure
            print(f"Error saving repo config '{config_path}': {exc}")

    def _update_repo_value(self, key: str, value: Any) -> None:
        if key in self.repo_config:
            self.repo_config[key] = value
            self._save_repo_config()

    # ------------------------------------------------------------------
    # Global values (stored in QSettings)
    def get_repo_dir(self) -> str:
        return self.settings.value("last_repo_dir", "", str)

    def set_repo_dir(self, repo_dir: str) -> None:
        repo_dir = repo_dir or ""
        self.settings.setValue("last_repo_dir", repo_dir)
        if repo_dir != self.current_repo:
            self.current_repo = repo_dir
            self._load_repo_config(repo_dir)

    def get_output_dir(self) -> str:
        repo_value = self.repo_config.get("last_output_dir", "")
        if repo_value:
            return repo_value
        return self.settings.value("last_output_dir", "", str)

    def set_output_dir(self, output_dir: str) -> None:
        self.settings.setValue("last_output_dir", output_dir)
        self._update_repo_value("last_output_dir", output_dir)

    # ------------------------------------------------------------------
    # Repository specific values
    def get_origin_branch(self) -> str:
        return self.repo_config.get("origin_branch", "")

    def set_origin_branch(self, origin_branch: str) -> None:
        self._update_repo_value("origin_branch", origin_branch)

    def get_bitbucket_username(self) -> str:
        return self.repo_config.get("bitbucket_username", "")

    def set_bitbucket_username(self, username: str) -> None:
        self._update_repo_value("bitbucket_username", username)

    def get_bitbucket_app_password(self) -> str:
        return self.repo_config.get("bitbucket_app_password", "")

    def set_bitbucket_app_password(self, pwd: str) -> None:
        self._update_repo_value("bitbucket_app_password", pwd)

    def get_repo_slug(self) -> str:
        return self.repo_config.get("repo_slug", "")

    def set_repo_slug(self, slug: str) -> None:
        self._update_repo_value("repo_slug", slug)

    def get_commit_hashes(self) -> str:
        return self.repo_config.get("commit_hashes", "")

    def set_commit_hashes(self, commit_hashes: str) -> None:
        self._update_repo_value("commit_hashes", commit_hashes)

    def get_pr_title(self) -> str:
        return self.repo_config.get("pr_title", "")

    def set_pr_title(self, title: str) -> None:
        self._update_repo_value("pr_title", title)

    def get_source_branch(self) -> str:
        return self.repo_config.get("source_branch", "")

    def set_source_branch(self, branch: str) -> None:
        self._update_repo_value("source_branch", branch)

    def get_target_branch(self) -> str:
        return self.repo_config.get("target_branch", "")

    def set_target_branch(self, branch: str) -> None:
        self._update_repo_value("target_branch", branch)

    def get_provider(self) -> str:
        provider = self.repo_config.get("provider", "bitbucket")
        return provider or "bitbucket"

    def set_provider(self, provider: str) -> None:
        provider = (provider or "bitbucket").lower()
        self._update_repo_value("provider", provider)

    def get_bitbucket_workspace(self) -> str:
        return self.repo_config.get("bitbucket_workspace", "")

    def set_bitbucket_workspace(self, workspace: str) -> None:
        self._update_repo_value("bitbucket_workspace", workspace)

    def get_github_owner(self) -> str:
        return self.repo_config.get("github_owner", "")

    def set_github_owner(self, owner: str) -> None:
        self._update_repo_value("github_owner", owner)

    def get_github_repo(self) -> str:
        return self.repo_config.get("github_repo", "")

    def set_github_repo(self, repo: str) -> None:
        self._update_repo_value("github_repo", repo)

    def get_github_token(self) -> str:
        return self.repo_config.get("github_token", "")

    def set_github_token(self, token: str) -> None:
        self._update_repo_value("github_token", token)
