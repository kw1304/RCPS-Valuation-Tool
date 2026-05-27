# Update WatLanding service: python -m http.server  ->  python server.py (Flask + /api/rates)
$ErrorActionPreference = 'Continue'

$nssm = 'C:\Users\admin\AppData\Local\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win64\nssm.exe'
$py   = 'C:\Users\admin\AppData\Local\Python\bin\python.exe'

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host 'Need admin. Relaunching...' -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

Write-Host '==> WatLanding stop'
& $nssm stop WatLanding | Out-Null
Start-Sleep -Seconds 2

Write-Host '==> AppParameters update -> server.py'
& $nssm set WatLanding Application $py
& $nssm set WatLanding AppParameters 'server.py'
& $nssm set WatLanding AppDirectory 'C:\Claude\WAT'

# Optional: set ECOS_API_KEY here (uncomment + paste your key)
# & $nssm set WatLanding AppEnvironmentExtra 'ECOS_API_KEY=YOUR_KEY_HERE'

Write-Host '==> WatLanding start'
& $nssm start WatLanding
Start-Sleep -Seconds 3

Write-Host '=== Status ==='
sc.exe query WatLanding | Select-String 'STATE'
Write-Host ''
Write-Host 'Test: curl http://localhost:8765/healthz'
Read-Host 'Press Enter to close'
