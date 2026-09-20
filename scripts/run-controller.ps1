#Requires -Version 7
<#
.SYNOPSIS
  제어부(FastAPI)를 실행한다.

.DESCRIPTION
  기본 접점은 루프백 주소다(implementation-baseline 2절). 상태 DB와 로그는
  `var\controller\` 에 만들어지며 커밋되지 않는다.
  `web\dist` 가 있으면 빌드된 화면을 같은 주소에서 서빙한다.
#>
[CmdletBinding()]
param(
    [string]$BindHost = '127.0.0.1',
    [int]$Port = 8765,
    [switch]$Reload
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw '.venv 가 없다. 먼저 scripts\bootstrap.ps1 을 실행한다.'
}

$env:PYTHONPATH = $repoRoot
$args = @('-m', 'uvicorn', 'controller.app:app', '--host', $BindHost, '--port', $Port)
if ($Reload) { $args += '--reload' }

Write-Host "제어부: http://${BindHost}:${Port}  (Ctrl+C 로 중지)" -ForegroundColor Green
& $python @args
