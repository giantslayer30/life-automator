"""
db_init.py — Initialize the SQLite database schema for the job application platform.

Tables:
  - jobs              : Scraped job listings with dedup fingerprint
  - resumes           : Versioned resume uploads
  - applications      : Application records with status tags
  - application_notes : Feedback / rejection notes per application
  - scrape_errors     : Error log for failed scrape attempts
"""

import sqlite3
import os
from pathlib import Path
from typing import Union

DB_PATH = Path(__file__).parent.parent / ".tmp" / "jobs.db"


def get_connection(db_path: Union[str, Path] = DB_PATH) -> sqlite3.Connection:
    """Return a connection with foreign keys enforced and row_factory set."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Union[str, Path] = DB_PATH) -> None:
    """Create all tables if they don't exist."""
    conn = get_connection(db_path)
    c = conn.cursor()

    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint     TEXT    NOT NULL UNIQUE,   -- MD5 hash for dedup
            title           TEXT    NOT NULL,
            company         TEXT    NOT NULL,
            location        TEXT,
            remote          INTEGER DEFAULT 0,          -- 1 = remote
            employment_type TEXT,                       -- full-time, contract, etc.
            salary_min      INTEGER,
            salary_max      INTEGER,
            salary_currency TEXT    DEFAULT 'USD',
            description     TEXT,
            url             TEXT    NOT NULL,
            source          TEXT    NOT NULL,           -- linkedin, naukri, dribbble …
            ai_skills_needed INTEGER DEFAULT 0,         -- 1 = tagged
            ai_skills_tags  TEXT,                       -- JSON list of triggering terms
            visa_sponsorship INTEGER DEFAULT 0,         -- 1 = mentions visa/relocation
            visa_tags       TEXT,                       -- JSON list of triggering terms
            scraped_at      TEXT    NOT NULL,           -- ISO8601
            last_seen_at    TEXT    NOT NULL,           -- updated on re-scrape
            closed_at       TEXT,                       -- set when job confirmed closed
            is_archived     INTEGER DEFAULT 0
        )
    """)

    # Migrate existing databases — add columns if missing
    for col, defn in [
        ("visa_sponsorship", "INTEGER DEFAULT 0"),
        ("visa_tags",        "TEXT"),
    ]:
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {defn}")
        except Exception:
            pass  # column already exists

    # ------------------------------------------------------------------
    # resumes
    # ------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS resumes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            version         INTEGER NOT NULL,
            label           TEXT,                       -- e.g. "Senior UX — compact"
            drive_file_id   TEXT,                       -- Google Drive file ID
            local_path      TEXT,                       -- .tmp/ path (transient)
            html_content    TEXT,                       -- source HTML for PDF gen
            created_at      TEXT    NOT NULL,
            is_active       INTEGER DEFAULT 1           -- 1 = current default
        )
    """)

    # ------------------------------------------------------------------
    # applications
    # ------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id          INTEGER NOT NULL REFERENCES jobs(id),
            resume_id       INTEGER REFERENCES resumes(id),
            status          TEXT    NOT NULL DEFAULT 'Applied',
                            -- preset: Applied | Interviewing – R1 | Interviewing – R2
                            --         HR Round | Assignment | Offer | Rejected | Ghosted
                            -- or any user-defined string
            superfolio_url  TEXT,                       -- optional custom Superfolio link
            applied_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL,
            days_to_outcome INTEGER,                    -- auto-calc on status change
            UNIQUE(job_id)                              -- prevent duplicate applications
        )
    """)

    # ------------------------------------------------------------------
    # application_notes  (feedback per application)
    # ------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS application_notes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id  INTEGER NOT NULL REFERENCES applications(id),
            feedback_text   TEXT,
            feedback_channel TEXT,                      -- email | call | none
            created_at      TEXT    NOT NULL
        )
    """)

    # ------------------------------------------------------------------
    # negative_keywords  (user-managed blocked title terms)
    # ------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS negative_keywords (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword    TEXT NOT NULL UNIQUE COLLATE NOCASE,
            created_at TEXT NOT NULL
        )
    """)

    # ------------------------------------------------------------------
    # scrape_errors
    # ------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS scrape_errors (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source          TEXT    NOT NULL,
            url             TEXT,
            status_code     INTEGER,
            error_message   TEXT,
            occurred_at     TEXT    NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print(f"[db_init] Database ready at: {db_path}")


if __name__ == "__main__":
    init_db()
