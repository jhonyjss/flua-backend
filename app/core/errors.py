"""Return safe, non-leaking error messages to clients.

Raw exception text can carry upstream provider responses, internal URLs, or
stack details. ``safe_error`` logs the full exception server-side under a short
reference id and returns only a generic message (plus that ref) for the client,
so support can still correlate a user report to a log line without exposing
internals over the wire.
"""
import logging
import uuid

_logger = logging.getLogger("flueai.errors")

_GENERIC_MESSAGE = "Ocorreu um erro inesperado. Tente novamente."


def safe_error(
    exc: BaseException,
    *,
    context: str = "error",
    user_message: str | None = None,
) -> str:
    """Log ``exc`` (with traceback) under a short ref id; return a safe message.

    Call from inside an ``except`` block so the active traceback is captured.
    The returned string is safe to send to the client — it never contains the
    raw exception text, only an opaque ``ref`` that maps to the server log.
    """
    ref = uuid.uuid4().hex[:8]
    _logger.exception("[%s] ref=%s: %r", context, ref, exc)
    return f"{user_message or _GENERIC_MESSAGE} (ref: {ref})"
