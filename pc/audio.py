"""Toca o microfone do celular numa saida de audio do PC.

Para outros apps enxergarem como microfone, a saida escolhida precisa ser um
cabo de audio virtual (ex.: "CABLE Input" do VB-CABLE).
"""
import threading

import sounddevice as sd

TAXA = 48000
BYTES_POR_AMOSTRA = 2
MAX_ATRASO = int(TAXA * BYTES_POR_AMOSTRA * 0.25)  # passou de 250 ms acumulado...
ALVO_ATRASO = int(TAXA * BYTES_POR_AMOSTRA * 0.06)  # ...descarta e volta para 60 ms


def saidas():
    """[(indice, nome)] das saidas de audio (so a API MME, para nao repetir nomes)."""
    try:
        apis = sd.query_hostapis()
        mme = next((i for i, a in enumerate(apis) if a["name"] == "MME"), None)
        lista = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0 and (mme is None or d["hostapi"] == mme):
                lista.append((i, d["name"]))
        return lista
    except Exception:
        return []


def saida_cabo_virtual():
    for i, nome in saidas():
        if "CABLE Input" in nome:
            return i
    return None


class Audio:
    def __init__(self):
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stream = None
        self.dispositivo = None

    def iniciar(self, dispositivo):
        self.parar()
        self.dispositivo = dispositivo
        self._stream = sd.RawOutputStream(
            samplerate=TAXA, channels=1, dtype="int16", device=dispositivo,
            blocksize=480, latency="low", callback=self._callback,
        )
        self._stream.start()

    def parar(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        with self._lock:
            self._buf.clear()

    @property
    def tocando(self):
        return self._stream is not None

    def receber(self, dados):
        if self._stream is None:
            return
        with self._lock:
            self._buf += dados
            if len(self._buf) > MAX_ATRASO:
                del self._buf[:len(self._buf) - ALVO_ATRASO]

    def _callback(self, saida, quadros, tempo, status):
        n = quadros * BYTES_POR_AMOSTRA
        with self._lock:
            pedaco = bytes(self._buf[:n])
            del self._buf[:n]
        saida[:len(pedaco)] = pedaco
        if len(pedaco) < n:
            saida[len(pedaco):n] = b"\x00" * (n - len(pedaco))
