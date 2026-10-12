$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
New-Item -ItemType Directory .tools -Force | Out-Null
if(!(Test-Path .tools/dotnet/dotnet.exe)){
    Invoke-WebRequest https://dot.net/v1/dotnet-install.ps1 -OutFile .tools/dotnet-install.ps1
    & .tools/dotnet-install.ps1 -Version 10.0.401 -InstallDir (Join-Path $root '.tools/dotnet') -NoPath
    if($LASTEXITCODE){throw '.NET installation failed'}
}
if(!(Test-Path .tools/uv/uv.exe)){
    Invoke-WebRequest https://releases.astral.sh/github/uv/releases/download/0.13.0/uv-x86_64-pc-windows-msvc.zip -OutFile .tools/uv.zip
    Expand-Archive .tools/uv.zip .tools/uv -Force
}
$env:UV_PYTHON_INSTALL_DIR=Join-Path $root '.tools/python'
& .tools/uv/uv.exe python install 3.12.15
if($LASTEXITCODE){throw 'Python install failed'}
if(!(Test-Path .venv/Scripts/python.exe)){& .tools/uv/uv.exe venv --python 3.12.15 .venv}
& .tools/uv/uv.exe pip sync --python .venv/Scripts/python.exe server/requirements-dev.lock
if($LASTEXITCODE){throw 'Python dependencies failed'}
if(!$env:JAVA_HOME){
    $java=Get-Command java -ErrorAction SilentlyContinue
    if($java){$env:JAVA_HOME=Split-Path (Split-Path $java.Source -Parent) -Parent}
}
if(!$env:JAVA_HOME -or !(Test-Path (Join-Path $env:JAVA_HOME 'bin/java.exe'))){
    Invoke-WebRequest https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse -OutFile .tools/jdk17.zip
    Expand-Archive .tools/jdk17.zip .tools/jdk17 -Force
    $env:JAVA_HOME=(Get-ChildItem .tools/jdk17 -Directory | Select-Object -First 1).FullName
}
$env:ANDROID_HOME=Join-Path $root '.tools/android-sdk'
if(!(Test-Path .tools/android-sdk/cmdline-tools/bin/sdkmanager.bat)){
    Invoke-WebRequest https://dl.google.com/android/repository/commandlinetools-win-13114758_latest.zip -OutFile .tools/android-tools.zip
    Expand-Archive .tools/android-tools.zip .tools/android-sdk -Force
}
1..20 | ForEach-Object {'y'} | & .tools/android-sdk/cmdline-tools/bin/sdkmanager.bat --sdk_root=$env:ANDROID_HOME 'platform-tools' 'platforms;android-36' 'build-tools;36.0.0'
if($LASTEXITCODE){throw 'Android SDK installation failed'}
Write-Output "Ready. JAVA_HOME=$env:JAVA_HOME; ANDROID_HOME=$env:ANDROID_HOME. This session is configured; set these variables again in a new terminal."
