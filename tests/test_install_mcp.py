import json
from pathlib import Path
from unittest.mock import patch

import pytest

import install_mcp


def test_update_mcp_servers_config_creates_new_file(tmp_path: Path):
    config_path = tmp_path / "mcp.json"

    changed, written_path = install_mcp.update_mcp_servers_config(
        config_path,
        "repolens",
        {"command": "python3", "args": ["/tmp/mcp_server.py"]},
    )

    assert changed is True
    assert written_path == config_path
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["repolens"]["command"] == "python3"


def test_update_mcp_servers_config_is_idempotent(tmp_path: Path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "repolens": {"command": "python3", "args": ["/tmp/mcp_server.py"]},
                }
            }
        ),
        encoding="utf-8",
    )

    changed, _written_path = install_mcp.update_mcp_servers_config(
        config_path,
        "repolens",
        {"command": "python3", "args": ["/tmp/mcp_server.py"]},
    )

    assert changed is False


def test_update_mcp_servers_config_preserves_existing_servers(tmp_path: Path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "existing": {"command": "node", "args": ["server.js"]},
                }
            }
        ),
        encoding="utf-8",
    )

    install_mcp.update_mcp_servers_config(
        config_path,
        "repolens",
        {"command": "python3", "args": ["/tmp/mcp_server.py"]},
    )

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"existing", "repolens"}


def test_select_clients_defaults_to_all():
    assert install_mcp.select_clients([]) == list(install_mcp.SUPPORTED_CLIENTS)


def test_select_clients_rejects_unknown_client():
    with pytest.raises(ValueError):
        install_mcp.select_clients(["unknown"])


def test_install_chatgpt_returns_manual_fallback():
    result = install_mcp.install_chatgpt()

    assert result.success is False
    assert "cannot connect directly to a local stdio MCP server" in result.message
    assert "README" in result.details


def test_cursor_config_path_project_scope_uses_repo_root(tmp_path: Path):
    with patch.object(install_mcp, "repo_root", return_value=tmp_path):
        assert install_mcp.cursor_config_path("project") == tmp_path / ".cursor" / "mcp.json"


def test_claude_desktop_config_path_darwin():
    with patch("install_mcp.platform.system", return_value="Darwin"):
        path = install_mcp.claude_desktop_config_path()
    assert str(path).endswith("Library/Application Support/Claude/claude_desktop_config.json")
