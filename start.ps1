#Requires -Version 5.1
# SPDX-License-Identifier: Apache-2.0
<#
.SYNOPSIS
    Start J-Forecast Board and keep it running until Ctrl+C.
.DESCRIPTION
    Other settings come from JFB_* environment variables (docs/configuration.md).
    If scripts are blocked on this PC, double-click start.cmd instead.
.PARAMETER Model
    'timestral' (default) or 'stub': a stand-in that downloads nothing; its numbers are not forecasts.
.PARAMETER Port
    Port to listen on (default 8000).
.PARAMETER ListenAddress
    Address to listen on (default 127.0.0.1, this PC only).
.EXAMPLE
    .\start.ps1
.EXAMPLE
    .\start.ps1 -Model stub -Port 8010
#>
[CmdletBinding()]
param(
    [ValidateSet('timestral', 'stub')][string]$Model,
    [ValidateRange(1, 65535)][int]$Port,
    [string]$ListenAddress
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT) {
    $venvPython = Join-Path -Path $PSScriptRoot -ChildPath '.venv\Scripts\python.exe'
}
else {
    $venvPython = Join-Path -Path $PSScriptRoot -ChildPath '.venv/bin/python'
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'J-Forecast Board is not installed yet: run .\setup.ps1 (or setup.cmd) first.'
    exit 1
}

$arguments = @('-m', 'j_forecast_board', 'serve')
if ($Port) {
    $arguments += @('--port', [string]$Port)
}
if ($ListenAddress) {
    $arguments += @('--host', $ListenAddress)
}

$previous = @{ PYTHONUTF8 = $env:PYTHONUTF8; JFB_MODEL = $env:JFB_MODEL }
$env:PYTHONUTF8 = '1'
if ($Model) {
    $env:JFB_MODEL = $Model
}
try {
    Set-Location -LiteralPath $PSScriptRoot
    & $venvPython @arguments
    exit $LASTEXITCODE
}
finally {
    $env:PYTHONUTF8 = $previous.PYTHONUTF8
    $env:JFB_MODEL = $previous.JFB_MODEL
}
