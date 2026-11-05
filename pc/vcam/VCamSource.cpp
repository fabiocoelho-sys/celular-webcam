#include "VCamSource.h"

#define RETURN_IF_FAILED(x)       \
    do {                          \
        HRESULT _hr = (x);        \
        if (FAILED(_hr)) return _hr; \
    } while (0)

// Formatos oferecidos aos apps (OBS, Zoom...). O programa do PC adapta o video
// do celular ao formato que o app escolher.
static const struct {
    UINT32 w, h, fps;
} kFormats[] = {
    {1920, 1080, 30}, {1280, 720, 30}, {1920, 1080, 60}, {1280, 720, 60},
    {640, 360, 30},   {640, 480, 30},  {3840, 2160, 30},
};

static HRESULT CreateVideoType(UINT32 w, UINT32 h, UINT32 fps, IMFMediaType** out) {
    ComPtr<IMFMediaType> t;
    RETURN_IF_FAILED(MFCreateMediaType(&t));
    t->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
    t->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_NV12);
    MFSetAttributeSize(t.Get(), MF_MT_FRAME_SIZE, w, h);
    MFSetAttributeRatio(t.Get(), MF_MT_FRAME_RATE, fps, 1);
    MFSetAttributeRatio(t.Get(), MF_MT_PIXEL_ASPECT_RATIO, 1, 1);
    t->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive);
    t->SetUINT32(MF_MT_ALL_SAMPLES_INDEPENDENT, TRUE);
    t->SetUINT32(MF_MT_FIXED_SIZE_SAMPLES, TRUE);
    t->SetUINT32(MF_MT_DEFAULT_STRIDE, w);
    t->SetUINT32(MF_MT_SAMPLE_SIZE, w * h * 3 / 2);
    t->SetUINT32(MF_MT_AVG_BITRATE, w * h * 12 * fps);
    *out = t.Detach();
    return S_OK;
}

// ===========================================================================
// MediaStream
// ===========================================================================

MediaStream::MediaStream() { ++g_objects; }

MediaStream::~MediaStream() {
    StopThread();
    if (_stopEvent) CloseHandle(_stopEvent);
    --g_objects;
}

HRESULT MediaStream::Initialize(MediaSource* source, DWORD id) {
    _source = source;
    RETURN_IF_FAILED(MFCreateEventQueue(&_queue));
    RETURN_IF_FAILED(MFCreateAttributes(&_attributes, 8));
    _attributes->SetGUID(MF_DEVICESTREAM_STREAM_CATEGORY, PINNAME_VIDEO_CAPTURE);
    _attributes->SetUINT32(MF_DEVICESTREAM_STREAM_ID, id);
    _attributes->SetUINT32(MF_DEVICESTREAM_FRAMESERVER_SHARED, 1);
    _attributes->SetUINT32(MF_DEVICESTREAM_ATTRIBUTE_FRAMESOURCE_TYPES, MFFrameSourceTypes_Color);

    std::vector<ComPtr<IMFMediaType>> types;
    std::vector<IMFMediaType*> raw;
    for (auto& f : kFormats) {
        ComPtr<IMFMediaType> t;
        RETURN_IF_FAILED(CreateVideoType(f.w, f.h, f.fps, &t));
        raw.push_back(t.Get());
        types.push_back(t);
    }
    RETURN_IF_FAILED(MFCreateStreamDescriptor(id, (DWORD)raw.size(), raw.data(), &_descriptor));
    ComPtr<IMFMediaTypeHandler> handler;
    RETURN_IF_FAILED(_descriptor->GetMediaTypeHandler(&handler));
    RETURN_IF_FAILED(handler->SetCurrentMediaType(raw[0]));
    RETURN_IF_FAILED(_attributes->CopyAllItems(_descriptor.Get()));

    RETURN_IF_FAILED(MFCreateVideoSampleAllocatorEx(IID_PPV_ARGS(&_allocator)));
    _stopEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    return S_OK;
}

STDMETHODIMP MediaStream::QueryInterface(REFIID riid, void** ppv) {
    if (!ppv) return E_POINTER;
    if (riid == __uuidof(IUnknown) || riid == __uuidof(IMFMediaEventGenerator) ||
        riid == __uuidof(IMFMediaStream) || riid == __uuidof(IMFMediaStream2)) {
        *ppv = static_cast<IMFMediaStream2*>(this);
        AddRef();
        return S_OK;
    }
    *ppv = nullptr;
    return E_NOINTERFACE;
}

STDMETHODIMP_(ULONG) MediaStream::AddRef() { return ++_ref; }

STDMETHODIMP_(ULONG) MediaStream::Release() {
    ULONG r = --_ref;
    if (r == 0) delete this;
    return r;
}

STDMETHODIMP MediaStream::GetEvent(DWORD flags, IMFMediaEvent** ev) {
    ComPtr<IMFMediaEventQueue> q;
    {
        std::lock_guard<std::mutex> lk(_lock);
        q = _queue;
    }
    if (!q) return MF_E_SHUTDOWN;
    return q->GetEvent(flags, ev);
}

STDMETHODIMP MediaStream::BeginGetEvent(IMFAsyncCallback* cb, IUnknown* state) {
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    return _queue->BeginGetEvent(cb, state);
}

STDMETHODIMP MediaStream::EndGetEvent(IMFAsyncResult* r, IMFMediaEvent** ev) {
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    return _queue->EndGetEvent(r, ev);
}

STDMETHODIMP MediaStream::QueueEvent(MediaEventType t, REFGUID g, HRESULT hr, const PROPVARIANT* v) {
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    return _queue->QueueEventParamVar(t, g, hr, v);
}

STDMETHODIMP MediaStream::GetMediaSource(IMFMediaSource** src) {
    if (!src) return E_POINTER;
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue || !_source) return MF_E_SHUTDOWN;
    return _source->QueryInterface(IID_PPV_ARGS(src));
}

STDMETHODIMP MediaStream::GetStreamDescriptor(IMFStreamDescriptor** sd) {
    if (!sd) return E_POINTER;
    std::lock_guard<std::mutex> lk(_lock);
    if (!_descriptor) return MF_E_SHUTDOWN;
    return _descriptor.CopyTo(sd);
}

STDMETHODIMP MediaStream::RequestSample(IUnknown* token) {
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    if (_state != MF_STREAM_STATE_RUNNING) return MF_E_INVALIDREQUEST;
    _pending.emplace_back(token);
    _cv.notify_one();
    return S_OK;
}

STDMETHODIMP MediaStream::SetStreamState(MF_STREAM_STATE state) {
    MF_STREAM_STATE cur;
    {
        std::lock_guard<std::mutex> lk(_lock);
        cur = _state;
    }
    if (state == cur) return S_OK;
    switch (state) {
    case MF_STREAM_STATE_RUNNING:
        return Start();
    case MF_STREAM_STATE_STOPPED:
        return Stop();
    case MF_STREAM_STATE_PAUSED: {
        std::lock_guard<std::mutex> lk(_lock);
        _state = MF_STREAM_STATE_PAUSED;
        return S_OK;
    }
    default:
        return MF_E_INVALID_STATE_TRANSITION;
    }
}

STDMETHODIMP MediaStream::GetStreamState(MF_STREAM_STATE* state) {
    if (!state) return E_POINTER;
    std::lock_guard<std::mutex> lk(_lock);
    *state = _state;
    return S_OK;
}

HRESULT MediaStream::Start() {
    StopThread();
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;

    ComPtr<IMFMediaTypeHandler> handler;
    ComPtr<IMFMediaType> type;
    RETURN_IF_FAILED(_descriptor->GetMediaTypeHandler(&handler));
    RETURN_IF_FAILED(handler->GetCurrentMediaType(&type));
    UINT32 num = 30, den = 1;
    MFGetAttributeSize(type.Get(), MF_MT_FRAME_SIZE, &_width, &_height);
    MFGetAttributeRatio(type.Get(), MF_MT_FRAME_RATE, &num, &den);
    _fps = den ? std::max<UINT32>(1, num / den) : 30;

    _allocator->UninitializeSampleAllocator();
    RETURN_IF_FAILED(_allocator->InitializeSampleAllocator(8, type.Get()));

    _share.Open();
    _lastFrame.assign((size_t)_width * _height * 3 / 2, 0);
    _hasLastFrame = false;
    _lastSeq = -1;
    _pending.clear();
    _stopping = false;
    ResetEvent(_stopEvent);
    _state = MF_STREAM_STATE_RUNNING;
    VCamLog(L"stream start %ux%u @ %u", _width, _height, _fps);

    PROPVARIANT t;
    PropVariantInit(&t);
    t.vt = VT_I8;
    t.hVal.QuadPart = MFGetSystemTime();
    _queue->QueueEventParamVar(MEStreamStarted, GUID_NULL, S_OK, &t);

    AddRef();  // a thread segura uma referencia
    _thread = std::thread([this] {
        DeliveryLoop();
        Release();
    });
    return S_OK;
}

HRESULT MediaStream::Stop() {
    StopThread();
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    _state = MF_STREAM_STATE_STOPPED;
    _pending.clear();
    _share.Close();
    PROPVARIANT t;
    PropVariantInit(&t);
    t.vt = VT_I8;
    t.hVal.QuadPart = MFGetSystemTime();
    _queue->QueueEventParamVar(MEStreamStopped, GUID_NULL, S_OK, &t);
    VCamLog(L"stream stop");
    return S_OK;
}

void MediaStream::StopThread() {
    {
        std::lock_guard<std::mutex> lk(_lock);
        _stopping = true;
        _cv.notify_all();
    }
    if (_stopEvent) SetEvent(_stopEvent);
    if (_thread.joinable()) {
        if (_thread.get_id() == std::this_thread::get_id())
            _thread.detach();
        else
            _thread.join();
    }
}

void MediaStream::Shutdown() {
    StopThread();
    std::lock_guard<std::mutex> lk(_lock);
    if (_queue) _queue->Shutdown();
    _queue = nullptr;
    _pending.clear();
    if (_allocator) _allocator->UninitializeSampleAllocator();
    _allocator = nullptr;
    _descriptor = nullptr;
    _source = nullptr;
    _share.Close();
}

void MediaStream::DeliveryLoop() {
    const int64_t interval = 10'000'000LL / _fps;  // unidades de 100 ns
    // Timer de alta resolucao: o Sleep/Wait normal do Windows so acorda a cada ~16 ms
    HANDLE timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    if (!timer) timer = CreateWaitableTimerW(nullptr, FALSE, nullptr);

    // Espera ate o instante 'when' (100 ns, relogio do MF). Se 'frameEvent' vier,
    // acorda antes quando chegar quadro novo. Retorna false se pediram para parar.
    auto waitUntil = [&](int64_t when, HANDLE frameEvent) -> bool {
        int64_t now = MFGetSystemTime();
        if (when <= now) return WaitForSingleObject(_stopEvent, 0) != WAIT_OBJECT_0;
        LARGE_INTEGER due;
        due.QuadPart = -(when - now);
        SetWaitableTimer(timer, &due, 0, nullptr, nullptr, FALSE);
        HANDLE hs[3] = {_stopEvent, timer, frameEvent};
        DWORD r = WaitForMultipleObjects(frameEvent ? 3 : 2, hs, FALSE, INFINITE);
        CancelWaitableTimer(timer);
        return r != WAIT_OBJECT_0;
    };

    int64_t next = MFGetSystemTime();
    for (;;) {
        // 1) espera um pedido de quadro
        ComPtr<IUnknown> token;
        {
            std::unique_lock<std::mutex> lk(_lock);
            _cv.wait_for(lk, std::chrono::milliseconds(200), [this] { return _stopping || !_pending.empty(); });
            if (_stopping) break;
            if (_pending.empty()) continue;
        }

        // 2) ritmo fixo no FPS pedido; se chegar quadro novo do celular um pouco
        //    antes da hora, entrega na hora (menos atraso)
        int64_t now = MFGetSystemTime();
        if (next < now - interval) next = now;  // ficou para tras: ressincroniza
        if (!waitUntil(next - interval / 4, nullptr)) break;
        if (!waitUntil(next, _share.Event())) break;

        // 3) entrega
        {
            std::lock_guard<std::mutex> lk(_lock);
            if (_stopping) break;
            if (_pending.empty()) continue;
            token = _pending.front();
            _pending.pop_front();
        }
        HRESULT hr = DeliverSample(token.Get());
        if (hr == MF_E_SAMPLEALLOCATOR_EMPTY) {
            // o app ainda nao devolveu os quadros anteriores; tenta de novo ja ja
            std::lock_guard<std::mutex> lk(_lock);
            _pending.push_front(token);
            continue;
        }
        next += interval;
    }
    if (timer) CloseHandle(timer);
}

HRESULT MediaStream::DeliverSample(IUnknown* token) {
    ComPtr<IMFSample> sample;
    HRESULT hr = _allocator->AllocateSample(&sample);
    if (FAILED(hr)) {
        if (hr == MF_E_SAMPLEALLOCATOR_EMPTY) Sleep(2);
        return hr;
    }
    ComPtr<IMFMediaBuffer> buffer;
    RETURN_IF_FAILED(sample->GetBufferByIndex(0, &buffer));

    ComPtr<IMF2DBuffer2> buffer2d;
    if (SUCCEEDED(buffer.As(&buffer2d))) {
        BYTE* scan0 = nullptr;
        BYTE* start = nullptr;
        LONG pitch = 0;
        DWORD len = 0;
        RETURN_IF_FAILED(buffer2d->Lock2DSize(MF2DBuffer_LockFlags_Write, &scan0, &pitch, &start, &len));
        FillFrame(scan0, pitch);
        buffer2d->Unlock2D();
    } else {
        BYTE* data = nullptr;
        DWORD maxLen = 0;
        RETURN_IF_FAILED(buffer->Lock(&data, &maxLen, nullptr));
        FillFrame(data, (LONG)_width);
        buffer->Unlock();
        buffer->SetCurrentLength(_width * _height * 3 / 2);
    }

    sample->SetSampleTime(MFGetSystemTime());
    sample->SetSampleDuration(10'000'000LL / _fps);
    if (token) sample->SetUnknown(MFSampleExtension_Token, token);

    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    return _queue->QueueEventParamUnk(MEMediaSample, GUID_NULL, S_OK, sample.Get());
}

void MediaStream::FillFrame(uint8_t* dst, LONG pitch) {
    const size_t frameSize = (size_t)_width * _height * 3 / 2;
    const ULONGLONG now = GetTickCount64();

    VCamHeader* h = _share.Header();
    if (!h && _share.Open()) h = _share.Header();
    if (h) {
        h->reqWidth = _width;
        h->reqHeight = _height;
        h->reqFps = _fps;
        h->consumerTick = (int64_t)now;

        const bool appAlive = now - (ULONGLONG)h->appTick < 3000;
        const int64_t s1 = h->seq;
        if (appAlive && (s1 & 1) == 0 && s1 != _lastSeq && h->frameWidth == _width && h->frameHeight == _height) {
            memcpy(_lastFrame.data(), _share.Pixels(), frameSize);
            MemoryBarrier();
            if (h->seq == s1) {
                _lastSeq = s1;
                _hasLastFrame = true;
            }
        }
        if (!appAlive) _hasLastFrame = false;
    }

    if (!_hasLastFrame) {
        // Tela de espera: cinza escuro
        for (UINT32 y = 0; y < _height; y++) memset(dst + (size_t)y * pitch, 40, _width);
        uint8_t* uv = dst + (size_t)pitch * _height;
        for (UINT32 y = 0; y < _height / 2; y++) memset(uv + (size_t)y * pitch, 128, _width);
        return;
    }

    const uint8_t* src = _lastFrame.data();
    if ((UINT32)pitch == _width) {
        memcpy(dst, src, frameSize);
        return;
    }
    for (UINT32 y = 0; y < _height; y++) memcpy(dst + (size_t)y * pitch, src + (size_t)y * _width, _width);
    const uint8_t* srcUv = src + (size_t)_width * _height;
    uint8_t* dstUv = dst + (size_t)pitch * _height;
    for (UINT32 y = 0; y < _height / 2; y++) memcpy(dstUv + (size_t)y * pitch, srcUv + (size_t)y * _width, _width);
}

// ===========================================================================
// MediaSource
// ===========================================================================

MediaSource::MediaSource() { ++g_objects; }
MediaSource::~MediaSource() { --g_objects; }

HRESULT MediaSource::Initialize() {
    RETURN_IF_FAILED(MFCreateEventQueue(&_queue));
    RETURN_IF_FAILED(MFCreateAttributes(&_attributes, 4));
    _stream.Attach(new MediaStream());
    RETURN_IF_FAILED(_stream->Initialize(this, 0));
    ComPtr<IMFStreamDescriptor> sd;
    RETURN_IF_FAILED(_stream->GetStreamDescriptor(&sd));
    IMFStreamDescriptor* sds[] = {sd.Get()};
    RETURN_IF_FAILED(MFCreatePresentationDescriptor(1, sds, &_descriptor));
    RETURN_IF_FAILED(_descriptor->SelectStream(0));
    VCamLog(L"source criada");
    return S_OK;
}

STDMETHODIMP MediaSource::QueryInterface(REFIID riid, void** ppv) {
    if (!ppv) return E_POINTER;
    if (riid == __uuidof(IUnknown) || riid == __uuidof(IMFMediaEventGenerator) ||
        riid == __uuidof(IMFMediaSource) || riid == __uuidof(IMFMediaSourceEx)) {
        *ppv = static_cast<IMFMediaSourceEx*>(this);
    } else if (riid == __uuidof(IMFGetService)) {
        *ppv = static_cast<IMFGetService*>(this);
    } else if (riid == __uuidof(IKsControl)) {
        *ppv = static_cast<IKsControl*>(this);
    } else {
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    AddRef();
    return S_OK;
}

STDMETHODIMP_(ULONG) MediaSource::AddRef() { return ++_ref; }

STDMETHODIMP_(ULONG) MediaSource::Release() {
    ULONG r = --_ref;
    if (r == 0) delete this;
    return r;
}

STDMETHODIMP MediaSource::GetEvent(DWORD flags, IMFMediaEvent** ev) {
    ComPtr<IMFMediaEventQueue> q;
    {
        std::lock_guard<std::mutex> lk(_lock);
        q = _queue;
    }
    if (!q) return MF_E_SHUTDOWN;
    return q->GetEvent(flags, ev);
}

STDMETHODIMP MediaSource::BeginGetEvent(IMFAsyncCallback* cb, IUnknown* state) {
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    return _queue->BeginGetEvent(cb, state);
}

STDMETHODIMP MediaSource::EndGetEvent(IMFAsyncResult* r, IMFMediaEvent** ev) {
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    return _queue->EndGetEvent(r, ev);
}

STDMETHODIMP MediaSource::QueueEvent(MediaEventType t, REFGUID g, HRESULT hr, const PROPVARIANT* v) {
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    return _queue->QueueEventParamVar(t, g, hr, v);
}

STDMETHODIMP MediaSource::GetCharacteristics(DWORD* c) {
    if (!c) return E_POINTER;
    *c = MFMEDIASOURCE_IS_LIVE;
    return S_OK;
}

STDMETHODIMP MediaSource::CreatePresentationDescriptor(IMFPresentationDescriptor** pd) {
    if (!pd) return E_POINTER;
    std::lock_guard<std::mutex> lk(_lock);
    if (!_descriptor) return MF_E_SHUTDOWN;
    return _descriptor->Clone(pd);
}

STDMETHODIMP MediaSource::Start(IMFPresentationDescriptor* pd, const GUID* fmt, const PROPVARIANT* start) {
    if (!pd || !start) return E_INVALIDARG;
    if (fmt && *fmt != GUID_NULL) return MF_E_UNSUPPORTED_TIME_FORMAT;

    ComPtr<MediaStream> stream;
    bool selected = false;
    {
        std::lock_guard<std::mutex> lk(_lock);
        if (!_queue) return MF_E_SHUTDOWN;
        DWORD count = 0;
        RETURN_IF_FAILED(pd->GetStreamDescriptorCount(&count));
        for (DWORD i = 0; i < count; i++) {
            BOOL sel = FALSE;
            ComPtr<IMFStreamDescriptor> sd;
            RETURN_IF_FAILED(pd->GetStreamDescriptorByIndex(i, &sel, &sd));
            DWORD id = 0;
            sd->GetStreamIdentifier(&id);
            if (id != 0) continue;
            selected = sel != FALSE;
            if (selected) {
                _descriptor->SelectStream(0);
                // Garante que o tipo escolhido pelo app vale no nosso descritor
                ComPtr<IMFMediaTypeHandler> h;
                ComPtr<IMFMediaType> type;
                if (SUCCEEDED(sd->GetMediaTypeHandler(&h)) && SUCCEEDED(h->GetCurrentMediaType(&type))) {
                    ComPtr<IMFStreamDescriptor> mine;
                    ComPtr<IMFMediaTypeHandler> myHandler;
                    if (SUCCEEDED(_stream->GetStreamDescriptor(&mine)) && SUCCEEDED(mine->GetMediaTypeHandler(&myHandler)))
                        myHandler->SetCurrentMediaType(type.Get());
                }
            } else {
                _descriptor->DeselectStream(0);
            }
        }
        stream = _stream;
        if (selected) {
            _queue->QueueEventParamUnk(_started ? MEUpdatedStream : MENewStream, GUID_NULL, S_OK,
                                       static_cast<IMFMediaStream*>(stream.Get()));
        }
    }

    if (selected) RETURN_IF_FAILED(stream->Start());

    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    PROPVARIANT t;
    PropVariantInit(&t);
    t.vt = VT_I8;
    t.hVal.QuadPart = MFGetSystemTime();
    _started = true;
    return _queue->QueueEventParamVar(MESourceStarted, GUID_NULL, S_OK, &t);
}

STDMETHODIMP MediaSource::Stop() {
    ComPtr<MediaStream> stream;
    {
        std::lock_guard<std::mutex> lk(_lock);
        if (!_queue) return MF_E_SHUTDOWN;
        stream = _stream;
    }
    if (stream) stream->Stop();
    std::lock_guard<std::mutex> lk(_lock);
    if (!_queue) return MF_E_SHUTDOWN;
    PROPVARIANT t;
    PropVariantInit(&t);
    t.vt = VT_I8;
    t.hVal.QuadPart = MFGetSystemTime();
    return _queue->QueueEventParamVar(MESourceStopped, GUID_NULL, S_OK, &t);
}

STDMETHODIMP MediaSource::Pause() { return MF_E_INVALID_STATE_TRANSITION; }

STDMETHODIMP MediaSource::Shutdown() {
    ComPtr<MediaStream> stream;
    {
        std::lock_guard<std::mutex> lk(_lock);
        if (!_queue) return MF_E_SHUTDOWN;
        _queue->Shutdown();
        _queue = nullptr;
        stream = _stream;
        _stream = nullptr;
        _descriptor = nullptr;
    }
    if (stream) stream->Shutdown();
    VCamLog(L"source shutdown");
    return S_OK;
}

STDMETHODIMP MediaSource::GetSourceAttributes(IMFAttributes** a) {
    if (!a) return E_POINTER;
    std::lock_guard<std::mutex> lk(_lock);
    if (!_attributes) return MF_E_SHUTDOWN;
    return _attributes.CopyTo(a);
}

STDMETHODIMP MediaSource::GetStreamAttributes(DWORD id, IMFAttributes** a) {
    if (!a) return E_POINTER;
    std::lock_guard<std::mutex> lk(_lock);
    if (!_stream) return MF_E_SHUTDOWN;
    if (id != 0) return MF_E_INVALIDSTREAMNUMBER;
    IMFAttributes* attrs = _stream->Attributes();
    attrs->AddRef();
    *a = attrs;
    return S_OK;
}

STDMETHODIMP MediaSource::SetD3DManager(IUnknown*) { return S_OK; }

STDMETHODIMP MediaSource::GetService(REFGUID, REFIID, LPVOID* ppv) {
    if (ppv) *ppv = nullptr;
    return MF_E_UNSUPPORTED_SERVICE;
}

STDMETHODIMP MediaSource::KsProperty(PKSPROPERTY, ULONG, LPVOID, ULONG, ULONG*) {
    return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND);
}

STDMETHODIMP MediaSource::KsMethod(PKSMETHOD, ULONG, LPVOID, ULONG, ULONG*) {
    return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND);
}

STDMETHODIMP MediaSource::KsEvent(PKSEVENT, ULONG, LPVOID, ULONG, ULONG*) {
    return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND);
}

// ===========================================================================
// Activator
// ===========================================================================

Activator::Activator() { ++g_objects; }
Activator::~Activator() { --g_objects; }

HRESULT Activator::Initialize() { return MFCreateAttributes(&_attributes, 4); }

STDMETHODIMP Activator::QueryInterface(REFIID riid, void** ppv) {
    if (!ppv) return E_POINTER;
    if (riid == __uuidof(IUnknown) || riid == __uuidof(IMFAttributes) || riid == __uuidof(IMFActivate)) {
        *ppv = static_cast<IMFActivate*>(this);
        AddRef();
        return S_OK;
    }
    *ppv = nullptr;
    return E_NOINTERFACE;
}

STDMETHODIMP_(ULONG) Activator::AddRef() { return ++_ref; }

STDMETHODIMP_(ULONG) Activator::Release() {
    ULONG r = --_ref;
    if (r == 0) delete this;
    return r;
}

STDMETHODIMP Activator::ActivateObject(REFIID riid, void** ppv) {
    if (!ppv) return E_POINTER;
    std::lock_guard<std::mutex> lk(_lock);
    if (!_source) {
        ComPtr<MediaSource> src;
        src.Attach(new MediaSource());
        RETURN_IF_FAILED(src->Initialize());
        _source = src;
    }
    return _source->QueryInterface(riid, ppv);
}

STDMETHODIMP Activator::ShutdownObject() {
    std::lock_guard<std::mutex> lk(_lock);
    if (_source) _source->Shutdown();
    _source = nullptr;
    return S_OK;
}

STDMETHODIMP Activator::DetachObject() {
    std::lock_guard<std::mutex> lk(_lock);
    _source = nullptr;
    return S_OK;
}
