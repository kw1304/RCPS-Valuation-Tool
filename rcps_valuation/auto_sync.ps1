# RCPS Valuation Tool 자동 동기화 스크립트
# 작업 스케줄러에서 10분마다 실행

$ErrorActionPreference = "SilentlyContinue"
$RepoDir = "C:\Claude\rcps_valuation"
$LogFile = "$RepoDir\auto_sync.log"

Set-Location (Split-Path $RepoDir)

# 현재 커밋 해시 저장
$beforeHash = git rev-parse HEAD 2>&1

# pull (안전: 머지 충돌 없는 fast-forward만)
$pullResult = git pull --ff-only origin master 2>&1

# 변경 있을 때만 서비스 재시작
$afterHash = git rev-parse HEAD 2>&1
if ($beforeHash -ne $afterHash) {
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 업데이트: $beforeHash → $afterHash" | Out-File $LogFile -Append
    Restart-Service RcpsValuation -Force
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 서비스 재시작 완료" | Out-File $LogFile -Append
}
