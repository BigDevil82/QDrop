param([switch]$ReleaseAndroid)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
$dotnet=if(Test-Path .tools/dotnet/dotnet.exe){(Resolve-Path .tools/dotnet/dotnet.exe).Path}else{'dotnet'}
& $dotnet publish windows/QDrop.App/QDrop.App.csproj -c Release -r win-x64 --self-contained true -o artifacts/windows
if($LASTEXITCODE){throw 'Windows publish failed'}
if(Test-Path .tools/android-sdk){$env:ANDROID_HOME=(Resolve-Path .tools/android-sdk).Path}
Push-Location android
try {
    $task=if($ReleaseAndroid){'assembleRelease'}else{'assembleDebug'}
    & ./gradlew.bat $task testDebugUnitTest --console plain
    if($LASTEXITCODE){throw 'Android build failed'}
} finally {Pop-Location}
New-Item -ItemType Directory artifacts/android -Force | Out-Null
Copy-Item android/app/build/outputs/apk/debug/app-debug.apk artifacts/android/QDrop-debug.apk -ErrorAction SilentlyContinue
if($ReleaseAndroid){Copy-Item android/app/build/outputs/apk/release/app-release.apk artifacts/android/QDrop-release.apk}
Compress-Archive -Path artifacts/windows/* -DestinationPath artifacts/QDrop-windows-x64.zip -Force
Get-FileHash artifacts/android/*.apk,artifacts/QDrop-windows-x64.zip | Format-Table
