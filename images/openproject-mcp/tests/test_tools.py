"""Task-queue operations against a fake OpenProject. Ported from homelab-mcp's
tests/test_tools_openproject.py; identity now comes from the request's token.

The load-bearing cases are the 409 paths: a claim or completion that loses a
lockVersion race must never report success for a write OpenProject refused,
and must never take a task someone else won.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from conftest import (
    TOKEN_FINANCES,
    TOKEN_HANK,
    TOKEN_HOMELAB,
    FakeOpenProject,
    basic,
    fx,
)

from openproject_mcp.config import Settings, expand_hosts, normalize_base
from openproject_mcp.tools import OpenProject, TTLCache, bearer_token

pytestmark = pytest.mark.anyio

T = TOKEN_HOMELAB  # the default caller: user 21 "Homelab Manager", login bot-homelab


# A valid handoff for creates whose subject is not the handoff itself.
HANDOFF = {"context": "Inbox/x.md", "done_when": "x is done."}


def conflict() -> tuple[int, Any]:
    return (409, fx("error_409_update_conflict"))


# ── identity ──────────────────────────────────────────────────────────


async def test_whoami_reports_the_token_owner(op: OpenProject) -> None:
    out = await op.whoami(T)
    assert out["id"] == 21 and out["login"] == "bot-homelab" and out["name"] == "Homelab Manager"
    assert out["default_project"] is None


async def test_every_request_uses_the_callers_token_as_basic_apikey(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_empty"))
    await op.claim_next(T)
    await op.list_tasks(TOKEN_FINANCES)
    homelab = [c for c in fake.calls if c.headers["authorization"] == basic(T)]
    finances = [c for c in fake.calls if c.headers["authorization"] == basic(TOKEN_FINANCES)]
    assert homelab and finances and len(homelab) + len(finances) == len(fake.calls)
    # Each caller's own work-package query went out with its own token.
    assert [c.headers["authorization"] for c in fake.calls if c.url.path.endswith("/work_packages")] == [
        basic(T),
        basic(TOKEN_FINANCES),
    ]


async def test_identity_is_cached_per_token(op: OpenProject, fake: FakeOpenProject) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_empty"))
    for token in (T, T, TOKEN_FINANCES, TOKEN_FINANCES):
        await op.list_tasks(token)
    me_calls = [c for c in fake.calls if c.url.path == "/api/v3/users/me"]
    assert [c.headers["authorization"] for c in me_calls] == [basic(T), basic(TOKEN_FINANCES)]


async def test_identity_cache_expires_after_a_short_ttl(fake: FakeOpenProject) -> None:
    now = [0.0]
    op = OpenProject(Settings(url="http://openproject.test"), transport=fake.transport)
    op.cache = TTLCache(600, clock=lambda: now[0])
    await op.whoami(T)
    now[0] = 30
    await op.whoami(T)
    now[0] = 61
    await op.whoami(T)
    assert [c.url.path for c in fake.calls].count("/api/v3/users/me") == 2


async def test_a_token_openproject_rejects_is_a_bad_token_error(op: OpenProject) -> None:
    out = await op.whoami("not-a-real-token")
    assert out["error"]["code"] == "openproject_bad_token"
    out = await op.claim_next("not-a-real-token")
    assert out["error"]["code"] == "openproject_bad_token"


async def test_no_token_is_refused_before_calling_out(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    for out in (await op.whoami(None), await op.list_tasks(""), await op.get_task(None, 1)):
        assert out["error"]["code"] == "openproject_unauthenticated"
    assert not fake.calls


def test_bearer_token_parsing() -> None:
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token("bearer   abc ") == "abc"
    assert bearer_token("Bearer ") is None
    assert bearer_token("Basic abc") is None
    assert bearer_token("") is None and bearer_token(None) is None


async def test_tokens_never_reach_logs_or_results(
    op: OpenProject, fake: FakeOpenProject, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    fake.on("GET", "/work_packages", fx("work_packages_ready"))
    fake.on("PATCH", "/work_packages/101", conflict())
    fake.on("GET", "/work_packages/101", fx("wp_101_taken"))
    fake.on("PATCH", "/work_packages/102", (500, {"message": "boom"}))
    out = await op.claim_next(T)
    out2 = await op.whoami("rejected-token-value")
    blob = json.dumps(out) + json.dumps(out2) + caplog.text + repr(op.cache._data)
    for token in (T, "rejected-token-value"):
        assert token not in blob
        assert basic(token)[6:] not in blob


# ── claim_next ────────────────────────────────────────────────────────


async def test_claim_next_patches_assignee_and_status_with_the_listed_lock_version(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_ready"))
    fake.on("PATCH", "/work_packages/101", fx("wp_101_claimed"))

    out = await op.claim_next(T)

    assert out["claimed"] is True and out["caller"] == "bot-homelab"
    assert out["task"]["id"] == 101 and out["task"]["assignee_id"] == 21
    assert out["task"]["status"] == "In progress"
    assert out["attempts"] == 1 and out["conflicts"] == 0
    (body,) = fake.sent("PATCH", "/work_packages/101")
    assert body == {
        "lockVersion": 3,
        "_links": {
            "assignee": {"href": "/api/v3/users/21"},
            "status": {"href": "/api/v3/statuses/7"},
        },
    }
    (query,) = fake.query("GET", "/work_packages")
    filters = json.loads(query["filters"][0])
    # No project and no default: every project the caller can see.
    assert not [f for f in filters if "project" in f]
    assert {"status": {"operator": "=", "values": ["1"]}} in filters
    assert {"assignee": {"operator": "!*", "values": []}} in filters
    assert json.loads(query["sortBy"][0])[0] == ["priority", "desc"]


async def test_claim_next_on_409_moves_on_when_the_refetched_task_was_taken(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_ready"))
    fake.on("PATCH", "/work_packages/101", conflict())
    fake.on("GET", "/work_packages/101", fx("wp_101_taken"))
    fake.on("PATCH", "/work_packages/102", fx("wp_102_claimed"))

    out = await op.claim_next(T)

    assert out["claimed"] is True
    assert out["task"]["id"] == 102
    assert out["conflicts"] == 1 and out["attempts"] == 2
    assert out["skipped"] == [{"id": 101, "reason": "taken"}]
    # The lost task was never written a second time.
    assert len(fake.sent("PATCH", "/work_packages/101")) == 1
    assert fake.sent("PATCH", "/work_packages/102")[0]["lockVersion"] == 1


async def test_claim_next_on_409_retries_a_still_free_task_with_the_fresh_lock_version(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_ready"))
    fake.on("PATCH", "/work_packages/101", conflict(), (200, fx("wp_101_claimed")))
    fake.on("GET", "/work_packages/101", fx("wp_101_bumped"))

    out = await op.claim_next(T)

    assert out["claimed"] is True and out["task"]["id"] == 101
    assert [b["lockVersion"] for b in fake.sent("PATCH", "/work_packages/101")] == [3, 4]
    assert out["conflicts"] == 1
    assert not fake.sent("PATCH", "/work_packages/102")


async def test_claim_next_gives_up_after_the_attempt_bound(make_op, fake: FakeOpenProject) -> None:
    op = make_op(claim_max_attempts=2)
    fake.on("GET", "/work_packages", fx("work_packages_ready"))
    fake.on("PATCH", "/work_packages/101", conflict())
    fake.on("GET", "/work_packages/101", fx("wp_101_bumped"))

    out = await op.claim_next(T)

    assert out["claimed"] is False
    assert out["reason"] == "max_attempts_exhausted"
    assert out["attempts"] == 2 and out["conflicts"] == 2
    assert len(fake.sent("PATCH", "/work_packages/101")) == 2
    assert not fake.sent("PATCH", "/work_packages/102")


async def test_claim_next_with_nothing_claimable_is_an_answer_not_an_error(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_empty"))
    out = await op.claim_next(T)
    assert "error" not in out
    assert out["claimed"] is False and out["reason"] == "no_claimable_task"
    assert not [c for c in fake.calls if c.method == "PATCH"]


async def test_claim_next_skips_a_task_the_workflow_refuses(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_ready"))
    fake.on("PATCH", "/work_packages/101", (422, fx("error_422_status_transition")))
    fake.on("PATCH", "/work_packages/102", fx("wp_102_claimed"))
    out = await op.claim_next(T)
    assert out["claimed"] is True and out["task"]["id"] == 102
    assert out["skipped"][0]["id"] == 101
    assert "transition" in out["skipped"][0]["reason"]


async def test_claim_next_in_a_project_the_caller_cannot_see(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    out = await op.claim_next(T, project="finances")  # no route: OpenProject says 404
    assert out["error"]["code"] == "openproject_unknown_project"
    assert not fake.query("GET", "/work_packages")


async def test_claim_next_restricted_to_one_project(op: OpenProject, fake: FakeOpenProject) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_empty"))
    await op.claim_next(T, project="bots-shared")
    await op.claim_next(T, project="5")
    assert {"project": {"operator": "=", "values": ["9"]}} in fake.filters("GET", "/work_packages")
    assert {"project": {"operator": "=", "values": ["5"]}} in fake.filters(
        "GET", "/work_packages", 1
    )


async def test_the_default_project_applies_when_none_is_given(
    make_op, fake: FakeOpenProject
) -> None:
    op = make_op(default_project="bots-shared")
    fake.on("GET", "/work_packages", fx("work_packages_empty"))
    await op.claim_next(T)
    await op.list_tasks(T, project="homelab")
    assert {"project": {"operator": "=", "values": ["9"]}} in fake.filters("GET", "/work_packages")
    assert {"project": {"operator": "=", "values": ["5"]}} in fake.filters(
        "GET", "/work_packages", 1
    )
    assert (await op.whoami(T))["default_project"] == "bots-shared"


async def test_unknown_ready_status_is_reported_with_known_names(make_op) -> None:
    op = make_op(ready_statuses=("Ready",))
    out = await op.claim_next(T)
    assert out["error"]["code"] == "openproject_unknown_status"
    assert "In progress" in out["error"]["hint"]


async def test_lookups_are_cached_across_calls(op: OpenProject, fake: FakeOpenProject) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_empty"))
    await op.claim_next(T, project="homelab")
    await op.claim_next(T, project="homelab")
    paths = [c.url.path for c in fake.calls]
    assert paths.count("/api/v3/statuses") == 1
    assert paths.count("/api/v3/users/me") == 1
    assert paths.count("/api/v3/projects/homelab") == 1
    assert paths.count("/api/v3/work_packages") == 2


async def test_project_lookups_are_cached_per_token(op: OpenProject, fake: FakeOpenProject) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_empty"))
    await op.list_tasks(T, project="homelab")
    await op.list_tasks(TOKEN_FINANCES, project="homelab")
    assert [c.url.path for c in fake.calls].count("/api/v3/projects/homelab") == 2


# ── complete ──────────────────────────────────────────────────────────


async def test_complete_closes_with_lock_version_then_posts_the_summary(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages/102", fx("wp_102_claimed"))
    fake.on("PATCH", "/work_packages/102", fx("wp_102_closed"))
    fake.on("POST", "/work_packages/102/activities", fx("activity_created"), status=201)

    out = await op.complete_task(T, 102, "  Pruned 412 snapshots older than 30 days.  ")

    assert out["completed"] is True and out["already_done"] is False
    assert out["task"]["status"] == "Closed"
    assert out["comment_posted"] is True and out["comment_id"] == 510
    assert fake.sent("PATCH", "/work_packages/102") == [
        {"lockVersion": 2, "_links": {"status": {"href": "/api/v3/statuses/12"}}}
    ]
    assert fake.sent("POST", "/work_packages/102/activities") == [
        {"comment": {"raw": "Pruned 412 snapshots older than 30 days."}}
    ]
    # Status first, comment second.
    methods = [c.method for c in fake.calls if "/work_packages/102" in c.url.path]
    assert methods.index("PATCH") < methods.index("POST")


async def test_complete_on_409_rereads_and_retries_with_the_new_lock_version(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages/102", fx("wp_102_claimed"), fx("wp_102_claimed_edited"))
    fake.on("PATCH", "/work_packages/102", conflict(), (200, fx("wp_102_closed")))
    fake.on("POST", "/work_packages/102/activities", fx("activity_created"), status=201)

    out = await op.complete_task(T, 102, "Done.")

    assert out["completed"] is True and out["conflicts"] == 1
    assert [b["lockVersion"] for b in fake.sent("PATCH", "/work_packages/102")] == [2, 3]
    assert len(fake.sent("POST", "/work_packages/102/activities")) == 1


async def test_complete_on_409_stops_if_the_task_was_reassigned_meanwhile(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    taken = fx("wp_102_claimed_edited")
    taken["_links"]["assignee"] = {"href": "/api/v3/users/22", "title": "Finances Bot"}
    fake.on("GET", "/work_packages/102", fx("wp_102_claimed"), taken)
    fake.on("PATCH", "/work_packages/102", conflict())

    out = await op.complete_task(T, 102, "Done.")

    assert out["error"]["code"] == "openproject_not_assignee"
    assert len(fake.sent("PATCH", "/work_packages/102")) == 1
    assert not fake.sent("POST", "/work_packages/102/activities")


async def test_complete_conflicting_forever_is_a_bounded_error(
    make_op, fake: FakeOpenProject
) -> None:
    op = make_op(claim_max_attempts=3)
    fake.on("GET", "/work_packages/102", fx("wp_102_claimed"))
    fake.on("PATCH", "/work_packages/102", conflict())
    out = await op.complete_task(T, 102, "Done.")
    assert out["error"]["code"] == "openproject_conflict"
    assert len(fake.sent("PATCH", "/work_packages/102")) == 3
    assert not fake.sent("POST", "/work_packages/102/activities")


async def test_complete_refuses_a_task_held_by_someone_else(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages/101", fx("wp_101_taken"))
    out = await op.complete_task(T, 101, "Done.")
    assert out["error"]["code"] == "openproject_not_assignee"
    assert not [c for c in fake.calls if c.method in ("PATCH", "POST")]
    # ...and the holder can complete it.
    fake.on("PATCH", "/work_packages/101", fx("wp_102_closed"))
    fake.on("POST", "/work_packages/101/activities", fx("activity_created"), status=201)
    assert (await op.complete_task(TOKEN_FINANCES, 101, "Done."))["completed"] is True


async def test_complete_reports_a_failed_comment_without_hiding_the_close(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages/102", fx("wp_102_claimed"))
    fake.on("PATCH", "/work_packages/102", fx("wp_102_closed"))
    fake.on("POST", "/work_packages/102/activities", {"message": "boom"}, status=500)
    out = await op.complete_task(T, 102, "Done.")
    assert out["completed"] is True
    assert out["comment_posted"] is False
    assert out["comment_error"]["code"] == "openproject_http_500"


async def test_complete_an_already_closed_task_skips_the_patch(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages/102", fx("wp_102_closed"))
    fake.on("POST", "/work_packages/102/activities", fx("activity_created"), status=201)
    out = await op.complete_task(T, 102, "Done.")
    assert out["completed"] is True and out["already_done"] is True
    assert not fake.sent("PATCH", "/work_packages/102")


async def test_done_status_is_configurable(make_op, fake: FakeOpenProject) -> None:
    op = make_op(done_status="Rejected")
    fake.on("GET", "/work_packages/102", fx("wp_102_claimed"))
    fake.on("PATCH", "/work_packages/102", fx("wp_102_closed"))
    fake.on("POST", "/work_packages/102/activities", fx("activity_created"), status=201)
    await op.complete_task(T, 102, "Won't do.")
    body = fake.sent("PATCH", "/work_packages/102")[0]
    assert body["_links"]["status"] == {"href": "/api/v3/statuses/14"}


# ── release ───────────────────────────────────────────────────────────


async def test_release_clears_assignee_and_resets_status_with_lock_version(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages/102", fx("wp_102_claimed"))
    fake.on("PATCH", "/work_packages/102", fx("wp_102_released"))
    fake.on("POST", "/work_packages/102/activities", fx("activity_created"), status=201)
    out = await op.release_task(T, 102, reason="Needs Ryan's sudo.")
    assert out["released"] is True and out["task"]["assignee_id"] is None
    assert fake.sent("PATCH", "/work_packages/102") == [
        {
            "lockVersion": 2,
            "_links": {"assignee": {"href": None}, "status": {"href": "/api/v3/statuses/1"}},
        }
    ]
    assert fake.sent("POST", "/work_packages/102/activities") == [
        {"comment": {"raw": "Needs Ryan's sudo."}}
    ]


async def test_release_refuses_someone_elses_task(op: OpenProject, fake: FakeOpenProject) -> None:
    fake.on("GET", "/work_packages/101", fx("wp_101_taken"))
    out = await op.release_task(T, 101)
    assert out["error"]["code"] == "openproject_not_assignee"


# ── list / get / comment ──────────────────────────────────────────────


async def test_list_tasks_filters_and_reports_truncation(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    page = fx("work_packages_ready")
    page["total"] = 7
    fake.on("GET", "/work_packages", page)
    out = await op.list_tasks(T, project="bots-shared", assignee="unassigned", limit=2)
    assert out["returned"] == 2 and out["total"] == 7 and out["truncated"] is True
    assert [t["id"] for t in out["tasks"]] == [101, 102]
    query = fake.query("GET", "/work_packages")[0]
    filters = json.loads(query["filters"][0])
    assert {"project": {"operator": "=", "values": ["9"]}} in filters
    assert {"status": {"operator": "o", "values": []}} in filters
    assert {"assignee": {"operator": "!*", "values": []}} in filters
    assert query["pageSize"] == ["2"]


async def test_list_tasks_by_status_name_and_me(op: OpenProject, fake: FakeOpenProject) -> None:
    fake.on("GET", "/work_packages", fx("work_packages_empty"))
    out = await op.list_tasks(T, status="in progress", assignee="me")
    assert out["returned"] == 0 and out["truncated"] is False
    filters = fake.filters("GET", "/work_packages")
    assert {"status": {"operator": "=", "values": ["7"]}} in filters
    assert {"assignee": {"operator": "=", "values": ["21"]}} in filters
    assert not [f for f in filters if "project" in f]


async def test_get_task_comments_carry_the_authors_login_and_id(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages/101", fx("wp_101_new"))
    fake.on("GET", "/work_packages/101/activities", fx("activities_101"))
    # As a non-admin sees them: Ryan's login is hidden.
    fake.on("GET", "/users/1", fx("user_1_as_member"))
    fake.on("GET", "/users/22", {**fx("users_me_finances"), "login": None})
    # The finances bot has used this server, so its login is known.
    await op.whoami(TOKEN_FINANCES)

    out = await op.get_task(T, 101, comments=3)

    assert out["id"] == 101 and out["lock_version"] == 3
    assert [
        (c["id"], c["author"], c["author_id"], c["author_login"]) for c in out["recent_comments"]
    ] == [
        (505, "Ryan Holt", 1, None),
        (504, "Finances Bot", 22, "bot-finances"),
        (502, "Ryan Holt", 1, None),
    ]
    # One lookup per unknown author, none for a known one.
    paths = [c.url.path for c in fake.calls]
    assert paths.count("/api/v3/users/1") == 1 and "/api/v3/users/22" not in paths


async def test_get_task_takes_a_visible_login_from_openproject(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages/101", fx("wp_101_new"))
    fake.on("GET", "/work_packages/101/activities", fx("activities_101"))
    # An admin-ish token sees logins.
    fake.on("GET", "/users/1", {**fx("user_1_as_member"), "login": "ryan"})
    fake.on("GET", "/users/22", fx("users_me_finances"))
    out = await op.get_task(T, 101, comments=2)
    assert [(c["author_id"], c["author_login"]) for c in out["recent_comments"]] == [
        (1, "ryan"),
        (22, "bot-finances"),
    ]


async def test_get_task_own_comment_uses_the_callers_login(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    activities = fx("activities_101")
    activities["_embedded"]["elements"].append(fx("activity_created"))  # by user 21
    fake.on("GET", "/work_packages/101", fx("wp_101_new"))
    fake.on("GET", "/work_packages/101/activities", activities)
    out = await op.get_task(T, 101, comments=1)
    assert out["recent_comments"][0]["author_id"] == 21
    assert out["recent_comments"][0]["author_login"] == "bot-homelab"
    assert "/api/v3/users/21" not in [c.url.path for c in fake.calls]


async def test_get_task_survives_an_author_lookup_failure(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages/101", fx("wp_101_new"))
    fake.on("GET", "/work_packages/101/activities", fx("activities_101"))
    fake.on("GET", "/users/1", {"message": "forbidden"}, status=403)
    out = await op.get_task(T, 101, comments=1)
    assert "error" not in out
    assert out["recent_comments"][0]["author_login"] is None


async def test_task_urls_use_the_public_url_and_api_calls_the_service_url(
    make_op, fake: FakeOpenProject
) -> None:
    op = make_op(public_url="https://tasks.example.test/")
    fake.on("GET", "/work_packages/101", fx("wp_101_new"))
    out = await op.get_task(T, 101, comments=0)
    assert out["url"] == "https://tasks.example.test/work_packages/101"
    assert {c.url.host for c in fake.calls} == {"openproject.test"}
    assert (await op.whoami(T))["openproject_url"] == "https://tasks.example.test"
    # Without a public URL the links fall back to OPENPROJECT_URL.
    plain = make_op()
    assert (await plain.get_task(T, 101, comments=0))["url"] == (
        "http://openproject.test:8080/work_packages/101"
    )


async def test_add_comment_posts_raw_markdown(op: OpenProject, fake: FakeOpenProject) -> None:
    fake.on("POST", "/work_packages/101/activities", fx("activity_created"), status=201)
    out = await op.add_comment(T, 101, "On it.")
    assert out == {"commented": True, "caller": "bot-homelab", "task_id": 101, "comment_id": 510}


# ── create ────────────────────────────────────────────────────────────


async def test_create_task_resolves_names_and_a_peer_by_login_via_principals(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/principals", fx("principals_hank"))
    fake.on("POST", "/work_packages", fx("wp_103_created"), status=201)

    out = await op.create_task(
        T,
        subject="Renew the certificate",
        context="Personal/Tech/Certificates.md",
        done_when="The certificate is renewed and served.",
        project="homelab",
        description="Created by the Homelab Manager bot.",
        type="task",
        priority="High",
        assignee="hank",
        due_date="2026-11-01",
    )

    assert out["created"] is True and out["task"]["id"] == 103
    (body,) = fake.sent("POST", "/work_packages")
    assert body == {
        "subject": "Renew the certificate",
        "description": {"format": "markdown", "raw": "Created by the Homelab Manager bot."},
        "dueDate": "2026-11-01",
        # A String custom field is written plain, a Formattable one as {raw}.
        "customField7": "Personal/Tech/Certificates.md",
        "customField8": {"raw": "The certificate is renewed and served."},
        "_links": {
            "project": {"href": "/api/v3/projects/5"},
            "type": {"href": "/api/v3/types/1"},
            "priority": {"href": "/api/v3/priorities/9"},
            "assignee": {"href": "/api/v3/users/23"},
        },
    }
    assert out["task"]["context"] == "Personal/Tech/Certificates.md"
    assert out["task"]["done_when"] == "The certificate is renewed and served."
    # The form is asked with the same links but the project, which is in its path.
    (form,) = fake.sent("POST", "/projects/5/work_packages/form")
    assert form == {
        "_links": {
            "type": {"href": "/api/v3/types/1"},
            "priority": {"href": "/api/v3/priorities/9"},
            "assignee": {"href": "/api/v3/users/23"},
        }
    }
    # Members of the target project only, users only, searched by name attributes
    # (which includes the login even when OpenProject does not show it).
    filters = fake.filters("GET", "/principals")
    assert {"member": {"operator": "=", "values": ["5"]}} in filters
    assert {"type": {"operator": "=", "values": ["User"]}} in filters
    assert {"any_name_attribute": {"operator": "~", "values": ["hank"]}} in filters
    assert all(c.headers["authorization"] == basic(T) for c in fake.calls)


async def test_assignee_by_login_picks_the_exact_login_among_several(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/principals", fx("principals_two_hanks"))
    fake.on("POST", "/work_packages", fx("wp_103_created"), status=201)
    # Hank's login is known once Hank has used the server.
    await op.whoami(TOKEN_HANK)
    await op.create_task(T, subject="x", **HANDOFF, project="homelab", assignee="hank")
    assert fake.sent("POST", "/work_packages")[0]["_links"]["assignee"] == {
        "href": "/api/v3/users/23"
    }


async def test_assignee_by_display_name(op: OpenProject, fake: FakeOpenProject) -> None:
    fake.on("GET", "/principals", fx("principals_two_hanks"))
    fake.on("POST", "/work_packages", fx("wp_103_created"), status=201)
    await op.create_task(T, subject="x", **HANDOFF, project="homelab", assignee="Hank Hill")
    assert fake.sent("POST", "/work_packages")[0]["_links"]["assignee"] == {
        "href": "/api/v3/users/24"
    }


async def test_assignee_ambiguous_or_unknown_is_an_error_before_creating(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/principals", fx("principals_two_hanks"))
    out = await op.create_task(T, subject="x", **HANDOFF, project="homelab", assignee="han")
    assert out["error"]["code"] == "openproject_ambiguous_assignee"
    assert "Hank Hill" in out["error"]["hint"]
    fake.on("GET", "/principals", fx("principals_empty"))
    out = await op.create_task(T, subject="x", **HANDOFF, project="homelab", assignee="nobody")
    assert out["error"]["code"] == "openproject_unknown_assignee"
    assert not fake.sent("POST", "/work_packages")


async def test_assignee_me_and_numeric_skip_the_principals_lookup(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("POST", "/work_packages", fx("wp_103_created"), status=201)
    await op.create_task(T, subject="x", **HANDOFF, project="homelab", assignee="me")
    await op.create_task(T, subject="x", **HANDOFF, project="homelab", assignee="42")
    assert [b["_links"]["assignee"] for b in fake.sent("POST", "/work_packages")] == [
        {"href": "/api/v3/users/21"},
        {"href": "/api/v3/users/42"},
    ]
    assert not fake.query("GET", "/principals")


async def test_create_task_needs_a_project_unless_there_is_a_default(
    make_op, fake: FakeOpenProject
) -> None:
    op = make_op()
    out = await op.create_task(T, subject="x", **HANDOFF)
    assert out["error"]["code"] == "openproject_project_required"
    fake.on("POST", "/work_packages", fx("wp_103_created"), status=201)
    op = make_op(default_project="homelab")
    assert (await op.create_task(T, subject="x", **HANDOFF))["created"] is True
    assert fake.sent("POST", "/work_packages")[0]["_links"]["project"] == {
        "href": "/api/v3/projects/5"
    }


async def test_create_task_rejects_a_bad_date_before_calling_out(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    out = await op.create_task(T, subject="x", **HANDOFF, project="homelab", due_date="next week")
    assert out["error"]["code"] == "openproject_bad_date"
    assert not fake.sent("POST", "/work_packages")


async def test_create_needs_the_projects_handoff_fields(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("POST", "/projects/5/work_packages/form", fx("wp_form_without_handoff_fields"))
    out = await op.create_task(T, subject="x", project="homelab", **HANDOFF)
    assert out["error"]["code"] == "openproject_fields_missing"
    assert "'Context' or 'Done when'" in out["error"]["message"]
    assert fake.sent("POST", "/projects/5/work_packages/form")
    assert not fake.sent("POST", "/work_packages")


async def test_create_refuses_a_blank_handoff_before_calling_out(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    for context, done_when in (("  ", "x is done."), ("Inbox/x.md", ""), ("", " ")):
        out = await op.create_task(
            T, subject="x", context=context, done_when=done_when, project="homelab"
        )
        assert out["error"]["code"] == "openproject_handoff_incomplete"
    assert not fake.calls


async def test_create_finds_the_fields_by_configured_name_case_insensitively(
    make_op, fake: FakeOpenProject
) -> None:
    form = fx("wp_form_with_handoff_fields")
    schema = form["_embedded"]["schema"]
    schema["customField8"]["name"] = "Acceptance"
    schema["customField7"]["name"] = "CONTEXT"
    fake.on("POST", "/projects/5/work_packages/form", form)
    fake.on("POST", "/work_packages", fx("wp_103_created"), status=201)
    op = make_op(done_when_field="acceptance")
    assert (await op.create_task(T, subject="x", project="homelab", **HANDOFF))["created"]
    (body,) = fake.sent("POST", "/work_packages")
    assert body["customField7"] == "Inbox/x.md"
    assert body["customField8"] == {"raw": "x is done."}


async def test_a_decision_for_ryan_goes_to_him_with_needs_ryan(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    statuses = fx("statuses")
    statuses["_embedded"]["elements"].append(
        {"_type": "Status", "id": 15, "name": "Needs Ryan", "isClosed": False}
    )
    fake.on("GET", "/statuses", statuses)
    fake.on("POST", "/work_packages", fx("wp_103_created"), status=201)
    out = await op.create_task(
        T,
        subject="Pick a cut target",
        context="Personal/Fitness/Inbox.md",
        done_when="Ryan has chosen a calorie target.",
        project="homelab",
        assignee="1",
        status="needs ryan",
    )
    assert out["created"] is True
    (body,) = fake.sent("POST", "/work_packages")
    assert body["_links"]["assignee"] == {"href": "/api/v3/users/1"}
    assert body["_links"]["status"] == {"href": "/api/v3/statuses/15"}
    # The form is asked for that status too: its schema can differ by status.
    (form,) = fake.sent("POST", "/projects/5/work_packages/form")
    assert form["_links"]["status"] == {"href": "/api/v3/statuses/15"}


async def test_create_with_an_unknown_status_is_refused_before_creating(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    out = await op.create_task(T, subject="x", project="homelab", status="Nope", **HANDOFF)
    assert out["error"]["code"] == "openproject_unknown_status"
    assert not fake.sent("POST", "/work_packages")


async def test_get_task_shows_the_handoff_fields(op: OpenProject, fake: FakeOpenProject) -> None:
    wp = fx("wp_101_new")
    wp["customField7"] = "Personal/Fitness/Plan.md"
    wp["customField8"] = {"format": "markdown", "raw": "The plan names a target.", "html": ""}
    fake.on("GET", "/work_packages/101", wp)
    fake.on("GET", "/work_packages/schemas/9-1", fx("wp_schema_9_1"))
    out = await op.get_task(T, 101, comments=0)
    assert out["context"] == "Personal/Fitness/Plan.md"
    assert out["done_when"] == "The plan names a target."
    # The schema is cached: a second read does not fetch it again.
    await op.get_task(T, 101, comments=0)
    assert len(fake.query("GET", "/work_packages/schemas/9-1")) == 1


async def test_get_task_handoff_fields_are_null_when_unset_or_unreadable(
    op: OpenProject, fake: FakeOpenProject
) -> None:
    fake.on("GET", "/work_packages/102", fx("wp_102_new"))
    fake.on("GET", "/work_packages/schemas/5-1", fx("wp_schema_5_1"))
    out = await op.get_task(T, 102, comments=0)
    assert "error" not in out
    assert (out["context"], out["done_when"]) == (None, None)
    # A schema OpenProject will not serve leaves them null, not an error.
    fake.on("GET", "/work_packages/101", fx("wp_101_new"))
    out = await op.get_task(T, 101, comments=0)
    assert "error" not in out
    assert (out["context"], out["done_when"]) == (None, None)


# ── config ────────────────────────────────────────────────────────────


def test_base_url_tolerates_an_api_v3_suffix() -> None:
    assert normalize_base("https://tasks.test/api/v3/") == "https://tasks.test"
    assert normalize_base("https://tasks.test/") == "https://tasks.test"


def test_settings_from_env() -> None:
    s = Settings.from_env({})
    assert s.api_base == "http://openproject.openproject.svc.cluster.local:8080"
    assert s.web_base == s.api_base
    assert s.port == 8000 and s.claim_max_attempts == 5 and s.cache_seconds == 600
    assert s.ready_statuses == ("New",) and s.default_project is None
    assert (s.context_field, s.done_when_field) == ("Context", "Done when")
    assert "openproject-mcp.openproject.svc.cluster.local:*" in s.allowed_hosts
    assert "openproject-mcp.openproject.svc.cluster.local" in s.allowed_hosts
    s = Settings.from_env(
        {
            "OPENPROJECT_URL": "http://op:8080/api/v3",
            "OPENPROJECT_PUBLIC_URL": "https://tasks.example.test",
            "OPENPROJECT_DEFAULT_PROJECT": "bots",
            "OPENPROJECT_READY_STATUSES": "New, Ready",
            "OPENPROJECT_DONE_STATUS": "Done",
            "OPENPROJECT_CONTEXT_FIELD": "Vault note",
            "OPENPROJECT_DONE_WHEN_FIELD": "Acceptance",
            "OPENPROJECT_CLAIM_MAX_ATTEMPTS": "3",
            "OPENPROJECT_CACHE_SECONDS": "0",
            "PORT": "9000",
            "ALLOWED_HOSTS": "mcp.test:*",
        }
    )
    assert s.api_base == "http://op:8080" and s.web_base == "https://tasks.example.test"
    assert s.default_project == "bots" and s.ready_statuses == ("New", "Ready")
    assert s.done_status == "Done" and s.claim_max_attempts == 3 and s.port == 9000
    assert s.identity_seconds == 0
    assert (s.context_field, s.done_when_field) == ("Vault note", "Acceptance")
    assert s.allowed_hosts == ("mcp.test:*", "mcp.test")
    with pytest.raises(ValueError, match="OPENPROJECT_CLAIM_MAX_ATTEMPTS"):
        Settings.from_env({"OPENPROJECT_CLAIM_MAX_ATTEMPTS": "50"})


def test_expand_hosts() -> None:
    assert expand_hosts(["a:*", "b", "a"]) == ["a:*", "a", "b"]
