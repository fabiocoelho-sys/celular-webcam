# Instala (ou remove) a camera virtual "Celular Webcam". Pede administrador.
#   instalar-camera.ps1            -> instala/atualiza
#   instalar-camera.ps1 -Remover   -> remove
param([switch]$Remover, [string]$Origem = (Join-Path $PSScriptRoot 'bin'))

$ErrorActionPreference = 'Stop'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Origem', "`"$Origem`"")
    if ($Remover) { $argList += '-Remover' }
    $p = Start-Process powershell -Verb RunAs -ArgumentList $argList -Wait -PassThru
    exit $p.ExitCode
}

$destino = Join-Path $env:ProgramFiles 'CelularWebcam'
$dados = Join-Path $env:ProgramData 'CelularWebcam'
$log = Join-Path $dados 'instalacao.log'
New-Item -ItemType Directory -Force $dados | Out-Null
# O servico de cameras (LocalService) precisa escrever o log aqui
icacls $dados /grant '*S-1-5-19:(OI)(CI)M' '*S-1-5-32-545:(OI)(CI)M' | Out-Null
Start-Transcript -Path $log -Append | Out-Null

function Parar-ServicoCamera {
    foreach ($s in 'FrameServerMonitor', 'FrameServer') {
        Stop-Service $s -Force -ErrorAction SilentlyContinue
    }
}

try {
    if ($Remover) {
        if (Test-Path "$destino\vcamctl.exe") { & "$destino\vcamctl.exe" remove }
        Parar-ServicoCamera
        if (Test-Path "$destino\CelularWebcamSource.dll") { & regsvr32.exe /s /u "$destino\CelularWebcamSource.dll" }
        Remove-Item $destino -Recurse -Force -ErrorAction SilentlyContinue
        Write-Output 'Camera removida.'
        exit 0
    }

    New-Item -ItemType Directory -Force $destino | Out-Null
    # A DLL fica carregada no servico de cameras: para o servico antes de trocar
    Parar-ServicoCamera
    Copy-Item "$Origem\CelularWebcamSource.dll" $destino -Force
    Copy-Item "$Origem\vcamctl.exe" $destino -Force

    $r = Start-Process regsvr32.exe -ArgumentList '/s', "`"$destino\CelularWebcamSource.dll`"" -Wait -PassThru
    if ($r.ExitCode -ne 0) { throw "regsvr32 falhou ($($r.ExitCode))" }

    & "$destino\vcamctl.exe" install
    if ($LASTEXITCODE -ne 0) { throw "vcamctl falhou ($LASTEXITCODE)" }
    Write-Output 'Camera instalada.'
    exit 0
} catch {
    Write-Output "ERRO: $_"
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
