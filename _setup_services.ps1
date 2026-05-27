# WAT + JET Windows service installer (run as admin)
$ErrorActionPreference = 'Continue'

$nssm = 'C:\Users\admin\AppData\Local\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win64\nssm.exe'
$py   = 'C:\Users\admin\AppData\Local\Python\bin\python.exe'
$logs = 'C:\Claude\_service_logs'

if (-not (Test-Path $logs)) { New-Item -ItemType Directory -Force $logs | Out-Null }

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host 'Need admin. Relaunching...' -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

function Install-Svc($name, $display, $svcargs, $workdir) {
    Write-Host ('==> ' + $name) -ForegroundColor Cyan

    & $nssm stop $name 2>$null | Out-Null
    & $nssm remove $name confirm 2>$null | Out-Null

    & $nssm install $name $py $svcargs
    & $nssm set $name AppDirectory $workdir
    & $nssm set $name AppStdout ($logs + '\' + $name + '.log')
    & $nssm set $name AppStderr ($logs + '\' + $name + '.log')
    & $nssm set $name AppRotateFiles 1
    & $nssm set $name AppRotateOnline 1
    & $nssm set $name AppRotateBytes 10485760
    & $nssm set $name Start SERVICE_AUTO_START
    & $nssm set $name DisplayName $display
    & $nssm set $name AppExit Default Restart
    & $nssm set $name AppRestartDelay 3000

    & $nssm start $name
    Write-Host ('    ' + $name + ' started') -ForegroundColor Green
}

# kill existing 8765 / 5050 listeners
foreach ($port in 8765, 5050) {
    $pids = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).OwningProcess
    foreach ($p in $pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Seconds 1

Install-Svc 'WatLanding'   'WAT! Landing'   '-m http.server 8765' 'C:\Claude\WAT'
Install-Svc 'JetAutoTool'  'JET Auto Tool'  'run_server.py'        'C:\Claude\AUTO_JET_TOOL'

Write-Host ''
Write-Host '=== Status ===' -ForegroundColor Yellow
sc.exe query WatLanding  | Select-String 'STATE'
sc.exe query JetAutoTool | Select-String 'STATE'

Write-Host ''
Write-Host 'Check: http://localhost:8765/  http://localhost:5050/'
Write-Host 'Logs : C:\Claude\_service_logs\'
Write-Host ''
Read-Host 'Press Enter to close'
