#Requires -Version 7
<#
.SYNOPSIS
  로컬 Runner를 실행한다.

.DESCRIPTION
  Runner가 제어부에 먼저 연결한다. 수신 포트를 열지 않는다.
  원문·실행 원장·부수효과 기록은 `var\runner\<runner_id>\` 에 저장된다.

  P2-01의 실행기는 코딩 CLI가 아니다. Codex·Claude 연결은 P2-03에서 붙인다.
#>
[CmdletBinding()]
param(
    [string]$RunnerId = 'runner-local-1',
    [string]$ControllerUrl = 'http://127.0.0.1:8765'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw '.venv 가 없다. 먼저 scripts\bootstrap.ps1 을 실행한다.'
}

$env:PYTHONPATH = $repoRoot
$env:HADS_RUNNER_ID = $RunnerId
$env:HADS_CONTROLLER_URL = $ControllerUrl

Write-Host "Runner ${RunnerId} → ${ControllerUrl}  (Ctrl+C 로 중지)" -ForegroundColor Green
& $python -m runner.agent
