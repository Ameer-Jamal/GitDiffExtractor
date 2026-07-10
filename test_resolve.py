from mcp_server import RepoLensMCPBackend
import json

backend = RepoLensMCPBackend()
try:
    repo = backend.resolve_repository(
        provider="bitbucket",
        workspace="etqdev",
        slug="mt-frontend",
        allow_direct=True
    )
    print(f"Resolved: {json.dumps(repo, indent=2)}")
except Exception as e:
    print(f"Error: {e}")
