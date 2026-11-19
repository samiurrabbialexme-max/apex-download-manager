"""Media extraction and download engine wrapping yt-dlp and ffmpeg."""
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.core.binaries import BinaryManager
from app.core.models import DownloadStatus, DownloadTask, FormatInfo, MediaMetadata
from app.core.url_classifier import sanitize_filename


class MediaDownloadCanceled(Exception):
    """Raised when a media download is canceled or paused by the user."""
    pass


class MediaDownloader:
    """Handles metadata probing and stream extraction/muxing via yt-dlp and ffmpeg."""

    def __init__(self, binary_manager: Optional[BinaryManager] = None):
        self.binary_manager = binary_manager or BinaryManager()

    def probe_media(self, url: str) -> MediaMetadata:
        """Extracts media metadata (title, thumbnail, formats, duration) without downloading."""
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError("yt-dlp is not installed. Please install it or check the binary manager.")

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
            "noplaylist": True,
        }

        # Point to ffmpeg if available
        ffmpeg_info = self.binary_manager.get_ffmpeg_info()
        if ffmpeg_info.is_available and ffmpeg_info.path:
            ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_info.path) or ffmpeg_info.path

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        title = info.get("title", "Unknown Title")
        thumbnail = info.get("thumbnail", "")
        duration = int(info.get("duration", 0))
        uploader = info.get("uploader", "")
        webpage_url = info.get("webpage_url", url)

        formats = self._parse_formats(info)

        return MediaMetadata(
            url=url,
            title=title,
            thumbnail_url=thumbnail,
            duration=duration,
            uploader=uploader,
            formats=formats,
            description=info.get("description", "")[:250],
            webpage_url=webpage_url,
        )

    def _parse_formats(self, info: Dict[str, Any]) -> List[FormatInfo]:
        """Parses and deduplicates useful video and audio formats."""
        raw_formats = info.get("formats", [])
        if not raw_formats:
            # Fallback for single format
            return [
                FormatInfo(
                    format_id="best",
                    resolution=info.get("resolution", "Best Quality"),
                    ext=info.get("ext", "mp4"),
                    filesize=info.get("filesize") or info.get("filesize_approx") or 0,
                    note="Default",
                )
            ]

        parsed: List[FormatInfo] = []
        seen_keys = set()

        ffmpeg_info = self.binary_manager.get_ffmpeg_info()
        ffmpeg_available = ffmpeg_info.is_available and ffmpeg_info.path

        if ffmpeg_available:
            parsed.append(
                FormatInfo(
                    format_id="bestvideo+bestaudio/best",
                    resolution="Best Available Quality (1080p+)",
                    ext="mp4",
                    filesize=0,
                    note="Recommended - Merged via ffmpeg",
                    vcodec="best",
                    acodec="best",
                )
            )
        else:
            parsed.append(
                FormatInfo(
                    format_id="best[vcodec!=none][acodec!=none]/best[ext=mp4]/best",
                    resolution="Best Direct Quality (720p/360p)",
                    ext="mp4",
                    filesize=0,
                    note="Direct pre-merged stream (No ffmpeg needed)",
                    vcodec="best",
                    acodec="best",
                )
            )

        # Always offer "Best Audio"
        parsed.append(
            FormatInfo(
                format_id="bestaudio/best",
                resolution="Audio Only (Best Quality)",
                ext="mp3",
                filesize=0,
                note="Extracted Audio (MP3/M4A)",
                is_audio_only=True,
                vcodec="none",
                acodec="best",
            )
        )

        for f in raw_formats:
            fid = f.get("format_id", "")
            ext = f.get("ext", "mp4")
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            height = f.get("height")
            filesize = f.get("filesize") or f.get("filesize_approx") or 0
            fps = f.get("fps")
            tbr = f.get("tbr")
            format_note = f.get("format_note", "")

            is_video = vcodec != "none"
            is_audio = acodec != "none"
            is_audio_only = is_audio and not is_video
            is_video_only = is_video and not is_audio

            # Label resolution
            if height:
                res = f"{height}p"
            elif is_audio_only:
                res = "Audio Only"
            else:
                res = f.get("resolution", "Default")

            key = (res, ext, is_audio_only)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            # Filter out strange or unsupported containers
            if ext in ("mhtml", "none"):
                continue

            parsed.append(
                FormatInfo(
                    format_id=fid,
                    resolution=res,
                    ext=ext,
                    filesize=filesize,
                    vcodec=vcodec,
                    acodec=acodec,
                    fps=fps,
                    tbr=tbr,
                    note=format_note,
                    is_audio_only=is_audio_only,
                    is_video_only=is_video_only,
                )
            )

        return parsed

    def download_media(
        self,
        task: DownloadTask,
        progress_callback: Optional[Callable[[DownloadTask], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        pause_event: Optional[threading.Event] = None,
    ) -> bool:
        """Executes yt-dlp download with real-time progress callbacks and cancel/pause hooks."""
        try:
            import yt_dlp
        except ImportError:
            task.status = DownloadStatus.FAILED
            task.error_message = "yt-dlp is missing. Please download it via Settings."
            if progress_callback:
                progress_callback(task)
            return False

        task.status = DownloadStatus.CONNECTING
        if progress_callback:
            progress_callback(task)

        target_path = Path(task.save_path)
        target_dir = target_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        format_spec = task.format_id or "bestvideo+bestaudio/best"
        is_audio_target = "audio" in format_spec or target_path.suffix.lower() in (".mp3", ".m4a", ".aac", ".flac")

        # Custom progress hook
        def hook(d: Dict[str, Any]) -> None:
            if cancel_event and cancel_event.is_set():
                raise MediaDownloadCanceled("Download canceled by user.")
            if pause_event and pause_event.is_set():
                raise MediaDownloadCanceled("Download paused by user.")

            status = d.get("status")
            if status == "downloading":
                task.status = DownloadStatus.DOWNLOADING
                task.downloaded_bytes = d.get("downloaded_bytes", task.downloaded_bytes)
                task.total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or task.total_bytes
                task.speed_bps = float(d.get("speed") or 0.0)
                task.eta_seconds = int(d.get("eta") or 0)
                if progress_callback:
                    progress_callback(task)
            elif status == "finished":
                task.downloaded_bytes = task.total_bytes
                if progress_callback:
                    progress_callback(task)

        # Base yt-dlp options
        ydl_opts: Dict[str, Any] = {
            "format": format_spec,
            "outtmpl": str(target_dir / f"{target_path.stem}.%(ext)s"),
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "continuedl": True,
            "overwrites": True,
            "retries": 5,
            "fragment_retries": 5,
        }

        # Speed limit configuration
        if task.headers.get("speed_limit"):
            try:
                limit = int(task.headers["speed_limit"])
                if limit > 0:
                    ydl_opts["ratelimit"] = limit
            except Exception:
                pass

        # Check if ffmpeg is available
        ffmpeg_info = self.binary_manager.get_ffmpeg_info()
        ffmpeg_available = ffmpeg_info.is_available and ffmpeg_info.path

        if ffmpeg_available:
            ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_info.path) or ffmpeg_info.path

            if is_audio_target:
                ydl_opts["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ]
            else:
                ydl_opts["merge_output_format"] = "mp4"
        else:
            # ffmpeg is missing: fallback to single pre-merged stream so the download does not fail!
            if "+" in format_spec:
                format_spec = "best[vcodec!=none][acodec!=none]/best[ext=mp4]/best"
                ydl_opts["format"] = format_spec
            if is_audio_target:
                # Do not run FFmpegExtractAudio postprocessor; keep best native audio stream
                ydl_opts["format"] = "bestaudio/best"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([task.url])

            # Resolve actual downloaded file (prioritize target extension)
            final_file = None
            if is_audio_target:
                candidate_exts = [".mp3", ".m4a", ".aac", ".flac", ".opus", ".ogg", ".webm"]
            else:
                candidate_exts = [".mp4", ".mkv", ".webm", ".avi"]

            for ext in candidate_exts:
                p = target_dir / f"{target_path.stem}{ext}"
                if p.exists() and p.stat().st_size > 0:
                    final_file = p
                    break

            if not final_file:
                actual_files = list(target_dir.glob(f"{target_path.stem}.*"))
                non_parts = [f for f in actual_files if not f.name.endswith(".part")]
                if non_parts:
                    final_file = non_parts[0]

            if final_file:
                task.save_path = str(final_file)
                task.filename = final_file.name
                task.total_bytes = final_file.stat().st_size
                task.downloaded_bytes = task.total_bytes

            task.status = DownloadStatus.COMPLETED
            task.completed_at = time.time()
            task.error_message = ""
            task.speed_bps = 0.0
            task.eta_seconds = 0
            if progress_callback:
                progress_callback(task)
            return True

        except MediaDownloadCanceled:
            if pause_event and pause_event.is_set():
                task.status = DownloadStatus.PAUSED
            else:
                task.status = DownloadStatus.CANCELED
            task.speed_bps = 0.0
            task.eta_seconds = 0
            if progress_callback:
                progress_callback(task)
            return False

        except Exception as e:
            # Recovery: check if the destination file was already created by ffmpeg or yt-dlp
            recovered_file = None
            candidate_exts = [".mp3", ".m4a", ".mp4", ".mkv"] if is_audio_target else [".mp4", ".mkv", ".webm"]
            for ext in candidate_exts:
                p = target_dir / f"{target_path.stem}{ext}"
                if p.exists() and p.stat().st_size > 1024:
                    recovered_file = p
                    break

            if recovered_file:
                task.save_path = str(recovered_file)
                task.filename = recovered_file.name
                task.total_bytes = recovered_file.stat().st_size
                task.downloaded_bytes = task.total_bytes
                task.status = DownloadStatus.COMPLETED
                task.completed_at = time.time()
                task.error_message = ""
                task.speed_bps = 0.0
                task.eta_seconds = 0
                if progress_callback:
                    progress_callback(task)
                return True

            task.status = DownloadStatus.FAILED
            task.error_message = f"Media download failed: {e}"
            task.speed_bps = 0.0
            task.eta_seconds = 0
            if progress_callback:
                progress_callback(task)
            return False
