$ErrorActionPreference="Stop"
Set-Location $PSScriptRoot
if (!(Test-Path .env)) { Copy-Item .env.example .env }
py -m pip install -r requirements.txt
py bot.py
