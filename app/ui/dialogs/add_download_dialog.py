"""Dialog for adding new downloads with instant media format probing and thumbnail preview."""
import os
import threading
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

from PySide6.QtCore import QByteArray, QObject, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from app.config import Config
from app.core.binaries import BinaryManager
from app.core.http_downloader import HttpSegmentDownloader
from app.core.media_downloader import MediaDownloader
from app.core.models import DownloadStatus, DownloadTask, DownloadType, FormatInfo, MediaMetadata
from app.core.url_classifier import (
    classify_url,
    extract_filename_from_url,
    is_media_url,
    sanitize_filename,
    sanitize_url,
)


class ProbeWorker(QThread):
    """Background worker to probe URL metadata without freezing the UI."""

    probe_finished = Signal(object)  # MediaMetadata or dict
    probe_failed = Signal(str)

    def __init__(self, url: str, binary_manager: BinaryManager):
        super().__init__()
        self.url = url
        self.binary_manager = binary_manager

    def run(self) -> None:
        try:
            if is_media_url(self.url):
                md = MediaDownloader(self.binary_manager)
                meta = md.probe_media(self.url)
                self.probe_finished.emit(meta)
            else:
                # Direct HTTP probe
                task = DownloadTask(url=self.url, save_path="", filename="")
                downloader = HttpSegmentDownloader(task)
                supports_range, total_bytes, server_filename = downloader.probe_url()

                suggested_fn = server_filename or extract_filename_from_url(self.url)
                self.probe_finished.emit({
                    "type": "direct_http",
                    "filename": suggested_fn,
                    "total_bytes": total_bytes,
                    "supports_range": supports_range,
                })
        except Exception as e:
            self.probe_failed.emit(str(e))


class ThumbnailLoader(QThread):
    """Fetches thumbnail image in background for smooth UI rendering."""

    image_loaded = Signal(QPixmap)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self) -> None:
        if not self.url:
            return
        try:
            req = Request(self.url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=8) as resp:
                data = resp.read()
                img = QImage.fromData(QByteArray(data))
                if not img.isNull():
                    pix = QPixmap.fromImage(img)
                    self.image_loaded.emit(pix)
        except Exception:
            pass


class AddDownloadDialog(QDialog):
    """Quick-Add download modal dialog."""

    def __init__(self, parent=None, config: Optional[Config] = None, initial_url: str = ""):
        super().__init__(parent)
        self.config = config or Config()
        self.binary_manager = BinaryManager(self.config)

        if not isinstance(initial_url, str):
            initial_url = ""

        self.setWindowTitle("Add Download")
        self.resize(560, 480)
        self.setModal(True)

        self._probe_worker: Optional[ProbeWorker] = None
        self._thumb_worker: Optional[ThumbnailLoader] = None
        self._current_metadata: Optional[MediaMetadata] = None
        self._is_direct_http = True

        self._init_ui(initial_url)

        if initial_url:
            self.start_probe()

    def _init_ui(self, initial_url: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # URL row
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter download link or video URL (YouTube, Facebook, direct file...)")
        self.url_input.setText(initial_url)
        self.url_input.textChanged.connect(self._on_url_changed)

        self.btn_probe = QPushButton("Analyze Link")
        self.btn_probe.clicked.connect(self.start_probe)

        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.btn_probe)
        layout.addLayout(url_layout)

        # Probing status indicator
        self.status_label = QLabel("Ready to analyze link.")
        self.status_label.setStyleSheet("color: #888899; font-style: italic;")
        layout.addWidget(self.status_label)

        # Preview Container (Thumbnail & Info)
        self.preview_container = QHBoxLayout()
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(140, 80)
        self.thumbnail_label.setStyleSheet("background-color: #2b2b36; border-radius: 4px; border: 1px solid #3e3e4a;")
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setText("No Preview")
        self.preview_container.addWidget(self.thumbnail_label)

        self.info_label = QLabel("File information will appear here.")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("font-size: 12px; color: #d0d0d0;")
        self.preview_container.addWidget(self.info_label, 1)

        layout.addLayout(self.preview_container)

        # Form Options
        form_layout = QFormLayout()

        # Format / Quality Selector
        self.format_combo = QComboBox()
        self.format_combo.setEnabled(False)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        form_layout.addRow("Quality / Format:", self.format_combo)

        # File Name
        self.filename_input = QLineEdit()
        form_layout.addRow("Save As:", self.filename_input)

        # Save Directory
        save_dir_layout = QHBoxLayout()
        self.save_dir_input = QLineEdit(self.config.default_download_dir)
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._browse_save_dir)
        save_dir_layout.addWidget(self.save_dir_input)
        save_dir_layout.addWidget(self.btn_browse)
        form_layout.addRow("Save In:", save_dir_layout)

        # Connections / Segments
        seg_layout = QHBoxLayout()
        self.seg_slider = QSlider(Qt.Horizontal)
        self.seg_slider.setRange(1, 32)
        self.seg_slider.setValue(self.config.default_segments)
        self.seg_spin = QSpinBox()
        self.seg_spin.setRange(1, 32)
        self.seg_spin.setValue(self.config.default_segments)

        self.seg_slider.valueChanged.connect(self.seg_spin.setValue)
        self.seg_spin.valueChanged.connect(self.seg_slider.setValue)

        seg_layout.addWidget(self.seg_slider)
        seg_layout.addWidget(self.seg_spin)
        form_layout.addRow("Connections:", seg_layout)

        layout.addLayout(form_layout)

        # Bottom Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_download_later = QPushButton("Download Later (Queue)")
        self.btn_download_later.setStyleSheet("background-color: #3b3b48; color: #ffffff;")
        self.btn_download_later.clicked.connect(lambda: self._submit(auto_start=False))

        self.btn_download_now = QPushButton("Start Download")
        self.btn_download_now.setDefault(True)
        self.btn_download_now.clicked.connect(lambda: self._submit(auto_start=True))

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet("background-color: transparent; border: 1px solid #555566;")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(self.btn_download_later)
        btn_layout.addWidget(self.btn_download_now)

        layout.addLayout(btn_layout)

    def _on_url_changed(self, text: str) -> None:
        clean = sanitize_url(text)
        if clean and not self.filename_input.text():
            suggested = extract_filename_from_url(clean)
            self.filename_input.setText(suggested)

    def start_probe(self) -> None:
        url = sanitize_url(self.url_input.text())
        if not url:
            QMessageBox.warning(self, "Invalid URL", "Please enter a valid HTTP/HTTPS or media link.")
            return

        self.status_label.setText("🔄 Analyzing link and probing formats...")
        self.status_label.setStyleSheet("color: #00b4d8; font-weight: bold;")
        self.btn_probe.setEnabled(False)

        self._probe_worker = ProbeWorker(url, self.binary_manager)
        self._probe_worker.probe_finished.connect(self._on_probe_finished)
        self._probe_worker.probe_failed.connect(self._on_probe_failed)
        self._probe_worker.start()

    def _on_probe_finished(self, result: object) -> None:
        self.btn_probe.setEnabled(True)
        self.format_combo.clear()

        if isinstance(result, MediaMetadata):
            self._is_direct_http = False
            self._current_metadata = result

            self.status_label.setText("✔ Media streams detected successfully.")
            self.status_label.setStyleSheet("color: #2ec4b6; font-weight: bold;")

            dur_str = f"{result.duration // 60:02d}:{result.duration % 60:02d}" if result.duration else "Unknown"
            info_text = f"<b>{result.title}</b><br>Author: {result.uploader or 'Unknown'} | Duration: {dur_str}"
            self.info_label.setText(info_text)

            clean_title = sanitize_filename(result.title)
            self.filename_input.setText(clean_title + ".mp4")

            self.format_combo.blockSignals(True)
            self.format_combo.clear()
            for f in result.formats:
                self.format_combo.addItem(f.display_name, f)
            self.format_combo.setEnabled(True)
            self.format_combo.blockSignals(False)
            self._on_format_changed(self.format_combo.currentIndex())

            # Load thumbnail
            if result.thumbnail_url:
                self._thumb_worker = ThumbnailLoader(result.thumbnail_url)
                self._thumb_worker.image_loaded.connect(self._on_thumb_loaded)
                self._thumb_worker.start()

        elif isinstance(result, dict):
            self._is_direct_http = True
            self._current_metadata = None

            fn = result.get("filename", "download.bin")
            self.filename_input.setText(fn)

            size_bytes = result.get("total_bytes", 0)
            supports_range = result.get("supports_range", False)

            size_str = FormatInfo.format_bytes(size_bytes) if size_bytes > 0 else "Unknown size"
            range_str = "Multi-connection segmented download supported" if supports_range else "Single stream (No server range support)"

            self.status_label.setText("✔ Direct HTTP link verified.")
            self.status_label.setStyleSheet("color: #2ec4b6; font-weight: bold;")
            self.info_label.setText(f"<b>{fn}</b><br>Size: {size_str}<br>{range_str}")

            self.format_combo.addItem(f"Standard Direct File ({size_str})", "direct")
            self.format_combo.setEnabled(False)

    def _on_format_changed(self, index: int) -> None:
        if index < 0:
            return
        data = self.format_combo.itemData(index)
        cur_fn = self.filename_input.text().strip()
        if not cur_fn:
            return

        stem, _ = os.path.splitext(cur_fn)
        if isinstance(data, FormatInfo):
            if data.is_audio_only:
                self.filename_input.setText(f"{stem}.mp3")
            else:
                ext = data.ext if data.ext not in ("none", "") else "mp4"
                self.filename_input.setText(f"{stem}.{ext}")
        elif isinstance(data, str) and "audio" in data:
            self.filename_input.setText(f"{stem}.mp3")

    def _on_probe_failed(self, error: str) -> None:
        self.btn_probe.setEnabled(True)
        self.status_label.setText("⚠ Probe failed. You can still download as direct link.")
        self.status_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")
        self.info_label.setText(f"Details: {error[:180]}")

        url = sanitize_url(self.url_input.text())
        if not self.filename_input.text():
            self.filename_input.setText(extract_filename_from_url(url))

    def _on_thumb_loaded(self, pix: QPixmap) -> None:
        scaled = pix.scaled(self.thumbnail_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumbnail_label.setPixmap(scaled)

    def _browse_save_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.save_dir_input.text())
        if chosen:
            self.save_dir_input.setText(chosen)

    def _submit(self, auto_start: bool) -> None:
        url = sanitize_url(self.url_input.text())
        if not url:
            QMessageBox.warning(self, "Error", "URL cannot be empty.")
            return

        filename = self.filename_input.text().strip()
        if not filename:
            filename = extract_filename_from_url(url)

        save_dir = Path(self.save_dir_input.text().strip())
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = str(save_dir / filename)

        format_data = self.format_combo.currentData()
        format_id = format_data.format_id if isinstance(format_data, FormatInfo) else (format_data or "")
        is_audio = (isinstance(format_data, FormatInfo) and format_data.is_audio_only) or "audio" in str(format_id)

        # Ensure correct extension for audio files
        if is_audio and not filename.lower().endswith((".mp3", ".m4a", ".aac", ".flac", ".ogg")):
            stem, _ = os.path.splitext(filename)
            filename = f"{stem}.mp3"
            save_path = str(save_dir / filename)

        download_type = DownloadType.MEDIA_STREAM if (not self._is_direct_http or is_media_url(url)) else DownloadType.DIRECT_HTTP

        task = DownloadTask(
            url=url,
            filename=filename,
            save_path=save_path,
            download_type=download_type,
            status=DownloadStatus.QUEUED if auto_start else DownloadStatus.PAUSED,
            segments_count=self.seg_spin.value(),
            format_id=format_id,
            media_title=self._current_metadata.title if self._current_metadata else "",
            thumbnail_url=self._current_metadata.thumbnail_url if self._current_metadata else "",
            duration=self._current_metadata.duration if self._current_metadata else 0,
        )

        self.created_task = task
        self.auto_start = auto_start
        self.accept()
