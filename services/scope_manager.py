from __future__ import annotations

from typing import Optional

from ConfigManager import ConfigManager
from models.contribution_models import ContributionScope, RepositoryRef
from services.provider_api import ProviderClient, build_provider_client


class ScopeManager:
    def __init__(self, config: ConfigManager, provider_client: Optional[ProviderClient] = None):
        self.config = config
        self.provider = provider_client or build_provider_client(config)

    def set_provider(self, provider_client: ProviderClient) -> None:
        self.provider = provider_client

    def current_repository(self) -> Optional[RepositoryRef]:
        return self.provider.current_repository()

    def list_accessible_repositories(self, force_refresh: bool = False) -> list[RepositoryRef]:
        context_key = self.provider.context_key()
        cached, _timestamp = self.config.get_cached_discovered_repositories(
            self.provider.provider_name,
            context_key,
        )
        if cached and not force_refresh:
            return [RepositoryRef.from_dict(item) for item in cached]

        repositories = self.provider.list_repositories()
        repositories = sorted(repositories, key=lambda repo: repo.display_name.lower())
        self.config.set_cached_discovered_repositories(
            self.provider.provider_name,
            context_key,
            [repo.to_dict() for repo in repositories],
        )
        return repositories

    def get_selected_repositories(self) -> list[RepositoryRef]:
        selected = self.config.get_selected_repositories()
        return [RepositoryRef.from_dict(item) for item in selected]

    def save_selected_repositories(self, repositories: list[RepositoryRef]) -> None:
        self.config.set_selected_repositories([repo.to_dict() for repo in repositories])

    def resolve_scope(self, scope_type: str) -> ContributionScope:
        scope_type = (scope_type or "current_repo").strip().lower()
        if scope_type == "contributed_repos":
            raise ValueError(
                "Contributed repositories require a developer and date range from a contribution query."
            )
        if scope_type == "all_repos":
            repositories = tuple(self.list_accessible_repositories())
            return ContributionScope(
                scope_type="all_repos",
                repositories=repositories,
                label=f"All repositories ({len(repositories)})",
            )

        if scope_type == "selected_repos":
            repositories = tuple(self.get_selected_repositories())
            return ContributionScope(
                scope_type="selected_repos",
                repositories=repositories,
                label=f"Selected repositories ({len(repositories)})",
            )

        current_repo = self.current_repository()
        repositories = (current_repo,) if current_repo else ()
        label = current_repo.display_name if current_repo else "Current repository"
        return ContributionScope(
            scope_type="current_repo",
            repositories=repositories,
            label=label,
        )
