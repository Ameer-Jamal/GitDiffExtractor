import json
import pytest
from unittest.mock import MagicMock, patch
from mcp_server import RepoLensMCPBackend
from models.contribution_models import RepositoryRef

@pytest.fixture
def mock_backend():
    with patch("mcp_server.build_provider_client") as mock_build:
        mock_provider = MagicMock()
        mock_build.return_value = mock_provider
        
        # Mock resolve_repository
        backend = RepoLensMCPBackend()
        backend.resolve_repository = MagicMock(return_value={
            "provider": "bitbucket",
            "owner": "example-workspace",
            "slug": "backend-service",
            "full_name": "example-workspace/backend-service",
            "clone_url": "https://bitbucket.org/example-workspace/backend-service.git"
        })
        return backend, mock_provider

def test_find_pr_for_commit(mock_backend):
    backend, provider = mock_backend
    provider.list_pull_requests_for_commit.return_value = [{"id": "123", "title": "Fix bug"}]
    
    result = backend.find_pr_for_commit(commit_hash="abc123")
    
    assert result["count"] == 1
    assert result["pull_requests"][0]["id"] == "123"
    provider.list_pull_requests_for_commit.assert_called_once()

def test_search_contributions_by_ticket(mock_backend):
    backend, provider = mock_backend
    
    with patch.object(backend.history_service, "execute_query") as mock_execute:
        mock_execute.return_value = MagicMock(
            records=[],
            scope=MagicMock(scope_type="all", label="All", repositories=[]),
            partial_errors=[],
            grouped_records=[],
            total_prs=0,
            total_commits=0,
            active_repositories=[],
            top_repositories=[],
            ticket_prefixes=[]
        )
        
        backend.search_contributions_by_ticket(ticket="RU-24133")
        
        args, _ = mock_execute.call_args
        query = args[0]
        assert query.search_text == "RU-24133"

def test_analyze_file_history(mock_backend):
    backend, provider = mock_backend
    
    with patch.object(backend.history_service, "execute_file_history_query") as mock_execute:
        mock_execute.return_value = MagicMock(
            records=[MagicMock(to_dict=lambda: {"id": "1"})],
            total_prs=1,
            total_commits=0
        )
        
        result = backend.analyze_file_history(file_path="src/main.java")
        
        assert result["file_path"] == "src/main.java"
        assert len(result["records"]) == 1
        mock_execute.assert_called_once()

def test_query_contribution_history_fuzzy_resolve(mock_backend):
    backend, provider = mock_backend
    
    backend.resolve_repository.side_effect = lambda **kwargs: {
        "provider": "bitbucket",
        "owner": "example-workspace",
        "slug": kwargs.get("slug"),
        "full_name": f"example-workspace/{kwargs.get('slug')}"
    }
    
    with patch.object(backend.history_service, "execute_query") as mock_execute:
        mock_execute.return_value = MagicMock(
            records=[],
            scope=MagicMock(scope_type="custom", label="custom", repositories=[RepositoryRef(provider="bitbucket", workspace="example-workspace", slug="backend-service", display_name="backend-service", full_name="example-workspace/backend-service")]),
            partial_errors=[],
            grouped_records=[],
            total_prs=0,
            total_commits=0,
            active_repositories=[],
            top_repositories=[],
            ticket_prefixes=[]
        )
        
        backend.query_contribution_history(
            developer="me",
            repositories_json=json.dumps(["backend-service"])
        )
        
        args, _ = mock_execute.call_args
        query = args[0]
        assert len(query.scope_repositories) == 1
        assert query.scope_repositories[0].slug == "backend-service"

def test_get_pr_context_url(mock_backend):
    backend, provider = mock_backend
    
    backend.resolve_repository.return_value = {
        "provider": "bitbucket",
        "owner": "example-workspace",
        "slug": "db-migration-service",
        "full_name": "example-workspace/db-migration-service",
        "clone_url": "https://bitbucket.org/example-workspace/db-migration-service.git"
    }
    
    with patch.object(backend.pr_service, "parse_pr_url") as mock_parse:
        mock_parse.return_value = {
            "provider": "bitbucket",
            "workspace": "example-workspace",
            "slug": "db-migration-service",
            "pr_id": "778"
        }
        
        with patch.object(backend.pr_service, "get_pull_request") as mock_get_pr:
            mock_get_pr.return_value = {"id": 778, "title": "DB Migration"}
            
            with patch.object(backend, "_repo_dir") as mock_repo_dir:
                mock_repo_dir.return_value = "/tmp/repo"
                with patch.object(backend.diff_service, "generate_pr_diff") as mock_diff:
                    mock_diff.return_value = MagicMock(
                        diff_text="diff content",
                        merge_base="base",
                        source_commit="src",
                        destination_commit="dst",
                        merge_commit="mrg"
                    )
                    
                    result = backend.get_pr_context(reference="https://bitbucket.org/example-workspace/db-migration-service/pull-requests/778")
                    
                    assert result["pr"]["id"] == 778
                    assert result["diff_text"] == "diff content"
                    mock_parse.assert_called_once()
                    mock_get_pr.assert_called_once()


def test_create_pull_request(mock_backend):
    backend, _provider = mock_backend
    backend.resolve_repository.return_value = {
        "provider": "github",
        "owner": "openai",
        "slug": "demo",
        "full_name": "openai/demo",
    }
    with patch.object(backend.pr_creation_service, "create_pull_request") as mock_create:
        mock_create.return_value = {"url": "https://github.com/openai/demo/pull/17", "number": 17}

        result = backend.create_pull_request(
            title="Feature",
            source_branch="feature/test",
            target_branch="main",
        )

    assert result["number"] == 17
    mock_create.assert_called_once()


def test_create_pull_request_uses_direct_repo_args():
    config = MagicMock()
    config.get_provider.return_value = "bitbucket"
    config.get_active_repository.return_value = {
        "provider": "bitbucket",
        "owner": "example-workspace",
        "slug": "mobile-app",
    }
    config.get_selected_repositories.return_value = []
    config.get_managed_repo_root.return_value = ""
    config.get_repo_dir.return_value = ""
    config.effective_source_summary.return_value = {}
    with patch("mcp_server.build_provider_client") as mock_build:
        mock_build.return_value = MagicMock()
        backend = RepoLensMCPBackend(config)

    with patch.object(backend.pr_creation_service, "create_pull_request") as mock_create:
        mock_create.return_value = {"url": "https://github.com/Ameer-Jamal/RepoLens/pull/8", "number": 8}
        result = backend.create_pull_request(
            provider="github",
            workspace="Ameer-Jamal",
            slug="RepoLens",
            title="Feature",
            source_branch="feature/test",
            target_branch="main",
        )

    assert result["number"] == 8
    repo_arg = mock_create.call_args.args[0]
    assert repo_arg["provider"] == "github"
    assert repo_arg["owner"] == "Ameer-Jamal"
    assert repo_arg["slug"] == "RepoLens"


def test_create_pull_request_can_infer_repo_from_repo_dir():
    config = MagicMock()
    config.get_provider.return_value = "bitbucket"
    config.get_active_repository.return_value = {}
    config.get_selected_repositories.return_value = []
    config.get_managed_repo_root.return_value = ""
    config.get_repo_dir.return_value = ""
    config.effective_source_summary.return_value = {}
    with patch("mcp_server.build_provider_client") as mock_build:
        mock_build.return_value = MagicMock()
        backend = RepoLensMCPBackend(config)

    inferred_context = MagicMock()
    inferred_context.repository_dict.return_value = {
        "provider": "github",
        "owner": "Ameer-Jamal",
        "slug": "RepoLens",
        "local_dir": "/tmp/RepoLens",
    }
    with patch.object(backend.git_context_service, "resolve", return_value=inferred_context):
        with patch.object(backend.pr_creation_service, "create_pull_request") as mock_create:
            mock_create.return_value = {"number": 8}
            backend.create_pull_request(
                repo_dir="/tmp/RepoLens",
                title="Feature",
                source_branch="feature/test",
                target_branch="main",
            )

    repo_arg = mock_create.call_args.args[0]
    assert repo_arg["provider"] == "github"
    assert repo_arg["owner"] == "Ameer-Jamal"


def test_get_git_repository_context_returns_auth_status():
    config = MagicMock()
    config.get_github_token.return_value = "token"
    config.get_bitbucket_username.return_value = ""
    config.get_bitbucket_app_password.return_value = ""
    config.get_provider.return_value = "github"
    config.get_managed_repo_root.return_value = ""
    config.get_repo_dir.return_value = "/tmp/RepoLens"
    config.get_active_repository.return_value = {}
    config.get_selected_repositories.return_value = []
    config.effective_source_summary.return_value = {}
    with patch("mcp_server.build_provider_client") as mock_build:
        mock_build.return_value = MagicMock()
        backend = RepoLensMCPBackend(config)

    context = MagicMock()
    context.to_dict.return_value = {"provider": "github", "owner": "Ameer-Jamal", "slug": "RepoLens"}
    with patch.object(backend.git_context_service, "resolve", return_value=context):
        result = backend.get_git_repository_context()

    assert result["auth"]["github_token_configured"] is True
    assert result["auth"]["bitbucket_username_configured"] is False
