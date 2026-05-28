# _restart_server.ps1
$port = 8766
$proc = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($proc) {
    Stop-Process -Id $proc.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Process -FilePath "python" -ArgumentList "run_server.py" -WorkingDirectory $here -WindowStyle Hidden
Start-Sleep -Seconds 2
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -UseBasicParsing -TimeoutSec 5
    Write-Host "Server up: $($r.Content)"
} catch {
    Write-Host "Healthz failed: $_"
}
