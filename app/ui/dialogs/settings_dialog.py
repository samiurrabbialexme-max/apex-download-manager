"""Application settings and configuration dialog."""
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.config import Config


class SettingsDialog(QDialog):
    """User preferences configuration dialog."""

    def __init__(self, parent=None, config: Optional[Config] = None):
        super().__init__(parent)
        self.config = config or Config()

        self.setWindowTitle("Apex Settings")
        self.resize(480, 420)
        self.setModal(True)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        form = QFormLayout()

        # Concurrent downloads
        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(1, 10)
        self.spin_concurrent.setValue(self.config.max_concurrent_downloads)
        form.addRow("Max Concurrent Downloads:", self.spin_concurrent)

        # Default segments
        self.spin_segments = QSpinBox()
        self.spin_segments.setRange(1, 32)
        self.spin_segments.setValue(self.config.default_segments)
        form.addRow("Default Multi-Part Segments:", self.spin_segments)

        # Global Speed Limit (KB/s)
        self.spin_speed_limit = QSpinBox()
        self.spin_speed_limit.setRange(0, 1000000)
        self.spin_speed_limit.setSingleStep(100)
        self.spin_speed_limit.setSuffix(" KB/s (0 = unlimited)")
        current_limit_kb = self.config.speed_limit_bytes_per_sec // 1024
        self.spin_speed_limit.setValue(current_limit_kb)
        form.addRow("Global Speed Limit:", self.spin_speed_limit)

        # Download directory
        dir_layout = QHBoxLayout()
        self.dir_input = QLineEdit(self.config.default_download_dir)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_dir)
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(btn_browse)
        form.addRow("Default Download Directory:", dir_layout)

        # Theme
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Dark", "Light"])
        current_theme = self.config.get("theme", "dark").capitalize()
        self.combo_theme.setCurrentText(current_theme)
        form.addRow("Theme:", self.combo_theme)

        layout.addLayout(form)

        # Checkboxes
        self.chk_clipboard = QCheckBox("Monitor clipboard for downloadable links & video URLs")
        self.chk_clipboard.setChecked(self.config.clipboard_monitor)
        layout.addWidget(self.chk_clipboard)

        self.chk_close_tray = QCheckBox("Close button minimizes to system tray instead of exiting")
        self.chk_close_tray.setChecked(self.config.close_to_tray)
        layout.addWidget(self.chk_close_tray)

        self.chk_notifications = QCheckBox("Show desktop notification on download completion")
        self.chk_notifications.setChecked(self.config.get("notify_on_complete", True))
        layout.addWidget(self.chk_notifications)

        layout.addStretch()

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("Save Settings")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._save)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)

    def _browse_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.dir_input.text())
        if chosen:
            self.dir_input.setText(chosen)

    def _save(self) -> None:
        self.config.set("max_concurrent_downloads", self.spin_concurrent.value(), auto_save=False)
        self.config.set("default_segments", self.spin_segments.value(), auto_save=False)
        self.config.set("speed_limit_bytes_per_sec", self.spin_speed_limit.value() * 1024, auto_save=False)
        self.config.set("default_download_dir", self.dir_input.text().strip(), auto_save=False)
        self.config.set("clipboard_monitor", self.chk_clipboard.isChecked(), auto_save=False)
        self.config.set("close_to_tray", self.chk_close_tray.isChecked(), auto_save=False)
        self.config.set("notify_on_complete", self.chk_notifications.isChecked(), auto_save=False)
        self.config.set("theme", self.combo_theme.currentText().lower(), auto_save=False)
        self.config.save()
        self.accept()
