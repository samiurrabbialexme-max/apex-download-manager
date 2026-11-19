"""Unit tests for queue state transitions and lifecycle."""
from pathlib import Path
import pytest
from app.config import Config
from app.core.database import Database
from app.core.models import DownloadStatus, DownloadTask
from app.core.queue_manager import QueueManager


def test_download_status_flags():
    s_queued = DownloadStatus.QUEUED
    assert not s_queued.is_active
    assert not s_queued.is_terminal
    assert s_queued.can_pause
    assert not s_queued.can_resume

    s_dl = DownloadStatus.DOWNLOADING
    assert s_dl.is_active
    assert not s_dl.is_terminal
    assert s_dl.can_pause

    s_paused = DownloadStatus.PAUSED
    assert not s_paused.is_active
    assert not s_paused.is_terminal
    assert s_paused.can_resume

    s_completed = DownloadStatus.COMPLETED
    assert not s_completed.is_active
    assert s_completed.is_terminal


def test_queue_manager_state_transitions(tmp_path: Path):
    db = Database(tmp_path / "queue_test.db")
    cfg = Config(tmp_path / "cfg.json")
    qm = QueueManager(db=db, config=cfg)
    # Stub schedule_next to avoid background thread dispatch in this state test
    qm._schedule_next = lambda: None

    task = DownloadTask(
        url="https://example.com/testfile.dat",
        filename="testfile.dat",
        save_path=str(tmp_path / "testfile.dat"),
        status=DownloadStatus.QUEUED,
    )

    qm.add_task(task, auto_start=False)
    assert qm.get_task(task.id) is not None
    assert qm.get_task(task.id).status == DownloadStatus.QUEUED

    # Pause task
    qm.pause_task(task.id)
    assert qm.get_task(task.id).status == DownloadStatus.PAUSED

    # Resume task
    qm.resume_task(task.id)
    assert qm.get_task(task.id).status == DownloadStatus.QUEUED

    # Cancel task
    qm.cancel_task(task.id)
    assert qm.get_task(task.id).status == DownloadStatus.CANCELED

    # Delete task
    qm.delete_task(task.id)
    assert qm.get_task(task.id) is None
    assert db.get_task(task.id) is None
