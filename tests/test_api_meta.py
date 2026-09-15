"""Tests for the meta endpoints (health) and the HTML home page.

Phase 3 note: GET / moved from a JSON endpoint index to the server-rendered
home page; the interactive docs at /docs remain the API index.
"""


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_home_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Library" in response.text
