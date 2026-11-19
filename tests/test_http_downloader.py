"""Integration tests for multi-segment HTTP downloader with live local Range-supporting server."""
import hashlib
import http.server
import os
import socketserver
import threading
import time
from pathlib import Path
import pytest

from app.core.http_downloader import HttpSegmentDownloader
from app.core.models import DownloadStatus, DownloadTask


class RangeHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP request handler providing HTTP 206 Range support for testing."""

    test_data: bytes = b""

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.test_data)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Disposition", 'attachment; filename="payload.bin"')
        self.end_headers()

    def do_GET(self):
        range_header = self.headers.get("Range")
        total_len = len(self.test_data)

        if range_header and range_header.startswith("bytes="):
            parts = range_header[6:].split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else total_len - 1
            end = min(end, total_len - 1)

            content = self.test_data[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{total_len}")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(total_len))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(self.test_data)

    def log_message(self, format, *args):
        # Silence HTTP server logs during pytest
        pass


@pytest.fixture(scope="module")
def local_http_server():
    # 1.5 MB test payload
    payload = os.urandom(1536 * 1024)
    RangeHTTPRequestHandler.test_data = payload
    expected_sha256 = hashlib.sha256(payload).hexdigest()

    # Find free port
    server = socketserver.TCPServer(("127.0.0.1", 0), RangeHTTPRequestHandler)
    port = server.server_address[1]

    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()

    yield f"http://127.0.0.1:{port}/payload.bin", payload, expected_sha256

    server.shutdown()
    server.server_close()


def test_http_downloader_probe(local_http_server):
    url, payload, _ = local_http_server
    task = DownloadTask(url=url, filename="probe.bin", save_path="")
    dl = HttpSegmentDownloader(task)

    supports_range, total_bytes, server_fn = dl.probe_url()
    assert supports_range is True
    assert total_bytes == len(payload)
    assert server_fn == "payload.bin"


def test_http_downloader_segmented_complete(tmp_path: Path, local_http_server):
    url, payload, expected_sha256 = local_http_server
    dest_path = tmp_path / "downloaded_payload.bin"

    task = DownloadTask(
        url=url,
        filename="downloaded_payload.bin",
        save_path=str(dest_path),
        segments_count=4,
    )

    progress_updates = []
    dl = HttpSegmentDownloader(task, progress_callback=lambda t: progress_updates.append(t.downloaded_bytes))

    success = dl.download()
    assert success is True
    assert task.status == DownloadStatus.COMPLETED
    assert dest_path.exists()
    assert dest_path.stat().st_size == len(payload)

    # Verify SHA-256 byte-for-byte integrity
    with open(dest_path, "rb") as f:
        actual_sha256 = hashlib.sha256(f.read()).hexdigest()
    assert actual_sha256 == expected_sha256
    assert len(progress_updates) > 0


def test_http_downloader_pause_and_resume(tmp_path: Path, local_http_server):
    url, payload, expected_sha256 = local_http_server
    dest_path = tmp_path / "resumed_payload.bin"

    task = DownloadTask(
        url=url,
        filename="resumed_payload.bin",
        save_path=str(dest_path),
        segments_count=4,
    )

    # Use a rate limiter so it doesn't download 1.5MB in 10ms
    from app.core.rate_limiter import RateLimiter
    rate_limiter = RateLimiter(max_bytes_per_sec=100 * 1024)  # 100 KB/s throttled

    dl = HttpSegmentDownloader(task, rate_limiter=rate_limiter)

    # Trigger pause shortly after start
    def trigger_pause():
        time.sleep(0.08)
        dl.pause()

    th = threading.Thread(target=trigger_pause, daemon=True)
    th.start()

    # Initial download should halt with PAUSED
    dl.download()
    assert dl.is_paused
    assert task.status == DownloadStatus.PAUSED

    # Now create a fresh downloader with no rate limit on the same task to resume
    resumer = HttpSegmentDownloader(task)
    success = resumer.download()

    assert success is True
    assert task.status == DownloadStatus.COMPLETED
    assert dest_path.exists()
    assert dest_path.stat().st_size == len(payload)

    with open(dest_path, "rb") as f:
        actual_sha256 = hashlib.sha256(f.read()).hexdigest()
    assert actual_sha256 == expected_sha256
