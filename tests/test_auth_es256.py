"""ES256 (post-rotation) verification path — JWKS key resolution mocked."""
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

import app.core.auth as auth_mod


@pytest.fixture()
def ec_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def make_es256_token(private_key, **overrides) -> str:
    payload = {
        "sub": "00000000-0000-0000-0000-000000000002",
        "email": "es256@test.dev",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        **overrides,
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-key"})


def test_es256_token_accepted_via_jwks(client, mock_transport, monkeypatch, ec_keypair):
    private_key, public_key = ec_keypair
    monkeypatch.setattr(auth_mod, "_resolve_asymmetric_key", lambda token: public_key)
    mock_transport(lambda request: httpx.Response(200, json={"value": "ek_test"}))

    token = make_es256_token(private_key)
    res = client.post(
        "/api/realtime/session",
        json={"pipelineMode": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200


def test_es256_with_wrong_key_rejected(client, monkeypatch, ec_keypair):
    private_key, _ = ec_keypair
    other_public = ec.generate_private_key(ec.SECP256R1()).public_key()
    monkeypatch.setattr(auth_mod, "_resolve_asymmetric_key", lambda token: other_public)

    token = make_es256_token(private_key)
    res = client.post(
        "/api/realtime/session",
        json={"pipelineMode": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401


def test_es256_expired_rejected(client, monkeypatch, ec_keypair):
    private_key, public_key = ec_keypair
    monkeypatch.setattr(auth_mod, "_resolve_asymmetric_key", lambda token: public_key)

    token = make_es256_token(private_key, exp=int(time.time()) - 10)
    res = client.post(
        "/api/realtime/session",
        json={"pipelineMode": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
