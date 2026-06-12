"""Shared async HTTP client factory.

All outbound provider calls go through `http_client()` so tests can swap in
an `httpx.MockTransport` by monkeypatching `transport_factory`.
"""
from collections.abc import Callable

import httpx

transport_factory: Callable[[], httpx.AsyncBaseTransport | None] = lambda: None


def http_client(timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=transport_factory())
