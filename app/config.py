from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
EXERCISES_DIR = BASE_DIR / "data" / "exercises"

load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()

# Admin bootstrap: created on startup if no admin user exists yet.
ADMIN_PHONE = os.environ.get("ADMIN_PHONE", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
ADMIN_NAME = os.environ.get("ADMIN_NAME", "Amministratore").strip()

# Session / device cookies.
SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "session")
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

HOST = os.environ.get("ITALIAN_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("ITALIAN_TEST_PORT", "8050"))
DB_PATH = Path(os.environ.get("ITALIAN_TEST_DB", "data/italian_test.db"))

# Number of exercises available per part from the seed data.
PARTS = [1, 2, 3, 4]
