"""Tema escuro do programa do PC.

Sem bibliotecas extras: os controles arredondados sao imagens geradas aqui mesmo com
o Pillow e entregues ao ttk. Geradas na hora para sairem nitidas em qualquer escala de tela.
"""
import ctypes
import tkinter as tk
from tkinter import font as tkfont, ttk

from PIL import Image, ImageDraw, ImageTk

FUNDO = "#14161b"
VIDEO = "#0b0c0f"
CONTROLE = "#262a33"
CONTROLE_HOVER = "#2f3440"
CONTROLE_PRESS = "#383e4b"
BORDA = "#3a404c"
TEXTO = "#eceef2"
TEXTO2 = "#9aa3b2"
DESATIVADO = "#5f6674"
DESTAQUE = "#4f7cff"
DESTAQUE_HOVER = "#6b92ff"
DESTAQUE_PRESS = "#3f68e0"
ALERTA = "#ff6b6b"

_imagens = []  # o Tk nao guarda referencia: sem isto as imagens somem


def aplicar(root):
    """Monta o tema. Chamar antes de criar os widgets."""
    e = root.winfo_fpixels("1i") / 96  # escala da tela

    def px(v):
        return max(1, round(v * e))

    def foto(img):
        f = ImageTk.PhotoImage(img, master=root)
        _imagens.append(f)
        return f

    def caixa(w, h, raio, cor, borda=None):
        k = 4  # desenha maior e reduz, para suavizar as curvas
        img = Image.new("RGBA", (px(w) * k, px(h) * k), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle(
            (0, 0, img.width - 1, img.height - 1), px(raio) * k, fill=cor, outline=borda, width=k if borda else 0,
        )
        return foto(img.resize((px(w), px(h)), Image.LANCZOS))

    def interruptor(fundo, bola, ligado):
        k = 4
        w, h, folga = px(34), px(18), px(8)
        img = Image.new("RGBA", ((w + folga) * k, h * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), h * k // 2, fill=fundo)
        m = px(3) * k
        lado = h * k - 2 * m
        x = (w * k - m - lado) if ligado else m
        d.ellipse((x, m, x + lado, m + lado), fill=bola)
        return foto(img.resize((w + folga, h), Image.LANCZOS))

    def seta(cor):
        k = 4
        w, h = px(26), px(16)
        img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
        cx, cy, a = w * k // 2, h * k // 2, px(4) * k
        ImageDraw.Draw(img).line(
            [(cx - a, cy - a // 2), (cx, cy + a // 2), (cx + a, cy - a // 2)], fill=cor, width=px(2) * k, joint="curve",
        )
        return foto(img.resize((w, h), Image.LANCZOS))

    def bola(cor):
        k = 4
        lado = px(16)
        img = Image.new("RGBA", (lado * k, lado * k), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((0, 0, lado * k - 1, lado * k - 1), fill=cor)
        return foto(img.resize((lado, lado), Image.LANCZOS))

    def trilho(cor):
        k = 4
        w, h, a = px(24), px(20), px(4)
        img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
        y = (h - a) * k // 2
        ImageDraw.Draw(img).rounded_rectangle((0, y, w * k - 1, y + a * k), a * k // 2, fill=cor)
        return foto(img.resize((w, h), Image.LANCZOS))

    def aba(cor, altura):
        w, h = px(16), px(30)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if altura:
            ImageDraw.Draw(img).rectangle((0, h - px(altura), w, h), fill=cor)
        return foto(img)

    familia = "Segoe UI Variable Text" if "Segoe UI Variable Text" in tkfont.families(root) else "Segoe UI"
    for nome in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        tkfont.nametofont(nome, root=root).configure(family=familia, size=10)

    root.configure(bg=FUNDO)
    # Lista que abre nas caixas de selecao
    root.option_add("*TCombobox*Listbox.background", CONTROLE)
    root.option_add("*TCombobox*Listbox.foreground", TEXTO)
    root.option_add("*TCombobox*Listbox.selectBackground", DESTAQUE)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.highlightThickness", 0)
    root.option_add("*TCombobox*Listbox.relief", "flat")

    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=FUNDO, foreground=TEXTO, troughcolor=FUNDO, bordercolor=FUNDO,
                lightcolor=FUNDO, darkcolor=FUNDO, focuscolor=FUNDO, selectbackground=DESTAQUE,
                selectforeground="#ffffff", insertcolor=TEXTO)
    # O clam clareia o fundo de tudo que esta desativado ou com o mouse em cima
    s.map(".", background=[("disabled", FUNDO), ("active", FUNDO)], foreground=[("disabled", DESATIVADO)])
    s.configure("TLabel", background=FUNDO, foreground=TEXTO)
    s.configure("Status.TLabel", foreground=TEXTO2)
    s.configure("Rotulo.TLabel", foreground=TEXTO2)
    s.configure("BateriaBaixa.TLabel", foreground=ALERTA)

    # ---- botoes
    r = 8
    caixa_btn = dict(border=px(r + 1), padding=0, sticky="nsew")
    s.element_create(
        "Mod.Button.bg", "image", caixa(28, 28, r, CONTROLE),
        ("disabled", caixa(28, 28, r, FUNDO, CONTROLE)),
        ("pressed", caixa(28, 28, r, CONTROLE_PRESS)),
        ("active", caixa(28, 28, r, CONTROLE_HOVER)), **caixa_btn,
    )
    s.element_create(
        "Mod.Accent.bg", "image", caixa(28, 28, r, DESTAQUE),
        ("disabled", caixa(28, 28, r, CONTROLE)),
        ("pressed", caixa(28, 28, r, DESTAQUE_PRESS)),
        ("active", caixa(28, 28, r, DESTAQUE_HOVER)), **caixa_btn,
    )
    s.element_create(
        "Mod.Seg.bg", "image", caixa(28, 28, r, FUNDO),
        ("selected", caixa(28, 28, r, DESTAQUE)),
        ("active", caixa(28, 28, r, CONTROLE)), **caixa_btn,
    )

    def layout_botao(fundo, rotulo="Button"):
        return [(fundo, {"sticky": "nsew", "children": [
            (f"{rotulo}.padding", {"sticky": "nsew", "children": [(f"{rotulo}.label", {"sticky": ""})]}),
        ]})]

    s.layout("TButton", layout_botao("Mod.Button.bg"))
    s.layout("Accent.TButton", layout_botao("Mod.Accent.bg"))
    s.layout("Seg.TRadiobutton", layout_botao("Mod.Seg.bg", "Radiobutton"))
    s.configure("TButton", padding=(px(14), px(7)), foreground=TEXTO, background=FUNDO)
    s.configure("Accent.TButton", padding=(px(18), px(7)), foreground="#ffffff", background=FUNDO)
    s.configure("Seg.TRadiobutton", padding=(px(12), px(7)), foreground=TEXTO2, background=FUNDO)
    s.map("TButton", foreground=[("disabled", DESATIVADO)], background=[("active", FUNDO)])
    s.map("Accent.TButton", foreground=[("disabled", DESATIVADO)], background=[("active", FUNDO)])
    s.map("Seg.TRadiobutton", foreground=[("selected", "#ffffff"), ("active", TEXTO)], background=[("active", FUNDO)])

    # ---- interruptor no lugar da caixa de marcar
    s.element_create(
        "Mod.Check.indicator", "image", interruptor(CONTROLE_PRESS, TEXTO2, False),
        ("disabled", "selected", interruptor(CONTROLE, DESATIVADO, True)),
        ("disabled", interruptor(CONTROLE, DESATIVADO, False)),
        ("selected", interruptor(DESTAQUE, "#ffffff", True)),
        ("active", interruptor(BORDA, TEXTO, False)), sticky="",
    )
    s.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [
        ("Mod.Check.indicator", {"side": "left", "sticky": ""}),
        ("Checkbutton.label", {"side": "left", "sticky": "w"}),
    ]})])
    s.configure("TCheckbutton", padding=(0, px(3)), foreground=TEXTO, background=FUNDO)
    s.map("TCheckbutton", foreground=[("disabled", DESATIVADO)], background=[("active", FUNDO)])

    # ---- caixa de selecao
    s.element_create(
        "Mod.Combo.field", "image", caixa(28, 28, r, CONTROLE),
        ("disabled", caixa(28, 28, r, FUNDO, CONTROLE)),
        ("focus", caixa(28, 28, r, CONTROLE, DESTAQUE)),
        ("active", caixa(28, 28, r, CONTROLE_HOVER)), border=px(r + 1), padding=0, sticky="nsew",
    )
    s.element_create(
        "Mod.Combo.seta", "image", seta(TEXTO2), ("disabled", seta(DESATIVADO)), sticky="",
    )
    s.layout("TCombobox", [("Mod.Combo.field", {"sticky": "nsew", "children": [
        ("Mod.Combo.seta", {"side": "right", "sticky": ""}),
        ("Combobox.padding", {"expand": "1", "sticky": "nsew", "children": [
            ("Combobox.textarea", {"sticky": "nsew"}),
        ]}),
    ]})])
    s.configure("TCombobox", padding=(px(10), px(6), 0, px(6)), foreground=TEXTO, background=FUNDO,
                fieldbackground=CONTROLE, arrowsize=0)
    # Na selecao fixa, o texto nao fica com cara de texto selecionado
    s.map("TCombobox",
          foreground=[("disabled", DESATIVADO)],
          fieldbackground=[("disabled", FUNDO)],
          selectbackground=[("readonly", CONTROLE)],
          selectforeground=[("readonly", TEXTO)])

    # ---- slider
    s.element_create("Mod.Scale.trough", "image", trilho(BORDA), ("disabled", trilho(CONTROLE)),
                     border=(px(4), 0), sticky="ew")
    s.element_create("Mod.Scale.slider", "image", bola(DESTAQUE), ("disabled", bola(CONTROLE_PRESS)),
                     ("pressed", bola(DESTAQUE_PRESS)), ("active", bola(DESTAQUE_HOVER)), sticky="")
    s.layout("Horizontal.TScale", [("Mod.Scale.trough", {"sticky": "nsew", "children": [
        ("Mod.Scale.slider", {"side": "left", "sticky": ""}),
    ]})])
    s.configure("Horizontal.TScale", background=FUNDO)

    # ---- abas: so um traco embaixo da aba ativa
    s.element_create(
        "Mod.Tab.bg", "image", aba(BORDA, 1), ("selected", aba(DESTAQUE, 2)), ("active", aba(TEXTO2, 1)),
        border=(0, 0, 0, px(3)), sticky="nsew",
    )
    s.layout("TNotebook", [("Notebook.client", {"sticky": "nsew"})])
    s.configure("TNotebook", background=FUNDO, borderwidth=0, tabmargins=0)
    s.layout("TNotebook.Tab", [("Mod.Tab.bg", {"sticky": "nsew", "children": [
        ("Notebook.padding", {"sticky": "nsew", "children": [("Notebook.label", {"sticky": ""})]}),
    ]})])
    s.configure("TNotebook.Tab", padding=(px(14), px(7)), background=FUNDO, foreground=TEXTO2, borderwidth=0)
    s.map("TNotebook.Tab", foreground=[("selected", TEXTO), ("active", TEXTO)], background=[("active", FUNDO)],
          padding=[("selected", (px(14), px(7)))])  # o clam muda o espaco da aba ativa e ela "desce"

    # ---- barra de rolagem da lista das caixas de selecao
    s.configure("Vertical.TScrollbar", background=CONTROLE_PRESS, troughcolor=CONTROLE, bordercolor=CONTROLE,
                lightcolor=CONTROLE_PRESS, darkcolor=CONTROLE_PRESS, arrowcolor=TEXTO2, arrowsize=px(12))
    s.map("Vertical.TScrollbar", background=[("active", BORDA)])


def barra_escura(root):
    """Deixa a barra de titulo do Windows escura e da mesma cor do programa."""
    try:
        root.update_idletasks()
        hwnd = ctypes.c_void_p(int(root.wm_frame(), 16))
        dwm = ctypes.windll.dwmapi
        ligado = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ligado), 4)  # DWMWA_USE_IMMERSIVE_DARK_MODE
        r, g, b = root.winfo_rgb(FUNDO)
        cor = ctypes.c_int((r >> 8) | (g >> 8) << 8 | (b >> 8) << 16)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cor), 4)     # DWMWA_CAPTION_COLOR
    except (AttributeError, OSError, ValueError, tk.TclError):
        pass  # so a barra fica clara; o resto do programa funciona igual
