#pragma once
#include "VCam.h"
#include "FrameShare.h"
#include <thread>

class MediaSource;

// Repassa todos os metodos de IMFAttributes para um objeto interno (_attributes).
#define FORWARD_IMFATTRIBUTES(target)                                                                         \
    STDMETHODIMP GetItem(REFGUID k, PROPVARIANT* v) override { return target->GetItem(k, v); }                \
    STDMETHODIMP GetItemType(REFGUID k, MF_ATTRIBUTE_TYPE* t) override { return target->GetItemType(k, t); } \
    STDMETHODIMP CompareItem(REFGUID k, REFPROPVARIANT v, BOOL* r) override { return target->CompareItem(k, v, r); } \
    STDMETHODIMP Compare(IMFAttributes* a, MF_ATTRIBUTES_MATCH_TYPE m, BOOL* r) override { return target->Compare(a, m, r); } \
    STDMETHODIMP GetUINT32(REFGUID k, UINT32* v) override { return target->GetUINT32(k, v); }                 \
    STDMETHODIMP GetUINT64(REFGUID k, UINT64* v) override { return target->GetUINT64(k, v); }                 \
    STDMETHODIMP GetDouble(REFGUID k, double* v) override { return target->GetDouble(k, v); }                 \
    STDMETHODIMP GetGUID(REFGUID k, GUID* v) override { return target->GetGUID(k, v); }                       \
    STDMETHODIMP GetStringLength(REFGUID k, UINT32* v) override { return target->GetStringLength(k, v); }     \
    STDMETHODIMP GetString(REFGUID k, LPWSTR s, UINT32 n, UINT32* l) override { return target->GetString(k, s, n, l); } \
    STDMETHODIMP GetAllocatedString(REFGUID k, LPWSTR* s, UINT32* l) override { return target->GetAllocatedString(k, s, l); } \
    STDMETHODIMP GetBlobSize(REFGUID k, UINT32* v) override { return target->GetBlobSize(k, v); }             \
    STDMETHODIMP GetBlob(REFGUID k, UINT8* b, UINT32 n, UINT32* l) override { return target->GetBlob(k, b, n, l); } \
    STDMETHODIMP GetAllocatedBlob(REFGUID k, UINT8** b, UINT32* l) override { return target->GetAllocatedBlob(k, b, l); } \
    STDMETHODIMP GetUnknown(REFGUID k, REFIID r, LPVOID* p) override { return target->GetUnknown(k, r, p); }  \
    STDMETHODIMP SetItem(REFGUID k, REFPROPVARIANT v) override { return target->SetItem(k, v); }              \
    STDMETHODIMP DeleteItem(REFGUID k) override { return target->DeleteItem(k); }                             \
    STDMETHODIMP DeleteAllItems() override { return target->DeleteAllItems(); }                               \
    STDMETHODIMP SetUINT32(REFGUID k, UINT32 v) override { return target->SetUINT32(k, v); }                  \
    STDMETHODIMP SetUINT64(REFGUID k, UINT64 v) override { return target->SetUINT64(k, v); }                  \
    STDMETHODIMP SetDouble(REFGUID k, double v) override { return target->SetDouble(k, v); }                  \
    STDMETHODIMP SetGUID(REFGUID k, REFGUID v) override { return target->SetGUID(k, v); }                     \
    STDMETHODIMP SetString(REFGUID k, LPCWSTR v) override { return target->SetString(k, v); }                 \
    STDMETHODIMP SetBlob(REFGUID k, const UINT8* b, UINT32 n) override { return target->SetBlob(k, b, n); }  \
    STDMETHODIMP SetUnknown(REFGUID k, IUnknown* u) override { return target->SetUnknown(k, u); }             \
    STDMETHODIMP LockStore() override { return target->LockStore(); }                                         \
    STDMETHODIMP UnlockStore() override { return target->UnlockStore(); }                                     \
    STDMETHODIMP GetCount(UINT32* c) override { return target->GetCount(c); }                                 \
    STDMETHODIMP GetItemByIndex(UINT32 i, GUID* k, PROPVARIANT* v) override { return target->GetItemByIndex(i, k, v); } \
    STDMETHODIMP CopyAllItems(IMFAttributes* d) override { return target->CopyAllItems(d); }

// ---------------------------------------------------------------------------
// Stream de video (unico) da camera
// ---------------------------------------------------------------------------
class MediaStream : public IMFMediaStream2 {
public:
    MediaStream();
    HRESULT Initialize(MediaSource* source, DWORD id);

    // IUnknown
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override;
    STDMETHODIMP_(ULONG) AddRef() override;
    STDMETHODIMP_(ULONG) Release() override;

    // IMFMediaEventGenerator
    STDMETHODIMP GetEvent(DWORD flags, IMFMediaEvent** ev) override;
    STDMETHODIMP BeginGetEvent(IMFAsyncCallback* cb, IUnknown* state) override;
    STDMETHODIMP EndGetEvent(IMFAsyncResult* r, IMFMediaEvent** ev) override;
    STDMETHODIMP QueueEvent(MediaEventType t, REFGUID g, HRESULT hr, const PROPVARIANT* v) override;

    // IMFMediaStream
    STDMETHODIMP GetMediaSource(IMFMediaSource** src) override;
    STDMETHODIMP GetStreamDescriptor(IMFStreamDescriptor** sd) override;
    STDMETHODIMP RequestSample(IUnknown* token) override;

    // IMFMediaStream2
    STDMETHODIMP SetStreamState(MF_STREAM_STATE state) override;
    STDMETHODIMP GetStreamState(MF_STREAM_STATE* state) override;

    HRESULT Start();
    HRESULT Stop();
    void Shutdown();
    IMFAttributes* Attributes() { return _attributes.Get(); }

private:
    ~MediaStream();
    void DeliveryLoop();
    HRESULT DeliverSample(IUnknown* token);
    void FillFrame(uint8_t* dst, LONG pitch);
    void StopThread();

    std::atomic<ULONG> _ref{1};
    std::mutex _lock;
    std::condition_variable _cv;
    ComPtr<IMFMediaEventQueue> _queue;
    ComPtr<IMFStreamDescriptor> _descriptor;
    ComPtr<IMFAttributes> _attributes;
    ComPtr<IMFVideoSampleAllocatorEx> _allocator;
    MediaSource* _source = nullptr;  // referencia fraca (a fonte e dona do stream)
    MF_STREAM_STATE _state = MF_STREAM_STATE_STOPPED;
    std::deque<ComPtr<IUnknown>> _pending;
    bool _stopping = false;
    std::thread _thread;
    HANDLE _stopEvent = nullptr;
    FrameShare _share;
    UINT32 _width = 1920, _height = 1080, _fps = 30;
    int64_t _lastSeq = -1;
    std::vector<uint8_t> _lastFrame;  // ultimo quadro valido (para repetir)
    bool _hasLastFrame = false;
};

// ---------------------------------------------------------------------------
// Fonte de midia (a "camera")
// ---------------------------------------------------------------------------
class MediaSource : public IMFMediaSourceEx, public IMFGetService, public IKsControl {
public:
    MediaSource();
    HRESULT Initialize();

    // IUnknown
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override;
    STDMETHODIMP_(ULONG) AddRef() override;
    STDMETHODIMP_(ULONG) Release() override;

    // IMFMediaEventGenerator
    STDMETHODIMP GetEvent(DWORD flags, IMFMediaEvent** ev) override;
    STDMETHODIMP BeginGetEvent(IMFAsyncCallback* cb, IUnknown* state) override;
    STDMETHODIMP EndGetEvent(IMFAsyncResult* r, IMFMediaEvent** ev) override;
    STDMETHODIMP QueueEvent(MediaEventType t, REFGUID g, HRESULT hr, const PROPVARIANT* v) override;

    // IMFMediaSource
    STDMETHODIMP GetCharacteristics(DWORD* c) override;
    STDMETHODIMP CreatePresentationDescriptor(IMFPresentationDescriptor** pd) override;
    STDMETHODIMP Start(IMFPresentationDescriptor* pd, const GUID* fmt, const PROPVARIANT* start) override;
    STDMETHODIMP Stop() override;
    STDMETHODIMP Pause() override;
    STDMETHODIMP Shutdown() override;

    // IMFMediaSourceEx
    STDMETHODIMP GetSourceAttributes(IMFAttributes** a) override;
    STDMETHODIMP GetStreamAttributes(DWORD id, IMFAttributes** a) override;
    STDMETHODIMP SetD3DManager(IUnknown* m) override;

    // IMFGetService
    STDMETHODIMP GetService(REFGUID svc, REFIID riid, LPVOID* ppv) override;

    // IKsControl
    STDMETHODIMP KsProperty(PKSPROPERTY p, ULONG pl, LPVOID d, ULONG dl, ULONG* r) override;
    STDMETHODIMP KsMethod(PKSMETHOD m, ULONG ml, LPVOID d, ULONG dl, ULONG* r) override;
    STDMETHODIMP KsEvent(PKSEVENT e, ULONG el, LPVOID d, ULONG dl, ULONG* r) override;

private:
    ~MediaSource();

    std::atomic<ULONG> _ref{1};
    std::mutex _lock;
    ComPtr<IMFMediaEventQueue> _queue;
    ComPtr<IMFPresentationDescriptor> _descriptor;
    ComPtr<IMFAttributes> _attributes;
    ComPtr<MediaStream> _stream;
    bool _started = false;
};

// ---------------------------------------------------------------------------
// Ativador: e o objeto COM que o servico de cameras cria a partir do CLSID
// ---------------------------------------------------------------------------
class Activator : public IMFActivate {
public:
    Activator();
    HRESULT Initialize();

    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override;
    STDMETHODIMP_(ULONG) AddRef() override;
    STDMETHODIMP_(ULONG) Release() override;

    FORWARD_IMFATTRIBUTES(_attributes)

    STDMETHODIMP ActivateObject(REFIID riid, void** ppv) override;
    STDMETHODIMP ShutdownObject() override;
    STDMETHODIMP DetachObject() override;

private:
    ~Activator();
    std::atomic<ULONG> _ref{1};
    std::mutex _lock;
    ComPtr<IMFAttributes> _attributes;
    ComPtr<MediaSource> _source;
};
