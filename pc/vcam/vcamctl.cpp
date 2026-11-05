// vcamctl.exe - cria ou remove a camera "Celular Webcam" no Windows 11.
//   vcamctl install   -> registra a camera para todos os usuarios (permanente)
//   vcamctl remove    -> remove a camera
// Precisa rodar como administrador. A DLL (CelularWebcamSource.dll) ja deve
// estar registrada com regsvr32.
#include "VCam.h"
#include <mfvirtualcamera.h>
#include <cstdio>

static int Run(bool install) {
    ComPtr<IMFVirtualCamera> cam;
    HRESULT hr = MFCreateVirtualCamera(MFVirtualCameraType_SoftwareCameraSource, MFVirtualCameraLifetime_System,
                                       MFVirtualCameraAccess_AllUsers, VCAM_FRIENDLY_NAME, CLSID_CELULARWEBCAM_STR,
                                       nullptr, 0, &cam);
    if (FAILED(hr)) {
        wprintf(L"MFCreateVirtualCamera falhou: 0x%08X\n", (unsigned)hr);
        return 2;
    }
    if (install) {
        hr = cam->Start(nullptr);
        if (FAILED(hr)) {
            wprintf(L"Start falhou: 0x%08X\n", (unsigned)hr);
            return 3;
        }
        wprintf(L"Camera instalada.\n");
    } else {
        hr = cam->Remove();
        if (FAILED(hr)) {
            wprintf(L"Remove falhou: 0x%08X\n", (unsigned)hr);
            return 4;
        }
        wprintf(L"Camera removida.\n");
    }
    cam->Shutdown();
    return 0;
}

int wmain(int argc, wchar_t** argv) {
    if (argc < 2 || (wcscmp(argv[1], L"install") != 0 && wcscmp(argv[1], L"remove") != 0)) {
        wprintf(L"uso: vcamctl install|remove\n");
        return 1;
    }
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    MFStartup(MF_VERSION);
    int r = Run(wcscmp(argv[1], L"install") == 0);
    MFShutdown();
    CoUninitialize();
    return r;
}

void VCamLog(const wchar_t*, ...) {}
std::atomic<long> g_objects{0};
