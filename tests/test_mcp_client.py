import json

import pytest
import requests
import requests_mock

from dealbreakers.mcp import (
    MCPClient,
    MCPError,
    MCPHTTPError,
    MCPProtocolError,
    discover_all,
)

URL = "https://mcp.example.com/mcp"

TOOLS = [
    {
        "name": "search_hotels",
        "description": "Search hotels",
        "inputSchema": {
            "type": "object",
            "properties": {"destination": {"type": "string"}},
            "required": ["destination"],
        },
    }
]


def mcp_handler(request, context):
    """Respond to initialize / notifications / tools/list like a real server."""
    body = request.json()
    method = body.get("method")

    if method == "initialize":
        context.headers["Mcp-Session-Id"] = "session-123"
        return {
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}},
        }
    if method == "notifications/initialized":
        context.status_code = 202
        return {}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": TOOLS}}

    return {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": "Unknown"}}


def test_list_tools_sends_correct_jsonrpc_body() -> None:
    with requests_mock.Mocker() as mock:
        mock.post(URL, json=mcp_handler)

        client = MCPClient(URL)
        tools = client.list_tools()

        assert tools == TOOLS

        methods = [request.json().get("method") for request in mock.request_history]
        assert methods == ["initialize", "notifications/initialized", "tools/list"]

        tools_request = mock.request_history[-1].json()
        assert tools_request["jsonrpc"] == "2.0"
        assert isinstance(tools_request["id"], int)
        assert tools_request["params"] == {}

        # Session id from initialize is reused on later requests
        assert mock.request_history[-1].headers.get("Mcp-Session-Id") == "session-123"


def test_request_parses_plain_json_result() -> None:
    with requests_mock.Mocker() as mock:
        mock.post(URL, json={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})

        result = MCPClient(URL).request("ping")
        assert result == {"ok": True}


def test_request_parses_sse_response() -> None:
    sse_body = (
        "event: message\n"
        f"data: {json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'tools': TOOLS}})}\n\n"
    )
    with requests_mock.Mocker() as mock:
        mock.post(URL, text=sse_body, headers={"Content-Type": "text/event-stream"})

        result = MCPClient(URL).request("tools/list")
        assert result["tools"] == TOOLS


def test_jsonrpc_error_raises_protocol_error() -> None:
    with requests_mock.Mocker() as mock:
        mock.post(
            URL,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32601, "message": "Method not found"},
            },
        )

        with pytest.raises(MCPProtocolError, match="Method not found"):
            MCPClient(URL).request("tools/list")


def test_http_error_raises_http_error() -> None:
    with requests_mock.Mocker() as mock:
        mock.post(URL, status_code=500, text="boom")

        with pytest.raises(MCPHTTPError) as exc_info:
            MCPClient(URL).request("tools/list")
        assert exc_info.value.status_code == 500


def test_malformed_json_raises_protocol_error() -> None:
    with requests_mock.Mocker() as mock:
        mock.post(URL, text="not json at all", headers={"Content-Type": "application/json"})

        with pytest.raises(MCPProtocolError, match="Malformed JSON"):
            MCPClient(URL).request("tools/list")


def test_timeout_raises_mcp_error() -> None:
    with requests_mock.Mocker() as mock:
        mock.post(URL, exc=requests.exceptions.ConnectTimeout)

        with pytest.raises(MCPError):
            MCPClient(URL).request("tools/list")


def test_discover_all_captures_errors_per_provider() -> None:
    good_url = "https://good.example.com/mcp"
    bad_url = "https://bad.example.com/mcp"

    with requests_mock.Mocker() as mock:
        mock.post(good_url, json=mcp_handler)
        mock.post(bad_url, status_code=503, text="down")

        results = discover_all({"good": good_url, "bad": bad_url})

        assert results["good"]["ok"] is True
        assert results["good"]["tools"] == TOOLS
        assert results["bad"]["ok"] is False
        assert "503" in results["bad"]["error"]
