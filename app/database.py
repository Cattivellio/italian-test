from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

import psycopg2
import psycopg2.extras

from .config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    phone         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    name          TEXT    NOT NULL DEFAULT '',
    role          TEXT    NOT NULL DEFAULT 'student',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token_hash  TEXT    NOT NULL UNIQUE,
    device_id   TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    last_seen   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS vocabulary (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL DEFAULT 0,
    term        TEXT    NOT NULL,
    definition  TEXT    NOT NULL,
    exercise_id TEXT    NOT NULL DEFAULT '',
    part        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL DEFAULT 0,
    exercise_id  TEXT    NOT NULL,
    part         INTEGER NOT NULL,
    correct      INTEGER NOT NULL DEFAULT 0,
    total        INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_exercises (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL DEFAULT 0,
    exercise_id TEXT    NOT NULL UNIQUE,
    part        INTEGER NOT NULL,
    payload     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sim_exercises (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL DEFAULT 0,
    exercise_id TEXT    NOT NULL UNIQUE,
    part        INTEGER NOT NULL,
    payload     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""

# Columns to add to databases that predate multi-user support.
_LEGACY_USER_COLUMNS = {
    "vocabulary": ("user_id", "INTEGER NOT NULL DEFAULT 0"),
    "attempts": ("user_id", "INTEGER NOT NULL DEFAULT 0"),
    "ai_exercises": ("user_id", "INTEGER NOT NULL DEFAULT 0"),
    "sim_exercises": ("user_id", "INTEGER NOT NULL DEFAULT 0"),
}


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def _cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _migrate(conn) -> None:
    """Add user_id columns to tables created by older versions of the app."""
    for table, (col, decl) in _LEGACY_USER_COLUMNS.items():
        try:
            with _cursor(conn) as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = %s AND column_name = %s",
                    (table, col),
                )
                exists = cur.fetchone()
        except psycopg2.Error:
            continue
        if not exists:
            with conn.cursor() as cur:
                cur.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {decl}')


@contextmanager
def get_conn() -> Iterator[psycopg2.extensions.connection]:
    conn = get_connection()
    conn.autocommit = False
    try:
        # Idempotent: guarantees tables exist even if the schema changed
        # while the app was already running.
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn():
        pass


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --- Users ------------------------------------------------------------------

def create_user(phone: str, password_hash: str, name: str, role: str = "student", active: int = 1) -> int:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "INSERT INTO users(phone, password_hash, name, role, active, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (phone, password_hash, name, role, active, now_iso()),
            )
            return int(cur.fetchone()["id"])


def get_user_by_phone(phone: str) -> Optional[dict]:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT id, phone, password_hash, name, role, active, created_at "
                "FROM users WHERE phone = %s",
                (phone,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT id, phone, password_hash, name, role, active, created_at "
                "FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def list_users() -> list[dict]:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT id, phone, name, role, active, created_at FROM users ORDER BY id"
            )
            return [dict(r) for r in cur.fetchall()]


def admin_exists() -> bool:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1")
            return cur.fetchone() is not None


def set_user_password(user_id: int, password_hash: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id)
            )
            return cur.rowcount > 0


def set_user_active(user_id: int, active: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET active = %s WHERE id = %s", (1 if active else 0, user_id)
            )


def delete_user(user_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            for table in ("sessions", "vocabulary", "attempts", "ai_exercises", "sim_exercises"):
                cur.execute(f"DELETE FROM {table} WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))


# --- Sessions ---------------------------------------------------------------

def create_session(user_id: int, token_hash: str, device_id: str, keep_others: bool = False) -> int:
    with get_conn() as conn:
        # One active session per regular user: drop any previous one. Admins
        # may hold multiple concurrent sessions (keep_others=True).
        if not keep_others:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        ts = now_iso()
        with _cursor(conn) as cur:
            cur.execute(
                "INSERT INTO sessions(user_id, token_hash, device_id, created_at, last_seen) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (user_id, token_hash, device_id, ts, ts),
            )
            return int(cur.fetchone()["id"])


def get_session_by_token(token_hash: str) -> Optional[dict]:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT id, user_id, device_id, created_at, last_seen FROM sessions "
                "WHERE token_hash = %s",
                (token_hash,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def active_session_for_user(user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT id, user_id, device_id, created_at, last_seen FROM sessions "
                "WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def touch_session(session_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE sessions SET last_seen = %s WHERE id = %s", (now_iso(), session_id))


def delete_session_by_token(token_hash: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash,))
            return cur.rowcount > 0


def revoke_sessions_for_user(user_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


# --- Vocabulary -----------------------------------------------------------

def save_keyword(user_id: int, term: str, definition: str, exercise_id: str = "", part: int = 0) -> int:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT id FROM vocabulary WHERE user_id = %s AND term = %s AND definition = %s",
                (user_id, term, definition),
            )
            row = cur.fetchone()
            if row:
                return int(row["id"])
            cur.execute(
                "INSERT INTO vocabulary(user_id, term, definition, exercise_id, part, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (user_id, term, definition, exercise_id, part, now_iso()),
            )
            return int(cur.fetchone()["id"])


def list_keywords(user_id: int) -> list[dict]:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT id, term, definition, part, created_at FROM vocabulary "
                "WHERE user_id = %s ORDER BY lower(term)",
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def delete_keyword(user_id: int, keyword_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM vocabulary WHERE id = %s AND user_id = %s", (keyword_id, user_id)
            )
            return cur.rowcount > 0


# --- Attempts / progress ---------------------------------------------------

def record_attempt(user_id: int, exercise_id: str, part: int, correct: int, total: int) -> int:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "INSERT INTO attempts(user_id, exercise_id, part, correct, total, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (user_id, exercise_id, part, correct, total, now_iso()),
            )
            return int(cur.fetchone()["id"])


def passed_exercise_ids(user_id: int) -> set[str]:
    """Ids of exercises that have been passed with a perfect score at least once."""
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT DISTINCT exercise_id FROM attempts "
                "WHERE user_id = %s AND correct = total",
                (user_id,),
            )
            return {str(r["exercise_id"]) for r in cur.fetchall()}


def reset_progress(user_id: int) -> None:
    """Clear a user's attempts, AI progression and transient simulation
    exercises (keeps vocabulary)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            for table in ("attempts", "ai_exercises", "sim_exercises"):
                cur.execute(f"DELETE FROM {table} WHERE user_id = %s", (user_id,))


def part_stats(user_id: int) -> list[dict]:
    """Per-part accuracy, excluding simulation attempts (part 0)."""
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT part, COUNT(*) AS attempts, "
                "COALESCE(SUM(correct), 0) AS correct, COALESCE(SUM(total), 0) AS total "
                "FROM attempts WHERE user_id = %s AND part > 0 GROUP BY part ORDER BY part",
                (user_id,),
            )
            rows = cur.fetchall()
    out = []
    for r in rows:
        total_q = int(r["total"])
        percent = round((int(r["correct"]) / total_q) * 100) if total_q else 0
        out.append(
            {
                "part": int(r["part"]),
                "attempts": int(r["attempts"]),
                "correct": int(r["correct"]),
                "total": total_q,
                "percent": percent,
            }
        )
    return out


# --- AI-generated progression exercises ------------------------------------

def save_ai_exercise(user_id: int, part: int, exercise_id: str, payload: str) -> None:
    """Persist an AI-generated exercise (payload is the Exercise JSON)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_exercises(user_id, exercise_id, part, payload, created_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (exercise_id) DO UPDATE SET "
                "user_id = EXCLUDED.user_id, part = EXCLUDED.part, "
                "payload = EXCLUDED.payload, created_at = EXCLUDED.created_at",
                (user_id, exercise_id, part, payload, now_iso()),
            )


def latest_ai_exercise(user_id: int, part: int) -> Optional[dict]:
    """The most recently created AI exercise for a user/part (highest id)."""
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT exercise_id, part, payload FROM ai_exercises "
                "WHERE user_id = %s AND part = %s ORDER BY id DESC LIMIT 1",
                (user_id, part),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_ai_exercise(user_id: int, exercise_id: str) -> Optional[dict]:
    """Look up a stored AI exercise by its id, returning the raw payload dict."""
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT exercise_id, part, payload FROM ai_exercises "
                "WHERE user_id = %s AND exercise_id = %s",
                (user_id, exercise_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


# --- Transient AI exercises for simulations ---------------------------------

def save_sim_exercise(user_id: int, part: int, exercise_id: str, payload: str) -> None:
    """Persist an AI exercise used by a simulation run (transient exam content)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sim_exercises(user_id, exercise_id, part, payload, created_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (exercise_id) DO UPDATE SET "
                "user_id = EXCLUDED.user_id, part = EXCLUDED.part, "
                "payload = EXCLUDED.payload, created_at = EXCLUDED.created_at",
                (user_id, exercise_id, part, payload, now_iso()),
            )


def get_sim_exercise(user_id: int, exercise_id: str) -> Optional[dict]:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT exercise_id, part, payload FROM sim_exercises "
                "WHERE user_id = %s AND exercise_id = %s",
                (user_id, exercise_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def clear_sim_exercises(user_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sim_exercises WHERE user_id = %s", (user_id,))


def list_attempts(user_id: int, limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT id, exercise_id, part, correct, total, created_at "
                "FROM attempts WHERE user_id = %s ORDER BY id DESC LIMIT %s",
                (user_id, max(1, int(limit))),
            )
            return [dict(r) for r in cur.fetchall()]


def stats(user_id: int) -> dict:
    with get_conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(correct), 0) AS correct, "
                "COALESCE(SUM(total), 0) AS total_q FROM attempts WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            total = int(row["total"])
            correct = int(row["correct"])
            total_q = int(row["total_q"])
    pct = round((correct / total_q) * 100) if total_q else 0
    return {"attempts": total, "correct": correct, "total": total_q, "percent": pct}


def is_healthy() -> bool:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False
