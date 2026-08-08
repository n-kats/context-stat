from __future__ import annotations

import asyncio
import os

import uvicorn
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


def _tool(name: str) -> types.Tool:
    return types.Tool(
        name=name,
        description="Return the supplied message.",
        inputSchema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )


async def list_tools(_context: object, params: object) -> types.ListToolsResult:
    if getattr(params, "cursor", None) == "page-2":
        return types.ListToolsResult(tools=[_tool("echo-second")])
    return types.ListToolsResult(
        tools=[_tool("echo")],
        nextCursor="page-2",
    )


async def call_tool(_context: object, params: types.CallToolRequestParams) -> types.CallToolResult:
    if params.name == "fail":
        return types.CallToolResult(
            isError=True,
            content=[types.TextContent(text="server rejected the request")],
        )
    arguments = params.arguments or {}
    message = str(arguments.get("message", ""))
    return types.CallToolResult(
        content=[types.TextContent(text=message)],
        structuredContent={"echo": message},
    )


def _server() -> Server:
    return Server(
        "context-stat-test-server",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


async def main_stdio() -> None:
    server = _server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    if os.environ.get("MCP_TEST_TRANSPORT") == "streamable-http":
        server = _server()
        app = server.streamable_http_app(streamable_http_path="/mcp", json_response=True)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=int(os.environ["MCP_TEST_PORT"]),
            log_level="warning",
        )
        return
    asyncio.run(main_stdio())


if __name__ == "__main__":
    main()
