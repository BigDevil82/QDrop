param([string]$Package = (Join-Path $PSScriptRoot '../artifacts/windows'), [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs/QDrop'))
$ErrorActionPreference = 'Stop'
$Package = (Resolve-Path -LiteralPath $Package).Path
if (!(Test-Path -LiteralPath (Join-Path $Package 'QDrop.App.exe'))) { throw 'Package missing QDrop.App.exe' }
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
Copy-Item -Path (Join-Path $Package '*') -Destination $Destination -Recurse -Force
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'QDrop.lnk'))
$shortcut.TargetPath = Join-Path $Destination 'QDrop.App.exe'
$shortcut.WorkingDirectory = $Destination
$shortcut.Save()
Write-Output "Installed: $Destination (launch QDrop.App.exe, enable startup in Settings if desired)"
