# RcpsValuation 서비스 ACL 부여 — 현재 사용자에게 시작/중지/재시작 권한
# 관리자 권한으로 실행 필요 (우클릭 → "PowerShell로 실행" 안 되면 관리자 PowerShell에서 호출)

$sid = (New-Object System.Security.Principal.NTAccount("$env:USERDOMAIN\$env:USERNAME")).Translate([System.Security.Principal.SecurityIdentifier]).Value
Write-Host "현재 사용자 SID: $sid" -ForegroundColor Cyan

$sddl = "D:(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;RPWPCR;;;$sid)"

Write-Host "RcpsValuation 서비스 ACL 적용 중..." -ForegroundColor Yellow
& sc.exe sdset RcpsValuation $sddl

if ($LASTEXITCODE -eq 0) {
    Write-Host "성공! 이제 관리자 권한 없이도 서비스 제어 가능." -ForegroundColor Green
    Write-Host "검증 — 서비스 재시작 시도 중..." -ForegroundColor Yellow
    try {
        Restart-Service -Name RcpsValuation -Force -ErrorAction Stop
        Write-Host "재시작 성공. 5000번 포트에서 새 코드 동작 중." -ForegroundColor Green
    } catch {
        Write-Host "재시작 실패: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "ACL 적용 실패 (exit $LASTEXITCODE)" -ForegroundColor Red
}

Write-Host ""
Read-Host "엔터를 누르면 종료"
