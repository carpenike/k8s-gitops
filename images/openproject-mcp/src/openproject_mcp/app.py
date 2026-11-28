"""The ASGI app: streamable HTTP MCP at /mcp behind a bearer gate, /healthz open.

Request flow:
  BearerGate      /mcp* without `Authorization: Bearer <token>` -> 401, before
                  any MCP handling. /healthz passes through unauthenticated,
                  and so do /hooks/openproject, which checks OpenProject's own
                  webhook signature instead (relay.py), and /hooks/alertmanager,
                  which checks its own bearer token (alerts.py).
  MCP app         the SDK's Starlette app: Host allowlist (DNS-rebinding
                  check), then stateless streamable HTTP with JSON responses.
  tools           read the same bearer token from the request and use it for
                  every OpenProject call they make (HTTP Basic apikey:<token>).
"""

from __future__ import annotations

import json
import logging
import os

import httpx
import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from openproject_mcp import __version__
from openproject_mcp.alerts import HOOK_PATH as ALERTS_HOOK_PATH
from openproject_mcp.alerts import AlertRelay
from openproject_mcp.alerts import enabled as alerts_enabled
from openproject_mcp.config import Settings
from openproject_mcp.relay import HOOK_PATH, Relay
from openproject_mcp.tools import INSTRUCTIONS, OpenProject, bearer_token, register

log = logging.getLogger(__name__)

MCP_PATH = "/mcp"
HEALTH_PATH = "/healthz"
#: Paths that do their own auth (or need none), so BearerGate lets them through.
UNGATED = (HEALTH_PATH, HOOK_PATH, ALERTS_HOOK_PATH)


class BearerGate:
    """Refuse MCP requests that carry no bearer token, with 401, before MCP sees them.

    The token is not checked here: OpenProject checks it on the first call a
    tool makes. This only guarantees that no request reaches a tool anonymously.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "") not in UNGATED:
            header = next(
                (v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"authorization"),
                None,
            )
            if bearer_token(header) is None:
                body = json.dumps(
                    {
                        "error": {
                            "code": "unauthorized",
                            "message": "Missing bearer token.",
                            "hint": "Send Authorization: Bearer <your OpenProject API token>.",
                        }
                    }
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                            (b"www-authenticate", b'Bearer realm="openproject-mcp"'),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def build_app(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    relay_transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[BearerGate, OpenProject]:
    """The ASGI app and its OpenProject client. The transports are for tests."""
    op = OpenProject(settings, transport=transport)
    relay = Relay(settings, transport=relay_transport)
    alert_relay = AlertRelay(settings, transport=relay_transport)
    mcp = MCPServer(
        name="openproject",
        title="OpenProject task queue",
        instructions=INSTRUCTIONS,
        version=__version__,
    )
    register(mcp, op)

    @mcp.custom_route(HEALTH_PATH, methods=["GET"], include_in_schema=False)
    async def healthz(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route(HOOK_PATH, methods=["POST"], include_in_schema=False)
    async def openproject_hook(request: Request) -> Response:
        return await relay.handle(request)

    @mcp.custom_route(ALERTS_HOOK_PATH, methods=["POST"], include_in_schema=False)
    async def alertmanager_hook(request: Request) -> Response:
        return await alert_relay.handle(request)

    app = mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(settings.allowed_hosts),
            allowed_origins=[],
        ),
        host="0.0.0.0",  # noqa: S104 - the Pod's Service is the only way in
    )
    return BearerGate(app), op


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # httpx logs every request URL at INFO; keep it quiet (paths only via our own logs).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Stateless mode "terminates" a session after every request; not news.
    logging.getLogger("mcp.server.streamable_http").setLevel(logging.WARNING)
    settings = Settings.from_env()
    app, _ = build_app(settings)
    log.info(
        "openproject-mcp %s on :%d, OpenProject %s, default project %s",
        __version__,
        settings.port,
        settings.api_base,
        settings.default_project or "(none)",
    )
    external = sorted(bot for bot, _, _ in settings.relay_targets)
    log.info(
        "task-board relay at %s: %s",
        HOOK_PATH,
        f"on, bots {', '.join(settings.relay_bots)}; outside the cluster: "
        f"{', '.join(external) or 'none'}"
        if settings.openproject_webhook_secret and settings.relay_bots
        and (settings.hermes_webhook_secret or external)
        else "off (needs OPENPROJECT_WEBHOOK_SECRET, RELAY_BOTS, and HERMES_WEBHOOK_SECRET "
        "or RELAY_TARGETS)",
    )
    log.info(
        "alertmanager relay at %s: %s",
        ALERTS_HOOK_PATH,
        f"on, to {settings.alerts_bot}'s alerts route"
        if alerts_enabled(settings)
        else "off, 503 (needs ALERTMANAGER_HOOK_TOKEN, HERMES_WEBHOOK_SECRET and a valid "
        "ALERTS_BOT)",
    )
    for problem in settings.relay_target_errors:
        log.warning("task-board relay: %s; entry ignored", problem)
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104
        port=settings.port,
        workers=1,
        proxy_headers=False,
        server_header=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
