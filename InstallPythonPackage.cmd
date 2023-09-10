@echo off
:: Arguments:
:: 1 - dev/regular (optional) to enable install in dev-mode
:: 2 - python-path (optional) path to custom python installation

echo ARGS: %0 %*

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

if %DEVMODE%==1 (
    echo Installing in dev mode...
    @echo off
    %PIP% install -e %SOURCE_PATH%
    @echo on
) else (
    echo Installing in regular mode...
    @echo off
    %PIP% install %SOURCE_PATH%
    @echo on
)
