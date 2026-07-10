"""Telegram alerting for unhandled backend errors.

Fire-and-forget and config-gated: a no-op unless a bot token + chat id are set.
Guardrails against phone-spam / Telegram rate limits: dedup by signature within
a window (repeats folded into a "+N more" note) plus a global hourly cap.
In-memory only (single-instance; multi-replica would need shared state).
"""
import logging
import time

import httpx

from app.core.config import get_settings

_logger = logging.getLogger("flueai.telegram")

_DEDUP_WINDOW_S = 600
_GLOBAL_MAX_PER_HOUR = 20

_seen: dict[str, dict] = {}
_hour_start = 0.0
_hour_count = 0


async def notify_telegram(text: str, *, signature: str | None = None) -> None:
    """Send an alert to Telegram. No-op unless a bot token + chat id are set."""
    global _hour_start, _hour_count

    settings = get_settings()
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        return  # dormant until configured

    now = time.time()

    # Global hourly cap.
    if now - _hour_start > 3600:
        _hour_start = now
        _hour_count = 0
    if _hour_count >= _GLOBAL_MAX_PER_HOUR:
        return

    # Dedup by signature.
    sig = signature or text[:120]
    state = _seen.get(sig)
    if state and now - state["last"] < _DEDUP_WINDOW_S:
        state["suppressed"] += 1
        return
    repeated = state["suppressed"] if state else 0
    _seen[sig] = {"last": now, "suppressed": 0}
    _hour_count += 1

    suffix = f"\n\n(+{repeated} more in the last 10m)" if repeated else ""
    body = (text + suffix)[:4000]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": body, "disable_web_page_preview": True},
            )
    except Exception as exc:  # never let alerting break the request
        _logger.warning("telegram alert failed: %r", exc)
