from services.git_context_service import GitContextService


def test_parse_github_https_remote():
    provider, owner, slug = GitContextService.parse_remote_url("https://github.com/Ameer-Jamal/RepoLens.git")

    assert provider == "github"
    assert owner == "Ameer-Jamal"
    assert slug == "RepoLens"


def test_parse_github_ssh_remote():
    provider, owner, slug = GitContextService.parse_remote_url("git@github.com:Ameer-Jamal/RepoLens.git")

    assert provider == "github"
    assert owner == "Ameer-Jamal"
    assert slug == "RepoLens"


def test_parse_bitbucket_https_remote():
    provider, owner, slug = GitContextService.parse_remote_url("https://bitbucket.org/example-workspace/mobile-app.git")

    assert provider == "bitbucket"
    assert owner == "example-workspace"
    assert slug == "mobile-app"
