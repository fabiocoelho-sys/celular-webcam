"""Conexao com o celular: busca na rede (Wi-Fi), cabo USB (adb) e o protocolo TCP.

Protocolo (igual ao StreamServer.kt): tipo (1 byte) + tamanho (4 bytes, big-endian) + conteudo.
  1 = JSON                3 = video H.264 (pts 8 bytes + flags 1 byte + dados)
  4 = audio PCM 16 bits mono 48 kHz (pts 8 bytes + amostras)
"""
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time

STREAM_PORT = 27183
DISCOVERY_PORT = 27184
TYPE_JSON, TYPE_VIDEO, TYPE_AUDIO = 1, 3, 4
PACKAGE = "com.fabio.celularwebcam"
NO_WINDOW = 0x08000000  # nao abre janela preta do adb

AQUI = os.path.dirname(os.path.abspath(__file__))
# Instalado (exe do PyInstaller): adb/, apk/ e icone/ ficam ao lado do exe
PASTA_APP = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else AQUI


def recurso(*partes):
    """Caminho de um arquivo do app, tanto instalado quanto rodando do codigo-fonte."""
    for base in (PASTA_APP, os.path.join(AQUI, "..")):
        caminho = os.path.normpath(os.path.join(base, *partes))
        if os.path.exists(caminho):
            return caminho
    return None


class ErroConexao(Exception):
    pass


# --------------------------------------------------------------------- Wi-Fi

def _ips_locais():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return ips


def procurar_celulares(tempo=1.5):
    """Manda um broadcast na rede e devolve [(nome, ip, porta)] dos celulares com o app aberto."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind(("", 0))
    s.settimeout(0.2)
    destinos = {"255.255.255.255"} | {ip.rsplit(".", 1)[0] + ".255" for ip in _ips_locais()}
    achados = {}
    fim = time.time() + tempo
    proximo_envio = 0.0
    try:
        while time.time() < fim:
            if time.time() >= proximo_envio:
                for d in destinos:
                    try:
                        s.sendto(b"CELWEBCAM?", (d, DISCOVERY_PORT))
                    except OSError:
                        pass
                proximo_envio = time.time() + 0.5
            try:
                data, addr = s.recvfrom(2048)
                info = json.loads(data.decode("utf-8"))
                if info.get("app") == "celular-webcam":
                    achados[addr[0]] = (info.get("name", "Celular"), addr[0], int(info.get("port", STREAM_PORT)))
            except (socket.timeout, ValueError):
                pass
    finally:
        s.close()
    return list(achados.values())


# --------------------------------------------------------------------- cabo USB

def achar_adb():
    candidatos = [
        os.path.join(PASTA_APP, "adb", "adb.exe"),
        os.path.join(AQUI, "adb", "adb.exe"),
        shutil.which("adb"),
        os.path.join(os.environ.get("ANDROID_HOME", ""), "platform-tools", "adb.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
    ]
    for c in candidatos:
        if c and os.path.isfile(c):
            return c
    return None


def _adb(adb, *args, timeout=15):
    r = subprocess.run([adb, *args], capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    return (r.stdout or "") + (r.stderr or "")


def preparar_cabo(status=lambda msg: None):
    """Liga o tunel USB (adb forward) e abre o app no celular. Instala o app se precisar."""
    adb = achar_adb()
    if not adb:
        raise ErroConexao("Não encontrei o adb (necessário para o cabo USB).")
    status("Procurando celular no cabo USB...")
    saida = _adb(adb, "devices")
    linhas = [l.split("\t") for l in saida.splitlines()[1:] if "\t" in l]
    prontos = [l[0] for l in linhas if l[1].strip() == "device"]
    if not prontos:
        if any(l[1].strip() == "unauthorized" for l in linhas):
            raise ErroConexao("Autorize este computador na tela do celular (pergunta da Depuração USB).")
        raise ErroConexao("Nenhum celular no cabo. Ative a 'Depuração USB' nas opções do desenvolvedor do celular.")
    serial = prontos[0]

    _adb(adb, "-s", serial, "forward", f"tcp:{STREAM_PORT}", f"tcp:{STREAM_PORT}")

    status("Abrindo o app no celular...")
    saida = _adb(adb, "-s", serial, "shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity")
    if "Error" in saida or "does not exist" in saida:
        apk = recurso("apk", "celular-webcam.apk")
        if not apk:
            raise ErroConexao("O app não está instalado no celular.")
        status("Instalando o app no celular...")
        saida = _adb(adb, "-s", serial, "install", "-r", apk, timeout=120)
        if "Success" not in saida:
            raise ErroConexao("Não consegui instalar o app no celular: " + saida.strip()[-200:])
        _adb(adb, "-s", serial, "shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity")
    return serial


# --------------------------------------------------------------------- conexao TCP

class ConexaoCelular:
    """Uma conexao TCP com o app do celular. Os callbacks rodam na thread de leitura."""

    def __init__(self, host, port, on_json, on_video, on_audio, on_closed):
        self.host = host
        self.port = port
        self.on_json = on_json
        self.on_video = on_video
        self.on_audio = on_audio
        self.on_closed = on_closed
        self.sock = None
        self.hello = None
        self._hello_event = threading.Event()
        self._send_lock = threading.Lock()
        self._closed = False
        self.bytes_recebidos = 0

    def conectar(self, timeout=4.0):
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self.sock.settimeout(10.0)
        threading.Thread(target=self._ler, name="celular-leitura", daemon=True).start()

    def esperar_hello(self, timeout=4.0):
        return self._hello_event.wait(timeout) and not self._closed

    def enviar(self, obj):
        data = json.dumps(obj).encode("utf-8")
        try:
            with self._send_lock:
                self.sock.sendall(struct.pack(">BI", TYPE_JSON, len(data)) + data)
        except OSError:
            self.fechar("erro ao enviar")

    def fechar(self, motivo="fechada"):
        if self._closed:
            return
        self._closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self._hello_event.set()
        self.on_closed(self, motivo)

    def _ler_exato(self, n):
        buf = bytearray(n)
        view = memoryview(buf)
        pos = 0
        while pos < n:
            r = self.sock.recv_into(view[pos:], n - pos)
            if r == 0:
                raise ConnectionError("o celular fechou a conexão")
            pos += r
        return buf

    def _ler(self):
        motivo = "fechada"
        try:
            while not self._closed:
                tipo, tamanho = struct.unpack(">BI", self._ler_exato(5))
                dados = self._ler_exato(tamanho)
                self.bytes_recebidos += tamanho + 5
                if tipo == TYPE_VIDEO:
                    pts, flags = struct.unpack_from(">qB", dados)
                    self.on_video(memoryview(dados)[9:], pts, flags)
                elif tipo == TYPE_AUDIO:
                    self.on_audio(bytes(memoryview(dados)[8:]))
                elif tipo == TYPE_JSON:
                    msg = json.loads(dados.decode("utf-8"))
                    if msg.get("t") == "hello":
                        self.hello = msg
                        self._hello_event.set()
                    self.on_json(self, msg)
        except socket.timeout:
            motivo = "o celular parou de responder"
        except (OSError, ConnectionError, ValueError, struct.error) as e:
            motivo = str(e) or "conexão perdida"
        self.fechar(motivo)
