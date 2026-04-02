"""
lucid_to_miro.api — Miro REST API client and board uploader.

Public surface:
    MiroClient      Zero-dependency HTTP client (urllib-based).
    MiroAuthError   Raised when token is missing or rejected.
    MiroAPIError    Raised on non-retryable API errors.
    upload_document Upload a parsed Document to a Miro board.
"""
from lucid_to_miro.api.miro_client import MiroClient, MiroAuthError, MiroAPIError, MiroRateLimitError
from lucid_to_miro.api.uploader import upload_document

__all__ = [
    "MiroClient",
    "MiroAuthError",
    "MiroAPIError",
    "MiroRateLimitError",
    "upload_document",
]
