# MembersDownloader

An ultimate power-user GUI for `yt-dlp` designed for seamless members-only videos, livestreams, and bulk playlist downloads.

## Key Features
- **Pre-flight Cookie & Auth Tester:** One-click probe to verify your browser cookies and membership authorization against YouTube before running long queues.
- **Master Queue Progress & Real-time Filter:** Global progress bar, live speed/ETA aggregate banner, and instant search filter for URLs, titles, and download statuses.
- **Pre-flight Disk Space Checker:** Live disk space indicator with intelligent low-space warnings (< 2 GB) before launching batch queues.
- **File Integrity Guard:** Automated `ffprobe` duration verification ensures partial or corrupt media streams are never marked complete.
- **Archival Polish:** Preserves authentic YouTube upload dates (`--mtime`), embeds chapter markers (`--embed-chapters`), and injects high-resolution cover art into `.mp4` containers.
- **Zero-Clutter Auto-Merge:** Merges split video & audio streams automatically using FFmpeg with cover art and sweeps away loose `.webm`, `.part`, and temporary files.
- **Background Channel Watcher & Auto-Sync:** Monitors channels or playlists on scheduled intervals (15m to 12h), auto-downloading new member videos with native Windows toast alerts.
- **Audio Normalization:** Balanced sound levels using EBU R128 `loudnorm` standard.
- **Clipboard Monitor:** Silently watches clipboard from the system tray and auto-queues copied YouTube links.
- **Lifetime Analytics & History:** Detailed audit trail with instant re-queueing and one-click folder exploration.

## Installation & Running from Source
1. Clone or download this repository.
2. Double-click `install.bat` (installs Python requirements and sets up environment).
3. Double-click `start.bat` to launch the application.

## Building Standalone Executable (.exe)
You can package the entire application into a portable, standalone Windows `.exe` that runs without needing Python installed:
- Double-click `build.bat`, or run:
  ```bash
  python build_exe.py
  ```
- The compiled `.exe` will be saved in `dist/MembersDownloader.exe`.

## Requirements
- Python 3.10+
- FFmpeg (added to system PATH)
- Dependencies listed in `requirements.txt`

