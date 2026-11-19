"""Multi-connection segmented HTTP/HTTPS download engine with resume, rate-limiting, and retry backoff."""
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.core.models import DownloadStatus, DownloadTask, SegmentInfo
from app.core.rate_limiter import RateLimiter
from app.core.url_classifier import parse_content_disposition, sanitize_filename


class HttpSegmentDownloader:
    """High-performance segmented downloader supporting Range requests, resume, and rate limiting."""

    CHUNK_SIZE = 64 * 1024  # 64 KB read buffer

    def __init__(
        self,
        task: DownloadTask,
        rate_limiter: Optional[RateLimiter] = None,
        progress_callback: Optional[Callable[[DownloadTask], None]] = None,
        max_retries: int = 3,
        backoff_sec: float = 2.0,
    ):
        self.task = task
        self.rate_limiter = rate_limiter or RateLimiter()
        self.progress_callback = progress_callback
        self.max_retries = max_retries
        self.backoff_sec = backoff_sec

        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()

        # Speed and ETA calculation trackers
        self._last_progress_time = time.monotonic()
        self._last_downloaded_bytes = 0
        self._speed_history: List[float] = []

    def pause(self) -> None:
        """Signals the downloader to pause gracefully."""
        self._pause_event.set()

    def cancel(self) -> None:
        """Signals the downloader to abort and cancel."""
        self._cancel_event.set()

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    @property
    def is_canceled(self) -> bool:
        return self._cancel_event.is_set()

    def probe_url(self) -> Tuple[bool, int, str]:
        """Probes the remote URL to check Range support, Content-Length, and Content-Disposition filename."""
        req_headers = {"User-Agent": self.task.headers.get("User-Agent", "Mozilla/5.0"), "Accept-Encoding": "identity"}
        req_headers.update(self.task.headers)

        supports_range = False
        content_length = 0
        server_filename = ""

        # 1. Try HEAD request
        try:
            req = Request(self.task.url, headers=req_headers, method="HEAD")
            with urlopen(req, timeout=12) as resp:
                headers = {k.lower(): v for k, v in resp.headers.items()}
                cd = headers.get("content-disposition", "")
                if cd:
                    server_filename = parse_content_disposition(cd)

                if "accept-ranges" in headers and "bytes" in headers["accept-ranges"].lower():
                    supports_range = True

                cl = headers.get("content-length")
                if cl and cl.isdigit():
                    content_length = int(cl)
        except Exception:
            pass

        # 2. If range support not confirmed, probe with a 1-byte GET Range request
        if not supports_range or content_length <= 0:
            try:
                range_headers = dict(req_headers)
                range_headers["Range"] = "bytes=0-0"
                req = Request(self.task.url, headers=range_headers, method="GET")
                with urlopen(req, timeout=12) as resp:
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    cd = headers.get("content-disposition", "")
                    if cd and not server_filename:
                        server_filename = parse_content_disposition(cd)

                    if resp.status == 206:
                        supports_range = True
                        cr = headers.get("content-range", "")
                        # Content-Range: bytes 0-0/12345
                        if "/" in cr:
                            total_str = cr.split("/")[-1].strip()
                            if total_str.isdigit():
                                content_length = int(total_str)
                    elif resp.status == 200 and content_length <= 0:
                        cl = headers.get("content-length")
                        if cl and cl.isdigit():
                            content_length = int(cl)
            except Exception:
                pass

        return supports_range, content_length, server_filename

    def download(self) -> bool:
        """Executes the download using multi-connection segments or single stream fallback."""
        self.task.status = DownloadStatus.CONNECTING
        self._notify_progress()

        supports_range, total_bytes, server_filename = self.probe_url()
        self.task.supports_range = supports_range

        if server_filename and not self.task.filename:
            self.task.filename = server_filename

        if total_bytes > 0:
            self.task.total_bytes = total_bytes

        # If file is very small (< 512KB) or server doesn't support ranges, use single stream
        use_segments = supports_range and total_bytes > (512 * 1024) and self.task.segments_count > 1

        self.task.status = DownloadStatus.DOWNLOADING
        self._last_progress_time = time.monotonic()
        self._last_downloaded_bytes = self.task.downloaded_bytes

        if use_segments:
            return self._download_segmented()
        else:
            return self._download_single_stream()

    def _prepare_segments(self) -> List[SegmentInfo]:
        """Creates or resumes segment boundaries."""
        num_segments = max(1, self.task.segments_count)
        total_size = self.task.total_bytes

        # If existing segments match total size and count, resume them
        if self.task.segments and len(self.task.segments) == num_segments:
            # Refresh downloaded bytes from disk part files
            for seg in self.task.segments:
                part_path = self._get_part_path(seg.segment_id)
                if part_path.exists():
                    seg.downloaded_bytes = part_path.stat().st_size
                else:
                    seg.downloaded_bytes = 0
            return self.task.segments

        # Generate fresh segments
        chunk_size = total_size // num_segments
        segments: List[SegmentInfo] = []

        for i in range(num_segments):
            start = i * chunk_size
            end = (start + chunk_size - 1) if (i < num_segments - 1) else (total_size - 1)
            seg = SegmentInfo(segment_id=i, start_byte=start, end_byte=end, downloaded_bytes=0)

            part_path = self._get_part_path(i)
            if part_path.exists():
                seg.downloaded_bytes = part_path.stat().st_size

            segments.append(seg)

        self.task.segments = segments
        return segments

    def _get_part_path(self, segment_id: int) -> Path:
        save_dir = Path(self.task.save_path).parent
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir / f"{self.task.filename}.part_{self.task.id}_{segment_id}"

    def _download_segmented(self) -> bool:
        segments = self._prepare_segments()
        target_dir = Path(self.task.save_path).parent
        target_dir.mkdir(parents=True, exist_ok=True)

        # Calculate initial downloaded count
        with self._lock:
            self.task.downloaded_bytes = sum(s.downloaded_bytes for s in segments)
            self._last_downloaded_bytes = self.task.downloaded_bytes

        num_workers = min(len(segments), self.task.segments_count)
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            future_to_seg = {
                executor.submit(self._download_segment_worker, seg): seg
                for seg in segments
                if not seg.is_complete
            }

            for future in as_completed(future_to_seg):
                seg = future_to_seg[future]
                try:
                    success = future.result()
                    if not success:
                        if self.is_paused:
                            self.task.status = DownloadStatus.PAUSED
                            self._notify_progress()
                            return False
                        if self.is_canceled:
                            self.task.status = DownloadStatus.CANCELED
                            self._cleanup_parts(segments)
                            self._notify_progress()
                            return False
                        self.task.status = DownloadStatus.FAILED
                        self.task.error_message = f"Segment {seg.segment_id} failed after retries."
                        return False
                except Exception as e:
                    if self.is_paused:
                        self.task.status = DownloadStatus.PAUSED
                        self._notify_progress()
                        return False
                    if self.is_canceled:
                        self.task.status = DownloadStatus.CANCELED
                        self._cleanup_parts(segments)
                        self._notify_progress()
                        return False
                    self.task.status = DownloadStatus.FAILED
                    self.task.error_message = f"Error in segment {seg.segment_id}: {e}"
                    return False

        if self.is_paused:
            self.task.status = DownloadStatus.PAUSED
            self._notify_progress()
            return False

        if self.is_canceled:
            self.task.status = DownloadStatus.CANCELED
            self._cleanup_parts(segments)
            self._notify_progress()
            return False

        # Assemble parts into final destination
        return self._assemble_segments(segments)

    def _download_segment_worker(self, seg: SegmentInfo) -> bool:
        part_path = self._get_part_path(seg.segment_id)
        current_downloaded = part_path.stat().st_size if part_path.exists() else 0
        seg.downloaded_bytes = current_downloaded

        if seg.is_complete:
            seg.status = "completed"
            return True

        req_start = seg.start_byte + current_downloaded
        req_end = seg.end_byte

        for attempt in range(1, self.max_retries + 1):
            if self.is_paused or self.is_canceled:
                return False

            try:
                headers = dict(self.task.headers)
                headers["User-Agent"] = headers.get("User-Agent", "Mozilla/5.0")
                headers["Range"] = f"bytes={req_start}-{req_end}"

                req = Request(self.task.url, headers=headers)
                with urlopen(req, timeout=15) as resp:
                    if resp.status not in (200, 206):
                        raise HTTPError(self.task.url, resp.status, "Unexpected range response", resp.headers, None)

                    mode = "ab" if current_downloaded > 0 else "wb"
                    with open(part_path, mode) as f:
                        seg.status = "downloading"
                        while True:
                            if self.is_paused or self.is_canceled:
                                return False

                            chunk = resp.read(self.CHUNK_SIZE)
                            if not chunk:
                                break

                            self.rate_limiter.acquire(len(chunk))
                            f.write(chunk)
                            seg.downloaded_bytes += len(chunk)

                            with self._lock:
                                self.task.downloaded_bytes += len(chunk)
                                self._update_speed_eta()

                            self._notify_progress()

                    if seg.downloaded_bytes >= seg.size:
                        seg.status = "completed"
                        return True

            except Exception as e:
                seg.status = "failed"
                if attempt < self.max_retries:
                    # Exponential backoff
                    sleep_time = self.backoff_sec * (2 ** (attempt - 1))
                    time.sleep(sleep_time)
                    # Recheck current downloaded bytes on disk for resume
                    current_downloaded = part_path.stat().st_size if part_path.exists() else 0
                    req_start = seg.start_byte + current_downloaded
                else:
                    return False

        return seg.is_complete

    def _assemble_segments(self, segments: List[SegmentInfo]) -> bool:
        """Assembles all downloaded chunk files into the target destination file."""
        final_dest = Path(self.task.save_path)
        temp_dest = final_dest.with_suffix(".assembling")

        try:
            with open(temp_dest, "wb") as out_f:
                for seg in sorted(segments, key=lambda s: s.segment_id):
                    part_path = self._get_part_path(seg.segment_id)
                    if not part_path.exists():
                        raise FileNotFoundError(f"Missing segment file: {part_path}")

                    with open(part_path, "rb") as in_f:
                        shutil.copyfileobj(in_f, out_f, length=128 * 1024)

            # Atomic replace
            if final_dest.exists():
                final_dest.unlink()
            temp_dest.replace(final_dest)

            # Cleanup segment files
            self._cleanup_parts(segments)

            self.task.status = DownloadStatus.COMPLETED
            self.task.downloaded_bytes = self.task.total_bytes
            self.task.speed_bps = 0.0
            self.task.eta_seconds = 0
            self.task.completed_at = time.time()
            self._notify_progress()
            return True
        except Exception as e:
            self.task.status = DownloadStatus.FAILED
            self.task.error_message = f"Failed during segment assembly: {e}"
            if temp_dest.exists():
                temp_dest.unlink()
            return False

    def _download_single_stream(self) -> bool:
        """Single-connection streaming fallback for servers without byte-range support."""
        final_dest = Path(self.task.save_path)
        temp_dest = final_dest.with_suffix(".downloading")

        req_headers = dict(self.task.headers)
        req_headers["User-Agent"] = req_headers.get("User-Agent", "Mozilla/5.0")

        # Resume single stream if server supports it and temp file exists
        mode = "wb"
        start_byte = 0
        if self.task.supports_range and temp_dest.exists():
            start_byte = temp_dest.stat().st_size
            if start_byte > 0:
                req_headers["Range"] = f"bytes={start_byte}-"
                mode = "ab"
                self.task.downloaded_bytes = start_byte

        for attempt in range(1, self.max_retries + 1):
            if self.is_paused or self.is_canceled:
                return False

            try:
                req = Request(self.task.url, headers=req_headers)
                with urlopen(req, timeout=20) as resp, open(temp_dest, mode) as f:
                    while True:
                        if self.is_paused or self.is_canceled:
                            return False

                        chunk = resp.read(self.CHUNK_SIZE)
                        if not chunk:
                            break

                        self.rate_limiter.acquire(len(chunk))
                        f.write(chunk)

                        with self._lock:
                            self.task.downloaded_bytes += len(chunk)
                            if self.task.total_bytes <= 0:
                                cl = resp.headers.get("content-length")
                                if cl and cl.isdigit():
                                    self.task.total_bytes = int(cl) + start_byte
                            self._update_speed_eta()

                        self._notify_progress()

                # Finished successfully
                if final_dest.exists():
                    final_dest.unlink()
                temp_dest.replace(final_dest)

                self.task.status = DownloadStatus.COMPLETED
                self.task.speed_bps = 0.0
                self.task.eta_seconds = 0
                self.task.completed_at = time.time()
                self._notify_progress()
                return True

            except Exception as e:
                if self.is_paused:
                    self.task.status = DownloadStatus.PAUSED
                    self._notify_progress()
                    return False
                if self.is_canceled:
                    self.task.status = DownloadStatus.CANCELED
                    if temp_dest.exists():
                        temp_dest.unlink()
                    self._notify_progress()
                    return False

                if attempt < self.max_retries:
                    time.sleep(self.backoff_sec * (2 ** (attempt - 1)))
                else:
                    self.task.status = DownloadStatus.FAILED
                    self.task.error_message = f"Single stream download failed: {e}"
                    self._notify_progress()
                    return False

        return False

    def _cleanup_parts(self, segments: List[SegmentInfo]) -> None:
        for seg in segments:
            p = self._get_part_path(seg.segment_id)
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def _update_speed_eta(self) -> None:
        now = time.monotonic()
        dt = now - self._last_progress_time
        if dt >= 0.5:
            delta_bytes = self.task.downloaded_bytes - self._last_downloaded_bytes
            current_speed = delta_bytes / dt if dt > 0 else 0.0

            # Rolling speed average
            self._speed_history.append(current_speed)
            if len(self._speed_history) > 5:
                self._speed_history.pop(0)

            avg_speed = sum(self._speed_history) / len(self._speed_history)
            self.task.speed_bps = avg_speed

            if avg_speed > 0 and self.task.total_bytes > self.task.downloaded_bytes:
                remaining_bytes = self.task.total_bytes - self.task.downloaded_bytes
                self.task.eta_seconds = int(remaining_bytes / avg_speed)
            else:
                self.task.eta_seconds = 0

            self._last_progress_time = now
            self._last_downloaded_bytes = self.task.downloaded_bytes

    def _notify_progress(self) -> None:
        if self.progress_callback:
            try:
                self.progress_callback(self.task)
            except Exception:
                pass
