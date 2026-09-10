"""
Build script to package MembersDownloader into a standalone Windows executable (.exe).
Supports both single-file portable (--onefile) and folder (--onedir) modes.
Usage:
    python build_exe.py           # Builds single portable exe by default
    python build_exe.py --onedir  # Builds folder distribution (fastest startup)
"""

import sys
import os
import subprocess

def main():
    print("=" * 60)
    print(" MembersDownloader - Standalone Executable Builder")
    print("=" * 60)

    base_dir = os.path.abspath(os.path.dirname(__file__))
    os.chdir(base_dir)

    mode = "--onefile"
    if "--onedir" in sys.argv:
        mode = "--onedir"
        print(">> Build Mode: Folder Distribution (--onedir)")
    else:
        print(">> Build Mode: Standalone Portable Single Executable (--onefile)")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        mode,
        "--windowed",
        "--name", "MembersDownloader",
        "--collect-all", "customtkinter",
        "--hidden-import", "pystray",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageDraw",
        "downloader.py"
    ]

    print(f">> Running PyInstaller command: {' '.join(cmd)}")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n" + "=" * 60)
        print(" [SUCCESS] Build completed successfully!")
        dist_path = os.path.join(base_dir, "dist")
        if mode == "--onefile":
            exe_path = os.path.join(dist_path, "MembersDownloader.exe")
            print(f" Standalone Executable: {exe_path}")
        else:
            print(f" Distribution Directory: {os.path.join(dist_path, 'MembersDownloader')}")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print(f" [ERROR] Build failed with exit code {result.returncode}")
        print("=" * 60)
        sys.exit(result.returncode)

if __name__ == "__main__":
    main()
