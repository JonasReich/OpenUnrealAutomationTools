@echo off
:: Arguments:
:: 1 - python-path (optional) path to custom python installation

if [%1]==[] (
    set PYTHON=python
) else (
    set "PYTHON=%1"
)

%PYTHON% -m pytest %SOURCE_PATH%
