import json
import pytest
from unittest.mock import MagicMock, patch
from mcp_server import RepoLensMCPBackend
from models.contribution_models import RepositoryRef, ContributionRecord

@pytest.fixture
def mock_backend():
    with patch("mcp_server.build_provider_client") as mock_build:
        mock_provider = MagicMock()
        mock_build.return_value = mock_provider
        
        # Mock resolve_repository
        backend = RepoLensMCPBackend()
        backend.resolve_repository = MagicMock(return_value={
            "provider": "bitbucket",
            "owner": "etqdev",
            "slug": "mt-backend",
            "full_name": "etqdev/mt-backend"
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
    # search_contributions_by_ticket calls query_contribution_history
    # which calls history_service.execute_query
    
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
        
        args, kwargs = mock_execute.call_args
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
    
    # Mock resolve_repository to return a repo for a slug
    backend.resolve_repository.side_effect = lambda **kwargs: {
        "provider": "bitbucket",
        "owner": "etqdev",
        "slug": kwargs.get("slug"),
        "full_name": f"etqdev/{kwargs.get('slug')}"
    }
    
    with patch.object(backend.history_service, "execute_query") as mock_execute:
        mock_execute.return_value = MagicMock(
            records=[],
            scope=MagicMock(scope_type="custom", label="custom", repositories=[RepositoryRef(provider="bitbucket", workspace="etqdev", slug="mt-backend", display_name="mt-backend", full_name="etqdev/mt-backend")]),
            partial_errors=[],
            grouped_records=[],
            total_prs=0,
            total_commits=0,
            active_repositories=[],
            top_repositories=[],
            ticket_prefixes=[]
        )
        
        # Pass a list of strings instead of dicts
        backend.query_contribution_history(
            developer="me",
            repositories_json=json.dumps(["mt-backend"])
        )
        
        args, kwargs = mock_execute.call_args
        query = args[0]
        assert len(query.scope_repositories) == 1
        assert query.scope_repositories[0].slug == "mt-backend"
