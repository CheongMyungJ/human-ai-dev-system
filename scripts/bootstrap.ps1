#Requires -Version 7
<#
.SYNOPSIS
  개발용 사전 준비: 저장소 로컬 가상환경과 의존성 설치.

.DESCRIPTION
  런타임은 Python 3.12로 고정한다. `python` 과 `py` 런처의 기본 버전이 서로 다를 수 있어
  (이 PC: 3.12 대 3.14) 인터프리터를 `py -3.12` 로 명시한다.
  근거: p1-environment-contract.md 2절 주의 1, DEVELOPMENT.md P2-PLAN-01.

  사용자 전역 Python·Node·CLI 설정은 바꾸지 않는다. 설치 대상은
  저장소 아래 `.venv\` 와 `web\node_modules\` 뿐이며 둘 다 .gitignore 에 있다.
#>
[CmdletBinding()]
param(
    [switch]$SkipWeb
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host '== Python 3.12 가상환경 ==' -ForegroundColor Cyan
if (-not (Test-Path '.venv')) {
    py -3.12 -m venv .venv
}
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python --version

Write-Host '== Python 의존성 ==' -ForegroundColor Cyan
& $python -m pip install --disable-pip-version-check -r requirements.txt

if (-not $SkipWeb) {
    Write-Host '== 웹 UI 의존성과 빌드 ==' -ForegroundColor Cyan
    Push-Location (Join-Path $repoRoot 'web')
    try {
        npm install --no-fund --no-audit
        npm run build
    }
    finally {
        Pop-Location
    }
}

Write-Host ''
Write-Host '준비 완료. 다음 명령을 쓴다:' -ForegroundColor Green
Write-Host '  scripts\run-controller.ps1   제어부 실행 (기본 http://127.0.0.1:8765)'
Write-Host '  scripts\run-runner.ps1       로컬 Runner 실행'
Write-Host '  scripts\run-tests.ps1        전체 시험'
