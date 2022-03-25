@echo off

PowerShell "%~dp0CompileProject.ps1 -RootFolder %* *>&1 | Tee-Object -FilePath %~dp0Saved/Logs/Log.log"
