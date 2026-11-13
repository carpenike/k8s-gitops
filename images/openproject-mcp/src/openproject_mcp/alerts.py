"""Alertmanager relay: an Alertmanager webhook in, one bot's Hermes `alerts` route out.

Alertmanager's webhook receiver can send a bearer token but cannot sign a
body, and a Hermes webhook route accepts only HMAC-SHA256 schemes. So
`POST /hooks/alertmanager` checks the bearer token (ALERTMANAGER_HOOK_TOKEN,
constant-time), reads the v4 payload, and posts the bot named by ALERTS_BOT a
plain-text rendering signed with Hermes' generic V2 scheme, using the same
HERMES_WEBHOOK_SECRET and the same Service and port as the task-board relay
(relay.py), at the path /webhooks/alerts.

Alertmanager re-sends a group on every repeat_interval. The relay forwards a
group only when:

  - it has not seen the group (by `groupKey`) before;
  - the group's status changed (firing -> resolved, resolved -> firing);
  - the group is firing and has a firing fingerprint it has not forwarded.

Anything else is a repeat and gets 200 `{"status": "duplicate"}`. The state is
in memory: resolved groups go after 24 hours, and at most 1000 groups are kept
(least recently changed first). A restart forgets it, so the forwarded event's
`webhook-id` is derived from what was forwarded (group, status, and each
alert's fingerprint and start time): Hermes drops a delivery id it has already
seen, which catches a repeat across a restart.

A forward the bot does not accept (transport error or a non-2xx answer) is a
502, and the group is not recorded as forwarded, so Alertmanager's own retry
delivers it.

Everything in the payload is data from whatever raised the alert: control and
format characters are stripped, each value and the whole body are capped, and
nothing in it selects a URL, a header or a bot.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from openproject_mcp.config import Settings
from openproject_mcp.relay import _LOGIN, hermes_headers

log = logging.getLogger(__name__)

HOOK_PATH = "/hooks/alertmanager"
EVENT_TYPE = "alertmanager"
MAX_BODY = 262_144
#: The rendered `body` the bot gets, in UTF-8 bytes, marker included.
BODY_LIMIT = 8192
TRUNCATED = "\u2026truncated"
SUBJECT_LIMIT = 200
LABEL_VALUE_LIMIT = 256
ANNOTATION_VALUE_LIMIT = 2048
URL_LIMIT = 512
#: Dedup state bounds.
MAX_GROUPS = 1000
RESOLVED_TTL = 24 * 3600
STATUSES = ("firing", "resolved")
#: Shown first, in this order; any other label follows, sorted.
LABEL_ORDER = ("namespace", "pod", "container", "job", "instance", "service", "node", "cluster")
ANNOTATION_ORDER = (("summary", "summary"), ("description", "description"),
                    ("runbook_url", "runbook"))
SEVERITY_RANK = {"critical": 5, "error": 4, "high": 4, "warning": 3, "medium": 3,
                 "info": 2, "low": 2, "none": 1}
#: Alertmanager's zero time: an alert that has not ended.
_ZERO_TIME = "0001-01-01T00:00:00Z"


def clean(value: Any, limit: int) -> str:
    """One line of text: control and format characters become spaces, capped at `limit`."""
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        # Cc: C0/C1 controls (incl. newlines and tabs); Cf: zero-width and bidi
        # overrides; Zl/Zp: line and paragraph separators.
        out.append(" " if cat in ("Cc", "Cf", "Zl", "Zp") else ch)
    text = " ".join("".join(out).split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def bearer_ok(expected: str, header: str | None) -> bool:
    """`Authorization: Bearer <expected>`, compared in constant time."""
    if not expected or not header:
        return False
    scheme, _, token = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(token.strip().encode(), expected.encode())


@dataclass(frozen=True)
class Alert:
    status: str
    fingerprint: str
    starts_at: str
    labels: dict[str, str]
    annotations: dict[str, str]
    ends_at: str
    generator_url: str


@dataclass(frozen=True)
class Notification:
    group_key: str
    status: str
    receiver: str
    external_url: str
    common_labels: dict[str, str]
    group_labels: dict[str, str]
    truncated_alerts: int
    alerts: tuple[Alert, ...]

    @property
    def firing(self) -> tuple[Alert, ...]:
        return tuple(a for a in self.alerts if a.status == "firing")

    def forwarded(self) -> tuple[Alert, ...]:
        """The alerts this status is about: the firing ones, or all for a resolved group."""
        return self.firing if self.status == "firing" else self.alerts


def _str_map(value: Any, limit: int) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return {clean(k, 128): clean(v, limit) for k, v in value.items() if clean(k, 128)}


def parse(event: Any) -> Notification | None:
    """An Alertmanager webhook v4 payload, or None if it is not one."""
    if not isinstance(event, dict) or event.get("version") != "4":
        return None
    group_key, status, raw_alerts = event.get("groupKey"), event.get("status"), event.get("alerts")
    if not (isinstance(group_key, str) and group_key) or status not in STATUSES:
        return None
    if not isinstance(raw_alerts, list) or not raw_alerts:
        return None
    alerts: list[Alert] = []
    for raw in raw_alerts:
        if not isinstance(raw, dict) or raw.get("status") not in STATUSES:
            return None
        labels = _str_map(raw.get("labels"), LABEL_VALUE_LIMIT)
        if labels is None:
            return None
        annotations = _str_map(raw.get("annotations") or {}, ANNOTATION_VALUE_LIMIT) or {}
        fingerprint = raw.get("fingerprint")
        if not (isinstance(fingerprint, str) and fingerprint.strip()):
            # Alertmanager always sends one; derive a stable stand-in if not.
            fingerprint = hashlib.sha256(
                json.dumps(sorted(labels.items())).encode()
            ).hexdigest()[:16]
        alerts.append(Alert(
            status=raw["status"],
            fingerprint=clean(fingerprint, 64),
            starts_at=clean(raw.get("startsAt"), 64),
            labels=labels,
            annotations=annotations,
            ends_at=clean(raw.get("endsAt"), 64),
            generator_url=clean(raw.get("generatorURL"), URL_LIMIT),
        ))
    truncated = event.get("truncatedAlerts")
    return Notification(
        group_key=group_key,
        status=status,
        receiver=clean(event.get("receiver"), 128),
        external_url=clean(event.get("externalURL"), URL_LIMIT),
        common_labels=_str_map(event.get("commonLabels"), LABEL_VALUE_LIMIT) or {},
        group_labels=_str_map(event.get("groupLabels"), LABEL_VALUE_LIMIT) or {},
        truncated_alerts=truncated if isinstance(truncated, int) and truncated > 0 else 0,
        alerts=tuple(alerts),
    )


def delivery_id(n: Notification) -> str:
    """Stable per (group, status, forwarded alerts): the same notice always gets the same id.

    Each alert's start time is in it too, so an alert that resolved and fired
    again is a new delivery to Hermes, while a repeat_interval re-send is not.
    """
    key = json.dumps(
        [n.group_key, n.status, sorted((a.fingerprint, a.starts_at) for a in n.forwarded())],
        separators=(",", ":"),
    )
    return "am-" + hashlib.sha256(key.encode()).hexdigest()


def severity(n: Notification) -> str:
    """commonLabels.severity, else the highest one among the alerts, else `unknown`."""
    common = n.common_labels.get("severity", "")
    if common:
        return common
    seen = {a.labels.get("severity", "") for a in n.forwarded()} - {""}
    if not seen:
        return "unknown"
    return max(sorted(seen), key=lambda s: SEVERITY_RANK.get(s.lower(), 0))


def subject(n: Notification) -> str:
    """`[FIRING] KubePodCrashLooping (warning) x3`."""
    name = (n.common_labels.get("alertname") or n.group_labels.get("alertname")
            or "multiple alerts")
    count = len(n.forwarded())
    return clean(f"[{n.status.upper()}] {name} ({severity(n)}) x{count}", SUBJECT_LIMIT)


def _render_alert(a: Alert) -> list[str]:
    head = f"[{a.status}] {a.labels.get('alertname', '(no alertname)')}"
    if a.labels.get("severity"):
        head += f" severity={a.labels['severity']}"
    rest = [k for k in LABEL_ORDER if k in a.labels]
    rest += sorted(k for k in a.labels if k not in LABEL_ORDER and k not in ("alertname",
                                                                            "severity"))
    lines = [head]
    if rest:
        lines.append("  labels: " + " ".join(f"{k}={a.labels[k]}" for k in rest))
    for key, title in ANNOTATION_ORDER:
        if a.annotations.get(key):
            lines.append(f"  {title}: {a.annotations[key]}")
    when = f"  starts: {a.starts_at or '?'}"
    if a.ends_at and a.ends_at != _ZERO_TIME and a.status == "resolved":
        when += f"  ends: {a.ends_at}"
    lines.append(when)
    if a.generator_url:
        lines.append(f"  source: {a.generator_url}")
    return lines


def _fit(text: str, limit: int) -> str:
    """Cut `text` to at most `limit` UTF-8 bytes, on a character boundary."""
    data = text.encode()
    if len(data) <= limit:
        return text
    return data[:limit].decode(errors="ignore")


def render(n: Notification, limit: int = BODY_LIMIT) -> str:
    """Plain text, one block per alert (firing first), at most `limit` UTF-8 bytes."""
    group = " ".join(f"{k}={v}" for k, v in sorted(n.group_labels.items()))
    header = f"Alertmanager group {n.status}: {len(n.alerts)} alert(s)"
    if group:
        header += f", grouped by {group}"
    if n.truncated_alerts:
        header += f"; {n.truncated_alerts} more not sent by Alertmanager (max_alerts)"
    blocks = [header]
    ordered = sorted(n.alerts, key=lambda a: a.status != "firing")
    for a in ordered:
        blocks.append("\n".join(_render_alert(a)))
    text = "\n\n".join(blocks)
    if len(text.encode()) <= limit:
        return text
    marker = "\n" + TRUNCATED
    return _fit(text, limit - len(marker.encode())).rstrip() + marker


def forward_payload(n: Notification, bot: str) -> dict[str, Any]:
    """What the bot's Hermes route gets.

    Its filters key on `event_type`, `bot`, `status`, and need `subject` and
    `body`; the shape mirrors the board relay's `event_type` + `bot`.
    """
    return {
        "event_type": EVENT_TYPE,
        "bot": bot,
        "subject": subject(n),
        "body": render(n),
        "priority": severity(n),
        "status": n.status,
        "group_key": clean(n.group_key, 512),
        "external_url": n.external_url,
    }


def enabled(s: Settings) -> bool:
    """On once there is a token to check, a key to sign with, and a valid bot."""
    return bool(s.alertmanager_hook_token and s.hermes_webhook_secret
                and _LOGIN.match(s.alerts_bot))


@dataclass
class _Group:
    status: str
    fingerprints: frozenset[str]
    updated: float


class AlertRelay:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self._groups: OrderedDict[str, _Group] = OrderedDict()
        # One notification at a time: a concurrent repeat must see the first
        # one's outcome, not race it to the bot.
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=10.0, transport=transport)

    @property
    def enabled(self) -> bool:
        return enabled(self.settings)

    @property
    def url(self) -> str:
        return self.settings.alerts_url.format(bot=self.settings.alerts_bot)

    def _prune(self, now: float) -> None:
        stale = [k for k, g in self._groups.items()
                 if g.status == "resolved" and now - g.updated > RESOLVED_TTL]
        for key in stale:
            del self._groups[key]
        while len(self._groups) > MAX_GROUPS:
            self._groups.popitem(last=False)

    def is_new(self, n: Notification) -> bool:
        """Whether this notification is news for its group (see the module docstring)."""
        seen = self._groups.get(n.group_key)
        if seen is None or seen.status != n.status:
            return True
        if n.status == "firing":
            return not {a.fingerprint for a in n.firing} <= seen.fingerprints
        return False

    def record(self, n: Notification) -> None:
        """Mark this notification as forwarded."""
        now = self._clock()
        seen = self._groups.pop(n.group_key, None)
        fingerprints = frozenset(a.fingerprint for a in n.firing)
        if seen is not None and seen.status == n.status == "firing":
            fingerprints |= seen.fingerprints
        self._groups[n.group_key] = _Group(n.status, fingerprints, now)
        self._prune(now)

    async def _read(self, request: Request) -> bytes | None:
        """The body, or None once it passes MAX_BODY (it is not read further)."""
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return None
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY:
                return None
            chunks.append(chunk)
        return b"".join(chunks)

    async def handle(self, request: Request) -> Response:
        if not self.enabled:
            return JSONResponse({"error": "alert relay not configured"}, status_code=503)
        if not bearer_ok(self.settings.alertmanager_hook_token,
                         request.headers.get("authorization")):
            log.warning("alerts: refused a request with a missing or wrong bearer token")
            return JSONResponse({"error": "unauthorized"}, status_code=401,
                                headers={"www-authenticate": 'Bearer realm="alertmanager"'})
        try:
            body = await self._read(request)
        except ValueError:
            body = None
        if body is None:
            return JSONResponse({"error": "body too large"}, status_code=413)
        try:
            event = json.loads(body)
        except ValueError:
            return JSONResponse({"error": "not JSON"}, status_code=400)
        n = parse(event)
        if n is None:
            return JSONResponse({"error": "not an Alertmanager v4 payload"}, status_code=400)

        ref = hashlib.sha256(n.group_key.encode()).hexdigest()[:12]
        async with self._lock:
            if not self.is_new(n):
                log.info("alerts: group %s %s: duplicate, dropped", ref, n.status)
                return JSONResponse({"status": "duplicate"})
            payload = json.dumps(forward_payload(n, self.settings.alerts_bot),
                                 separators=(",", ":")).encode()
            headers = hermes_headers(self.settings.hermes_webhook_secret, payload,
                                     delivery_id(n))
            try:
                resp = await self._client.post(self.url, content=payload, headers=headers)
                code = resp.status_code
            except httpx.HTTPError as exc:
                log.warning("alerts: group %s %s -> %s failed: %s", ref, n.status,
                            self.settings.alerts_bot, exc.__class__.__name__)
                code = -1
            if not 200 <= code < 300:
                if code != -1:
                    log.warning("alerts: group %s %s -> %s: HTTP %s", ref, n.status,
                                self.settings.alerts_bot, code)
                # Not recorded: Alertmanager retries a failed notification.
                return JSONResponse({"error": "bot did not accept the alert",
                                     "bot_status": code}, status_code=502)
            self.record(n)
        log.info("alerts: group %s %s (%d alerts) -> %s: HTTP %s", ref, n.status,
                 len(n.forwarded()), self.settings.alerts_bot, code)
        return JSONResponse({"status": "forwarded"}, status_code=202)

    async def aclose(self) -> None:
        await self._client.aclose()
