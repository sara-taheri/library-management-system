"""Live FastAPI server + Playwright page fixture for the smoke suite.

Chromium is optional: if Playwright is missing or the browser cannot
launch (typical on locked-down sandboxes without OS libraries), tests
are skipped rather than reported as failures.
"""
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.main import create_app
from app.models import Book
from tests.conftest import make_user

MEMBER = {"username": "testmember", "password": "password123"}
ADMIN = {"username": "testadmin", "password": "adminpass123"}

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment without Playwright
    sync_playwright = None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def playwright_browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed")
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
    except Exception as exc:
        playwright.stop()
        pytest.skip(f"Playwright Chromium cannot launch: {exc}")
    yield browser
    browser.close()
    playwright.stop()


@pytest.fixture(scope="session")
def e2e_app(tmp_path_factory):
    db_file: Path = tmp_path_factory.mktemp("e2e") / "e2e_library.db"
    application = create_app(database_url=f"sqlite:///{db_file}")
    with application.state.session_factory() as db:
        db.add_all(
            [
                Book(
                    id=1,
                    title="Harry Potter",
                    author="J.K. Rowling",
                    genre="Fantasy",
                    total_copies=5,
                    available_copies=5,
                ),
                Book(
                    id=2,
                    title="The Notebook",
                    author="Nicholas Sparks",
                    genre="Romance",
                    total_copies=4,
                    available_copies=4,
                ),
                Book(
                    id=3,
                    title="Hamlet",
                    author="William Shakespeare",
                    genre="Drama",
                    total_copies=7,
                    available_copies=7,
                ),
            ]
        )
        db.commit()
    make_user(application, MEMBER["username"], MEMBER["password"])
    make_user(application, ADMIN["username"], ADMIN["password"], role="admin")
    yield application
    application.state.engine.dispose()


@pytest.fixture(scope="session")
def e2e_base_url(e2e_app, playwright_browser):
    port = _free_port()
    config = uvicorn.Config(
        e2e_app, host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=0.3).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        pytest.fail("E2E uvicorn server did not start")

    yield url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def browser_page(playwright_browser, e2e_base_url):
    context = playwright_browser.new_context(base_url=e2e_base_url)
    page = context.new_page()
    yield page
    context.close()
