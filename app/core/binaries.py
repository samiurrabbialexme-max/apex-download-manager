"""Binary detector, path resolver, and automated installer for yt-dlp and ffmpeg."""
import io
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib.request import Request, urlopen

from app.config import BIN_DIR, Config


@dataclass
class BinaryInfo:
    name: str
    path: Optional[str]
    is_available: bool
    version: str = "Unknown"
    source: str = "missing"  # "system", "bundled", "python_lib", "missing"
    error: str = ""


class BinaryManager:
    """Manages detection, version verification, and automated downloads for external binaries."""

    YT_DLP_WIN_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    YT_DLP_LINUX_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
    
    # Gyan.dev official Windows release essentials build
    FFMPEG_WIN_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    FFMPEG_LINUX_TAR_URL = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.bin_dir = BIN_DIR
        self.is_windows = platform.system() == "Windows"

    def get_yt_dlp_info(self) -> BinaryInfo:
        """Resolves yt-dlp availability from custom path, bundled bin, system PATH, or python library."""
        exe_name = "yt-dlp.exe" if self.is_windows else "yt-dlp"

        # 1. Check custom path in settings
        custom_path = self.config.get("yt_dlp_custom_path", "")
        if custom_path and os.path.isfile(custom_path) and os.access(custom_path, os.X_OK):
            ver = self._get_binary_version(custom_path, ["--version"])
            return BinaryInfo(name="yt-dlp", path=custom_path, is_available=True, version=ver, source="custom")

        # 2. Check bundled binary in BIN_DIR
        bundled = self.bin_dir / exe_name
        if bundled.exists() and (self.is_windows or os.access(bundled, os.X_OK)):
            ver = self._get_binary_version(str(bundled), ["--version"])
            return BinaryInfo(name="yt-dlp", path=str(bundled), is_available=True, version=ver, source="bundled")

        # 3. Check system PATH
        system_exe = shutil.which("yt-dlp")
        if system_exe:
            ver = self._get_binary_version(system_exe, ["--version"])
            return BinaryInfo(name="yt-dlp", path=system_exe, is_available=True, version=ver, source="system")

        # 4. Check python library
        try:
            import yt_dlp
            ver = getattr(yt_dlp.version, "__version__", "Installed")
            return BinaryInfo(name="yt-dlp", path=sys.executable, is_available=True, version=ver, source="python_lib")
        except ImportError:
            pass

        return BinaryInfo(
            name="yt-dlp",
            path=None,
            is_available=False,
            version="Missing",
            source="missing",
            error="yt-dlp is not found on system PATH, bundled folder, or python environment.",
        )

    def get_ffmpeg_info(self) -> BinaryInfo:
        """Resolves ffmpeg availability from custom path, bundled bin, or system PATH."""
        exe_name = "ffmpeg.exe" if self.is_windows else "ffmpeg"

        # 1. Check custom path
        custom_path = self.config.get("ffmpeg_custom_path", "")
        if custom_path and os.path.isfile(custom_path) and os.access(custom_path, os.X_OK):
            ver = self._get_binary_version(custom_path, ["-version"])
            return BinaryInfo(name="ffmpeg", path=custom_path, is_available=True, version=ver, source="custom")

        # 2. Check bundled binary in BIN_DIR
        bundled = self.bin_dir / exe_name
        if bundled.exists() and (self.is_windows or os.access(bundled, os.X_OK)):
            ver = self._get_binary_version(str(bundled), ["-version"])
            return BinaryInfo(name="ffmpeg", path=str(bundled), is_available=True, version=ver, source="bundled")

        # 3. Check system PATH
        system_exe = shutil.which("ffmpeg")
        if system_exe:
            ver = self._get_binary_version(system_exe, ["-version"])
            return BinaryInfo(name="ffmpeg", path=system_exe, is_available=True, version=ver, source="system")

        return BinaryInfo(
            name="ffmpeg",
            path=None,
            is_available=False,
            version="Missing",
            source="missing",
            error="ffmpeg is required for audio/video muxing and high-quality YouTube 1080p+ downloads.",
        )

    def download_yt_dlp(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, str]:
        """Downloads official yt-dlp binary into bundled BIN_DIR."""
        target_name = "yt-dlp.exe" if self.is_windows else "yt-dlp"
        url = self.YT_DLP_WIN_URL if self.is_windows else self.YT_DLP_LINUX_URL
        target_path = self.bin_dir / target_name

        try:
            self._download_file(url, target_path, progress_callback)
            if not self.is_windows:
                target_path.chmod(0o755)
            return True, f"Successfully downloaded yt-dlp to {target_path}"
        except Exception as e:
            return False, f"Failed to download yt-dlp: {e}"

    def download_ffmpeg(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, str]:
        """Downloads and extracts ffmpeg into BIN_DIR for Windows or Linux."""
        try:
            if self.is_windows:
                temp_zip = self.bin_dir / "ffmpeg_temp.zip"
                self._download_file(self.FFMPEG_WIN_ZIP_URL, temp_zip, progress_callback)

                # Extract ffmpeg.exe and ffprobe.exe
                with zipfile.ZipFile(temp_zip, "r") as z:
                    for member in z.namelist():
                        filename = os.path.basename(member)
                        if filename.lower() in ("ffmpeg.exe", "ffprobe.exe"):
                            source = z.open(member)
                            target = open(self.bin_dir / filename, "wb")
                            with source, target:
                                shutil.copyfileobj(source, target)

                if temp_zip.exists():
                    temp_zip.unlink()
            else:
                import tarfile
                temp_tar = self.bin_dir / "ffmpeg_temp.tar.xz"
                self._download_file(self.FFMPEG_LINUX_TAR_URL, temp_tar, progress_callback)

                with tarfile.open(temp_tar, "r:xz") as tar:
                    for member in tar.getmembers():
                        filename = os.path.basename(member.name)
                        if filename in ("ffmpeg", "ffprobe"):
                            member.name = filename
                            tar.extract(member, path=self.bin_dir)

                if temp_tar.exists():
                    temp_tar.unlink()

                ffmpeg_bin = self.bin_dir / "ffmpeg"
                ffprobe_bin = self.bin_dir / "ffprobe"
                if ffmpeg_bin.exists():
                    ffmpeg_bin.chmod(0o755)
                if ffprobe_bin.exists():
                    ffprobe_bin.chmod(0o755)

            return True, f"Successfully installed ffmpeg to {self.bin_dir}"
        except Exception as e:
            return False, f"Failed to install ffmpeg: {e}"

    def _download_file(
        self,
        url: str,
        dest: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        headers = {"User-Agent": self.config.user_agent}
        req = Request(url, headers=headers)
        temp_dest = dest.with_suffix(".downloading")

        with urlopen(req, timeout=30) as resp, open(temp_dest, "wb") as out_file:
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 64 * 1024

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size > 0:
                    progress_callback(downloaded, total_size)

        temp_dest.replace(dest)

    def _get_binary_version(self, path: str, args: list) -> str:
        try:
            creationflags = 0
            if self.is_windows:
                creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

            res = subprocess.run(
                [path] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
                creationflags=creationflags,
            )
            out = (res.stdout or res.stderr).strip()
            first_line = out.splitlines()[0] if out.splitlines() else "Available"
            return first_line[:40]
        except Exception:
            return "Available"
