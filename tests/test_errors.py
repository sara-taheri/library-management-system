"""HTTP hardening: generic 500 handler and security headers.

The boom routes are registered on the test app only; they are not part
of the real application.
"""
import logging

from fastapi.testclient import TestClient

from app.main import GENERIC_SERVER_ERROR


def _boom_client(app) -> TestClient:
    @app.get("/__test/boom")
    def html_boom():
        raise RuntimeError("secret internals")

    @app.get("/api/__test/boom")
    def api_boom():
        raise RuntimeError("secret internals")

    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_exception_renders_html_500(app):
    with _boom_client(app) as client:
        response = client.get("/__test/boom")
    assert response.status_code == 500
    assert "text/html" in response.headers["content-type"]
    assert "Something went wrong" in response.text
    assert "500" in response.text
    assert GENERIC_SERVER_ERROR in response.text
    assert "secret internals" not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


def test_unhandled_exception_api_returns_json_500(app):
    with _boom_client(app) as client:
        response = client.get("/api/__test/boom")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": GENERIC_SERVER_ERROR}
    assert "secret internals" not in response.text
    assert "RuntimeError" not in response.text


def test_unhandled_exception_json_accept_on_html_path(app):
    with _boom_client(app) as client:
        response = client.get(
            "/__test/boom", headers={"Accept": "application/json"}
        )
    assert response.status_code == 500
    assert response.json() == {"detail": GENERIC_SERVER_ERROR}


def test_unhandled_exception_is_logged_server_side(app, caplog):
    with caplog.at_level(logging.ERROR, logger="app"):
        with _boom_client(app) as client:
            client.get("/__test/boom")
    assert "Unhandled exception" in caplog.text
    assert "secret internals" in caplog.text


def test_existing_html_404_still_renders(client):
    response = client.get("/definitely-not-a-page")
    assert response.status_code == 404
    assert "Page not found" in response.text


def test_security_headers_on_html_and_api(client):
    for path in ("/", "/health", "/api/books"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert (
            response.headers["Referrer-Policy"]
            == "strict-origin-when-cross-origin"
        )


def test_security_headers_on_error_response(client):
    response = client.get("/definitely-not-a-page")
    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
