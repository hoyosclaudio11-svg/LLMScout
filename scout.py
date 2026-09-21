# -*- coding: utf-8 -*-
"""LLM Scout — panel de escritorio que detecta la tarea activa y sugiere
los mejores LLMs según benchmarks. v1.

Uso:
    python scout.py              panel (GUI)
    python scout.py --scan       qué detecta ahora mismo (5 muestras)
    python scout.py --top coding top 3 para una categoría
    python scout.py --stats      adopción (real + manual)
"""

import argparse
import json
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

import tkinter as tk

AQUI = Path(__file__).parent
DATA_DIR = AQUI / "data"
sys.path.insert(0, str(AQUI))

import detector  # noqa: E402
from detector import tarea_activa, ETIQUETA, CATEGORIAS, usuario_activo  # noqa: E402
import benchmarks  # noqa: E402
import gateway  # noqa: E402
import noticias  # noqa: E402
from storage import DB  # noqa: E402

__version__ = "1.1"

LOG = DATA_DIR / "scout.log"
DB_PATH = DATA_DIR / "scout.db"
UI_JSON = DATA_DIR / "ui.json"
OVERRIDES_JSON = DATA_DIR / "overrides.json"
PUERTO_INSTANCIA = 51753  # bind sin listen: guard de instancia única
POLL_MS = 3000
CICLOS_GATEWAY = 20       # un chequeo de pedidos cada ~60 s
MM_DEFAULT = AQUI.parent / "ModelMatch" / "datos" / "modelmatch.db"

# tema
BG = "#12151b"
CARD = "#1a2028"
CARD2 = "#232b38"
TXT = "#e8ecf3"
MUT = "#8b95a7"
LINE = "#2a3444"
ACCENT = {"coding": "#4da3ff", "writing": "#e8a04c", "data": "#59c98f",
          "research": "#b48cf2", "media": "#f2708f", "chat": "#5ad1cd",
          "general": "#8b95a7"}
MEDALLA = {1: "#f5c451", 2: "#c7ccd6", 3: "#cd8f5a"}

# noticias de IA: aparecen de vez en cuando, no todo el tiempo
NOTI_PRIMERA = 3 * 60    # primera aparición: a los 3 min de arrancar
NOTI_INTERVALO = 12 * 60 # cada cuánto vuelve a aparecer
NOTI_DURACION = 150      # cuánto tiempo queda visible
NOTI_CICLO = 45          # rotación de titular mientras está visible
ALPHA_DEF = 0.88


def _log(msg):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _excepthook(t, v, tb):
    _log("EXCEPCION:\n" + "".join(traceback.format_exception(t, v, tb)))
    sys.__excepthook__(t, v, tb)


sys.excepthook = _excepthook


def _cargar_json(path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def _mm_default():
    return str(MM_DEFAULT)


_guard = None


def _instancia_unica():
    """True si somos la única instancia (bind de un puerto local sin listen)."""
    global _guard
    try:
        _guard = socket.socket()
        _guard.bind(("127.0.0.1", PUERTO_INSTANCIA))
        return True
    except OSError:
        return False


# ------------------------------------------------------------------- panel ---

class Panel:
    def __init__(self, root):
        self.root = root
        self.db = DB(DB_PATH)
        ui = _cargar_json(UI_JSON, {})
        self.mm_db = ui.get("modelmatch_db") or _mm_default()
        self.overrides = _cargar_json(OVERRIDES_JSON, {})
        self.modelos = None
        self.fuente = ""
        self.locales = []
        self.locales_ts = 0
        self.solo_local = tk.BooleanVar(value=False)
        self.topmost = tk.BooleanVar(value=bool(ui.get("topmost", True)))
        self.noticias_on = tk.BooleanVar(value=bool(ui.get("noticias", True)))
        self.alpha = float(ui.get("alpha", ALPHA_DEF))
        if not 0.3 <= self.alpha <= 1.0:
            self.alpha = ALPHA_DEF
        self.alpha_var = tk.DoubleVar(value=self.alpha)
        self.usos_modelo = {}
        self._cat = None
        self._app_actual = ""
        self._proceso = ""
        self._ticks = 0
        self._gw_listo = False
        # estado de la franja de noticias
        self._noti_items, self._noti_idx = [], 0
        self._noti_visible = False
        self._noti_hover = False
        self._noti_t_mostrar = time.time() + NOTI_PRIMERA
        self._noti_t_ocultar = 0

        root.title("LLM Scout")
        root.configure(bg=BG)
        root.overrideredirect(True)
        root.attributes("-topmost", self.topmost.get())
        root.attributes("-alpha", self.alpha)

        self._armar_ui()
        self._posicionar(ui)
        self._bind_drag()
        self._menu()

        threading.Thread(target=self._recargar, daemon=True).start()
        threading.Thread(target=self._noticias_loop, daemon=True).start()
        root.after(POLL_MS, self._tick)
        root.protocol("WM_DELETE_WINDOW", self._salir)
        _log(f"inicio v{__version__}")

    # ---- UI base
    def _armar_ui(self):
        pad = {"bg": BG}

        header = tk.Frame(self.root, **pad)
        header.pack(fill="x", padx=12, pady=(10, 2))
        self.dot = tk.Canvas(header, width=8, height=8, bg=BG, highlightthickness=0)
        self.dot.create_oval(1, 1, 7, 7, fill=MUT, outline="")
        self.dot.pack(side="left")
        tk.Label(header, text=" LLM Scout", bg=BG, fg=TXT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        btn_top = tk.Label(header, text="📌", bg=BG, fg=MUT, cursor="hand2",
                           font=("Segoe UI", 9))
        btn_top.pack(side="right", padx=(6, 0))
        btn_top.bind("<Button-1>", lambda e: self._toggle_top())
        btn_close = tk.Label(header, text="✕", bg=BG, fg=MUT, cursor="hand2",
                             font=("Segoe UI", 9))
        btn_close.pack(side="right")
        btn_close.bind("<Button-1>", lambda e: self._salir())
        btn_ref = tk.Label(header, text="↻", bg=BG, fg=MUT, cursor="hand2",
                           font=("Segoe UI", 10, "bold"))
        btn_ref.pack(side="right", padx=6)
        btn_ref.bind("<Button-1>", lambda e: self._recargar_thread())

        self.lbl_tarea = tk.Label(self.root, text="Mirando qué hacés…", bg=BG,
                                  fg=TXT, font=("Segoe UI", 11, "bold"),
                                  anchor="w", wraplength=330, justify="left")
        self.lbl_tarea.pack(fill="x", padx=12, pady=(2, 0))
        self.lbl_ctx = tk.Label(self.root, text="", bg=BG, fg=MUT,
                                font=("Segoe UI", 8), anchor="w",
                                wraplength=330, justify="left")
        self.lbl_ctx.pack(fill="x", padx=12)

        self.frame_cards = tk.Frame(self.root, bg=BG)
        self.frame_cards.pack(fill="x", padx=12, pady=6)

        self.lbl_carga = tk.Label(self.frame_cards, text="Cargando benchmarks…",
                                  bg=BG, fg=MUT, font=("Segoe UI", 9))
        self.lbl_carga.pack(pady=20)

        # --- franja de noticias de IA (aparece de vez en cuando) ---
        self.frame_noti = tk.Frame(self.root, bg=BG)
        tk.Frame(self.frame_noti, height=1, bg=LINE).pack(fill="x", pady=(0, 5))
        fila_noti = tk.Frame(self.frame_noti, bg=BG)
        fila_noti.pack(fill="x")
        tk.Label(fila_noti, text="📰", bg=BG, fg=MUT,
                 font=("Segoe UI", 8)).pack(side="left")
        self.lbl_noti = tk.Label(fila_noti, text="", bg=BG, fg=TXT,
                                 font=("Segoe UI", 8), anchor="w",
                                 wraplength=290, justify="left", cursor="hand2")
        self.lbl_noti.pack(side="left", padx=(4, 0))
        self.lbl_noti.bind("<Button-1>", self._noti_abrir)
        btn_noti_x = tk.Label(fila_noti, text="✕", bg=BG, fg=MUT,
                              cursor="hand2", font=("Segoe UI", 8))
        btn_noti_x.pack(side="right")
        btn_noti_x.bind("<Button-1>", lambda e: self._noti_ocultar())
        self.lbl_noti_meta = tk.Label(self.frame_noti, text="", bg=BG, fg=MUT,
                                      font=("Segoe UI", 7), anchor="w")
        self.lbl_noti_meta.pack(fill="x")
        self.lbl_noti_meta.bind("<Button-1>", self._noti_abrir)
        for w in (self.frame_noti, fila_noti):
            w.bind("<Enter>", lambda e: setattr(self, "_noti_hover", True))
            w.bind("<Leave>", lambda e: setattr(self, "_noti_hover", False))
        self._pie = None  # se asigna abajo para poder ordenar el pack

        pie = tk.Frame(self.root, bg=BG)
        self._pie = pie
        pie.pack(fill="x", padx=12, pady=(0, 8))
        self.lbl_filtro = tk.Checkbutton(
            pie, text="Solo FreeLLMAPI (3001)", variable=self.solo_local,
            command=self._toggle_filtro, bg=BG, fg=MUT, activebackground=BG,
            activeforeground=TXT, selectcolor=CARD2, font=("Segoe UI", 8),
            highlightthickness=0, bd=0, cursor="hand2")
        self.lbl_filtro.pack(side="left")
        self.lbl_pie = tk.Label(pie, text="", bg=BG, fg=MUT,
                                font=("Segoe UI", 8), anchor="e",
                                wraplength=210, justify="right")
        self.lbl_pie.pack(side="right")
        self._pintar_pie()

    def _posicionar(self, ui):
        self.root.update_idletasks()
        w, h = 370, 430
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = ui.get("x"), ui.get("y")
        if isinstance(x, int) and isinstance(y, int) and -w < x < sw and -h < y < sh:
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        else:
            self.root.geometry(f"{w}x{h}+{sw - w - 16}+{sh - h - 60}")

    def _bind_drag(self):
        for w in (self.root, self.lbl_tarea, self.lbl_ctx):
            w.bind("<Button-1>", self._down, add="+")
            w.bind("<B1-Motion>", self._move, add="+")
            w.bind("<ButtonRelease-1>", lambda e: self._guardar_pos(), add="+")

    def _down(self, e):
        self._dx, self._dy = e.x, e.y

    def _move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TXT, bd=0)
        m.add_command(label="Recargar benchmarks", command=self._recargar_thread)
        m.add_checkbutton(label="Siempre arriba", variable=self.topmost,
                          command=self._toggle_top)
        m.add_separator()
        m.add_checkbutton(label="Noticias de IA de vez en cuando",
                          variable=self.noticias_on,
                          command=self._toggle_noticias)
        m.add_command(label="Ver noticias ahora", command=self._noticias_ahora)
        m_t = tk.Menu(m, tearoff=0, bg=CARD, fg=TXT, bd=0)
        for pct in (100, 90, 80, 70, 60):
            m_t.add_radiobutton(label=f"{pct} %", value=pct / 100,
                                variable=self.alpha_var, command=self._set_alpha)
        m.add_cascade(label="Transparencia", menu=m_t)
        m.add_separator()
        m.add_command(label="Abrir carpeta de datos", command=self._abrir_datos)
        m.add_command(label="Salir", command=self._salir)
        for w in (self.root, self.lbl_tarea):
            w.bind("<Button-3>", lambda e: m.tk_popup(e.x_root, e.y_root))

    def _set_alpha(self):
        self.alpha = round(float(self.alpha_var.get()), 2)
        self.root.attributes("-alpha", self.alpha)
        self._guardar_pos()

    def _toggle_noticias(self):
        if self.noticias_on.get():
            self._noti_t_mostrar = time.time() + 30  # reactivada: en 30 s
        elif self._noti_visible:
            self._noti_ocultar()
        self._guardar_pos()

    def _toggle_top(self):
        self.root.attributes("-topmost", self.topmost.get())
        self._guardar_pos()

    def _abrir_datos(self):
        import os
        os.startfile(str(DATA_DIR))

    def _salir(self):
        self._guardar_pos()
        self.root.destroy()

    def _guardar_pos(self):
        try:
            d = _cargar_json(UI_JSON, {})
            d.update({"x": self.root.winfo_x(), "y": self.root.winfo_y(),
                      "topmost": bool(self.topmost.get()),
                      "alpha": self.alpha,
                      "noticias": bool(self.noticias_on.get())})
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            UI_JSON.write_text(json.dumps(d), "utf-8")
        except Exception:
            pass

    # ---- datos
    def _recargar_thread(self):
        solo = bool(self.solo_local.get())
        threading.Thread(target=self._recargar, args=(solo,), daemon=True).start()

    def _recargar(self, solo=False):
        try:
            if not self._gw_listo:
                self._gw_listo = gateway.inicial(self.db, self.mm_db)
            filtro = None
            if solo:
                self._asegurar_locales()
                filtro = self.locales
            modelos, fuente = benchmarks.cargar(filtro)
            self.modelos, self.fuente = modelos, fuente
            self.root.after(0, self._repintar_si_hay_tarea)
            # segunda pasada con precios frescos de OpenRouter (red)
            if benchmarks.refrescar_precios():
                modelos, fuente = benchmarks.cargar(filtro)
                self.modelos, self.fuente = modelos, fuente
                self.root.after(0, self._repintar_si_hay_tarea)
        except Exception:
            _log("error recargando:\n" + traceback.format_exc())

    def _asegurar_locales(self):
        # cache de 60 s para no golpear el gateway
        if time.time() - self.locales_ts < 60:
            return
        self.locales = benchmarks.models_locales()
        self.locales_ts = time.time()

    def _toggle_filtro(self):
        self._recargar_thread()

    # ---- noticias de IA (franja intermitente) ----
    def _noticias_loop(self):
        """Trae el feed en background y lo refresca cada 30 min."""
        while True:
            if self.noticias_on.get():
                items, estado = noticias.cargar()
                if items or estado != "vacio":
                    self._noti_items = items
                elif self._noti_items:
                    pass  # sin red: quedarnos con lo último que haya
            time.sleep(30 * 60)

    def _noticias_ahora(self):
        def traer():
            items, _ = noticias.cargar(forzar=True)
            self._noti_items = items or self._noti_items
            if self._noti_items:
                self.root.after(0, self._noti_mostrar)
        threading.Thread(target=traer, daemon=True).start()

    def _noti_tick(self):
        """Programado desde _tick: decide si la franja entra o sale."""
        if not self.noticias_on.get():
            return
        ahora = time.time()
        if self._noti_visible:
            if ahora > self._noti_t_ocultar and not self._noti_hover:
                self._noti_ocultar()
        elif self._noti_items and ahora >= self._noti_t_mostrar:
            self._noti_mostrar()

    def _noti_mostrar(self):
        if not self._noti_items or self._noti_visible:
            return
        self._noti_visible = True
        self._noti_idx %= max(1, len(self._noti_items))
        self._noti_pintar()
        self._noti_t_ocultar = time.time() + NOTI_DURACION
        self.frame_noti.pack(fill="x", padx=12, before=self._pie)
        self._ajustar_geo()
        self.root.after(NOTI_CICLO * 1000, self._noti_rotar)

    def _noti_ocultar(self):
        self._noti_visible = False
        self._noti_hover = False
        self.frame_noti.pack_forget()
        self._ajustar_geo()
        self._noti_t_mostrar = time.time() + NOTI_INTERVALO

    def _noti_rotar(self):
        if not self._noti_visible:
            return
        self._noti_idx = (self._noti_idx + 1) % len(self._noti_items)
        self._noti_pintar()
        self.root.after(NOTI_CICLO * 1000, self._noti_rotar)

    def _noti_pintar(self):
        if not self._noti_items:
            return
        it = self._noti_items[self._noti_idx]
        self.lbl_noti.config(text=it["titulo"])
        cuando = noticias.hace(it["ts"])
        self.lbl_noti_meta.config(
            text=f"{it['fuente']}" + (f" · {cuando}" if cuando else ""))

    def _noti_abrir(self, _e=None):
        if self._noti_items:
            webbrowser.open(self._noti_items[self._noti_idx]["link"])

    def _ajustar_geo(self):
        """Recalcula el alto real del panel y lo baja si queda fuera de pantalla."""
        try:
            self.root.update_idletasks()
            h = min(self.root.winfo_reqheight(),
                    self.root.winfo_screenheight() - 20)
            x, y = self.root.winfo_x(), self.root.winfo_y()
            if y + h > self.root.winfo_screenheight() - 10:
                y = max(0, self.root.winfo_screenheight() - 10 - h)
            self.root.geometry(f"370x{h}+{x}+{y}")
        except Exception:
            pass

    # ---- loop de detección
    def _tick(self):
        self._ticks += 1
        if self._ticks % CICLOS_GATEWAY == 0:
            threading.Thread(target=self._chequeo_gateway, daemon=True).start()
        self._noti_tick()
        try:
            # higiene de la métrica: sin input reciente o PC bloqueada -> no contar
            if usuario_activo(max_idle_seg=300):
                info = tarea_activa()
                if info and not (info["proceso"] in ("python", "pythonw")
                                 and "llm scout" in info["titulo"].lower()):
                    self._proceso = info["proceso"]
                    override = self.overrides.get(info["proceso"])
                    if override in CATEGORIAS:
                        info["categoria"] = override
                        info["etiqueta"] = ETIQUETA.get(override, override)
                    if (info["categoria"] != self._cat
                            or info["app"] != self._app_actual):
                        self._cat = info["categoria"]
                        self._app_actual = info["app"]
                        self._repintar(info)
                        self.dot.itemconfig(1, fill=ACCENT.get(info["categoria"], MUT))
        except Exception:
            _log("error tick:\n" + traceback.format_exc())
        self.root.after(POLL_MS, self._tick)

    def _chequeo_gateway(self):
        try:
            if gateway.chequear(self.db, self.mm_db):
                self.root.after(0, self._post_gateway)
        except Exception:
            _log("error gateway:\n" + traceback.format_exc())

    def _post_gateway(self):
        self._pintar_pie()
        self._repintar_si_hay_tarea()

    def _repintar_si_hay_tarea(self):
        info = None
        if self._cat:
            info = {"categoria": self._cat, "app": self._app_actual,
                    "titulo": "", "etiqueta": ETIQUETA.get(self._cat, "")}
        else:
            t = tarea_activa()
            if t and not (t["proceso"] in ("python", "pythonw")
                          and "llm scout" in t["titulo"].lower()):
                self._cat = t["categoria"]
                self._app_actual = t["app"]
                info = t
        if info is None:  # sin tarea detectada todavía: sugerencias generales
            info = {"categoria": "general", "app": "", "titulo": "",
                    "etiqueta": ETIQUETA["general"]}
        self._repintar(info)

    # ---- tarjetas
    def _repintar(self, info):
        if self.modelos is None:
            return
        cat = info["categoria"]
        recs = benchmarks.recomendar(cat, self.modelos)
        if not recs:
            return

        for w in self.frame_cards.winfo_children():
            w.destroy()

        color = ACCENT.get(cat, MUT)
        self.lbl_tarea.config(
            text=f"{info['etiqueta']} — {info['app']}".rstrip(" —"), fg=color)
        self.lbl_ctx.config(text=info.get("titulo", ""))
        self.usos_modelo = self.db.usos_por_modelo()

        locales_on = bool(self.locales)
        for i, item in enumerate(recs, start=1):
            es_loc = locales_on and benchmarks.es_local(
                item["modelo"]["name"], self.locales)
            self._tarjeta(i, item, color=color, local=es_loc, cat=cat)

        self._pintar_pie()
        self.db.impresiones(cat, [(item["modelo"]["id"], i)
                                  for i, item in enumerate(recs, 1)])
        self._ajustar_geo()

    def _tarjeta(self, rank, item, color, local, cat):
        m = item["modelo"]
        rol_color = {"Mejor": color, "Equilibrado": "#e8a04c",
                     "Económico": "#59c98f"}.get(item["rol"], color)
        card = tk.Frame(self.frame_cards, bg=CARD, highlightbackground=LINE,
                        highlightthickness=1)
        card.pack(fill="x", pady=4)
        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(head, text=f"{rank}", bg=CARD, fg=MEDALLA.get(rank, MUT),
                 font=("Segoe UI", 12, "bold"), width=2).pack(side="left")
        tk.Label(head, text=item["rol"], bg=CARD, fg=rol_color,
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(2, 0))
        nombre = m["name"] + ("  ● local" if local else "")
        tk.Label(head, text=nombre, bg=CARD, fg=TXT,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=(4, 0))
        btn_ov = tk.Label(head, text="⋯", bg=CARD, fg=MUT, cursor="hand2",
                          font=("Segoe UI", 10, "bold"))
        btn_ov.pack(side="right")
        btn_ov.bind("<Button-1>", lambda e: self._menu_override(cat))
        tk.Label(head, text=m["provider"], bg=CARD, fg=MUT,
                 font=("Segoe UI", 8)).pack(side="right", padx=(0, 6))

        cuerpo = tk.Frame(card, bg=CARD)
        cuerpo.pack(fill="x", padx=10)
        usos_m = self.usos_modelo.get(m["id"], 0)
        extra = f" · tus usos: {usos_m}" if usos_m else ""
        tk.Label(cuerpo, text=f"{item['motivo']} · índice {item['indice']:.0f}{extra}",
                 bg=CARD, fg=color, font=("Segoe UI", 8), anchor="w",
                 wraplength=320, justify="left").pack(fill="x")
        tk.Label(cuerpo, text=item["nota"], bg=CARD, fg=MUT,
                 font=("Segoe UI", 8), anchor="w",
                 wraplength=320, justify="left").pack(fill="x", pady=(1, 4))

        fila = tk.Frame(card, bg=CARD)
        fila.pack(fill="x", padx=10, pady=(0, 8))
        b_uso = tk.Button(fila, text="✓ Usé este", bg=CARD2, fg=TXT, relief="flat",
                          activebackground=LINE, activeforeground=TXT, bd=0,
                          font=("Segoe UI", 8), cursor="hand2",
                          command=lambda: self._uso(b_uso, cat, m, pos))
        b_uso.pack(side="left")
        url = benchmarks.url_web(m["name"])
        if url:
            b_open = tk.Button(fila, text="Abrir ↗", bg=CARD, fg=MUT, relief="flat",
                               activebackground=CARD2, activeforeground=TXT, bd=0,
                               font=("Segoe UI", 8), cursor="hand2",
                               command=lambda u=url: webbrowser.open(u))
            b_open.pack(side="left", padx=8)
        b_copy = tk.Button(fila, text="Copiar nombre", bg=CARD, fg=MUT,
                           relief="flat", activebackground=CARD2, bd=0,
                           font=("Segoe UI", 8), cursor="hand2",
                           command=lambda n=m["name"]: self._copiar(n))
        b_copy.pack(side="left", padx=(0 if url else 8, 0))

    def _menu_override(self, cat_actual):
        m = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TXT, bd=0)
        m.add_command(label="Esta ventana es otra cosa:", state="disabled",
                      background=CARD, foreground=MUT)

        def set_cat(c):
            if self._proceso:
                self.overrides[self._proceso] = c
                try:
                    OVERRIDES_JSON.write_text(json.dumps(self.overrides), "utf-8")
                except Exception:
                    pass
                self._cat = c
                self._app_actual = ""
                self._repintar_si_hay_tarea()

        for c in CATEGORIAS:
            marca = "✓ " if c == cat_actual else ""
            m.add_command(label=f"{marca}{ETIQUETA[c]}",
                          command=lambda c=c: set_cat(c))
        m.tk_popup(self.root.winfo_x() + 40, self.root.winfo_y() + 80)

    def _pintar_pie(self):
        t = self.db.tasa()
        fuente = self.fuente if len(self.fuente) <= 42 else self.fuente[:40] + "…"
        self.lbl_pie.config(text=(
            f"adopción hoy {t['reales_hoy']} real + {t['manuales_hoy']} manual "
            f"/ {t['imp_hoy']} · {fuente}"))

    def _uso(self, btn, cat, m, pos):
        self.db.uso(cat, m["id"], pos)
        btn.config(text="✓ anotado", state="disabled")
        self._pintar_pie()

    def _copiar(self, nombre):
        self.root.clipboard_clear()
        self.root.clipboard_append(nombre)


# -------------------------------------------------------------------- CLI ----

def cli_scan():
    print("muestreando la ventana activa 5 veces (1 s entre muestras)…")
    for _ in range(5):
        t = tarea_activa()
        if t:
            print(f"  {t['etiqueta']:16} · {t['app']:20} · {t['titulo'][:50]}")
        else:
            print("  (sin ventana activa)")
        time.sleep(1)


def cli_top(categoria):
    if categoria not in CATEGORIAS:
        print(f"categoría inválida. opciones: {', '.join(CATEGORIAS)}")
        return
    ms, f = benchmarks.cargar()
    print(f"fuente: {f}")
    for r in benchmarks.recomendar(categoria, ms):
        m = r["modelo"]
        url = benchmarks.url_web(m["name"])
        print(f"  [{r['rol']:11}] {m['name']:22} índice {r['indice']:5.1f} · "
              f"{r['nota'] or r['motivo']} · {url or '-'}")


def cli_stats():
    db = DB(DB_PATH)
    t = db.tasa()
    pct_h = (t["reales_hoy"] + t["manuales_hoy"]) / t["imp_hoy"] * 100 if t["imp_hoy"] else 0
    pct_t = (t["reales_tot"] + t["manuales_tot"]) / t["imp_tot"] * 100 if t["imp_tot"] else 0
    print(f"hoy : {t['reales_hoy']} reales + {t['manuales_hoy']} manuales "
          f"/ {t['imp_hoy']} sugerencias ({pct_h:.0f}%)")
    print(f"total: {t['reales_tot']} reales + {t['manuales_tot']} manuales "
          f"/ {t['imp_tot']} sugerencias ({pct_t:.0f}%)")
    filas = db.resumen()
    if filas:
        print("\npor modelo (30 días):  reales + manuales / mostradas")
        for m, r, u, i in filas:
            print(f"  {m:24} {r:3} + {u:3} / {i:3}")


def main():
    ap = argparse.ArgumentParser(description="LLM Scout")
    ap.add_argument("--scan", action="store_true", help="probar el detector")
    ap.add_argument("--top", metavar="CAT", help="top 3 para una categoría")
    ap.add_argument("--stats", action="store_true", help="adopción registrada")
    args = ap.parse_args()

    if args.scan:
        cli_scan()
    elif args.top:
        cli_top(args.top)
    elif args.stats:
        cli_stats()
    else:
        if not _instancia_unica():
            _log("otra instancia ya está corriendo; saliendo")
            print("LLM Scout ya está corriendo.")
            sys.exit(0)
        root = tk.Tk()
        Panel(root)
        root.mainloop()


if __name__ == "__main__":
    main()
