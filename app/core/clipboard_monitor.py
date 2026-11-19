"""Clipboard listener service for auto-detecting downloadable links and media URLs."""
import re
from typing import Optional
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QClipboard, QGuiApplication

from app.config import Config
from app.core.url_classifier import COMMON_FILE_EXTENSIONS, is_media_url, sanitize_url


class ClipboardMonitor(QObject):
    """Watches the system clipboard and signals when a supported media or file URL is copied."""

    url_detected = Signal(str)

    def __init__(self, config: Optional[Config] = None):
        super().__init__()
        self.config = config or Config()
        self._enabled = self.config.clipboard_monitor
        self._last_processed_url = ""
        self._clipboard: Optional[QClipboard] = None
        self._poll_timer: Optional[QTimer] = None

    def start(self) -> None:
        """Starts monitoring system clipboard events."""
        app = QGuiApplication.instance()
        if not app:
            return

        self._clipboard = app.clipboard()
        if self._clipboard:
            self._clipboard.dataChanged.connect(self._check_clipboard)

        # Polling fallback is only safe/needed on Windows to bypass Win32 clipboard mutex locks
        import platform
        if platform.system() == "Windows":
            self._poll_timer = QTimer(self)
            self._poll_timer.timeout.connect(self._check_clipboard)
            self._poll_timer.start(2000)

    def stop(self) -> None:
        """Stops monitoring."""
        if self._poll_timer:
            self._poll_timer.stop()
        if self._clipboard:
            try:
                self._clipboard.dataChanged.disconnect(self._check_clipboard)
            except Exception:
                pass

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.config.set("clipboard_monitor", enabled)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def _check_clipboard(self) -> None:
        if not self._enabled:
            return

        app = QGuiApplication.instance()
        if not app:
            return

        clipboard = app.clipboard()
        text = clipboard.text().strip()
        if not text:
            return

        # Avoid redundant processing
        if text == self._last_processed_url:
            return

        clean_url = sanitize_url(text)
        if not self._is_downloadable_url(clean_url):
            return

        self._last_processed_url = text
        self.url_detected.emit(clean_url)

    def _is_downloadable_url(self, url: str) -> bool:
        """Determines if the URL in the clipboard is a candidate for download."""
        if not url.startswith(("http://", "https://", "ftp://")):
            return False

        try:
            parsed = urlparse(url)
            if not parsed.netloc or "." not in parsed.netloc:
                return False

            # Check if it's a recognized media platform
            if is_media_url(url):
                return True

            # Check if path has a common downloadable file extension
            path_lower = parsed.path.lower()
            for ext in COMMON_FILE_EXTENSIONS:
                if path_lower.endswith(ext):
                    return True

            return False
        except Exception:
            return False
