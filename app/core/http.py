"""Shared async HTTP client factory.

All outbound provider calls go through `http_client()` so tests can swap in
an `httpx.MockTransport` by monkeypatching `transport_factory`.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

_clients: dict[float, httpx.AsyncClient] = {}


def transport_factory() -> httpx.AsyncBaseTransport | None:
    """Overridden in tests (monkeypatched to return an httpx.MockTransport)."""
    return None


@asynccontextmanager
async def http_client(timeout: float = 30.0) -> AsyncIterator[httpx.AsyncClient]:
    transport = transport_factory()
    if transport is not None:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            yield client
        return

    client = _clients.get(timeout)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        _clients[timeout] = client

    yield client


async def close_http_clients() -> None:
    for client in list(_clients.values()):
        if not client.is_closed:
            await client.aclose()
    _clients.clear()
