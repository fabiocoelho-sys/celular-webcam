# Cria o atalho "Celular Webcam" na area de trabalho desta maquina.
# O atalho fica fora do vault, entao cada maquina roda isto uma vez.
$ErrorActionPreference = 'Stop'

$venv = Join-Path $env:LOCALAPPDATA 'celular-webcam\venv'
$pythonw = Join-Path $venv 'Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Output 'Preparando o ambiente Python...'
    python -m venv $venv
    & (Join-Path $venv 'Scripts\python.exe') -m pip install -q --upgrade pip
    & (Join-Path $venv 'Scripts\python.exe') -m pip install -q -r (Join-Path $PSScriptRoot 'requirements.txt')
}

$atalho = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Celular Webcam.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($atalho)
$s.TargetPath = $pythonw
$s.Arguments = '"' + (Join-Path $PSScriptRoot 'app.py') + '"'
$s.WorkingDirectory = $PSScriptRoot
$s.IconLocation = (Resolve-Path (Join-Path $PSScriptRoot '..\icone\celular-webcam.ico')).Path + ',0'
$s.Description = 'Usar a câmera do celular como webcam'
$s.Save()
Write-Output "Atalho criado: $atalho"
