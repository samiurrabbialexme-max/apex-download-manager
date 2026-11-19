"""Main application dashboard with IDM-inspired layout, category tree, and status bar."""
import os
import platform
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import Config
from app.core.clipboard_monitor import ClipboardMonitor
from app.core.models import DownloadStatus, DownloadTask, DownloadType, FormatInfo
from app.core.queue_manager import QueueManager
from app.ui.components.task_table import TaskTableWidget
from app.ui.components.tray_icon import TrayController, create_app_icon
from app.ui.dialogs.add_download_dialog import AddDownloadDialog
from app.ui.dialogs.binary_manager_dialog import BinaryManagerDialog
from app.ui.dialogs.settings_dialog import SettingsDialog
from app.ui.theme import get_theme_qss


class MainWindow(QMainWindow):
    """Main desktop window for Apex Download Manager."""

    CAT_ALL = "all"
    CAT_DOWNLOADING = "downloading"
    CAT_QUEUED = "queued"
    CAT_COMPLETED = "completed"
    CAT_PAUSED = "paused"
    CAT_FAILED = "failed"
    CAT_MEDIA = "media"
    CAT_DIRECT = "direct"

    def __init__(self, queue_manager: QueueManager, config: Optional[Config] = None):
        super().__init__()
        self.queue_manager = queue_manager
        self.config = config or Config()

        self.setWindowTitle("Apex Download Manager")
        self.setWindowIcon(create_app_icon())
        self.resize(1020, 640)

        self._current_category = self.CAT_ALL
        self._category_items: Dict[str, QTreeWidgetItem] = {}

        self._setup_ui()
        self._setup_connections()

        # System tray controller
        self.tray_controller = TrayController(self, self.queue_manager)

        # Clipboard monitor
        self.clipboard_monitor = ClipboardMonitor(self.config)
        self.clipboard_monitor.url_detected.connect(self._on_clipboard_url)
        if self.config.clipboard_monitor:
            self.clipboard_monitor.start()

        # Apply saved stylesheet
        self._apply_theme()

        # Initial populate from database
        self._populate_initial_tasks()

    def _setup_ui(self) -> None:
        self._setup_toolbar()

        # Central Splitter: Category sidebar on left, Task table on right
        splitter = QSplitter(Qt.Horizontal)

        # Left Category Tree
        self.category_tree = QTreeWidget()
        self.category_tree.setHeaderHidden(True)
        self.category_tree.setMaximumWidth(220)
        self.category_tree.setMinimumWidth(160)
        self._build_category_tree()
        self.category_tree.itemClicked.connect(self._on_category_selected)
        splitter.addWidget(self.category_tree)

        # Right Task Table
        self.table = TaskTableWidget()
        splitter.addWidget(self.table)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)

        # Bottom Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.lbl_status_active = QLabel("Active: 0 / 3")
        self.lbl_status_speed = QLabel("Total Speed: 0 B/s")
        self.lbl_status_binaries = QLabel("Tools: Checking...")
        self.lbl_status_clipboard = QLabel("Clipboard: ON" if self.config.clipboard_monitor else "Clipboard: OFF")

        self.status_bar.addWidget(self.lbl_status_active, 1)
        self.status_bar.addWidget(self.lbl_status_speed, 1)
        self.status_bar.addPermanentWidget(self.lbl_status_binaries)
        self.status_bar.addPermanentWidget(self.lbl_status_clipboard)

        self._update_binary_status_bar()

    def _setup_toolbar(self) -> None:
        toolbar = QToolBar("Main Controls")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # + Add URL
        self.act_add = QAction("➕ Add URL", self)
        self.act_add.setShortcut(QKeySequence("Ctrl+N"))
        self.act_add.triggered.connect(self.open_add_dialog)
        toolbar.addAction(self.act_add)

        toolbar.addSeparator()

        # Resume
        self.act_resume = QAction("▶ Resume", self)
        self.act_resume.triggered.connect(self._on_resume_clicked)
        toolbar.addAction(self.act_resume)

        # Pause
        self.act_pause = QAction("⏸ Pause", self)
        self.act_pause.triggered.connect(self._on_pause_clicked)
        toolbar.addAction(self.act_pause)

        # Stop / Cancel
        self.act_stop = QAction("⏹ Stop", self)
        self.act_stop.triggered.connect(self._on_stop_clicked)
        toolbar.addAction(self.act_stop)

        # Delete
        self.act_delete = QAction("🗑 Delete", self)
        self.act_delete.setShortcut(QKeySequence.Delete)
        self.act_delete.triggered.connect(self._on_delete_clicked)
        toolbar.addAction(self.act_delete)

        toolbar.addSeparator()

        # Clear Completed
        self.act_clear = QAction("🧹 Clear Finished", self)
        self.act_clear.triggered.connect(self.queue_manager.clear_completed)
        toolbar.addAction(self.act_clear)

        toolbar.addSeparator()

        # Settings
        self.act_settings = QAction("⚙ Settings", self)
        self.act_settings.triggered.connect(self._open_settings_dialog)
        toolbar.addAction(self.act_settings)

        # External Binaries
        self.act_binaries = QAction("🛠 Binaries", self)
        self.act_binaries.triggered.connect(self._open_binary_dialog)
        toolbar.addAction(self.act_binaries)

    def _build_category_tree(self) -> None:
        self.category_tree.clear()

        categories = [
            (self.CAT_ALL, "📁 All Downloads"),
            (self.CAT_DOWNLOADING, "⬇ Downloading"),
            (self.CAT_QUEUED, "⏳ Queued"),
            (self.CAT_COMPLETED, "✔ Completed"),
            (self.CAT_PAUSED, "⏸ Paused"),
            (self.CAT_FAILED, "✖ Failed"),
            (self.CAT_MEDIA, "🎬 Media Streams"),
            (self.CAT_DIRECT, "📦 Direct Files"),
        ]

        for cat_id, title in categories:
            item = QTreeWidgetItem([f"{title} (0)"])
            item.setData(0, Qt.UserRole, cat_id)
            self.category_tree.addTopLevelItem(item)
            self._category_items[cat_id] = item

        self.category_tree.setCurrentItem(self._category_items[self.CAT_ALL])

    def _setup_connections(self) -> None:
        # Table action connections
        self.table.pause_requested.connect(self.queue_manager.pause_task)
        self.table.resume_requested.connect(self.queue_manager.resume_task)
        self.table.retry_requested.connect(self.queue_manager.retry_task)
        self.table.delete_requested.connect(self.queue_manager.delete_task)

        # Queue manager signals
        self.queue_manager.task_added.connect(self._on_task_added)
        self.queue_manager.task_updated.connect(self._on_task_updated)
        self.queue_manager.task_status_changed.connect(self._on_task_status_changed)
        self.queue_manager.task_deleted.connect(self._on_task_deleted)
        self.queue_manager.stats_updated.connect(self._on_stats_updated)

    def _populate_initial_tasks(self) -> None:
        tasks = self.queue_manager.get_all_tasks()
        for t in tasks:
            self.table.update_or_add_task(t)
        self._refresh_category_counts()
        self._apply_category_filter()

    @Slot()
    def open_add_dialog(self, initial_url: str = "") -> None:
        if not isinstance(initial_url, str):
            initial_url = ""
        dialog = AddDownloadDialog(self, self.config, initial_url=initial_url)
        if dialog.exec():
            task = getattr(dialog, "created_task", None)
            auto_start = getattr(dialog, "auto_start", True)
            if task:
                self.queue_manager.add_task(task, auto_start=auto_start)

    def _on_clipboard_url(self, url: str) -> None:
        # If user has clipboard monitor enabled, bring dialog up
        if not self.isVisible():
            self.tray_controller.show_window()
        self.open_add_dialog(initial_url=url)

    def _on_task_added(self, task: DownloadTask) -> None:
        self.table.update_or_add_task(task)
        self._refresh_category_counts()
        self._apply_category_filter()

    def _on_task_updated(self, task: DownloadTask) -> None:
        self.table.update_or_add_task(task)
        self._refresh_category_counts()

    def _on_task_status_changed(self, task_id: str, status_str: str) -> None:
        self._refresh_category_counts()
        self._apply_category_filter()

    def _on_task_deleted(self, task_id: str) -> None:
        self.table.remove_task(task_id)
        self._refresh_category_counts()

    def _on_stats_updated(self, active_count: int, total_speed: float) -> None:
        max_c = self.config.max_concurrent_downloads
        self.lbl_status_active.setText(f"Active: {active_count} / {max_c}")
        formatted_speed = FormatInfo.format_bytes(int(total_speed)) + "/s"
        self.lbl_status_speed.setText(f"Total Speed: {formatted_speed}")

    def _on_category_selected(self, item: QTreeWidgetItem, column: int) -> None:
        cat_id = item.data(0, Qt.UserRole)
        if cat_id:
            self._current_category = cat_id
            self._apply_category_filter()

    def _refresh_category_counts(self) -> None:
        tasks = self.queue_manager.get_all_tasks()
        counts = {
            self.CAT_ALL: len(tasks),
            self.CAT_DOWNLOADING: sum(1 for t in tasks if t.status in (DownloadStatus.DOWNLOADING, DownloadStatus.CONNECTING)),
            self.CAT_QUEUED: sum(1 for t in tasks if t.status == DownloadStatus.QUEUED),
            self.CAT_COMPLETED: sum(1 for t in tasks if t.status == DownloadStatus.COMPLETED),
            self.CAT_PAUSED: sum(1 for t in tasks if t.status == DownloadStatus.PAUSED),
            self.CAT_FAILED: sum(1 for t in tasks if t.status == DownloadStatus.FAILED),
            self.CAT_MEDIA: sum(1 for t in tasks if t.download_type == DownloadType.MEDIA_STREAM),
            self.CAT_DIRECT: sum(1 for t in tasks if t.download_type == DownloadType.DIRECT_HTTP),
        }

        titles = {
            self.CAT_ALL: "📁 All Downloads",
            self.CAT_DOWNLOADING: "⬇ Downloading",
            self.CAT_QUEUED: "⏳ Queued",
            self.CAT_COMPLETED: "✔ Completed",
            self.CAT_PAUSED: "⏸ Paused",
            self.CAT_FAILED: "✖ Failed",
            self.CAT_MEDIA: "🎬 Media Streams",
            self.CAT_DIRECT: "📦 Direct Files",
        }

        for cat_id, count in counts.items():
            if cat_id in self._category_items:
                self._category_items[cat_id].setText(0, f"{titles[cat_id]} ({count})")

    def _apply_category_filter(self) -> None:
        cat = self._current_category
        tasks = {t.id: t for t in self.queue_manager.get_all_tasks()}

        for row in range(self.table.rowCount()):
            item = self.table.item(row, TaskTableWidget.COL_FILENAME)
            if not item:
                continue
            tid = item.data(Qt.UserRole)
            task = tasks.get(tid)
            if not task:
                continue

            visible = True
            if cat == self.CAT_DOWNLOADING:
                visible = task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.CONNECTING)
            elif cat == self.CAT_QUEUED:
                visible = task.status == DownloadStatus.QUEUED
            elif cat == self.CAT_COMPLETED:
                visible = task.status == DownloadStatus.COMPLETED
            elif cat == self.CAT_PAUSED:
                visible = task.status == DownloadStatus.PAUSED
            elif cat == self.CAT_FAILED:
                visible = task.status == DownloadStatus.FAILED
            elif cat == self.CAT_MEDIA:
                visible = task.download_type == DownloadType.MEDIA_STREAM
            elif cat == self.CAT_DIRECT:
                visible = task.download_type == DownloadType.DIRECT_HTTP

            self.table.setRowHidden(row, not visible)

    def _on_resume_clicked(self) -> None:
        tid = self.table.get_selected_task_id()
        if tid:
            self.queue_manager.resume_task(tid)
        else:
            self.queue_manager.resume_all()

    def _on_pause_clicked(self) -> None:
        tid = self.table.get_selected_task_id()
        if tid:
            self.queue_manager.pause_task(tid)
        else:
            self.queue_manager.pause_all()

    def _on_stop_clicked(self) -> None:
        tid = self.table.get_selected_task_id()
        if tid:
            self.queue_manager.cancel_task(tid)

    def _on_delete_clicked(self) -> None:
        tid = self.table.get_selected_task_id()
        if not tid:
            return

        res = QMessageBox.question(
            self,
            "Confirm Delete",
            "Are you sure you want to delete this download task?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if res == QMessageBox.Yes:
            self.queue_manager.delete_task(tid, delete_file=False)

    def _open_settings_dialog(self) -> None:
        dlg = SettingsDialog(self, self.config)
        if dlg.exec():
            self._apply_theme()
            self.clipboard_monitor.set_enabled(self.config.clipboard_monitor)
            if self.config.clipboard_monitor:
                self.clipboard_monitor.start()
            else:
                self.clipboard_monitor.stop()

            self.queue_manager.set_speed_limit(self.config.speed_limit_bytes_per_sec)
            self.queue_manager.set_max_concurrent(self.config.max_concurrent_downloads)
            self.lbl_status_clipboard.setText("Clipboard: ON" if self.config.clipboard_monitor else "Clipboard: OFF")

    def _open_binary_dialog(self) -> None:
        dlg = BinaryManagerDialog(self, self.config)
        dlg.exec()
        self._update_binary_status_bar()

    def _update_binary_status_bar(self) -> None:
        bm = self.queue_manager.binary_manager
        yt = bm.get_yt_dlp_info()
        ff = bm.get_ffmpeg_info()

        yt_text = "yt-dlp: Ready" if yt.is_available else "yt-dlp: Missing"
        ff_text = "ffmpeg: Ready" if ff.is_available else "ffmpeg: Missing"

        self.lbl_status_binaries.setText(f"Tools: {yt_text} | {ff_text}")

    def _apply_theme(self) -> None:
        theme = self.config.get("theme", "dark")
        self.setStyleSheet(get_theme_qss(theme))

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handles Windows minimize-to-tray on close if enabled."""
        if self.config.close_to_tray:
            event.ignore()
            self.hide()
            if self.config.get("notify_on_complete", True):
                self.tray_controller.notify(
                    "Apex Running in Background",
                    "Apex Download Manager will continue running in your Windows system tray.",
                )
        else:
            self.queue_manager.shutdown()
            event.accept()
