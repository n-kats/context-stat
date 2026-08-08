from __future__ import annotations

import json
from pathlib import Path

import pytest

from context_stat.adapters.mcp import McpServerConfig
from context_stat.cli import _resolve_mcp_config
from context_stat.domain.errors import ConfigurationError


def test_stdio_mcp_config_is_validated_without_online_permission(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps({"transport": "stdio", "command": "demo", "args": ["--serve"]}),
        encoding="utf-8",
    )

    config = McpServerConfig.from_path(config_path)
    config.validate()
    assert config.args == ("--serve",)


def test_http_mcp_config_is_validated_without_tokenizer_online_permission(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps({"transport": "streamable-http", "url": "https://example.test/mcp"}),
        encoding="utf-8",
    )

    config = McpServerConfig.from_path(config_path)
    config.validate()


def test_codex_stdio_config_is_converted(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[mcp_servers.demo]
command = "demo-server"
args = ["--serve"]
cwd = "/tmp/demo"
env = { MCP_MODE = "test" }
""",
        encoding="utf-8",
    )

    config = McpServerConfig.from_codex_path(config_path)

    assert config.server_name == "demo"
    assert config.transport == "stdio"
    assert config.command == "demo-server"
    assert config.args == ("--serve",)
    assert config.cwd == "/tmp/demo"
    assert config.env == {"MCP_MODE": "test"}


def test_codex_http_config_converts_headers(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[mcp_servers.remote]
url = "https://example.test/mcp"
bearer_token_env_var = "MCP_TOKEN"
http_headers = { X-Region = "test" }
env_http_headers = { X-Trace = "MCP_TRACE" }
""",
        encoding="utf-8",
    )

    config = McpServerConfig.from_codex_path(config_path)

    assert config.server_name == "remote"
    assert config.transport == "streamable-http"
    assert config.url == "https://example.test/mcp"
    assert config.headers == {"X-Region": "test"}
    assert config.headers_from_env == {
        "X-Trace": "MCP_TRACE",
        "Authorization": "MCP_TOKEN",
    }


def test_codex_config_requires_server_name_when_multiple_servers(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[mcp_servers.one]
command = "one"

[mcp_servers.two]
url = "https://example.test/mcp"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="use --server NAME"):
        McpServerConfig.from_codex_path(config_path)

    assert McpServerConfig.from_codex_path(config_path, "two").server_name == "two"
    connection = _resolve_mcp_config(
        None,
        None,
        (),
        codex_config_path=config_path,
        server_name="two",
    )
    assert connection.source == "codex-config"
    assert connection.config.server_name == "two"


def test_codex_disabled_server_is_not_selected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[mcp_servers.disabled]
enabled = false
command = "disabled"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="no enabled MCP server"):
        McpServerConfig.from_codex_path(config_path)
    with pytest.raises(ConfigurationError, match="server is disabled"):
        McpServerConfig.from_codex_path(config_path, "disabled")


def test_direct_mcp_url_builds_streamable_http_config() -> None:
    connection = _resolve_mcp_config(
        None,
        "https://example.test/mcp",
        ("Authorization=MCP_AUTHORIZATION",),
    )

    assert connection.config_path is None
    assert connection.source == "url"
    assert connection.config.transport == "streamable-http"
    assert connection.config.url == "https://example.test/mcp"
    assert connection.config.headers_from_env == {"Authorization": "MCP_AUTHORIZATION"}
