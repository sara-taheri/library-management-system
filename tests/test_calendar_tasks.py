"""Selected-day briefing, run-tasks button, and A ± B calculator."""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import CalendarEvent, EventStatus, User
from app.services import event_service, loan_service
from tests.conftest import csrf_token_from, make_user, page_login


def _login_page(client, username, password):
    page_login(client, username, password)
    return client


def test_selected_day_briefing_respects_visibility(seeded_app):
    make_user(seeded_app, "alice", "alicepass123")
    make_user(seeded_app, "root", "rootpass123", role="admin")
    day = datetime(2026, 9, 20, 10, 0, 0)

    with seeded_app.state.session_factory() as db:
        alice = db.scalar(select(User).where(User.username == "alice"))
        loan = loan_service.borrow_book(db, user=alice, book_id=1, now=day)
        # Force the due date onto the selected calendar day for the briefing.
        loan.due_at = day + timedelta(hours=4)
        reminder = db.scalar(
            select(CalendarEvent).where(CalendarEvent.loan_id == loan.id)
        )
        reminder.event_date = loan.due_at
        reminder.scheduled_at = loan.due_at
        db.commit()

    with TestClient(seeded_app) as client:
        guest = client.get("/calendar", params={"date": "2026-09-20"})
        assert guest.status_code == 200
        assert "This day" in guest.text
        assert "Books due" in guest.text
        assert "Sign in to see loans" in guest.text
        briefing_html = guest.text.split("id=\"briefing-heading\"")[1].split("Events on")[0]
        assert "Harry Potter" not in briefing_html
        assert "Run pending tasks" not in guest.text

        _login_page(client, "alice", "alicepass123")
        member = client.get("/calendar", params={"date": "2026-09-20"})
        assert "Harry Potter" in member.text
        assert "Showing your loans" in member.text
        assert "Run pending tasks" in member.text
        assert 'name="a"' in member.text  # calculator

        client.cookies.clear()
        _login_page(client, "root", "rootpass123")
        admin = client.get("/calendar", params={"date": "2026-09-20"})
        assert "Showing every member's loans" in admin.text
        assert "Harry Potter" in admin.text
        assert "alice" in admin.text  # borrower name for admins


def test_run_pending_tasks_for_selected_date(seeded_app):
    make_user(seeded_app, "alice", "alicepass123")
    when = datetime(2026, 9, 22, 9, 0, 0)
    with seeded_app.state.session_factory() as db:
        alice = db.scalar(select(User).where(User.username == "alice"))
        event = event_service.create_event(
            db,
            creator=alice,
            title="Study reminder",
            event_date=when,
            event_type="reminder",
        )
        event_id = event.id

    with TestClient(seeded_app) as client:
        _login_page(client, "alice", "alicepass123")
        page = client.get("/calendar", params={"date": "2026-09-22"})
        token = csrf_token_from(page.text)
        response = client.post(
            "/calendar/run",
            data={"_csrf": token, "date": "2026-09-22"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/calendar?date=2026-09-22"
        after = client.get(response.headers["location"])
        assert "1 completed, 0 failed" in after.text
        assert "Study reminder" in after.text
        assert "Reminder delivered to alice: Study reminder" in after.text

    with seeded_app.state.session_factory() as db:
        stored = db.get(CalendarEvent, event_id)
        assert stored.status == EventStatus.COMPLETED.value


def test_run_tasks_does_not_touch_other_days(seeded_app):
    make_user(seeded_app, "alice", "alicepass123")
    with seeded_app.state.session_factory() as db:
        from sqlalchemy import select
        from app.models import User

        alice = db.scalar(select(User).where(User.username == "alice"))
        keep = event_service.create_event(
            db,
            creator=alice,
            title="Other day",
            event_date=datetime(2026, 9, 23, 9, 0, 0),
            event_type="reminder",
        )
        keep_id = keep.id

    with TestClient(seeded_app) as client:
        _login_page(client, "alice", "alicepass123")
        token = csrf_token_from(
            client.get("/calendar", params={"date": "2026-09-22"}).text
        )
        client.post(
            "/calendar/run",
            data={"_csrf": token, "date": "2026-09-22"},
            follow_redirects=True,
        )

    with seeded_app.state.session_factory() as db:
        stored = db.get(CalendarEvent, keep_id)
        assert stored.status == EventStatus.PENDING.value


def test_calculator_two_plus_three(seeded_app):
    make_user(seeded_app, "alice", "alicepass123")
    with TestClient(seeded_app) as client:
        _login_page(client, "alice", "alicepass123")
        token = csrf_token_from(
            client.get("/calendar", params={"date": "2026-09-22"}).text
        )
        response = client.post(
            "/calendar/calculate",
            data={"_csrf": token, "date": "2026-09-22", "a": "2", "b": "3", "op": "+"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        page = client.get(response.headers["location"])
        assert "2 + 3 = 5" in page.text
        assert "Calculation: 2 + 3" in page.text


def test_calculator_ten_minus_four(seeded_app):
    make_user(seeded_app, "alice", "alicepass123")
    with TestClient(seeded_app) as client:
        _login_page(client, "alice", "alicepass123")
        token = csrf_token_from(
            client.get("/calendar", params={"date": "2026-09-22"}).text
        )
        response = client.post(
            "/calendar/calculate",
            data={"_csrf": token, "date": "2026-09-22", "a": "10", "b": "4", "op": "-"},
            follow_redirects=True,
        )
        assert "10 - 4 = 6" in response.text


def test_calculator_rejects_invalid_input(seeded_app):
    make_user(seeded_app, "alice", "alicepass123")
    with TestClient(seeded_app) as client:
        _login_page(client, "alice", "alicepass123")
        token = csrf_token_from(
            client.get("/calendar", params={"date": "2026-09-22"}).text
        )
        letters = client.post(
            "/calendar/calculate",
            data={"_csrf": token, "date": "2026-09-22", "a": "two", "b": "3", "op": "+"},
            follow_redirects=True,
        )
        assert "A and B must be numbers." in letters.text
        assert "two + 3" not in letters.text

        bad_op = client.post(
            "/calendar/calculate",
            data={"_csrf": token, "date": "2026-09-22", "a": "2", "b": "3", "op": "*"},
            follow_redirects=True,
        )
        assert "Operator must be + or -." in bad_op.text

        empty = client.post(
            "/calendar/calculate",
            data={"_csrf": token, "date": "2026-09-22", "a": "", "b": "3", "op": "+"},
            follow_redirects=True,
        )
        assert "A is required." in empty.text
