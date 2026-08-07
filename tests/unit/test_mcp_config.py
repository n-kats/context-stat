from __future__ import annotations

import json
from pathlib import Path

from context_stat.adapters.mcp import McpServerConfig


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
