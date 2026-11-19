"""Dialog displaying external binary status (yt-dlp, ffmpeg) with 1-click downloaders."""
import threading
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from app.config import Config
from app.core.binaries import BinaryInfo, BinaryManager


class BinaryDownloadWorker(QThread):
    """Downloads binary in background thread while streaming percentage."""

    progress_signal = Signal(int, int)  # downloaded, total
    finished_signal = Signal(bool, str)

    def __init__(self, binary_type: str, binary_manager: BinaryManager):
        super().__init__()
        self.binary_type = binary_type
        self.binary_manager = binary_manager

    def run(self) -> None:
        def cb(downloaded: int, total: int):
            self.progress_signal.emit(downloaded, total)

        if self.binary_type == "yt-dlp":
            success, msg = self.binary_manager.download_yt_dlp(cb)
        else:
            success, msg = self.binary_manager.download_ffmpeg(cb)

        self.finished_signal.emit(success, msg)


class BinaryManagerDialog(QDialog):
    """External tools and binary manager dialog."""

    def __init__(self, parent=None, config: Optional[Config] = None):
        super().__init__(parent)
        self.config = config or Config()
        self.manager = BinaryManager(self.config)

        self.setWindowTitle("External Tools & Binaries")
        self.resize(520, 360)
        self.setModal(True)

        self._active_worker: Optional[BinaryDownloadWorker] = None
        self._init_ui()
        self.refresh_status()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        intro = QLabel(
            "Apex uses <b>yt-dlp</b> for extracting media streams and <b>ffmpeg</b> "
            "for high-definition 1080p+ video and audio merging."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #b0b0c0; font-size: 12px;")
        layout.addWidget(intro)

        # yt-dlp Box
        self.grp_yt = QGroupBox("yt-dlp (Media Extractor)")
        grp_yt_layout = QVBoxLayout(self.grp_yt)

        self.lbl_yt_status = QLabel("Checking status...")
        self.lbl_yt_path = QLabel()
        self.lbl_yt_path.setStyleSheet("color: #888899; font-size: 11px;")
        self.pbar_yt = QProgressBar()
        self.pbar_yt.setVisible(False)

        h_yt = QHBoxLayout()
        self.btn_dl_yt = QPushButton("Download / Update yt-dlp")
        self.btn_dl_yt.clicked.connect(lambda: self._start_download("yt-dlp"))
        h_yt.addWidget(self.btn_dl_yt)
        h_yt.addStretch()

        grp_yt_layout.addWidget(self.lbl_yt_status)
        grp_yt_layout.addWidget(self.lbl_yt_path)
        grp_yt_layout.addWidget(self.pbar_yt)
        grp_yt_layout.addLayout(h_yt)
        layout.addWidget(self.grp_yt)

        # ffmpeg Box
        self.grp_ff = QGroupBox("ffmpeg (Audio/Video Muxer)")
        grp_ff_layout = QVBoxLayout(self.grp_ff)

        self.lbl_ff_status = QLabel("Checking status...")
        self.lbl_ff_path = QLabel()
        self.lbl_ff_path.setStyleSheet("color: #888899; font-size: 11px;")
        self.pbar_ff = QProgressBar()
        self.pbar_ff.setVisible(False)

        h_ff = QHBoxLayout()
        self.btn_dl_ff = QPushButton("Download ffmpeg (Windows)")
        self.btn_dl_ff.clicked.connect(lambda: self._start_download("ffmpeg"))
        h_ff.addWidget(self.btn_dl_ff)
        h_ff.addStretch()

        grp_ff_layout.addWidget(self.lbl_ff_status)
        grp_ff_layout.addWidget(self.lbl_ff_path)
        grp_ff_layout.addWidget(self.pbar_ff)
        grp_ff_layout.addLayout(h_ff)
        layout.addWidget(self.grp_ff)

        layout.addStretch()

        # Bottom buttons
        btn_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("Re-scan")
        self.btn_refresh.clicked.connect(self.refresh_status)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

    def refresh_status(self) -> None:
        # Refresh yt-dlp
        yt_info = self.manager.get_yt_dlp_info()
        if yt_info.is_available:
            self.lbl_yt_status.setText(f"✔ <b>Available</b> (Version: {yt_info.version}, Source: {yt_info.source})")
            self.lbl_yt_status.setStyleSheet("color: #2ec4b6;")
            self.lbl_yt_path.setText(f"Path: {yt_info.path or 'Python internal'}")
        else:
            self.lbl_yt_status.setText("✖ <b>Missing</b> - Media downloads will be unavailable.")
            self.lbl_yt_status.setStyleSheet("color: #ff6b6b;")
            self.lbl_yt_path.setText(yt_info.error)

        # Refresh ffmpeg
        ff_info = self.manager.get_ffmpeg_info()
        if ff_info.is_available:
            self.lbl_ff_status.setText(f"✔ <b>Available</b> (Version: {ff_info.version}, Source: {ff_info.source})")
            self.lbl_ff_status.setStyleSheet("color: #2ec4b6;")
            self.lbl_ff_path.setText(f"Path: {ff_info.path}")
        else:
            self.lbl_ff_status.setText("✖ <b>Missing</b> - Video+Audio muxing and 1080p+ formats will be limited.")
            self.lbl_ff_status.setStyleSheet("color: #ff6b6b;")
            self.lbl_ff_path.setText(ff_info.error)

    def _start_download(self, binary_type: str) -> None:
        pbar = self.pbar_yt if binary_type == "yt-dlp" else self.pbar_ff
        btn = self.btn_dl_yt if binary_type == "yt-dlp" else self.btn_dl_ff

        pbar.setVisible(True)
        pbar.setValue(0)
        btn.setEnabled(False)

        self._active_worker = BinaryDownloadWorker(binary_type, self.manager)
        self._active_worker.progress_signal.connect(lambda d, t: self._on_download_progress(pbar, d, t))
        self._active_worker.finished_signal.connect(lambda s, m: self._on_download_finished(binary_type, btn, pbar, s, m))
        self._active_worker.start()

    def _on_download_progress(self, pbar: QProgressBar, downloaded: int, total: int) -> None:
        if total > 0:
            pct = int((downloaded / total) * 100)
            pbar.setValue(pct)
            pbar.setFormat(f"{pct}% ({downloaded // (1024*1024)} MB / {total // (1024*1024)} MB)")

    def _on_download_finished(self, b_type: str, btn: QPushButton, pbar: QProgressBar, success: bool, message: str) -> None:
        btn.setEnabled(True)
        pbar.setVisible(False)
        self.refresh_status()

        if success:
            QMessageBox.information(self, "Download Complete", message)
        else:
            QMessageBox.warning(self, "Download Failed", message)
