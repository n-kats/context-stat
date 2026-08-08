from __future__ import annotations

import contextlib
import json
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from context_stat.domain.content import (
    ContentBundle,
    ContentItem,
    ContentKind,
    ImagePayload,
    StructuredPayload,
    TextPayload,
)
from context_stat.domain.errors import ConfigurationError


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return str(value)


def _codex_string_map(value: Any, field: str, server_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise ConfigurationError(
            f"Codex MCP server {field} must be a map of strings: {server_name}"
        )
    return dict(value)


@dataclass(frozen=True)
class McpServerConfig:
    transport: str
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    headers_from_env: dict[str, str] | None = None
    server_name: str | None = None

    @classmethod
    def from_path(cls, path: Path) -> McpServerConfig:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"could not read MCP config {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ConfigurationError("MCP config must be a JSON object")
        transport = value.get("transport")
        if transport not in {"stdio", "streamable-http"}:
            raise ConfigurationError("MCP config transport must be `stdio` or `streamable-http`")
        args = value.get("args", [])
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise ConfigurationError("MCP config args must be an array of strings")
        env = value.get("env")
        if env is not None and (
            not isinstance(env, dict)
            or not all(isinstance(key, str) and isinstance(item, str) for key, item in env.items())
        ):
            raise ConfigurationError("MCP config env must be an object of strings")
        headers_from_env = value.get("headers_from_env")
        if headers_from_env is not None and (
            not isinstance(headers_from_env, dict)
            or not all(
                isinstance(key, str) and isinstance(item, str)
                for key, item in headers_from_env.items()
            )
        ):
            raise ConfigurationError("headers_from_env must map header names to env names")
        headers = value.get("headers")
        if headers is not None and (
            not isinstance(headers, dict)
            or not all(
                isinstance(key, str) and isinstance(item, str) for key, item in headers.items()
            )
        ):
            raise ConfigurationError("MCP config headers must map header names to values")
        return cls(
            transport=transport,
            command=value.get("command"),
            args=tuple(args),
            env=env,
            cwd=value.get("cwd"),
            url=value.get("url"),
            headers=headers,
            headers_from_env=headers_from_env,
        )

    @classmethod
    def from_codex_path(cls, path: Path, server_name: str | None = None) -> McpServerConfig:
        try:
            value = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigurationError(f"could not read Codex config {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ConfigurationError("Codex config must be a TOML table")
        servers = value.get("mcp_servers")
        if not isinstance(servers, dict):
            raise ConfigurationError("Codex config must contain an mcp_servers table")

        candidates: list[str] = []
        for name, settings in servers.items():
            if not isinstance(name, str) or not isinstance(settings, dict):
                raise ConfigurationError("Codex mcp_servers entries must be tables")
            enabled = settings.get("enabled", True)
            if not isinstance(enabled, bool):
                raise ConfigurationError(f"Codex MCP server {name} enabled must be a boolean")
            if enabled and ("command" in settings or "url" in settings):
                candidates.append(name)

        if server_name is None:
            if len(candidates) != 1:
                if not candidates:
                    raise ConfigurationError(
                        "Codex config has no enabled MCP server with command or url"
                    )
                available = ", ".join(candidates)
                raise ConfigurationError(
                    f"Codex config has multiple enabled MCP servers; use --server NAME "
                    f"(available: {available})"
                )
            selected_name = candidates[0]
        else:
            selected_name = server_name
            settings = servers.get(selected_name)
            if not isinstance(settings, dict):
                available = ", ".join(candidates) or "none"
                raise ConfigurationError(
                    f"Codex MCP server not found: {selected_name} (available: {available})"
                )
            if settings.get("enabled", True) is False:
                raise ConfigurationError(f"Codex MCP server is disabled: {selected_name}")

        settings = servers[selected_name]
        if not isinstance(settings, dict):
            raise ConfigurationError(f"Codex MCP server must be a table: {selected_name}")
        command = settings.get("command")
        url = settings.get("url")
        if command is not None and url is not None:
            raise ConfigurationError(
                f"Codex MCP server cannot define both command and url: {selected_name}"
            )
        if command is not None:
            if not isinstance(command, str) or not command:
                raise ConfigurationError(
                    f"Codex MCP server command must be a non-empty string: {selected_name}"
                )
            args = settings.get("args", [])
            if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
                raise ConfigurationError(
                    f"Codex MCP server args must be an array of strings: {selected_name}"
                )
            env = _codex_string_map(settings.get("env"), "env", selected_name)
            cwd = settings.get("cwd")
            if cwd is not None and not isinstance(cwd, str):
                raise ConfigurationError(f"Codex MCP server cwd must be a string: {selected_name}")
            return cls(
                transport="stdio",
                command=command,
                args=tuple(args),
                env=env or None,
                cwd=cwd,
                server_name=selected_name,
            )
        if url is not None:
            if not isinstance(url, str) or not url:
                raise ConfigurationError(
                    f"Codex MCP server url must be a non-empty string: {selected_name}"
                )
            headers = _codex_string_map(settings.get("http_headers"), "http_headers", selected_name)
            headers_from_env = _codex_string_map(
                settings.get("env_http_headers"), "env_http_headers", selected_name
            )
            bearer_env = settings.get("bearer_token_env_var")
            if bearer_env is not None:
                if not isinstance(bearer_env, str) or not bearer_env:
                    raise ConfigurationError(
                        "Codex MCP bearer_token_env_var must be a non-empty string: "
                        f"{selected_name}"
                    )
                if "Authorization" in headers or "Authorization" in headers_from_env:
                    raise ConfigurationError(
                        f"Codex MCP server defines Authorization more than once: {selected_name}"
                    )
                headers_from_env["Authorization"] = bearer_env
            return cls(
                transport="streamable-http",
                url=url,
                headers=headers or None,
                headers_from_env=headers_from_env or None,
                server_name=selected_name,
            )
        raise ConfigurationError(f"Codex MCP server must define command or url: {selected_name}")

    def validate(self) -> None:
        if self.transport == "stdio":
            if not self.command or not isinstance(self.command, str):
                raise ConfigurationError("stdio MCP config requires a command")
            return
        if not self.url or not isinstance(self.url, str):
            raise ConfigurationError("streamable-http MCP config requires a url")


class McpClientPort(Protocol):
    async def list_tools(self, *, cursor: str | None = None) -> Any: ...

    async def list_resources(self, *, cursor: str | None = None) -> Any: ...

    async def list_prompts(self, *, cursor: str | None = None) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any] | None) -> Any: ...

    async def read_resource(self, uri: str) -> Any: ...

    async def get_prompt(self, name: str, arguments: dict[str, str] | None) -> Any: ...

    @property
    def server_capabilities(self) -> Any: ...


class OfficialMcpSdkAdapter:
    def __init__(self, config: McpServerConfig) -> None:
        self._config = config
        self._stack: contextlib.AsyncExitStack | None = None
        self._client: Any = None

    async def __aenter__(self) -> OfficialMcpSdkAdapter:
        self._config.validate()
        from mcp.client import Client

        self._stack = contextlib.AsyncExitStack()
        await self._stack.__aenter__()
        if self._config.transport == "stdio":
            from mcp.client.stdio import StdioServerParameters, stdio_client

            server = StdioServerParameters(
                command=self._config.command or "",
                args=list(self._config.args),
                env={**os.environ, **(self._config.env or {})},
                cwd=self._config.cwd,
            )
            transport = stdio_client(server)
        else:
            from mcp.client.streamable_http import streamable_http_client

            headers = dict(self._config.headers or {})
            for header, env_name in (self._config.headers_from_env or {}).items():
                value = os.environ.get(env_name)
                if value is None:
                    raise ConfigurationError(
                        f"MCP HTTP header environment variable is not set: {env_name}"
                    )
                headers[header] = value
            if headers:
                import httpx2

                http_client = httpx2.AsyncClient(headers=headers)
                await self._stack.enter_async_context(http_client)
                transport = streamable_http_client(self._config.url or "", http_client=http_client)
            else:
                transport = streamable_http_client(self._config.url or "")
        self._client = Client(transport, mode="auto", raise_exceptions=True)
        await self._stack.enter_async_context(self._client)
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc_value, traceback)
        self._stack = None
        self._client = None

    async def list_tools(self, *, cursor: str | None = None) -> Any:
        return await self._client.list_tools(cursor=cursor)

    async def list_resources(self, *, cursor: str | None = None) -> Any:
        return await self._client.list_resources(cursor=cursor)

    async def list_prompts(self, *, cursor: str | None = None) -> Any:
        return await self._client.list_prompts(cursor=cursor)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None) -> Any:
        return await self._client.call_tool(name, arguments=arguments)

    async def read_resource(self, uri: str) -> Any:
        return await self._client.read_resource(uri)

    async def get_prompt(self, name: str, arguments: dict[str, str] | None) -> Any:
        return await self._client.get_prompt(name, arguments=arguments)

    @property
    def server_capabilities(self) -> Any:
        return self._client.server_capabilities


def _content_item(
    value: dict[str, Any], *, item_id: str, label: str, direction: str, role: str
) -> ContentItem:
    item_type = value.get("type")
    if item_type == "resource":
        resource = value.get("resource")
        if isinstance(resource, dict):
            nested = _content_item(
                resource,
                item_id=item_id,
                label=label,
                direction=direction,
                role=role,
            )
            metadata = {**nested.metadata, "mcp_type": "resource"}
            uri = resource.get("uri")
            if isinstance(uri, str):
                metadata["resource_uri"] = uri
            return replace(nested, metadata=metadata)
    if item_type is None and "text" in value:
        item_type = "text"
        value = {**value, "type": item_type}
    elif item_type is None and "blob" in value:
        item_type = "image" if str(value.get("mimeType", "")).startswith("image/") else None
        if item_type == "image":
            import base64

            value = {**value, "type": item_type, "data": value["blob"]}
    metadata = {"mcp_type": item_type}
    if item_type == "text":
        text = str(value.get("text", ""))
        return ContentItem(
            item_id=item_id,
            origin="mcp",
            label=label,
            kind=ContentKind.TEXT,
            payload=TextPayload(raw=text.encode("utf-8"), text=text, encoding="utf-8"),
            metadata=metadata,
            direction=direction,
            semantic_role=role,
        )
    if item_type == "image":
        import base64

        data = base64.b64decode(str(value.get("data", "")), validate=True)
        return ContentItem(
            item_id=item_id,
            origin="mcp",
            label=label,
            kind=ContentKind.IMAGE,
            payload=ImagePayload(data=data, media_type=value.get("mimeType")),
            metadata=metadata,
            direction=direction,
            semantic_role=role,
        )
    return ContentItem(
        item_id=item_id,
        origin="mcp",
        label=label,
        kind=ContentKind.STRUCTURED,
        payload=StructuredPayload(value=value),
        metadata=metadata,
        direction=direction,
        semantic_role=role,
    )


def list_result_bundle(result: Any, kind: str) -> ContentBundle:
    value = jsonable(result)
    entries = value.get(kind, []) if isinstance(value, dict) else []
    items = []
    for index, entry in enumerate(entries):
        metadata: dict[str, Any] = {
            "mcp_kind": kind,
            "mcp_index": index,
            "mcp_definition": entry,
        }
        label = f"{kind}[{index}]"
        if isinstance(entry, dict):
            name = entry.get("name")
            uri = entry.get("uri")
            description = entry.get("description")
            if isinstance(name, str) and name:
                label = name
                metadata["mcp_name"] = name
            elif kind == "resources" and isinstance(uri, str) and uri:
                label = uri
            if isinstance(uri, str) and uri:
                metadata["mcp_uri"] = uri
            if isinstance(description, str) and description:
                metadata["mcp_description"] = description
            mime_type = entry.get("mimeType")
            if isinstance(mime_type, str) and mime_type:
                metadata["mcp_mime_type"] = mime_type
        items.append(
            ContentItem(
                item_id=f"mcp:{kind}:{index}",
                origin="mcp",
                label=label,
                kind=ContentKind.STRUCTURED,
                payload=StructuredPayload(value=entry),
                metadata=metadata,
                direction="server_to_client",
                semantic_role="returned",
            )
        )
    return ContentBundle(tuple(items), facts={"operation": f"{kind}/list"})


def result_bundle(result: Any, method: str) -> ContentBundle:
    value = jsonable(result)
    items: list[ContentItem] = []
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, list):
            for index, block in enumerate(content):
                if isinstance(block, dict):
                    items.append(
                        _content_item(
                            block,
                            item_id=f"mcp:return:{index}",
                            label=f"{method}.content[{index}]",
                            direction="server_to_client",
                            role="returned",
                        )
                    )
        structured = value.get("structuredContent")
        if structured is not None:
            items.append(
                ContentItem(
                    item_id="mcp:return:structuredContent",
                    origin="mcp",
                    label=f"{method}.structuredContent",
                    kind=ContentKind.STRUCTURED,
                    payload=StructuredPayload(value=structured),
                    direction="server_to_client",
                    semantic_role="returned",
                )
            )
        if method == "resources/read" and isinstance(value.get("contents"), list):
            for index, block in enumerate(value["contents"]):
                if isinstance(block, dict):
                    items.append(
                        _content_item(
                            block,
                            item_id=f"mcp:resource:{index}",
                            label=f"{method}.contents[{index}]",
                            direction="server_to_client",
                            role="returned",
                        )
                    )
        if method == "prompts/get" and isinstance(value.get("messages"), list):
            for index, message in enumerate(value["messages"]):
                if isinstance(message, dict) and isinstance(message.get("content"), dict):
                    items.append(
                        _content_item(
                            message["content"],
                            item_id=f"mcp:prompt:{index}",
                            label=f"{method}.messages[{index}]",
                            direction="server_to_client",
                            role="returned",
                        )
                    )
    if not items:
        items.append(
            ContentItem(
                item_id="mcp:return:result",
                origin="mcp",
                label=f"{method}.result",
                kind=ContentKind.STRUCTURED,
                payload=StructuredPayload(value=value),
                direction="server_to_client",
                semantic_role="returned",
            )
        )
    return ContentBundle(tuple(items), facts={"operation": method})
