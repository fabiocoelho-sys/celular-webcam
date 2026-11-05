"""Icone na area de notificacao do Windows (os "itens ocultos" da barra de tarefas).

Usa a API do Windows direto, sem bibliotecas extras. Roda numa thread propria,
porque o icone precisa de uma janela invisivel com o seu proprio loop de mensagens.
"""
import ctypes
import threading
from ctypes import wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CLASSE = "CelularWebcamBandeja"
MUTEX = "CelularWebcamPrograma"

WM_NULL = 0x0000
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_ICONE = 0x8000 + 1    # o Windows avisa aqui os cliques no icone
WM_MOSTRAR = 0x8000 + 2  # outra copia do programa pedindo para abrir a janela

NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
MF_STRING, MF_SEPARATOR = 0, 0x800
TPM_RETURNCMD, TPM_NONOTIFY = 0x100, 0x80
ERROR_ALREADY_EXISTS = 183
ASFW_ANY = 0xFFFFFFFF
CMD_ABRIR, CMD_SAIR = 1, 2

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", w.HINSTANCE), ("hIcon", w.HICON), ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
        ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT), ("uCallbackMessage", w.UINT),
        ("hIcon", w.HICON), ("szTip", w.WCHAR * 128), ("dwState", w.DWORD), ("dwStateMask", w.DWORD),
        ("szInfo", w.WCHAR * 256), ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
        ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", w.HICON),
    ]


# Sem isto, o ctypes corta os ponteiros em 32 bits
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.RegisterClassW.restype = w.ATOM
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreateWindowExW.restype = w.HWND
user32.CreateWindowExW.argtypes = [
    w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID,
]
user32.DestroyWindow.argtypes = [w.HWND]
user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.FindWindowW.restype = w.HWND
user32.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
user32.LoadImageW.restype = w.HANDLE
user32.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
user32.LoadIconW.restype = w.HICON
user32.LoadIconW.argtypes = [w.HINSTANCE, w.LPVOID]
user32.CreatePopupMenu.restype = w.HMENU
user32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
user32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.LPVOID]
user32.DestroyMenu.argtypes = [w.HMENU]
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.RegisterWindowMessageW.restype = w.UINT
user32.RegisterWindowMessageW.argtypes = [w.LPCWSTR]
shell32.Shell_NotifyIconW.restype = w.BOOL
shell32.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = w.HMODULE
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.CreateMutexW.restype = w.HANDLE
kernel32.CreateMutexW.argtypes = [w.LPVOID, w.BOOL, w.LPCWSTR]

_mutex = None  # precisa durar enquanto o programa estiver aberto


def ja_aberto():
    """Se o programa ja esta rodando, pede para a janela dele aparecer e devolve True.

    Com a janela escondida na bandeja, clicar no atalho abriria uma segunda copia,
    e as duas ficariam derrubando a conexao uma da outra.
    """
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, MUTEX)
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        return False
    user32.AllowSetForegroundWindow(ASFW_ANY)  # deixa a outra copia vir para a frente
    hwnd = user32.FindWindowW(CLASSE, None)
    if hwnd:
        user32.PostMessageW(hwnd, WM_MOSTRAR, 0, 0)
    return True


class Bandeja:
    """ao_abrir e ao_sair sao chamados na thread da bandeja, nao na da janela."""

    def __init__(self, icone, dica, ao_abrir, ao_sair):
        self.icone = icone
        self.dica = dica
        self.ao_abrir = ao_abrir
        self.ao_sair = ao_sair
        self.ativa = False  # so esconda a janela se isto for True, senao ela fica inacessivel
        self._hwnd = None
        self._dados = None
        self._proc = WNDPROC(self._mensagem)  # referencia precisa continuar viva
        self._msg_barra_criada = user32.RegisterWindowMessageW("TaskbarCreated")
        self._thread = threading.Thread(target=self._rodar, name="bandeja", daemon=True)

    def iniciar(self):
        self._thread.start()

    def parar(self):
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            self._thread.join(1)

    def _adicionar(self):
        self.ativa = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._dados)))

    def _rodar(self):
        hinst = kernel32.GetModuleHandleW(None)
        classe = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName=CLASSE)
        user32.RegisterClassW(ctypes.byref(classe))
        # Janela comum que nunca e mostrada (uma "message-only" nao receberia o TaskbarCreated)
        self._hwnd = user32.CreateWindowExW(0, CLASSE, "Celular Webcam", 0, 0, 0, 0, 0, None, None, hinst, None)
        if not self._hwnd:
            return

        lado = user32.GetSystemMetrics(49)  # SM_CXSMICON
        hicon = None
        if self.icone:
            hicon = user32.LoadImageW(None, self.icone, 1, lado, lado, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        d = NOTIFYICONDATAW()
        d.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        d.hWnd = self._hwnd
        d.uID = 1
        d.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        d.uCallbackMessage = WM_ICONE
        d.hIcon = hicon or user32.LoadIconW(None, 32512)  # IDI_APPLICATION
        d.szTip = self.dica
        self._dados = d
        self._adicionar()

        msg = w.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _mensagem(self, hwnd, msg, wparam, lparam):
        if msg == WM_ICONE:
            if lparam == WM_LBUTTONUP:
                self.ao_abrir()
            elif lparam == WM_RBUTTONUP:
                self._menu()
            return 0
        if msg == WM_MOSTRAR:
            self.ao_abrir()
            return 0
        if msg == self._msg_barra_criada:  # o Explorer reiniciou e perdeu o icone
            self._adicionar()
            return 0
        if msg == WM_CLOSE:
            self.ativa = False
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._dados))
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, CMD_ABRIR, "Abrir")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_SAIR, "Sair")
        ponto = w.POINT()
        user32.GetCursorPos(ctypes.byref(ponto))
        user32.SetForegroundWindow(self._hwnd)  # sem isto o menu nao fecha ao clicar fora
        cmd = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_NONOTIFY, ponto.x, ponto.y, 0, self._hwnd, None)
        user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd == CMD_ABRIR:
            self.ao_abrir()
        elif cmd == CMD_SAIR:
            self.ao_sair()
