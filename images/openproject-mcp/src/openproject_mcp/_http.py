"""HTTP plumbing: one error shape, a safe path encoder, one request helper.

Ported from homelab-mcp (src/homelab_mcp/tools/_http.py, MIT, same author;
LICENSE.homelab-mcp), trimmed to what this server uses.

Every tool returns ``{"error": {"code": ..., "message": ..., "hint": ...}}``
on failure and never raises to the MCP transport: tools catch `ToolError` at
the boundary and return `err.payload()`.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)


class ToolError(Exception):
    """An upstream/validation failure carrying a stable `code` for the client.

    Never carries secrets or a raw upstream body.
    """

    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "hint": self.hint}}


def enc(segment: str) -> str:
    """URL-encode a single path segment, leaving no '/' to enable traversal."""
    return quote(segment, safe="")


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    service: str,
    params: dict[str, Any] | None = None,
    json: Any | None = None,
    headers: dict[str, str] | None = None,
    unreachable_hint: str = "",
) -> Any:
    """Perform a request and return decoded JSON, mapping failures to ToolError.

      - transport failure  -> ToolError("{service}_unreachable", ...)
      - HTTP >= 400        -> ToolError("{service}_http_{status}", <detail>)
      - non-JSON 2xx body  -> ToolError("{service}_http_{status}", "non-JSON …")

    Only the method, the URL path and the exception class are logged — never
    params, bodies, headers, or auth.
    """
    try:
        resp = await client.request(method, url, params=params, json=json, headers=headers)
    except httpx.HTTPError as exc:
        log.warning(
            "%s %s %s failed: %s", service, method, httpx.URL(url).path, exc.__class__.__name__
        )
        raise ToolError(
            f"{service}_unreachable",
            f"Could not reach {service} ({exc.__class__.__name__}).",
            unreachable_hint,
        ) from exc

    if resp.status_code >= 400:
        detail: str | None = None
        try:
            body = resp.json()
            if isinstance(body, dict):
                detail = body.get("message") or body.get("error")
        except ValueError:
            detail = (resp.text or "")[:200] or None
        raise ToolError(
            f"{service}_http_{resp.status_code}",
            str(detail) if detail else f"{service} returned HTTP {resp.status_code}.",
            "",
        )

    if resp.status_code == 204 or not resp.content:
        return None
    try:
        return resp.json()
    except ValueError as exc:
        raise ToolError(
            f"{service}_http_{resp.status_code}",
            f"{service} returned a non-JSON response.",
            "",
        ) from exc
