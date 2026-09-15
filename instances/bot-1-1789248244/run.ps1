$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Python launcher (py) was not found. Install Python 3.12+ first.' }
if (-not (Test-Path '.venv')) { py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path '.env')) { & .\.venv\Scripts\python.exe setup.py }
& .\.venv\Scripts\python.exe -m py_compile main.py config.py pasarguard.py
Get-ChildItem database\*.py | ForEach-Object { & .\.venv\Scripts\python.exe -m py_compile $_.FullName }
Get-ChildItem keyboards\*.py | ForEach-Object { & .\.venv\Scripts\python.exe -m py_compile $_.FullName }
& .\.venv\Scripts\python.exe test_project.py
& .\.venv\Scripts\python.exe main.py
