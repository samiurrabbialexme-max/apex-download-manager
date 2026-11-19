"""Unit tests for progress formatting, speed, and ETA calculations."""
from app.core.models import DownloadStatus, DownloadTask, FormatInfo


def test_format_bytes():
    assert "500.0 B" in FormatInfo.format_bytes(500)
    assert "1.0 KB" in FormatInfo.format_bytes(1024)
    assert "10.0 MB" in FormatInfo.format_bytes(10 * 1024 * 1024)
    assert "2.5 GB" in FormatInfo.format_bytes(int(2.5 * 1024 * 1024 * 1024))


def test_download_task_progress_percentage():
    task = DownloadTask(url="", filename="", save_path="", total_bytes=1000, downloaded_bytes=250)
    assert task.progress_pct == 25.0

    task.downloaded_bytes = 1000
    assert task.progress_pct == 100.0

    # Over-download safeguard
    task.downloaded_bytes = 1200
    assert task.progress_pct == 100.0

    # Zero total bytes safeguard
    task.total_bytes = 0
    assert task.progress_pct == 0.0


def test_download_task_formatted_eta():
    task = DownloadTask(url="", filename="", save_path="", status=DownloadStatus.DOWNLOADING, eta_seconds=45)
    assert task.formatted_eta == "00:45"

    task.eta_seconds = 125
    assert task.formatted_eta == "02:05"

    task.eta_seconds = 3665  # 1h 1m 5s
    assert task.formatted_eta == "01:01:05"

    # Paused or idle
    task.status = DownloadStatus.PAUSED
    assert task.formatted_eta == "--:--"


def test_download_task_formatted_speed():
    task = DownloadTask(url="", filename="", save_path="", status=DownloadStatus.DOWNLOADING, speed_bps=1048576.0)
    assert "1.0 MB/s" in task.formatted_speed

    task.status = DownloadStatus.PAUSED
    assert task.formatted_speed == "0 B/s"
