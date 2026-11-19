"""Windows system tray icon integration, background persistence, and notifications."""
from typing import Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap, QPolygon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


def create_app_icon(size: int = 64) -> QIcon:
    """Generates a crisp programmatic application icon (IDM-inspired arrow)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Rounded background
    painter.setBrush(QColor("#007acc"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, size // 5, size // 5)

    # Downward arrow
    painter.setBrush(QColor("#ffffff"))
    w_half = size // 2
    h_third = size // 3

    # Arrow shaft
    painter.drawRect(w_half - size // 10, h_third - size // 8, size // 5, size // 3)

    # Arrow head
    poly = QPolygon([
        QPoint(size // 4, h_third + size // 6),
        QPoint(3 * size // 4, h_third + size // 6),
        QPoint(w_half, 3 * size // 4),
    ])
    painter.drawPolygon(poly)

    painter.end()
    return QIcon(pixmap)


class TrayController:
    """Manages system tray lifecycle, actions, and desktop notifications."""

    def __init__(self, parent_window: QWidget, queue_manager):
        self.window = parent_window
        self.queue_manager = queue_manager
        self.icon = create_app_icon()

        self.tray = QSystemTrayIcon(self.icon, self.window)
        self.tray.setToolTip("Apex Download Manager")

        self._setup_menu()
        self.tray.activated.connect(self._on_tray_activated)

        # Connect queue manager completion notifications
        self.queue_manager.task_completed.connect(self._on_task_completed)

        self.tray.show()

    def _setup_menu(self) -> None:
        menu = QMenu()

        act_show = menu.addAction("Open Apex Download Manager")
        act_show.triggered.connect(self.show_window)

        act_add = menu.addAction("Add New Download...")
        if hasattr(self.window, "open_add_dialog"):
            act_add.triggered.connect(self.window.open_add_dialog)

        menu.addSeparator()

        act_resume_all = menu.addAction("▶ Resume All")
        act_resume_all.triggered.connect(self.queue_manager.resume_all)

        act_pause_all = menu.addAction("⏸ Pause All")
        act_pause_all.triggered.connect(self.queue_manager.pause_all)

        menu.addSeparator()

        act_exit = menu.addAction("Exit Apex")
        act_exit.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.window.isVisible() and not self.window.isMinimized():
                self.window.hide()
            else:
                self.show_window()

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.activateWindow()
        self.window.raise_()

    def notify(self, title: str, message: str) -> None:
        if self.tray.isVisible():
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 4500)

    def _on_task_completed(self, task) -> None:
        if self.queue_manager.config.get("notify_on_complete", True):
            name = task.media_title if task.media_title else task.filename
            self.notify("Download Complete", f"Finished downloading: {name}")

    def quit_app(self) -> None:
        self.queue_manager.shutdown()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
