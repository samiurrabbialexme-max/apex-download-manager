"""Persistent SQLite state store for download history, queues, and segment states."""
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional

from app.config import DB_PATH
from app.core.models import DownloadStatus, DownloadTask, SegmentInfo


class Database:
    """Thread-safe SQLite database manager for task persistence."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        """Initializes tables and indexes."""
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    save_path TEXT NOT NULL,
                    download_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_bytes INTEGER DEFAULT 0,
                    downloaded_bytes INTEGER DEFAULT 0,
                    speed_bps REAL DEFAULT 0.0,
                    eta_seconds INTEGER DEFAULT 0,
                    segments_count INTEGER DEFAULT 8,
                    segments_json TEXT,
                    format_id TEXT,
                    media_title TEXT,
                    thumbnail_url TEXT,
                    duration INTEGER DEFAULT 0,
                    headers_json TEXT,
                    error_message TEXT,
                    created_at REAL,
                    updated_at REAL,
                    completed_at REAL,
                    supports_range INTEGER DEFAULT 1
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON tasks(created_at DESC)")
            conn.commit()

            # Crash recovery: If the app was closed abruptly while downloading, reset active tasks to PAUSED
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, speed_bps = 0.0, eta_seconds = 0
                WHERE status IN (?, ?)
                """,
                (DownloadStatus.PAUSED.value, DownloadStatus.DOWNLOADING.value, DownloadStatus.CONNECTING.value),
            )
            conn.commit()

    def add_task(self, task: DownloadTask) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    id, url, filename, save_path, download_type, status,
                    total_bytes, downloaded_bytes, speed_bps, eta_seconds,
                    segments_count, segments_json, format_id, media_title,
                    thumbnail_url, duration, headers_json, error_message,
                    created_at, updated_at, completed_at, supports_range
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.url,
                    task.filename,
                    task.save_path,
                    task.download_type.value,
                    task.status.value,
                    task.total_bytes,
                    task.downloaded_bytes,
                    task.speed_bps,
                    task.eta_seconds,
                    task.segments_count,
                    json.dumps([s.to_dict() for s in task.segments]),
                    task.format_id,
                    task.media_title,
                    task.thumbnail_url,
                    task.duration,
                    json.dumps(task.headers),
                    task.error_message,
                    task.created_at,
                    task.updated_at,
                    task.completed_at,
                    1 if task.supports_range else 0,
                ),
            )
            conn.commit()

    def update_task_progress(
        self,
        task_id: str,
        downloaded_bytes: int,
        total_bytes: int,
        speed_bps: float,
        eta_seconds: int,
        segments: Optional[List[SegmentInfo]] = None,
    ) -> None:
        with self._lock, self._get_connection() as conn:
            if segments is not None:
                conn.execute(
                    """
                    UPDATE tasks
                    SET downloaded_bytes = ?, total_bytes = ?, speed_bps = ?,
                        eta_seconds = ?, segments_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        downloaded_bytes,
                        total_bytes,
                        speed_bps,
                        eta_seconds,
                        json.dumps([s.to_dict() for s in segments]),
                        time.time(),
                        task_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE tasks
                    SET downloaded_bytes = ?, total_bytes = ?, speed_bps = ?,
                        eta_seconds = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (downloaded_bytes, total_bytes, speed_bps, eta_seconds, time.time(), task_id),
                )
            conn.commit()

    def update_task_status(
        self,
        task_id: str,
        status: DownloadStatus,
        error_message: str = "",
        completed_at: Optional[float] = None,
    ) -> None:
        with self._lock, self._get_connection() as conn:
            now = time.time()
            if status == DownloadStatus.COMPLETED and completed_at is None:
                completed_at = now
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, error_message = ?, updated_at = ?, completed_at = ?, speed_bps = 0.0, eta_seconds = 0
                WHERE id = ?
                """,
                (status.value, error_message, now, completed_at, task_id),
            )
            conn.commit()

    def update_task(self, task: DownloadTask) -> None:
        self.add_task(task)

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_task(row)

    def get_all_tasks(self) -> List[DownloadTask]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC")
            return [self._row_to_task(r) for r in cursor.fetchall()]

    def delete_task(self, task_id: str) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()

    def clear_completed(self) -> int:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE status = ?", (DownloadStatus.COMPLETED.value,))
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def _row_to_task(self, row: sqlite3.Row) -> DownloadTask:
        segments_raw = json.loads(row["segments_json"]) if row["segments_json"] else []
        headers = json.loads(row["headers_json"]) if row["headers_json"] else {}
        d = dict(row)
        d["segments"] = segments_raw
        d["headers"] = headers
        return DownloadTask.from_dict(d)
