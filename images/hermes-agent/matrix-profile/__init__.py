"""matrix-profile: the bot reads and changes its own Matrix profile (display name, avatar).

Local Hermes plugin (k8s-gitops, images/hermes-agent/matrix-profile; docs/hermes.md,
"Matrix profile"). It uses the gateway's own Matrix login from the agent's environment
(MATRIX_HOMESERVER, MATRIX_ACCESS_TOKEN, MATRIX_USER_ID), read through Hermes' profile-scoped
secret reader and never returned to the model. Matrix lets any user set their own
``displayname`` and ``avatar_url`` (client-server API, /profile/{userId}/...); an avatar is first
uploaded to the homeserver's media repository (/_matrix/media/v3/upload).

A new display name is also written to the Hermes profile's ``display_name`` (``profile.yaml`` in
``HERMES_HOME``), the name the Hermes app shows for this agent, so Matrix and the app agree.

Guards:
- Matrix conversations only (``HERMES_SESSION_PLATFORM == "matrix"``): not the API server, the
  webhook, cron or the CLI, so a change comes from someone the Matrix allowlist admits.
- Avatars come from local image files under the shared workspace or Hermes' cache (where
  ``image_generate`` saves), after symlinks are resolved; PNG/JPEG/WebP/GIF only, at most 5 MiB.
  No URLs: the agent has no general internet egress, and a fetched file would be unvetted.
- Display names: 1-64 characters after trimming, no control characters.
"""

from __future__ import annotations

import json
import logging
import os
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TOOLSET = "matrix_profile"
_TIMEOUT = 30
_MAX_AVATAR_BYTES = 5 * 1024 * 1024
_MAX_NAME_CHARS = 64
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
         ".gif": "image/gif"}


def _secret(name: str) -> str:
    try:
        from agent.secret_scope import get_secret
        return (get_secret(name) or "").strip()
    except Exception:
        return (os.environ.get(name) or "").strip()


def _credentials() -> tuple[str, str, str]:
    return (_secret("MATRIX_HOMESERVER").rstrip("/"), _secret("MATRIX_ACCESS_TOKEN"),
            _secret("MATRIX_USER_ID"))


def _available() -> bool:
    return all(_credentials())


def _session_platform() -> str:
    try:
        from tools.approval_context import _get_session_platform
        return (_get_session_platform() or "").strip().lower()
    except Exception:
        return (os.environ.get("HERMES_SESSION_PLATFORM") or "").strip().lower()


def _allowed_roots() -> list[Path]:
    roots = [Path("/workspace")]
    try:
        from hermes_constants import get_hermes_home
        roots.append(Path(get_hermes_home()) / "cache")
    except Exception:
        roots.append(Path(os.environ.get("HERMES_HOME", "/opt/data")) / "cache")
    return [r.resolve() for r in roots]


def _result(ok: bool, **fields: Any) -> str:
    return json.dumps({"success": ok, **fields})


def _request(method: str, path: str, *, body: bytes | None = None, content_type: str = "application/json",
             query: dict[str, str] | None = None) -> dict[str, Any]:
    homeserver, token, _ = _credentials()
    url = homeserver + path + (("?" + urllib.parse.urlencode(query)) if query else "")
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Matrix {method} {path.split('?')[0]} failed: HTTP {exc.code} {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Matrix homeserver unreachable: {exc.reason}") from None
    return json.loads(raw or b"{}")


def _profile_path(user_id: str, field: str = "") -> str:
    path = "/_matrix/client/v3/profile/" + urllib.parse.quote(user_id, safe="")
    return path + ("/" + field if field else "")


def _hermes_profile_name() -> str:
    """The Hermes profile's display name, or "" when none is set or it cannot be read."""
    try:
        from hermes_cli.profiles import read_profile_meta
        from hermes_constants import get_hermes_home
        return read_profile_meta(Path(get_hermes_home())).get("display_name", "")
    except Exception:
        return ""


def _set_hermes_profile_name(name: str) -> str | None:
    """Write ``display_name`` into this profile's profile.yaml; an error message, or None."""
    try:
        from hermes_cli.profiles import write_profile_meta
        from hermes_constants import get_hermes_home
        write_profile_meta(Path(get_hermes_home()), display_name=name)
    except Exception as exc:
        logger.warning("matrix-profile: Hermes profile display name not updated: %s", exc)
        return f"{type(exc).__name__}: {exc}"
    return None


def _guard() -> str | None:
    """An error message when the call must be refused, else None."""
    if not _available():
        return "Matrix credentials are not available in this process."
    platform = _session_platform()
    if platform != "matrix":
        return ("Changing or reading the bot's Matrix profile is only allowed from a Matrix conversation "
                f"(this session's platform is {platform or 'unknown'!r}).")
    return None


def handle_get_profile(args: dict[str, Any], **_kw) -> str:
    if (err := _guard()) is not None:
        return _result(False, error=err)
    _, _, user_id = _credentials()
    try:
        prof = _request("GET", _profile_path(user_id))
    except Exception as exc:
        return _result(False, error=str(exc))
    return _result(True, user_id=user_id, display_name=prof.get("displayname"), avatar_url=prof.get("avatar_url"),
                   hermes_display_name=_hermes_profile_name() or None)


def handle_set_display_name(args: dict[str, Any], **_kw) -> str:
    if (err := _guard()) is not None:
        return _result(False, error=err)
    name = str(args.get("display_name") or "").strip()
    if not name or len(name) > _MAX_NAME_CHARS:
        return _result(False, error=f"display_name must be 1-{_MAX_NAME_CHARS} characters after trimming.")
    if any(unicodedata.category(ch).startswith("C") for ch in name):
        return _result(False, error="display_name must not contain control or formatting characters.")
    _, _, user_id = _credentials()
    try:
        _request("PUT", _profile_path(user_id, "displayname"), body=json.dumps({"displayname": name}).encode())
    except Exception as exc:
        return _result(False, error=str(exc))
    logger.info("matrix-profile: display name of %s set", user_id)
    # Matrix succeeded; the Hermes app's name follows. A failure there is reported, not fatal.
    if (err := _set_hermes_profile_name(name)) is not None:
        return _result(True, user_id=user_id, display_name=name, hermes_display_name_updated=False,
                       hermes_display_name_error=err)
    return _result(True, user_id=user_id, display_name=name, hermes_display_name_updated=True)


def handle_set_avatar(args: dict[str, Any], **_kw) -> str:
    if (err := _guard()) is not None:
        return _result(False, error=err)
    raw = str(args.get("image_path") or "").strip()
    if not raw:
        return _result(False, error="image_path is required.")
    try:
        path = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return _result(False, error=f"No such file: {raw}")
    roots = _allowed_roots()
    if not any(path == root or root in path.parents for root in roots):
        return _result(False, error="image_path must be under " + " or ".join(str(r) for r in roots) + ".")
    mime = _MIME.get(path.suffix.lower())
    if mime is None:
        return _result(False, error="Avatar must be a .png, .jpg, .jpeg, .webp or .gif file.")
    size = path.stat().st_size
    if not path.is_file() or size == 0 or size > _MAX_AVATAR_BYTES:
        return _result(False, error=f"Avatar file must be a non-empty file of at most {_MAX_AVATAR_BYTES} bytes.")
    _, _, user_id = _credentials()
    try:
        uploaded = _request("POST", "/_matrix/media/v3/upload", body=path.read_bytes(), content_type=mime,
                            query={"filename": "avatar" + path.suffix.lower()})
        mxc = uploaded.get("content_uri")
        if not isinstance(mxc, str) or not mxc.startswith("mxc://"):
            return _result(False, error="Homeserver returned no content_uri for the upload.")
        _request("PUT", _profile_path(user_id, "avatar_url"), body=json.dumps({"avatar_url": mxc}).encode())
    except Exception as exc:
        return _result(False, error=str(exc))
    logger.info("matrix-profile: avatar of %s set (%d bytes)", user_id, size)
    return _result(True, user_id=user_id, avatar_url=mxc, bytes=size)


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


_TOOLS = (
    ("matrix_get_profile", _schema(
        "matrix_get_profile",
        "Read your own Matrix profile: user ID, display name and avatar (mxc:// URL), plus the name "
        "the Hermes app shows for you (hermes_display_name).",
        {}, []), handle_get_profile, "🪪"),
    ("matrix_set_display_name", _schema(
        "matrix_set_display_name",
        "Change your own display name (1-64 characters): on Matrix, and the name the Hermes app shows "
        "for you. Only when the user asks for it in this Matrix conversation. Never use a real "
        "person's name.",
        {"display_name": {"type": "string", "description": "The new display name."}},
        ["display_name"]), handle_set_display_name, "🏷️"),
    ("matrix_set_avatar", _schema(
        "matrix_set_avatar",
        "Change your own Matrix profile picture from a local image file (PNG, JPEG, WebP or GIF, at most "
        "5 MiB) under /workspace or Hermes' cache, for example the path image_generate returned. Only "
        "when the user asks for it in this Matrix conversation.",
        {"image_path": {"type": "string", "description": "Absolute path of the image file."}},
        ["image_path"]), handle_set_avatar, "🖼️"),
)


def register(ctx) -> None:
    """Register the profile tools under toolset ``matrix_profile``."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handler,
                          check_fn=_available, description=schema["description"], emoji=emoji)
