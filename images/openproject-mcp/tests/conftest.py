"""Shared fixtures: a fake OpenProject behind httpx.MockTransport.

The JSON under fixtures/ are full API v3 HAL documents (ported from
homelab-mcp's tests/fixtures/openproject, synthesized to OpenProject's API v3
reference: full `_links`, null hrefs for empty links, Collection envelopes,
UpdateConflict errors), so the projection is tested against the wire shape.
User documents follow OpenProject's UserRepresenter: `login` appears only
when the caller is that user (or holds manage_user/create_user).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from openproject_mcp.config import Settings
from openproject_mcp.tools import OpenProject

API_BASE = "http://openproject.test:8080"
FIXTURES = Path(__file__).parent / "fixtures"

# Dummy tokens; OpenProject's are 64 hex characters, these are obviously not.
TOKEN_HOMELAB = "dummy-token-homelab"
TOKEN_FINANCES = "dummy-token-finances"
TOKEN_HANK = "dummy-token-hank"


def fx(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def basic(token: str) -> str:
    return "Basic " + base64.b64encode(f"apikey:{token}".encode()).decode()


class FakeOpenProject:
    """Route (method, path) to queued recorded responses; record every request.

    A route with several queued responses serves them in order and repeats the
    last — which is how a work package "changes underneath" a claim. `/users/me`
    answers by the token in the Basic header.
    """

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list[tuple[int, Any]]] = {}
        self.calls: list[httpx.Request] = []
        self.me: dict[str, Any] = {
            TOKEN_HOMELAB: fx("users_me_homelab"),
            TOKEN_FINANCES: fx("users_me_finances"),
            TOKEN_HANK: fx("users_me_hank"),
        }
        self.on("GET", "/statuses", fx("statuses"))
        self.on("GET", "/priorities", fx("priorities"))
        self.on("GET", "/types", fx("types"))
        self.on("GET", "/projects/homelab", fx("project_homelab"))
        self.on("GET", "/projects/bots-shared", fx("project_shared"))
        # The create form of project 5 (homelab) carries the board's handoff
        # fields: customField7 "Context" (String), customField8 "Done when"
        # (Formattable). A test that needs them absent overrides this route.
        self.on("POST", "/projects/5/work_packages/form", fx("wp_form_with_handoff_fields"))
        self.transport = httpx.MockTransport(self._handle)

    def on(self, method: str, path: str, *responses: Any, status: int = 200) -> None:
        self.routes[(method, path)] = [
            r if isinstance(r, tuple) else (status, r) for r in responses
        ]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path.removeprefix("/api/v3")
        if request.method == "GET" and path == "/users/me":
            auth = request.headers.get("authorization", "")
            token = ""
            if auth.startswith("Basic "):
                token = base64.b64decode(auth[6:]).decode().partition(":")[2]
            user = self.me.get(token)
            if user is None:
                return httpx.Response(
                    401,
                    json={
                        "_type": "Error",
                        "errorIdentifier": "urn:openproject-org:api:v3:errors:Unauthenticated",
                        "message": "You did not provide the correct credentials.",
                    },
                )
            return httpx.Response(200, json=user)
        queue = self.routes.get((request.method, path))
        if not queue:
            return httpx.Response(404, json={"_type": "Error", "message": f"no route {path}"})
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(status, json=body)

    def sent(self, method: str, path: str) -> list[dict[str, Any]]:
        return [
            json.loads(c.content)
            for c in self.calls
            if c.method == method and c.url.path == "/api/v3" + path
        ]

    def query(self, method: str, path: str) -> list[dict[str, list[str]]]:
        return [
            parse_qs(urlsplit(str(c.url)).query)
            for c in self.calls
            if c.method == method and c.url.path == "/api/v3" + path
        ]

    def filters(self, method: str, path: str, index: int = 0) -> list[dict[str, Any]]:
        return json.loads(self.query(method, path)[index]["filters"][0])


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"url": API_BASE + "/", **overrides}
    return Settings(**values)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake() -> FakeOpenProject:
    return FakeOpenProject()


@pytest.fixture
def make_op(fake: FakeOpenProject):
    def make(**overrides: Any) -> OpenProject:
        return OpenProject(make_settings(**overrides), transport=fake.transport)

    return make


@pytest.fixture
def op(make_op) -> OpenProject:
    return make_op()
