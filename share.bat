@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo ==========================================================
echo    Video AI Studio  -  외부에 공유하기
echo ==========================================================
echo.

call scripts\win_prepare.bat
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

echo.
where cloudflared >nul 2>nul
if errorlevel 1 (
    echo   [없음] cloudflared   외부 주소를 만드는 프로그램입니다
    echo.
    echo          명령창에서:  winget install --id Cloudflare.cloudflared
    echo.
    echo          또는 아래 파일을 받아 이 폴더에 두세요:
    echo          https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
    echo          받은 뒤 이름을 cloudflared.exe 로 바꿔주세요.
    echo.
    echo          설치 후에는 이 창을 닫고 다시 실행하세요.
    echo.
    pause
    exit /b 1
)
echo   [있음] cloudflared

REM ---- 접속 비밀번호 ----------------------------------------------------
REM Anyone with the link can reach this machine, so a password is required.
REM Read from SHARE_PASSWORD when already set, otherwise asked for here. The
REM frontend reads the same variable by inheritance (see below), and
REM frontend/middleware.ts turns the gate on whenever it is present.
if defined SHARE_PASSWORD (
    echo   [있음] 접속 비밀번호 ^(환경변수 SHARE_PASSWORD^)
) else (
    echo.
    echo   외부 공유에는 접속 비밀번호가 필요합니다.
    echo   손님이 주소를 열면 이 비밀번호를 물어봅니다.
    echo   ^(영문과 숫자로 만들어 주세요^)
    echo.
    set /p "SHARE_PASSWORD=   사용할 비밀번호: "
)

if not defined SHARE_PASSWORD (
    echo.
    echo   [중단] 비밀번호가 비어 있어 공유를 멈췄습니다.
    echo          비밀번호 없이 열면 주소를 아는 누구나 쓸 수 있습니다.
    echo.
    pause
    exit /b 1
)

set "TUNLOG=%TEMP%\vas_tunnel.log"
if exist "%TUNLOG%" del /q "%TUNLOG%" >nul 2>nul

echo.
echo   서버와 화면을 켭니다...
REM Both windows inherit SHARE_PASSWORD from this script, so the frontend starts
REM with the gate already on. The backend stays on 127.0.0.1 and is never
REM exposed directly — the tunnel only publishes the frontend.
start "Video AI Studio - 서버 (닫으면 중지)" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "Video AI Studio - 화면 (닫으면 중지)" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo   화면이 준비될 때까지 기다립니다...
timeout /t 16 /nobreak >nul

echo   외부 주소를 만듭니다. 최대 1분 정도 걸립니다...
REM Quick tunnel: no Cloudflare account needed. A fresh address each run.
start "Video AI Studio - 외부 주소 (닫으면 공유 중지)" cmd /c "cloudflared tunnel --url http://localhost:3000 > "%TUNLOG%" 2>&1"

REM PowerShell does the waiting and the matching in one go: a batch retry loop
REM around a nested for /f is easy to get subtly wrong.
set "SHAREURL="
for /f "usebackq delims=" %%u in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=$env:TUNLOG; for($i=0;$i -lt 40;$i++){ if(Test-Path $p){ $m=Select-String -Path $p -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1; if($m){ $m.Matches[0].Value; break } }; Start-Sleep -Seconds 2 }"`) do set "SHAREURL=%%u"

echo.
if not defined SHAREURL (
    echo ==========================================================
    echo   [실패] 외부 주소를 받지 못했습니다.
    echo.
    echo    - 인터넷 연결을 확인하세요.
    echo    - 회사나 학교 네트워크는 막아두는 경우가 있습니다.
    echo    - 자세한 기록:  %TUNLOG%
    echo ==========================================================
    echo.
    pause
    exit /b 1
)

echo ==========================================================
echo.
echo    손님에게 보낼 주소
echo.
echo        %SHAREURL%
echo.
echo    접속 비밀번호
echo.
echo        %SHARE_PASSWORD%
echo.
echo    아이디 칸은 아무 글자나 넣으면 됩니다 ^(비워두면 안 됩니다^).
echo.
echo ==========================================================
echo.
echo   알아두실 점
echo    - 주소는 실행할 때마다 새로 바뀝니다.
echo    - 검은 창 3개가 열려 있는 동안만 접속됩니다.
echo    - 끄려면 창 3개를 닫으면 됩니다.
echo    - 영상은 내 컴퓨터가 만듭니다. 공유 중에는 컴퓨터를 켜 두고
echo      절전/잠자기로 들어가지 않게 해주세요.
echo.
echo ==========================================================
echo.
pause
