"""Caller authentication for the API.

The API sits behind the web tier, which holds a shared key and attaches it
server-side. The browser never sees the key: a React bundle cannot keep a
secret, so anything the SPA carried would be readable in DevTools.

This authenticates the *web tier*, not a person. There is no user identity
here and therefore no per-caller dealer group authorization - the UI chooses a
dealer group and the API validates that it exists. In this workshop each user
deploys their own stack, so there is no second user to isolate from. Anyone
who can reach the web tier can drive the API through it; the key only stops
the API's own hostname being called directly.
"""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

API_KEY_HEADER = "x-api-key"
API_KEY_ENV = "API_SHARED_KEY"

# Set by App Service on every worker. Its presence is the difference between
# "a laptop" and "reachable from the internet".
APP_SERVICE_MARKER = "WEBSITE_SITE_NAME"


def configured_key() -> str:
    return os.environ.get(API_KEY_ENV, "").strip()


def running_on_app_service() -> bool:
    return bool(os.environ.get(APP_SERVICE_MARKER, "").strip())


def api_auth_mode() -> str:
    """What `/api/health/details` reports about inbound protection."""

    if configured_key():
        return "shared_key"
    return "misconfigured" if running_on_app_service() else "unprotected"


def require_api_key(request: Request) -> None:
    """Reject anything that did not come through the web tier.

    Fails closed: a deployed app with no key configured refuses every request
    rather than serving them all. An unauthenticated API on a public hostname
    is the failure this exists to prevent, so it must not be what happens when
    someone forgets a setting.
    """

    expected = configured_key()
    if not expected:
        if running_on_app_service():
            raise HTTPException(
                status_code=503,
                detail="API_SHARED_KEY is not configured; refusing to serve unauthenticated.",
            )
        # Local development: uvicorn behind the Vite dev proxy, no key needed.
        return

    presented = request.headers.get(API_KEY_HEADER, "")
    # compare_digest so a wrong key cannot be narrowed down by response timing.
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API key.",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )
