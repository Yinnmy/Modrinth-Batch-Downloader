"""Kit de widgets Tkinter com visual flat/arredondado (estilo launcher / Discord).

Tudo é Tkinter puro (Canvas + Frame), sem dependências extras. O tema vive no
dicionário global ``T``; ``set_theme`` recalcula as cores e ``apply_theme``
percorre a árvore de widgets chamando ``retheme()`` em cada um.
"""
import base64
import re
import sys
import time
import tkinter as tk
from tkinter import font as tkfont

SCALE = 1.0
USER_SCALE = 1.0      # fator escolhido pelo usuário em Configurações (multiplica a escala do Windows)
FONTS = {}
T = {}


# ----------------------------------------------------------------- escala / fontes
def enable_dpi_awareness():
    """Evita o texto borrado do Windows em telas com escala (125%, 150%...)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def px(n):
    return int(round(n * SCALE))


def init(root, user_scale=1.0):
    """Calcula a escala (DPI do Windows × tamanho escolhido pelo usuário) e recria as fontes."""
    global SCALE, USER_SCALE
    USER_SCALE = max(0.7, min(2.0, float(user_scale or 1.0)))
    try:
        base = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:
        base = 1.0
    SCALE = base * USER_SCALE
    families = {f.lower(): f for f in tkfont.families(root)}
    pick = lambda options, default: next((families[f.lower()] for f in options if f.lower() in families), default)
    ui = pick(("Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text", "Cantarell",
               "Noto Sans", "DejaVu Sans", "Helvetica", "Arial"), "TkDefaultFont")
    mono = pick(("Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "Courier New"), "TkFixedFont")

    def make(name, family, size, weight="normal"):
        FONTS[name] = tkfont.Font(root=root, family=family, size=-px(size), weight=weight)

    make("body", ui, 13)
    make("bodyb", ui, 13, "bold")
    make("small", ui, 12)
    make("tiny", ui, 11)
    make("btn", ui, 13, "bold")
    make("nav", ui, 14, "bold")
    make("h1", ui, 26, "bold")
    make("h3", ui, 14, "bold")
    make("brand", ui, 16, "bold")
    make("mono", mono, 13)
    make("monob", mono, 13, "bold")


# ----------------------------------------------------------------- cores
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def mix(a, b, t):
    return _hex([x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b))])


def luminance(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def valid_hex(value):
    return isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None


def build_theme(base, accent):
    """Gera a paleta completa a partir de UMA cor de fundo + a cor de destaque."""
    dark = contrast(base, "#FFFFFF") >= contrast(base, "#000000")
    W, K = "#FFFFFF", "#000000"
    if dark:
        t = dict(
            sidebar=mix(base, K, .32), content=base, card=mix(base, W, .04), field=mix(base, K, .24),
            btn=mix(base, W, .10), btn_hover=mix(base, W, .16), btn_down=mix(base, W, .07),
            hover=mix(base, W, .07), border=mix(base, W, .09),
            text="#F2F3F5", scroll=mix(base, W, .16), scroll_hover=mix(base, W, .28),
            ok="#3BA55D", err="#ED4245", warn="#FAA61A", info="#7B8CFF",
        )
        t["nav_hover"] = mix(t["sidebar"], W, .05)
        t["nav_active"] = mix(t["sidebar"], W, .10)
    else:
        t = dict(
            sidebar=mix(base, K, .055), content=base, card=mix(base, W, .78), field=mix(base, K, .045),
            btn=mix(base, K, .07), btn_hover=mix(base, K, .11), btn_down=mix(base, K, .15),
            hover=mix(base, K, .06), border=mix(base, K, .12),
            text="#1F2328", scroll=mix(base, K, .20), scroll_hover=mix(base, K, .32),
            ok="#1E8E4A", err="#D32F2F", warn="#B7791F", info="#4B5BD6",
        )
        t["nav_hover"] = mix(t["sidebar"], K, .05)
        t["nav_active"] = mix(t["sidebar"], K, .10)
    t["dark"] = dark
    t["muted"] = mix(t["text"], base, .40)
    t["subtle"] = mix(t["text"], base, .62)
    t["accent"] = accent
    t["accent_hover"] = mix(accent, W, .14)
    t["accent_down"] = mix(accent, K, .14)
    t["on_accent"] = W if contrast(accent, W) >= contrast(accent, "#101214") else "#101214"
    return t


def set_theme(base, accent):
    T.clear()
    T.update(build_theme(base, accent))


def apply_theme(widget):
    """Chama retheme() em toda a árvore (pai antes do filho)."""
    for child in widget.winfo_children():
        fn = getattr(child, "retheme", None)
        if fn:
            fn()
        apply_theme(child)


def _role_of(parent, default="content"):
    return getattr(parent, "role", default)


def trace_var(widget, variable, callback):
    """Liga ``callback`` às mudanças da variável e remove a ligação quando o widget é destruído.

    Necessário porque a interface pode ser reconstruída (idioma / tamanho) e as variáveis continuam vivas."""
    tid = variable.trace_add("write", lambda *a: callback())

    def cleanup(event, v=variable, t=tid):
        if event.widget is widget:
            try:
                v.trace_remove("write", t)
            except Exception:
                pass
    widget.bind("<Destroy>", cleanup, add="+")


# ----------------------------------------------------------------- imagens
def load_photo(path, size):
    """PhotoImage quadrada de ``size`` px a partir de um arquivo (Pillow se disponível). None se falhar."""
    try:
        from PIL import Image, ImageTk
        img = Image.open(path).convert("RGBA")
        img.thumbnail((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except ImportError:
        pass
    except Exception:
        return None
    try:
        photo = tk.PhotoImage(file=str(path))
        factor = max(1, round(photo.width() / size))
        return photo.subsample(factor, factor) if factor > 1 else photo
    except Exception:
        return None


def photo_from_bytes(data, size):
    """Imagem a partir de bytes (ícones do Modrinth: PNG/WebP/JPEG). Sem Pillow só lê PNG/GIF."""
    if not data:
        return None
    try:
        import io
        from PIL import Image, ImageTk
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        img.thumbnail((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except ImportError:
        pass
    except Exception:
        return None
    try:
        photo = tk.PhotoImage(data=base64.b64encode(data))
        factor = max(1, round(photo.width() / size))
        return photo.subsample(factor, factor) if factor > 1 else photo
    except Exception:
        return None


# ----------------------------------------------------------------- desenho
def round_rect(cv, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y1 + r, x2, y2 - r,
           x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
           x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def draw_icon(cv, name, cx, cy, color, tag="icon"):
    s = SCALE
    w = max(2, round(1.9 * s))
    P = lambda *o: [v * s + (cx if i % 2 == 0 else cy) for i, v in enumerate(o)]
    kw = dict(fill=color, width=w, capstyle="round", joinstyle="round", tags=tag)
    if name == "download":
        cv.create_line(*P(0, -8, 0, 3), **kw)
        cv.create_line(*P(-5, -2, 0, 3, 5, -2), **kw)
        cv.create_line(*P(-8, 8, 8, 8), **kw)
    elif name == "convert":
        cv.create_line(*P(-8, -3, 8, -3), **kw)
        cv.create_line(*P(4, -7, 8, -3, 4, 1), **kw)
        cv.create_line(*P(8, 5, -8, 5), **kw)
        cv.create_line(*P(-4, 1, -8, 5, -4, 9), **kw)
    elif name == "analysis":
        cv.create_oval(*P(-8, -8, 3, 3), outline=color, width=w, tags=tag)
        cv.create_line(*P(3, 3, 8, 8), **kw)
    elif name == "mods":
        for dx, dy in ((-8, -8), (1, -8), (-8, 1), (1, 1)):
            cv.create_rectangle(*P(dx, dy, dx + 7, dy + 7), outline=color, width=w, tags=tag)
    elif name == "settings":
        for y, kx in ((-6, -3), (0, 4), (6, -1)):
            cv.create_line(*P(-8, y, 8, y), **kw)
            cv.create_oval(*P(kx - 2.5, y - 2.5, kx + 2.5, y + 2.5), fill=color, outline=color, tags=tag)
    elif name == "history":      # relógio
        cv.create_oval(*P(-8, -8, 8, 8), outline=color, width=w, tags=tag)
        cv.create_line(*P(0, -4, 0, 0, 4, 3), **kw)
    elif name == "update":       # setas circulares
        cv.create_arc(*P(-7, -7, 7, 7), start=35, extent=280, style="arc", outline=color, width=w, tags=tag)
        cv.create_line(*P(5, -9, 7, -5, 3, -4), **kw)
    elif name == "folder":
        cv.create_line(*P(-9, -5, -3, -5, -1, -2, 9, -2, 9, 7, -9, 7, -9, -5), **kw)
    elif name == "copy":
        cv.create_rectangle(*P(-3, -8, 8, 3), outline=color, width=w, tags=tag)
        cv.create_rectangle(*P(-8, -3, 3, 8), outline=color, width=w, tags=tag)
    elif name == "export":
        cv.create_line(*P(0, 3, 0, -8), **kw)
        cv.create_line(*P(-4, -4, 0, -8, 4, -4), **kw)
        cv.create_line(*P(-8, 3, -8, 8, 8, 8, 8, 3), **kw)
    elif name == "report":
        cv.create_rectangle(*P(-6, -8, 6, 8), outline=color, width=w, tags=tag)
        cv.create_line(*P(-3, -3, 3, -3), **kw)
        cv.create_line(*P(-3, 1, 3, 1), **kw)
        cv.create_line(*P(-3, 5, 1, 5), **kw)
    elif name == "check":
        cv.create_line(*P(-7, 0, -2, 5, 8, -5), **kw)


# ----------------------------------------------------------------- containers
class Box(tk.Frame):
    def __init__(self, parent, role=None, **kw):
        self.role = role or _role_of(parent)
        super().__init__(parent, bg=T[self.role], bd=0, highlightthickness=0, **kw)

    def retheme(self):
        self.configure(bg=T[self.role])


class Label(tk.Label):
    def __init__(self, parent, text="", fg="text", font="body", role=None, **kw):
        self.role = role or _role_of(parent)
        self.fgk = fg
        super().__init__(parent, text=text, bg=T[self.role], fg=T[fg], font=FONTS[font], bd=0,
                         highlightthickness=0, **kw)

    def set_fg(self, key):
        self.fgk = key
        self.configure(fg=T[key])

    def retheme(self):
        self.configure(bg=T[self.role], fg=T[self.fgk])


class Card(tk.Frame):
    """Painel arredondado; os filhos vão em ``card.body``."""

    def __init__(self, parent, pad=18, radius=10, fill="card", border=True):
        self.parent_role = _role_of(parent)
        self.role = self.parent_role
        self.fill, self.radius, self.border = fill, px(radius), border
        super().__init__(parent, bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.cv = tk.Canvas(self, bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = Box(self, role=fill)
        self.body.pack(fill="both", expand=True, padx=px(pad), pady=px(pad))
        self.bind("<Configure>", lambda e: self._draw())

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        self.cv.delete("all")
        if w < 4 or h < 4:
            return
        round_rect(self.cv, 0, 0, w - 1, h - 1, self.radius, fill=T[self.fill],
                   outline=T["border"] if self.border else T[self.fill])

    def retheme(self):
        self.configure(bg=T[self.parent_role])
        self.cv.configure(bg=T[self.parent_role])
        self._draw()


# ----------------------------------------------------------------- botões
class Button(tk.Canvas):
    def __init__(self, parent, text="", command=None, kind="secondary", icon=None, padx=16,
                 height=36, radius=8, font="btn"):
        self.parent_role = _role_of(parent)
        self.text, self.command, self.kind, self.icon = text, command, kind, icon
        self.fontkey, self.radius = font, px(radius)
        self.enabled, self.selected = True, False
        self._hover = self._down = False
        self.w = FONTS[font].measure(text) + 2 * px(padx) + (px(24) if icon else 0)
        self.h = px(height)
        super().__init__(parent, width=self.w, height=self.h, bg=T[self.parent_role], bd=0,
                         highlightthickness=0, cursor="hand2")
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.redraw()

    def _set(self, hover=None, down=None):
        if hover is not None:
            self._hover = hover
        if down is not None:
            self._down = down
        self.redraw()

    def _release(self, e):
        was_down = self._down
        self._set(down=False)
        if was_down and self.enabled and 0 <= e.x <= self.w and 0 <= e.y <= self.h and self.command:
            self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self.redraw()

    def set_selected(self, selected):
        self.selected = selected
        self.redraw()

    def _paint(self):
        if not self.enabled:
            fill = None if self.kind == "ghost" else T["btn"]
            return fill, T["subtle"]
        h, d = self._hover, self._down
        if self.kind == "primary":
            return (T["accent_down"] if d else T["accent_hover"] if h else T["accent"]), T["on_accent"]
        if self.kind == "chip":
            if self.selected:
                return (T["accent_hover"] if h else T["accent"]), T["on_accent"]
            return (T["btn_down"] if d else T["btn_hover"] if h else T["btn"]), (T["text"] if h else T["muted"])
        if self.kind == "ghost":
            return (T["btn"] if h else None), (T["text"] if h else T["muted"])
        return (T["btn_down"] if d else T["btn_hover"] if h else T["btn"]), T["text"]

    def redraw(self):
        self.delete("all")
        self.configure(bg=T[self.parent_role])
        fill, fg = self._paint()
        if fill:
            round_rect(self, 0, 0, self.w - 1, self.h - 1, self.radius, fill=fill, outline=fill)
        cx = self.w / 2 + (px(12) if self.icon else 0)
        if self.icon:
            tw = FONTS[self.fontkey].measure(self.text)
            cx = (self.w + px(24)) / 2
            draw_icon(self, self.icon, cx - tw / 2 - px(14), self.h / 2, fg)
        self.create_text(cx, self.h / 2, text=self.text, fill=fg, font=FONTS[self.fontkey])

    def retheme(self):
        self.redraw()


class Segmented(Box):
    """Grupo de botões-pílula ligado a uma StringVar."""

    def __init__(self, parent, variable, values, labels=None):
        super().__init__(parent)
        self.var, self.chips = variable, {}
        for i, v in enumerate(values):
            b = Button(self, (labels or {}).get(v, v.capitalize()), kind="chip", padx=14, height=34,
                       command=lambda v=v: variable.set(v))
            b.pack(side="left", padx=(0 if i == 0 else px(6), 0))
            self.chips[v] = b
        trace_var(self, variable, self.refresh)
        self.refresh()

    def refresh(self):
        for v, b in self.chips.items():
            b.set_selected(self.var.get() == v)


class Toggle(tk.Canvas):
    def __init__(self, parent, variable):
        self.parent_role = _role_of(parent)
        self.var = variable
        self.w, self.h = px(40), px(22)
        super().__init__(parent, width=self.w, height=self.h, bg=T[self.parent_role], bd=0,
                         highlightthickness=0, cursor="hand2")
        self.bind("<Button-1>", lambda e: variable.set(not variable.get()))
        trace_var(self, variable, self.redraw)
        self.redraw()

    def redraw(self):
        self.delete("all")
        self.configure(bg=T[self.parent_role])
        on = bool(self.var.get())
        round_rect(self, 0, 0, self.w - 1, self.h - 1, self.h / 2,
                   fill=T["accent"] if on else T["btn_hover"], outline=T["accent"] if on else T["btn_hover"])
        d, m = self.h - px(8), px(4)
        x = self.w - m - d if on else m
        self.create_oval(x, m, x + d, m + d, fill="#FFFFFF", outline="#FFFFFF")

    def retheme(self):
        self.redraw()


# ----------------------------------------------------------------- campos
class Field(tk.Frame):
    def __init__(self, parent, textvariable=None, width=14, font="body"):
        self.parent_role = _role_of(parent)
        self.role = self.parent_role
        self.focused = False
        super().__init__(parent, bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.cv = tk.Canvas(self, bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.entry = tk.Entry(self, textvariable=textvariable, width=width, relief="flat", bd=0,
                              highlightthickness=0, font=FONTS[font])
        self.entry.pack(fill="x", expand=True, padx=px(12), pady=px(9))
        self.entry.bind("<FocusIn>", lambda e: self._focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._focus(False))
        self.bind("<Configure>", lambda e: self._draw())
        self._style()

    def _focus(self, state):
        self.focused = state
        self._draw()

    def _style(self):
        self.entry.configure(bg=T["field"], fg=T["text"], insertbackground=T["text"],
                             selectbackground=T["accent"], selectforeground=T["on_accent"],
                             disabledbackground=T["field"], readonlybackground=T["field"])

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        self.cv.delete("all")
        if w < 4:
            return
        round_rect(self.cv, 0, 0, w - 1, h - 1, px(8), fill=T["field"],
                   outline=T["accent"] if self.focused else T["border"])

    def retheme(self):
        self.configure(bg=T[self.parent_role])
        self.cv.configure(bg=T[self.parent_role])
        self._style()
        self._draw()


class Scrollbar(tk.Canvas):
    def __init__(self, parent, command=None, role=None):
        self.parent_role = role or _role_of(parent)
        self.command = command
        self.first, self.last = 0.0, 1.0
        self._drag, self._hover = None, False
        super().__init__(parent, width=px(8), bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Enter>", lambda e: self._hov(True))
        self.bind("<Leave>", lambda e: self._hov(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))

    def _hov(self, state):
        self._hover = state
        self.redraw()

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.redraw()

    def _thumb(self):
        h = max(1, self.winfo_height())
        y1, y2 = self.first * h, self.last * h
        if y2 - y1 < px(28):
            y2 = min(h, y1 + px(28))
            y1 = y2 - px(28)
        return y1, y2, h

    def redraw(self):
        self.delete("all")
        self.configure(bg=T[self.parent_role])
        if self.last - self.first >= 0.999:
            return
        y1, y2, _ = self._thumb()
        w = self.winfo_width()
        col = T["scroll_hover"] if (self._hover or self._drag is not None) else T["scroll"]
        round_rect(self, 1, y1, w - 1, y2, px(4), fill=col, outline=col)

    def _press(self, e):
        y1, y2, _ = self._thumb()
        if y1 <= e.y <= y2:
            self._drag = e.y - y1
        elif self.command:
            self.command("scroll", -1 if e.y < y1 else 1, "pages")

    def _motion(self, e):
        if self._drag is None or not self.command:
            return
        _, _, h = self._thumb()
        self.command("moveto", max(0.0, (e.y - self._drag) / h))

    def retheme(self):
        self.redraw()


class TextBox(tk.Frame):
    """Caixa de texto arredondada com scrollbar fina e placeholder opcional."""

    def __init__(self, parent, font="mono", fill="field", placeholder="", pad=12, on_change=None, on_theme=None):
        self.parent_role = _role_of(parent)
        self.role = fill
        self.fill, self.pad, self.font = fill, pad, font
        self.on_change, self.on_theme, self.placeholder = on_change, on_theme, placeholder
        super().__init__(parent, bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.cv = tk.Canvas(self, bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.sb = Scrollbar(self, role=fill)
        self.sb.pack(side="right", fill="y", padx=(0, px(5)), pady=px(8))
        # width/height mínimos: o tamanho real vem do layout (expand), senão o Text pede 80x24 caracteres
        # e empurra o resto da tela para fora da janela.
        self.text = tk.Text(self, wrap="word", relief="flat", bd=0, highlightthickness=0, undo=True, width=10, height=4,
                            padx=0, pady=0, font=FONTS[font], spacing1=px(2), spacing3=px(2), cursor="xterm")
        self.text.pack(side="left", fill="both", expand=True, padx=(px(pad), px(6)), pady=px(pad - 2))
        self.sb.command = self.text.yview
        self.text.configure(yscrollcommand=self.sb.set)
        self.ph = tk.Label(self.text, text=placeholder, justify="left", anchor="nw", bd=0,
                           highlightthickness=0, font=FONTS[font])
        if placeholder:
            self.ph.place(x=0, y=0)
            self.ph.bind("<Button-1>", lambda e: self.text.focus_set())
        self.text.bind("<<Modified>>", self._modified)
        self.bind("<Configure>", lambda e: self._draw())
        self._style()

    def _modified(self, _e=None):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self.placeholder:
            if self.text.get("1.0", "end-1c"):
                self.ph.place_forget()
            else:
                self.ph.place(x=0, y=0)
        if self.on_change:
            self.on_change()

    def _style(self):
        bg = T[self.fill]
        self.text.configure(bg=bg, fg=T["text"], insertbackground=T["text"], selectbackground=T["accent"],
                            selectforeground=T["on_accent"], inactiveselectbackground=mix(bg, T["accent"], .5))
        self.ph.configure(bg=bg, fg=T["subtle"])
        if self.on_theme:
            self.on_theme(self.text)

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        self.cv.delete("all")
        if w < 4:
            return
        round_rect(self.cv, 0, 0, w - 1, h - 1, px(8), fill=T[self.fill],
                   outline=T["border"] if self.fill != "field" else T["border"])

    def retheme(self):
        self.configure(bg=T[self.parent_role])
        self.cv.configure(bg=T[self.parent_role])
        self._style()
        self._draw()


class ProgressBar(tk.Canvas):
    def __init__(self, parent, height=4):
        self.parent_role = _role_of(parent)
        self.value, self.maximum = 0, 1
        super().__init__(parent, height=px(height), bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.bind("<Configure>", lambda e: self.redraw())

    def set(self, value, maximum=None):
        if maximum is not None:
            self.maximum = max(1, maximum)
        self.value = max(0, min(value, self.maximum))
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        self.configure(bg=T[self.parent_role])
        self.create_rectangle(0, 0, w, h, fill=T["field"], outline="")
        fw = w * self.value / self.maximum
        if fw > 0:
            self.create_rectangle(0, 0, fw, h, fill=T["accent"], outline="")

    def retheme(self):
        self.redraw()


class StatusDot(tk.Canvas):
    def __init__(self, parent, size=9):
        self.parent_role = _role_of(parent)
        self.s, self.key = px(size), "subtle"
        super().__init__(parent, width=self.s, height=self.s, bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.redraw()

    def set_kind(self, key):
        self.key = key
        self.redraw()

    def redraw(self):
        self.delete("all")
        self.configure(bg=T[self.parent_role])
        self.create_oval(0, 0, self.s - 1, self.s - 1, fill=T[self.key], outline=T[self.key])

    def retheme(self):
        self.redraw()


# ----------------------------------------------------------------- sidebar
class Logo(tk.Canvas):
    """Mascote do app. Se ``image`` (PhotoImage) for dado, desenha ele; senão usa o logo desenhado (placeholder)."""

    def __init__(self, parent, size=38, image=None):
        self.parent_role = _role_of(parent)
        self.s = px(size)
        self.image = image
        super().__init__(parent, width=self.s, height=self.s, bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.redraw()

    def redraw(self):
        self.delete("all")
        self.configure(bg=T[self.parent_role])
        if self.image is not None:
            self.create_image(self.s / 2, self.s / 2, image=self.image)
            return
        round_rect(self, 0, 0, self.s - 1, self.s - 1, px(11), fill=T["accent"], outline=T["accent"])
        draw_icon(self, "download", self.s / 2, self.s / 2, T["on_accent"])

    def retheme(self):
        self.redraw()


class NavItem(tk.Canvas):
    def __init__(self, parent, text, icon, command):
        self.parent_role = _role_of(parent)
        self.text, self.icon, self.command = text, icon, command
        self.active = self._hover = False
        super().__init__(parent, height=px(40), bg=T[self.parent_role], bd=0, highlightthickness=0, cursor="hand2")
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Enter>", lambda e: self._hov(True))
        self.bind("<Leave>", lambda e: self._hov(False))
        self.bind("<Button-1>", lambda e: self.command())

    def _hov(self, state):
        self._hover = state
        self.redraw()

    def set_active(self, state):
        self.active = state
        self.redraw()

    def redraw(self):
        self.delete("all")
        self.configure(bg=T[self.parent_role])
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        if self.active or self._hover:
            col = T["nav_active"] if self.active else T["nav_hover"]
            round_rect(self, 0, 0, w - 1, h - 1, px(8), fill=col, outline=col)
        if self.active:
            round_rect(self, 0, h / 2 - px(10), px(4), h / 2 + px(10), px(2), fill=T["accent"], outline=T["accent"])
        fg = T["text"] if (self.active or self._hover) else T["muted"]
        draw_icon(self, self.icon, px(28), h / 2, T["accent"] if self.active else fg)
        self.create_text(px(52), h / 2, text=self.text, anchor="w", fill=fg, font=FONTS["nav"])

    def retheme(self):
        self.redraw()


# ----------------------------------------------------------------- seletores de aparência
class ThemeSwatch(tk.Canvas):
    def __init__(self, parent, name, label, base_fn, accent_fn, selected_fn, command):
        self.parent_role = _role_of(parent)
        self.name, self.label = name, label
        self.base_fn, self.accent_fn, self.selected_fn = base_fn, accent_fn, selected_fn
        self.w, self.ph = px(80), px(52)
        super().__init__(parent, width=self.w, height=self.ph + px(24), bg=T[self.parent_role], bd=0,
                         highlightthickness=0, cursor="hand2")
        self.bind("<Button-1>", lambda e: command(name))
        self.redraw()

    def redraw(self):
        self.delete("all")
        self.configure(bg=T[self.parent_role])
        p = build_theme(self.base_fn(), self.accent_fn())
        w, h, sel = self.w, self.ph, self.selected_fn()
        edge = T["accent"] if sel else T["border"]
        lw = 2 if sel else 1
        round_rect(self, 1, 1, w - 2, h - 1, px(9), fill=p["content"], outline=edge, width=lw)
        round_rect(self, 2, 2, px(26), h - 2, px(8), fill=p["sidebar"], outline=p["sidebar"])
        self.create_rectangle(px(14), 2, px(26), h - 2, fill=p["sidebar"], outline=p["sidebar"])
        round_rect(self, px(33), px(9), w - px(10), px(25), px(4), fill=p["card"], outline=p["border"])
        round_rect(self, px(33), px(32), px(33) + px(30), px(38), px(3), fill=p["accent"], outline=p["accent"])
        self.create_text(w / 2, h + px(13), text=self.label, fill=T["text"] if sel else T["muted"], font=FONTS["small"])

    def retheme(self):
        self.redraw()


class ColorDot(tk.Canvas):
    def __init__(self, parent, color, selected_fn, command):
        self.parent_role = _role_of(parent)
        self.color, self.selected_fn = color, selected_fn
        self.s = px(34)
        super().__init__(parent, width=self.s, height=self.s, bg=T[self.parent_role], bd=0,
                         highlightthickness=0, cursor="hand2")
        self.bind("<Button-1>", lambda e: command(color))
        self.redraw()

    def redraw(self):
        self.delete("all")
        self.configure(bg=T[self.parent_role])
        m = px(4)
        if self.selected_fn():
            self.create_oval(1, 1, self.s - 2, self.s - 2, outline=T["text"], width=2)
            m = px(7)
        self.create_oval(m, m, self.s - m - 1, self.s - m - 1, fill=self.color, outline=self.color)

    def retheme(self):
        self.redraw()


# ----------------------------------------------------------------- novos widgets (v5)
class ScrollFrame(tk.Frame):
    """Área rolável com a scrollbar fina do app. Coloque os filhos em ``scroll.inner``."""

    def __init__(self, parent, role=None):
        self.role = role or _role_of(parent)
        self.parent_role = self.role
        super().__init__(parent, bg=T[self.role], bd=0, highlightthickness=0)
        self.cv = tk.Canvas(self, bg=T[self.role], bd=0, highlightthickness=0)
        self.sb = Scrollbar(self, role=self.role)
        self.sb.pack(side="right", fill="y", padx=(px(6), 0))
        self.cv.pack(side="left", fill="both", expand=True)
        self.sb.command = self.cv.yview
        self.cv.configure(yscrollcommand=self.sb.set)
        self.inner = Box(self.cv, role=self.role)
        self._win = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self._win, width=e.width))
        # Um único bind_all por frame; o handler confere se o ponteiro está dentro deste frame
        # (Enter/Leave também disparam ao passar para widgets filhos, por isso não servem aqui).
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.bind_all("<Button-4>", lambda e: self._wheel(e, -1), add="+")
        self.bind_all("<Button-5>", lambda e: self._wheel(e, 1), add="+")

    def _inside(self, e):
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except Exception:
            return False
        while w is not None:
            if w is self:
                return True
            w = getattr(w, "master", None)
        return False

    def _wheel(self, e, direction=None):
        try:
            if not self._inside(e):
                return
            first, last = self.cv.yview()
            if last - first >= 0.999:       # nada para rolar
                return
            if direction is None:
                direction = -int(e.delta / 120) or (-1 if e.delta > 0 else 1)
            self.cv.yview_scroll(direction * 3, "units")
        except tk.TclError:                 # frame já destruído (interface reconstruída)
            pass

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self.cv.yview_moveto(0)

    def retheme(self):
        self.configure(bg=T[self.role])
        self.cv.configure(bg=T[self.role])


class Dropdown(Field):
    """Campo com lista suspensa (ex.: versões do Minecraft vindas da API). Continua aceitando texto digitado."""

    def __init__(self, parent, textvariable, values=(), width=12, on_pick=None):
        super().__init__(parent, textvariable=textvariable, width=width)
        self.var, self.values, self.on_pick = textvariable, list(values), on_pick
        self._popup, self._closed_at = None, 0.0
        self.entry.pack_forget()
        self.arrow = tk.Canvas(self, width=px(26), height=px(18), bg=T["field"], bd=0, highlightthickness=0, cursor="hand2")
        self.arrow.pack(side="right", padx=(0, px(6)))
        self.entry.pack(side="left", fill="x", expand=True, padx=(px(12), 0), pady=px(9))
        self.arrow.bind("<Button-1>", lambda e: self.toggle())
        self.entry.bind("<Down>", lambda e: self.open())
        self.bind("<Destroy>", lambda e: self.close() if e.widget is self else None, add="+")
        self._draw_arrow()

    def set_values(self, values):
        self.values = list(values)

    def _draw_arrow(self):
        self.arrow.delete("all")
        cx, cy, d = px(13), px(9), px(4)
        self.arrow.create_line(cx - d, cy - d // 2, cx, cy + d // 2 + 1, cx + d, cy - d // 2,
                               fill=T["muted"], width=2, capstyle="round", joinstyle="round")

    def toggle(self):
        self.close() if self._popup is not None else self.open()

    def open(self):
        if self._popup is not None or not self.values or time.monotonic() - self._closed_at < 0.2:
            return
        top = tk.Toplevel(self)
        top.withdraw()
        top.overrideredirect(True)
        top.configure(bg=T["border"])
        inner = tk.Frame(top, bg=T["field"], bd=0, highlightthickness=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        lb = tk.Listbox(inner, height=min(10, len(self.values)), bd=0, highlightthickness=0, relief="flat",
                        activestyle="none", exportselection=False, font=FONTS["body"], bg=T["field"], fg=T["text"],
                        selectbackground=T["accent"], selectforeground=T["on_accent"])
        sb = Scrollbar(inner, role="field")
        sb.pack(side="right", fill="y", padx=(0, px(3)), pady=px(4))
        lb.pack(side="left", fill="both", expand=True, padx=px(4), pady=px(4))
        sb.command = lb.yview
        lb.configure(yscrollcommand=sb.set)
        for v in self.values:
            lb.insert("end", v)
        current = self.var.get()
        if current in self.values:
            idx = self.values.index(current)
            lb.selection_set(idx)
            lb.see(idx)
        lb.bind("<Motion>", lambda e: (lb.selection_clear(0, "end"), lb.selection_set(lb.nearest(e.y))))
        lb.bind("<ButtonRelease-1>", lambda e: self._pick(lb.nearest(e.y)))
        lb.bind("<Return>", lambda e: self._pick(lb.curselection()[0]) if lb.curselection() else None)
        lb.bind("<Escape>", lambda e: self.close())
        lb.bind("<FocusOut>", lambda e: self.after(90, self.close))
        self._popup = top
        top.update_idletasks()
        x, y = self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + px(2)
        top.geometry(f"{max(self.winfo_width(), px(150))}x{top.winfo_reqheight()}+{x}+{y}")
        top.deiconify()
        top.lift()
        top.after(10, lb.focus_force)

    def _pick(self, index):
        if 0 <= index < len(self.values):
            self.var.set(self.values[index])
            if self.on_pick:
                self.on_pick(self.values[index])
        self.close()

    def close(self):
        if self._popup is not None:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None
            self._closed_at = time.monotonic()

    def retheme(self):
        super().retheme()
        self.arrow.configure(bg=T["field"])
        self._draw_arrow()


class Pill(tk.Canvas):
    """Etiqueta arredondada pequena (status, tipo de projeto). ``color`` é uma chave do tema (ok, warn, err, muted…)."""

    def __init__(self, parent, text="", color="muted", font="tiny"):
        self.parent_role = _role_of(parent)
        self.text, self.color, self.fontkey = text, color, font
        super().__init__(parent, bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.redraw()

    def set(self, text, color=None):
        self.text = text
        self.color = color or self.color
        self.redraw()

    def redraw(self):
        self.delete("all")
        self.configure(bg=T[self.parent_role])
        w = FONTS[self.fontkey].measure(self.text) + px(16)
        h = FONTS[self.fontkey].metrics("linespace") + px(6)
        self.configure(width=w, height=h)
        fill = mix(T[self.parent_role], T[self.color], .2)
        round_rect(self, 0, 0, w - 1, h - 1, h / 2, fill=fill, outline=fill)
        self.create_text(w / 2, h / 2, text=self.text, fill=T[self.color], font=FONTS[self.fontkey])

    def retheme(self):
        self.redraw()


class IconTile(tk.Canvas):
    """Quadradinho do ícone de um projeto: mostra a imagem ou, sem ela, a inicial do nome na cor de destaque."""

    def __init__(self, parent, size=36, image=None, letter="?"):
        self.parent_role = _role_of(parent)
        self.s, self.image, self.letter = px(size), image, (letter or "?")[:1].upper()
        super().__init__(parent, width=self.s, height=self.s, bg=T[self.parent_role], bd=0, highlightthickness=0)
        self.redraw()

    def redraw(self):
        self.delete("all")
        self.configure(bg=T[self.parent_role])
        if self.image is not None:
            self.create_image(self.s / 2, self.s / 2, image=self.image)
            return
        fill = mix(T[self.parent_role], T["accent"], .30)
        round_rect(self, 0, 0, self.s - 1, self.s - 1, px(8), fill=fill, outline=fill)
        self.create_text(self.s / 2, self.s / 2, text=self.letter, fill=T["text"], font=FONTS["bodyb"])

    def retheme(self):
        self.redraw()
