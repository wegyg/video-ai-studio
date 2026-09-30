@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo ==========================================================
echo    Video AI Studio  -  내 컴퓨터에서만 사용
echo ==========================================================
echo.

call scripts\win_prepare.bat
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

echo.
echo   서버와 화면을 켭니다...
echo.

REM Local-only run, so no login. Cleared explicitly in case SHARE_PASSWORD is set
REM system-wide from an earlier share session — otherwise this would keep asking
REM for a password on a machine that is not sharing anything.
set "SHARE_PASSWORD="
REM Resolution stays at the 1080p default because a PC has the memory for it.
start "Video AI Studio - 서버 (닫으면 중지)" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "Video AI Studio - 화면 (닫으면 중지)" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo   준비되는 동안 잠시 기다립니다...
timeout /t 14 /nobreak >nul
start "" "http://localhost:3000"

echo.
echo ==========================================================
echo   준비 완료!   주소:  http://localhost:3000
echo.
echo   이 주소는 내 컴퓨터에서만 열립니다.
echo   다른 사람에게 보여주려면  share.bat  을 쓰세요.
echo.
echo   끄려면: 새로 열린 검은 창 2개를 닫으세요.
echo ==========================================================
echo.
pause
