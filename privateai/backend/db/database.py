"""
Database module — SQLite only. All data local.
Single connection per request (thread-safe).
"""

import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.expanduser("~/.privateai/privateai.db")


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = get_db()
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                start_time  TEXT NOT NULL,
                end_time    TEXT,
                description TEXT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                note        TEXT,
                remind_at   TEXT NOT NULL,
                fired       INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS interaction_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT,
                user_input  TEXT,
                response    TEXT,
                tool_used   TEXT,
                latency_ms  INTEGER,
                ts          TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_calendar_start ON calendar_events(start_time);
            CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(remind_at);
            CREATE INDEX IF NOT EXISTS idx_log_session ON interaction_log(session_id);
        """)
        db.commit()
        logger.info(f"DB initialized at {DB_PATH}")
    finally:
        db.close()


def drop_all():
    """Wipe all tables. Called by /data/all endpoint."""
    db = get_db()
    try:
        db.executescript("""
            DROP TABLE IF EXISTS calendar_events;
            DROP TABLE IF EXISTS reminders;
            DROP TABLE IF EXISTS interaction_log;
        """)
        db.commit()
        logger.warning("All tables dropped (user requested data deletion)")
    finally:
        db.close()


def log_interaction(session_id: str, user_input: str, response: str, tool_used: str, latency_ms: int):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO interaction_log (session_id, user_input, response, tool_used, latency_ms) VALUES (?,?,?,?,?)",
            (session_id, user_input, response, tool_used, latency_ms),
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to log interaction: {e}")
    finally:
        db.close()
