@echo off
setlocal enabledelayedexpansion

for /d %%d in (D:\*QMT*) do (
    if exist "%%d\bin.x64\XtMiniQmt.exe" (
        set QMT_DIR=%%d
        goto :found
    )
)
:found
set PYTHONW=!QMT_DIR!\bin.x64\pythonw.exe
set BRIDGE=D:\qmt_bridge\qmt_bridge.py

echo ========================================
echo  QMT DingPan System
echo ========================================
echo.

tasklist /FI "IMAGENAME eq XtMiniQmt.exe" 2>NUL | find /I "XtMiniQmt.exe" >NUL
if ERRORLEVEL 1 (
    echo [..] Starting MiniQMT...
    start "" /MIN "!QMT_DIR!\bin.x64\XtMiniQmt.exe"
    echo.
    echo Please login in the MiniQMT window.
    echo After login, press any key to continue...
    echo.
    pause
) else (
    echo [OK] MiniQMT already running
    echo.
)

echo [..] Starting quote bridge (background, no window)...
start "" "!PYTHONW!" "!BRIDGE!"
timeout /T 3 /NOBREAK >NUL
echo [OK] Bridge running on port 8890
echo.

echo ========================================
echo  All Ready
echo ========================================
echo  MiniQMT:   running (tray)
echo  Bridge:    http://localhost:8890
echo  Dashboard: http://192.168.101.3:8891
echo ========================================
echo.
echo Press any key to open dashboard...
pause >NUL
start http://192.168.101.3:8891
