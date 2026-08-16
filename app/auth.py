from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional

from fastapi import Request

from .config import SESSION_COOKIE_NAME, SESSION_COOKIE_SECURE
from .database import (
    active_session_for_user,
    delete_session_by_token,
    get_session_by_token,
    get_user_by_id,
    touch_session,
)

PBKDF2_ITERATIONS = 260_000
DEVICE_COOKIE = "device_id"
DEVICE_MAX_AGE = 10 * 365 * 24 * 3600  # ~10 years

# --- Passwords --------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"pbkdf2${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, expected = stored.split("$", 2)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(digest.hex(), expected)


# --- Session tokens ---------------------------------------------------------

def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cookie_kwargs() -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": SESSION_COOKIE_SECURE,
        "path": "/",
    }


# --- Current user -----------------------------------------------------------

def get_current_user(request: Request) -> Optional[dict]:
    """Resolve the authenticated user from the session cookie + device cookie.

    A session is only valid on the exact device (device_id cookie) that created
    it: using the session from another device is treated as logged out.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    device = request.cookies.get(DEVICE_COOKIE)
    if not token or not device:
        return None
    session = get_session_by_token(hash_token(token))
    if not session or session["device_id"] != device:
        return None
    user = get_user_by_id(session["user_id"])
    if not user or not user["active"]:
        return None
    touch_session(session["id"])
    return user


# --- One-device-at-a-time login ---------------------------------------------

def login_conflict(user_id: int, device_id: str) -> bool:
    """True if the user is already signed in on a different device."""
    active = active_session_for_user(user_id)
    return active is not None and active["device_id"] != device_id


# --- Login throttling (in-memory) -------------------------------------------

class LoginThrottle:
    """Simple per-key attempt limiter (5 failed attempts -> 10 min lock)."""

    MAX_ATTEMPTS = 5
    WINDOW = 600

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}

    def blocked(self, key: str) -> bool:
        now = time.time()
        recent = [t for t in self._fails.get(key, []) if now - t < self.WINDOW]
        self._fails[key] = recent
        return len(recent) >= self.MAX_ATTEMPTS

    def record_fail(self, key: str) -> None:
        self._fails.setdefault(key, []).append(time.time())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


throttle = LoginThrottle()
