"""SQLite storage for the goal/roadmap planner."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS goal (
    id INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    target_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY,
    month_label TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def create_goal(conn: sqlite3.Connection, description: str, target_date: str) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO goal (description, target_date, created_at) VALUES (?, ?, ?)",
            (description, target_date, datetime.now(timezone.utc).isoformat()),
        )
    return cursor.lastrowid


def get_goal(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM goal ORDER BY id DESC LIMIT 1").fetchone()


def clear_milestones(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("DELETE FROM milestones")


def insert_milestone(conn: sqlite3.Connection, month_label: str, title: str, sort_order: int) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO milestones (month_label, title, sort_order, created_at) VALUES (?, ?, ?, ?)",
            (month_label, title, sort_order, datetime.now(timezone.utc).isoformat()),
        )
    return cursor.lastrowid


def list_milestones(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM milestones ORDER BY sort_order").fetchall()


def get_milestone(conn: sqlite3.Connection, milestone_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM milestones WHERE id = ?", (milestone_id,)).fetchone()


def update_milestone_status(conn: sqlite3.Connection, milestone_id: int, status: str) -> None:
    with conn:
        conn.execute(
            "UPDATE milestones SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now(timezone.utc).isoformat(), milestone_id),
        )
