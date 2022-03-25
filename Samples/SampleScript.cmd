@echo off

set "LogDir=%~dp0../Saved/Logs"
PowerShell "if (-not (Test-Path '%LogDir%')) { New-Item -ItemType 'Directory' -Path '%LogDir%' }"
PowerShell "%~dp0SampleScript.ps1 -RootFolder %* *>&1 | Tee-Object -FilePath %LogDir%/Log.log"
