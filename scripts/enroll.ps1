param([ValidateSet('enroll','devices','revoke','backup')][string]$Command='enroll',[string]$Value)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
$env:DATA_DIR=Join-Path $root 'data'
$env:PYTHONPATH=Join-Path $root 'server'
if($Value){& ./.venv/Scripts/python.exe -m app.cli $Command $Value}else{& ./.venv/Scripts/python.exe -m app.cli $Command}
exit $LASTEXITCODE
