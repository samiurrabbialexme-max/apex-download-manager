"""Unit tests for SQLite database persistence and recovery."""
import time
from pathlib import Path
import pytest

from app.core.database import Database
from app.core.models import DownloadStatus, DownloadTask, DownloadType, SegmentInfo


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_downloads.db"
    return Database(db_file)


def test_add_and_get_task(temp_db: Database):
    task = DownloadTask(
        url="https://example.com/test.iso",
        filename="test.iso",
        save_path="/tmp/test.iso",
        download_type=DownloadType.DIRECT_HTTP,
        status=DownloadStatus.QUEUED,
        total_bytes=1048576,
        segments_count=4,
    )
    temp_db.add_task(task)

    retrieved = temp_db.get_task(task.id)
    assert retrieved is not None
    assert retrieved.id == task.id
    assert retrieved.filename == "test.iso"
    assert retrieved.total_bytes == 1048576
    assert retrieved.status == DownloadStatus.QUEUED
    assert retrieved.segments_count == 4


def test_update_task_progress(temp_db: Database):
    task = DownloadTask(
        url="https://example.com/data.bin",
        filename="data.bin",
        save_path="/tmp/data.bin",
        total_bytes=2000,
    )
    temp_db.add_task(task)

    segments = [
        SegmentInfo(segment_id=0, start_byte=0, end_byte=999, downloaded_bytes=500, status="downloading"),
        SegmentInfo(segment_id=1, start_byte=1000, end_byte=1999, downloaded_bytes=100, status="downloading"),
    ]
    temp_db.update_task_progress(
        task_id=task.id,
        downloaded_bytes=600,
        total_bytes=2000,
        speed_bps=102400.0,
        eta_seconds=14,
        segments=segments,
    )

    updated = temp_db.get_task(task.id)
    assert updated is not None
    assert updated.downloaded_bytes == 600
    assert updated.speed_bps == 102400.0
    assert updated.eta_seconds == 14
    assert len(updated.segments) == 2
    assert updated.segments[0].downloaded_bytes == 500


def test_crash_recovery_resets_downloading_to_paused(tmp_path: Path):
    db_file = tmp_path / "crash_recovery.db"
    db1 = Database(db_file)

    task1 = DownloadTask(url="https://example.com/a.zip", filename="a.zip", save_path="/tmp/a.zip", status=DownloadStatus.DOWNLOADING)
    task2 = DownloadTask(url="https://example.com/b.zip", filename="b.zip", save_path="/tmp/b.zip", status=DownloadStatus.CONNECTING)
    task3 = DownloadTask(url="https://example.com/c.zip", filename="c.zip", save_path="/tmp/c.zip", status=DownloadStatus.COMPLETED)

    db1.add_task(task1)
    db1.add_task(task2)
    db1.add_task(task3)

    # Force database reopen (simulating app restart after unexpected exit)
    db2 = Database(db_file)

    t1 = db2.get_task(task1.id)
    t2 = db2.get_task(task2.id)
    t3 = db2.get_task(task3.id)

    assert t1.status == DownloadStatus.PAUSED
    assert t2.status == DownloadStatus.PAUSED
    assert t3.status == DownloadStatus.COMPLETED


def test_clear_completed(temp_db: Database):
    t_comp = DownloadTask(url="https://example.com/1", filename="1", save_path="", status=DownloadStatus.COMPLETED)
    t_queued = DownloadTask(url="https://example.com/2", filename="2", save_path="", status=DownloadStatus.QUEUED)

    temp_db.add_task(t_comp)
    temp_db.add_task(t_queued)

    deleted_count = temp_db.clear_completed()
    assert deleted_count == 1
    assert temp_db.get_task(t_comp.id) is None
    assert temp_db.get_task(t_queued.id) is not None
