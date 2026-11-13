"""The HTTP surface: bearer gate, /healthz, Host allowlist, and MCP over
streamable HTTP end to end (initialize, tools/list, tools/call)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from conftest import TOKEN_HOMELAB, FakeOpenProject, basic, make_settings
from starlette.testclient import TestClient

from openproject_mcp.app import build_app

TOOLS = {
    "whoami",
    "claim_next",
    "complete_task",
    "release_task",
    "list_tasks",
    "get_task",
    "add_comment",
    "create_task",
}
READ_ONLY = {"whoami", "list_tasks", "get_task"}
MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-06-18",
}


@pytest.fixture
def client(fake: FakeOpenProject) -> Iterator[TestClient]:
    app, _ = build_app(
        make_settings(allowed_hosts=("testserver", "localhost:*")), transport=fake.transport
    )
    with TestClient(app, base_url="http://testserver") as c:
        yield c


def rpc(
    client: TestClient, method: str, params: dict[str, Any] | None = None, *, token: str = "x"
) -> Any:
    headers = {**MCP_HEADERS, "authorization": f"Bearer {token}"}
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=headers)


def initialize(client: TestClient, token: str = "x") -> Any:
    return rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
        token=token,
    )


def test_healthz_needs_no_token(client: TestClient, fake: FakeOpenProject) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}
    assert not fake.calls


@pytest.mark.parametrize(
    "auth", [None, "", "Bearer", "Bearer   ", "Basic YXBpa2V5OnRva2Vu", "bogus"]
)
def test_mcp_without_a_bearer_token_is_401_before_mcp(
    client: TestClient, fake: FakeOpenProject, auth: str | None
) -> None:
    headers = dict(MCP_HEADERS)
    if auth is not None:
        headers["authorization"] = auth
    resp = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers
    )
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Bearer")
    assert resp.json()["error"]["code"] == "unauthorized"
    assert not fake.calls


def test_a_host_outside_the_allowlist_is_refused(fake: FakeOpenProject) -> None:
    app, _ = build_app(make_settings(), transport=fake.transport)  # default allowlist
    with TestClient(app, base_url="http://evil.example") as c:
        resp = initialize(c)
    assert resp.status_code == 421


def test_initialize_and_tools_list_with_any_bearer(
    client: TestClient, fake: FakeOpenProject
) -> None:
    resp = initialize(client, token="dummy")
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert result["serverInfo"]["name"] == "openproject"
    assert "claim_next" in result.get("instructions", "")

    resp = rpc(client, "tools/list", {}, token="dummy")
    assert resp.status_code == 200, resp.text
    tools = {t["name"]: t for t in resp.json()["result"]["tools"]}
    assert set(tools) == TOOLS
    for name, tool in tools.items():
        ann = tool["annotations"]
        assert ann["readOnlyHint"] is (name in READ_ONLY), name
        assert ann["destructiveHint"] is False, name
        assert len(tool["description"]) > 80, name
        # The token is never a tool argument; identity comes from the header.
        assert not {"bot", "token"} & set(tool["inputSchema"].get("properties", {})), name
    assert tools["create_task"]["inputSchema"]["required"] == ["subject", "context", "done_when"]
    assert set(tools["get_task"]["inputSchema"]["required"]) == {"task_id"}
    # Listing tools needs no OpenProject at all.
    assert not fake.calls


def test_tools_call_passes_the_bearer_token_through_as_basic_apikey(
    client: TestClient, fake: FakeOpenProject
) -> None:
    resp = rpc(
        client, "tools/call", {"name": "whoami", "arguments": {}}, token=TOKEN_HOMELAB
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert result.get("isError") is not True
    assert result["structuredContent"]["login"] == "bot-homelab"
    assert result["structuredContent"]["id"] == 21
    (call,) = fake.calls
    assert call.url.path == "/api/v3/users/me"
    assert call.headers["authorization"] == basic(TOKEN_HOMELAB)


def test_a_token_openproject_rejects_comes_back_as_a_tool_error_payload(
    client: TestClient,
) -> None:
    resp = rpc(client, "tools/call", {"name": "whoami", "arguments": {}}, token="wrong")
    assert resp.status_code == 200
    assert resp.json()["result"]["structuredContent"]["error"]["code"] == "openproject_bad_token"
