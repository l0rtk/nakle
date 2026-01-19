import sqlite3
import os
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from contextlib import contextmanager
from threading import Lock

# Database path, configurable via environment variable
DB_PATH = os.environ.get("USAGE_DB_PATH", "/data/usage.db")

_db_lock = Lock()


def init_db():
    """Initialize database and create tables if needed."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'unknown',
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                conversation_id TEXT,
                request_id TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON usage_records(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON usage_records(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source_timestamp ON usage_records(source, timestamp)")
        conn.commit()


@contextmanager
def get_connection():
    """Thread-safe database connection context manager."""
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def record_usage(
    source: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    request_id: str,
    conversation_id: Optional[str] = None
):
    """Record a single usage event."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO usage_records
            (timestamp, source, model, input_tokens, output_tokens, total_tokens, conversation_id, request_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                source,
                model,
                input_tokens,
                output_tokens,
                input_tokens + output_tokens,
                conversation_id,
                request_id
            )
        )
        conn.commit()


def get_usage_records(
    source: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Tuple[List[Dict[str, Any]], int]:
    """Retrieve usage records with optional filters."""
    conditions = []
    params = []

    if source:
        conditions.append("source = ?")
        params.append(source)
    if start_time:
        conditions.append("timestamp >= ?")
        params.append(start_time)
    if end_time:
        conditions.append("timestamp <= ?")
        params.append(end_time)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    with get_connection() as conn:
        # Get total count
        count_result = conn.execute(
            f"SELECT COUNT(*) FROM usage_records WHERE {where_clause}",
            params
        ).fetchone()
        total_count = count_result[0]

        # Get records
        rows = conn.execute(
            f"""
            SELECT timestamp, source, model, input_tokens, output_tokens,
                   total_tokens, conversation_id, request_id
            FROM usage_records
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset]
        ).fetchall()

        records = [dict(row) for row in rows]
        return records, total_count


def get_usage_stats(
    source: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get aggregated usage statistics grouped by source."""
    conditions = []
    params = []

    if source:
        conditions.append("source = ?")
        params.append(source)
    if start_time:
        conditions.append("timestamp >= ?")
        params.append(start_time)
    if end_time:
        conditions.append("timestamp <= ?")
        params.append(end_time)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                source,
                COUNT(*) as total_requests,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(total_tokens) as total_tokens
            FROM usage_records
            WHERE {where_clause}
            GROUP BY source
            ORDER BY total_tokens DESC
            """,
            params
        ).fetchall()

        return [dict(row) for row in rows]
