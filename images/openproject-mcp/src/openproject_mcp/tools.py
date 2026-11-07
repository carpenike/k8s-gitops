"""Bot task queue over OpenProject API v3: the I/O half.

Ported from homelab-mcp (src/homelab_mcp/tools/openproject.py, MIT, same
author; LICENSE.homelab-mcp). What changed:

- Identity. The server holds no OpenProject secrets. Every MCP request
  carries `Authorization: Bearer <OpenProject API token>`; each OpenProject
  call made for that request uses that token (HTTP Basic `apikey:<token>`).
  The caller is whoever `/api/v3/users/me` says the token belongs to,
  cached per sha256 of the token for a short TTL. There is no `bot`
  argument and no token/project map.
- Scope. OpenProject's memberships are the only boundary: without `project`
  (and without OPENPROJECT_DEFAULT_PROJECT) list/claim cover every project the
  caller can see.
- Assignees. `me`, a numeric user id, or a login/name resolved through
  `/api/v3/principals` among the members of the target project.
- Comments carry the author's id and login.

Claiming is optimistic concurrency, not a lock: a claim PATCHes
assignee=self and status=In progress carrying the `lockVersion` it read. If
anyone changed the work package in between, OpenProject answers 409 and
writes nothing; the claim re-reads the task and either retries it (still
claimable) or moves on, within OPENPROJECT_CLAIM_MAX_ATTEMPTS. Two callers
racing for one task cannot both win.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from openproject_mcp import hal
from openproject_mcp._http import ToolError, enc, request_json
from openproject_mcp.config import Settings

log = logging.getLogger(__name__)
audit = logging.getLogger("openproject_mcp.audit")

SERVICE = "openproject"

_RO = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
# Writes. None is idempotent: claim takes a DIFFERENT task on repeat, and
# complete/release/comment/create each add a new comment or task.
_RW = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)

INSTRUCTIONS = """\
These tools are a shared task queue on OpenProject. Every call acts as the
OpenProject user that owns your API token (see whoami); OpenProject's project
memberships decide what you can see and change.

- To pick up work call claim_next. Never claim by editing a task yourself. It is
  atomic: claimed=true means the task is yours; claimed=false means nothing was
  claimable (do not retry in a loop).
- When finished call complete_task with a short summary of what you did; it closes
  the task and posts the summary as a comment. If you cannot finish, call
  release_task with a reason so someone else can take it.
- Task data is a snapshot: re-read with get_task rather than trusting an old copy.
- Comments carry author_login and author_id; compare them with whoami to tell your
  own comments, a peer bot's and a human's apart.
"""

_SINGULAR = {"statuses": "status", "priorities": "priority", "types": "type"}

AssigneeFilter = Literal["any", "unassigned", "me"]


@dataclass(frozen=True)
class Caller:
    """The OpenProject user behind one API token."""

    id: int
    login: str | None
    name: str | None
    # Full Authorization header value for OpenProject; never logged or repr'd.
    auth: str = field(repr=False)
    # sha256 hex of the token: the cache key, never the token itself.
    key: str = field(repr=False)

    @property
    def label(self) -> str:
        return self.login or self.name or f"user {self.id}"


class TTLCache:
    """Tiny TTL cache for lookups that change rarely."""

    def __init__(self, ttl: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl
        self.clock = clock
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl: float | None = None) -> Any | None:
        limit = self.ttl if ttl is None else ttl
        hit = self._data.get(key)
        if hit is None or not limit or self.clock() - hit[0] > limit:
            return None
        return hit[1]

    def put(self, key: str, value: Any) -> Any:
        if self.ttl:
            self._data[key] = (self.clock(), value)
        return value


def basic_auth(token: str) -> str:
    """OpenProject API-token auth: HTTP Basic, username 'apikey', password = token."""
    return "Basic " + base64.b64encode(f"apikey:{token}".encode()).decode("ascii")


def token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def bearer_token(value: str | None) -> str | None:
    """The token of an `Authorization: Bearer <token>` header value, else None."""
    if not value:
        return None
    scheme, _, token = value.strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


class OpenProject:
    """Every operation takes the caller's OpenProject API token explicitly."""

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self.base = settings.api_base
        self.web_base = settings.web_base
        self.max_attempts = settings.claim_max_attempts
        self.cache = TTLCache(float(settings.cache_seconds))
        self.client = httpx.AsyncClient(timeout=20.0, transport=transport)
        # user id -> login of every token owner seen through /users/me. Lets a
        # caller see a peer's login although OpenProject hides other users'
        # logins from non-admins.
        self.known_logins: dict[int, str] = {}

    async def aclose(self) -> None:
        await self.client.aclose()

    # ── plumbing ─────────────────────────────────────────────────────
    async def _api(self, auth: str, method: str, path: str, **kw: Any) -> Any:
        return await request_json(
            self.client,
            method,
            f"{self.base}{hal.API}{path}",
            service=SERVICE,
            headers={"Authorization": auth, "Accept": "application/hal+json"},
            unreachable_hint="Check OPENPROJECT_URL and that OpenProject is up.",
            **kw,
        )

    async def caller(self, token: str | None) -> Caller:
        """Resolve a token to its OpenProject user (cached per token hash, short TTL)."""
        if not token:
            raise ToolError(
                "openproject_unauthenticated",
                "This request carried no OpenProject API token.",
                "Send Authorization: Bearer <your OpenProject API token>.",
            )
        key = token_key(token)
        hit = self.cache.get(f"me:{key}", self.settings.identity_seconds)
        if isinstance(hit, Caller):
            return hit
        auth = basic_auth(token)
        try:
            data = await self._api(auth, "GET", "/users/me")
        except ToolError as err:
            if err.code == "openproject_http_401":
                raise ToolError(
                    "openproject_bad_token",
                    "OpenProject rejected this API token.",
                    "Generate a new API token under My account → Access tokens.",
                ) from err
            raise
        user = hal.slim_user(data)
        if user["id"] is None:
            raise ToolError(
                "openproject_bad_token",
                "OpenProject did not identify this API token as a user.",
                "Use a user's API token, not an anonymous or OAuth one.",
            )
        who = Caller(id=user["id"], login=user["login"], name=user["name"], auth=auth, key=key)
        if who.login:
            self.known_logins[who.id] = who.login
        return self.cache.put(f"me:{key}", who)

    async def _named(self, who: Caller, kind: str) -> list[dict[str, Any]]:
        """All statuses / priorities / types (small, instance-wide lists), cached."""
        hit = self.cache.get(kind)
        if hit is not None:
            return list(hit)
        data = await self._api(who.auth, "GET", f"/{kind}")
        return list(self.cache.put(kind, hal.elements(data)))

    async def _resolve_named(self, who: Caller, kind: str, ref: str) -> int:
        ref = ref.strip()
        if ref.isdigit():
            return int(ref)
        items = await self._named(who, kind)
        for item in items:
            if str(item.get("name", "")).casefold() == ref.casefold() and isinstance(
                item.get("id"), int
            ):
                return int(item["id"])
        known = ", ".join(str(i.get("name")) for i in items)
        singular = _SINGULAR[kind]
        raise ToolError(
            f"openproject_unknown_{singular}",
            f"OpenProject has no {singular} named {ref!r}.",
            f"Known: {known}." if known else "",
        )

    async def _project_id(self, who: Caller, ref: str) -> int:
        ref = ref.strip()
        if ref.isdigit():
            return int(ref)
        # Visibility is per user, so the cache is per token.
        key = f"project:{who.key}:{ref.casefold()}"
        hit = self.cache.get(key)
        if hit is not None:
            return int(hit)
        try:
            data = await self._api(who.auth, "GET", f"/projects/{enc(ref)}")
        except ToolError as err:
            if err.code in ("openproject_http_404", "openproject_http_403"):
                raise ToolError(
                    "openproject_unknown_project",
                    f"{who.label} cannot see an OpenProject project {ref!r}.",
                    "Check the project identifier and that you are a member of it.",
                ) from err
            raise
        pid = (data or {}).get("id")
        if not isinstance(pid, int):
            raise ToolError("openproject_unknown_project", f"Project {ref!r} has no id.", "")
        return int(self.cache.put(key, pid))

    async def _project_filters(self, who: Caller, project: str | None) -> list[dict[str, Any]]:
        """`project` (or the default project) as a filter; none = every visible project."""
        ref = (project or "").strip() or self.settings.default_project
        if not ref:
            return []
        return [hal.id_filter("project", [await self._project_id(who, ref)])]

    async def _get_wp(self, who: Caller, task_id: int) -> dict[str, Any]:
        data = await self._api(who.auth, "GET", f"/work_packages/{enc(str(task_id))}")
        if not isinstance(data, dict):
            raise ToolError("openproject_bad_response", "Work package response was not an object.")
        return data

    async def _patch_wp(
        self, who: Caller, wp: dict[str, Any], links: dict[str, Any]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"lockVersion": wp.get("lockVersion"), "_links": links}
        data = await self._api(
            who.auth, "PATCH", f"/work_packages/{enc(str(wp.get('id')))}", json=body
        )
        return data if isinstance(data, dict) else wp

    async def _comment(self, who: Caller, task_id: int, text: str) -> Any:
        return await self._api(
            who.auth,
            "POST",
            f"/work_packages/{enc(str(task_id))}/activities",
            json={"comment": {"raw": text}},
        )

    def _slim(self, wp: dict[str, Any]) -> dict[str, Any]:
        return hal.slim_work_package(wp, web_base=self.web_base)

    async def _update_with_retry(
        self,
        who: Caller,
        task_id: int,
        links: dict[str, Any],
        check: Callable[[dict[str, Any]], bool],
    ) -> tuple[dict[str, Any], int, bool]:
        """PATCH with lockVersion; on 409 re-read, re-`check`, and retry (bounded).

        `check(wp)` raises ToolError when the task is no longer ours to change, and
        returns True when the change is already in effect (nothing to write).
        Returns (work package, conflicts, changed).
        """
        conflicts = 0
        wp = await self._get_wp(who, task_id)
        for _ in range(self.max_attempts):
            if check(wp):
                return wp, conflicts, False
            try:
                return await self._patch_wp(who, wp, links), conflicts, True
            except ToolError as err:
                if err.code != "openproject_http_409":
                    raise
                conflicts += 1
                wp = await self._get_wp(who, task_id)
        raise ToolError(
            "openproject_conflict",
            f"Work package {task_id} kept changing underneath us ({conflicts} conflicts).",
            "Re-read it with get_task and try again later.",
        )

    async def _login_of(self, who: Caller, user_id: int) -> str | None:
        """A user's login, or None when OpenProject hides it from this caller."""
        if user_id == who.id:
            return who.login
        if user_id in self.known_logins:
            return self.known_logins[user_id]
        key = f"login:{who.key}:{user_id}"
        hit = self.cache.get(key)
        if hit is not None:
            return hit or None
        try:
            user = hal.slim_user(await self._api(who.auth, "GET", f"/users/{user_id}"))
        except ToolError:
            user = {"login": None}
        login = user["login"]
        if login:
            self.known_logins[user_id] = login
        self.cache.put(key, login or "")
        return login

    async def _resolve_assignee(self, who: Caller, ref: str, project_id: int) -> int:
        """`me`, a numeric user id, or a login/name among the project's members."""
        ref = ref.strip()
        if ref.casefold() == "me":
            return who.id
        if ref.isdigit():
            return int(ref)
        data = await self._api(
            who.auth,
            "GET",
            "/principals",
            params={
                "filters": hal.filters_json(
                    [
                        hal.id_filter("member", [project_id]),
                        {"type": {"operator": "=", "values": ["User"]}},
                        {"any_name_attribute": {"operator": "~", "values": [ref]}},
                    ]
                ),
                "pageSize": 50,
            },
        )
        users = [hal.slim_user(p) for p in hal.elements(data)]
        users = [u for u in users if u["id"] is not None]
        wanted = ref.casefold()
        for u in users:
            login = u["login"] or self.known_logins.get(u["id"])
            if login and login.casefold() == wanted:
                return int(u["id"])
        by_name = [u for u in users if (u["name"] or "").casefold() == wanted]
        if len(by_name) == 1:
            return int(by_name[0]["id"])
        if len(users) == 1 and not by_name:
            # OpenProject matched it on login/first/last name or email, which it
            # may not show us; one member matched, so that is who was meant.
            return int(users[0]["id"])
        names = ", ".join(sorted(str(u["name"]) for u in (by_name or users)))
        if users:
            raise ToolError(
                "openproject_ambiguous_assignee",
                f"{ref!r} matches several members of the project.",
                f"Matches: {names}. Pass the login or the numeric user id.",
            )
        raise ToolError(
            "openproject_unknown_assignee",
            f"No member of the target project matches {ref!r}.",
            "Pass 'me', a member's login or name, or a numeric user id; the assignee "
            "must be a member of the task's project.",
        )

    # ── operations ───────────────────────────────────────────────────
    async def whoami(self, token: str | None) -> dict[str, Any]:
        try:
            who = await self.caller(token)
        except ToolError as err:
            return err.payload()
        return {
            "id": who.id,
            "login": who.login,
            "name": who.name,
            "default_project": self.settings.default_project,
            "openproject_url": self.web_base,
        }

    async def claim_next(self, token: str | None, project: str | None = None) -> dict[str, Any]:
        attempts = conflicts = 0
        skipped: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        try:
            who = await self.caller(token)
            filters = await self._project_filters(who, project)
            ready = [
                await self._resolve_named(who, "statuses", s) for s in self.settings.ready_statuses
            ]
            in_progress = await self._resolve_named(
                who, "statuses", self.settings.in_progress_status
            )
            listing = await self._api(
                who.auth,
                "GET",
                "/work_packages",
                params={
                    "filters": hal.filters_json(
                        [
                            *filters,
                            hal.id_filter("status", ready),
                            {"assignee": {"operator": "!*", "values": []}},
                        ]
                    ),
                    "sortBy": hal.CLAIM_SORT,
                    "pageSize": min(50, self.max_attempts * 2),
                },
            )
            candidates = hal.elements(listing)
            links = {
                "assignee": hal.link("users", who.id),
                "status": hal.link("statuses", in_progress),
            }
            for wp in candidates:
                while attempts < self.max_attempts:
                    attempts += 1
                    try:
                        claimed = await self._patch_wp(who, wp, links)
                    except ToolError as err:
                        if err.code == "openproject_http_409":
                            conflicts += 1
                            wp = await self._get_wp(who, int(wp["id"]))
                            if hal.is_unassigned(wp) and hal.status_id(wp) in ready:
                                continue  # still free: retry with the fresh lockVersion
                            skipped.append({"id": wp.get("id"), "reason": "taken"})
                            break
                        if err.code in ("openproject_http_403", "openproject_http_422"):
                            # Not permitted (role) or not allowed (workflow): next one.
                            skipped.append({"id": wp.get("id"), "reason": err.message})
                            break
                        raise
                    if hal.assignee_id(claimed) != who.id:
                        skipped.append({"id": wp.get("id"), "reason": "assignee not applied"})
                        break
                    audit.info(
                        "claim_next caller=%s task=%s attempts=%d conflicts=%d",
                        who.label,
                        claimed.get("id"),
                        attempts,
                        conflicts,
                    )
                    return {
                        "claimed": True,
                        "caller": who.label,
                        "task": self._slim(claimed),
                        "attempts": attempts,
                        "conflicts": conflicts,
                        "skipped": skipped,
                    }
                if attempts >= self.max_attempts:
                    break
        except ToolError as err:
            return err.payload()
        exhausted = attempts >= self.max_attempts and bool(candidates)
        audit.info(
            "claim_next caller=%s task=none attempts=%d conflicts=%d",
            who.label,
            attempts,
            conflicts,
        )
        return {
            "claimed": False,
            "caller": who.label,
            "reason": "max_attempts_exhausted" if exhausted else "no_claimable_task",
            "candidates_seen": len(candidates),
            "attempts": attempts,
            "conflicts": conflicts,
            "skipped": skipped,
        }

    async def complete_task(self, token: str | None, task_id: int, summary: str) -> dict[str, Any]:
        try:
            who = await self.caller(token)
            if not summary.strip():
                raise ToolError("openproject_bad_summary", "summary must be non-empty.", "")
            done = await self._resolve_named(who, "statuses", self.settings.done_status)

            def check(wp: dict[str, Any]) -> bool:
                if hal.assignee_id(wp) != who.id:
                    raise ToolError(
                        "openproject_not_assignee",
                        f"Task {task_id} is not assigned to {who.label}.",
                        "Claim it first (claim_next), or leave it alone.",
                    )
                return hal.status_id(wp) == done

            wp, conflicts, changed = await self._update_with_retry(
                who, task_id, {"status": hal.link("statuses", done)}, check
            )
        except ToolError as err:
            return err.payload()
        out: dict[str, Any] = {
            "completed": True,
            "already_done": not changed,
            "caller": who.label,
            "conflicts": conflicts,
            "task": self._slim(wp),
        }
        try:
            activity = await self._comment(who, task_id, summary.strip())
            out["comment_posted"] = True
            out["comment_id"] = (activity or {}).get("id")
        except ToolError as err:
            out["comment_posted"] = False
            out["comment_error"] = err.payload()["error"]
        audit.info(
            "complete_task caller=%s task=%s changed=%s comment=%s",
            who.label,
            task_id,
            changed,
            out["comment_posted"],
        )
        return out

    async def release_task(
        self, token: str | None, task_id: int, reason: str | None = None
    ) -> dict[str, Any]:
        try:
            who = await self.caller(token)
            reset = await self._resolve_named(who, "statuses", self.settings.release_status)

            def check(wp: dict[str, Any]) -> bool:
                owner = hal.assignee_id(wp)
                if owner is None and hal.status_id(wp) == reset:
                    return True  # already released
                if owner != who.id:
                    raise ToolError(
                        "openproject_not_assignee",
                        f"Task {task_id} is not assigned to {who.label}.",
                        "Only the user holding a task can release it.",
                    )
                return False

            wp, conflicts, changed = await self._update_with_retry(
                who,
                task_id,
                {"assignee": hal.link("users", None), "status": hal.link("statuses", reset)},
                check,
            )
            out: dict[str, Any] = {
                "released": True,
                "already_released": not changed,
                "caller": who.label,
                "conflicts": conflicts,
                "task": self._slim(wp),
            }
            if reason and reason.strip():
                await self._comment(who, task_id, reason.strip())
                out["comment_posted"] = True
        except ToolError as err:
            return err.payload()
        audit.info("release_task caller=%s task=%s changed=%s", who.label, task_id, changed)
        return out

    async def list_tasks(
        self,
        token: str | None,
        project: str | None = None,
        status: str = "open",
        assignee: AssigneeFilter = "any",
        limit: int = 25,
    ) -> dict[str, Any]:
        try:
            who = await self.caller(token)
            filters = await self._project_filters(who, project)
            wanted = status.strip()
            if wanted.casefold() == "open":
                filters.append({"status": {"operator": "o", "values": []}})
            elif wanted.casefold() != "all":
                filters.append(
                    hal.id_filter("status", [await self._resolve_named(who, "statuses", wanted)])
                )
            if assignee == "unassigned":
                filters.append({"assignee": {"operator": "!*", "values": []}})
            elif assignee == "me":
                filters.append(hal.id_filter("assignee", [who.id]))
            data = await self._api(
                who.auth,
                "GET",
                "/work_packages",
                params={
                    "filters": hal.filters_json(filters),
                    "sortBy": hal.LIST_SORT,
                    "pageSize": limit,
                },
            )
        except ToolError as err:
            return err.payload()
        rows = hal.elements(data)
        total = hal.collection_total(data, len(rows))
        return {
            "caller": who.label,
            "returned": len(rows),
            "total": total,
            "truncated": total > len(rows),
            "tasks": [self._slim(wp) for wp in rows],
        }

    async def get_task(self, token: str | None, task_id: int, comments: int = 5) -> dict[str, Any]:
        try:
            who = await self.caller(token)
            wp = await self._get_wp(who, task_id)
            activities = (
                await self._api(who.auth, "GET", f"/work_packages/{enc(str(task_id))}/activities")
                if comments
                else None
            )
        except ToolError as err:
            return err.payload()
        out = self._slim(wp)
        if not comments:
            out["recent_comments"] = []
            return out
        newest = hal.slim_comments(activities, comments)
        logins = {
            uid: await self._login_of(who, uid)
            for uid in dict.fromkeys(c["author_id"] for c in newest if c["author_id"] is not None)
        }
        out["recent_comments"] = hal.slim_comments(activities, comments, logins)
        return out

    async def add_comment(self, token: str | None, task_id: int, text: str) -> dict[str, Any]:
        try:
            who = await self.caller(token)
            if not text.strip():
                raise ToolError("openproject_bad_comment", "text must be non-empty.", "")
            activity = await self._comment(who, task_id, text.strip())
        except ToolError as err:
            return err.payload()
        audit.info("add_comment caller=%s task=%s", who.label, task_id)
        return {
            "commented": True,
            "caller": who.label,
            "task_id": task_id,
            "comment_id": (activity or {}).get("id"),
        }

    async def create_task(
        self,
        token: str | None,
        subject: str,
        project: str | None = None,
        description: str | None = None,
        type: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        due_date: str | None = None,
    ) -> dict[str, Any]:
        try:
            who = await self.caller(token)
            if not subject.strip():
                raise ToolError("openproject_bad_subject", "subject must be non-empty.", "")
            target = (project or "").strip() or self.settings.default_project
            if not target:
                raise ToolError(
                    "openproject_project_required",
                    "No project given and no default project is configured.",
                    "Pass `project` (identifier or id); list_tasks shows the projects you see.",
                )
            body: dict[str, Any] = {"subject": subject.strip()}
            if description and description.strip():
                body["description"] = {"format": "markdown", "raw": description}
            if due_date:
                try:
                    body["dueDate"] = date.fromisoformat(due_date).isoformat()
                except ValueError as exc:
                    raise ToolError(
                        "openproject_bad_date", f"due_date {due_date!r} is not YYYY-MM-DD.", ""
                    ) from exc
            pid = await self._project_id(who, target)
            links: dict[str, Any] = {"project": hal.link("projects", pid)}
            if type:
                links["type"] = hal.link("types", await self._resolve_named(who, "types", type))
            if priority:
                links["priority"] = hal.link(
                    "priorities", await self._resolve_named(who, "priorities", priority)
                )
            if assignee and assignee.strip():
                uid = await self._resolve_assignee(who, assignee, pid)
                links["assignee"] = hal.link("users", uid)
            body["_links"] = links
            created = await self._api(who.auth, "POST", "/work_packages", json=body)
        except ToolError as err:
            return err.payload()
        task = self._slim(created if isinstance(created, dict) else {})
        audit.info("create_task caller=%s task=%s project=%s", who.label, task["id"], pid)
        return {"created": True, "caller": who.label, "task": task}


# ── MCP registration ─────────────────────────────────────────────────

_PROJECT = Field(
    description=(
        "Project identifier (e.g. 'bots') or numeric id. Omit to use the server's default "
        "project, or every project you can see when there is none."
    )
)
_TASK_ID = Field(ge=1, description="Work package (task) id, e.g. 101.")


def request_token(ctx: Context | None) -> str | None:
    """The bearer token of the HTTP request behind this MCP call."""
    if ctx is None:
        return None
    try:
        headers = ctx.headers
    except (ValueError, AttributeError):
        return None
    if not headers:
        return None
    return bearer_token(headers.get("authorization"))


def register(mcp: MCPServer, op: OpenProject) -> None:
    """Register the task-queue tools on `mcp`, backed by `op`."""

    @mcp.tool(
        name="whoami",
        annotations=_RO,
        description=(
            "Who you are on OpenProject: the id, login and display name of the user that "
            "owns your API token, plus the server's default project (null when there is "
            "none). Use it to recognise your own tasks and comments (compare "
            "assignee_id/author_id with your id), and as a cheap check that your token works."
        ),
    )
    async def whoami(ctx: Context) -> dict[str, Any]:
        return await op.whoami(request_token(ctx))

    @mcp.tool(
        name="claim_next",
        annotations=_RW,
        description=(
            "Atomically claim the next unassigned, ready task (status New by default) and "
            "make it yours: sets assignee to you and status to In progress. Order: highest "
            "priority, then soonest due date, then oldest. Searches `project` if given, else "
            "the default project, else every project you can see. Safe under races: it uses "
            "OpenProject's lockVersion, so two callers can never both win one task. Returns "
            "claimed=true with the task, or claimed=false with a reason "
            "(no_claimable_task / max_attempts_exhausted) — that is an answer, not an error; "
            "do not call it again in a loop. Call this whenever you are ready for new work."
        ),
    )
    async def claim_next(
        ctx: Context, project: Annotated[str | None, _PROJECT] = None
    ) -> dict[str, Any]:
        return await op.claim_next(request_token(ctx), project)

    @mcp.tool(
        name="complete_task",
        annotations=_RW,
        description=(
            "Finish a task you hold: set its status to the done status (Closed by default) "
            "using lockVersion, then post `summary` as a comment. Refused "
            "(openproject_not_assignee) if the task is not assigned to you. If the status "
            "change succeeds but the comment fails, returns completed=true with "
            "comment_posted=false — then post the summary with add_comment; do not call "
            "complete_task again."
        ),
    )
    async def complete_task(
        ctx: Context,
        task_id: Annotated[int, _TASK_ID],
        summary: Annotated[
            str,
            Field(
                min_length=1,
                max_length=10000,
                description="What you did and the outcome, in a few sentences (markdown).",
            ),
        ],
    ) -> dict[str, Any]:
        return await op.complete_task(request_token(ctx), task_id, summary)

    @mcp.tool(
        name="release_task",
        annotations=_RW,
        description=(
            "Give a task you hold back to the queue: clear its assignee and reset its status "
            "(New by default) using lockVersion, and post `reason` as a comment so the next "
            "taker knows why. Use it when you cannot finish a task. Refused "
            "(openproject_not_assignee) if the task is not assigned to you."
        ),
    )
    async def release_task(
        ctx: Context,
        task_id: Annotated[int, _TASK_ID],
        reason: Annotated[
            str | None,
            Field(max_length=10000, description="Why you are giving it back (posted as a comment)."),
        ] = None,
    ) -> dict[str, Any]:
        return await op.release_task(request_token(ctx), task_id, reason)

    @mcp.tool(
        name="list_tasks",
        annotations=_RO,
        description=(
            "List tasks, most recently updated first, in `project` (or the default project, "
            "or every project you can see). `status`: a status name such as 'New' or 'In "
            "progress', 'open' (default: every not-closed status) or 'all'. `assignee`: "
            "'any' (default), 'unassigned' or 'me'. Returns slim tasks plus "
            "returned/total/truncated. To take work use claim_next, not this list."
        ),
    )
    async def list_tasks(
        ctx: Context,
        project: Annotated[str | None, _PROJECT] = None,
        status: Annotated[
            str, Field(max_length=100, description="Status name, 'open' or 'all'.")
        ] = "open",
        assignee: Annotated[
            AssigneeFilter, Field(description="'any', 'unassigned' or 'me'.")
        ] = "any",
        limit: Annotated[int, Field(ge=1, le=100, description="Most tasks to return.")] = 25,
    ) -> dict[str, Any]:
        return await op.list_tasks(request_token(ctx), project, status, assignee, limit)

    @mcp.tool(
        name="get_task",
        annotations=_RO,
        description=(
            "Fetch one task: status, assignee (name and id), project, priority, due date, "
            "lock_version, a plain-text description excerpt and a link, plus its newest "
            "comments (newest first). Each comment has author (display name), author_id and "
            "author_login (null when OpenProject hides that user's login from you); compare "
            "them with whoami and your peers' logins to tell your own, a peer bot's and a "
            "human's comments apart. Read a task before working it."
        ),
    )
    async def get_task(
        ctx: Context,
        task_id: Annotated[int, _TASK_ID],
        comments: Annotated[
            int, Field(ge=0, le=20, description="How many recent comments to include.")
        ] = 5,
    ) -> dict[str, Any]:
        return await op.get_task(request_token(ctx), task_id, comments)

    @mcp.tool(
        name="add_comment",
        annotations=_RW,
        description=(
            "Post a comment on a task as yourself: progress notes, a question for a human, a "
            "hand-off note for a peer bot, or a summary whose earlier post failed. Markdown. "
            "Each call adds a NEW comment."
        ),
    )
    async def add_comment(
        ctx: Context,
        task_id: Annotated[int, _TASK_ID],
        text: Annotated[
            str, Field(min_length=1, max_length=10000, description="Comment text (markdown).")
        ],
    ) -> dict[str, Any]:
        return await op.add_comment(request_token(ctx), task_id, text)

    @mcp.tool(
        name="create_task",
        annotations=_RW,
        description=(
            "Create a task in `project` (required unless the server has a default project). "
            "`assignee`: 'me', a member's login (e.g. a peer bot such as 'hank') or display "
            "name, a numeric user id, or omitted to leave it unassigned and claimable by "
            "anyone in the project. `type` and `priority` are names as shown in OpenProject "
            "(e.g. 'Task', 'High'). Each call creates a NEW task; check list_tasks first to "
            "avoid duplicates."
        ),
    )
    async def create_task(
        ctx: Context,
        subject: Annotated[
            str, Field(min_length=1, max_length=255, description="Short title.")
        ],
        project: Annotated[
            str | None,
            Field(description="Project identifier or id; default = the server's default project."),
        ] = None,
        description: Annotated[
            str | None,
            Field(max_length=20000, description="Body (markdown): goal, context, done-when."),
        ] = None,
        type: Annotated[str | None, Field(description="Work package type, e.g. 'Task'.")] = None,
        priority: Annotated[str | None, Field(description="Priority name, e.g. 'High'.")] = None,
        assignee: Annotated[
            str | None,
            Field(description="'me', a member's login or name, or a numeric user id."),
        ] = None,
        due_date: Annotated[str | None, Field(description="Due date, 'YYYY-MM-DD'.")] = None,
    ) -> dict[str, Any]:
        return await op.create_task(
            request_token(ctx), subject, project, description, type, priority, assignee, due_date
        )
