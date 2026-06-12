"""Shared async HTTP client factory.

All outbound provider calls go through `http_client()` so tests can swap in
an `httpx.MockTransport` by monkeypatching `transport_factory`.
"""
import httpx


def transport_factory() -> httpx.AsyncBaseTransport | None:
    """Overridden in tests (monkeypatched to return an httpx.MockTransport)."""
    return None


def http_client(timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=transport_factory())
