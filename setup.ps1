#Requires -Version 5.1
# SPDX-License-Identifier: Apache-2.0
<#
.SYNOPSIS
    First-time setup on Windows: create .venv, install the pinned dependencies, check the result.
.DESCRIPTION
    Works in Windows PowerShell 5.1 and PowerShell 7. If scripts are blocked on this PC, run
    setup.cmd instead (double-click it), or:
        powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
.PARAMETER Python
    Path to the python.exe to use. Default: the newest Python 3.12 to 3.14 that is found.
.EXAMPLE
    .\setup.ps1
.EXAMPLE
    .\setup.ps1 -Python 'C:\Program Files\Python313\python.exe'
#>
[CmdletBinding()]
param(
    [string]$Python
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-WindowsPlatform {
    return [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
}

function Get-VenvPython {
    if (Test-WindowsPlatform) {
        return Join-Path -Path $PSScriptRoot -ChildPath '.venv\Scripts\python.exe'
    }
    return Join-Path -Path $PSScriptRoot -ChildPath '.venv/bin/python'
}

function Test-SupportedPython {
    param(
        [Parameter(Mandatory)][string]$Command,
        [string[]]$Arguments = @()
    )
    $check = 'import sys; sys.exit(0 if (3, 12) <= sys.version_info[:2] < (3, 15) else 1)'
    try {
        & $Command @Arguments -c $check 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Find-Python {
    param([string]$Requested)
    if ($Requested) {
        $candidates = @(, @($Requested))
    }
    else {
        $candidates = @(
            @('py', '-3.14'), @('py', '-3.13'), @('py', '-3.12'),
            @('python'), @('python3'), @('python3.14'), @('python3.13'), @('python3.12')
        )
    }
    foreach ($candidate in $candidates) {
        $command = $candidate[0]
        $arguments = @($candidate | Select-Object -Skip 1)
        if (-not (Get-Command -Name $command -ErrorAction SilentlyContinue)) {
            continue
        }
        if (Test-SupportedPython -Command $command -Arguments $arguments) {
            return [pscustomobject]@{ Command = $command; Arguments = $arguments }
        }
    }
    return $null
}

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    Write-Host ''
    Write-Host "== $Description"
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed (exit code $LASTEXITCODE)."
    }
}

Set-Location -LiteralPath $PSScriptRoot
$venvPython = Get-VenvPython

if (-not (Test-Path -LiteralPath $venvPython)) {
    $found = Find-Python -Requested $Python
    if ($null -eq $found) {
        Write-Host 'Python 3.12, 3.13 or 3.14 is needed.'
        Write-Host 'Install it from https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH"),'
        Write-Host 'or with: winget install Python.Python.3.13'
        Write-Host 'then open a new PowerShell window and run setup again.'
        exit 1
    }
    Invoke-Step -Description 'Creating the .venv folder' -Command $found.Command -Arguments ($found.Arguments + @('-m', 'venv', '.venv'))
}
elseif (-not (Test-SupportedPython -Command $venvPython)) {
    Write-Host 'The existing .venv uses an unsupported Python. Delete the .venv folder and run setup again.'
    exit 1
}

# pip also writes a detailed log, to read if an install step fails (e.g. behind a proxy)
$diagnostics = Join-Path -Path $PSScriptRoot -ChildPath 'diagnostics'
$null = New-Item -ItemType Directory -Path $diagnostics -Force
$pipLog = Join-Path -Path $diagnostics -ChildPath 'pip.log'
$pip = @('-m', 'pip', 'install', '--log', $pipLog)
Invoke-Step -Description 'Updating pip' -Command $venvPython -Arguments ($pip + @('--upgrade', 'pip'))
Invoke-Step -Description 'Installing the dependencies (about 1 GB the first time)' -Command $venvPython -Arguments ($pip + @('-r', 'requirements.txt'))
Invoke-Step -Description 'Installing J-Forecast Board' -Command $venvPython -Arguments ($pip + @('--no-deps', '--no-build-isolation', '--editable', '.'))

Write-Host ''
Write-Host 'Checking the installation. The first time this also downloads the public datasets.'
$previousUtf8 = $env:PYTHONUTF8
$env:PYTHONUTF8 = '1'
try {
    & $venvPython -m j_forecast_board doctor --no-model
    $doctorExit = $LASTEXITCODE
}
finally {
    $env:PYTHONUTF8 = $previousUtf8
}

Write-Host ''
if ($doctorExit -eq 0) {
    Write-Host 'Setup finished. Start the app with: .\start.ps1   (or double-click start.cmd)'
    exit 0
}
Write-Host 'Setup finished, but the check found problems: read diagnostics\doctor-report.txt.'
exit 1
