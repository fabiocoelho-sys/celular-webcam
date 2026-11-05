#pragma once
#include "VCam.h"
#include <sddl.h>

// Lado da DLL da memoria compartilhada. Quem cria e a DLL (roda no servico de
// cameras, que pode criar objetos "Global\"); o programa do PC so abre.
class FrameShare {
public:
    ~FrameShare() { Close(); }

    bool Open() {
        if (_view) return true;
        PSECURITY_DESCRIPTOR sd = nullptr;
        // Todos podem ler/escrever; rotulo de integridade baixa para nao barrar o app.
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
                L"D:(A;;GA;;;WD)(A;;GA;;;SY)(A;;GA;;;LS)(A;;GA;;;BA)S:(ML;;NW;;;LW)",
                SDDL_REVISION_1, &sd, nullptr)) {
            sd = nullptr;
        }
        SECURITY_ATTRIBUTES sa{sizeof(sa), sd, FALSE};
        _map = CreateFileMappingW(INVALID_HANDLE_VALUE, sd ? &sa : nullptr, PAGE_READWRITE, 0,
                                  VCAM_SHARED_SIZE, VCAM_SHARED_NAME);
        if (_map) {
            _view = static_cast<uint8_t*>(MapViewOfFile(_map, FILE_MAP_ALL_ACCESS, 0, 0, VCAM_SHARED_SIZE));
            _event = CreateEventW(sd ? &sa : nullptr, FALSE, FALSE, VCAM_EVENT_NAME);
        } else {
            VCamLog(L"CreateFileMapping falhou: %u", GetLastError());
        }
        if (sd) LocalFree(sd);
        if (!_view) {
            Close();
            return false;
        }
        auto h = Header();
        if (h->magic != VCAM_MAGIC || h->version != VCAM_VERSION) {
            ZeroMemory(h, sizeof(VCamHeader));
            h->version = VCAM_VERSION;
            h->magic = VCAM_MAGIC;
        }
        return true;
    }

    void Close() {
        if (_view) UnmapViewOfFile(_view);
        if (_map) CloseHandle(_map);
        if (_event) CloseHandle(_event);
        _view = nullptr;
        _map = nullptr;
        _event = nullptr;
    }

    VCamHeader* Header() const { return reinterpret_cast<VCamHeader*>(_view); }
    const uint8_t* Pixels() const { return _view + VCAM_HEADER_SIZE; }
    HANDLE Event() const { return _event; }

private:
    HANDLE _map = nullptr;
    HANDLE _event = nullptr;
    uint8_t* _view = nullptr;
};
