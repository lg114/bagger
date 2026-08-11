"""Exception hierarchy for consolidation.

The distinction that matters operationally is **retryable vs terminal**. A run
over 64 sessions will hit rate limits and transient 5xx; those must not abort
the run. A malformed API key or an unparseable response will fail identically
on every retry and should surface immediately instead of burning three attempts
and 90 seconds of backoff per chunk.

``retryable`` is therefore a property of the exception, decided at the point
where we actually know the HTTP status or socket error — not guessed later by
string-matching a message.
"""

from __future__ import annotations

__all__ = [
    "ConsolidationError",
    "LLMResponseError",
    "LLMTransportError",
    "LLMUnauthorizedError",
]


class ConsolidationError(Exception):
    """Base class for every error raised by the consolidation package."""

    retryable: bool = False


class LLMTransportError(ConsolidationError):
    """The request never produced a usable HTTP response.

    Covers timeouts, DNS/connection failures, 429 rate limits and 5xx. All of
    these are worth retrying with backoff.
    """

    retryable = True

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class LLMUnauthorizedError(ConsolidationError):
    """Missing/invalid credentials, or a 4xx the server will keep rejecting.

    Terminal by construction: retrying an expired key wastes wall-clock time
    and, worse, hides the real fix from the user.
    """

    retryable = False

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class LLMResponseError(ConsolidationError):
    """A 200 response whose body could not be interpreted as records.

    Non-JSON content, a JSON scalar where an object was required, or a payload
    missing ``choices``. Terminal for the chunk: the model answered, it just
    answered wrongly, and an identical retry usually reproduces it. The chunk is
    recorded as failed and the run continues.
    """

    retryable = False
