"""SQLite database schema and connection management."""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    name TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    subject TEXT NOT NULL,
    input_mode TEXT NOT NULL DEFAULT 'csv',
    model_override TEXT,
    sample_size_maths INTEGER,
    sample_size_english INTEGER,
    random_seed INTEGER DEFAULT 42,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    total_strategies INTEGER DEFAULT 0,
    completed_strategies INTEGER DEFAULT 0,
    total_rows INTEGER DEFAULT 0,
    completed_rows INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS run_strategies (
    run_id TEXT NOT NULL REFERENCES runs(id),
    strategy_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    completed_at TEXT,
    rows_total INTEGER DEFAULT 0,
    rows_completed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    PRIMARY KEY (run_id, strategy_name)
);

CREATE TABLE IF NOT EXISTS run_questions (
    run_id TEXT NOT NULL REFERENCES runs(id),
    question_number TEXT NOT NULL,
    PRIMARY KEY (run_id, question_number)
);

CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    strategy_name TEXT NOT NULL,
    row_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    question_number TEXT NOT NULL,
    total_marks INTEGER NOT NULL,
    human_mark REAL NOT NULL,
    ai_mark REAL NOT NULL,
    error INTEGER NOT NULL DEFAULT 0,
    justification TEXT,
    criteria_breakdown TEXT,
    second_pass_changed INTEGER,
    debate_rounds INTEGER,
    debate_outcome TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    thinking_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id);
CREATE INDEX IF NOT EXISTS idx_eval_results_strategy ON eval_results(run_id, strategy_name);

CREATE TABLE IF NOT EXISTS prompt_overrides (
    strategy_name TEXT NOT NULL,
    field_path TEXT NOT NULL,
    original_text TEXT NOT NULL,
    override_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (strategy_name, field_path)
);

CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    subject TEXT,
    mime_type TEXT,
    file_size INTEGER,
    storage_path TEXT NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subjects (
    slug TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    csv_path TEXT NOT NULL,
    total_rows INTEGER DEFAULT 0,
    question_count INTEGER DEFAULT 0,
    is_builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_strategies (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT 'english',
    model TEXT NOT NULL,
    temperature REAL NOT NULL DEFAULT 0.0,
    thinking_budget INTEGER DEFAULT 4096,
    prompt_text TEXT NOT NULL,
    parse_mode TEXT NOT NULL DEFAULT 'simple',
    source_experiment_id TEXT,
    config_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autoresearch_sessions (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running',
    budget_usd REAL NOT NULL DEFAULT 20.0,
    spent_usd REAL NOT NULL DEFAULT 0.0,
    model TEXT NOT NULL DEFAULT 'gemini-2.5-pro',
    sample_size INTEGER NOT NULL DEFAULT 30,
    experiments_run INTEGER NOT NULL DEFAULT 0,
    best_exact_match REAL NOT NULL DEFAULT 0.0,
    best_experiment_id TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    report_md TEXT
);

CREATE TABLE IF NOT EXISTS autoresearch_experiments (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES autoresearch_sessions(id),
    description TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    exact_match REAL,
    within_1 REAL,
    mae REAL,
    bias REAL,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    n INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    kept INTEGER NOT NULL DEFAULT 0,
    per_question_json TEXT,
    prompt_text TEXT,
    config_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_autoresearch_exp_session
    ON autoresearch_experiments(session_id);

CREATE TABLE IF NOT EXISTS autoresearch_recommendations (
    id TEXT PRIMARY KEY,
    source_session_id TEXT NOT NULL REFERENCES autoresearch_sessions(id),
    recommendation_type TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    description TEXT NOT NULL,
    config_json TEXT NOT NULL,
    prompt_text TEXT,
    priority INTEGER NOT NULL DEFAULT 50,
    consumed_by_session_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_autoresearch_rec_source
    ON autoresearch_recommendations(source_session_id);
"""


def get_connection() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(config.DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """Initialize the database schema."""
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()

    # Migrate: add columns that may be missing on existing DBs
    _migrate_add_columns(conn)


def _migrate_add_columns(conn: sqlite3.Connection):
    """Add new columns to existing tables if they don't exist yet."""
    migrations = [
        ("autoresearch_experiments", "prompt_text", "TEXT"),
        ("autoresearch_experiments", "config_json", "TEXT"),
        ("autoresearch_sessions", "report_md", "TEXT"),
        ("autoresearch_sessions", "session_number", "INTEGER"),
        ("autoresearch_sessions", "parent_session_id", "TEXT"),
        ("autoresearch_experiments", "within_10_pct", "REAL"),
        ("autoresearch_sessions", "best_within_10_pct", "REAL"),
        ("autoresearch_sessions", "best_within_1", "REAL"),
        ("autoresearch_sessions", "bias_mode", "TEXT DEFAULT 'neutral'"),
    ]
    for table, column, col_type in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            # Column already exists
            pass

    # Backfill best_within_10_pct and best_within_1 on sessions from experiment data
    conn.execute("""
        UPDATE autoresearch_sessions
        SET best_within_10_pct = (
                SELECT MAX(e.within_10_pct)
                FROM autoresearch_experiments e
                WHERE e.session_id = autoresearch_sessions.id
                  AND e.within_10_pct IS NOT NULL
            ),
            best_within_1 = (
                SELECT MAX(e.within_1)
                FROM autoresearch_experiments e
                WHERE e.session_id = autoresearch_sessions.id
                  AND e.within_1 IS NOT NULL
            )
        WHERE best_within_10_pct IS NULL OR best_within_1 IS NULL
    """)
    conn.commit()


@contextmanager
def get_db():
    """Context manager for database operations."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
