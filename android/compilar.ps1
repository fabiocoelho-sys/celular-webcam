# Compila o app Android e copia o APK para a pasta apk/ do projeto.
#   compilar.ps1            -> so compila
#   compilar.ps1 -Instalar  -> compila e instala no celular conectado no cabo (depuracao USB ligada)
param([switch]$Instalar)
$ErrorActionPreference = 'Stop'

if (-not $env:JAVA_HOME -or -not (Test-Path "$env:JAVA_HOME\bin\java.exe")) {
    $jdk = Get-ChildItem "$env:ProgramFiles\Microsoft" -Directory -Filter 'jdk-17*' -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $jdk) { throw 'JDK 17 nao encontrado. Instale com: winget install Microsoft.OpenJDK.17' }
    $env:JAVA_HOME = $jdk.FullName
}
if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk" }
if (-not (Test-Path "$env:ANDROID_HOME\platforms")) { throw "Android SDK nao encontrado em $env:ANDROID_HOME (veja o NOTAS.md)" }

Push-Location $PSScriptRoot
try {
    & .\gradlew.bat assembleDebug --console=plain
    if ($LASTEXITCODE -ne 0) { throw 'Falha na compilacao' }
} finally {
    Pop-Location
}

$apkGerado = "$env:LOCALAPPDATA\celular-webcam-build\app\outputs\apk\debug\app-debug.apk"
$destino = Join-Path $PSScriptRoot '..\apk'
New-Item -ItemType Directory -Force $destino | Out-Null
Copy-Item $apkGerado (Join-Path $destino 'celular-webcam.apk') -Force
Write-Output "APK: $(Resolve-Path (Join-Path $destino 'celular-webcam.apk'))"

if ($Instalar) {
    $adb = "$env:ANDROID_HOME\platform-tools\adb.exe"
    & $adb install -r (Join-Path $destino 'celular-webcam.apk')
    & $adb shell am start -n com.fabio.celularwebcam/.MainActivity
}
