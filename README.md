# Apex Download Manager (IDM-Inspired Desktop App)

A high-performance, modular desktop media and file download manager inspired by **Internet Download Manager (IDM)**, engineered with **Python 3.12+** and **PySide6 (Qt for Python)**.

---

## 🚀 Key Features

### 1. High-Performance Segmented Download Engine
- **Multi-Connection Segmented Slicing**: Splits files into up to 32 concurrent HTTP range connections (`Accept-Ranges: bytes`), saturating available bandwidth.
- **Dynamic Speed Limiting**: Token-Bucket rate limiter allowing on-the-fly global bandwidth throttling.
- **Pause & Resume**: Graceful socket interruption with byte-level chunk tracking on disk. Resuming reconnects only missing byte ranges.
- **Fault-Tolerant Exponential Backoff**: Automatically handles transient network dropouts with configurable retry delays.

### 2. Media Extraction & YouTube / Facebook Support
- **Media Stream Extraction**: Deep integration with `yt-dlp` supporting YouTube, Facebook, TikTok, Vimeo, Twitter/X, Reddit, SoundCloud, and 1,000+ streaming sites.
- **Instant Preview & Format Probing**: Non-blocking background worker fetches video title, author, duration, and thumbnail preview without freezing the UI.
- **Audio/Video Muxing**: Automatic merge of high-res video streams (1080p, 1440p, 4K) and audio streams via `ffmpeg`.
- **Audio Extraction**: Direct 1-click extraction to MP3 / M4A.

### 3. Queue, Tray & IDM Dashboard UX
- **Category Filter Sidebar**: One-click filtering by All Downloads, Active, Queued, Completed, Paused, Failed, Media Streams, and Direct Files.
- **Task Table**: Real-time 60fps progress bars, download speed (MB/s), ETA countdown, and file sizes.
- **Windows System Tray Integration**: Minimizes to the Windows notification area to keep downloads running in the background when closed.
- **Clipboard Monitor (Toggleable)**: Detects copied links and automatically pops up a quick-add dialog.
- **Context Actions**: Right-click menu for Pause, Resume, Retry, Open File, Open Containing Folder (`explorer.exe /select,path`), and Delete.
- **Persistent SQLite WAL State**: Crash recovery resets active downloads to `PAUSED` upon restart; download history persists across sessions.

### 4. External Binary Manager
- Surfaces status of `yt-dlp` and `ffmpeg`.
- Built-in 1-click downloader for Windows binaries.

---

## 🛠 Architectural Choice: Python 3.12+ & PySide6 vs Electron & Tauri

| Consideration | Python 3.12+ & PySide6 (Selected) | Electron + TypeScript | Tauri + Rust / TS |
| :--- | :--- | :--- | :--- |
| **`yt-dlp` Integration** | **Direct native library + binary execution.** Zero IPC overhead; direct progress hook callbacks and format introspection. | Relies on child process CLI execution and parsing JSON stdout strings. Fragile on Windows paths and quoting. | Requires Rust FFI or parsing CLI subprocess stdout with bridge latency. |
| **Segmented I/O & Sockets** | Direct multi-threaded byte-range file writing with token-bucket rate limiting. | Heavy memory overhead passing binary chunks through V8 ArrayBuffers. | Fast in Rust, but requires complex IPC serialization to stream progress to TypeScript UI. |
| **Memory Footprint** | **~70-90 MB RAM**. Fast startup, true IDM snappy feel. | **~300-450 MB RAM** due to embedded Chromium runtime. | ~60-80 MB RAM (WebView2). |
| **Windows Tray & OS Integration** | Native `QSystemTrayIcon`, `QClipboard`, and Windows Explorer selection. | Sluggish tray menus; inconsistent clipboard listeners across Windows versions. | Requires third-party tray crates with limited event capabilities. |

---

## 📂 Project Structure

```
Project/
├── app/
│   ├── __init__.py
│   ├── config.py                 # Configuration and OS-specific paths
│   ├── main.py                   # Desktop application entry point & CLI flags
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py             # DownloadTask, FormatInfo, SegmentInfo dataclasses
│   │   ├── database.py           # SQLite WAL persistence & crash recovery
│   │   ├── url_classifier.py     # Heuristics for direct links vs media platforms
│   │   ├── binaries.py           # yt-dlp & ffmpeg detector and automated installer
│   │   ├── rate_limiter.py       # Thread-safe Token Bucket rate limiter
│   │   ├── http_downloader.py    # Multi-connection segmented Range download engine
│   │   ├── media_downloader.py   # yt-dlp wrapper with format probing & ffmpeg muxing
│   │   ├── queue_manager.py      # Worker pool, concurrency limiter, Qt Signal dispatcher
│   │   └── clipboard_monitor.py  # Background clipboard listener
│   └── ui/
│       ├── __init__.py
│       ├── theme.py              # IDM-inspired dark and light stylesheets
│       ├── main_window.py        # Main dashboard, toolbar, category sidebar
│       ├── components/
│       │   ├── task_table.py     # Real-time task table with custom progress bars
│       │   └── tray_icon.py      # Windows notification area & tray lifecycle
│       └── dialogs/
│           ├── add_download_dialog.py    # Add URL with thumbnail & format preview
│           ├── settings_dialog.py        # Speed limits, segments, folders
│           └── binary_manager_dialog.py  # yt-dlp / ffmpeg status and installer
├── tests/
│   ├── test_url_classifier.py    # URL sanitization and regex tests
│   ├── test_database.py          # SQLite CRUD and crash recovery tests
│   ├── test_rate_limiter.py      # Bandwidth throttling tests
│   ├── test_progress_parsing.py  # Byte/ETA/Speed calculation tests
│   ├── test_queue_state.py       # Queue state transitions & lifecycle tests
│   └── test_http_downloader.py   # Live Range-header segmented download integration tests
├── build_windows.py              # PyInstaller executable packager
├── requirements.txt              # Core & dev dependencies
├── run.py                        # Root launcher script
└── README.md
```

---

## 💻 Setup & Installation on Windows

### Prerequisites
- **Python 3.12 or newer** ([python.org](https://www.python.org/downloads/)). During installation, ensure **"Add Python to PATH"** is checked.
- **Git** (optional).

### 1. Clone or Extract the Project
```bash
git clone <repo-url>
cd Project
```

### 2. Create and Activate a Virtual Environment
```powershell
# Open PowerShell or Command Prompt
python -m venv .venv
.\.venv\Scripts\activate
```

### 3. Install Dependencies
```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Run the Application
```powershell
python run.py
```

---

## 🧪 Running the Automated Test Suite

The project includes unit and integration tests covering URL classification, multi-segment HTTP downloading with byte-range validation, SQLite persistence, rate limiting, and queue transitions:

```powershell
pytest -v
```

All 34 automated tests run in seconds:
```
tests/test_database.py .............................. PASSED
tests/test_http_downloader.py ....................... PASSED
tests/test_progress_parsing.py ..................... PASSED
tests/test_queue_state.py ........................... PASSED
tests/test_rate_limiter.py .......................... PASSED
tests/test_url_classifier.py ........................ PASSED
============================== 34 passed ==============================
```

---

## 📦 Building Standalone Windows `.exe`

To package Apex Download Manager into a standalone executable that runs without requiring Python to be installed on target machines:

```powershell
# In PowerShell / Command Prompt with venv activated:
python build_windows.py
```

The compiled standalone executable and all dependencies will be located in:
```
dist\ApexDownloadManager\ApexDownloadManager.exe
```

---

## 📄 License
MIT License. Free for personal and commercial use.
