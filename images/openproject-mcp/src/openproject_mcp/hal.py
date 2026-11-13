"""Pure helpers for the openproject_* tools: HAL in, slim objects out.

Ported from homelab-mcp (src/homelab_mcp/tools/_openproject.py, MIT, same
author; LICENSE.homelab-mcp). Changes: comments carry the author's id and an
optional login, and principal helpers for assignee resolution.

OpenProject's API v3 speaks HAL+JSON. A single work package is ~4 KB of
`_links` (every possible action, schema and attachment endpoint) wrapped around
a dozen fields a bot actually needs, and the human-readable names live as
`_links.<rel>.title` rather than as plain attributes. Handing that to a model
burns context and invites it to follow links it has no business following.

Everything here is a pure function of decoded JSON — no I/O, no clock, no
settings — so `tests/test_hal.py` can pin the projection against recorded HAL
documents without an HTTP mock. The I/O half lives in `tools.py`.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

#: API v3 lives under this path on every OpenProject instance.
API = "/api/v3"

#: Default cap for the plain-text description excerpt.
DESCRIPTION_CHARS = 500

_HREF_ID_RE = re.compile(r"/(\d+)/?$")
_TAG_RE = re.compile(r"<[^>]+>")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_QUOTE_RE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_MD_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_MD_EMPHASIS_RE = re.compile(r"(\*{1,3}|_{2,3}|~~|`+)")
_WS_RE = re.compile(r"\s+")


def href_id(link: Any) -> int | None:
    """The trailing numeric id of a HAL link (`/api/v3/users/7` -> 7), else None."""
    if not isinstance(link, dict):
        return None
    href = link.get("href")
    if not isinstance(href, str):
        return None
    match = _HREF_ID_RE.search(href)
    return int(match.group(1)) if match else None


def link_title(links: Any, rel: str) -> str | None:
    """`_links[rel].title`, or None when the link is absent or empty (href null)."""
    if not isinstance(links, dict):
        return None
    link = links.get(rel)
    if not isinstance(link, dict) or link.get("href") is None:
        return None
    title = link.get("title")
    return title if isinstance(title, str) else None


def plain_text(raw: Any, limit: int = DESCRIPTION_CHARS) -> tuple[str, bool]:
    """Flatten OpenProject's markdown/HTML `raw` text to one plain line.

    Returns `(text, truncated)`. Good enough for an excerpt a model reads to
    decide whether to open the task — NOT a markdown renderer. Link text is
    kept, link targets and images are dropped, emphasis markers and HTML tags
    are removed, whitespace collapses to single spaces.
    """
    if not isinstance(raw, str) or not raw.strip():
        return "", False
    text = _TAG_RE.sub(" ", raw)
    text = _MD_IMAGE_RE.sub(lambda m: m.group(1), text)
    text = _MD_LINK_RE.sub(lambda m: m.group(1), text)
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_QUOTE_RE.sub("", text)
    text = _MD_BULLET_RE.sub("", text)
    text = _MD_EMPHASIS_RE.sub("", text)
    text = _WS_RE.sub(" ", html.unescape(text)).strip()
    if len(text) <= limit:
        return text, False
    cut = text[:limit].rstrip()
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut + "…", True


def elements(collection: Any) -> list[dict[str, Any]]:
    """`_embedded.elements` of a HAL collection; [] for anything else."""
    if not isinstance(collection, dict):
        return []
    embedded = collection.get("_embedded")
    if not isinstance(embedded, dict):
        return []
    items = embedded.get("elements")
    return [e for e in items if isinstance(e, dict)] if isinstance(items, list) else []


def collection_total(collection: Any, fallback: int) -> int:
    """The collection's `total` (matches across ALL pages), else `fallback`."""
    if isinstance(collection, dict):
        total = collection.get("total")
        if isinstance(total, int):
            return total
    return fallback


def slim_work_package(
    wp: dict[str, Any], *, web_base: str = "", description_chars: int = DESCRIPTION_CHARS
) -> dict[str, Any]:
    """Project one HAL work package to the fields a bot works with."""
    links = wp.get("_links") or {}
    description = wp.get("description")
    raw = description.get("raw") if isinstance(description, dict) else None
    text, truncated = plain_text(raw, description_chars)
    wp_id = wp.get("id")
    return {
        "id": wp_id,
        "subject": wp.get("subject"),
        "type": link_title(links, "type"),
        "status": link_title(links, "status"),
        "status_id": href_id(links.get("status")),
        "assignee": link_title(links, "assignee"),
        "assignee_id": href_id(links.get("assignee")),
        "project": link_title(links, "project"),
        "project_id": href_id(links.get("project")),
        "priority": link_title(links, "priority"),
        "due_date": wp.get("dueDate"),
        "lock_version": wp.get("lockVersion"),
        "description": text,
        "description_truncated": truncated,
        "updated_at": wp.get("updatedAt"),
        "url": f"{web_base}/work_packages/{wp_id}" if web_base and wp_id is not None else None,
    }


def slim_comments(
    activities: Any, limit: int, logins: dict[int, str | None] | None = None
) -> list[dict[str, Any]]:
    """The newest `limit` human comments from an activities collection, newest first.

    Most activities are field-change journals with an empty comment; those are
    dropped. OpenProject returns activities oldest first. `logins` maps author
    user ids to logins (None when OpenProject hides it from the caller).
    """
    logins = logins or {}
    out: list[dict[str, Any]] = []
    for activity in elements(activities):
        comment = activity.get("comment")
        raw = comment.get("raw") if isinstance(comment, dict) else None
        if not isinstance(raw, str) or not raw.strip():
            continue
        text, _ = plain_text(raw, DESCRIPTION_CHARS)
        links = activity.get("_links")
        author_id = href_id((links or {}).get("user") if isinstance(links, dict) else None)
        out.append(
            {
                "id": activity.get("id"),
                "author": link_title(links, "user"),
                "author_id": author_id,
                "author_login": logins.get(author_id) if author_id is not None else None,
                "created_at": activity.get("createdAt"),
                "text": text,
            }
        )
    out.reverse()
    return out[:limit]


def slim_user(user: Any) -> dict[str, Any]:
    """`{id, login, name}` of a User/principal. `login` is None when hidden.

    OpenProject shows `login` only to the user themself and to users holding
    the global manage_user/create_user permission; everyone else sees `name`.
    """
    if not isinstance(user, dict):
        return {"id": None, "login": None, "name": None}
    login = user.get("login")
    name = user.get("name")
    uid = user.get("id")
    return {
        "id": uid if isinstance(uid, int) else None,
        "login": login if isinstance(login, str) and login else None,
        "name": name if isinstance(name, str) else None,
    }


def link(kind: str, ident: int | None) -> dict[str, str | None]:
    """A HAL link body for a PATCH/POST: `{"href": "/api/v3/<kind>/<id>"}` or null."""
    return {"href": None if ident is None else f"{API}/{kind}/{ident}"}


def filters_json(filters: list[dict[str, Any]]) -> str:
    """Encode API v3 `filters` (it is a JSON string in the query, not nested params)."""
    return json.dumps(filters, separators=(",", ":"))


def id_filter(name: str, ids: list[int]) -> dict[str, Any]:
    """`{name: {operator: "=", values: [ids]}}`."""
    return {name: {"operator": "=", "values": [str(i) for i in ids]}}


#: Claim order: most important first, then soonest due, then oldest.
CLAIM_SORT = json.dumps([["priority", "desc"], ["dueDate", "asc"], ["id", "asc"]])
#: List order: most recently touched first.
LIST_SORT = json.dumps([["updatedAt", "desc"]])


def is_unassigned(wp: dict[str, Any]) -> bool:
    """True when the work package has no assignee."""
    return href_id((wp.get("_links") or {}).get("assignee")) is None


def status_id(wp: dict[str, Any]) -> int | None:
    """The work package's current status id."""
    return href_id((wp.get("_links") or {}).get("status"))


def assignee_id(wp: dict[str, Any]) -> int | None:
    """The work package's current assignee id (None when unassigned)."""
    return href_id((wp.get("_links") or {}).get("assignee"))
