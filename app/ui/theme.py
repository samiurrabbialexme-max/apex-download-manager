"""Modern IDM-inspired styling and QSS stylesheets."""

DARK_THEME_QSS = """
QMainWindow, QDialog {
    background-color: #1e1e24;
    color: #e0e0e0;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
    font-size: 13px;
}

QWidget {
    color: #e0e0e0;
    selection-background-color: #007acc;
    selection-color: #ffffff;
}

/* Toolbar */
QToolBar {
    background-color: #25252d;
    border-bottom: 1px solid #33333d;
    padding: 6px;
    spacing: 8px;
}

QToolButton {
    background-color: #2e2e38;
    color: #f0f0f0;
    border: 1px solid #3e3e4a;
    border-radius: 5px;
    padding: 6px 12px;
    font-weight: 600;
}

QToolButton:hover {
    background-color: #3b3b48;
    border-color: #007acc;
}

QToolButton:pressed {
    background-color: #005999;
}

/* Sidebar Tree / Categories */
QTreeWidget {
    background-color: #25252d;
    border: none;
    border-right: 1px solid #33333d;
    padding: 8px 4px;
    font-size: 13px;
}

QTreeWidget::item {
    padding: 6px 10px;
    border-radius: 4px;
    margin-bottom: 2px;
}

QTreeWidget::item:selected {
    background-color: #007acc;
    color: #ffffff;
    font-weight: 600;
}

QTreeWidget::item:hover:!selected {
    background-color: #2e2e38;
}

/* Main Table */
QTableWidget {
    background-color: #1e1e24;
    border: none;
    gridline-color: #2a2a35;
    selection-background-color: #264f78;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: #25252d;
    color: #a0a0b0;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #33333d;
    font-weight: 600;
    font-size: 12px;
}

QTableWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #25252d;
}

/* Progress Bar */
QProgressBar {
    border: 1px solid #3e3e4a;
    border-radius: 4px;
    background-color: #25252d;
    text-align: center;
    color: #ffffff;
    font-size: 11px;
    font-weight: 600;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #007acc, stop:1 #00b4d8);
    border-radius: 3px;
}

/* Inputs & Buttons */
QLineEdit, QSpinBox, QComboBox {
    background-color: #282832;
    border: 1px solid #3e3e4a;
    border-radius: 4px;
    padding: 6px 10px;
    color: #ffffff;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #007acc;
}

QPushButton {
    background-color: #007acc;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #008be3;
}

QPushButton:pressed {
    background-color: #005999;
}

QPushButton:disabled {
    background-color: #3a3a46;
    color: #70707c;
}

/* Status Bar */
QStatusBar {
    background-color: #25252d;
    border-top: 1px solid #33333d;
    color: #a0a0b0;
    font-size: 12px;
    padding: 4px;
}

/* Menu */
QMenu {
    background-color: #25252d;
    border: 1px solid #3e3e4a;
    padding: 4px;
}

QMenu::item {
    padding: 6px 20px;
    border-radius: 3px;
}

QMenu::item:selected {
    background-color: #007acc;
    color: #ffffff;
}
"""

LIGHT_THEME_QSS = """
QMainWindow, QDialog {
    background-color: #f5f6f8;
    color: #202020;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
    font-size: 13px;
}

QToolBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e1e4e8;
    padding: 6px;
    spacing: 8px;
}

QToolButton {
    background-color: #f1f3f5;
    color: #333333;
    border: 1px solid #d0d7de;
    border-radius: 5px;
    padding: 6px 12px;
    font-weight: 600;
}

QToolButton:hover {
    background-color: #e9ecef;
    border-color: #0969da;
}

QTreeWidget {
    background-color: #ffffff;
    border: none;
    border-right: 1px solid #e1e4e8;
    padding: 8px 4px;
}

QTreeWidget::item:selected {
    background-color: #0969da;
    color: #ffffff;
    font-weight: 600;
}

QTableWidget {
    background-color: #ffffff;
    border: none;
    gridline-color: #f0f2f5;
    selection-background-color: #dbeafe;
    selection-color: #1e3a8a;
}

QHeaderView::section {
    background-color: #f8fafc;
    color: #475569;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #e2e8f0;
    font-weight: 600;
}

QProgressBar {
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background-color: #e2e8f0;
    text-align: center;
    color: #0f172a;
    font-size: 11px;
    font-weight: 600;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #38bdf8);
    border-radius: 3px;
}

QPushButton {
    background-color: #0969da;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: 600;
}
"""


def get_theme_qss(theme_name: str = "dark") -> str:
    if theme_name == "light":
        return LIGHT_THEME_QSS
    return DARK_THEME_QSS
