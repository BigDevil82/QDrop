param([string]$KeyDirectory = (Join-Path $env:LOCALAPPDATA 'QDropSigning'))
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
$KeyDirectory=[IO.Path]::GetFullPath($KeyDirectory)
if($KeyDirectory.Equals($root,[StringComparison]::OrdinalIgnoreCase) -or $KeyDirectory.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Signing keys must stay outside the repository'}
$keytool=if($env:JAVA_HOME){Join-Path $env:JAVA_HOME 'bin/keytool.exe'}else{'keytool'}
New-Item -ItemType Directory -Path $KeyDirectory -Force | Out-Null
$key=Join-Path $KeyDirectory 'release.jks'
$passwordFile=Join-Path $KeyDirectory 'password.dpapi'
if(!(Test-Path $key)){
    if(Test-Path $passwordFile){throw 'Key missing but password exists: restore key backup instead of creating a different identity'}
    $password=[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    $env:QDROP_STORE_PASSWORD=$password
    & $keytool -genkeypair -keystore $key -storepass:env QDROP_STORE_PASSWORD -keypass:env QDROP_STORE_PASSWORD -alias qdrop -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=QDrop Personal, O=Private'
    if($LASTEXITCODE){throw 'keytool failed'}
    $encrypted=[Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($password),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    [IO.File]::WriteAllBytes($passwordFile,$encrypted)
} else {
    $password=[Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($passwordFile),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))
}
$env:QDROP_KEYSTORE=$key
$env:QDROP_STORE_PASSWORD=$password
$env:QDROP_KEY_PASSWORD=$password
$env:QDROP_KEY_ALIAS='qdrop'
try {
    if(Test-Path .tools/android-sdk){$env:ANDROID_HOME=(Resolve-Path .tools/android-sdk).Path}
    $gradle=if(Test-Path .tools/gradle-8.13/bin/gradle.bat){(Resolve-Path .tools/gradle-8.13/bin/gradle.bat).Path}else{Join-Path $root 'android/gradlew.bat'}
    & $gradle -p android assembleRelease testReleaseUnitTest lintRelease --write-locks --console plain
    if($LASTEXITCODE){throw 'release build failed'}
    New-Item -ItemType Directory artifacts/android -Force | Out-Null
    Copy-Item android/app/build/outputs/apk/release/app-release.apk artifacts/android/QDrop-release.apk
    $apksigner=Join-Path $env:ANDROID_HOME 'build-tools/36.0.0/apksigner.bat'
    & $apksigner verify --verbose --print-certs artifacts/android/QDrop-release.apk
    if($LASTEXITCODE){throw 'APK signature verification failed'}
    Write-Output "Fixed signing key is outside repository: $key. Back up key and password securely; never regenerate for updates."
}finally{Remove-Item Env:QDROP_STORE_PASSWORD,Env:QDROP_KEY_PASSWORD,Env:QDROP_KEYSTORE,Env:QDROP_KEY_ALIAS -ErrorAction SilentlyContinue}
