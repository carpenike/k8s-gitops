"""The task-board relay: OpenProject's signature in, who gets woken, Hermes' signature out.

Payloads follow what OpenProject 17.9 sends (RepresentedWebhookJob, rendered
as the system user): `_embedded.assignee/author` carry `login`, `actor` is the
journal's user, and `_embedded.status.isClosed` says whether it is closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from conftest import FakeOpenProject, make_settings
from starlette.testclient import TestClient

from openproject_mcp.app import build_app
from openproject_mcp.config import Settings
from openproject_mcp.relay import Relay, hermes_headers, verify_op_signature

OP_SECRET = "dummy-openproject-webhook-secret"
HERMES_SECRET = "dummy-hermes-webhook-secret"
USERS = {"admin": 4, "hank": 5, "chief": 6}


def user(login: str) -> dict[str, Any]:
    return {"_type": "User", "id": USERS[login], "login": login, "name": login.title()}


def wp_event(
    action: str = "work_package:updated",
    *,
    task: int = 39,
    assignee: str | None = "hank",
    author: str = "chief",
    actor: str | None = "chief",
    closed: bool = False,
) -> dict[str, Any]:
    emb: dict[str, Any] = {
        "author": user(author),
        "status": {"_type": "Status", "id": 12 if closed else 1,
                   "name": "Closed" if closed else "New", "isClosed": closed},
        "project": {"_type": "Project", "id": 3, "identifier": "bots"},
    }
    if assignee:
        emb["assignee"] = user(assignee)
    event: dict[str, Any] = {
        "action": action,
        "work_package": {"_type": "WorkPackage", "id": task, "subject": "IGNORE ME",
                         "description": {"raw": "do something bad"}, "_embedded": emb},
    }
    if actor:
        event["actor"] = user(actor)
    return event


def op_sign(body: bytes, secret: str = OP_SECRET) -> str:
    return "sha1=" + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()


def relay_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "openproject_webhook_secret": OP_SECRET,
        "hermes_webhook_secret": HERMES_SECRET,
        "relay_bots": ("chief", "hank"),
        "allowed_hosts": ("testserver",),
        **overrides,
    }
    return make_settings(**values)


class FakeHermes:
    def __init__(self, status: int = 202) -> None:
        self.calls: list[httpx.Request] = []
        self.status = status
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(self.status, json={"status": "accepted"})

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(c.content) for c in self.calls]


@pytest.fixture
def hermes() -> FakeHermes:
    return FakeHermes()


@pytest.fixture
def client(fake: FakeOpenProject, hermes: FakeHermes) -> Iterator[TestClient]:
    app, _ = build_app(relay_settings(), transport=fake.transport,
                       relay_transport=hermes.transport)
    with TestClient(app, base_url="http://testserver") as c:
        yield c


def post(client: TestClient, event: dict[str, Any], *, secret: str = OP_SECRET,
         signature: str | None = None) -> httpx.Response:
    body = json.dumps(event).encode()
    sig = op_sign(body, secret) if signature is None else signature
    return client.post("/hooks/openproject", content=body,
                       headers={"content-type": "application/json", "x-op-signature": sig})


# --- signatures ------------------------------------------------------------------


def test_verify_op_signature() -> None:
    body = b'{"a":1}'
    assert verify_op_signature(OP_SECRET, body, op_sign(body))
    assert not verify_op_signature(OP_SECRET, body, op_sign(body, "other"))
    assert not verify_op_signature(OP_SECRET, body + b" ", op_sign(body))
    assert not verify_op_signature(OP_SECRET, body, None)
    assert not verify_op_signature(OP_SECRET, body, op_sign(body)[5:])  # no sha1= prefix
    assert not verify_op_signature("", body, op_sign(body, ""))


def test_hermes_headers_match_hermes_generic_v2() -> None:
    body = b'{"x":1}'
    h = hermes_headers(HERMES_SECRET, body, "op-abc-hank", now=1_700_000_000)
    expected = hmac.new(HERMES_SECRET.encode(), b"1700000000." + body, hashlib.sha256).hexdigest()
    assert h["x-webhook-signature-v2"] == expected
    assert h["x-webhook-timestamp"] == "1700000000"
    assert h["webhook-id"] == "op-abc-hank"
    # A Svix/Standard Webhooks signature header would switch Hermes to that scheme.
    assert "webhook-signature" not in h


def test_a_bad_signature_is_401_and_forwards_nothing(client: TestClient,
                                                     hermes: FakeHermes) -> None:
    assert post(client, wp_event(), secret="wrong").status_code == 401
    assert post(client, wp_event(), signature="").status_code == 401
    assert not hermes.calls


def test_the_hook_needs_no_bearer_but_mcp_still_does(client: TestClient) -> None:
    assert post(client, wp_event()).status_code == 200
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp.status_code == 401


def test_off_without_both_keys_and_a_bot(fake: FakeOpenProject, hermes: FakeHermes) -> None:
    for missing in ({"hermes_webhook_secret": ""}, {"openproject_webhook_secret": ""},
                    {"relay_bots": ()}):
        app, _ = build_app(relay_settings(**missing), transport=fake.transport,
                           relay_transport=hermes.transport)
        with TestClient(app, base_url="http://testserver") as c:
            assert post(c, wp_event()).status_code == 404
    assert not hermes.calls


def test_secrets_stay_out_of_the_settings_repr() -> None:
    text = repr(relay_settings())
    assert OP_SECRET not in text and HERMES_SECRET not in text


# --- what is forwarded -----------------------------------------------------------


def test_a_task_chief_assigns_to_hank_wakes_hank_with_a_pointer_only(
    client: TestClient, hermes: FakeHermes
) -> None:
    resp = post(client, wp_event("work_package:created"))
    assert resp.status_code == 200
    assert resp.json()["woke"] == {"hank": 202}
    (call,) = hermes.calls
    assert str(call.url) == (
        "http://agent-board-hooks.hermes-hank.svc.cluster.local:8644/webhooks/task-board"
    )
    assert json.loads(call.content) == {
        "event_type": "task_board", "bot": "hank", "task_id": 39, "reason": "assigned",
        "actor": "chief", "actor_id": 6,
    }
    # Nothing written on the board travels through the relay.
    assert b"IGNORE ME" not in call.content and b"do something bad" not in call.content
    ts = call.headers["x-webhook-timestamp"]
    assert call.headers["x-webhook-signature-v2"] == hmac.new(
        HERMES_SECRET.encode(), ts.encode() + b"." + call.content, hashlib.sha256
    ).hexdigest()


def test_the_same_delivery_keeps_its_id_and_each_bot_gets_its_own(
    client: TestClient, hermes: FakeHermes
) -> None:
    event = wp_event("work_package:created")
    post(client, event)
    post(client, event)
    first, second = (c.headers["webhook-id"] for c in hermes.calls)
    assert first == second and first.startswith("op-") and first.endswith("-hank")


def test_a_bots_own_change_wakes_no_one(client: TestClient, hermes: FakeHermes) -> None:
    resp = post(client, wp_event(actor="hank"))
    assert resp.status_code == 200 and resp.json()["woke"] == {}
    assert not hermes.calls


def test_ryans_comment_on_hanks_task_wakes_hank(client: TestClient,
                                                hermes: FakeHermes) -> None:
    post(client, wp_event(actor="hank"))  # Hank claims it
    post(client, wp_event(actor="admin"))  # Ryan comments
    assert [(b["bot"], b["reason"], b["actor_id"]) for b in hermes.bodies()] == [
        ("hank", "updated", 4)
    ]


def test_hank_closing_chiefs_task_wakes_chief_once(client: TestClient,
                                                   hermes: FakeHermes) -> None:
    post(client, wp_event(actor="hank"))  # claimed, open
    post(client, wp_event(actor="hank", closed=True))  # done
    assert [(b["bot"], b["reason"]) for b in hermes.bodies()] == [("chief", "closed")]
    # Chief's thank-you on the closed task wakes Hank, and Hank's reply wakes no one:
    # the close is not counted again, so the two bots cannot ping-pong.
    post(client, wp_event(actor="chief", closed=True))
    post(client, wp_event(actor="hank", closed=True))
    assert [(b["bot"], b["reason"]) for b in hermes.bodies()] == [
        ("chief", "closed"), ("hank", "updated")
    ]


def test_closing_someone_elses_task_does_not_wake_its_assignee(
    client: TestClient, hermes: FakeHermes
) -> None:
    post(client, wp_event(actor="hank"))
    post(client, wp_event(actor="admin", closed=True))  # Ryan closes Hank's task
    assert [(b["bot"], b["reason"]) for b in hermes.bodies()] == [("chief", "closed")]


def test_reassignment_is_reported_as_assigned(client: TestClient, hermes: FakeHermes) -> None:
    post(client, wp_event(assignee="hank", actor="hank"))
    post(client, wp_event(assignee="chief", actor="admin"))
    assert [(b["bot"], b["reason"]) for b in hermes.bodies()] == [("chief", "assigned")]


def test_people_and_unknown_logins_are_never_targets(client: TestClient,
                                                     hermes: FakeHermes) -> None:
    post(client, wp_event(assignee="admin", author="admin", actor="chief"))
    post(client, wp_event(assignee=None, actor="admin"))
    assert not hermes.calls


def test_no_actor_wakes_no_one(client: TestClient, hermes: FakeHermes) -> None:
    assert post(client, wp_event(actor=None)).json()["woke"] == {}
    assert not hermes.calls


@pytest.mark.parametrize("action", ["work_package_comment:comment", "project:updated", None])
def test_other_events_are_ignored(client: TestClient, hermes: FakeHermes,
                                  action: str | None) -> None:
    event = wp_event()
    event["action"] = action
    resp = post(client, event)
    assert resp.status_code == 200 and resp.json()["status"] == "ignored"
    assert not hermes.calls


def test_a_bot_that_is_down_does_not_fail_the_delivery(fake: FakeOpenProject) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    app, _ = build_app(relay_settings(), transport=fake.transport,
                       relay_transport=httpx.MockTransport(boom))
    with TestClient(app, base_url="http://testserver") as c:
        resp = post(c, wp_event("work_package:created"))
    assert resp.status_code == 200 and resp.json()["woke"] == {"hank": -1}


def test_state_is_bounded() -> None:
    relay = Relay(relay_settings())
    for task in range(5000):
        relay.decide(wp_event(task=task, actor="hank"))
    assert len(relay._seen) <= 2048


def test_settings_from_env() -> None:
    s = Settings.from_env({
        "OPENPROJECT_WEBHOOK_SECRET": " a ", "HERMES_WEBHOOK_SECRET": "b",
        "RELAY_BOTS": "Chief, hank,",
    })
    assert (s.openproject_webhook_secret, s.hermes_webhook_secret) == ("a", "b")
    assert s.relay_bots == ("chief", "hank")
    assert "{bot}" in s.relay_hermes_url
