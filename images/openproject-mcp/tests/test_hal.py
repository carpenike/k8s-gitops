"""HAL -> slim translation (pure). Ported from homelab-mcp."""

from __future__ import annotations

from conftest import fx

from openproject_mcp import hal

WEB = "https://tasks.example.test"


def test_slim_work_package_flattens_links_and_truncates_plain_description() -> None:
    slim = hal.slim_work_package(fx("wp_101_new"), web_base=WEB, description_chars=120)
    assert slim["id"] == 101
    assert slim["subject"] == "Rotate tunnel credentials"
    assert slim["status"] == "New" and slim["status_id"] == 1
    assert slim["assignee"] is None and slim["assignee_id"] is None
    assert slim["project"] == "Bots — Shared" and slim["project_id"] == 9
    assert slim["priority"] == "High"
    assert slim["type"] == "Task"
    assert slim["due_date"] == "2026-10-22"
    assert slim["lock_version"] == 3
    assert slim["url"] == f"{WEB}/work_packages/101"
    # Plain text: no markdown markers, no link targets, entities decoded.
    text = slim["description"]
    assert text.startswith("Goal Rotate the Cloudflare tunnel credentials")
    assert "**" not in text and "wiki.example.test" not in text and "##" not in text
    assert "the runbook" in text
    assert slim["description_truncated"] is True and text.endswith("…")
    assert len(text) <= 121
    # Nothing HAL-shaped leaks through.
    assert "_links" not in slim and "_embedded" not in slim


def test_slim_work_package_reports_the_assignee_and_short_description_untruncated() -> None:
    slim = hal.slim_work_package(fx("wp_102_claimed"))
    assert slim["assignee"] == "Homelab Manager" and slim["assignee_id"] == 21
    assert slim["description"] == "Keep 30 days of tank/media snapshots."
    assert slim["description_truncated"] is False
    assert slim["url"] is None


def test_slim_comments_drops_field_journals_and_returns_newest_first() -> None:
    comments = hal.slim_comments(fx("activities_101"), 2)
    assert [c["id"] for c in comments] == [505, 504]
    assert comments[0]["author"] == "Ryan Holt"
    assert comments[0]["text"] == "Agreed, leaving it for Homelab."
    assert comments[1]["text"] == "Looked at it; this is Homelab's job, not mine."
    assert len(hal.slim_comments(fx("activities_101"), 10)) == 3


def test_slim_comments_carry_author_id_and_login() -> None:
    comments = hal.slim_comments(fx("activities_101"), 3, {1: None, 22: "bot-finances"})
    assert [(c["author_id"], c["author_login"]) for c in comments] == [
        (1, None),
        (22, "bot-finances"),
        (1, None),
    ]


def test_slim_user_hides_nothing_it_was_not_given() -> None:
    assert hal.slim_user(fx("users_me_homelab")) == {
        "id": 21,
        "login": "bot-homelab",
        "name": "Homelab Manager",
    }
    assert hal.slim_user(fx("user_1_as_member")) == {"id": 1, "login": None, "name": "Ryan Holt"}
    assert hal.slim_user(None) == {"id": None, "login": None, "name": None}


def test_href_id_and_null_links() -> None:
    assert hal.href_id({"href": "/api/v3/users/7"}) == 7
    assert hal.href_id({"href": None}) is None
    assert hal.href_id(None) is None
    assert hal.link("users", None) == {"href": None}
    assert hal.link("statuses", 7) == {"href": "/api/v3/statuses/7"}
