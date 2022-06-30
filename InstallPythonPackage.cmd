@echo off
:: Arguments:
:: 1 - dev/regular (optional) to enable install in dev-mode
:: 2 - python-path (optional) path to custom python installation

if [%1]==[dev] (
    set DEVMODE=1
) else (
    set DEVMODE=0
)

if [%2]==[] (
    set PYTHON=python
) else (
    set "PYTHON=%2"
)

set PIP=%PYTHON% -m pip
set SOURCE_PATH=%~dp0python

echo Packing TestReportViewer_Template...
set "ZIP_SCRIPT=%~dp0python/openunrealautomation/zip.py"
set "ARCHIVE_SOURCE=%~dp0TestReportViewer_Template"
set "ARCHIVE_FILE=%~dp0python/openunrealautomation/resources/TestReportViewer_Template"
%PYTHON% %ZIP_SCRIPT% pack "%ARCHIVE_SOURCE%" "%ARCHIVE_FILE%"

if %DEVMODE%==1 (
    echo Installing in dev mode...
    %PIP% install -e %SOURCE_PATH%
) else (
    echo Installing in regular mode...
    %PIP% install %SOURCE_PATH%
)
