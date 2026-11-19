"""Build script to bundle Apex Download Manager into a standalone Windows .exe using PyInstaller."""
import os
import platform
import subprocess
import sys
from pathlib import Path


def build():
    print("==================================================")
    print("Building Apex Download Manager Standalone Executable")
    print(f"Platform: {platform.system()} {platform.machine()}")
    print(f"Python: {sys.version}")
    print("==================================================")

    # Ensure pyinstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("[Build] PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    project_root = Path(__file__).parent.resolve()
    entry_point = project_root / "run.py"

    pyinstaller_args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",  # Suppress console on Windows
        "--name",
        "ApexDownloadManager",
        f"--add-data={project_root / 'app'}{os.pathsep}app",
        "--collect-all",
        "yt_dlp",
        "--collect-all",
        "PySide6",
        str(entry_point),
    ]

    print("[Build] Running command:")
    print(" ".join(pyinstaller_args))

    result = subprocess.run(pyinstaller_args)
    if result.returncode == 0:
        dist_dir = project_root / "dist" / "ApexDownloadManager"
        print("\n==================================================")
        print("BUILD SUCCESSFUL!")
        print(f"Standalone application created at: {dist_dir}")
        print("==================================================")
    else:
        print("\n[Build Error] Packaging failed with exit code:", result.returncode)
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
