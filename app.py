"""Modrinth Batch Downloader V5 — interface (Tkinter).

A lógica (API, downloads paralelos, hashes, conflitos, atualizações) fica em ``core.py``;
as traduções em ``i18n.py``; os widgets em ``ui_kit.py``. Este arquivo monta as telas e liga tudo.
"""
import json
import os
import queue
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, colorchooser

import core
import ui_kit as ui
from core import APP_NAME, APP_VERSION, LOADERS
from i18n import tr, set_language, get_language, LANGUAGES
from ui_kit import (T, px, Box, Label, Card, Button, Field, TextBox, Toggle, Segmented, ProgressBar,
                    StatusDot, Logo, NavItem, ThemeSwatch, ColorDot, ScrollFrame, Dropdown, Pill, IconTile)

CONFIG_PATH = Path.home() / ".modrinth_batch_downloader.json"
HISTORY_PATH = Path.home() / ".modrinth_batch_downloader_history.json"
HISTORY_LIMIT = 30
PREVIEW_LIMIT = 30

# ----------------------------------------------------------------------------- aparência
DEFAULT_ACCENT = "#55B879"
LOADER_LABELS = {"fabric": "Fabric", "forge": "Forge", "neoforge": "NeoForge", "quilt": "Quilt"}
# Cada tema é só a cor de fundo; sidebar, cards, campos e bordas são derivados dela (ui_kit.build_theme).
THEME_BG = {"Midnight": "#313338", "Graphite": "#262626", "Forest": "#202B25",
            "Ocean": "#1D2733", "Dusk": "#2B2740", "Light": "#F2F3F5"}
THEME_ORDER = ("Midnight", "Graphite", "Forest", "Ocean", "Dusk", "Light")
ACCENT_PRESETS = ("#55B879", "#5865F2", "#3B82F6", "#A855F7", "#EC4899", "#F97316", "#EAB308", "#EF4444")
DEFAULT_CUSTOM_BG = "#2B2D31"
UI_SCALES = ("90", "100", "115", "130", "150")


def log_kind(msg):
    """Classifica uma linha de log pelo prefixo [TAG] (usado só nas linhas geradas pela própria interface)."""
    import re
    m = re.match(r"\s*\[([^\]]+)\]", msg)
    if not m:
        return None
    tag = m.group(1).upper()
    if tag == "OK":
        return "ok"
    if any(k in tag for k in ("ERRO", "ERROR", "FALHA", "FAIL", "SECURITY")):
        return "err"
    if any(k in tag for k in ("AVISO", "WARN", "CONFLITO", "CONFLICT", "RETRY", "INCOMPAT", "SEM COMPAT")):
        return "warn"
    if any(k in tag for k in ("BAIXANDO", "DOWNLOADING", "ATUALIZA", "UPDATE", "CONVERS", "AN\u00c1LISE", "ANALYSIS")):
        return "accent"
    return "muted"


def resource_path(relative):
    """Caminho de um arquivo embutido; funciona pelo Python e dentro do .exe do PyInstaller."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)


def app_dir():
    """Pasta do app (ao lado do .exe quando empacotado): onde ficam o ícone personalizado e os assets."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def ellipsize(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


class FileRow(Box):
    """Linha de um download em andamento: nome, MB baixados, velocidade e barra de progresso."""

    def __init__(self, parent):
        super().__init__(parent)
        top = Box(self)
        top.pack(fill="x")
        self.name = Label(top, "", font="small")
        self.name.pack(side="left")
        self.stats = Label(top, "", fg="muted", font="tiny")
        self.stats.pack(side="right")
        self.bar = ProgressBar(self, height=4)
        self.bar.pack(fill="x", pady=(px(5), 0))

    def update_info(self, name, done, total, speed):
        self.name.configure(text=ellipsize(name, 38))
        size = f"{done / 1048576:.1f} / {total / 1048576:.1f} MB" if total else f"{done / 1048576:.1f} MB"
        self.stats.configure(text=f"{size} · {core.human_speed(speed)}")
        self.bar.set(done, total or max(done, 1))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.config_data = self._load_config()
        cfg = self.config_data
        set_language(cfg.get("language", "pt") if cfg.get("language") in LANGUAGES else "pt")
        accent = cfg.get("accent", DEFAULT_ACCENT)
        self.accent = accent if ui.valid_hex(accent) else DEFAULT_ACCENT
        self.theme_name = cfg.get("theme", "Midnight")
        custom = cfg.get("custom_bg", DEFAULT_CUSTOM_BG)
        self.custom_bg = custom if ui.valid_hex(custom) else DEFAULT_CUSTOM_BG

        # --- variáveis (persistem mesmo quando a interface é reconstruída)
        self.language = tk.StringVar(value=get_language())
        self.ui_scale = tk.StringVar(value=cfg.get("ui_scale", "100") if cfg.get("ui_scale") in UI_SCALES else "100")
        self.game_version = tk.StringVar(value=cfg.get("game_version", "26.3"))
        self.source_version = tk.StringVar(value=cfg.get("source_version", ""))
        self.loader = tk.StringVar(value=cfg.get("loader", "fabric"))
        self.destination = tk.StringVar(value=cfg.get("destination", str(Path.home() / "Downloads" / "Modrinth Mods")))
        self.mods_folder = tk.StringVar(value=cfg.get("mods_folder", ""))
        self.scan_folder = tk.StringVar(value=cfg.get("scan_folder", ""))
        self.auto_deps = tk.BooleanVar(value=cfg.get("auto_deps", True))
        self.stable_only = tk.BooleanVar(value=cfg.get("stable_only", False))
        self.workers = tk.StringVar(value=str(cfg.get("workers", 4)) if str(cfg.get("workers", 4)) in ("3", "4", "5") else "4")
        self.retries = tk.StringVar(value=str(cfg.get("retries", 3)) if str(cfg.get("retries", 3)) in ("2", "3") else "3")
        self.notify = tk.BooleanVar(value=cfg.get("notify", True))
        self.snapshots = tk.BooleanVar(value=cfg.get("snapshots", False))
        self.update_url = tk.StringVar(value=cfg.get("update_url", core.UPDATE_URL_DEFAULT))
        self.status = tk.StringVar(value=tr("status.ready"))

        # --- estado
        self.events = queue.Queue()
        self.worker = None
        self.stop_event = threading.Event()
        self.jar_paths = []
        self.game_versions = list(cfg.get("game_versions_cache") or [])
        self.log_lines = []            # (kind, texto) — reaplicado quando a interface é reconstruída
        self.last_manifests = []
        self.update_results = []
        self.history = self._load_history()
        self.file_rows = {}
        self.preview_cache = {}
        self.preview_token = 0
        self.preview_after = None
        self.preview_rows = None
        self._preview_imgs = []
        self._dropdowns = []
        self._toast = None
        self._report_win = None
        self._after_run = None
        self.current_page = "download"
        self.app_update_info = None

        ui.init(self, self._scale_factor())
        ui.set_theme(self._theme_base(), self.accent)
        self.title(APP_NAME)
        self._set_app_icon()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(px(1140), sw - 40)}x{min(px(800), sh - 80)}")
        self._apply_minsize()
        self.configure(bg=T["content"])

        self._build_ui()
        self.show_page("download")
        for var in (self.game_version, self.loader, self.stable_only):
            var.trace_add("write", lambda *a: self._schedule_preview())
        for var in (self.workers, self.retries, self.notify, self.update_url, self.auto_deps, self.stable_only):
            var.trace_add("write", lambda *a: self._save_config())
        self.snapshots.trace_add("write", lambda *a: (self._save_config(), self._fetch_versions(True)))
        self.language.trace_add("write", lambda *a: self.after_idle(self._on_language))
        self.ui_scale.trace_add("write", lambda *a: self.after_idle(self._on_scale))
        self.after(100, self._drain_events)
        self.after(250, self._set_native_titlebar)
        self.after(600, lambda: self._fetch_versions(False))
        self.after(2500, lambda: self._check_app_update(False))

    # ------------------------------------------------------------------ ícone, config, tema
    def _icon_files(self):
        """(png, ico) a usar: o ícone personalizado, se existir; senão o que vem embutido no app."""
        png, ico = self._custom_icon_paths()                       # escolhido em Configurações (ao lado do app)
        if png.exists() and ico.exists():
            return str(png), str(ico)
        bpng, bico = (resource_path(os.path.join("assets", "custom_icon" + e)) for e in (".png", ".ico"))
        if os.path.exists(bpng) and os.path.exists(bico):          # embutido no .exe quando o build usou um ícone personalizado
            return bpng, bico
        return resource_path(os.path.join("assets", "icon.png")), resource_path(os.path.join("assets", "icon.ico"))

    @staticmethod
    def _custom_icon_paths():
        folder = app_dir() / "assets"
        return folder / "custom_icon.png", folder / "custom_icon.ico"

    def _set_app_icon(self):
        """Ícone da janela e da barra de tarefas (assets/icon.* ou o ícone personalizado)."""
        png, ico = self._icon_files()
        try:
            if sys.platform == "win32":
                self.iconbitmap(default=ico)
        except Exception:
            pass
        photo = ui.load_photo(png, 64)
        if photo is not None:
            self._icon_img = photo
            try:
                self.iconphoto(True, photo)
            except Exception:
                pass

    def _load_config(self):
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_config(self):
        data = {"accent": self.accent, "game_version": self.game_version.get(), "loader": self.loader.get(),
                "destination": self.destination.get(), "scan_folder": self.scan_folder.get(),
                "mods_folder": self.mods_folder.get(), "source_version": self.source_version.get(),
                "theme": self.theme_name, "custom_bg": self.custom_bg, "auto_deps": self.auto_deps.get(),
                "stable_only": self.stable_only.get(), "workers": self.workers.get(), "retries": self.retries.get(),
                "notify": self.notify.get(), "snapshots": self.snapshots.get(), "language": self.language.get(),
                "ui_scale": self.ui_scale.get(), "update_url": self.update_url.get(),
                "game_versions_cache": self.game_versions[:200]}
        try:
            CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_history(self):
        try:
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_history(self):
        try:
            HISTORY_PATH.write_text(json.dumps(self.history[:HISTORY_LIMIT], ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _theme_base(self):
        if self.theme_name == "Custom":
            return self.custom_bg
        return THEME_BG.get(self.theme_name, THEME_BG["Midnight"])

    def _scale_factor(self):
        try:
            return int(self.ui_scale.get()) / 100
        except ValueError:
            return 1.0

    def _apply_minsize(self):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.minsize(min(px(1000), sw - 40), min(px(700), sh - 80))

    def _apply_theme(self):
        ui.set_theme(self._theme_base(), self.accent)
        self.configure(bg=T["content"])
        ui.apply_theme(self)
        self.after(20, self._set_native_titlebar)

    def _set_native_titlebar(self, window=None):
        """Pinta a barra de título do Windows 10/11 com a cor da sidebar."""
        if sys.platform != "win32":
            return
        window = window or self
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
            dwm = ctypes.windll.dwmapi
            value = ctypes.c_int(1 if T["dark"] else 0)
            # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win11/Win10 recente); 19 em builds mais antigas do Win10.
            if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)) != 0:
                dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))

            def colorref(hex_color):
                h = hex_color.lstrip("#")
                return int(h[0:2], 16) | (int(h[2:4], 16) << 8) | (int(h[4:6], 16) << 16)
            for attr, color in ((35, T["sidebar"]), (34, T["sidebar"]), (36, T["text"])):
                val = ctypes.c_int(colorref(color))
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass

    def _pick_theme(self, name):
        if name == "Custom":
            chosen = colorchooser.askcolor(color=self.custom_bg, title=tr("dlg.bg_color"), parent=self)[1]
            if not chosen:
                return
            self.custom_bg = chosen
        self.theme_name = name
        self._apply_theme()
        self._save_config()

    def _pick_accent(self, color):
        self.accent = color
        self._apply_theme()
        self._save_config()

    def _choose_accent(self):
        chosen = colorchooser.askcolor(color=self.accent, title=tr("dlg.accent_color"), parent=self)[1]
        if chosen:
            self._pick_accent(chosen)
            self._append_log(tr("log.ui", msg=tr("toast.accent_log", c=chosen)), "muted")

    # ------------------------------------------------------------------ reconstrução (idioma / tamanho)
    def _on_language(self):
        set_language(self.language.get())
        self._save_config()
        self.status.set(tr("status.ready"))
        self.rebuild_ui()

    def _on_scale(self):
        self._save_config()
        old = ui.SCALE
        self.rebuild_ui(rescale_from=old)

    def rebuild_ui(self, rescale_from=None):
        """Destrói e recria toda a interface (necessário para trocar idioma ou tamanho), preservando o estado."""
        page = self.current_page
        links_text = self.links.get("1.0", "end-1c") if getattr(self, "links", None) else ""
        w, h = self.winfo_width(), self.winfo_height()
        for child in list(self.winfo_children()):
            child.destroy()
        self._toast = None
        self._report_win = None
        self.file_rows, self._dropdowns, self._preview_imgs = {}, [], []
        ui.init(self, self._scale_factor())
        ui.set_theme(self._theme_base(), self.accent)
        if rescale_from:
            ratio = ui.SCALE / rescale_from
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"{min(int(w * ratio), sw - 20)}x{min(int(h * ratio), sh - 60)}")
        self._apply_minsize()
        self.configure(bg=T["content"])
        self._build_ui()
        if links_text:
            self.links.insert("1.0", links_text)
        for kind, text in self.log_lines[-1500:]:
            self._append_log(text, kind, store=False)
        self.show_page(page)
        self._set_native_titlebar()
        self._sync_buttons()

    # ------------------------------------------------------------------ construção da interface
    def _build_ui(self):
        # Sidebar (esquerda) + área principal. A sidebar é a camada mais escura, como no Discord.
        self.sidebar = Box(self, role="sidebar", width=px(240))
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.main = Box(self, role="content")
        self.main.pack(side="left", fill="both", expand=True)
        self._build_sidebar()

        # Rodapé: status + barra de progresso fina colada na base da janela.
        footer = Box(self.main, role="content")
        footer.pack(side="bottom", fill="x")
        self.progress = ProgressBar(footer, height=4)
        self.progress.pack(side="bottom", fill="x")
        srow = Box(footer)
        srow.pack(side="bottom", fill="x", padx=px(34), pady=px(10))
        self.status_dot = StatusDot(srow)
        self.status_dot.pack(side="left")
        Label(srow, textvariable=self.status, fg="muted", font="small").pack(side="left", padx=(px(10), 0))
        self.percent = Label(srow, "", fg="muted", font="small")
        self.percent.pack(side="right")

        self.pages_host = Box(self.main, role="content")
        self.pages_host.pack(fill="both", expand=True, padx=px(34), pady=(px(30), px(4)))
        self.pages = {
            "download": self._build_download(), "convert": self._build_convert(), "analysis": self._build_analysis(),
            "mods": self._build_mods(), "history": self._build_history(), "settings": self._build_settings(),
        }
        self._update_local_summary()
        self._render_preview(self.preview_rows)
        self._render_mods()
        self._render_history()
        self._render_active()

    def _build_sidebar(self):
        s = self.sidebar
        bottom = Box(s, role="sidebar")
        bottom.pack(side="bottom", fill="x", padx=px(12), pady=(0, px(14)))
        self.nav = {}
        brand = Box(s, role="sidebar")
        brand.pack(fill="x", padx=px(20), pady=(px(26), px(24)))
        # Mascote: assets/mascot.png. Se o arquivo não existir, o Logo desenha o placeholder (quadrado com seta).
        self._mascot = ui.load_photo(resource_path(os.path.join("assets", "mascot.png")), px(46))
        Logo(brand, size=46, image=self._mascot).pack(side="left")
        names = Box(brand)
        names.pack(side="left", padx=(px(12), 0))
        Label(names, "Modrinth", font="brand").pack(anchor="w")
        Label(names, "Batch Downloader", fg="muted", font="tiny").pack(anchor="w")
        Label(s, tr("nav.tools"), fg="subtle", font="tiny", role="sidebar").pack(anchor="w", padx=px(24), pady=(0, px(6)))
        for key, icon in (("download", "download"), ("convert", "convert"), ("analysis", "analysis"),
                          ("mods", "mods"), ("history", "history")):
            item = NavItem(s, tr("nav." + key), icon, lambda k=key: self.show_page(k))
            item.pack(fill="x", padx=px(12), pady=px(2))
            self.nav[key] = item
        item = NavItem(bottom, tr("nav.settings"), "settings", lambda: self.show_page("settings"))
        item.pack(fill="x")
        self.nav["settings"] = item
        Label(bottom, f"V{APP_VERSION}", fg="subtle", font="tiny", role="sidebar").pack(anchor="w", padx=px(14), pady=(px(8), 0))

    def show_page(self, key):
        self.current_page = key
        for page in self.pages.values():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for k, item in self.nav.items():
            item.set_active(k == key)
        if key == "mods":
            self._update_scan_info()
        if key == "history":
            self._render_history()

    # --- helpers de layout
    def _page(self, title, subtitle):
        page = Box(self.pages_host, role="content")
        Label(page, title, font="h1").pack(anchor="w")
        sub = Label(page, subtitle, fg="muted", justify="left")
        sub.pack(anchor="w", pady=(px(4), 0))
        page.bind("<Configure>", lambda e, s=sub: s.configure(wraplength=max(260, e.width - px(8))))
        return page

    def _field_label(self, parent, text, **grid):
        Label(parent, text, fg="muted", font="small").grid(sticky="w", **grid)

    def _toggle_row(self, parent, text, variable):
        row = Box(parent)
        Toggle(row, variable).pack(side="left")
        Label(row, text).pack(side="left", padx=(px(12), 0))
        return row

    def _card_header(self, card, title, right_text=None):
        head = Box(card.body)
        head.pack(fill="x", pady=(0, px(10)))
        Label(head, title, font="h3").pack(side="left")
        right = None
        if right_text is not None:
            right = Label(head, right_text, fg="muted", font="small")
            right.pack(side="right")
        return head, right

    def _version_dropdown(self, parent, variable, width=12):
        dd = Dropdown(parent, variable, self._version_choices(variable), width=width)
        self._dropdowns.append(dd)
        return dd

    def _version_choices(self, variable=None):
        return list(self.game_versions)

    # --- páginas
    def _build_download(self):
        p = self._page(tr("dl.title"), tr("dl.subtitle"))
        grid = Box(p)
        grid.pack(fill="both", expand=True, pady=(px(20), px(14)))
        grid.columnconfigure(0, weight=3, uniform="d")
        grid.columnconfigure(1, weight=2, uniform="d")
        grid.rowconfigure(0, weight=1)

        card = Card(grid)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, px(8)))
        _, self.link_count = self._card_header(card, tr("dl.links_card"), tr("dl.no_links"))
        self.links_box = TextBox(card.body, font="mono", on_change=self._links_changed, placeholder=tr("dl.placeholder"))
        self.links_box.pack(fill="both", expand=True)
        self.links = self.links_box.text
        self.links.bind("<<Paste>>", self._format_pasted_links)

        # Cartão da direita: pré-visualização dos projetos; durante o download vira "Baixando agora".
        right = Card(grid)
        right.grid(row=0, column=1, sticky="nsew", padx=(px(8), 0))
        head = Box(right.body)
        head.pack(fill="x", pady=(0, px(10)))
        self.right_title = Label(head, tr("dl.preview"), font="h3")
        self.right_title.pack(side="left")
        self.right_info = Label(head, "", fg="muted", font="small")
        self.right_info.pack(side="right")
        self.preview_scroll = ScrollFrame(right.body)
        self.active_scroll = ScrollFrame(right.body)
        self.preview_scroll.pack(fill="both", expand=True)

        opt = Card(p)
        opt.pack(fill="x", pady=(0, px(16)))
        b = opt.body
        self._field_label(b, tr("dl.mc_version"), row=0, column=0)
        self._field_label(b, tr("dl.loader"), row=0, column=1, padx=(px(24), 0))
        self._version_dropdown(b, self.game_version).grid(row=1, column=0, sticky="w", pady=(px(6), 0))
        Segmented(b, self.loader, LOADERS, LOADER_LABELS).grid(row=1, column=1, sticky="w", padx=(px(24), 0), pady=(px(6), 0))
        self._toggle_row(b, tr("dl.auto_deps"), self.auto_deps).grid(row=2, column=0, columnspan=2, sticky="w", pady=(px(14), 0))
        self._toggle_row(b, tr("dl.stable_only"), self.stable_only).grid(row=3, column=0, columnspan=2, sticky="w", pady=(px(10), 0))

        act = Box(p)
        act.pack(fill="x")
        self.start_button = Button(act, tr("btn.download"), command=lambda: self._start(False), kind="primary", icon="download", height=42, padx=22)
        self.start_button.pack(side="left")
        self.stop_button = Button(act, tr("btn.stop"), command=self._stop, height=42, padx=18)
        self.stop_button.pack(side="left", padx=px(10))
        self.stop_button.set_enabled(False)
        Button(act, tr("btn.clear_links"), kind="ghost", height=42, padx=16,
               command=lambda: self.links.delete("1.0", "end")).pack(side="left")
        Button(act, tr("btn.open_folder"), kind="ghost", icon="folder", height=42, padx=16,
               command=lambda: self._open_folder(self.destination.get())).pack(side="right")
        return p

    def _build_convert(self):
        p = self._page(tr("cv.title"), tr("cv.subtitle"))
        v = Card(p)
        v.pack(fill="x", pady=(px(20), px(14)))
        self._card_header(v, tr("cv.versions"))
        b = Box(v.body)
        b.pack(fill="x")
        self._field_label(b, tr("cv.source"), row=0, column=0)
        self._field_label(b, tr("cv.target"), row=0, column=1, padx=(px(24), 0))
        self._version_dropdown(b, self.source_version, 14).grid(row=1, column=0, sticky="w", pady=(px(6), 0))
        self._version_dropdown(b, self.game_version, 14).grid(row=1, column=1, sticky="w", padx=(px(24), 0), pady=(px(6), 0))
        self._field_label(b, tr("cv.target_loader"), row=2, column=0, columnspan=2, pady=(px(16), 0))
        Segmented(b, self.loader, LOADERS, LOADER_LABELS).grid(row=3, column=0, columnspan=2, sticky="w", pady=(px(6), 0))
        self._toggle_row(b, tr("dl.stable_only"), self.stable_only).grid(row=4, column=0, columnspan=2, sticky="w", pady=(px(14), 0))

        o = Card(p)
        o.pack(fill="x", pady=(0, px(16)))
        self._card_header(o, tr("cv.origin"))
        Label(o.body, tr("cv.origin_hint"), fg="muted", font="small", justify="left").pack(anchor="w", pady=(0, px(12)))
        row = Box(o.body)
        row.pack(fill="x")
        Button(row, tr("btn.add_jars"), command=self._add_jars).pack(side="left")
        Button(row, tr("btn.pick_folder"), command=self._choose_scan_folder).pack(side="left", padx=px(8))
        Button(row, tr("btn.clear_selection"), kind="ghost", command=self._clear_local).pack(side="left")
        self.local_summary = Label(o.body, "", fg="muted", font="small", justify="left")
        self.local_summary.pack(anchor="w", pady=(px(14), 0))
        o.body.bind("<Configure>", lambda e: self.local_summary.configure(wraplength=max(200, e.width - px(8))))

        self.convert_button = Button(p, tr("btn.convert"), command=lambda: self._start(True), kind="primary", icon="convert", height=42, padx=22)
        self.convert_button.pack(anchor="w")
        return p

    def _style_log(self, text):
        text.tag_configure("sep", foreground=T["subtle"])
        for kind in ("ok", "err", "warn", "info", "accent", "muted"):
            text.tag_configure("tag_" + kind, foreground=T["subtle" if kind == "muted" else kind], font=ui.FONTS["monob"])

    def _build_analysis(self):
        p = self._page(tr("an.title"), tr("an.subtitle"))
        card = Card(p)
        card.pack(fill="both", expand=True, pady=(px(20), 0))
        head, _ = self._card_header(card, tr("an.log"))
        Button(head, tr("btn.clear"), kind="ghost", height=30, padx=12, command=self._clear_log).pack(side="right")
        Button(head, tr("btn.export_log"), kind="ghost", icon="export", height=30, padx=12,
               command=self._export_current_log).pack(side="right", padx=(0, px(6)))
        self.log_box = TextBox(card.body, font="mono", on_theme=self._style_log)
        self.log_box.pack(fill="both", expand=True)
        self.log = self.log_box.text
        self.log.configure(state="disabled")
        return p

    def _style_cards(self, text):
        text.tag_configure("h", font=ui.FONTS["bodyb"], foreground=T["text"], spacing1=px(2))
        text.tag_configure("m", font=ui.FONTS["small"], foreground=T["muted"], lmargin1=px(2), lmargin2=px(2))
        for kind in ("ok", "warn", "err", "info", "accent"):
            text.tag_configure("k_" + kind, font=ui.FONTS["small"], foreground=T[kind], lmargin1=px(2), lmargin2=px(2))

    def _build_mods(self):
        p = self._page(tr("md.title"), tr("md.subtitle"))
        bar = Box(p)
        bar.pack(fill="x", pady=(px(18), 0))
        self.scan_button = Button(bar, tr("btn.scan"), command=self._scan_folder, kind="primary", icon="analysis", height=40, padx=20)
        self.scan_button.pack(side="left")
        Button(bar, tr("btn.pick_scan"), command=self._pick_and_scan, height=40, padx=18).pack(side="left", padx=px(8))
        self.check_button = Button(bar, tr("btn.check_updates"), command=self._check_updates, icon="update", height=40, padx=18)
        self.check_button.pack(side="left")
        self.update_all_button = Button(bar, tr("btn.update_all", n=0), command=self._apply_updates, kind="primary",
                                        icon="download", height=40, padx=18)
        self.scan_info = Label(bar, "", fg="muted", font="small", justify="left")
        self.scan_info.pack(side="left", padx=(px(10), 0))

        # Aviso de conflitos (só aparece quando há algo a avisar)
        self.conflict_card = Card(p)
        self.conflict_body = Box(self.conflict_card.body)
        self.conflict_body.pack(fill="x")

        self.mods_grid = Box(p)
        self.mods_grid.pack(fill="both", expand=True, pady=(px(14), 0))
        grid = self.mods_grid
        grid.columnconfigure(0, weight=1, uniform="c")
        grid.columnconfigure(1, weight=1, uniform="c")
        grid.rowconfigure(0, weight=3)
        grid.rowconfigure(1, weight=2)
        for col, title in ((0, tr("md.mods_card")), (1, tr("md.deps_card"))):
            card = Card(grid)
            card.grid(row=0, column=col, sticky="nsew", padx=(0, px(8)) if col == 0 else (px(8), 0))
            _, cnt = self._card_header(card, title, "0")
            box = TextBox(card.body, font="body", on_theme=self._style_cards)
            box.pack(fill="both", expand=True)
            box.text.configure(state="disabled")
            if col == 0:
                self.active_box, self.mods_count, self.active_text = box, cnt, box.text
            else:
                self.deps_box, self.deps_count, self.deps_text = box, cnt, box.text
        # Log separado: dependências que faltam na pasta e de quais mods elas são exigidas
        mcard = Card(grid)
        mcard.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(px(14), 0))
        _, self.missing_count = self._card_header(mcard, tr("md.missing_card"), "0")
        self.missing_box = TextBox(mcard.body, font="body", on_theme=self._style_cards)
        self.missing_box.pack(fill="both", expand=True)
        self.missing_text = self.missing_box.text
        self.missing_text.configure(state="disabled")
        return p

    def _build_history(self):
        p = self._page(tr("hs.title"), tr("hs.subtitle"))
        bar = Box(p)
        bar.pack(fill="x", pady=(px(18), px(10)))
        Button(bar, tr("btn.clear_history"), kind="ghost", icon="history", height=36, padx=14,
               command=self._clear_history).pack(side="left")
        self.history_scroll = ScrollFrame(p)
        self.history_scroll.pack(fill="both", expand=True)
        return p

    def _build_settings(self):
        p = self._page(tr("st.title"), tr("st.subtitle"))
        sf = ScrollFrame(p)
        sf.pack(fill="both", expand=True, pady=(px(14), 0))
        host = sf.inner

        # --- Aparência
        a = Card(host)
        a.pack(fill="x", pady=(0, px(14)))
        self._card_header(a, tr("st.appearance"))
        ab = Box(a.body)
        ab.pack(fill="x")
        self._field_label(ab, tr("st.theme"), row=0, column=0, pady=(0, px(8)))
        swatches = Box(ab)
        swatches.grid(row=1, column=0, sticky="w")
        for name in THEME_ORDER:
            ThemeSwatch(swatches, name, name, lambda n=name: THEME_BG[n], lambda: self.accent,
                        lambda n=name: self.theme_name == n, self._pick_theme).pack(side="left", padx=(0, px(8)))
        ThemeSwatch(swatches, "Custom", tr("st.theme_custom"), lambda: self.custom_bg, lambda: self.accent,
                    lambda: self.theme_name == "Custom", self._pick_theme).pack(side="left")
        self._field_label(ab, tr("st.accent"), row=2, column=0, pady=(px(18), px(8)))
        dots = Box(ab)
        dots.grid(row=3, column=0, sticky="w")
        for color in ACCENT_PRESETS:
            ColorDot(dots, color, lambda c=color: self.accent.lower() == c.lower(), self._pick_accent).pack(side="left", padx=(0, px(6)))
        Button(dots, tr("st.accent_custom"), command=self._choose_accent, height=34, padx=14).pack(side="left", padx=(px(8), 0))
        self._field_label(ab, tr("st.ui_size") + "  ·  " + tr("st.ui_size_note"), row=4, column=0, pady=(px(18), px(8)))
        Segmented(ab, self.ui_scale, UI_SCALES, {v: v + "%" for v in UI_SCALES}).grid(row=5, column=0, sticky="w")
        self._field_label(ab, tr("st.language"), row=6, column=0, pady=(px(18), px(8)))
        Segmented(ab, self.language, tuple(LANGUAGES), LANGUAGES).grid(row=7, column=0, sticky="w")

        # --- Downloads
        d = Card(host)
        d.pack(fill="x", pady=(0, px(14)))
        self._card_header(d, tr("st.downloads"))
        db = Box(d.body)
        db.pack(fill="x")
        self._field_label(db, tr("st.workers"), row=0, column=0)
        self._field_label(db, tr("st.retries"), row=0, column=1, padx=(px(28), 0))
        Segmented(db, self.workers, ("3", "4", "5")).grid(row=1, column=0, sticky="w", pady=(px(6), 0))
        Segmented(db, self.retries, ("2", "3")).grid(row=1, column=1, sticky="w", padx=(px(28), 0), pady=(px(6), 0))
        self._toggle_row(db, tr("st.notify"), self.notify).grid(row=2, column=0, columnspan=2, sticky="w", pady=(px(16), 0))
        self._toggle_row(db, tr("st.snapshots"), self.snapshots).grid(row=3, column=0, columnspan=2, sticky="w", pady=(px(10), 0))
        vrow = Box(db)
        vrow.grid(row=4, column=0, columnspan=2, sticky="w", pady=(px(14), 0))
        Button(vrow, tr("st.refresh_versions"), icon="update", command=lambda: self._fetch_versions(True), height=34, padx=14).pack(side="left")

        # --- Pastas
        f = Card(host)
        f.pack(fill="x", pady=(0, px(14)))
        self._card_header(f, tr("st.folders"))
        b = Box(f.body)
        b.pack(fill="x")
        b.columnconfigure(0, weight=1)
        self._field_label(b, tr("st.dest"), row=0, column=0)
        Field(b, textvariable=self.destination, width=10).grid(row=1, column=0, sticky="ew", pady=(px(6), px(14)))
        Button(b, tr("btn.browse"), command=self._choose_destination, height=38).grid(row=1, column=1, padx=(px(8), 0), pady=(px(6), px(14)))
        self._field_label(b, tr("st.mods_folder"), row=2, column=0)
        Field(b, textvariable=self.scan_folder, width=10).grid(row=3, column=0, sticky="ew", pady=(px(6), 0))
        Button(b, tr("btn.browse"), command=self._choose_scan_folder, height=38).grid(row=3, column=1, padx=(px(8), 0), pady=(px(6), 0))

        # --- Ícone do app
        ic = Card(host)
        ic.pack(fill="x", pady=(0, px(14)))
        self._card_header(ic, tr("st.icon"))
        irow = Box(ic.body)
        irow.pack(fill="x")
        self._icon_preview = ui.load_photo(self._icon_files()[0], px(64))
        Logo(irow, size=64, image=self._icon_preview).pack(side="left")
        itxt = Box(irow)
        itxt.pack(side="left", padx=(px(16), 0), fill="x", expand=True)
        brow = Box(itxt)
        brow.pack(anchor="w", pady=(px(10), 0))
        Button(brow, tr("btn.choose_icon"), command=self._choose_icon, height=34, padx=14).pack(side="left")
        Button(brow, tr("btn.reset_icon"), kind="ghost", command=self._reset_icon, height=34, padx=14).pack(side="left", padx=px(6))

        # --- Sobre / atualização do app
        ab2 = Card(host)
        ab2.pack(fill="x", pady=(0, px(14)))
        self._card_header(ab2, tr("st.about"), tr("st.version", v=APP_VERSION))
        self._field_label_pack(ab2.body, tr("st.update_url"))
        Field(ab2.body, textvariable=self.update_url, width=10).pack(fill="x", pady=(px(6), px(12)))
        urow = Box(ab2.body)
        urow.pack(fill="x")
        Button(urow, tr("st.check_app_update"), icon="update", command=lambda: self._check_app_update(True), height=34, padx=14).pack(side="left")
        self.release_button = Button(urow, tr("btn.open_release"), kind="ghost", command=self._open_release, height=34, padx=14)
        self.update_label = Label(ab2.body, "", fg="muted", font="small", justify="left")
        self.update_label.pack(anchor="w", pady=(px(10), 0))
        self._show_app_update_label()

        Button(host, tr("btn.save"), kind="primary", height=42, padx=22,
               command=lambda: (self._save_config(), self.toast(tr("toast.saved"), "ok"))).pack(anchor="w", pady=(0, px(6)))
        return p

    def _field_label_pack(self, parent, text):
        Label(parent, text, fg="muted", font="small").pack(anchor="w")

    # ------------------------------------------------------------------ pequenos comportamentos de UI
    def toast(self, text, kind="warn"):
        if self._toast is not None:
            try:
                self._toast.destroy()
            except Exception:
                pass
        card = Card(self.main, pad=12)
        self._toast = card
        row = Box(card.body)
        row.pack()
        dot = StatusDot(row)
        dot.pack(side="left")
        dot.set_kind(kind)
        Label(row, text).pack(side="left", padx=(px(10), 0))
        card.place(relx=1.0, x=-px(34), y=px(26), anchor="ne")
        card.lift()

        def close(c=card):
            if self._toast is c:
                self._toast = None
            try:
                c.destroy()
            except Exception:
                pass
        self.after(4200, close)

    def _status(self, text, kind="subtle"):
        self.status.set(text)
        self.status_dot.set_kind(kind)

    def _busy(self):
        return bool(self.worker and self.worker.is_alive())

    def _sync_buttons(self):
        busy = self._busy()
        for name in ("start_button", "scan_button", "check_button", "convert_button", "update_all_button"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.set_enabled(not busy)
        self.stop_button.set_enabled(busy and self._running_engine)

    _running_engine = False

    def _open_folder(self, path):
        if not core.open_folder(path):
            self.toast(tr("toast.no_folder_open"))

    def _links_changed(self):
        n = len(self._link_lines())
        self.link_count.configure(text=tr("dl.no_links") if n == 0 else (tr("dl.one_link") if n == 1 else tr("dl.n_links", n=n)))
        self._schedule_preview()

    def _link_lines(self):
        return [x.strip() for x in self.links.get("1.0", "end").splitlines() if x.strip()]

    def _format_pasted_links(self, _event=None):
        # Normaliza o que foi colado para que cada link detectado fique na sua própria linha.
        self.after(50, self._normalize_link_lines)

    def _normalize_link_lines(self):
        try:
            content = self.links.get("1.0", "end-1c")
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            if lines and all("modrinth.com/" in line for line in lines):
                self.links.delete("1.0", "end")
                self.links.insert("1.0", "\n".join(lines) + "\n")
                self.links.mark_set("insert", "end-1c")
        except Exception:
            pass

    def _clear_log(self):
        self.log_lines.clear()
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _append_log(self, msg, kind=None, store=True):
        import re
        if store:
            self.log_lines.append((kind, msg))
            if len(self.log_lines) > 5000:
                del self.log_lines[:1000]
        t = self.log
        t.configure(state="normal")
        m = re.match(r"(\s*)(\[[^\]]+\])(.*)", msg, re.S)
        if m:
            lead, tag, rest = m.groups()
            t.insert("end", lead)
            t.insert("end", tag, ("tag_" + (kind or log_kind(msg) or "muted"),))
            t.insert("end", rest + "\n")
        elif msg.startswith("="):
            t.insert("end", msg + "\n", ("sep",))
        else:
            t.insert("end", msg + "\n")
        t.see("end")
        t.configure(state="disabled")

    def _log(self, level, key, **params):
        """Log a partir de threads de trabalho (vai para a fila de eventos)."""
        self.events.put(("log", level, tr(key, **params)))

    def _export_current_log(self):
        text = "\n".join(t for _, t in self.log_lines)
        self._export_log_text(text, self)

    def _export_log_text(self, text, parent, summary=""):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = filedialog.asksaveasfilename(parent=parent, title=tr("dlg.save_log"), defaultextension=".txt",
                                            initialfile=f"mbd-log-{stamp}.txt", filetypes=[("Text", "*.txt")])
        if not path:
            return
        header = tr("rp.export_header", v=APP_VERSION, date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            Path(path).write_text(header + "\n" + ("=" * 60) + "\n" + (summary + "\n\n" if summary else "") + text + "\n", encoding="utf-8")
            self.toast(tr("rp.log_saved", path=path), "ok")
        except Exception as exc:
            self.toast(tr("rp.log_fail", err=exc), "err")

    # --- cartões de texto (Mods ativos)
    def _set_cards(self, widget, entries, empty):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if not entries:
            widget.insert("end", empty, ("m",))
        for entry in entries:
            head, rest, kind = entry if len(entry) == 3 else (*entry, None)
            widget.insert("end", head + "\n", ("h",))
            widget.insert("end", rest.strip() + "\n", ("m",))
            if kind:
                widget.insert("end", kind[1] + "\n", ("k_" + kind[0],))
            widget.insert("end", "\n", ("m",))
        widget.configure(state="disabled")

    def _update_status_line(self, result):
        """(cor, texto) da linha de atualização de um mod, ou None."""
        s = result["status"]
        cur, new = result.get("current") or {}, result.get("latest") or {}
        mc, loader = self.game_version.get(), self.loader.get()
        if s == "update":
            return "warn", tr("md.upd_available", cur=cur.get("version_number", "?"), new=new.get("version_number", "?"))
        if s == "current":
            return "ok", tr("md.upd_current", cur=cur.get("version_number", "?"))
        if s == "unknown":
            return "info", tr("md.upd_unknown")
        if s == "wrong_loader":
            return "info", tr("md.upd_wrong_loader", loader=loader)
        if s == "other_target":
            return "info", tr("md.upd_other_target")
        return "info", tr("md.upd_none_for_target", mc=mc, loader=loader)

    def _manifest_entries(self, manifests):
        """(mods, bibliotecas): separa o que é mod do que é biblioteca/dependência instalada e mostra os vínculos."""
        by_file = {r["manifest"]["file"]: r for r in self.update_results}
        info = core.analyze_dependencies(manifests)
        mods, libs = [], []
        for m in manifests:
            name = m.get("name") or Path(m["file"]).stem
            line = "  " + tr("md.mod_line", id=m.get("id") or tr("md.unknown_id"), ver=m.get("version") or "?", loader=m.get("loader") or "?")
            used_by = info["required_by"].get(m["file"], [])
            if m["file"] in info["libraries"]:
                line += "\n" + (tr("md.lib_used_by", owners=", ".join(used_by)) if used_by else tr("md.lib_unused"))
                target = libs
            else:
                reqs = info["requires"].get(m["file"], [])
                if reqs:
                    items = ", ".join(tr("md.dep_ok", dep=d) if prov is not None else tr("md.dep_missing", dep=d) for d, prov in reqs)
                    line += "\n" + tr("md.requires", items=items)
                if m.get("optional"):
                    line += "\n" + tr("md.optional", items=", ".join(m["optional"]))
                if used_by:
                    line += "\n" + tr("md.used_by", owners=", ".join(used_by))
                target = mods
            res = by_file.get(m["file"])
            target.append((name, line, self._update_status_line(res)) if res else (name, line))
        return mods, libs

    def _render_mods(self):
        if not getattr(self, "active_text", None):
            return
        active, deps = self._manifest_entries(self.last_manifests)
        self._set_cards(self.active_text, active, tr("md.empty_mods"))
        self._set_cards(self.deps_text, deps, tr("md.empty_deps"))
        self.mods_count.configure(text=str(len(active)))
        self.deps_count.configure(text=str(len(deps)))
        missing = core.missing_dependencies(self.last_manifests)
        self._set_cards(self.missing_text,
                        [(dep, tr("md.missing_by", owners=", ".join(owners))) for dep, owners in missing.items()],
                        tr("md.empty_missing"))
        self.missing_count.configure(text=str(len(missing)))
        self._render_conflicts(core.detect_conflicts(self.last_manifests) if self.last_manifests else [])
        n = sum(1 for r in self.update_results if r["status"] == "update")
        if n:
            self.update_all_button.text = tr("btn.update_all", n=n)
            self.update_all_button.w = ui.FONTS["btn"].measure(self.update_all_button.text) + 2 * px(18) + px(24)
            self.update_all_button.configure(width=self.update_all_button.w)
            self.update_all_button.redraw()
            self.update_all_button.pack(side="left", padx=(px(8), 0), before=self.scan_info)
        else:
            self.update_all_button.pack_forget()

    def _render_conflicts(self, conflicts):
        for child in self.conflict_body.winfo_children():
            child.destroy()
        if not conflicts:
            self.conflict_card.pack_forget()
            return
        Label(self.conflict_body, "⚠  " + tr("md.conflicts"), fg="warn", font="h3").pack(anchor="w")
        for c in conflicts:
            Label(self.conflict_body, "• " + core.conflict_text(c), fg="warn", font="small", justify="left",
                  wraplength=px(760)).pack(anchor="w", pady=(px(4), 0))
        self.conflict_card.pack(fill="x", pady=(px(14), 0), before=self.mods_grid)

    # --- seleção de arquivos / pastas
    def _add_jars(self):
        paths = filedialog.askopenfilenames(title=tr("dlg.pick_jars"), filetypes=[(tr("dlg.jars"), "*.jar"), (tr("dlg.all"), "*.*")])
        self.jar_paths.extend(Path(p) for p in paths if Path(p) not in self.jar_paths)
        self._update_local_summary()
        self._save_config()

    def _choose_scan_folder(self):
        folder = filedialog.askdirectory(title=tr("dlg.pick_mods_folder"))
        if folder:
            self.scan_folder.set(folder)
            self.mods_folder.set(folder)
            self._update_local_summary()
            self._save_config()

    def _clear_local(self):
        self.jar_paths = []
        self.scan_folder.set("")
        self.mods_folder.set("")
        self._update_local_summary()
        self._save_config()

    def _local_files(self):
        local = list(self.jar_paths)
        folder_value = self.scan_folder.get() or self.mods_folder.get()
        if folder_value:
            p = Path(folder_value)
            if p.exists():
                local.extend(p.rglob("*.jar"))
        return list(dict.fromkeys(p for p in local if p.exists() and p.is_file() and p.suffix.lower() == ".jar"))

    def _update_local_summary(self):
        if not getattr(self, "local_summary", None):
            return
        count = len(self._local_files())
        folder = self.scan_folder.get() or self.mods_folder.get()
        self.local_summary.configure(text=tr("cv.summary", n=count, folder=folder) if count else tr("cv.summary_none"))

    def _update_scan_info(self):
        folder = self.scan_folder.get() or self.mods_folder.get()
        self.scan_info.configure(text=folder if folder else tr("md.no_folder"))

    def _pick_and_scan(self):
        before = self.scan_folder.get()
        self._choose_scan_folder()
        if self.scan_folder.get() and self.scan_folder.get() != before:
            self._scan_folder()
        self._update_scan_info()

    def _choose_destination(self):
        folder = filedialog.askdirectory(initialdir=self.destination.get() or str(Path.home()))
        if folder:
            self.destination.set(folder)
            self._save_config()

    # ------------------------------------------------------------------ escaneamento da pasta de mods
    def _scan_folder(self):
        """Lê os JARs da pasta de mods e preenche as listas da aba (sem baixar nada)."""
        if self._busy():
            self.toast(tr("toast.wait_task"))
            return
        folder = self.scan_folder.get() or self.mods_folder.get()
        self._update_scan_info()
        if not folder:
            self.toast(tr("toast.pick_mods_folder"))
            return
        if not Path(folder).is_dir():
            self.toast(tr("toast.folder_missing"))
            return
        files = self._local_files()
        if not files:
            self.last_manifests, self.update_results = [], []
            self._render_mods()
            self._set_cards(self.active_text, [], tr("md.no_jars"))
            self.toast(tr("toast.no_jars"))
            return
        self._save_config()
        self._update_local_summary()
        self.update_results = []
        self.progress.set(0, len(files))
        self.percent.configure(text="0%")
        self._status(tr("status.scanning", n=len(files)), "accent")
        self._running_engine = False
        self.worker = threading.Thread(target=self._scan_worker, args=(files,), daemon=True)
        self.worker.start()
        self._sync_buttons()

    def _scan_worker(self, files):
        manifests, missing, conflicts = [], {}, []
        try:
            self.events.put(("log", "muted", "=" * 52))
            self._log("accent", "log.scan_start", n=len(files))
            for i, jar in enumerate(files, 1):
                manifest = core.read_manifest(jar)
                manifests.append(manifest)
                if manifest.get("error"):
                    self._log("warn", "log.warn", msg=f"{jar.name}: {core.manifest_error(manifest)}")
                self.events.put(("scan_progress", i, len(files), jar.name))
            missing = core.missing_dependencies(manifests)     # {dependência: [mods que a exigem]}
            if missing:
                self._log("warn", "log.missing_header")
                for dep, owners in missing.items():
                    self._log("warn", "log.missing_item", dep=dep, owner=", ".join(owners))
            else:
                self._log("info", "log.missing_none")
            conflicts = core.detect_conflicts(manifests)
            core.log_conflicts(conflicts, self._log)
        except Exception as exc:
            self._log("err", "log.fatal", err=exc)
        finally:
            self.events.put(("scan_done", manifests, conflicts, sum(1 for m in manifests if m.get("error")),
                             len(missing)))

    # ------------------------------------------------------------------ verificar / aplicar atualizações de mods
    def _check_updates(self):
        if self._busy():
            self.toast(tr("toast.wait_task"))
            return
        if not self.last_manifests:
            self.toast(tr("md.scan_first"))
            return
        mc, loader = self.game_version.get().strip(), self.loader.get().strip().lower()
        self._status(tr("md.checking", mc=mc, loader=loader), "accent")
        self._append_log(tr("log.upd_start", n=len(self.last_manifests)), "accent")
        self._running_engine = False
        self.worker = threading.Thread(target=self._update_worker, args=(list(self.last_manifests), mc, loader, self.stable_only.get()), daemon=True)
        self.worker.start()
        self._sync_buttons()

    def _update_worker(self, manifests, mc, loader, stable):
        try:
            results = core.check_mod_updates(manifests, mc, loader, stable, retries=int(self.retries.get()), base_delay=1.0)
            self.events.put(("updates", results))
        except Exception as exc:
            self.events.put(("updates_error", exc))

    def _apply_updates(self):
        """Baixa a versão nova de cada mod com atualização (o antigo vira .old) e reescaneia a pasta."""
        if self._busy():
            self.toast(tr("toast.wait_task"))
            return
        refs = [r["latest"]["project_id"] for r in self.update_results if r["status"] == "update" and r.get("latest")]
        folder = self.scan_folder.get() or self.mods_folder.get()
        if not refs or not folder:
            return
        self._launch(links=[], local=[], convert=False, refs=refs, folder=Path(folder), after="rescan")

    # ------------------------------------------------------------------ execução (download / conversão / atualização)
    def _start(self, convert=False):
        if self._busy():
            return
        links = self._link_lines()
        local = self._local_files()
        if convert and not local:
            self.toast(tr("toast.convert_needs_jars"))
            self.show_page("convert")
            return
        if not links and not local:
            self.toast(tr("toast.paste_or_pick"))
            return
        version, loader, target = self.game_version.get().strip(), self.loader.get().strip().lower(), self.destination.get().strip()
        if not version or loader not in LOADERS or not target:
            self.toast(tr("toast.invalid_inputs"))
            return
        self._launch(links=links, local=local, convert=convert, refs=[], folder=Path(target))

    def _launch(self, links, local, convert, refs, folder, after=None):
        version, loader = self.game_version.get().strip(), self.loader.get().strip().lower()
        cfg = core.Settings(game_version=version, loader=loader, folder=folder, auto_deps=self.auto_deps.get(),
                            stable_only=self.stable_only.get(), workers=int(self.workers.get()),
                            retries=int(self.retries.get()), backoff=1.0, source_version=self.source_version.get())
        self._save_config()
        self.stop_event.clear()
        self._after_run = after
        self._running_engine = True
        self.progress.set(0, 1)
        self.percent.configure(text="0%")
        self._status(tr("status.analyzing"), "accent")
        self._append_log("=" * 52, "muted")
        self._append_log(tr("log.sep_dest", mc=version, loader=loader, src=self.source_version.get() or tr("log.not_informed"),
                            links=len(links) + len(refs), jars=len(local), conv=tr("log.yes") if convert else tr("log.no"),
                            workers=cfg.workers, stable=tr("log.yes") if cfg.stable_only else tr("log.no")), "muted")
        engine = core.Engine(cfg, self.events.put, self.stop_event)
        self._show_active(True)
        self.worker = threading.Thread(target=engine.run, args=(links, local, convert, True, refs), daemon=True)
        self.worker.start()
        self._sync_buttons()

    def _stop(self):
        self.stop_event.set()
        self._status(tr("status.stop_requested"), "warn")

    # ------------------------------------------------------------------ "Baixando agora" (progresso por arquivo)
    def _show_active(self, active):
        self.preview_scroll.pack_forget()
        self.active_scroll.pack_forget()
        if active:
            self.right_title.configure(text=tr("dl.active"))
            self.active_scroll.pack(fill="both", expand=True)
        else:
            self.right_title.configure(text=tr("dl.preview"))
            self.preview_scroll.pack(fill="both", expand=True)
            self.file_rows.clear()
        self._render_active()

    def _render_active(self):
        if not getattr(self, "active_scroll", None):
            return
        inner = self.active_scroll.inner
        idle = getattr(self, "_active_idle", None)
        if not self.file_rows:
            if idle is None or not idle.winfo_exists():
                self._active_idle = Label(inner, tr("dl.active_idle"), fg="muted", font="small")
                self._active_idle.pack(anchor="w")
            self.right_info.configure(text="")
        else:
            if idle is not None and idle.winfo_exists():
                idle.destroy()
            self.right_info.configure(text=str(len(self.file_rows)))

    def _file_event(self, key, name, done, total, speed):
        row = self.file_rows.get(key)
        if row is None:
            if len(self.file_rows) >= 8:
                return
            idle = getattr(self, "_active_idle", None)
            if idle is not None and idle.winfo_exists():
                idle.destroy()
            row = FileRow(self.active_scroll.inner)
            row.pack(fill="x", pady=(0, px(10)))
            self.file_rows[key] = row
            self.right_info.configure(text=str(len(self.file_rows)))
        row.update_info(name, done, total, speed)

    def _file_done(self, key):
        row = self.file_rows.pop(key, None)
        if row is not None:
            row.destroy()
            self._render_active()

    # ------------------------------------------------------------------ pré-visualização dos links
    def _schedule_preview(self):
        if self.preview_after is not None:
            try:
                self.after_cancel(self.preview_after)
            except Exception:
                pass
        self.preview_after = self.after(700, self._refresh_preview)

    def _refresh_preview(self):
        self.preview_after = None
        if not getattr(self, "links", None):
            return
        refs, seen = [], set()
        for line in self._link_lines():
            try:
                hint, slug = core.parse_project_url(line)
            except ValueError:
                continue
            if slug.lower() not in seen:
                seen.add(slug.lower())
                refs.append((hint, slug))
        if not refs:
            self.preview_rows = None
            self._render_preview(None)
            return
        extra = max(0, len(refs) - PREVIEW_LIMIT)
        refs = refs[:PREVIEW_LIMIT]
        self.preview_token += 1
        if self.preview_rows is None:
            self._render_preview(None, loading=True)
        threading.Thread(target=self._preview_worker, args=(self.preview_token, refs, extra), daemon=True).start()

    def _preview_worker(self, token, refs, extra):
        mc, loader, stable = self.game_version.get().strip(), self.loader.get().strip().lower(), self.stable_only.get()
        try:
            rows = core.fetch_previews(refs, mc, loader, stable, self.preview_cache, workers=4, retries=2, base_delay=0.6)
        except Exception:
            rows = [{"slug": s, "title": s, "kind": "mod", "icon": None, "version": "", "vtype": "", "status": "error"} for _, s in refs]
        self.events.put(("preview", token, rows, extra))

    def _render_preview(self, rows, extra=0, loading=False):
        if not getattr(self, "preview_scroll", None):
            return
        sc = self.preview_scroll
        sc.clear()
        self._preview_imgs = []
        inner = sc.inner
        if not rows:
            Label(inner, tr("dl.preview_loading") if loading else tr("dl.preview_empty"), fg="muted", font="small",
                  justify="left", wraplength=px(300)).pack(anchor="w")
            if not self.file_rows:
                self.right_info.configure(text="")
            return
        mc, loader = self.game_version.get().strip(), self.loader.get().strip()
        for r in rows:
            row = Box(inner)
            row.pack(fill="x", pady=(0, px(10)))
            photo = ui.photo_from_bytes(r.get("icon"), px(36))
            if photo is not None:
                self._preview_imgs.append(photo)
            IconTile(row, 36, photo, r["title"]).pack(side="left")
            text = Box(row)
            text.pack(side="left", fill="x", expand=True, padx=(px(10), px(6)))
            Label(text, ellipsize(r["title"], 26), font="bodyb").pack(anchor="w")
            status = r["status"]
            if status == "ok":
                sub = f"{tr('kind.' + r['kind'])} · {r['version']}"
                pill = (r.get("vtype") or "release", {"release": "ok", "beta": "warn", "alpha": "err"}.get(r.get("vtype"), "ok"))
            elif status == "incompatible":
                sub = tr("dl.preview_incompat", mc=mc, loader=loader) if r["kind"] == "mod" else tr("dl.preview_incompat_nl", mc=mc)
                pill = (tr("rp.incompatible"), "warn")
            elif status == "notfound":
                sub, pill = r["slug"], (tr("dl.preview_notfound"), "err")
            else:
                sub, pill = r["slug"], (tr("dl.preview_error"), "err")
            Label(text, ellipsize(sub, 40), fg="muted", font="tiny").pack(anchor="w")
            Pill(row, pill[0], pill[1]).pack(side="right")
        if extra:
            Label(inner, tr("dl.preview_more", n=extra), fg="muted", font="small").pack(anchor="w")
        if not self.file_rows:
            self.right_info.configure(text=str(len(rows)))

    # ------------------------------------------------------------------ versões do jogo (API) e atualização do app
    def _fetch_versions(self, announce):
        include = self.snapshots.get()

        def work():
            try:
                versions = core.fetch_game_versions(include, retries=2, base_delay=0.8)
                self.events.put(("versions", versions, announce, None))
            except Exception as exc:
                self.events.put(("versions", [], announce, exc))
        threading.Thread(target=work, daemon=True).start()

    def _apply_versions(self, versions):
        self.game_versions = versions
        for dd in self._dropdowns:
            try:
                dd.set_values(versions)
            except Exception:
                pass
        self._save_config()

    def _check_app_update(self, manual):
        url = (self.update_url.get() or "").strip()
        if "SEU_USUARIO" in url or not url:
            if manual:
                self.events.put(("app_update", {"error": tr("st.update_no_url")}, True))
            return

        def work():
            try:
                self.events.put(("app_update", core.check_app_update(url), manual))
            except Exception as exc:
                self.events.put(("app_update", {"error": core.short_error(exc)}, manual))
        threading.Thread(target=work, daemon=True).start()

    def _show_app_update_label(self):
        info, label = self.app_update_info, getattr(self, "update_label", None)
        if label is None:
            return
        if not info:
            label.configure(text="")
            return
        if info.get("error"):
            label.configure(text=tr("st.update_error", err=info["error"]) if info["error"] != tr("st.update_no_url") else info["error"])
            self.release_button.pack_forget()
        elif info.get("newer"):
            label.configure(text=tr("st.update_available", v=info["latest"]))
            if info.get("url"):
                self.release_button.pack(side="left", padx=(px(6), 0))
        else:
            label.configure(text=tr("st.update_none", v=APP_VERSION))
            self.release_button.pack_forget()

    def _open_release(self):
        if self.app_update_info and self.app_update_info.get("url"):
            webbrowser.open(self.app_update_info["url"])

    # ------------------------------------------------------------------ ícone personalizado
    def _choose_icon(self):
        path = filedialog.askopenfilename(parent=self, title=tr("dlg.pick_image"),
                                          filetypes=[(tr("dlg.images"), "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.ico"), (tr("dlg.all"), "*.*")])
        if not path:
            return
        try:
            from PIL import Image
        except ImportError:
            self.toast(tr("st.icon_needs_pillow"), "err")
            return
        try:
            img = Image.open(path).convert("RGBA")
            side = min(img.size)                       # recorta o centro para ficar quadrada
            left, top = (img.width - side) // 2, (img.height - side) // 2
            img = img.crop((left, top, left + side, top + side)).resize((256, 256), Image.LANCZOS)
            png, ico = self._custom_icon_paths()
            png.parent.mkdir(parents=True, exist_ok=True)
            img.resize((512, 512), Image.LANCZOS).save(png)
            img.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        except Exception as exc:
            self.toast(tr("st.icon_fail", err=exc), "err")
            return
        self._set_app_icon()
        self.rebuild_ui()
        self.toast(tr("st.icon_applied"), "ok")

    def _reset_icon(self):
        for p in self._custom_icon_paths():
            try:
                p.unlink()
            except OSError:
                pass
        self._set_app_icon()
        self.rebuild_ui()
        self.toast(tr("st.icon_reset"), "ok")

    # ------------------------------------------------------------------ histórico
    def _add_history(self, report):
        if not report.items and not report.conflicts:
            return
        entry = report.to_dict()
        entry["counts"] = report.counts
        self.history.insert(0, entry)
        del self.history[HISTORY_LIMIT:]
        self._save_history()

    def _clear_history(self):
        self.history = []
        self._save_history()
        self._render_history()

    def _render_history(self):
        sc = getattr(self, "history_scroll", None)
        if sc is None:
            return
        sc.clear()
        if not self.history:
            Label(sc.inner, tr("hs.empty"), fg="muted").pack(anchor="w")
            return
        for entry in self.history:
            card = Card(sc.inner, pad=14)
            card.pack(fill="x", pady=(0, px(10)), padx=(0, px(2)))
            c = entry.get("counts", {})
            when = datetime.fromtimestamp(entry.get("finished") or entry.get("started") or time.time()).strftime("%d/%m/%Y %H:%M")
            Label(card.body, tr("hs.entry_title", date=when, mc=entry.get("game_version", "?"),
                                loader=LOADER_LABELS.get(entry.get("loader"), entry.get("loader", "?"))), font="bodyb").pack(anchor="w")
            Label(card.body, tr("hs.counts", ok=c.get("downloaded", 0), skip=c.get("skipped", 0),
                                inc=c.get("incompatible", 0), err=c.get("failed", 0)), fg="muted", font="small").pack(anchor="w", pady=(px(2), px(10)))
            row = Box(card.body)
            row.pack(anchor="w")
            Button(row, tr("btn.report"), icon="report", height=32, padx=14,
                   command=lambda e=entry: self.show_report(core.Report.from_dict(e))).pack(side="left")
            Button(row, tr("btn.open_folder"), kind="ghost", icon="folder", height=32, padx=12,
                   command=lambda e=entry: self._open_folder(e.get("folder", ""))).pack(side="left", padx=px(6))

    # ------------------------------------------------------------------ relatório final
    def show_report(self, rep):
        """Janela com o resumo: baixados, pulados, incompatíveis e falhas + copiar incompatíveis / exportar log."""
        if self._report_win is not None:
            try:
                self._report_win.destroy()
            except Exception:
                pass
        win = tk.Toplevel(self)
        self._report_win = win
        win.title(tr("rp.title"))
        win.configure(bg=T["content"])
        win.transient(self)
        try:
            if sys.platform == "win32":
                win.iconbitmap(self._icon_files()[1])
        except Exception:
            pass
        w, h = min(px(780), self.winfo_screenwidth() - 40), min(px(660), self.winfo_screenheight() - 80)
        x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.minsize(px(620), px(480))

        body = Box(win, role="content")
        body.pack(fill="both", expand=True, padx=px(28), pady=px(24))
        Label(body, tr("rp.title"), font="h1").pack(anchor="w")
        Label(body, tr("rp.subtitle", mc=rep.game_version, loader=LOADER_LABELS.get(rep.loader, rep.loader), folder=rep.folder),
              fg="muted", font="small").pack(anchor="w", pady=(px(4), px(16)))

        counts = rep.counts
        tiles = Box(body)
        tiles.pack(fill="x")
        for i, (key, label, color) in enumerate((("downloaded", "rp.downloaded", "ok"), ("skipped", "rp.skipped", "info"),
                                                  ("incompatible", "rp.incompatible", "warn"), ("failed", "rp.failed", "err"))):
            tiles.columnconfigure(i, weight=1, uniform="t")
            tile = Card(tiles, pad=14)
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else px(6), 0 if i == 3 else px(6)))
            Label(tile.body, str(counts[key]), fg=color, font="h1").pack(anchor="w")
            Label(tile.body, tr(label), fg="muted", font="small").pack(anchor="w")
        if counts["corrupted"]:
            Label(body, "🛡  " + tr("rp.corrupted_note", n=counts["corrupted"]), fg="err", font="small").pack(anchor="w", pady=(px(10), 0))

        box = TextBox(body, font="body", on_theme=self._style_cards)
        box.pack(fill="both", expand=True, pady=(px(14), px(14)))
        self._fill_report_details(box.text, rep)

        btns = Box(body)
        btns.pack(fill="x")
        Button(btns, tr("btn.copy_incompatible"), icon="copy", height=38, padx=16, command=lambda: self._copy_incompatible(rep, win)).pack(side="left")
        Button(btns, tr("btn.export_log"), icon="export", height=38, padx=16,
               command=lambda: self._export_log_text(rep.log_text(), win, self._report_summary(rep))).pack(side="left", padx=px(8))
        Button(btns, tr("btn.open_folder"), icon="folder", height=38, padx=16, command=lambda: self._open_folder(rep.folder)).pack(side="left")
        Button(btns, tr("btn.close"), kind="primary", height=38, padx=20, command=win.destroy).pack(side="right")
        win.after(250, lambda: self._set_native_titlebar(win))
        win.focus_force()

    def _fill_report_details(self, text, rep):
        sections = (("rp.sec_incompatible", "incompatible", "warn"), ("rp.sec_failed", "failed", "err"),
                    ("rp.sec_corrupted", "corrupted", "err"), ("rp.sec_skipped", "skipped", "info"))
        text.configure(state="normal")
        text.delete("1.0", "end")
        any_detail = False
        for title_key, status, color in sections:
            items = rep.by_status(status)
            if not items:
                continue
            any_detail = True
            text.insert("end", f"{tr(title_key)} ({len(items)})\n", ("h",))
            for it in items:
                detail = f" — {it['detail']}" if it.get("detail") else ""
                text.insert("end", f"  • {it['title']}{detail}\n", ("k_" + color,))
            text.insert("end", "\n", ("m",))
        if rep.conflicts:
            any_detail = True
            text.insert("end", f"{tr('rp.sec_conflicts')} ({len(rep.conflicts)})\n", ("h",))
            for c in rep.conflicts:
                text.insert("end", f"  • {core.conflict_text(c)}\n", ("k_warn",))
        if not any_detail:
            text.insert("end", tr("rp.no_details"), ("m",))
        text.configure(state="disabled")

    @staticmethod
    def _report_summary(rep):
        c = rep.counts
        return tr("status.finished", state=tr("state.stopped") if rep.stopped else tr("state.done"),
                  ok=c["downloaded"], skip=c["skipped"], inc=c["incompatible"], err=c["failed"])

    def _copy_incompatible(self, rep, win):
        lines = rep.incompatible_lines()
        if not lines:
            self.toast(tr("rp.none_incompatible"))
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.update()
        self.toast(tr("rp.copied", n=len(lines)), "ok")

    # ------------------------------------------------------------------ fila de eventos (threads → interface)
    def _drain_events(self):
        try:
            for _ in range(400):
                self._handle_event(self.events.get_nowait())
        except queue.Empty:
            pass
        except Exception as exc:       # um evento com problema não pode derrubar a interface
            try:
                self._append_log(tr("log.err", slug="UI", err=exc), "err")
            except Exception:
                pass
        self.after(100, self._drain_events)

    def _handle_event(self, event):
        kind = event[0]
        if kind == "log":
            self._append_log(event[2], event[1])
        elif kind == "manifests":
            self.last_manifests = event[1]
            self.update_results = []
            self._render_mods()
        elif kind == "progress":
            _, done, total, active, speed, size = event
            self.progress.set(done, total)
            self.percent.configure(text=f"{int(100 * min(done, total) / max(1, total))}%")
            if active:
                self._status(tr("status.working", n=active, size=core.human_size(size), speed=core.human_speed(speed)), "accent")
            else:
                self._status(tr("status.resolving"), "accent")
        elif kind == "file":
            self._file_event(*event[1:])
        elif kind == "file_done":
            self._file_done(event[1])
        elif kind == "scan_progress":
            _, i, n, name = event
            self.progress.set(i, n)
            self.percent.configure(text=f"{int(100 * i / max(1, n))}%")
            self._status(tr("status.reading", name=name), "accent")
        elif kind == "scan_done":
            self._on_scan_done(*event[1:])
        elif kind == "updates":
            self._on_updates(event[1])
        elif kind == "updates_error":
            self._append_log(tr("log.upd_fail", err=core.short_error(event[1])), "err")
            self._status(tr("log.upd_fail", err=core.short_error(event[1])), "err")
            self._sync_buttons()
        elif kind == "finished":
            self._on_finished(event[1])
        elif kind == "preview":
            _, token, rows, extra = event
            if token == self.preview_token:
                self.preview_rows = rows
                self._render_preview(rows, extra)
        elif kind == "versions":
            _, versions, announce, error = event
            if versions:
                self._apply_versions(versions)
                if announce:
                    self.toast(tr("st.versions_loaded", n=len(versions)), "ok")
            elif announce:
                self.toast(tr("st.versions_failed"))
        elif kind == "app_update":
            _, info, manual = event
            self.app_update_info = info
            self._show_app_update_label()
            if info.get("newer"):
                self.toast(tr("toast.new_version", v=info["latest"]), "accent")
            elif manual:
                self.toast(self.update_label.cget("text") or "", "ok" if not info.get("error") else "warn")

    def _on_scan_done(self, manifests, conflicts, bad, missing):
        self.last_manifests = manifests
        self.update_results = []
        self.progress.set(1, 1)
        self.percent.configure(text="100%")
        extra = (tr("status.scan_extra_bad", n=bad) if bad else "") + (tr("status.scan_extra_missing", n=missing) if missing else "")
        self._status(tr("status.scan_done", n=len(manifests), extra=extra), "warn" if (bad or missing or conflicts) else "ok")
        self._update_scan_info()
        self._render_mods()
        self._sync_buttons()
        if conflicts:
            self.toast(tr("toast.conflicts"))

    def _on_updates(self, results):
        self.update_results = results
        n = 0
        for r in results:
            if r["status"] == "update":
                n += 1
                m, new = r["manifest"], r["latest"]
                self._append_log(tr("log.upd_found", name=m.get("name") or Path(m["file"]).name,
                                    cur=(r["current"] or {}).get("version_number", "?"), new=new.get("version_number", "?")), "accent")
        if not n:
            self._append_log(tr("log.upd_none"), "ok")
        self._status(tr("md.check_done", n=n) if n else tr("md.check_done_none"), "warn" if n else "ok")
        self._render_mods()
        self._sync_buttons()

    def _on_finished(self, rep):
        counts = rep.counts
        self._running_engine = False
        self._show_active(False)
        if not rep.stopped:
            self.progress.set(1, 1)
            self.percent.configure(text="100%")
        summary = self._report_summary(rep)
        kind = "warn" if rep.stopped else "err" if counts["failed"] else "ok"
        self._status(summary, kind)
        self._append_log(summary, kind if kind != "err" else "err")
        self._add_history(rep)
        self._render_history()
        self._save_config()
        self._sync_buttons()
        if rep.conflicts:
            self.toast(tr("toast.conflicts"))
        if self.notify.get():
            core.notify_windows(tr("notify.title"), tr("notify.body", ok=counts["downloaded"], skip=counts["skipped"],
                                                      inc=counts["incompatible"], err=counts["failed"]))
        self.show_report(rep)
        if self._after_run == "rescan":
            self._after_run = None
            self.after(300, self._scan_folder)


if __name__ == "__main__":
    ui.enable_dpi_awareness()
    App().mainloop()
