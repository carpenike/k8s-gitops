"""Task-board relay: OpenProject's outgoing webhook in, a pointer to the right bot out.

OpenProject signs a webhook with HMAC-SHA1 (`X-OP-Signature: sha1=<hex>`) and
sends the whole work package. A Hermes webhook route accepts only SHA-256
schemes. So this endpoint verifies OpenProject's signature, decides which bot
(if any) the change is for, and posts that bot's Hermes route a short event
signed the way Hermes checks it (generic V2: hex HMAC-SHA256 of
`<timestamp>.<body>` in `X-Webhook-Signature-V2`, with `X-Webhook-Timestamp`).

The event is a pointer: the task id, why, and who made the change. No subject,
description or comment text is forwarded, so nothing written on the board
reaches a bot's prompt through here; the bot reads the task itself, as itself,
through the MCP tools.

Who is woken (OpenProject sends one event per aggregated journal, so a burst
of edits within its aggregation window, 5 minutes by default, is one event):

  - the assignee, when it is a bot and someone else made the change, unless
    the change closed the task;
  - the author, when it is a bot, someone else made the change, and the change
    closed the task (a handoff it created is done).

Where the event goes: a bot with an entry in RELAY_TARGETS lives outside
the cluster (a Grok Bot routine's webhook trigger). It gets the same pointer
plus the task's link, as a JSON POST with `Authorization: Bearer <key>`. Any
other bot is a Hermes bot, reached at RELAY_HERMES_URL with the signature
above.

A bot's own changes never wake that bot. "Closed the task" needs the previous
state, which only this process has seen: it keeps the last status per task in
memory. After a restart the first event on an already closed task counts as
the close, at most one extra notice per task.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from openproject_mcp.config import Settings

log = logging.getLogger(__name__)

HOOK_PATH = "/hooks/openproject"
EVENTS = {"work_package:created", "work_package:updated"}
EVENT_TYPE = "task_board"
MAX_BODY = 1_048_576
#: Logins as OpenProject allows them, minus anything that could not be a
#: Kubernetes namespace suffix.
_LOGIN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_STATE_LIMIT = 2048


@dataclass(frozen=True)
class Wake:
    bot: str
    reason: str  # assigned | updated | closed


@dataclass(frozen=True)
class _Seen:
    assignee: str | None
    closed: bool


def _login(user: Any) -> str | None:
    if isinstance(user, dict) and user.get("_type") == "User":
        login = user.get("login")
        if isinstance(login, str):
            return login
    return None


def _user_id(user: Any) -> int | None:
    if isinstance(user, dict) and isinstance(user.get("id"), int):
        return user["id"]
    return None


def verify_op_signature(secret: str, body: bytes, header: str | None) -> bool:
    """OpenProject's `X-OP-Signature`: `sha1=` + hex HMAC-SHA1 of the raw body."""
    if not secret or not header or not header.startswith("sha1="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(header[5:].strip().lower(), expected)


def hermes_headers(secret: str, body: bytes, delivery_id: str, now: int | None = None) -> dict:
    """Hermes' generic V2 signature, plus a delivery id it dedupes on."""
    ts = str(int(time.time()) if now is None else now)
    sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {
        "content-type": "application/json",
        "x-webhook-timestamp": ts,
        "x-webhook-signature-v2": sig,
        # Hermes reads webhook-id as the delivery id when no Svix signature
        # header is present; a redelivered OpenProject event keeps it.
        "webhook-id": delivery_id,
    }


class Relay:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self.bots = frozenset(settings.relay_bots)
        self.targets = {bot: (url, bearer) for bot, url, bearer in settings.relay_targets}
        self._seen: OrderedDict[int, _Seen] = OrderedDict()
        self._client = httpx.AsyncClient(timeout=10.0, transport=transport)

    @property
    def enabled(self) -> bool:
        s = self.settings
        return bool(
            s.openproject_webhook_secret and self.bots and (s.hermes_webhook_secret or self.targets)
        )

    def decide(self, event: dict[str, Any]) -> tuple[int | None, list[Wake], dict[str, Any]]:
        """Which bots this event wakes. Updates the per-task state."""
        action = event.get("action")
        wp = event.get("work_package")
        if action not in EVENTS or not isinstance(wp, dict) or not isinstance(wp.get("id"), int):
            return None, [], {}
        task_id = wp["id"]
        emb = wp.get("_embedded") if isinstance(wp.get("_embedded"), dict) else {}
        assignee = _login(emb.get("assignee"))
        author = _login(emb.get("author"))
        status = emb.get("status") if isinstance(emb.get("status"), dict) else {}
        closed = status.get("isClosed") is True
        actor_user = event.get("actor")
        actor = _login(actor_user)

        before = self._seen.pop(task_id, None)
        self._seen[task_id] = _Seen(assignee=assignee, closed=closed)
        while len(self._seen) > _STATE_LIMIT:
            self._seen.popitem(last=False)

        info = {"actor": actor or "unknown", "actor_id": _user_id(actor_user)}
        if actor is None:
            # Without an actor there is no telling a bot's own change from
            # someone else's, so wake no one (no loops).
            return task_id, [], info

        just_closed = closed and (before is None or not before.closed)
        wakes: list[Wake] = []
        if assignee in self.bots and assignee != actor and not just_closed:
            newly = action == "work_package:created" or (
                before is not None and before.assignee != assignee
            )
            wakes.append(Wake(assignee, "assigned" if newly else "updated"))
        if (just_closed and author in self.bots and author != actor
                and not any(w.bot == author for w in wakes)):
            wakes.append(Wake(author, "closed"))
        return task_id, wakes, info

    async def forward(self, wake: Wake, task_id: int, info: dict[str, Any], digest: str) -> int:
        payload = {
            "event_type": EVENT_TYPE,
            "bot": wake.bot,
            "task_id": task_id,
            "reason": wake.reason,
            "actor": info["actor"],
            "actor_id": info["actor_id"],
        }
        target = self.targets.get(wake.bot)
        if target is not None:
            url, bearer = target
            payload["task_url"] = f"{self.settings.web_base}/work_packages/{task_id}"
            body = json.dumps(payload, separators=(",", ":")).encode()
            headers = {"content-type": "application/json", "authorization": f"Bearer {bearer}"}
            kind = "external"
        elif self.settings.hermes_webhook_secret:
            body = json.dumps(payload, separators=(",", ":")).encode()
            url = self.settings.relay_hermes_url.format(bot=wake.bot)
            headers = hermes_headers(
                self.settings.hermes_webhook_secret, body, f"op-{digest}-{wake.bot}"
            )
            kind = "hermes"
        else:
            log.warning("relay: task %s -> %s: no target and no HERMES_WEBHOOK_SECRET",
                        task_id, wake.bot)
            return -1
        try:
            resp = await self._client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            log.warning(
                "relay: task %s -> %s (%s, %s) failed: %s",
                task_id, wake.bot, wake.reason, kind, exc.__class__.__name__,
            )
            return -1
        log.info("relay: task %s -> %s (%s, %s): HTTP %s", task_id, wake.bot, wake.reason,
                 kind, resp.status_code)
        return resp.status_code

    async def handle(self, request: Request) -> Response:
        if not self.enabled:
            return JSONResponse({"error": "relay not configured"}, status_code=404)
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return JSONResponse({"error": "body too large"}, status_code=413)
        body = await request.body()
        if len(body) > MAX_BODY:
            return JSONResponse({"error": "body too large"}, status_code=413)
        if not verify_op_signature(
            self.settings.openproject_webhook_secret, body, request.headers.get("x-op-signature")
        ):
            log.warning("relay: refused a request with a missing or bad X-OP-Signature")
            return JSONResponse({"error": "bad signature"}, status_code=401)
        try:
            event = json.loads(body)
        except ValueError:
            return JSONResponse({"error": "not JSON"}, status_code=400)
        if not isinstance(event, dict):
            return JSONResponse({"error": "not a JSON object"}, status_code=400)

        task_id, wakes, info = self.decide(event)
        if task_id is None:
            return JSONResponse({"status": "ignored", "action": str(event.get("action"))[:64]})
        digest = hashlib.sha256(body).hexdigest()[:24]
        results = {}
        for wake in wakes:
            if not _LOGIN.match(wake.bot):
                continue
            results[wake.bot] = await self.forward(wake, task_id, info, digest)
        if not wakes:
            log.info("relay: task %s by %s wakes no one", task_id, info["actor"])
        # Always 200 to OpenProject once the signature is good: it retries only
        # timeouts, and a bot that is down should not hold up its log.
        return JSONResponse({"status": "ok", "task": task_id, "woke": results})

    async def aclose(self) -> None:
        await self._client.aclose()
