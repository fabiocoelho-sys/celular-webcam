"""Lado do programa do PC da camera virtual "Celular Webcam".

A DLL (pc/vcam) roda dentro do servico de cameras do Windows e cria uma memoria
compartilhada quando algum app (OBS, Zoom, Meet...) abre a camera. Aqui a gente
so abre essa memoria e escreve os quadros em NV12 no tamanho que o app pediu.
Layout igual ao VCamHeader de pc/vcam/VCam.h.
"""
import ctypes
import ctypes.wintypes as wt
import time
import winreg

NOME_MEMORIA = "Global\\CelularWebcam_Frames"
NOME_EVENTO = "Global\\CelularWebcam_NewFrame"
CLSID = "{F4D71105-46E5-44EC-8776-146B9BACF9A2}"
MAGIC = 0x4D435743
HEADER = 64
MAX_W, MAX_H = 3840, 2160
TAMANHO = HEADER + MAX_W * MAX_H * 3 // 2

FILE_MAP_ALL_ACCESS = 0xF001F
EVENT_MODIFY_STATE = 0x0002

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
k32.OpenFileMappingW.restype = wt.HANDLE
k32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
k32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
k32.OpenEventW.restype = wt.HANDLE
k32.SetEvent.argtypes = [wt.HANDLE]
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.GetTickCount64.restype = ctypes.c_ulonglong


class _Header(ctypes.Structure):
    _fields_ = [
        ("magic", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("reqWidth", ctypes.c_uint32),
        ("reqHeight", ctypes.c_uint32),
        ("reqFps", ctypes.c_uint32),
        ("reserved0", ctypes.c_uint32),
        ("consumerTick", ctypes.c_int64),
        ("seq", ctypes.c_int64),
        ("frameWidth", ctypes.c_uint32),
        ("frameHeight", ctypes.c_uint32),
        ("appTick", ctypes.c_int64),
        ("reserved1", ctypes.c_uint8 * 8),
    ]


def instalada():
    """A DLL da camera virtual esta registrada no Windows?"""
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Classes\CLSID\{CLSID}\InprocServer32"))
        return True
    except OSError:
        return False


class CameraVirtual:
    def __init__(self):
        self._map = None
        self._view = None
        self._event = None
        self._header = None
        self._proxima_tentativa = 0.0

    def abrir(self):
        """Tenta abrir a memoria compartilhada (so existe com a camera em uso)."""
        if self._header is not None:
            return True
        agora = time.monotonic()
        if agora < self._proxima_tentativa:
            return False
        self._proxima_tentativa = agora + 1.0
        h = k32.OpenFileMappingW(FILE_MAP_ALL_ACCESS, False, NOME_MEMORIA)
        if not h:
            return False
        view = k32.MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, TAMANHO)
        if not view:
            k32.CloseHandle(h)
            return False
        header = _Header.from_address(view)
        if header.magic != MAGIC:
            k32.UnmapViewOfFile(view)
            k32.CloseHandle(h)
            return False
        self._map, self._view, self._header = h, view, header
        self._event = k32.OpenEventW(EVENT_MODIFY_STATE, False, NOME_EVENTO)
        return True

    def pedido(self):
        """(largura, altura, fps) que o app quer, ou None se nenhum app esta usando a camera."""
        if not self.abrir():
            return None
        h = self._header
        if k32.GetTickCount64() - h.consumerTick > 1500:
            return None
        w, a = h.reqWidth, h.reqHeight
        if not (0 < w <= MAX_W and 0 < a <= MAX_H):
            return None
        return w, a, h.reqFps

    def escrever(self, nv12, largura, altura):
        """nv12: array numpy (altura*3/2, largura) uint8, contiguo."""
        h = self._header
        if h is None:
            return
        h.seq += 1  # impar: escrevendo
        ctypes.memmove(self._view + HEADER, nv12.ctypes.data, nv12.nbytes)
        h.frameWidth = largura
        h.frameHeight = altura
        h.appTick = k32.GetTickCount64()
        h.seq += 1  # par: pronto
        if self._event:
            k32.SetEvent(self._event)

    def fechar(self):
        if self._header is not None:
            self._header.appTick = 0  # a camera volta para a tela de espera na hora
        if self._view:
            k32.UnmapViewOfFile(self._view)
        if self._map:
            k32.CloseHandle(self._map)
        if self._event:
            k32.CloseHandle(self._event)
        self._map = self._view = self._event = self._header = None
