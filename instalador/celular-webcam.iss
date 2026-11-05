; Instalador do Celular Webcam (Inno Setup 6).
; Gerado pelo gerar-versao.ps1, que passa /DVersao=x.y.z e /DOrigem=<pasta com os arquivos>.

#ifndef Versao
  #define Versao "0.0.0"
#endif
#ifndef Origem
  #define Origem "..\build"
#endif

[Setup]
AppId={{5B1E7A9C-3D44-4C1B-9F0E-6A2C8D1B7E55}
AppName=Celular Webcam
AppVersion={#Versao}
AppVerName=Celular Webcam {#Versao}
AppPublisher=Celular Webcam
DefaultDirName={autopf}\Celular Webcam
DefaultGroupName=Celular Webcam
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; A webcam virtual usa uma API que so existe no Windows 11
MinVersion=10.0.22000
OutputDir={#Origem}\..
OutputBaseFilename=CelularWebcam-Instalador-{#Versao}
SetupIconFile=..\icone\celular-webcam.ico
UninstallDisplayIcon={app}\CelularWebcam.exe
UninstallDisplayName=Celular Webcam
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
VersionInfoVersion={#Versao}
VersionInfoCompany=Celular Webcam
VersionInfoDescription=Instalador do Celular Webcam
VersionInfoProductName=Celular Webcam

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "atalho"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Origem}\programa\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Origem}\adb\*"; DestDir: "{app}\adb"; Flags: ignoreversion
Source: "{#Origem}\apk\celular-webcam.apk"; DestDir: "{app}\apk"; Flags: ignoreversion
Source: "..\icone\celular-webcam.ico"; DestDir: "{app}\icone"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
; Camera virtual: a DLL fica carregada no servico de cameras do Windows
Source: "{#Origem}\vcam\CelularWebcamSource.dll"; DestDir: "{app}\vcam"; Flags: ignoreversion regserver restartreplace uninsrestartdelete
Source: "{#Origem}\vcam\vcamctl.exe"; DestDir: "{app}\vcam"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Celular Webcam"; Filename: "{app}\CelularWebcam.exe"
Name: "{autodesktop}\Celular Webcam"; Filename: "{app}\CelularWebcam.exe"; Tasks: atalho

[Run]
Filename: "{app}\vcam\vcamctl.exe"; Parameters: "install"; Flags: runhidden waituntilterminated; StatusMsg: "Registrando a webcam virtual..."
Filename: "{app}\CelularWebcam.exe"; Description: "{cm:LaunchProgram,Celular Webcam}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\vcam\vcamctl.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoverCamera"

[Code]
// Para o servico de cameras do Windows, que segura a DLL da webcam virtual
procedure PararServicoCamera();
var
  Codigo: Integer;
begin
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -Command "Stop-Service FrameServerMonitor,FrameServer -Force -ErrorAction SilentlyContinue"',
    '', SW_HIDE, ewWaitUntilTerminated, Codigo);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  PararServicoCamera();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    PararServicoCamera();
end;
