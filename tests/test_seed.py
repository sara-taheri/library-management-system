"""First-boot seed: empty DB gets sample books + bcrypt demo users once."""
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import Book, Loan, User
from app.services.seed_service import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_USERNAME,
    DEMO_MEMBER_PASSWORD,
    DEMO_MEMBER_USERNAME,
    seed_if_empty,
)
from app.utils.security import BCRYPT
from tests.conftest import page_login


def _make_app(tmp_path, *, seed: bool):
    db_file = tmp_path / "seed_library.db"
    application = create_app(database_url=f"sqlite:///{db_file}", seed=seed)
    return application


def test_empty_database_is_seeded(tmp_path):
    application = _make_app(tmp_path, seed=True)
    with application.state.session_factory() as db:
        books = list(db.scalars(select(Book).order_by(Book.id)).all())
        users = list(db.scalars(select(User).order_by(User.id)).all())
        loans = db.scalar(select(func.count()).select_from(Loan)) or 0

    titles = {book.title for book in books}
    assert "Harry Potter" in titles
    assert "Hamlet" in titles
    assert len(books) == 3
    assert loans == 0  # borrows.json is not imported

    usernames = {user.username: user for user in users}
    assert set(usernames) == {DEMO_ADMIN_USERNAME, DEMO_MEMBER_USERNAME}
    assert usernames[DEMO_ADMIN_USERNAME].role == "admin"
    assert usernames[DEMO_MEMBER_USERNAME].role == "member"
    for user in users:
        assert user.hash_algorithm == BCRYPT
        assert user.password_hash != DEMO_ADMIN_PASSWORD
        assert user.password_hash != DEMO_MEMBER_PASSWORD
        assert not user.password_hash.startswith("240be518")  # not SHA-256 hex
    application.state.engine.dispose()


def test_seed_does_not_duplicate_on_restart(tmp_path):
    db_file = tmp_path / "seed_library.db"
    url = f"sqlite:///{db_file}"
    first = create_app(database_url=url, seed=True)
    with first.state.session_factory() as db:
        book_ids = [book.id for book in db.scalars(select(Book)).all()]
        user_ids = [user.id for user in db.scalars(select(User)).all()]
    first.state.engine.dispose()

    second = create_app(database_url=url, seed=True)
    with second.state.session_factory() as db:
        assert [book.id for book in db.scalars(select(Book)).all()] == book_ids
        assert [user.id for user in db.scalars(select(User)).all()] == user_ids
        assert db.scalar(select(func.count()).select_from(Book)) == 3
        assert db.scalar(select(func.count()).select_from(User)) == 2
        # Calling the service again is also a no-op.
        again = seed_if_empty(db)
        assert again == {"books": 0, "users": 0}
    second.state.engine.dispose()


def test_tests_do_not_seed_by_default(tmp_path):
    """create_app(database_url=...) must stay empty so existing tests hold."""
    application = _make_app(tmp_path, seed=False)
    with application.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Book)) == 0
        assert db.scalar(select(func.count()).select_from(User)) == 0
    application.state.engine.dispose()


def test_demo_admin_can_log_in(tmp_path):
    application = _make_app(tmp_path, seed=True)
    with TestClient(application) as client:
        response = page_login(
            client, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD
        )
        assert response.status_code == 200
        assert response.url.path == "/account"
        assert DEMO_ADMIN_USERNAME in response.text
        admin_page = client.get("/admin")
        assert admin_page.status_code == 200
        assert "Admin overview" in admin_page.text
    application.state.engine.dispose()


def test_demo_member_is_blocked_from_admin(tmp_path):
    application = _make_app(tmp_path, seed=True)
    from fastapi.testclient import TestClient

    with TestClient(application) as client:
        page_login(client, DEMO_MEMBER_USERNAME, DEMO_MEMBER_PASSWORD)
        response = client.get("/admin", follow_redirects=True)
        assert response.url.path == "/account"
        assert "Access denied. Admins only." in response.text
        assert 'href="/admin"' not in response.text.split("<footer", 1)[0]
    application.state.engine.dispose()
