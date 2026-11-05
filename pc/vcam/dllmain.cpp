#include "VCamSource.h"
#include <cstdarg>
#include <cstdio>

std::atomic<long> g_objects{0};
static std::atomic<long> g_locks{0};
static HMODULE g_module = nullptr;

// Log em C:\ProgramData\CelularWebcam\vcam.log (a pasta e criada pelo instalador).
void VCamLog(const wchar_t* fmt, ...) {
    wchar_t msg[512];
    va_list args;
    va_start(args, fmt);
    _vsnwprintf_s(msg, _TRUNCATE, fmt, args);
    va_end(args);
    OutputDebugStringW(msg);

    wchar_t path[MAX_PATH];
    if (!ExpandEnvironmentStringsW(L"%ProgramData%\\CelularWebcam\\vcam.log", path, MAX_PATH)) return;
    FILE* f = nullptr;
    if (_wfopen_s(&f, path, L"a, ccs=UTF-8") == 0 && f) {
        SYSTEMTIME st;
        GetLocalTime(&st);
        fwprintf(f, L"%04u-%02u-%02u %02u:%02u:%02u [%u] %s\n", st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute,
                 st.wSecond, GetCurrentProcessId(), msg);
        fclose(f);
    }
}

class ClassFactory : public IClassFactory {
public:
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (riid == __uuidof(IUnknown) || riid == __uuidof(IClassFactory)) {
            *ppv = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return 2; }
    STDMETHODIMP_(ULONG) Release() override { return 1; }

    STDMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        ComPtr<Activator> act;
        act.Attach(new (std::nothrow) Activator());
        if (!act) return E_OUTOFMEMORY;
        HRESULT hr = act->Initialize();
        if (FAILED(hr)) return hr;
        return act->QueryInterface(riid, ppv);
    }

    STDMETHODIMP LockServer(BOOL lock) override {
        if (lock)
            ++g_locks;
        else
            --g_locks;
        return S_OK;
    }
};

static ClassFactory g_factory;

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = module;
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}

STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, LPVOID* ppv) {
    if (clsid != CLSID_CelularWebcam) return CLASS_E_CLASSNOTAVAILABLE;
    return g_factory.QueryInterface(riid, ppv);
}

STDAPI DllCanUnloadNow() { return (g_objects == 0 && g_locks == 0) ? S_OK : S_FALSE; }

static const wchar_t* kClsidKey = L"Software\\Classes\\CLSID\\" CLSID_CELULARWEBCAM_STR;

STDAPI DllRegisterServer() {
    wchar_t path[MAX_PATH];
    if (!GetModuleFileNameW(g_module, path, MAX_PATH)) return HRESULT_FROM_WIN32(GetLastError());

    HKEY key = nullptr;
    LSTATUS st = RegCreateKeyExW(HKEY_LOCAL_MACHINE, kClsidKey, 0, nullptr, 0, KEY_WRITE, nullptr, &key, nullptr);
    if (st != ERROR_SUCCESS) return HRESULT_FROM_WIN32(st);
    RegSetValueExW(key, nullptr, 0, REG_SZ, (const BYTE*)VCAM_FRIENDLY_NAME, sizeof(VCAM_FRIENDLY_NAME));
    HKEY inproc = nullptr;
    st = RegCreateKeyExW(key, L"InprocServer32", 0, nullptr, 0, KEY_WRITE, nullptr, &inproc, nullptr);
    if (st == ERROR_SUCCESS) {
        RegSetValueExW(inproc, nullptr, 0, REG_SZ, (const BYTE*)path, (DWORD)((wcslen(path) + 1) * sizeof(wchar_t)));
        const wchar_t model[] = L"Both";
        RegSetValueExW(inproc, L"ThreadingModel", 0, REG_SZ, (const BYTE*)model, sizeof(model));
        RegCloseKey(inproc);
    }
    RegCloseKey(key);
    return HRESULT_FROM_WIN32(st);
}

STDAPI DllUnregisterServer() {
    LSTATUS st = RegDeleteTreeW(HKEY_LOCAL_MACHINE, kClsidKey);
    return (st == ERROR_SUCCESS || st == ERROR_FILE_NOT_FOUND) ? S_OK : HRESULT_FROM_WIN32(st);
}
