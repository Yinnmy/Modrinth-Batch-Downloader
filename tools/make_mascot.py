"""Gera o mascote do MBD (corvo fofo estilo anime segurando uma maçã verde) e os ícones do app.

Uso:  python tools/make_mascot.py

Saídas em ../assets:
  mascot.png   corvo + maçã, fundo transparente (usado na sidebar e na aba Sobre)
  icon.png     versão "app icon" (quadrado arredondado) 512x512
  icon.ico     ícone do .exe / janela (16 a 256 px)

Tudo é desenhado com Pillow em 4x de resolução e reduzido (antialiasing). Para trocar o visual
basta substituir os arquivos de assets/ por outra arte; nenhum código precisa mudar.
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

S = 4                      # fator de supersampling
W = 1000                   # "tela lógica" 1000x1000
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")

# Paleta (azul-noite combinando com o ícone antigo + verde da maçã)
INK = (22, 25, 42, 255)
FEATHER = (38, 43, 72, 255)
FEATHER_HI = (66, 76, 122, 255)
FEATHER_LO = (27, 30, 52, 255)
BELLY = (74, 84, 132, 255)
BEAK = (255, 186, 82, 255)
BEAK_LO = (233, 140, 52, 255)
BLUSH = (255, 128, 150, 150)
APPLE = (126, 217, 87, 255)
APPLE_LO = (78, 170, 62, 255)
APPLE_DK = (52, 128, 52, 255)
APPLE_HI = (214, 255, 168, 255)
STEM = (96, 62, 40, 255)
LEAF = (88, 190, 84, 255)
LEAF_LO = (52, 140, 66, 255)


def sc(v):
    return v * S


def pts(points):
    return [(sc(x), sc(y)) for x, y in points]


def ellipse(d, cx, cy, rx, ry, **kw):
    d.ellipse([sc(cx - rx), sc(cy - ry), sc(cx + rx), sc(cy + ry)], **kw)


def rot_ellipse(d, cx, cy, rx, ry, angle, **kw):
    """Elipse rotacionada (polígono), para asas e penas."""
    a = math.radians(angle)
    pl = []
    for i in range(72):
        t = i / 72 * 2 * math.pi
        x, y = rx * math.cos(t), ry * math.sin(t)
        pl.append((cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)))
    d.polygon(pts(pl), **kw)


def star(d, cx, cy, r, color):
    """Brilho de 4 pontas (sparkle) típico de anime."""
    p = [(cx, cy - r), (cx + r * .22, cy - r * .22), (cx + r, cy), (cx + r * .22, cy + r * .22),
         (cx, cy + r), (cx - r * .22, cy + r * .22), (cx - r, cy), (cx - r * .22, cy - r * .22)]
    d.polygon(pts(p), fill=color)


def eye(d, cx, cy, flip=1):
    """Olho grande e brilhante com íris verde (combina com a maçã)."""
    ellipse(d, cx, cy, 56, 74, fill=(18, 20, 34, 255))                         # contorno / esclera escura
    ellipse(d, cx, cy + 6, 46, 62, fill=(86, 196, 92, 255))                     # íris
    ellipse(d, cx, cy + 22, 42, 40, fill=(150, 238, 120, 255))                  # luz inferior da íris
    ellipse(d, cx, cy - 2, 22, 34, fill=(14, 16, 28, 255))                      # pupila
    ellipse(d, cx - 16 * flip, cy - 26, 15, 19, fill=(255, 255, 255, 255))     # brilho grande
    ellipse(d, cx + 16 * flip, cy + 30, 7, 8, fill=(255, 255, 255, 235))       # brilho pequeno
    # cílio superior grosso
    d.arc([sc(cx - 60), sc(cy - 80), sc(cx + 60), sc(cy + 40)], 200, 340, fill=(10, 11, 20, 255), width=sc(9))


def draw_mascot(d):
    # ---------- sombra no chão
    ellipse(d, 500, 925, 230, 28, fill=(0, 0, 0, 55))

    # ---------- cauda (penas atrás)
    for ang, ln in ((28, 150), (48, 135), (8, 120)):
        a = math.radians(ang)
        cx, cy = 650 + math.cos(a) * 40, 770 + math.sin(a) * 40
        rot_ellipse(d, cx + math.cos(a) * ln * .5, cy + math.sin(a) * ln * .35, ln * .55, 34, ang * .8, fill=FEATHER_LO)

    # ---------- pés
    for fx in (430, 570):
        d.rounded_rectangle([sc(fx - 34), sc(868), sc(fx + 34), sc(912)], radius=sc(20), fill=BEAK_LO)
        for dx in (-22, 0, 22):
            ellipse(d, fx + dx, 912, 11, 8, fill=BEAK_LO)

    # ---------- corpo
    ellipse(d, 500, 730, 215, 190, fill=FEATHER)
    ellipse(d, 500, 770, 150, 130, fill=BELLY)                                  # barriga clara
    d.arc([sc(300), sc(560), sc(700), sc(920)], 200, 340, fill=FEATHER_HI, width=sc(10))

    # ---------- cabeça grande (chibi)
    ellipse(d, 500, 440, 262, 238, fill=FEATHER)
    d.arc([sc(260), sc(215), sc(740), sc(640)], 205, 300, fill=FEATHER_HI, width=sc(16))     # brilho do topo
    ellipse(d, 500, 560, 200, 110, fill=FEATHER_LO)                              # sombra sob as bochechas
    ellipse(d, 500, 440, 262, 238, fill=FEATHER)
    d.arc([sc(260), sc(215), sc(740), sc(640)], 205, 300, fill=FEATHER_HI, width=sc(14))

    # ---------- topete (ahoge) e penas da cabeça
    for (x, y, tx, ty, wd) in ((500, 215, 470, 100, 34), (530, 220, 590, 120, 30), (468, 222, 410, 150, 26)):
        a = math.atan2(ty - y, tx - x) + math.pi / 2
        ox, oy = math.cos(a) * wd, math.sin(a) * wd
        d.polygon(pts([(x - ox, y - oy), (tx, ty), (x + ox, y + oy)]), fill=FEATHER)
        d.line(pts([(x, y), (tx, ty)]), fill=FEATHER_HI, width=sc(5))

    # ---------- bochechas coradas
    ellipse(d, 338, 535, 52, 30, fill=BLUSH)
    ellipse(d, 662, 535, 52, 30, fill=BLUSH)

    # ---------- olhos
    eye(d, 395, 455, 1)
    eye(d, 605, 455, 1)

    # ---------- bico pequeno
    d.polygon(pts([(462, 515), (538, 515), (500, 575)]), fill=BEAK)
    d.polygon(pts([(472, 540), (528, 540), (500, 575)]), fill=BEAK_LO)
    ellipse(d, 500, 520, 16, 7, fill=(255, 226, 150, 255))
    d.line(pts([(500, 548), (500, 540)]), fill=(150, 80, 30, 255), width=sc(3))

    # ---------- asas (abraçando a maçã)
    rot_ellipse(d, 318, 735, 78, 150, 24, fill=FEATHER_LO)
    rot_ellipse(d, 326, 725, 66, 138, 24, fill=FEATHER)
    rot_ellipse(d, 682, 735, 78, 150, -24, fill=FEATHER_LO)
    rot_ellipse(d, 674, 725, 66, 138, -24, fill=FEATHER)
    d.arc([sc(260), sc(600), sc(390), sc(860)], 110, 160, fill=FEATHER_HI, width=sc(8))
    d.arc([sc(610), sc(600), sc(740), sc(860)], 20, 70, fill=FEATHER_HI, width=sc(8))

    # ---------- maçã verde (segurada na frente)
    ax, ay = 500, 745
    ellipse(d, ax - 52, ay - 8, 100, 96, fill=APPLE)
    ellipse(d, ax + 52, ay - 8, 100, 96, fill=APPLE)
    ellipse(d, ax, ay + 40, 120, 86, fill=APPLE)
    ellipse(d, ax, ay - 92, 26, 16, fill=APPLE_DK)                               # covinha do topo
    ellipse(d, ax + 40, ay + 56, 98, 58, fill=APPLE_LO)                          # sombra inferior
    ellipse(d, ax - 38, ay - 26, 100, 70, fill=APPLE)
    ellipse(d, ax - 52, ay - 10, 98, 90, fill=APPLE)
    ellipse(d, ax - 62, ay - 44, 34, 20, fill=APPLE_HI)                          # brilho
    ellipse(d, ax - 100, ay - 4, 8, 14, fill=APPLE_HI)
    d.line(pts([(ax, ay - 92), (ax + 8, ay - 138)]), fill=STEM, width=sc(12))    # cabo
    d.polygon(pts([(ax + 10, ay - 128), (ax + 82, ay - 170), (ax + 128, ay - 126), (ax + 62, ay - 108)]), fill=LEAF)
    d.line(pts([(ax + 14, ay - 126), (ax + 112, ay - 138)]), fill=LEAF_LO, width=sc(5))

    # ---------- "mãozinhas" (pontas das asas) sobre a maçã
    ellipse(d, 392, 738, 36, 28, fill=FEATHER)
    ellipse(d, 608, 738, 36, 28, fill=FEATHER)
    ellipse(d, 386, 730, 18, 10, fill=FEATHER_HI)
    ellipse(d, 602, 730, 18, 10, fill=FEATHER_HI)

    # ---------- brilhos de anime
    star(d, 230, 250, 36, (255, 247, 205, 255))
    star(d, 780, 210, 26, (200, 255, 190, 255))
    star(d, 815, 330, 16, (255, 247, 205, 255))
    star(d, 190, 380, 14, (200, 255, 190, 255))


def render_mascot(size=1024):
    img = Image.new("RGBA", (W * S, W * S), (0, 0, 0, 0))
    draw_mascot(ImageDraw.Draw(img))
    return img.resize((size, size), Image.LANCZOS)


def render_icon(mascot, size=512):
    """Quadrado arredondado com degradê verde-escuro + o mascote por cima."""
    big = size * 2
    bg = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    grad = Image.new("RGBA", (big, big))
    gp = grad.load()
    c1, c2 = (46, 66, 58), (22, 30, 36)
    for y in range(big):
        for x in range(big):
            t = min(1.0, (x * .35 + y * .65) / big)
            gp[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * .22), fill=255)
    bg.paste(grad, (0, 0), mask)
    glow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([big * .12, big * .12, big * .88, big * .88], fill=(126, 217, 87, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(big * .06))
    bg.alpha_composite(glow)
    m = mascot.resize((int(big * .88), int(big * .88)), Image.LANCZOS)
    bg.alpha_composite(m, (int(big * .06), int(big * .08)))
    return bg.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    mascot = render_mascot(1024)
    mascot.resize((512, 512), Image.LANCZOS).save(os.path.join(ASSETS, "mascot.png"))
    icon = render_icon(mascot, 512)
    icon.save(os.path.join(ASSETS, "icon.png"))
    icon.save(os.path.join(ASSETS, "icon.ico"),
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Arquivos gerados em", ASSETS)


if __name__ == "__main__":
    sys.exit(main())
