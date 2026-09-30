@echo off
REM Shared setup for start.bat and share.bat.
REM Checks for the programs we need and installs project dependencies.
REM Never installs system software itself — it only says where to get it.
REM Returns exit code 1 when something is missing.

setlocal enabledelayedexpansion

echo   필요한 프로그램을 확인합니다...
echo.

set MISSING=0

where python >nul 2>nul
if errorlevel 1 (
    echo   [없음] Python
    echo          https://www.python.org/downloads/
    echo          설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
    set MISSING=1
) else (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   [있음] %%v
)

where node >nul 2>nul
if errorlevel 1 (
    echo   [없음] Node.js
    echo          https://nodejs.org/  ^(LTS 버튼^)
    set MISSING=1
) else (
    for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo   [있음] Node.js %%v
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo   [없음] ffmpeg   영상을 만드는 데 꼭 필요합니다
    echo          명령창에서:  winget install Gyan.FFmpeg
    echo          또는 https://www.gyan.dev/ffmpeg/builds/ 에서
    echo          ffmpeg-release-essentials.zip 을 받아 bin 폴더를 PATH 에 추가
    set MISSING=1
) else (
    echo   [있음] ffmpeg
)

if "!MISSING!"=="1" (
    echo.
    echo   ----------------------------------------------------------
    echo    위에 [없음] 으로 나온 프로그램을 먼저 설치해 주세요.
    echo    설치한 뒤에는 이 창을 닫고 새로 실행해야 인식됩니다.
    echo   ----------------------------------------------------------
    exit /b 1
)

echo.
echo   프로젝트 준비 상태를 확인합니다. 처음이면 몇 분 걸립니다...
echo.

if not exist "backend\.venv\Scripts\python.exe" (
    echo   - 서버 부품 설치 중
    python -m venv "backend\.venv"
    if errorlevel 1 (
        echo   [실패] Python 가상환경을 만들 수 없습니다.
        exit /b 1
    )
    "backend\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    "backend\.venv\Scripts\python.exe" -m pip install --quiet fastapi "uvicorn[standard]" pydantic pydantic-settings python-multipart httpx pillow gTTS
    if errorlevel 1 (
        echo   [실패] 서버 부품 설치 실패. 인터넷 연결을 확인하세요.
        exit /b 1
    )
) else (
    echo   - 서버 부품 준비됨
)

if not exist "frontend\node_modules" (
    echo   - 화면 부품 설치 중
    pushd frontend
    call npm install --no-fund --no-audit
    set NPMFAIL=!errorlevel!
    popd
    if not "!NPMFAIL!"=="0" (
        echo   [실패] 화면 부품 설치 실패. 인터넷 연결을 확인하세요.
        exit /b 1
    )
) else (
    echo   - 화면 부품 준비됨
)

if not exist "backend\.env" (
    echo.
    echo   [참고] 실제 영상 배경을 쓰려면 Pexels 키가 필요합니다.
    echo          backend\.env 파일을 만들고 다음 한 줄을 넣으세요.
    echo            PEXELS_API_KEY=발급받은키
    echo          키가 없어도 실행됩니다 ^(단색 배경이 쓰입니다^).
)

exit /b 0
