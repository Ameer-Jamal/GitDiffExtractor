from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.RepositoryProvider import RepositoryProvider
from services.pr_creation_service import PullRequestCreationService
from services.pr_patch_service import (
    FileChange,
    PullRequestFromChangesRequest,
    PullRequestPatchService,
)


@pytest.fixture
def config():
    config = MagicMock()
    config.get_provider.return_value = "github"
    return config


@pytest.fixture
def creation_service():
    return MagicMock(spec=PullRequestCreationService)


@pytest.fixture
def service(config, creation_service):
    return PullRequestPatchService(config, creation_service=creation_service)


def _repo(local_dir: str) -> dict:
    return {
        "provider": "github",
        "owner": "openai",
        "slug": "demo",
        "full_name": "openai/demo",
        "clone_url": "https://github.com/openai/demo.git",
        "local_dir": local_dir,
    }


def _provider(*, branch_exists):
    provider = MagicMock()
    provider.validate_credentials.return_value = MagicMock()
    provider.branch_exists.side_effect = branch_exists
    return provider


def test_parse_changes_accepts_file_and_delete_entries(service):
    changes = service.parse_changes(
        '[{"path": "src/app.py", "content": "print(1)"}, {"path": "old.txt", "delete": true}]'
    )

    assert [change.path for change in changes] == ["src/app.py", "old.txt"]
    assert changes[0].content == "print(1)"
    assert changes[1].delete is True


def test_parse_changes_rejects_invalid_json(service):
    with pytest.raises(ValueError, match="changes_json must be a JSON array"):
        service.parse_changes("{not json}")


def test_create_pull_request_from_changes_commits_and_opens_pr(service, creation_service, tmp_path):
    repo = _repo(str(tmp_path))
    target_file = tmp_path / "src" / "app.py"
    creation_service.create_pull_request.return_value = {
        "number": 12,
        "url": "https://github.com/openai/demo/pull/12",
    }

    with patch(
        "services.pr_patch_service.build_provider_client_for_name",
        return_value=_provider(branch_exists=[True, False, True]),
    ), patch.object(
        RepositoryProvider, "run_git"
    ) as run_git, patch.object(
        RepositoryProvider,
        "git_output",
        side_effect=["", "main", "src/app.py"],
    ), patch.object(RepositoryProvider, "push_branch") as push_branch:
        result = service.create_pull_request_from_changes(
            repo,
            PullRequestFromChangesRequest(
                title="Add greeting",
                target_branch="main",
                files=(FileChange(path="src/app.py", content="print('hi')\n"),),
            ),
        )

    assert target_file.read_text() == "print('hi')\n"
    assert result["number"] == 12
    assert result["changed_paths"] == ["src/app.py"]

    request = creation_service.create_pull_request.call_args.args[1]
    assert request.source_branch.startswith("repolens/")
    assert request.target_branch == "main"

    executed = [call.args[0] for call in run_git.call_args_list]
    assert ["git", "checkout", "-B", request.source_branch, "origin/main"] in executed
    assert ["git", "commit", "-m", "Add greeting"] in executed
    push_branch.assert_called_once()


def test_create_pull_request_from_patch_only(service, creation_service, tmp_path):
    creation_service.create_pull_request.return_value = {"number": 3}
    diff = "diff --git a/patched.py b/patched.py\n--- a/patched.py\n+++ b/patched.py\n"

    with patch(
        "services.pr_patch_service.build_provider_client_for_name",
        return_value=_provider(branch_exists=[True, False, True]),
    ), patch.object(
        RepositoryProvider, "run_git"
    ) as run_git, patch.object(
        RepositoryProvider,
        "git_output",
        side_effect=["", "main", "patched.py"],
    ), patch.object(RepositoryProvider, "push_branch"):
        result = service.create_pull_request_from_changes(
            _repo(str(tmp_path)),
            PullRequestFromChangesRequest(title="Apply patch", target_branch="main", patch=diff),
        )

    assert result["changed_paths"] == ["patched.py"]
    apply_calls = [call for call in run_git.call_args_list if call.args[0][:2] == ["git", "apply"]]
    assert apply_calls
    assert apply_calls[0].kwargs["input_text"] == diff


def test_create_pull_request_from_changes_requires_changes(service):
    with pytest.raises(ValueError, match="Provide at least one file change or a patch"):
        service.create_pull_request_from_changes(
            _repo("/tmp/demo"),
            PullRequestFromChangesRequest(title="Empty", target_branch="main"),
        )


def test_create_pull_request_from_changes_rejects_existing_source_branch(service):
    with patch(
        "services.pr_patch_service.build_provider_client_for_name",
        return_value=_provider(branch_exists=[True, True]),
    ):
        with pytest.raises(ValueError, match="already exists"):
            service.create_pull_request_from_changes(
                _repo("/tmp/demo"),
                PullRequestFromChangesRequest(
                    title="Feature",
                    target_branch="main",
                    source_branch="feature/existing",
                    files=(FileChange(path="a.txt", content="a"),),
                ),
            )


def test_apply_files_refuses_path_traversal(service, tmp_path):
    with pytest.raises(ValueError, match="outside the repository"):
        service._apply_files(Path(tmp_path), (FileChange(path="../evil.txt", content="x"),))
