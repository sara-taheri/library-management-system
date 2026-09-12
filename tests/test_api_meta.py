"""Tests for the meta endpoints (health / root)."""


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_root_advertises_endpoints(client):
    response = client.get("/")
    assert response.status_code == 200
    endpoints = response.json()["endpoints"]
    assert endpoints["books"] == "/api/books"
    assert endpoints["health"] == "/health"
