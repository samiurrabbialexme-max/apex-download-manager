"""Queue manager, concurrency orchestrator, and Qt Signal dispatcher."""
import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QObject, Signal

from app.config import Config
from app.core.binaries import BinaryManager
from app.core.database import Database
from app.core.http_downloader import HttpSegmentDownloader
from app.core.media_downloader import MediaDownloader
from app.core.models import DownloadStatus, DownloadTask, DownloadType
from app.core.rate_limiter import RateLimiter


class QueueManager(QObject):
    """Central queue coordinator managing worker threads, concurrency, and task state."""

    # Qt Signals for real-time UI synchronization
    task_added = Signal(object)              # DownloadTask
    task_updated = Signal(object)            # DownloadTask
    task_status_changed = Signal(str, str)   # task_id, status_str
    task_completed = Signal(object)          # DownloadTask
    task_failed = Signal(str, str)           # task_id, error_message
    task_deleted = Signal(str)               # task_id
    stats_updated = Signal(int, float)       # active_downloads, total_speed_bps

    def __init__(self, db: Optional[Database] = None, config: Optional[Config] = None):
        super().__init__()
        self.db = db or Database()
        self.config = config or Config()
        self.binary_manager = BinaryManager(self.config)
        self.media_downloader = MediaDownloader(self.binary_manager)

        self.global_rate_limiter = RateLimiter(self.config.speed_limit_bytes_per_sec)

        self._active_workers: Dict[str, threading.Thread] = {}
        self._active_downloaders: Dict[str, object] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._pause_events: Dict[str, threading.Event] = {}
        self._tasks_cache: Dict[str, DownloadTask] = {}
        self._last_db_save_time: Dict[str, float] = {}

        self._lock = threading.RLock()
        self._shutdown_flag = False

        # Load existing tasks from DB
        self._load_persisted_tasks()

    def _load_persisted_tasks(self) -> None:
        tasks = self.db.get_all_tasks()
        with self._lock:
            for t in tasks:
                self._tasks_cache[t.id] = t

    def get_all_tasks(self) -> list[DownloadTask]:
        with self._lock:
            return list(self._tasks_cache.values())

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        with self._lock:
            return self._tasks_cache.get(task_id)

    def set_speed_limit(self, max_bytes_per_sec: int) -> None:
        """Dynamically adjusts global bandwidth limit."""
        self.config.set("speed_limit_bytes_per_sec", max_bytes_per_sec)
        self.global_rate_limiter.set_rate(max_bytes_per_sec)

    def set_max_concurrent(self, max_concurrent: int) -> None:
        self.config.set("max_concurrent_downloads", max(1, max_concurrent))
        self._schedule_next()

    def add_task(self, task: DownloadTask, auto_start: bool = True) -> None:
        """Adds a new task to queue and database."""
        with self._lock:
            self._tasks_cache[task.id] = task
        self.db.add_task(task)
        self.task_added.emit(task)

        if auto_start:
            self.start_task(task.id)

    def start_task(self, task_id: str) -> None:
        """Marks task as QUEUED and schedules download."""
        with self._lock:
            task = self._tasks_cache.get(task_id)
            if not task:
                return
            if task.id in self._active_workers:
                return  # Already running
            task.status = DownloadStatus.QUEUED
            task.error_message = ""

        self.db.update_task_status(task_id, DownloadStatus.QUEUED)
        self.task_status_changed.emit(task_id, DownloadStatus.QUEUED.value)
        self.task_updated.emit(task)
        self._schedule_next()

    def pause_task(self, task_id: str) -> None:
        """Pauses an active or queued task."""
        with self._lock:
            if task_id in self._pause_events:
                self._pause_events[task_id].set()

            task = self._tasks_cache.get(task_id)
            if task:
                task.status = DownloadStatus.PAUSED
                task.speed_bps = 0.0
                task.eta_seconds = 0

        self.db.update_task_status(task_id, DownloadStatus.PAUSED)
        self.task_status_changed.emit(task_id, DownloadStatus.PAUSED.value)
        if task:
            self.task_updated.emit(task)
        self._schedule_next()

    def resume_task(self, task_id: str) -> None:
        """Resumes a paused or failed task."""
        self.start_task(task_id)

    def retry_task(self, task_id: str) -> None:
        """Resets errors and retries the task."""
        with self._lock:
            task = self._tasks_cache.get(task_id)
            if task:
                task.error_message = ""
                task.status = DownloadStatus.QUEUED
        self.start_task(task_id)

    def cancel_task(self, task_id: str) -> None:
        """Cancels an active task."""
        with self._lock:
            if task_id in self._cancel_events:
                self._cancel_events[task_id].set()
            task = self._tasks_cache.get(task_id)
            if task:
                task.status = DownloadStatus.CANCELED
                task.speed_bps = 0.0
                task.eta_seconds = 0

        self.db.update_task_status(task_id, DownloadStatus.CANCELED)
        self.task_status_changed.emit(task_id, DownloadStatus.CANCELED.value)
        if task:
            self.task_updated.emit(task)
        self._schedule_next()

    def delete_task(self, task_id: str, delete_file: bool = False) -> None:
        """Removes a task from queue, database, and optionally deletes the target file on disk."""
        self.cancel_task(task_id)

        with self._lock:
            task = self._tasks_cache.pop(task_id, None)

        if task and delete_file:
            try:
                p = Path(task.save_path)
                if p.exists():
                    p.unlink()
            except Exception as e:
                print(f"[QueueManager] Failed to delete file on disk: {e}")

        self.db.delete_task(task_id)
        self.task_deleted.emit(task_id)
        self._schedule_next()

    def pause_all(self) -> None:
        with self._lock:
            ids = list(self._tasks_cache.keys())
        for tid in ids:
            self.pause_task(tid)

    def resume_all(self) -> None:
        with self._lock:
            ids = [
                t.id for t in self._tasks_cache.values()
                if t.status in (DownloadStatus.PAUSED, DownloadStatus.FAILED)
            ]
        for tid in ids:
            self.resume_task(tid)

    def clear_completed(self) -> None:
        with self._lock:
            completed_ids = [
                t.id for t in self._tasks_cache.values()
                if t.status == DownloadStatus.COMPLETED
            ]
            for cid in completed_ids:
                self._tasks_cache.pop(cid, None)

        self.db.clear_completed()
        for cid in completed_ids:
            self.task_deleted.emit(cid)

    def _schedule_next(self) -> None:
        """Picks queued tasks and launches workers up to max concurrent limit."""
        if self._shutdown_flag:
            return

        with self._lock:
            active_count = len(self._active_workers)
            max_concurrent = self.config.max_concurrent_downloads

            if active_count >= max_concurrent:
                self._emit_stats()
                return

            slots_available = max_concurrent - active_count
            queued_tasks = [
                t for t in self._tasks_cache.values()
                if t.status == DownloadStatus.QUEUED and t.id not in self._active_workers
            ]
            # Order by created_at ascending
            queued_tasks.sort(key=lambda t: t.created_at)
            to_launch = queued_tasks[:slots_available]

            for task in to_launch:
                cancel_event = threading.Event()
                pause_event = threading.Event()
                self._cancel_events[task.id] = cancel_event
                self._pause_events[task.id] = pause_event

                worker = threading.Thread(
                    target=self._run_worker,
                    args=(task, cancel_event, pause_event),
                    daemon=True,
                    name=f"Worker-{task.id}",
                )
                self._active_workers[task.id] = worker
                worker.start()

            self._emit_stats()

    def _run_worker(
        self,
        task: DownloadTask,
        cancel_event: threading.Event,
        pause_event: threading.Event,
    ) -> None:
        """Worker thread entry point for either HTTP or media extraction."""
        def progress_cb(updated_task: DownloadTask) -> None:
            now = time.monotonic()
            last_save = self._last_db_save_time.get(updated_task.id, 0.0)

            # Persist to DB at most once per 1.5 seconds or upon state change
            if (now - last_save) >= 1.5 or updated_task.status != DownloadStatus.DOWNLOADING:
                self.db.update_task_progress(
                    updated_task.id,
                    updated_task.downloaded_bytes,
                    updated_task.total_bytes,
                    updated_task.speed_bps,
                    updated_task.eta_seconds,
                    updated_task.segments,
                )
                self._last_db_save_time[updated_task.id] = now

            self.task_updated.emit(updated_task)
            self._emit_stats()

        success = False
        try:
            if task.download_type == DownloadType.MEDIA_STREAM:
                success = self.media_downloader.download_media(
                    task=task,
                    progress_callback=progress_cb,
                    cancel_event=cancel_event,
                    pause_event=pause_event,
                )
            else:
                downloader = HttpSegmentDownloader(
                    task=task,
                    rate_limiter=self.global_rate_limiter,
                    progress_callback=progress_cb,
                    max_retries=self.config.get("auto_retry_count", 3),
                    backoff_sec=float(self.config.get("retry_backoff_sec", 2.0)),
                )
                with self._lock:
                    self._active_downloaders[task.id] = downloader

                # Connect cancel/pause
                def monitor_signals():
                    while task.status.is_active:
                        if cancel_event.is_set():
                            downloader.cancel()
                            break
                        if pause_event.is_set():
                            downloader.pause()
                            break
                        time.sleep(0.1)

                monitor_th = threading.Thread(target=monitor_signals, daemon=True)
                monitor_th.start()

                success = downloader.download()

        except Exception as e:
            task.status = DownloadStatus.FAILED
            task.error_message = str(e)
            success = False

        finally:
            with self._lock:
                self._active_workers.pop(task.id, None)
                self._active_downloaders.pop(task.id, None)
                self._cancel_events.pop(task.id, None)
                self._pause_events.pop(task.id, None)

            # Final database sync
            self.db.update_task(task)
            self.task_status_changed.emit(task.id, task.status.value)
            self.task_updated.emit(task)

            if success or task.status == DownloadStatus.COMPLETED:
                self.task_completed.emit(task)
            elif task.status == DownloadStatus.FAILED:
                self.task_failed.emit(task.id, task.error_message)

            self._schedule_next()

    def _emit_stats(self) -> None:
        with self._lock:
            active_count = len(self._active_workers)
            total_speed = sum(
                t.speed_bps for t in self._tasks_cache.values()
                if t.status == DownloadStatus.DOWNLOADING
            )
        self.stats_updated.emit(active_count, total_speed)

    def shutdown(self) -> None:
        """Gracefully halts all worker threads on application exit."""
        self._shutdown_flag = True
        self.pause_all()
