# _restart_server.ps1
$port = 8766
# kill main listener + 모든 multiprocessing child (Windows reload 좀비 회피)
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    $parent_pid = $c.OwningProcess
    # child processes (multiprocessing fork) 먼저
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "parent_pid=$parent_pid" -or $_.ParentProcessId -eq $parent_pid
    } | ForEach-Object {
        Invoke-CimMethod -InputObject $_ -MethodName Terminate -ErrorAction SilentlyContinue | Out-Null
    }
    # parent
    Stop-Process -Id $parent_pid -Force -ErrorAction SilentlyContinue
    & taskkill /F /PID $parent_pid 2>&1 | Out-Null
}
Start-Sleep -Seconds 3
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Process -FilePath "python" -ArgumentList "run_server.py" -WorkingDirectory $here -WindowStyle Hidden
Start-Sleep -Seconds 3
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -UseBasicParsing -TimeoutSec 5
    Write-Host "Server up: $($r.Content)"
} catch {
    Write-Host "Healthz failed: $_"
}
