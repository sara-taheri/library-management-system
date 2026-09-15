"""Calendar events API tests (Checkpoint 3).

Covers creation, listing by date/month, editing, deletion, cancelling
and the visibility/permission rules (owner, member, admin, guest).
"""
import pytest
from fastapi.testclient import TestClient

from app.models import EventStatus
from tests.conftest import api_login, make_user

GENERAL = {
    "title": "Study session",
    "event_date": "2026-09-20T10:00:00",
    "event_type": "general",
}
REMINDER = {
    "title": "Return Dune",
    "description": "Drop it at the front desk",
    "event_date": "2026-09-25T17:30:00",
    "event_type": "reminder",
}
ANNOUNCEMENT = {
    "title": "Library closed on Monday",
    "event_date": "2026-09-21T09:00:00",
    "event_type": "announcement",
}


@pytest.fixture()
def calendar_app(seeded_app):
    make_user(seeded_app, "alice", "alicepass123")
    make_user(seeded_app, "bob", "bobpass123")
    make_user(seeded_app, "root", "rootpass123", role="admin")
    return seeded_app


@pytest.fixture()
def calendar_client(calendar_app):
    with TestClient(calendar_app) as test_client:
        yield test_client


def _login(client, username, password):
    response = api_login(client, username, password)
    assert response.status_code == 200, response.text
    return client


def _create(client, payload, username="alice", password="alicepass123"):
    _login(client, username, password)
    return client.post("/api/events", json=payload)


# ------------------------------------------------------------------ create


def test_create_reminder_as_member(calendar_client):
    response = _create(calendar_client, REMINDER)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Return Dune"
    assert body["event_type"] == "reminder"
    assert body["status"] == "pending"
    assert body["creator_name"] == "alice"
    assert body["is_task"] is True
    assert body["is_public"] is False
    # Task-like events are scheduled for their event date (runner hook).
    assert body["scheduled_at"] == body["event_date"]
    assert body["executed_at"] is None


def test_create_general_event_has_no_schedule(calendar_client):
    body = _create(calendar_client, GENERAL).json()
    assert body["is_task"] is False
    assert body["scheduled_at"] is None


def test_create_requires_login(calendar_client):
    assert calendar_client.post("/api/events", json=GENERAL).status_code == 401


def test_create_validation(calendar_client):
    _login(calendar_client, "alice", "alicepass123")
    missing_title = calendar_client.post(
        "/api/events", json={"event_date": "2026-09-20T10:00:00"}
    )
    assert missing_title.status_code == 422
    bad_date = calendar_client.post(
        "/api/events", json={"title": "X", "event_date": "not-a-date"}
    )
    assert bad_date.status_code == 422
    bad_type = calendar_client.post(
        "/api/events", json={**GENERAL, "event_type": "party"}
    )
    assert bad_type.status_code == 400
    assert "Unknown event type" in bad_type.json()["detail"]


def test_announcements_are_admin_only(calendar_client):
    member = _create(calendar_client, ANNOUNCEMENT)
    assert member.status_code == 403
    assert "Only admins" in member.json()["detail"]

    admin = _create(
        calendar_client, ANNOUNCEMENT, username="root", password="rootpass123"
    )
    assert admin.status_code == 201
    assert admin.json()["is_public"] is True


def test_create_with_book_link(calendar_client):
    linked = _create(calendar_client, {**REMINDER, "book_id": 1})
    assert linked.status_code == 201
    assert linked.json()["book_id"] == 1

    missing = _create(calendar_client, {**GENERAL, "book_id": 9999})
    assert missing.status_code == 404


def test_create_with_loan_link_permissions(calendar_client):
    _login(calendar_client, "alice", "alicepass123")
    loan = calendar_client.post("/api/loans", json={"book_id": 1}).json()

    own = calendar_client.post(
        "/api/events", json={**REMINDER, "loan_id": loan["id"]}
    )
    assert own.status_code == 201
    assert own.json()["loan_id"] == loan["id"]

    _login(calendar_client, "bob", "bobpass123")
    foreign = calendar_client.post(
        "/api/events", json={**REMINDER, "loan_id": loan["id"]}
    )
    assert foreign.status_code == 403


# ------------------------------------------------------------------- lists


def test_list_events_by_date(calendar_client):
    _create(calendar_client, GENERAL)  # alice, 2026-09-20
    _create(calendar_client, {**GENERAL, "title": "Second", "event_date": "2026-09-20T18:00:00"})
    _create(calendar_client, REMINDER)  # alice, 2026-09-25

    _login(calendar_client, "alice", "alicepass123")
    day = calendar_client.get("/api/events", params={"date": "2026-09-20"}).json()
    assert day["total"] == 2
    assert day["day"] == "2026-09-20"
    assert {item["title"] for item in day["items"]} == {"Study session", "Second"}

    other_day = calendar_client.get("/api/events", params={"date": "2026-09-21"}).json()
    assert other_day["total"] == 0


def test_private_events_are_not_visible_to_others(calendar_client):
    _create(calendar_client, GENERAL)  # alice
    _create(
        calendar_client, ANNOUNCEMENT, username="root", password="rootpass123"
    )

    _login(calendar_client, "bob", "bobpass123")
    bob_view = calendar_client.get(
        "/api/events", params={"date": "2026-09-20"}
    ).json()
    assert bob_view["total"] == 0  # alice's general event is private

    bob_view_21 = calendar_client.get(
        "/api/events", params={"date": "2026-09-21"}
    ).json()
    assert [item["title"] for item in bob_view_21["items"]] == [
        "Library closed on Monday"
    ]  # announcements are public

    calendar_client.cookies.clear()
    guest_view = calendar_client.get(
        "/api/events", params={"month": "2026-09"}
    ).json()
    assert [item["title"] for item in guest_view["items"]] == [
        "Library closed on Monday"
    ]


def test_list_events_by_month(calendar_client):
    _create(calendar_client, GENERAL)  # September
    _create(
        calendar_client,
        {**GENERAL, "title": "October plan", "event_date": "2026-10-02T08:00:00"},
    )
    _login(calendar_client, "alice", "alicepass123")
    september = calendar_client.get("/api/events", params={"month": "2026-09"}).json()
    assert september["total"] == 1
    assert september["items"][0]["title"] == "Study session"

    bad_month = calendar_client.get("/api/events", params={"month": "2026-13"})
    assert bad_month.status_code == 422


def test_admin_sees_all_events(calendar_client):
    _create(calendar_client, GENERAL)  # alice
    _create(calendar_client, {**REMINDER}, username="bob", password="bobpass123")

    _login(calendar_client, "root", "rootpass123")
    everything = calendar_client.get("/api/events").json()
    assert everything["total"] == 2
    assert {item["creator_name"] for item in everything["items"]} == {"alice", "bob"}


def test_event_detail_visibility(calendar_client):
    event_id = _create(calendar_client, GENERAL).json()["id"]

    assert calendar_client.get(f"/api/events/{event_id}").status_code == 200  # alice
    _login(calendar_client, "bob", "bobpass123")
    assert calendar_client.get(f"/api/events/{event_id}").status_code == 404  # hidden
    _login(calendar_client, "root", "rootpass123")
    assert calendar_client.get(f"/api/events/{event_id}").status_code == 200  # admin
    assert calendar_client.get("/api/events/9999").status_code == 404

    announcement_id = _create(
        calendar_client, ANNOUNCEMENT, username="root", password="rootpass123"
    ).json()["id"]
    calendar_client.cookies.clear()
    public = calendar_client.get(f"/api/events/{announcement_id}")
    assert public.status_code == 200  # public event, even for guests


# ------------------------------------------------------------ update/delete


def test_update_own_event(calendar_client):
    event_id = _create(calendar_client, GENERAL).json()["id"]
    response = calendar_client.put(
        f"/api/events/{event_id}",
        json={"title": "Deep work", "event_type": "reminder",
              "event_date": "2026-09-22T08:00:00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Deep work"
    assert body["event_type"] == "reminder"
    # Became a task and moved: schedule follows the new date.
    assert body["is_task"] is True
    assert body["scheduled_at"] == body["event_date"]


def test_update_no_fields_is_400(calendar_client):
    event_id = _create(calendar_client, GENERAL).json()["id"]
    assert calendar_client.put(f"/api/events/{event_id}", json={}).status_code == 400


def test_update_permissions(calendar_client):
    event_id = _create(calendar_client, GENERAL).json()["id"]

    _login(calendar_client, "bob", "bobpass123")
    assert calendar_client.put(
        f"/api/events/{event_id}", json={"title": "Hijack"}
    ).status_code == 403

    _login(calendar_client, "root", "rootpass123")
    admin_edit = calendar_client.put(
        f"/api/events/{event_id}", json={"title": "Fixed by admin"}
    )
    assert admin_edit.status_code == 200

    # Members cannot touch library-wide events at all.
    announcement_id = calendar_client.post("/api/events", json=ANNOUNCEMENT).json()["id"]
    _login(calendar_client, "alice", "alicepass123")
    denied = calendar_client.put(
        f"/api/events/{announcement_id}", json={"title": "Nope"}
    )
    assert denied.status_code == 403
    # ...and cannot turn a private event into an announcement.
    own_id = calendar_client.post("/api/events", json=REMINDER).json()["id"]
    escalate = calendar_client.put(
        f"/api/events/{own_id}", json={"event_type": "announcement"}
    )
    assert escalate.status_code == 403


def test_delete_permissions(calendar_client):
    event_id = _create(calendar_client, GENERAL).json()["id"]

    _login(calendar_client, "bob", "bobpass123")
    assert calendar_client.delete(f"/api/events/{event_id}").status_code == 403

    _login(calendar_client, "root", "rootpass123")
    deleted = calendar_client.delete(f"/api/events/{event_id}")
    assert deleted.status_code == 200
    assert "deleted" in deleted.json()["message"]
    assert calendar_client.get(f"/api/events/{event_id}").status_code == 404

    assert calendar_client.delete("/api/events/9999").status_code == 404


def test_delete_own_event(calendar_client):
    event_id = _create(calendar_client, GENERAL).json()["id"]
    deleted = calendar_client.delete(f"/api/events/{event_id}")
    assert deleted.status_code == 200
    _login(calendar_client, "alice", "alicepass123")
    assert calendar_client.get("/api/events").json()["total"] == 0


# ------------------------------------------------------------------ cancel


def test_cancel_event(calendar_client):
    event_id = _create(calendar_client, REMINDER).json()["id"]

    cancelled = calendar_client.post(f"/api/events/{event_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == EventStatus.CANCELLED.value

    # Cancelled events stay visible in the calendar (history)...
    _login(calendar_client, "alice", "alicepass123")
    listed = calendar_client.get("/api/events").json()
    assert listed["total"] == 1
    assert listed["items"][0]["status"] == "cancelled"

    # ...but cannot be cancelled twice.
    again = calendar_client.post(f"/api/events/{event_id}/cancel")
    assert again.status_code == 409
    assert "already cancelled" in again.json()["detail"]


def test_cancel_permissions(calendar_client):
    event_id = _create(calendar_client, REMINDER).json()["id"]
    _login(calendar_client, "bob", "bobpass123")
    assert calendar_client.post(f"/api/events/{event_id}/cancel").status_code == 403
    _login(calendar_client, "root", "rootpass123")
    assert calendar_client.post(f"/api/events/{event_id}/cancel").status_code == 200
