// Celular Webcam - camera virtual do Windows 11 (Media Foundation / Frame Server).
//
// O programa do PC escreve cada quadro (NV12) numa memoria compartilhada; esta DLL,
// carregada pelo servico de cameras do Windows, entrega esses quadros para qualquer
// app que abrir a camera "Celular Webcam" (OBS, Zoom, Meet, Teams, Discord...).
#pragma once

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mferror.h>
#include <mfobjects.h>
#include <ks.h>
#include <ksproxy.h>
#include <ksmedia.h>
#include <wrl/client.h>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <deque>
#include <vector>

using Microsoft::WRL::ComPtr;

// {F4D71105-46E5-44EC-8776-146B9BACF9A2}
static const GUID CLSID_CelularWebcam =
    {0xf4d71105, 0x46e5, 0x44ec, {0x87, 0x76, 0x14, 0x6b, 0x9b, 0xac, 0xf9, 0xa2}};
#define CLSID_CELULARWEBCAM_STR L"{F4D71105-46E5-44EC-8776-146B9BACF9A2}"
#define VCAM_FRIENDLY_NAME L"Celular Webcam"

// ---------------------------------------------------------------------------
// Memoria compartilhada (mesmo layout usado em pc/camera_virtual.py)
// ---------------------------------------------------------------------------
#define VCAM_SHARED_NAME L"Global\\CelularWebcam_Frames"
#define VCAM_EVENT_NAME L"Global\\CelularWebcam_NewFrame"
#define VCAM_MAGIC 0x4D435743u  // "CWCM"
#define VCAM_VERSION 1u
#define VCAM_MAX_WIDTH 3840u
#define VCAM_MAX_HEIGHT 2160u
#define VCAM_HEADER_SIZE 64u
#define VCAM_SHARED_SIZE (VCAM_HEADER_SIZE + VCAM_MAX_WIDTH * VCAM_MAX_HEIGHT * 3u / 2u)

#pragma pack(push, 8)
struct VCamHeader {
    uint32_t magic;          // 0
    uint32_t version;        // 4
    uint32_t reqWidth;       // 8   formato pedido pelo app que abriu a camera
    uint32_t reqHeight;      // 12
    uint32_t reqFps;         // 16
    uint32_t reserved0;      // 20
    int64_t consumerTick;    // 24  GetTickCount64 do ultimo quadro entregue
    volatile int64_t seq;    // 32  impar enquanto o programa do PC escreve
    uint32_t frameWidth;     // 40  tamanho do quadro que esta no buffer (NV12)
    uint32_t frameHeight;    // 44
    int64_t appTick;         // 48  GetTickCount64 da ultima escrita do programa do PC
    uint8_t reserved1[8];    // 56
};
#pragma pack(pop)
static_assert(sizeof(VCamHeader) == VCAM_HEADER_SIZE, "layout");

// Contagem de objetos vivos (para DllCanUnloadNow)
extern std::atomic<long> g_objects;

void VCamLog(const wchar_t* fmt, ...);
