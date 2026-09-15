$ErrorActionPreference='Stop'
py -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
py bot.py
