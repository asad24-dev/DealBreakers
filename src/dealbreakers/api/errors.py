"""Deal Room API exceptions."""


class DealRoomError(Exception):
    """Base exception for Deal Room API errors."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(DealRoomError):
    """401/403 — invalid or missing team key."""


class OfferValidationError(DealRoomError):
    """400 — malformed offer; round is not consumed."""

    def __init__(self, message: str, *, body: str = "") -> None:
        super().__init__(message, status_code=400)
        self.body = body


class NotFoundError(DealRoomError):
    """404 — match or resource not found."""


class RateLimitError(DealRoomError):
    """429 — per-team rate limit exceeded."""


class ServerError(DealRoomError):
    """5xx — server-side failure."""
