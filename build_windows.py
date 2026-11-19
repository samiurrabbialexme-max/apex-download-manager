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

    icon_path = project_root / "resources" / "icon.ico"

    pyinstaller_args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",  # Single standalone .exe (just download & double-click)
        "--windowed",  # Suppress console on Windows
        "--name",
        "ApexDownloadManager",
        f"--add-data={project_root / 'app'}{os.pathsep}app",
        f"--add-data={project_root / 'resources'}{os.pathsep}resources",
        "--collect-all",
        "yt_dlp",
        "--collect-all",
        "PySide6",
    ]

    if icon_path.exists():
        pyinstaller_args.extend(["--icon", str(icon_path)])

    pyinstaller_args.append(str(entry_point))

    print("[Build] Running command:")
    print(" ".join(pyinstaller_args))

    result = subprocess.run(pyinstaller_args)
    if result.returncode == 0:
        dist_file = project_root / "dist" / "ApexDownloadManager.exe"
        print("\n==================================================")
        print("BUILD SUCCESSFUL!")
        print(f"Standalone single executable created at: {dist_file}")
        print("Users can download and double-click this file directly without installing Python.")
        print("==================================================")
    else:
        print("\n[Build Error] Packaging failed with exit code:", result.returncode)
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
