"""Settings from the environment.

The server holds no OpenProject credentials: every MCP request brings the
caller's own OpenProject API token as `Authorization: Bearer <token>`. The
only secrets are the task-board relay's two HMAC keys (relay.py), kept out of
the dataclass repr.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

DEFAULT_URL = "http://openproject.openproject.svc.cluster.local:8080"
DEFAULT_ALLOWED_HOSTS = (
    "openproject-mcp.openproject.svc.cluster.local:*,"
    "openproject-mcp.openproject.svc:*,"
    "openproject-mcp:*,"
    "localhost:*,"
    "127.0.0.1:*"
)
DEFAULT_RELAY_HERMES_URL = (
    "http://agent-board-hooks.hermes-{bot}.svc.cluster.local:8644/webhooks/task-board"
)


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def normalize_base(url: str) -> str:
    """Strip a trailing slash and a trailing `/api/v3`."""
    base = url.strip().rstrip("/")
    if base.endswith("/api/v3"):
        base = base[: -len("/api/v3")]
    return base


def expand_hosts(hosts: list[str]) -> list[str]:
    """`name:*` also allows the bare `name` (a Host header on port 80 has no port)."""
    out: list[str] = []
    for host in hosts:
        for item in (host, host[:-2] if host.endswith(":*") else None):
            if item and item not in out:
                out.append(item)
    return out


@dataclass(frozen=True)
class Settings:
    #: API calls go here (the in-cluster Service).
    url: str = DEFAULT_URL
    #: Human-facing links (`url` on tasks) use this; falls back to `url`.
    public_url: str = ""
    default_project: str | None = None
    ready_statuses: tuple[str, ...] = ("New",)
    in_progress_status: str = "In progress"
    done_status: str = "Closed"
    release_status: str = "New"
    claim_max_attempts: int = 5
    cache_seconds: int = 600
    port: int = 8000
    allowed_hosts: tuple[str, ...] = field(
        default_factory=lambda: tuple(expand_hosts(_csv(DEFAULT_ALLOWED_HOSTS)))
    )
    #: Task-board relay (relay.py). Off unless both keys and a bot are set.
    openproject_webhook_secret: str = field(default="", repr=False)
    hermes_webhook_secret: str = field(default="", repr=False)
    relay_bots: tuple[str, ...] = ()
    relay_hermes_url: str = DEFAULT_RELAY_HERMES_URL

    @property
    def api_base(self) -> str:
        return normalize_base(self.url)

    @property
    def web_base(self) -> str:
        return normalize_base(self.public_url) if self.public_url.strip() else self.api_base

    @property
    def identity_seconds(self) -> int:
        """`/users/me` per token: a short TTL, never longer than CACHE_SECONDS."""
        return min(60, self.cache_seconds)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        ready = _csv(env.get("OPENPROJECT_READY_STATUSES", "")) or ["New"]
        return cls(
            url=env.get("OPENPROJECT_URL", "").strip() or DEFAULT_URL,
            public_url=env.get("OPENPROJECT_PUBLIC_URL", "").strip(),
            default_project=env.get("OPENPROJECT_DEFAULT_PROJECT", "").strip() or None,
            ready_statuses=tuple(ready),
            in_progress_status=env.get("OPENPROJECT_IN_PROGRESS_STATUS", "").strip()
            or "In progress",
            done_status=env.get("OPENPROJECT_DONE_STATUS", "").strip() or "Closed",
            release_status=env.get("OPENPROJECT_RELEASE_STATUS", "").strip() or "New",
            claim_max_attempts=_int(env, "OPENPROJECT_CLAIM_MAX_ATTEMPTS", 5, 1, 20),
            cache_seconds=_int(env, "OPENPROJECT_CACHE_SECONDS", 600, 0, 86400),
            port=_int(env, "PORT", 8000, 1, 65535),
            allowed_hosts=tuple(
                expand_hosts(_csv(env.get("ALLOWED_HOSTS", "")) or _csv(DEFAULT_ALLOWED_HOSTS))
            ),
            openproject_webhook_secret=env.get("OPENPROJECT_WEBHOOK_SECRET", "").strip(),
            hermes_webhook_secret=env.get("HERMES_WEBHOOK_SECRET", "").strip(),
            relay_bots=tuple(b.lower() for b in _csv(env.get("RELAY_BOTS", ""))),
            relay_hermes_url=env.get("RELAY_HERMES_URL", "").strip() or DEFAULT_RELAY_HERMES_URL,
        )
