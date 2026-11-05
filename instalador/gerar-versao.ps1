# Gera uma versao para publicar: APK do Android + instalador do Windows.
#   powershell -File instalador\gerar-versao.ps1
# A versao vem do versionName em android/app/build.gradle.kts.
# Saida: %LOCALAPPDATA%\celular-webcam-build\versao\ (fora do OneDrive)
$ErrorActionPreference = 'Stop'
$raiz = Split-Path $PSScriptRoot -Parent
$gradle = Get-Content "$raiz\android\app\build.gradle.kts" -Raw
if ($gradle -notmatch 'versionName = "([\d.]+)"') { throw 'versionName nao encontrado' }
$versao = $Matches[1]
$saida = Join-Path $env:LOCALAPPDATA 'celular-webcam-build\versao'
$origem = Join-Path $saida 'arquivos'
Write-Output "== Celular Webcam $versao"
if (Test-Path $saida) { Remove-Item $saida -Recurse -Force }
New-Item -ItemType Directory -Force "$origem\apk", "$origem\adb", "$origem\vcam" | Out-Null

# 1) App Android (release)
Write-Output '== APK'
if (-not $env:JAVA_HOME) {
    $env:JAVA_HOME = (Get-ChildItem "$env:ProgramFiles\Microsoft" -Directory -Filter 'jdk-17*' | Select-Object -First 1).FullName
}
if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk" }
Push-Location "$raiz\android"
try {
    & .\gradlew.bat assembleRelease --console=plain -q
    if ($LASTEXITCODE -ne 0) { throw 'falha no APK' }
} finally { Pop-Location }
$apk = "$env:LOCALAPPDATA\celular-webcam-build\app\outputs\apk\release\app-release.apk"
Copy-Item $apk "$origem\apk\celular-webcam.apk"
Copy-Item $apk "$saida\CelularWebcam-$versao.apk"

# 2) Camera virtual (compila se o Visual Studio estiver instalado; senao usa a ja compilada)
Write-Output '== Camera virtual'
cmd /c "`"$raiz\pc\vcam\compilar.bat`" >nul 2>nul"
Copy-Item "$raiz\pc\vcam\bin\CelularWebcamSource.dll", "$raiz\pc\vcam\bin\vcamctl.exe" "$origem\vcam"

# 3) adb (modo cabo USB)
$adbOrigem = if (Test-Path "$raiz\pc\adb\adb.exe") { "$raiz\pc\adb" } else { "$env:ANDROID_HOME\platform-tools" }
Copy-Item "$adbOrigem\adb.exe", "$adbOrigem\AdbWinApi.dll", "$adbOrigem\AdbWinUsbApi.dll" "$origem\adb"

# 4) Programa do PC em .exe (PyInstaller)
Write-Output '== Programa do PC'
$py = Join-Path $env:LOCALAPPDATA 'celular-webcam\venv\Scripts\python.exe'
$p = $versao.Split('.')
$verInfo = (Get-Content "$PSScriptRoot\versao.txt" -Raw -Encoding UTF8).Replace('{V1}', $p[0]).Replace('{V2}', $p[1]).Replace('{V3}', $p[2]).Replace('{VERSAO}', $versao)
$verArq = Join-Path $saida 'versao-exe.txt'
[System.IO.File]::WriteAllText($verArq, $verInfo, (New-Object System.Text.UTF8Encoding($false)))
& $py -m PyInstaller --noconfirm --clean --log-level WARN --windowed --name CelularWebcam `
    --icon "$raiz\icone\celular-webcam.ico" --version-file $verArq `
    --distpath "$saida\dist" --workpath "$saida\work" --specpath $saida `
    "$raiz\pc\app.py"
if ($LASTEXITCODE -ne 0) { throw 'falha no PyInstaller' }
Move-Item "$saida\dist\CelularWebcam" "$origem\programa"

# 5) Instalador (Inno Setup)
Write-Output '== Instalador'
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup nao encontrado (winget install JRSoftware.InnoSetup)' }
& $iscc /Q "/DVersao=$versao" "/DOrigem=$origem" "$PSScriptRoot\celular-webcam.iss"
if ($LASTEXITCODE -ne 0) { throw 'falha no Inno Setup' }

Get-ChildItem $saida -File | Where-Object { $_.Extension -in '.apk', '.exe' } |
    ForEach-Object { '{0}  ({1:N1} MB)' -f $_.FullName, ($_.Length / 1MB) }
