import time

import jwt

from tests.conftest import JWT_SECRET, make_token


def test_health_is_public(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_protected_route_requires_token(client):
    res = client.post("/api/realtime/session", json={})
    assert res.status_code == 401


def test_invalid_token_rejected(client):
    res = client.post(
        "/api/realtime/session",
        json={},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert res.status_code == 401


def test_expired_token_rejected(client):
    expired = jwt.encode(
        {"sub": "u1", "aud": "authenticated", "exp": int(time.time()) - 10},
        JWT_SECRET,
        algorithm="HS256",
    )
    res = client.post("/api/realtime/session", json={}, headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401


def test_wrong_audience_rejected(client):
    token = jwt.encode(
        {"sub": "u1", "aud": "anon", "exp": int(time.time()) + 3600},
        JWT_SECRET,
        algorithm="HS256",
    )
    res = client.post("/api/realtime/session", json={}, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


def test_valid_token_passes_auth(client, mock_transport):
    import httpx

    mock_transport(lambda request: httpx.Response(200, json={"value": "ek_test_123"}))
    res = client.post(
        "/api/realtime/session",
        json={"level": "beginner"},
        headers={"Authorization": f"Bearer {make_token()}"},
    )
    assert res.status_code == 200
