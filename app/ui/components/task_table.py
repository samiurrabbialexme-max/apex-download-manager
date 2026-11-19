"""Interactive download task table with real-time progress bars, speed, and context actions."""
import datetime
import os
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QMessageBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
)

from app.core.models import DownloadStatus, DownloadTask


class TaskTableWidget(QTableWidget):
    """Custom table view displaying download tasks with IDM-like progress and control."""

    COL_FILENAME = 0
    COL_SIZE = 1
    COL_PROGRESS = 2
    COL_SPEED = 3
    COL_ETA = 4
    COL_STATUS = 5
    COL_ADDED = 6

    # Action signals to controller
    pause_requested = Signal(str)
    resume_requested = Signal(str)
    retry_requested = Signal(str)
    delete_requested = Signal(str, bool)  # task_id, delete_file_on_disk
    open_file_requested = Signal(str)
    open_folder_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task_id_to_row: Dict[str, int] = {}
        self._row_to_task_id: Dict[int, str] = {}
        self._task_cache: Dict[str, DownloadTask] = {}

        self._setup_table()

    def _setup_table(self) -> None:
        headers = ["File Name", "Size", "Progress", "Speed", "ETA", "Status", "Date Added"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)

        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)

        header = self.horizontalHeader()
        header.setSectionResizeMode(self.COL_FILENAME, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_SIZE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_PROGRESS, QHeaderView.Fixed)
        self.setColumnWidth(self.COL_PROGRESS, 180)
        header.setSectionResizeMode(self.COL_SPEED, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_ETA, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_ADDED, QHeaderView.ResizeToContents)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemDoubleClicked.connect(self._on_double_click)

    def update_or_add_task(self, task: DownloadTask) -> None:
        """Adds a new row or updates existing row for the given task."""
        self._task_cache[task.id] = task

        if task.id in self._task_id_to_row:
            row = self._task_id_to_row[task.id]
            self._update_row(row, task)
        else:
            row = self.rowCount()
            self.insertRow(row)
            self._task_id_to_row[task.id] = row
            self._row_to_task_id[row] = task.id
            self._init_row(row, task)

    def remove_task(self, task_id: str) -> None:
        """Removes a row from the table."""
        if task_id not in self._task_id_to_row:
            return
        row = self._task_id_to_row[task_id]
        self.removeRow(row)

        self._task_cache.pop(task_id, None)
        self._rebuild_row_mappings()

    def _rebuild_row_mappings(self) -> None:
        self._task_id_to_row.clear()
        self._row_to_task_id.clear()
        for r in range(self.rowCount()):
            item = self.item(r, self.COL_FILENAME)
            if item:
                tid = item.data(Qt.UserRole)
                if tid:
                    self._task_id_to_row[tid] = r
                    self._row_to_task_id[r] = tid

    def _init_row(self, row: int, task: DownloadTask) -> None:
        # File Name
        display_name = task.media_title if task.media_title else task.filename
        fn_item = QTableWidgetItem(display_name)
        fn_item.setData(Qt.UserRole, task.id)
        fn_item.setToolTip(f"{task.save_path}\nURL: {task.url}")
        self.setItem(row, self.COL_FILENAME, fn_item)

        # Size
        size_item = QTableWidgetItem(task.formatted_size)
        size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(row, self.COL_SIZE, size_item)

        # Progress Bar Widget
        pbar = QProgressBar()
        pbar.setRange(0, 100)
        pbar.setValue(int(task.progress_pct))
        pbar.setFormat(f"{task.progress_pct:.1f}%")
        self.setCellWidget(row, self.COL_PROGRESS, pbar)

        # Speed
        speed_item = QTableWidgetItem(task.formatted_speed)
        speed_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(row, self.COL_SPEED, speed_item)

        # ETA
        eta_item = QTableWidgetItem(task.formatted_eta)
        eta_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, self.COL_ETA, eta_item)

        # Status
        status_item = QTableWidgetItem(self._format_status(task))
        status_item.setTextAlignment(Qt.AlignCenter)
        if task.status == DownloadStatus.FAILED and task.error_message:
            status_item.setToolTip(f"Error: {task.error_message}\nDouble-click to view details, or right-click to Retry.")
        self.setItem(row, self.COL_STATUS, status_item)

        # Date Added
        dt = datetime.datetime.fromtimestamp(task.created_at).strftime("%Y-%m-%d %H:%M")
        added_item = QTableWidgetItem(dt)
        added_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, self.COL_ADDED, added_item)

    def _update_row(self, row: int, task: DownloadTask) -> None:
        display_name = task.media_title if task.media_title else task.filename
        fn_item = self.item(row, self.COL_FILENAME)
        if fn_item and fn_item.text() != display_name:
            fn_item.setText(display_name)

        size_item = self.item(row, self.COL_SIZE)
        if size_item:
            size_item.setText(task.formatted_size)

        pbar = self.cellWidget(row, self.COL_PROGRESS)
        if isinstance(pbar, QProgressBar):
            pbar.setValue(int(task.progress_pct))
            pbar.setFormat(f"{task.progress_pct:.1f}%")

        speed_item = self.item(row, self.COL_SPEED)
        if speed_item:
            speed_item.setText(task.formatted_speed)

        eta_item = self.item(row, self.COL_ETA)
        if eta_item:
            eta_item.setText(task.formatted_eta)

        status_item = self.item(row, self.COL_STATUS)
        if status_item:
            status_item.setText(self._format_status(task))
            if task.status == DownloadStatus.FAILED and task.error_message:
                status_item.setToolTip(f"Error: {task.error_message}\nDouble-click to view details, or right-click to Retry.")
            else:
                status_item.setToolTip("")

    def _format_status(self, task: DownloadTask) -> str:
        s = task.status
        if s == DownloadStatus.DOWNLOADING:
            return "⬇ Downloading"
        elif s == DownloadStatus.CONNECTING:
            return "🔄 Connecting"
        elif s == DownloadStatus.QUEUED:
            return "⏳ Queued"
        elif s == DownloadStatus.PAUSED:
            return "⏸ Paused"
        elif s == DownloadStatus.COMPLETED:
            return "✔ Completed"
        elif s == DownloadStatus.FAILED:
            return "✖ Failed"
        elif s == DownloadStatus.CANCELED:
            return "⏹ Canceled"
        return s.value.capitalize()

    def get_selected_task_id(self) -> Optional[str]:
        selected_rows = self.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        return self._row_to_task_id.get(row)

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        if not item:
            return
        row = item.row()
        task_id = self._row_to_task_id.get(row)
        if not task_id:
            return

        task = self._task_cache.get(task_id)
        if not task:
            return

        menu = QMenu(self)

        # Context actions based on state
        if task.status.can_pause:
            act_pause = menu.addAction("⏸ Pause Download")
            act_pause.triggered.connect(lambda: self.pause_requested.emit(task_id))
        elif task.status.can_resume:
            act_resume = menu.addAction("▶ Resume Download")
            act_resume.triggered.connect(lambda: self.resume_requested.emit(task_id))

        if task.status == DownloadStatus.FAILED:
            act_error = menu.addAction("ℹ View Error Details")
            act_error.triggered.connect(lambda: self._show_error_dialog(task))
            act_retry = menu.addAction("🔄 Retry Download")
            act_retry.triggered.connect(lambda: self.retry_requested.emit(task_id))

        menu.addSeparator()

        file_exists = Path(task.save_path).exists()
        act_open_file = menu.addAction("📄 Open File")
        act_open_file.setEnabled(file_exists)
        act_open_file.triggered.connect(lambda: self._open_file(task.save_path))

        act_open_folder = menu.addAction("📁 Open Containing Folder")
        act_open_folder.triggered.connect(lambda: self._open_folder(task.save_path))

        menu.addSeparator()

        act_copy_link = menu.addAction("🔗 Copy Download Link")
        act_copy_link.triggered.connect(lambda: self._copy_link(task.url))

        menu.addSeparator()

        act_delete_task = menu.addAction("🗑 Remove from List")
        act_delete_task.triggered.connect(lambda: self.delete_requested.emit(task_id, False))

        act_delete_all = menu.addAction("❌ Delete File from Disk")
        act_delete_all.triggered.connect(lambda: self.delete_requested.emit(task_id, True))

        menu.exec(self.viewport().mapToGlobal(pos))

    def _on_double_click(self, item: QTableWidgetItem) -> None:
        row = item.row()
        task_id = self._row_to_task_id.get(row)
        if not task_id:
            return
        task = self._task_cache.get(task_id)
        if not task:
            return

        if task.status == DownloadStatus.COMPLETED:
            self._open_file(task.save_path)
        elif task.status == DownloadStatus.FAILED:
            self._show_error_dialog(task)
        elif task.status == DownloadStatus.PAUSED:
            self.resume_requested.emit(task_id)
        elif task.status == DownloadStatus.DOWNLOADING:
            self.pause_requested.emit(task_id)

    def _show_error_dialog(self, task: DownloadTask) -> None:
        msg = task.error_message or "Unknown download error."
        hint = ""
        if "ffmpeg" in msg.lower():
            hint = "\n\n💡 Tip: ffmpeg is required for merging separate 1080p+ video and audio streams. You can click 'Binaries' in the top toolbar to install ffmpeg, or click Retry to download the pre-merged stream."

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Download Error Details")
        box.setText(f"<b>Download Failed:</b> {task.filename}")
        box.setInformativeText(f"{msg}{hint}")
        btn_retry = box.addButton("🔄 Retry Download", QMessageBox.AcceptRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()

        if box.clickedButton() == btn_retry:
            self.retry_requested.emit(task.id)

    def _open_file(self, file_path: str) -> None:
        p = Path(file_path)
        if not p.exists():
            QMessageBox.warning(self, "File Not Found", f"The file no longer exists at:\n{file_path}")
            return

        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin":
                subprocess.run(["open", file_path])
            else:
                subprocess.run(["xdg-open", file_path])
        except Exception as e:
            QMessageBox.critical(self, "Error Opening File", f"Could not launch file:\n{e}")

    def _open_folder(self, file_path: str) -> None:
        p = Path(file_path)
        folder = p.parent if p.is_file() else p
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)

        system = platform.system()
        try:
            if system == "Windows":
                # Select file in Windows Explorer
                if p.exists():
                    subprocess.run(["explorer.exe", f"/select,{os.path.normpath(str(p))}"])
                else:
                    subprocess.run(["explorer.exe", os.path.normpath(str(folder))])
            elif system == "Darwin":
                subprocess.run(["open", "-R", str(p)])
            else:
                subprocess.run(["xdg-open", str(folder)])
        except Exception as e:
            QMessageBox.critical(self, "Error Opening Folder", f"Could not open directory:\n{e}")

    def _copy_link(self, url: str) -> None:
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(url)
