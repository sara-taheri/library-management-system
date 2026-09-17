"""Admin dashboard (M3) and role-aware account summary."""
from datetime import timedelta

from sqlalchemy import select

from app.database import utcnow
from app.models import Loan
from tests.conftest import api_login, make_user, page_login

METRIC_LABELS = [
    "Members",
    "Book titles",
    "Available books",
    "Available copies",
    "Borrowed books",
    "Active loans",
    "Overdue loans",
    "Due soon",
    "Calendar events",
    "Upcoming events",
]


def test_admin_dashboard_shows_rich_metrics(client, admin_account):
    page_login(client, **admin_account)
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert "Admin overview" in html
    for label in METRIC_LABELS:
        assert label in html
    assert "Recent activity" in html
    assert "No recent borrowing or calendar activity yet." in html
    assert 'href="/books?available=1"' in html
    assert 'href="/admin/loans?status=overdue"' in html


def test_admin_dashboard_recent_activity_after_borrow(seeded_app, seeded_client):
    make_user(seeded_app, "alice", "alicepass123")
    make_user(seeded_app, "root", "rootpass123", role="admin")
    api_login(seeded_client, "alice", "alicepass123")
    borrowed = seeded_client.post("/api/loans", json={"book_id": 1})
    assert borrowed.status_code == 201

    api_login(seeded_client, "root", "rootpass123")
    html = seeded_client.get("/admin").text
    assert "Harry Potter" in html
    assert "Borrowed" in html
    assert "alice" in html
    assert "No recent borrowing or calendar activity yet." not in html


def test_member_account_shows_personal_summary_not_admin_metrics(
    client, member_account
):
    page_login(client, **member_account)
    account = client.get("/account")
    assert account.status_code == 200
    html = account.text
    assert "My library summary" in html or "Active loans" in html
    assert "Admin overview" not in html
    assert 'href="/admin"' not in html
    assert "Available copies" not in html
    home = client.get("/").text
    assert 'href="/admin"' not in home


def test_admin_sees_admin_nav_and_account_shortcut(client, admin_account):
    page_login(client, **admin_account)
    account = client.get("/account").text
    assert 'href="/admin"' in account
    assert "Admin overview" in account
    admin = client.get("/admin")
    assert admin.status_code == 200
    assert 'href="/admin" aria-current="page"' in admin.text


def test_member_cannot_open_admin_loans(client, member_account):
    page_login(client, **member_account)
    response = client.get("/admin/loans", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] in ("/admin", "/account")


def test_overdue_loan_filter(seeded_app, seeded_client):
    make_user(seeded_app, "alice", "alicepass123")
    make_user(seeded_app, "root", "rootpass123", role="admin")
    api_login(seeded_client, "alice", "alicepass123")
    assert seeded_client.post("/api/loans", json={"book_id": 1}).status_code == 201
    assert seeded_client.post("/api/loans", json={"book_id": 2}).status_code == 201

    with seeded_app.state.session_factory() as db:
        first = db.scalar(select(Loan).order_by(Loan.id))
        first.due_at = utcnow() - timedelta(days=2)
        db.commit()

    api_login(seeded_client, "root", "rootpass123")
    overdue = seeded_client.get("/admin/loans", params={"status": "overdue"})
    assert overdue.status_code == 200
    assert "1 loan" in overdue.text
    assert "Harry Potter" in overdue.text
    assert "The Notebook" not in overdue.text
    dashboard = seeded_client.get("/admin").text
    assert "Overdue loans" in dashboard
