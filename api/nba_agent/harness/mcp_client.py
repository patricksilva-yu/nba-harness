"""MCP lifecycle, discovery and validation. No direct basketball service imports."""

import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from jsonschema import Draft202012Validator
from mcp.shared.exceptions import McpError

from .contracts import ALLOWLIST


class ToolFailure(Exception):
    """Safe structured error code; never forward raw provider exceptions."""


def local_client(db_path: Path, timeout: float) -> Client:
    # The NBA server needs storage configuration, never model credentials.
    env = {key: value for key, value in os.environ.items() if key.startswith("NBA_DB_") or key in {
        "PATH", "SYSTEMROOT", "NBA_STORAGE_BACKEND", "POSTGRES_CONNECTION_STRING", "NBA_POSTGRES_SCHEMA",
    }}
    env["NBA_MCP_DB_PATH"] = str(db_path.resolve())
    env["FASTMCP_SHOW_SERVER_BANNER"] = "false"
    return Client(StdioTransport(
        command=sys.executable, args=["-m", "api.nba_agent.mcp_server"],
        cwd=str(Path(__file__).resolve().parents[3]), env=env, keep_alive=False,
    ), timeout=timeout, init_timeout=timeout)


class MCPBoundary:
    def __init__(self, client):
        self.client = client
        self.schemas = {}

    async def discover(self) -> list[dict]:
        discovered = await self.client.list_tools()
        self.schemas = {tool.name: tool for tool in discovered if tool.name in ALLOWLIST}
        if set(self.schemas) != set(ALLOWLIST):
            raise ToolFailure("missing_required_tools")
        for tool in self.schemas.values():
            Draft202012Validator.check_schema(tool.inputSchema)
            if tool.outputSchema:
                Draft202012Validator.check_schema(tool.outputSchema)
        # Preserve MCP optional/default semantics; validate locally on every call.
        return [{"type": "function", "name": name, "description": self.schemas[name].description,
                 "parameters": self.schemas[name].inputSchema, "strict": False} for name in ALLOWLIST]

    def validate(self, name: str, arguments: dict) -> None:
        if name not in self.schemas:
            raise ToolFailure("tool_not_allowed")
        schema = self.schemas[name].inputSchema
        if set(arguments) - set(schema.get("properties", {})):
            raise ToolFailure("unknown_arguments")
        if not Draft202012Validator(schema).is_valid(arguments):
            raise ToolFailure("invalid_arguments")

    async def call(self, name: str, arguments: dict) -> dict:
        self.validate(name, arguments)
        try:
            result = await self.client.call_tool(name, arguments, raise_on_error=False)
        except McpError as exc:
            raise ToolFailure("mcp_protocol_error") from exc
        if result.is_error:
            raise ToolFailure("tool_execution_error")
        payload = result.structured_content
        if not isinstance(payload, dict):
            raise ToolFailure("invalid_tool_result")
        schema = self.schemas[name].outputSchema
        if schema and not Draft202012Validator(schema).is_valid(payload):
            raise ToolFailure("invalid_tool_result")
        if not isinstance(payload.get("summary"), dict):
            raise ToolFailure("missing_tool_summary")
        return payload
