"""Server-rendered calendar page tests (Checkpoint 3).

Monthly grid, navigation, day selection, and the create/edit/delete/
cancel forms - driven like a browser (CSRF tokens included).
"""
import html
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import utcnow
from tests.conftest import api_login, csrf_token_from, make_user, page_login


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


def _create_event_api(client, payload, username="alice", password="alicepass123"):
    _login(client, username, password)
    response = client.post("/api/events", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


ALICE_EVENT = {
    "title": "Study session",
    "event_date": "2026-09-20T10:00:00",
    "event_type": "general",
}


# ------------------------------------------------------------ month grid


def test_calendar_page_is_public(calendar_client):
    response = calendar_client.get("/calendar")
    assert response.status_code == 200
    now = utcnow()
    assert f"{now.strftime('%B')} {now.year}" in response.text  # current month
    assert "Prev" in response.text and "Next" in response.text
    # Guests are invited to log in to add events.
    assert "/login?next=/calendar/new" in response.text


def test_month_navigation(calendar_client):
    october = calendar_client.get("/calendar", params={"month": "2026-10"})
    assert "October 2026" in october.text
    assert "/calendar?month=2026-09" in october.text  # prev
    assert "/calendar?month=2026-11" in october.text  # next

    december = calendar_client.get("/calendar", params={"month": "2026-12"})
    assert "/calendar?month=2027-01" in december.text  # year wraps forward
    january = calendar_client.get("/calendar", params={"month": "2027-01"})
    assert "/calendar?month=2026-12" in january.text  # and backward


def test_day_selection_shows_that_days_events(calendar_client):
    _create_event_api(calendar_client, ALICE_EVENT)
    _login(calendar_client, "alice", "alicepass123")

    day = calendar_client.get("/calendar", params={"date": "2026-09-20"})
    assert "Sunday, 20 September 2026" in day.text
    assert "Study session" in day.text
    assert "1 event" in day.text  # count chip in the grid cell

    empty = calendar_client.get("/calendar", params={"date": "2026-09-21"})
    assert "No events on this day" in empty.text
    assert "Study session" not in empty.text


def test_guests_see_only_library_wide_events(calendar_client):
    _create_event_api(calendar_client, ALICE_EVENT)
    _create_event_api(
        calendar_client,
        {
            "title": "Library closed on Monday",
            "event_date": "2026-09-20T09:00:00",
            "event_type": "announcement",
        },
        username="root",
        password="rootpass123",
    )

    calendar_client.cookies.clear()
    guest = calendar_client.get("/calendar", params={"date": "2026-09-20"})
    assert "Library closed on Monday" in guest.text
    assert "Study session" not in guest.text
    assert "library announcement" in guest.text.lower() or "Library announcement" in guest.text

    _login(calendar_client, "alice", "alicepass123")
    member = calendar_client.get("/calendar", params={"date": "2026-09-20"})
    assert "Study session" in member.text  # owner sees her own event


# ---------------------------------------------------------- create form


def test_create_event_via_page(calendar_client):
    page_login(calendar_client, "alice", "alicepass123")
    form_page = calendar_client.get("/calendar/new", params={"date": "2026-09-22"})
    assert "New event" in form_page.text
    assert 'value="2026-09-22"' in form_page.text  # prefilled date
    # Members do not get admin-only types in the selector.
    assert '<option value="announcement"' not in form_page.text
    assert '<option value="maintenance"' not in form_page.text

    response = calendar_client.post(
        "/calendar/new",
        data={
            "title": "Return Dune",
            "description": "Front desk",
            "event_date": "2026-09-22",
            "event_time": "16:45",
            "event_type": "reminder",
            "book_id": "1",
            "_csrf": csrf_token_from(form_page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/calendar?date=2026-09-22"

    day_text = html.unescape(calendar_client.get(response.headers["location"]).text)
    assert "Event 'Return Dune' was created." in day_text  # flash
    assert "Return Dune" in day_text
    assert "16:45" in day_text
    assert "Harry Potter" in day_text  # related book link


def test_create_form_validation(calendar_client):
    page_login(calendar_client, "alice", "alicepass123")
    token = csrf_token_from(calendar_client.get("/calendar/new").text)

    empty_title = calendar_client.post(
        "/calendar/new",
        data={
            "title": "", "description": "", "event_date": "2026-09-22",
            "event_time": "09:00", "event_type": "general", "book_id": "",
            "_csrf": token,
        },
    )
    assert empty_title.status_code == 200  # re-rendered form
    assert "Title is required" in empty_title.text

    bad_date = calendar_client.post(
        "/calendar/new",
        data={
            "title": "X", "description": "", "event_date": "September",
            "event_time": "09:00", "event_type": "general", "book_id": "",
            "_csrf": token,
        },
    )
    assert bad_date.status_code == 200
    assert "valid date and time" in bad_date.text

    escalated = calendar_client.post(
        "/calendar/new",
        data={
            "title": "Sneaky", "description": "", "event_date": "2026-09-22",
            "event_time": "09:00", "event_type": "announcement", "book_id": "",
            "_csrf": token,
        },
    )
    assert escalated.status_code == 200
    assert "Only admins" in escalated.text


def test_admin_can_create_announcement_via_page(calendar_client):
    page_login(calendar_client, "root", "rootpass123")
    form_page = calendar_client.get("/calendar/new")
    assert "announcement" in form_page.text  # admin gets library-wide types
    response = calendar_client.post(
        "/calendar/new",
        data={
            "title": "Annual inventory week",
            "description": "",
            "event_date": "2026-09-23",
            "event_time": "08:00",
            "event_type": "maintenance",
            "book_id": "",
            "_csrf": csrf_token_from(form_page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Annual inventory week" in calendar_client.get(
        response.headers["location"]
    ).text


# --------------------------------------------------- edit / cancel / delete


def test_edit_event_via_page(calendar_client):
    event = _create_event_api(calendar_client, ALICE_EVENT)
    page_login(calendar_client, "alice", "alicepass123")

    form_page = calendar_client.get(f"/calendar/{event['id']}/edit")
    assert 'value="Study session"' in form_page.text
    assert 'value="2026-09-20"' in form_page.text

    response = calendar_client.post(
        f"/calendar/{event['id']}/edit",
        data={
            "title": "Deep work session",
            "description": "Silent floor",
            "event_date": "2026-09-20",
            "event_time": "10:00",
            "event_type": "general",
            "book_id": "",
            "_csrf": csrf_token_from(form_page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    day = calendar_client.get("/calendar", params={"date": "2026-09-20"})
    assert "Deep work session" in day.text
    assert "Study session" not in day.text


def test_member_cannot_manage_others_events(calendar_client):
    event = _create_event_api(calendar_client, ALICE_EVENT)
    # api_login always replaces the active session (the page login form
    # redirects signed-in users, so it cannot be used to switch accounts).
    _login(calendar_client, "bob", "bobpass123")

    assert calendar_client.get(f"/calendar/{event['id']}/edit").status_code == 404

    token = csrf_token_from(calendar_client.get("/calendar").text)
    response = calendar_client.post(
        f"/calendar/{event['id']}/delete",
        data={"_csrf": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "own events" in calendar_client.get(response.headers["location"]).text

    # The event still exists.
    _login(calendar_client, "alice", "alicepass123")
    day = calendar_client.get("/calendar", params={"date": "2026-09-20"})
    assert "Study session" in day.text


def test_admin_manages_all_events_via_page(calendar_client):
    event = _create_event_api(calendar_client, ALICE_EVENT)
    _login(calendar_client, "root", "rootpass123")

    day = calendar_client.get("/calendar", params={"date": "2026-09-20"})
    assert "Study session" in day.text
    assert f"/calendar/{event['id']}/edit" in day.text  # admin gets controls

    token = csrf_token_from(day.text)
    response = calendar_client.post(
        f"/calendar/{event['id']}/delete",
        data={"_csrf": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    after = calendar_client.get(response.headers["location"])
    assert "was deleted" in after.text  # flash confirmation
    # The event card is gone (the flash message itself quotes the title).
    assert f"/calendar/{event['id']}/edit" not in after.text


def test_cancel_via_page(calendar_client):
    event = _create_event_api(
        calendar_client,
        {**ALICE_EVENT, "title": "Return Hamlet", "event_type": "reminder"},
    )
    page_login(calendar_client, "alice", "alicepass123")
    day = calendar_client.get("/calendar", params={"date": "2026-09-20"})
    token = csrf_token_from(day.text)

    response = calendar_client.post(
        f"/calendar/{event['id']}/cancel",
        data={"_csrf": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    after = calendar_client.get(response.headers["location"])
    assert "was cancelled" in after.text
    assert "Cancelled" in after.text  # status badge


# ------------------------------------------------------------ dashboard


def test_account_shows_upcoming_events(calendar_client):
    future = utcnow() + timedelta(days=5)
    _create_event_api(
        calendar_client,
        {
            "title": "Future study session",
            "event_date": future.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": "general",
        },
    )
    page_login(calendar_client, "alice", "alicepass123")
    account = calendar_client.get("/account").text
    assert "Upcoming schedule" in account
    assert "Future study session" in account
    assert f"/calendar?date={future.date().isoformat()}" in account
