@echo off
echo ========================================
echo   Smart Clipboard - Build EXE
echo ========================================
echo.

echo   [1/3] Installing project dependencies...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo   ERROR: Failed to install dependencies!
    pause
    exit /b 1
)
echo.

echo   [2/3] Installing PyInstaller...
python -m pip install pyinstaller
if %errorlevel% neq 0 (
    echo   ERROR: Failed to install PyInstaller!
    pause
    exit /b 1
)
echo.

echo   [3/3] Building EXE...
pyinstaller --noconfirm --onefile --windowed --name "SmartClipboard" smart_clipboard.py
if %errorlevel% neq 0 (
    echo   ERROR: Build failed!
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Done!
echo   Output: dist\SmartClipboard.exe
echo ========================================
pause
