from unittest.mock import MagicMock, patch

import pytest

from services.pr_creation_service import PullRequestCreateRequest, PullRequestCreationService


@pytest.fixture
def service():
    config = MagicMock()
    config.get_provider.return_value = "github"
    return PullRequestCreationService(config)


def test_create_pull_request_validates_remote_branches(service):
    repo = {"provider": "github", "owner": "openai", "slug": "demo"}
    provider = MagicMock()
    provider.validate_credentials.return_value = MagicMock()
    provider.branch_exists.side_effect = [True, False]

    with patch("services.pr_creation_service.build_provider_client_for_name", return_value=provider):
        with pytest.raises(ValueError, match="Remote target branch 'main' does not exist."):
            service.create_pull_request(
                repo,
                PullRequestCreateRequest(
                    title="Feature",
                    source_branch="feature/test",
                    target_branch="main",
                ),
            )


def test_create_pull_request_returns_normalized_result(service):
    repo = {
        "provider": "github",
        "owner": "openai",
        "slug": "demo",
        "full_name": "openai/demo",
    }
    provider = MagicMock()
    provider.validate_credentials.return_value = MagicMock()
    provider.branch_exists.side_effect = [True, True]
    provider.create_pull_request.return_value = {
        "number": 17,
        "title": "Feature",
        "html_url": "https://github.com/openai/demo/pull/17",
        "state": "open",
        "draft": True,
    }

    with patch("services.pr_creation_service.build_provider_client_for_name", return_value=provider):
        result = service.create_pull_request(
            repo,
            PullRequestCreateRequest(
                title="Feature",
                description="Desc",
                source_branch="origin/feature/test",
                target_branch="main",
                draft=True,
            ),
        )

    assert result["pr_id"] == 17
    assert result["number"] == 17
    assert result["url"] == "https://github.com/openai/demo/pull/17"
    assert result["source_branch"] == "feature/test"
    assert result["draft"] is True
    assert result["warnings"] == []
