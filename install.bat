@echo off
echo =======================================
echo MembersDownloader Setup
echo =======================================
echo.
echo Installing Python dependencies...
pip install -r requirements.txt
echo.
echo Checking for FFmpeg (Required for audio/video merging)...
winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
echo.
echo Setup Complete! You can now run start.bat
pause
