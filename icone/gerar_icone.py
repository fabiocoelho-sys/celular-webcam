"""Gera o icone do Celular Webcam: .ico do Windows, PNGs e os icones do app Android.

Uso: python gerar_icone.py   (precisa do Pillow; o ambiente do pc/iniciar.bat ja tem)
"""
import os

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

AQUI = os.path.dirname(os.path.abspath(__file__))
RES_ANDROID = os.path.join(AQUI, "..", "android", "app", "src", "main", "res")
S = 1024  # desenha grande e reduz (bordas suaves)


def gradiente(w, h, c1, c2):
    """Gradiente diagonal (canto superior esquerdo -> inferior direito)."""
    y, x = np.mgrid[0:h, 0:w]
    t = ((x + y) / float(w + h - 2))[..., None]
    rgb = np.array(c1) * (1 - t) + np.array(c2) * t
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def desenhar(tamanho=S, fundo_quadrado=False):
    k = tamanho / S
    img = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))

    # fundo: quadrado arredondado com gradiente azul -> roxo
    fundo = gradiente(tamanho, tamanho, (37, 99, 235), (139, 61, 230)).convert("RGBA")
    mascara = Image.new("L", (tamanho, tamanho), 0)
    raio = 0 if fundo_quadrado else int(220 * k)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, tamanho - 1, tamanho - 1), raio, fill=255)
    img.paste(fundo, (0, 0), mascara)

    # brilho suave no alto
    brilho = Image.new("L", (tamanho, tamanho), 0)
    ImageDraw.Draw(brilho).ellipse((-200 * k, -520 * k, 1224 * k, 420 * k), fill=60)
    brilho = ImageChops.multiply(brilho.filter(ImageFilter.GaussianBlur(80 * k)), mascara)
    img = Image.composite(Image.new("RGBA", img.size, (255, 255, 255, 255)), img, brilho)

    d = ImageDraw.Draw(img)

    # sombra do celular
    sombra = Image.new("L", (tamanho, tamanho), 0)
    ImageDraw.Draw(sombra).rounded_rectangle((300 * k, 210 * k, 724 * k, 870 * k), int(80 * k), fill=110)
    sombra = sombra.filter(ImageFilter.GaussianBlur(28 * k))
    img = Image.composite(Image.new("RGBA", img.size, (20, 10, 60, 255)), img,
                          ImageChops.multiply(sombra, mascara))
    d = ImageDraw.Draw(img)

    # celular (de pe), corpo branco
    corpo = (290 * k, 180 * k, 714 * k, 840 * k)
    d.rounded_rectangle(corpo, int(80 * k), fill=(255, 255, 255, 255))
    # tela escura
    d.rounded_rectangle((320 * k, 220 * k, 684 * k, 800 * k), int(54 * k), fill=(24, 30, 56, 255))

    # lente grande no meio da tela
    cx, cy = 502 * k, 510 * k
    for r, cor in (
        (150, (235, 238, 250)),   # anel claro
        (126, (40, 46, 80)),      # anel escuro
        (98, (30, 64, 175)),      # vidro
        (62, (59, 130, 246)),
        (30, (14, 20, 48)),       # pupila
    ):
        d.ellipse((cx - r * k, cy - r * k, cx + r * k, cy + r * k), fill=cor)
    # reflexos da lente
    d.ellipse((cx - 70 * k, cy - 78 * k, cx - 28 * k, cy - 36 * k), fill=(255, 255, 255, 230))
    d.ellipse((cx + 34 * k, cy + 36 * k, cx + 52 * k, cy + 54 * k), fill=(255, 255, 255, 150))

    # ponto vermelho "ao vivo"
    d.ellipse((588 * k, 252 * k, 640 * k, 304 * k), fill=(239, 68, 68, 255))

    # ondas de sinal (transmitindo), a direita do celular
    for i, r in enumerate((80, 135, 190)):
        caixa = (700 * k - r * k, 330 * k - r * k, 700 * k + r * k, 330 * k + r * k)
        d.arc(caixa, -60, 30, fill=(255, 255, 255, 255 - i * 55), width=int(28 * k))
    return img


def main():
    os.makedirs(AQUI, exist_ok=True)
    grande = desenhar()
    for t in (1024, 512, 256):
        grande.resize((t, t), Image.LANCZOS).save(os.path.join(AQUI, f"celular-webcam-{t}.png"))
    grande.save(os.path.join(AQUI, "celular-webcam.ico"),
                sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])

    # Android: icone do app em cada densidade
    densidades = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    for nome, t in densidades.items():
        pasta = os.path.join(RES_ANDROID, f"mipmap-{nome}")
        os.makedirs(pasta, exist_ok=True)
        grande.resize((t, t), Image.LANCZOS).save(os.path.join(pasta, "ic_launcher.png"))
    print("icones gerados")


if __name__ == "__main__":
    main()
