"""Minimal MCP client over Streamable HTTP JSON-RPC."""

from __future__ import annotations

import json
from typing import Any

import requests

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "dealbreakers", "version": "0.1.0"}


class MCPError(Exception):
    """Base exception for MCP failures (including timeouts and connection errors)."""


class MCPHTTPError(MCPError):
    """Non-2xx HTTP response from the MCP server."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class MCPProtocolError(MCPError):
    """JSON-RPC error response or unparseable payload."""


class MCPClient:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        self._session_id: str | None = None
        self._initialized = False
        self._next_id = 0

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request and return its `result`."""
        if method != "initialize":
            self._ensure_initialized()
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params or {},
        }
        response = self._post(payload)
        return self._extract_result(response)

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the server's tool descriptors from tools/list."""
        result = self.request("tools/list")
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke a server tool via tools/call and return its result."""
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._initialized = True  # set first so the initialize request doesn't recurse
        try:
            self.request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            )
        except MCPError:
            self._initialized = False
            raise
        self._notify("notifications/initialized")

    def _notify(self, method: str) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        try:
            self._post({"jsonrpc": "2.0", "method": method}, expect_body=False)
        except MCPError:
            # Some servers reject or ignore notifications; not fatal for discovery.
            pass

    def _post(
        self,
        payload: dict[str, Any],
        *,
        expect_body: bool = True,
    ) -> dict[str, Any] | None:
        headers = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        try:
            response = self._session.post(
                self.base_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise MCPError(f"Request to {self.base_url} failed: {exc}") from exc

        if not response.ok:
            raise MCPHTTPError(
                f"HTTP {response.status_code} from {self.base_url}: {response.text[:500]}",
                status_code=response.status_code,
            )

        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id

        if not expect_body:
            return None
        return self._parse_body(response)

    def _parse_body(self, response: requests.Response) -> dict[str, Any]:
        content_type = response.headers.get("Content-Type", "")

        # Servers often omit charset; requests then falls back to latin-1,
        # corrupting UTF-8 payloads (and injecting fake line breaks like NEL).
        if "charset" not in content_type.lower():
            response.encoding = "utf-8"

        if "text/event-stream" in content_type:
            message = self._parse_sse(response.text)
            if message is None:
                raise MCPProtocolError(
                    f"No JSON-RPC message found in SSE stream from {self.base_url}"
                )
            return message

        try:
            return response.json()
        except ValueError as exc:
            raise MCPProtocolError(
                f"Malformed JSON from {self.base_url}: {response.text[:500]}"
            ) from exc

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any] | None:
        """Extract the first JSON-RPC response object from an SSE body.

        Per the SSE spec, one event may span multiple `data:` lines which must
        be concatenated; events are separated by blank lines. Only CR/LF count
        as line breaks (str.splitlines would also split on NEL etc., which can
        appear inside JSON payloads).
        """
        events: list[str] = []
        current: list[str] = []
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if line.startswith("data:"):
                current.append(line[len("data:"):].lstrip())
            elif not line.strip() and current:
                events.append("\n".join(current))
                current = []
        if current:
            events.append("\n".join(current))

        for event in events:
            try:
                message = json.loads(event)
            except ValueError:
                continue
            if isinstance(message, dict) and "jsonrpc" in message:
                return message
        return None

    @staticmethod
    def _extract_result(message: dict[str, Any]) -> dict[str, Any]:
        if "error" in message and message["error"] is not None:
            error = message["error"]
            raise MCPProtocolError(
                f"JSON-RPC error {error.get('code')}: {error.get('message')}"
            )
        if "result" not in message:
            raise MCPProtocolError(f"JSON-RPC response missing 'result': {message}")
        return message["result"]
