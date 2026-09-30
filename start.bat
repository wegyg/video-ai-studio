@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ==================================================
echo    Video AI Studio - 내 컴퓨터에서 실행하기
echo ==================================================
echo.
echo [1/3] 필요한 프로그램을 확인합니다...
echo.

set MISSING=0

REM ---------- Python ----------
where python >nul 2>nul
if errorlevel 1 (
    echo   [없음] Python
    echo          - https://www.python.org/downloads/ 에서 내려받아 설치하세요.
    echo          - 설치 첫 화면에서 "Add python.exe to PATH" 를 반드시 체크하세요.
    set MISSING=1
) else (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   [있음] %%v
)

REM ---------- Node.js ----------
where node >nul 2>nul
if errorlevel 1 (
    echo   [없음] Node.js
    echo          - https://nodejs.org/ 에서 LTS 버전을 내려받아 설치하세요.
    set MISSING=1
) else (
    for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo   [있음] Node.js %%v
)

REM ---------- ffmpeg ----------
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo   [없음] ffmpeg  ^(영상을 만드는 데 꼭 필요합니다^)
    echo          - https://www.gyan.dev/ffmpeg/builds/ 에서
    echo            "ffmpeg-release-essentials.zip" 을 내려받으세요.
    echo          - 압축을 풀고 안에 있는 bin 폴더를 시스템 PATH 에 추가하세요.
    echo          - 또는 명령창에서:  winget install Gyan.FFmpeg
    set MISSING=1
) else (
    echo   [있음] ffmpeg
)

echo.
if "!MISSING!"=="1" (
    echo --------------------------------------------------
    echo  위에 [없음] 으로 표시된 프로그램을 먼저 설치하세요.
    echo  설치를 마친 뒤 이 파일을 다시 실행하면 됩니다.
    echo  ^(설치 후에는 이 창을 닫고 새로 열어야 인식됩니다^)
    echo --------------------------------------------------
    echo.
    pause
    exit /b 1
)

echo [2/3] 처음 실행이면 준비 작업을 합니다. 몇 분 걸릴 수 있습니다...
echo.

if not exist "backend\.venv\Scripts\python.exe" (
    echo   - 서버 준비 중 ^(Python 패키지 설치^)
    python -m venv "backend\.venv"
    if errorlevel 1 (
        echo   [실패] Python 가상환경을 만들 수 없습니다.
        pause
        exit /b 1
    )
    "backend\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    "backend\.venv\Scripts\python.exe" -m pip install --quiet fastapi "uvicorn[standard]" pydantic pydantic-settings python-multipart httpx pillow gTTS
    if errorlevel 1 (
        echo   [실패] Python 패키지 설치에 실패했습니다. 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
) else (
    echo   - 서버 준비 완료 ^(이미 설치됨^)
)

if not exist "frontend\node_modules" (
    echo   - 화면 준비 중 ^(Node 패키지 설치^)
    pushd frontend
    call npm install --no-fund --no-audit
    popd
    if errorlevel 1 (
        echo   [실패] Node 패키지 설치에 실패했습니다. 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
) else (
    echo   - 화면 준비 완료 ^(이미 설치됨^)
)

if not exist "backend\.env" (
    echo.
    echo   [참고] 스톡 영상을 쓰려면 Pexels 키가 필요합니다.
    echo          backend\.env 파일을 만들고 아래 한 줄을 넣으세요:
    echo            PEXELS_API_KEY=발급받은키
    echo          키가 없어도 실행은 됩니다 ^(단색 배경이 사용됩니다^).
)

echo.
echo [3/3] 서버와 화면을 시작합니다...
echo.

start "Video AI Studio - 서버 (닫으면 중지됩니다)" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "Video AI Studio - 화면 (닫으면 중지됩니다)" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo   잠시 기다린 뒤 브라우저가 열립니다...
timeout /t 12 /nobreak >nul
start "" "http://localhost:3000"

echo.
echo ==================================================
echo  준비 완료!  브라우저에서 http://localhost:3000
echo.
echo  끄려면: 새로 열린 검은 창 2개를 닫으면 됩니다.
echo ==================================================
echo.
pause
