"""Celular Webcam - programa do PC.

Conecta no app do celular (Wi-Fi ou cabo USB), mostra a previa, envia a imagem
para a webcam virtual "Celular Webcam" e controla a camera do celular a distancia.
"""
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

import audio
import bandeja
import camera_virtual
import conexao
import tema
from video import Video

PASTA_CONFIG = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "CelularWebcam")
ARQ_CONFIG = os.path.join(PASTA_CONFIG, "config.json")

QUALIDADES = [
    ("Automática", 0),
    ("Baixa (4 Mbps)", 4_000_000),
    ("Média (8 Mbps)", 8_000_000),
    ("Alta (16 Mbps)", 16_000_000),
    ("Muito alta (30 Mbps)", 30_000_000),
]
BRANCO = {
    "auto": "Automático", "daylight": "Luz do dia", "cloudy": "Nublado",
    "fluorescent": "Fluorescente", "incandescent": "Incandescente (amarelada)",
    "warm": "Fluorescente quente", "shade": "Sombra", "twilight": "Crepúsculo",
}
ROTACOES = ["0°", "90°", "180°", "270°"]


def carregar_config():
    try:
        with open(ARQ_CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def salvar_config(cfg):
    try:
        os.makedirs(PASTA_CONFIG, exist_ok=True)
        with open(ARQ_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = carregar_config()
        self.eventos = queue.Queue()

        self.cam_virtual = camera_virtual.CameraVirtual()
        self.video = Video(self.cam_virtual, self._pedir_keyframe)
        self.video.rotacao_extra = self.cfg.get("rotacao", 0)
        self.video.espelhar = self.cfg.get("espelhar", False)
        self.audio = audio.Audio()

        self.conn = None
        self.quer_conectar = False
        self.cameras = {}       # id -> capacidades (do celular)
        self.estado = {}        # ajustes atuais da camera do celular
        self.nome_celular = ""
        self.achados = []       # [(nome, ip, porta)]
        self._atualizando = False
        self._ultimo_toque = {}  # chave -> hora em que o usuario mexeu
        self._patch = {}
        self._patch_timer = None
        self._versao_previa = 0
        self._foto = None
        self._ultimos_bytes = (time.monotonic(), 0, 0)
        self._painel_camera_id = None
        self._maximizada = False

        root.title("Celular Webcam")
        root.minsize(1040, 680)
        tema.aplicar(root)
        root.protocol("WM_DELETE_WINDOW", self.sair)
        self.bandeja = bandeja.Bandeja(
            conexao.recurso("icone", "celular-webcam.ico"), "Celular Webcam",
            lambda: self.eventos.put(("mostrar",)), lambda: self.eventos.put(("sair",)),
        )
        self.bandeja.iniciar()
        root.bind("<Unmap>", self._ao_minimizar)
        root.bind("<Configure>", self._ao_redimensionar)
        self._montar_tela()
        tema.barra_escura(root)
        self._loop()
        self._loop_info()
        if self.cfg.get("modo", "wifi") == "wifi":
            self.procurar()

    # ================================================================== bandeja

    def _ao_minimizar(self, ev):
        # O evento tambem chega dos widgets internos; so interessa o da janela
        if ev.widget is self.root and self.root.state() == "iconic" and self.bandeja.ativa:
            self.root.withdraw()
            self.video.previa_ativa = False

    def _ao_redimensionar(self, ev):
        estado = self.root.state()
        if ev.widget is self.root and estado in ("normal", "zoomed"):
            self._maximizada = estado == "zoomed"

    def mostrar(self):
        self.video.previa_ativa = True
        self.root.deiconify()
        if self._maximizada:
            self.root.state("zoomed")
        self.root.lift()
        self.root.focus_force()

    # ================================================================== tela

    def _montar_tela(self):
        topo = ttk.Frame(self.root, padding=(16, 14, 16, 6))
        topo.pack(fill="x")

        self.modo = tk.StringVar(value=self.cfg.get("modo", "wifi"))
        ttk.Radiobutton(topo, text="Wi-Fi", value="wifi", variable=self.modo, command=self._modo_mudou,
                        style="Seg.TRadiobutton").pack(side="left")
        ttk.Radiobutton(topo, text="Cabo USB", value="usb", variable=self.modo, command=self._modo_mudou,
                        style="Seg.TRadiobutton").pack(side="left", padx=(4, 16))

        self.alvo = tk.StringVar(value=self.cfg.get("ultimo_ip", ""))
        self.combo_alvo = ttk.Combobox(topo, textvariable=self.alvo, width=34)
        self.combo_alvo.pack(side="left")
        self.bt_procurar = ttk.Button(topo, text="Procurar", command=self.procurar)
        self.bt_procurar.pack(side="left", padx=8)
        self.bt_conectar = ttk.Button(topo, text="Conectar", command=self.alternar_conexao, style="Accent.TButton")
        self.bt_conectar.pack(side="left")

        self.status = tk.StringVar(value="Abra o app Celular Webcam no celular.")
        ttk.Label(self.root, textvariable=self.status, style="Status.TLabel", padding=(18, 0)).pack(fill="x")

        corpo = ttk.Frame(self.root, padding=(16, 10, 16, 14))
        corpo.pack(fill="both", expand=True)

        # --- esquerda: previa
        esq = ttk.Frame(corpo)
        esq.pack(side="left", fill="both", expand=True)
        self.previa = tk.Label(esq, bg=tema.VIDEO, fg=tema.TEXTO2, text="Sem imagem", width=64, height=18, bd=0)
        self.previa.pack(fill="both", expand=True)

        linha = ttk.Frame(esq, padding=(0, 10, 0, 0))
        linha.pack(fill="x")
        ttk.Label(linha, text="Girar", style="Rotulo.TLabel").pack(side="left")
        self.rotacao = tk.StringVar(value=f"{self.video.rotacao_extra}°")
        cb = ttk.Combobox(linha, textvariable=self.rotacao, values=ROTACOES, width=6, state="readonly")
        cb.pack(side="left", padx=(8, 18))
        cb.bind("<<ComboboxSelected>>", self._rotacao_mudou)
        self.espelhar = tk.BooleanVar(value=self.video.espelhar)
        ttk.Checkbutton(linha, text="Espelhar", variable=self.espelhar, command=self._espelhar_mudou).pack(side="left")

        self.info = tk.StringVar()
        ttk.Label(esq, textvariable=self.info, style="Status.TLabel", padding=(0, 8, 0, 0)).pack(fill="x")
        self.info_webcam = tk.StringVar()
        ttk.Label(esq, textvariable=self.info_webcam, style="Status.TLabel").pack(fill="x")
        self.bt_instalar = ttk.Button(esq, text="Instalar webcam virtual", command=self.instalar_webcam)
        # Instalado pelo instalador, a camera virtual ja vem junto; o botao e so para o codigo-fonte
        if not camera_virtual.instalada() and not getattr(sys, "frozen", False):
            self.bt_instalar.pack(anchor="w", pady=(4, 0))

        # --- direita: controles
        dir_ = ttk.Frame(corpo, width=340)
        dir_.pack(side="right", fill="y", padx=(18, 0))
        dir_.pack_propagate(False)
        self.abas = ttk.Notebook(dir_)
        self.abas.pack(fill="both", expand=True)
        self.aba_camera = ttk.Frame(self.abas, padding=(2, 10))
        self.aba_imagem = ttk.Frame(self.abas, padding=(2, 10))
        self.aba_audio = ttk.Frame(self.abas, padding=(2, 12))
        self.abas.add(self.aba_camera, text="Câmera")
        self.abas.add(self.aba_imagem, text="Imagem")
        self.abas.add(self.aba_audio, text="Microfone")
        self._montar_aba_audio()
        self._painel_vazio()
        self._modo_mudou(salvar=False)

    def _painel_vazio(self):
        for aba in (self.aba_camera, self.aba_imagem):
            for w in aba.winfo_children():
                w.destroy()
            ttk.Label(aba, text="Conecte o celular para ver\nos ajustes da câmera.", style="Status.TLabel").pack(pady=20)
        self._atualizadores = []
        self._painel_camera_id = None

    def _montar_aba_audio(self):
        a = self.aba_audio
        self.usar_mic = tk.BooleanVar(value=False)
        ttk.Checkbutton(a, text="Usar o microfone do celular", variable=self.usar_mic,
                        command=self._mic_mudou).pack(anchor="w")
        ttk.Label(a, text="Enviar o som para:", padding=(0, 10, 0, 2)).pack(anchor="w")
        self.saidas = audio.saidas()
        nomes = [n for _, n in self.saidas]
        padrao = audio.saida_cabo_virtual()
        escolhida = self.cfg.get("saida_audio")
        if escolhida not in nomes:
            escolhida = next((n for i, n in self.saidas if i == padrao), nomes[0] if nomes else "")
        self.saida_audio = tk.StringVar(value=escolhida)
        cb = ttk.Combobox(a, textvariable=self.saida_audio, values=nomes, state="readonly", width=40)
        cb.pack(anchor="w", fill="x")
        cb.bind("<<ComboboxSelected>>", lambda e: self._mic_mudou())
        dica = ("Para o som aparecer como microfone no Zoom, Meet, OBS etc., "
                "escolha um cabo de áudio virtual (ex.: \"CABLE Input\").")
        if padrao is None:
            dica += "\n\nNenhum cabo de áudio virtual encontrado neste PC."
        ttk.Label(a, text=dica, wraplength=300, style="Status.TLabel", padding=(0, 10)).pack(anchor="w")

    # ---------------------------------------------------------- painel da camera

    def _montar_painel(self, cam):
        for aba in (self.aba_camera, self.aba_imagem):
            for w in aba.winfo_children():
                w.destroy()
        self._atualizadores = []
        self._painel_camera_id = cam["id"]

        def titulo(pai, texto):
            l = ttk.Label(pai, text=texto, style="Rotulo.TLabel", padding=(0, 9, 0, 3))
            l.pack(anchor="w")
            return l

        def combo(pai, rotulo, itens, indice_atual, ao_escolher):
            titulo(pai, rotulo)
            var = tk.StringVar()
            c = ttk.Combobox(pai, textvariable=var, values=itens, state="readonly")
            c.pack(fill="x")
            c.bind("<<ComboboxSelected>>", lambda e: ao_escolher(c.current()))

            def atualizar(s):
                i = indice_atual(s)
                if 0 <= i < len(c["values"]) and c.current() != i:
                    c.current(i)
            self._atualizadores.append(atualizar)
            return c

        def slider(pai, rotulo, de, ate, valor, formato, ao_mudar, chave, ativo=lambda s: True):
            t = titulo(pai, rotulo)
            var = tk.DoubleVar()

            def mexeu(_=None):
                if self._atualizando:
                    return
                self._ultimo_toque[chave] = time.monotonic()
                t.configure(text=f"{rotulo}: {formato(var.get())}")
                ao_mudar(var.get())
            sc = ttk.Scale(pai, from_=de, to=ate, variable=var, command=mexeu)
            sc.pack(fill="x")

            def atualizar(s):
                if time.monotonic() - self._ultimo_toque.get(chave, 0) > 0.8:
                    var.set(valor(s))
                t.configure(text=f"{rotulo}: {formato(var.get())}")
                sc.state(["!disabled"] if ativo(s) else ["disabled"])
            self._atualizadores.append(atualizar)

        def check(pai, rotulo, chave, ativo=lambda s: True):
            var = tk.BooleanVar()
            c = ttk.Checkbutton(pai, text=rotulo, variable=var,
                                command=lambda: self.enviar({chave: var.get()}, ja=True))
            c.pack(anchor="w", pady=(6, 0))

            def atualizar(s):
                var.set(bool(s.get(chave)))
                c.state(["!disabled"] if ativo(s) else ["disabled"])
            self._atualizadores.append(atualizar)

        # ------------------------------------------------ aba Câmera
        a = self.aba_camera
        ids = list(self.cameras.keys())
        combo(a, "Câmera", [self.cameras[i]["label"] for i in ids],
              lambda s: ids.index(s.get("camera")) if s.get("camera") in ids else -1,
              lambda i: self.enviar({"camera": ids[i]}, ja=True))

        tamanhos = cam["sizes"]  # [w, h, fps_max, [fps...]] (versoes antigas: so os 3 primeiros)
        combo(a, "Resolução", [f"{t[0]} x {t[1]}" for t in tamanhos],
              lambda s: next((i for i, t in enumerate(tamanhos) if t[0] == s.get("width") and t[1] == s.get("height")), -1),
              lambda i: self.enviar({"width": tamanhos[i][0], "height": tamanhos[i][1]}, ja=True))

        titulo(a, "FPS")
        fps_var = tk.StringVar()
        fps_combo = ttk.Combobox(a, textvariable=fps_var, state="readonly")
        fps_combo.pack(fill="x")
        fps_opcoes = []

        def fps_escolhido(_):
            i = fps_combo.current()
            if 0 <= i < len(fps_opcoes):
                self.enviar({"fps": fps_opcoes[i]}, ja=True)
        fps_combo.bind("<<ComboboxSelected>>", fps_escolhido)
        fps_aviso = ttk.Label(a, style="Status.TLabel", wraplength=300)
        fps_aviso.pack(anchor="w")

        def fps_atualizar(s):
            t = next((t for t in tamanhos if t[0] == s.get("width") and t[1] == s.get("height")), None)
            if t and len(t) > 3:
                opcoes = list(t[3])  # lista exata de FPS dessa resolucao
            else:
                maximo = t[2] if t else 30
                opcoes = [f for f in cam["fps"] if 10 <= f <= maximo]
            if opcoes != fps_opcoes:
                fps_opcoes[:] = opcoes
                fps_combo["values"] = [f"{f} FPS" for f in opcoes]
            if s.get("fps") in fps_opcoes:
                fps_combo.current(fps_opcoes.index(s["fps"]))
            if 60 not in opcoes:
                fps_aviso.configure(
                    text=f"Este celular libera até {max(opcoes, default=30)} FPS para outros apps nesta resolução.")
            else:
                fps_aviso.configure(text="")
        self._atualizadores.append(fps_atualizar)

        combo(a, "Qualidade (taxa de bits)", [q[0] for q in QUALIDADES],
              lambda s: next((i for i, q in enumerate(QUALIDADES) if q[1] == s.get("bitrate")), 0),
              lambda i: self.enviar({"bitrate": QUALIDADES[i][1]}, ja=True))

        if cam["zoomMax"] > cam["zoomMin"]:
            slider(a, "Zoom", cam["zoomMin"], cam["zoomMax"], lambda s: s.get("zoom", 1.0),
                   lambda v: f"{v:.1f}x", lambda v: self.enviar({"zoom": round(v, 2)}), "zoom")

        if cam["flash"]:
            check(a, "Lanterna", "torch")

        # ------------------------------------------------ aba Imagem
        b = self.aba_imagem
        if cam["evMax"] > cam["evMin"]:
            slider(b, "Brilho", cam["evMin"], cam["evMax"], lambda s: s.get("ev", 0),
                   lambda v: f"{round(v) * cam['evStep']:+.1f}", lambda v: self.enviar({"ev": int(round(v))}), "ev",
                   ativo=lambda s: not s.get("aeManual"))
        check(b, "Modo pouca luz", "lowLight")
        check(b, "Travar exposição", "aeLock", ativo=lambda s: not s.get("aeManual"))

        if cam["focus"]:
            check(b, "Foco automático", "afAuto")
            slider(b, "Foco", 0, 1, lambda s: s.get("focus", 0),
                   lambda v: "infinito" if v < 0.005 else f"{v * 100:.0f}%",
                   lambda v: self.enviar({"focus": round(v, 3)}), "focus", ativo=lambda s: not s.get("afAuto"))

        modos = cam["awb"]
        if len(modos) > 1:
            combo(b, "Balanço de branco", [BRANCO.get(m, m) for m in modos],
                  lambda s: modos.index(s.get("awb")) if s.get("awb") in modos else 0,
                  lambda i: self.enviar({"awb": modos[i]}, ja=True))
        check(b, "Travar cor", "awbLock")

        if cam["manual"]:
            check(b, "Exposição manual (ISO / obturador)", "aeManual")
            slider(b, "ISO", cam["isoMin"], cam["isoMax"], lambda s: s.get("iso", 400),
                   lambda v: f"{int(v)}", lambda v: self.enviar({"iso": int(v)}), "iso",
                   ativo=lambda s: bool(s.get("aeManual")))
            ln_min = math.log(cam["expMinNs"])
            ln_max = math.log(min(cam["expMaxNs"], 100_000_000))
            slider(b, "Obturador", 0, 1,
                   lambda s: (math.log(max(s.get("shutterNs", 16_666_666), 1)) - ln_min) / (ln_max - ln_min),
                   lambda v: f"1/{round(1e9 / math.exp(ln_min + (ln_max - ln_min) * v))} s",
                   lambda v: self.enviar({"shutterNs": int(math.exp(ln_min + (ln_max - ln_min) * v))}), "shutter",
                   ativo=lambda s: bool(s.get("aeManual")))

        if cam["stab"]:
            check(b, "Estabilização (aumenta o atraso)", "stab")

        ttk.Button(b, text="Voltar tudo para o automático", command=self._restaurar).pack(anchor="w", pady=(14, 0))

    def _aplicar_estado(self):
        cam = self.cameras.get(self.estado.get("camera"))
        if not cam:
            return
        if self._painel_camera_id != cam["id"]:
            self._montar_painel(cam)
        self._atualizando = True
        try:
            for f in self._atualizadores:
                f(self.estado)
        finally:
            self._atualizando = False
        if bool(self.estado.get("audio")) != self.usar_mic.get():
            self.usar_mic.set(bool(self.estado.get("audio")))
        self._sincronizar_audio()

    def _restaurar(self):
        self.enviar({"ev": 0, "afAuto": True, "awb": "auto", "aeManual": False, "aeLock": False,
                     "awbLock": False, "lowLight": False, "zoom": 1.0}, ja=True)

    # ================================================================== conexao

    def _modo_mudou(self, salvar=True):
        wifi = self.modo.get() == "wifi"
        self.combo_alvo.state(["!disabled"] if wifi else ["disabled"])
        self.bt_procurar.state(["!disabled"] if wifi else ["disabled"])
        if salvar:
            self.cfg["modo"] = self.modo.get()

    def procurar(self):
        self.bt_procurar.state(["disabled"])
        self.status.set("Procurando celulares na rede...")

        def trabalho():
            achados = conexao.procurar_celulares()
            self.eventos.put(("achados", achados))
        threading.Thread(target=trabalho, daemon=True).start()

    def alternar_conexao(self):
        if self.quer_conectar:
            self.desconectar()
        else:
            self.conectar()

    def conectar(self):
        self.quer_conectar = True
        self.bt_conectar.configure(text="Desconectar")
        modo = self.modo.get()
        alvo = self.alvo.get().strip()
        threading.Thread(target=self._conectar_trabalho, args=(modo, alvo), daemon=True).start()

    def _conectar_trabalho(self, modo, alvo):
        st = lambda m: self.eventos.put(("status", m))
        try:
            if modo == "usb":
                conexao.preparar_cabo(st)
                host, tentativas = "127.0.0.1", 8
            else:
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)", alvo)
                host = m.group(1) if m else None
                if not host:
                    st("Procurando celulares na rede...")
                    achados = conexao.procurar_celulares()
                    self.eventos.put(("achados", achados))
                    if not achados:
                        raise conexao.ErroConexao(
                            "Nenhum celular encontrado. O app está aberto no celular? Estão no mesmo Wi-Fi?")
                    host = achados[0][1]
                tentativas = 2
            st(f"Conectando em {host}...")
            for _ in range(tentativas):
                if not self.quer_conectar:
                    return
                c = conexao.ConexaoCelular(host, conexao.STREAM_PORT, self._on_json, self._on_video,
                                           self._on_audio, self._on_fechou)
                try:
                    c.conectar()
                    if c.esperar_hello(4):
                        self.eventos.put(("conectado", c, modo, host))
                        return
                    c.fechar("sem resposta")
                except OSError:
                    pass
                time.sleep(1)
            raise conexao.ErroConexao(
                "Não consegui conectar. Confira se o app está aberto no celular"
                + (" e se o cabo está ligado." if modo == "usb" else " e no mesmo Wi-Fi do PC."))
        except conexao.ErroConexao as e:
            self.eventos.put(("falhou", str(e)))
        except Exception as e:
            self.eventos.put(("falhou", f"Erro: {e}"))

    def desconectar(self):
        self.quer_conectar = False
        c, self.conn = self.conn, None
        if c:
            c.fechar("desconectado")
        self.audio.parar()
        self.bt_conectar.configure(text="Conectar")
        self.status.set("Desconectado.")
        self.previa.configure(image="", text="Sem imagem")
        self._foto = None
        self._painel_vazio()

    def enviar(self, patch, ja=False):
        """Manda ajustes para o celular. Sliders sao agrupados (no maximo ~25 por segundo)."""
        if self._atualizando:
            return
        self.estado.update(patch)
        self._patch.update(patch)
        if ja:
            self._mandar_patch()
        elif self._patch_timer is None:
            self._patch_timer = self.root.after(40, self._mandar_patch)

    def _mandar_patch(self):
        if self._patch_timer is not None:
            self.root.after_cancel(self._patch_timer)
        self._patch_timer = None
        patch, self._patch = self._patch, {}
        if patch and self.conn:
            self.conn.enviar({"t": "set", "s": patch})

    def _pedir_keyframe(self):
        c = self.conn
        if c:
            c.enviar({"t": "keyframe"})

    # --- callbacks da conexao (thread de leitura)
    def _on_json(self, c, msg):
        if "rot" in msg:
            self.video.rotacao_celular = int(msg["rot"])
        self.eventos.put(("json", c, msg))

    def _on_video(self, dados, pts, flags):
        self.video.receber(dados, pts, flags)

    def _on_audio(self, dados):
        self.audio.receber(dados)

    def _on_fechou(self, c, motivo):
        self.eventos.put(("fechou", c, motivo))

    # ================================================================== loop da tela

    def _loop(self):
        try:
            while True:
                self._tratar(self.eventos.get_nowait())
        except queue.Empty:
            pass
        rgb, self._versao_previa = self.video.pegar_previa(self._versao_previa)
        if rgb is not None and self.conn:
            self._mostrar_previa(rgb)
        self.root.after(30, self._loop)

    def _tratar(self, ev):
        tipo = ev[0]
        if tipo == "status":
            self.status.set(ev[1])
        elif tipo == "mostrar":
            self.mostrar()
        elif tipo == "sair":
            self.sair()
        elif tipo == "achados":
            self.achados = ev[1]
            self.bt_procurar.state(["!disabled"] if self.modo.get() == "wifi" else ["disabled"])
            itens = [f"{nome} ({ip})" for nome, ip, _ in self.achados]
            self.combo_alvo["values"] = itens
            if itens and not self.quer_conectar:
                ultimo = self.cfg.get("ultimo_ip", "")
                self.alvo.set(next((i for i in itens if ultimo and ultimo in i), itens[0]))
                self.status.set(f"{len(itens)} celular(es) encontrado(s). Clique em Conectar.")
            elif not itens and not self.quer_conectar:
                self.status.set("Nenhum celular encontrado. Abra o app no celular (mesmo Wi-Fi) ou digite o IP.")
        elif tipo == "conectado":
            _, c, modo, host = ev
            if not self.quer_conectar:
                c.fechar("cancelado")
                return
            self.conn = c
            self.video.reiniciar()
            hello = c.hello
            self.nome_celular = hello.get("name", "Celular")
            self.cameras = {cam["id"]: cam for cam in hello.get("cameras", [])}
            self.estado = dict(hello.get("s", {}))
            self._painel_camera_id = None
            self._aplicar_estado()
            via = "cabo USB" if modo == "usb" else f"Wi-Fi ({host})"
            self.status.set(f"Conectado ao {self.nome_celular} pelo {via}.")
            if modo == "wifi":
                self.cfg["ultimo_ip"] = host
        elif tipo == "json":
            _, c, msg = ev
            if c is not self.conn:
                return
            t = msg.get("t")
            if t in ("state", "hello"):
                self.estado = dict(msg.get("s", {}))
                self._aplicar_estado()
            elif t == "error":
                self.status.set("Celular: " + msg.get("msg", "erro"))
        elif tipo == "fechou":
            _, c, motivo = ev
            if c is not self.conn:
                return
            self.conn = None
            self.audio.parar()
            if self.quer_conectar:
                self.status.set(f"Conexão perdida ({motivo}). Tentando de novo...")
                self.root.after(1500, lambda: self.quer_conectar and self.conn is None and self._reconectar())
        elif tipo == "falhou":
            if self.quer_conectar:
                self.quer_conectar = False
                self.bt_conectar.configure(text="Conectar")
            self.status.set(ev[1])

    def _reconectar(self):
        threading.Thread(target=self._conectar_trabalho, args=(self.modo.get(), self.alvo.get().strip()),
                         daemon=True).start()

    def _mostrar_previa(self, rgb):
        lw = max(self.previa.winfo_width(), 100)
        lh = max(self.previa.winfo_height(), 100)
        img = Image.fromarray(rgb)
        escala = min(lw / img.width, lh / img.height)
        if abs(escala - 1) > 0.02:
            img = img.resize((max(1, int(img.width * escala)), max(1, int(img.height * escala))), Image.BILINEAR)
        self._foto = ImageTk.PhotoImage(img)
        self.previa.configure(image=self._foto, text="")

    def _loop_info(self):
        agora = time.monotonic()
        t0, q0, b0 = self._ultimos_bytes
        c = self.conn
        bytes_ = c.bytes_recebidos if c else 0
        quadros = self.video.quadros
        dt = max(agora - t0, 0.001)
        if c:
            fps = (quadros - q0) / dt
            mbps = max(bytes_ - b0, 0) * 8 / dt / 1e6
            w, h = self.video.tamanho
            self.info.set(f"Recebendo {w}x{h} · {fps:.0f} FPS · {mbps:.1f} Mbps")
        else:
            self.info.set("")
        self._ultimos_bytes = (agora, quadros, bytes_)

        if not camera_virtual.instalada():
            self.info_webcam.set("Webcam virtual não instalada." +
                                 (" Reinstale o Celular Webcam." if getattr(sys, "frozen", False) else ""))
        elif self.video.em_uso:
            w, h, f = self.video.em_uso
            self.info_webcam.set(f"Webcam \"Celular Webcam\" em uso por um app ({w}x{h}, {f} FPS).")
        else:
            self.info_webcam.set("Webcam \"Celular Webcam\" pronta. Escolha ela no OBS, Zoom, Meet...")
        self.root.after(1000, self._loop_info)

    # ================================================================== imagem e audio

    def _rotacao_mudou(self, _=None):
        graus = int(self.rotacao.get().rstrip("°"))
        self.video.rotacao_extra = graus
        self.cfg["rotacao"] = graus

    def _espelhar_mudou(self):
        self.video.espelhar = self.espelhar.get()
        self.cfg["espelhar"] = self.espelhar.get()

    def _mic_mudou(self):
        self.cfg["saida_audio"] = self.saida_audio.get()
        if self.conn and bool(self.estado.get("audio")) != self.usar_mic.get():
            self.enviar({"audio": self.usar_mic.get()}, ja=True)
        if self.audio.tocando:
            self.audio.parar()
        self._sincronizar_audio()

    def _sincronizar_audio(self):
        quer = bool(self.conn) and bool(self.estado.get("audio"))
        if quer and not self.audio.tocando:
            idx = next((i for i, n in self.saidas if n == self.saida_audio.get()), None)
            try:
                self.audio.iniciar(idx)
            except Exception as e:
                self.status.set(f"Não consegui abrir a saída de áudio: {e}")
        elif not quer and self.audio.tocando:
            self.audio.parar()

    def instalar_webcam(self):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vcam", "instalar-camera.ps1")
        self.status.set("Instalando a webcam virtual (o Windows pode pedir permissão)...")

        def trabalho():
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                           creationflags=conexao.NO_WINDOW)
            ok = camera_virtual.instalada()
            self.eventos.put(("status", "Webcam virtual instalada." if ok else "A instalação da webcam virtual falhou."))
            if ok:
                self.root.after(0, self.bt_instalar.pack_forget)
        threading.Thread(target=trabalho, daemon=True).start()

    def sair(self):
        self.quer_conectar = False
        if self.conn:
            self.conn.fechar("saindo")
        self.audio.parar()
        self.cam_virtual.fechar()
        salvar_config(self.cfg)
        self.bandeja.parar()
        self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # nitido em telas com zoom
        # Faz a barra de tarefas usar o icone do app, e nao o do Python
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Fabio.CelularWebcam")
    except Exception:
        pass
    if bandeja.ja_aberto():
        return
    root = tk.Tk()
    icone = conexao.recurso("icone", "celular-webcam.ico")
    if icone:
        root.iconbitmap(default=icone)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
