@echo off
rem SPDX-License-Identifier: Apache-2.0
rem Double-click to run setup.ps1, even where PowerShell scripts are blocked.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
