@echo off
chcp 65001 >nul
echo ========================================
echo   Smart Clipboard - Run
echo ========================================
echo.
echo Finding and killing old smart_clipboard process...
powershell -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*smart_clipboard*' } | ForEach-Object { Write-Host ('Killing PID: ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }" 2>nul
timeout /t 1 /nobreak >nul

echo Hotkey: Alt+Q to toggle window
echo Double-click tray icon to show
echo Right-click tray icon for settings
echo.
python smart_clipboard.py
