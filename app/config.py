"""Configuration manager and environment paths for Apex Download Manager."""
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Dict


def get_default_data_dir() -> Path:
    """Returns the OS-appropriate application data directory."""
    system = platform.system()
    if system == "Windows":
        app_data = os.environ.get("APPDATA")
        if app_data:
            base = Path(app_data)
        else:
            base = Path.home() / "AppData" / "Roaming"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    app_dir = base / "ApexDownloadManager"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_default_downloads_dir() -> Path:
    """Returns the standard user Downloads directory."""
    if platform.system() == "Windows":
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            p = Path(user_profile) / "Downloads"
            if p.exists():
                return p
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    return downloads_dir


DATA_DIR = get_default_data_dir()
BIN_DIR = DATA_DIR / "bin"
BIN_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "downloads.db"
CONFIG_PATH = DATA_DIR / "settings.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "max_concurrent_downloads": 3,
    "default_segments": 8,
    "speed_limit_bytes_per_sec": 0,  # 0 = unlimited
    "default_download_dir": str(get_default_downloads_dir()),
    "clipboard_monitor": True,
    "minimize_to_tray": True,
    "close_to_tray": True,
    "notify_on_complete": True,
    "auto_retry_count": 3,
    "retry_backoff_sec": 2.0,
    "yt_dlp_custom_path": "",
    "ffmpeg_custom_path": "",
    "theme": "dark",  # "dark", "light", "classic_idm"
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
}


class Config:
    """Persistent application settings manager."""

    def __init__(self, config_file: Path = CONFIG_PATH):
        self.config_file = config_file
        self._settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        """Loads settings from disk if available."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self._settings.update(saved)
            except Exception as e:
                print(f"[Config] Error loading settings from {self.config_file}: {e}")

    def save(self) -> None:
        """Saves current settings to disk atomically."""
        try:
            temp_file = self.config_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
            temp_file.replace(self.config_file)
        except Exception as e:
            print(f"[Config] Error saving settings to {self.config_file}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default if default is not None else DEFAULT_SETTINGS.get(key))

    def set(self, key: str, value: Any, auto_save: bool = True) -> None:
        self._settings[key] = value
        if auto_save:
            self.save()

    @property
    def max_concurrent_downloads(self) -> int:
        return int(self.get("max_concurrent_downloads", 3))

    @property
    def default_segments(self) -> int:
        return max(1, min(32, int(self.get("default_segments", 8))))

    @property
    def speed_limit_bytes_per_sec(self) -> int:
        return int(self.get("speed_limit_bytes_per_sec", 0))

    @property
    def default_download_dir(self) -> str:
        return str(self.get("default_download_dir", str(get_default_downloads_dir())))

    @property
    def clipboard_monitor(self) -> bool:
        return bool(self.get("clipboard_monitor", True))

    @property
    def close_to_tray(self) -> bool:
        return bool(self.get("close_to_tray", True))

    @property
    def user_agent(self) -> str:
        return str(self.get("user_agent", DEFAULT_SETTINGS["user_agent"]))
