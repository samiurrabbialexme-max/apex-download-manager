"""Main application entry point for Apex Download Manager."""
import argparse
import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.config import Config
from app.core.database import Database
from app.core.queue_manager import QueueManager
from app.ui.components.tray_icon import create_app_icon
from app.ui.main_window import MainWindow


def parse_args():
    parser = argparse.ArgumentParser(description="Apex Media & File Download Manager (IDM-inspired)")
    parser.add_argument("--add", dest="url", help="URL to download immediately on launch", default="")
    parser.add_argument("--minimized", action="store_true", help="Start minimized to the system tray")
    return parser.parse_args()


def main():
    # Handle graceful Ctrl+C in terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    args = parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Apex Download Manager")
    app.setApplicationDisplayName("Apex Download Manager")
    app.setOrganizationName("Antigravity")
    app.setWindowIcon(create_app_icon())

    # Ensure tray icon continues running if last window is closed
    app.setQuitOnLastWindowClosed(False)

    config = Config()
    db = Database()
    queue_mgr = QueueManager(db=db, config=config)

    window = MainWindow(queue_manager=queue_mgr, config=config)

    if not args.minimized:
        window.show()

    if args.url:
        QTimer.singleShot(400, lambda: window.open_add_dialog(initial_url=args.url))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
