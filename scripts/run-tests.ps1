#Requires -Version 7
<#
.SYNOPSIS
  전체 시험을 실행한다.

.DESCRIPTION
  제품 시험(pytest)과 P1의 OpenCode 계약 시험(unittest)을 모두 돌린다.
  두 묶음은 성격이 다르다. P1 계약 시험은 CLI를 실행하지 않는 문서 계약 시험이며
  OpenCode 실환경 검증이 아니다.

  UI-03 부터 **웹 빌드와 웹 단위 시험을 먼저** 돌린다. pytest 의 브라우저 시험
  (tests/test_web_shell.py)이 빌드된 web/dist 를 실제로 쓰기 때문이다 — 빌드가 소스보다
  오래됐으면 그 시험은 건너뛴다. -SkipWeb 으로 뺄 수 있다.
#>
[CmdletBinding()]
param([switch]$SkipP1, [switch]$SkipWeb)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw '.venv 가 없다. 먼저 scripts\bootstrap.ps1 을 실행한다.'
}

if (-not $SkipWeb) {
    Write-Host '== 웹 빌드·단위 시험 (npm) ==' -ForegroundColor Cyan
    Push-Location (Join-Path $repoRoot 'web')
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "웹 빌드 실패 (exit $LASTEXITCODE)" }
        npm test
        if ($LASTEXITCODE -ne 0) { throw "웹 단위 시험 실패 (exit $LASTEXITCODE)" }
    }
    finally {
        Pop-Location
    }
    Write-Host ''
}

Write-Host '== 제품 시험 (pytest) ==' -ForegroundColor Cyan
& $python -m pytest
if ($LASTEXITCODE -ne 0) { throw "pytest 실패 (exit $LASTEXITCODE)" }

if (-not $SkipP1) {
    Write-Host ''
    Write-Host '== P1 OpenCode 문서 계약 시험 (unittest, CLI 미실행) ==' -ForegroundColor Cyan
    & $python -m unittest discover -s p1/opencode -t p1/opencode
    if ($LASTEXITCODE -ne 0) { throw "P1 계약 시험 실패 (exit $LASTEXITCODE)" }
}

Write-Host ''
Write-Host '전체 시험 통과' -ForegroundColor Green
