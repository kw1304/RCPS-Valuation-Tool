$script = "$PSScriptRoot\auto_sync.ps1"

schtasks /create /tn "RcpsValuationAutoSync" `
  /tr "PowerShell.exe -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File `"$script`"" `
  /sc minute /mo 15 `
  /ru "$env:USERDOMAIN\$env:USERNAME" `
  /f 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ 자동 동기화 등록 완료 (15분 간격)" -ForegroundColor Green
    schtasks /run /tn "RcpsValuationAutoSync"
} else {
    Write-Host "❌ 등록 실패 — 관리자 권한으로 다시 실행하세요" -ForegroundColor Red
}
