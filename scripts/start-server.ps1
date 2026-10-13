param([int]$Port=8000, [string]$BindHost="127.0.0.1")
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
$env:DATA_DIR=Join-Path $root 'data'
$env:PYTHONPATH=Join-Path $root 'server'
& ./.venv/Scripts/python.exe -m alembic -c server/alembic.ini upgrade head
if($LASTEXITCODE){throw 'Migration failed'}
& ./.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir server --host $BindHost --port $Port --workers 1 --no-access-log --no-proxy-headers
exit $LASTEXITCODE
