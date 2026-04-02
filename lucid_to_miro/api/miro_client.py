"""
Zero-dependency HTTP client for the Miro REST API v2.

Authentication
--------------
Supports Personal Access Tokens (PAT) and OAuth 2.0 bearer tokens.
Pass the token directly or set the MIRO_TOKEN environment variable.

Rate limits
-----------
Miro enforces ~100 requests / 10 s per token.  This client automatically
retries on HTTP 429 (Retry-After header respected) and on transient 5xx
errors with exponential back-off (up to _MAX_RETRIES attempts).

See docs/MIRO_AUTH.md for a full authentication guide.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

BASE_URL     = "https://api.miro.com"
_MAX_RETRIES = 3
_RETRY_ON    = {500, 502, 503, 504}


class MiroAuthError(Exception):
    """Token is missing, malformed, or rejected with HTTP 401/403."""


class MiroAPIError(Exception):
    """Non-retryable API error."""
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        super().__init__(f"Miro API HTTP {status}: {body[:400]}")


class MiroRateLimitError(MiroAPIError):
    """Rate limit hit and retries exhausted."""


class MiroClient:
    """
    Thin, zero-dependency HTTP client for the Miro REST API v2.

    Usage::

        client = MiroClient(token="your_pat_here")
        board  = client.post("/v2/boards", {"name": "My Board"})
        print(board["viewLink"])
    """

    def __init__(self, token: str) -> None:
        """
        Args:
            token: Miro Personal Access Token or OAuth bearer token.
                   Obtain one at https://miro.com/app/settings/user-profile/
                   under "Your apps" → "Create new app" → "Tokens".
                   See docs/MIRO_AUTH.md for step-by-step instructions.

        Raises:
            MiroAuthError: If token is blank.
        """
        if not token or not token.strip():
            raise MiroAuthError(
                "Miro access token is required.\n"
                "  Option 1: export MIRO_TOKEN=<your_token>   (recommended)\n"
                "  Option 2: pass --token <your_token> on the command line\n"
                "  See docs/MIRO_AUTH.md for how to create a token."
            )
        self._token = token.strip()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute an authenticated HTTP request with automatic retry.

        Args:
            method: HTTP verb ("GET", "POST", "PUT", "DELETE", …).
            path:   API path, e.g. "/v2/boards".
            body:   Optional request body (will be JSON-encoded).

        Returns:
            Parsed JSON response dict (empty dict for 204 No Content).

        Raises:
            MiroAuthError:      HTTP 401 — bad / expired token.
            MiroRateLimitError: HTTP 429 — rate limit exhausted after retries.
            MiroAPIError:       Other non-retryable HTTP errors.
        """
        url  = f"{BASE_URL}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None

        for attempt in range(_MAX_RETRIES):
            req = urllib.request.Request(
                url, data=data, headers=self._headers(), method=method
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw.strip() else {}

            except urllib.error.HTTPError as exc:
                status = exc.code
                rbody  = exc.read().decode("utf-8", errors="replace")

                if status == 401:
                    raise MiroAuthError(
                        "Authentication failed (HTTP 401).\n"
                        "  • Verify the token is copied correctly (no trailing spaces).\n"
                        "  • Confirm the token has not expired or been revoked.\n"
                        "  • Check the token scopes include boards:write.\n"
                        f"  API response: {rbody[:300]}\n"
                        "  See docs/MIRO_AUTH.md § Troubleshooting."
                    )

                if status == 403:
                    raise MiroAuthError(
                        "Permission denied (HTTP 403).\n"
                        "  • The token scope may not include boards:write.\n"
                        "  • If using --team-id, verify you are a member of that team.\n"
                        f"  API response: {rbody[:300]}"
                    )

                if status == 429:
                    retry_after = int(exc.headers.get("Retry-After", "5"))
                    if attempt < _MAX_RETRIES - 1:
                        time.sleep(retry_after)
                        continue
                    raise MiroRateLimitError(status, rbody)

                if status in _RETRY_ON and attempt < _MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue

                raise MiroAPIError(status, rbody)

        raise MiroAPIError(0, "Max retries exceeded")

    def get(self, path: str) -> Dict[str, Any]:
        """HTTP GET."""
        return self.request("GET", path)

    def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """HTTP POST with JSON body."""
        return self.request("POST", path, body)

    def put(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """HTTP PUT with JSON body."""
        return self.request("PUT", path, body)

    def delete(self, path: str) -> Dict[str, Any]:
        """HTTP DELETE."""
        return self.request("DELETE", path)
