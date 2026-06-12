import time

import jwt
import pytest
from fastapi.testclient import TestClient

import app.core.http as http_mod
from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limits

JWT_SECRET = "test-jwt-secret"


@pytest.fixture(autouse=True)
def settings_env(monkeypatch):
    """Deterministic settings for every test."""
    env = {
        "APP_ENV": "test",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_JWT_SECRET": JWT_SECRET,
        "SUPABASE_SERVICE_KEY": "service-key",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "OPENAI_API_KEY": "sk-openai-test",
        "GOOGLE_TTS_API_KEY": "g-test",
        "ELEVENLABS_API_KEY": "el-test",
        "DEEPGRAM_API_KEY": "dg-test",
        "STRIPE_SECRET_KEY": "sk_test_123",
        "STRIPE_WEBHOOK_SECRET": "whsec_test",
        "STRIPE_PRICE_STARTER_MONTHLY": "price_starter_m",
        "STRIPE_PRICE_STARTER_YEARLY": "price_starter_y",
        "STRIPE_PRICE_PRO_MONTHLY": "price_pro_m",
        "STRIPE_PRICE_PRO_YEARLY": "price_pro_y",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    reset_rate_limits()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def make_token(user_id: str = "00000000-0000-0000-0000-000000000001", email: str = "jhony@test.dev") -> str:
    return jwt.encode(
        {"sub": user_id, "email": email, "aud": "authenticated", "exp": int(time.time()) + 3600},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture()
def auth_headers() -> dict:
    return {"Authorization": f"Bearer {make_token()}"}


@pytest.fixture()
def mock_transport(monkeypatch):
    """Install an httpx.MockTransport for all outbound provider calls.

    Usage: mock_transport(handler) where handler(request) -> httpx.Response.
    """
    import httpx

    def installer(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(http_mod, "transport_factory", lambda: transport)
        return transport

    return installer
