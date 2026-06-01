# _restart_server.ps1 — BC(8766) 재기동 (raw 기동, admin 불필요).
# 자동시작은 Startup 폴더 BC_Server.vbs(pythonw)가 담당. 이 스크립트는 코드 커밋 후
# git post-commit 훅이 호출해 8766 리스너를 교체한다.
# (NSSM 서비스 시도는 비admin 환경에서 StopPending 행·권한문제로 철회 — VBS/raw 채택.)
$port = 8766
# 기존 8766 리스너 + multiprocessing child 종료 (Windows reload 좀비 회피)
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    $parent_pid = $c.OwningProcess
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "parent_pid=$parent_pid" -or $_.ParentProcessId -eq $parent_pid
    } | ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate -ErrorAction SilentlyContinue | Out-Null }
    Stop-Process -Id $parent_pid -Force -ErrorAction SilentlyContinue
    & taskkill /F /PID $parent_pid 2>&1 | Out-Null
}
# pythonw(VBS 기동분)도 정리
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'BC_CONFIRMATION_TOOL.*run_server' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Process -FilePath 'python' -ArgumentList 'run_server.py' -WorkingDirectory $here -WindowStyle Hidden
Start-Sleep -Seconds 8
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -UseBasicParsing -TimeoutSec 8
    Write-Host "Server up: $($r.Content)"
} catch {
    Write-Host "Healthz failed (콜드스타트 더 필요): $_"
}
