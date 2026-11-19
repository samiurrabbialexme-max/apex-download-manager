"""Domain models and data structures for download tasks, segments, and media."""
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    CONNECTING = "connecting"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

    @property
    def is_active(self) -> bool:
        return self in (DownloadStatus.CONNECTING, DownloadStatus.DOWNLOADING)

    @property
    def is_terminal(self) -> bool:
        return self in (DownloadStatus.COMPLETED, DownloadStatus.CANCELED)

    @property
    def can_pause(self) -> bool:
        return self in (DownloadStatus.DOWNLOADING, DownloadStatus.CONNECTING, DownloadStatus.QUEUED)

    @property
    def can_resume(self) -> bool:
        return self in (DownloadStatus.PAUSED, DownloadStatus.FAILED)


class DownloadType(str, Enum):
    DIRECT_HTTP = "direct_http"
    MEDIA_STREAM = "media_stream"


@dataclass
class SegmentInfo:
    """Represents a byte range chunk in a multi-segmented download."""
    segment_id: int
    start_byte: int
    end_byte: int
    downloaded_bytes: int = 0
    status: str = "pending"  # pending, downloading, completed, failed

    @property
    def size(self) -> int:
        if self.end_byte < self.start_byte:
            return 0
        return self.end_byte - self.start_byte + 1

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.size - self.downloaded_bytes)

    @property
    def is_complete(self) -> bool:
        return self.downloaded_bytes >= self.size and self.size > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "downloaded_bytes": self.downloaded_bytes,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SegmentInfo":
        return cls(
            segment_id=int(data["segment_id"]),
            start_byte=int(data["start_byte"]),
            end_byte=int(data["end_byte"]),
            downloaded_bytes=int(data.get("downloaded_bytes", 0)),
            status=str(data.get("status", "pending")),
        )


@dataclass
class FormatInfo:
    """Extracted stream or media format from yt-dlp."""
    format_id: str
    resolution: str
    ext: str
    filesize: int = 0
    vcodec: str = "none"
    acodec: str = "none"
    fps: Optional[float] = None
    tbr: Optional[float] = None  # total bitrate kbps
    note: str = ""
    is_audio_only: bool = False
    is_video_only: bool = False

    @property
    def display_name(self) -> str:
        parts = []
        if self.is_audio_only:
            parts.append(f"Audio Only ({self.ext.upper()})")
        else:
            parts.append(f"{self.resolution} ({self.ext.upper()})")
        
        if self.fps and self.fps > 30:
            parts.append(f"{int(self.fps)}fps")
        if self.filesize > 0:
            parts.append(self.format_bytes(self.filesize))
        elif self.tbr:
            parts.append(f"~{int(self.tbr)}kbps")
        if self.note:
            parts.append(f"[{self.note}]")
        return " - ".join(parts)

    @staticmethod
    def format_bytes(num_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:3.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} PB"


@dataclass
class MediaMetadata:
    """Preview metadata extracted from media URLs."""
    url: str
    title: str
    thumbnail_url: str = ""
    duration: int = 0
    uploader: str = ""
    formats: List[FormatInfo] = field(default_factory=list)
    description: str = ""
    webpage_url: str = ""


@dataclass
class DownloadTask:
    """Central representation of a download entity."""
    url: str
    save_path: str
    filename: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    download_type: DownloadType = DownloadType.DIRECT_HTTP
    status: DownloadStatus = DownloadStatus.QUEUED
    total_bytes: int = 0
    downloaded_bytes: int = 0
    speed_bps: float = 0.0
    eta_seconds: int = 0
    segments_count: int = 8
    segments: List[SegmentInfo] = field(default_factory=list)
    format_id: str = ""
    media_title: str = ""
    thumbnail_url: str = ""
    duration: int = 0
    headers: Dict[str, str] = field(default_factory=dict)
    error_message: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    supports_range: bool = True

    @property
    def progress_pct(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        pct = (self.downloaded_bytes / self.total_bytes) * 100.0
        return min(100.0, max(0.0, pct))

    @property
    def formatted_size(self) -> str:
        if self.total_bytes <= 0:
            return FormatInfo.format_bytes(self.downloaded_bytes) + " / Unknown"
        return f"{FormatInfo.format_bytes(self.downloaded_bytes)} / {FormatInfo.format_bytes(self.total_bytes)}"

    @property
    def formatted_speed(self) -> str:
        if self.status != DownloadStatus.DOWNLOADING or self.speed_bps <= 0:
            return "0 B/s"
        return f"{FormatInfo.format_bytes(int(self.speed_bps))}/s"

    @property
    def formatted_eta(self) -> str:
        if self.status != DownloadStatus.DOWNLOADING or self.eta_seconds <= 0 or self.eta_seconds > 86400 * 7:
            return "--:--"
        m, s = divmod(self.eta_seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "filename": self.filename,
            "save_path": self.save_path,
            "download_type": self.download_type.value,
            "status": self.status.value,
            "total_bytes": self.total_bytes,
            "downloaded_bytes": self.downloaded_bytes,
            "speed_bps": self.speed_bps,
            "eta_seconds": self.eta_seconds,
            "segments_count": self.segments_count,
            "segments": [s.to_dict() for s in self.segments],
            "format_id": self.format_id,
            "media_title": self.media_title,
            "thumbnail_url": self.thumbnail_url,
            "duration": self.duration,
            "headers": self.headers,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "supports_range": 1 if self.supports_range else 0,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DownloadTask":
        segments_raw = d.get("segments") or []
        segments = [SegmentInfo.from_dict(s) for s in segments_raw]
        return cls(
            id=d["id"],
            url=d["url"],
            filename=d["filename"],
            save_path=d["save_path"],
            download_type=DownloadType(d.get("download_type", DownloadType.DIRECT_HTTP.value)),
            status=DownloadStatus(d.get("status", DownloadStatus.QUEUED.value)),
            total_bytes=int(d.get("total_bytes", 0)),
            downloaded_bytes=int(d.get("downloaded_bytes", 0)),
            speed_bps=float(d.get("speed_bps", 0.0)),
            eta_seconds=int(d.get("eta_seconds", 0)),
            segments_count=int(d.get("segments_count", 8)),
            segments=segments,
            format_id=str(d.get("format_id", "")),
            media_title=str(d.get("media_title", "")),
            thumbnail_url=str(d.get("thumbnail_url", "")),
            duration=int(d.get("duration", 0)),
            headers=d.get("headers") or {},
            error_message=str(d.get("error_message", "")),
            created_at=float(d.get("created_at", time.time())),
            updated_at=float(d.get("updated_at", time.time())),
            completed_at=d.get("completed_at"),
            supports_range=bool(d.get("supports_range", 1)),
        )
