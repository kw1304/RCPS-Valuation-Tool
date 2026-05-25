# RCPS Valuation Tool — Windows 자동 셋업 스크립트
# 관리자 PowerShell 에서 실행:
#   irm https://raw.githubusercontent.com/kw1304/RCPS-Valuation-Tool/master/rcps_valuation/setup_windows.ps1 | iex

$ErrorActionPreference = "Continue"
$RepoUrl = "https://github.com/kw1304/RCPS-Valuation-Tool"
$InstallDir = "C:\Claude"
$PythonExe = ""

Write-Host "================================" -ForegroundColor Cyan
Write-Host "RCPS Valuation Tool 셋업 시작" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# 관리자 권한 확인
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "⚠️  관리자 PowerShell 에서 실행해주세요." -ForegroundColor Red
    Write-Host "    시작 → PowerShell 우클릭 → 관리자 권한으로 실행" -ForegroundColor Yellow
    exit 1
}

function Test-Cmd($cmd) { $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue) }

function Step($n, $msg) {
    Write-Host ""
    Write-Host "[$n] $msg" -ForegroundColor Green
    Write-Host ("-" * 60) -ForegroundColor DarkGray
}

# PATH 새로고침
function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
}

# ---------------------------------------------------------------------------
Step 1 "winget 확인"
if (-not (Test-Cmd "winget")) {
    Write-Host "❌ winget 미설치 — Windows 10/11 최신 업데이트 필요" -ForegroundColor Red
    exit 1
}
Write-Host "✅ winget OK"

# ---------------------------------------------------------------------------
Step 2 "Git 설치 확인"
if (Test-Cmd "git") {
    Write-Host "✅ git 이미 설치됨: $(git --version)"
} else {
    winget install --id Git.Git --accept-source-agreements --accept-package-agreements -h
    Refresh-Path
}

# ---------------------------------------------------------------------------
Step 3 "Python 3.11+ 설치"
$PythonExe = "C:\Users\$env:USERNAME\AppData\Local\Python\bin\python.exe"
if (Test-Path $PythonExe) {
    Write-Host "✅ 사용자 Python 발견: $PythonExe"
    & $PythonExe --version
} elseif ((Get-Command python -ErrorAction SilentlyContinue) -and (python --version 2>&1) -match "Python 3\.(1[1-9]|[2-9]\d)") {
    $PythonExe = (Get-Command python).Source
    Write-Host "✅ Python OK: $PythonExe"
} else {
    Write-Host "Python 3.11 설치 중..."
    winget install --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements -h
    Refresh-Path
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) { $PythonExe = "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python311\python.exe" }
}

# ---------------------------------------------------------------------------
Step 4 "Tailscale 설치"
if (Test-Cmd "tailscale") {
    Write-Host "✅ Tailscale 이미 설치됨: $(tailscale --version | Select-Object -First 1)"
} else {
    winget install --id Tailscale.Tailscale --accept-source-agreements --accept-package-agreements -h
    Refresh-Path
}

# ---------------------------------------------------------------------------
Step 5 "NSSM 설치 (서비스 매니저)"
if (Test-Cmd "nssm") {
    Write-Host "✅ NSSM 이미 설치됨"
} else {
    winget install --id NSSM.NSSM --accept-source-agreements --accept-package-agreements -h
    Refresh-Path
}

# ---------------------------------------------------------------------------
Step 6 "레포 클론 (C:\Claude)"
if (-not (Test-Path "$InstallDir\.git")) {
    if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir | Out-Null }
    Set-Location (Split-Path $InstallDir)
    git clone $RepoUrl (Split-Path $InstallDir -Leaf) 2>&1 | Write-Host
} else {
    Write-Host "✅ $InstallDir 이미 git 레포"
    Set-Location $InstallDir
    git pull origin master 2>&1 | Write-Host
}

# ---------------------------------------------------------------------------
Step 7 "Python 의존성 설치"
Set-Location "$InstallDir\rcps_valuation"
& $PythonExe -m pip install --upgrade pip 2>&1 | Select-Object -Last 3
& $PythonExe -m pip install -r requirements.txt 2>&1 | Select-Object -Last 5
Write-Host "✅ 의존성 설치 완료"

# ---------------------------------------------------------------------------
Step 8 "Windows 빠른 시작 OFF + 슬립 타이머 30분 (WoL 호환)"
try {
    Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power" -Name HiberbootEnabled -Value 0
    Write-Host "✅ 빠른 시작 OFF"
} catch { Write-Host "⚠️ 빠른 시작 설정 실패: $($_.Exception.Message)" }
powercfg /change standby-timeout-ac 30 2>&1 | Out-Null
Write-Host "✅ 슬립 타이머 30분 (AC)"

# ---------------------------------------------------------------------------
Step 9 "NSSM 서비스 등록 (RcpsValuation)"
$svcExists = (sc.exe query RcpsValuation 2>&1) -notmatch "does not exist"
if ($svcExists) {
    Write-Host "✅ 이미 등록됨 — 재시작만"
    Restart-Service RcpsValuation -Force -ErrorAction SilentlyContinue
} else {
    nssm install RcpsValuation $PythonExe "$InstallDir\rcps_valuation\run_server.py" 2>&1 | Out-Null
    nssm set RcpsValuation AppDirectory "$InstallDir\rcps_valuation" 2>&1 | Out-Null
    nssm set RcpsValuation Start SERVICE_AUTO_START 2>&1 | Out-Null
    nssm set RcpsValuation AppStdout "$InstallDir\rcps_valuation\service_stdout.log" 2>&1 | Out-Null
    nssm set RcpsValuation AppStderr "$InstallDir\rcps_valuation\service_stderr.log" 2>&1 | Out-Null
    nssm set RcpsValuation DisplayName "RCPS Valuation Tool" 2>&1 | Out-Null
    nssm start RcpsValuation 2>&1 | Out-Null
    Write-Host "✅ 서비스 등록 + 시작"
}
Start-Sleep 3
sc.exe query RcpsValuation | Select-String "STATE"

# ---------------------------------------------------------------------------
Step 10 "로컬 응답 테스트"
try {
    $r = (Invoke-WebRequest -Uri http://localhost:5000/healthz -UseBasicParsing -TimeoutSec 10).Content
    Write-Host "✅ /healthz : $r"
} catch {
    Write-Host "⚠️ 응답 없음 — 서비스 로그 확인: $InstallDir\rcps_valuation\service_stderr.log" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "셋업 완료" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "남은 수동 단계 (2가지):" -ForegroundColor Yellow
Write-Host ""
Write-Host "1) Tailscale 로그인 (브라우저 열림)" -ForegroundColor White
Write-Host "   tailscale up" -ForegroundColor Gray
Write-Host "   → 기존 kw1304@ 계정으로 로그인" -ForegroundColor Gray
Write-Host ""
Write-Host "2) Tailscale Funnel 활성화 (외부 접속용)" -ForegroundColor White
Write-Host "   tailscale funnel --bg 5000" -ForegroundColor Gray
Write-Host "   → 새 노드 권한 필요시 표시되는 URL 클릭해 승인" -ForegroundColor Gray
Write-Host ""
Write-Host "3) (선택) Claude CLI 설치 + 로그인" -ForegroundColor White
Write-Host "   https://claude.com/download" -ForegroundColor Gray
Write-Host "   설치 후: claude login (Claude Max 구독 같은 계정)" -ForegroundColor Gray
Write-Host ""
Write-Host "완료 후 노트북 Funnel URL 확인:" -ForegroundColor White
Write-Host "   tailscale status" -ForegroundColor Gray
Write-Host "   → 본인 노트북 이름.taild5874c.ts.net 형식" -ForegroundColor Gray
Write-Host ""
