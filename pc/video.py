"""Decodifica o H.264 do celular e entrega para a camera virtual e para a previa da janela."""
import threading
import time

import av
import numpy as np

PREVIA_LARGURA = 512
PREVIA_FPS = 15


class Video:
    def __init__(self, camera_virtual, pedir_keyframe):
        self.cam = camera_virtual
        self.pedir_keyframe = pedir_keyframe
        self.rotacao_celular = 0  # graus que o celular pede para a imagem ficar em pe
        self.rotacao_extra = 0    # escolhida pelo usuario
        self.espelhar = False
        self.previa_ativa = True  # falso com a janela escondida na bandeja

        self._lock = threading.Lock()
        self.previa = None        # array RGB pequeno
        self.previa_versao = 0
        self._ultima_previa = 0.0
        self._fundo_cache = {}

        self.quadros = 0
        self.tamanho = (0, 0)
        self.em_uso = None        # (w, h, fps) pedido pelo app que usa a webcam
        self.reiniciar()

    def reiniciar(self):
        self._codec = av.CodecContext.create("h264", "r")
        self._codec.flags |= av.codec.context.Flags.low_delay
        self._codec.thread_type = "SLICE"
        self._config = None
        self._esperando_keyframe = True

    # chamado na thread de leitura da conexao
    def receber(self, dados, pts, flags):
        if flags & 2:  # SPS/PPS: guarda para mandar junto com o proximo quadro
            self._config = bytes(dados)
            return
        if self._esperando_keyframe and not flags & 1:
            return
        pacote = self._config + bytes(dados) if self._config else bytes(dados)
        self._config = None
        try:
            quadros = self._codec.decode(av.Packet(pacote))
        except av.error.FFmpegError:
            self._esperando_keyframe = True
            self.pedir_keyframe()
            return
        self._esperando_keyframe = False
        for q in quadros:
            self._saida(q)

    def _saida(self, quadro):
        self.quadros += 1
        self.tamanho = (quadro.width, quadro.height)
        agora = time.monotonic()
        quer_previa = self.previa_ativa and agora - self._ultima_previa >= 1.0 / PREVIA_FPS
        pedido = self.cam.pedido()
        self.em_uso = pedido
        if not pedido and not quer_previa:
            return

        img = self._transformar(quadro)

        if pedido:
            w, h, _ = pedido
            self.cam.escrever(self._encaixar(img, w, h), w, h)

        if quer_previa:
            self._ultima_previa = agora
            pw = PREVIA_LARGURA
            ph = max(2, int(img.height * pw / img.width) // 2 * 2)
            rgb = img.reformat(width=pw, height=ph, format="rgb24").to_ndarray()
            with self._lock:
                self.previa = rgb
                self.previa_versao += 1

    def _transformar(self, quadro):
        """Gira/espelha direto nos planos YUV (mais leve que converter para RGB)."""
        rot = (self.rotacao_celular + self.rotacao_extra) % 360
        if rot == 0 and not self.espelhar:
            return quadro
        w, h = quadro.width, quadro.height
        arr = quadro.to_ndarray(format="yuv420p")
        y = arr[:h]
        u = arr[h:h + h // 4].reshape(h // 2, w // 2)
        v = arr[h + h // 4:].reshape(h // 2, w // 2)
        k = -(rot // 90)  # rot90 do numpy gira no sentido anti-horario
        planos = []
        for p in (y, u, v):
            if k:
                p = np.rot90(p, k)
            if self.espelhar:
                p = p[:, ::-1]
            planos.append(np.ascontiguousarray(p))
        nh, nw = planos[0].shape
        junto = np.concatenate([p.ravel() for p in planos]).reshape(nh * 3 // 2, nw)
        return av.VideoFrame.from_ndarray(junto, format="yuv420p")

    def _encaixar(self, img, w, h):
        """Ajusta ao tamanho pedido pelo app, sem distorcer (faixas pretas se precisar)."""
        escala = min(w / img.width, h / img.height)
        tw = max(2, int(img.width * escala) // 2 * 2)
        th = max(2, int(img.height * escala) // 2 * 2)
        if (tw, th) == (w, h):
            if (img.width, img.height) == (w, h):
                return img.to_ndarray(format="nv12")
            return img.reformat(width=w, height=h, format="nv12").to_ndarray()

        dentro = img.reformat(width=tw, height=th, format="nv12").to_ndarray()
        fundo = self._fundo(w, h).copy()
        x0 = (w - tw) // 4 * 2
        y0 = (h - th) // 4 * 2
        fundo[y0:y0 + th, x0:x0 + tw] = dentro[:th]
        fundo[h + y0 // 2:h + y0 // 2 + th // 2, x0:x0 + tw] = dentro[th:]
        return fundo

    def _fundo(self, w, h):
        f = self._fundo_cache.get((w, h))
        if f is None:
            f = np.empty((h * 3 // 2, w), np.uint8)
            f[:h] = 16    # preto
            f[h:] = 128   # sem cor
            self._fundo_cache = {(w, h): f}
        return f

    def pegar_previa(self, versao_atual):
        with self._lock:
            if self.previa_versao == versao_atual:
                return None, versao_atual
            return self.previa, self.previa_versao
