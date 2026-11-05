@echo off
rem Compila a camera virtual (DLL + vcamctl.exe).
rem Arquivos intermediarios: %LOCALAPPDATA%\celular-webcam-build\vcam (fora do OneDrive)
rem Resultado: pc\vcam\bin (pronto para o instalar-camera.ps1)
setlocal
set SRC=%~dp0
set OUT=%LOCALAPPDATA%\celular-webcam-build\vcam

set "VCVARS="
for %%r in ("%ProgramFiles%" "%ProgramFiles(x86)%") do for %%v in (18 2022) do for %%e in (BuildTools Community Professional Enterprise) do (
    if not defined VCVARS if exist "%%~r\Microsoft Visual Studio\%%v\%%e\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%%~r\Microsoft Visual Studio\%%v\%%e\VC\Auxiliary\Build\vcvars64.bat"
)
if not defined VCVARS (
    echo Visual Studio Build Tools nao encontrado.
    exit /b 1
)
call "%VCVARS%" >nul || exit /b 1

if not exist "%OUT%" mkdir "%OUT%"
cd /d "%OUT%"

set CFLAGS=/nologo /std:c++17 /EHsc /O2 /MT /W3 /DUNICODE /D_UNICODE
set LIBS=mfplat.lib mfuuid.lib mf.lib ole32.lib advapi32.lib

cl %CFLAGS% /LD "%SRC%dllmain.cpp" "%SRC%VCamSource.cpp" /Fe:CelularWebcamSource.dll /link /DEF:"%SRC%vcam.def" %LIBS% || exit /b 1
cl %CFLAGS% "%SRC%vcamctl.cpp" /Fe:vcamctl.exe /link %LIBS% mfsensorgroup.lib || exit /b 1

rem Copia os binarios para o projeto (o notebook instala sem precisar compilar)
if not exist "%SRC%bin" mkdir "%SRC%bin"
copy /y CelularWebcamSource.dll "%SRC%bin\" >nul
copy /y vcamctl.exe "%SRC%bin\" >nul

echo.
echo OK: %SRC%bin
