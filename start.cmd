@echo off
rem SPDX-License-Identifier: Apache-2.0
rem Double-click to run start.ps1, even where PowerShell scripts are blocked.
rem Options are passed on, for example: start.cmd -Model stub -Port 8010
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
