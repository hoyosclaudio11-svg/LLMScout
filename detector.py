# -*- coding: utf-8 -*-
"""Detector de tarea activa: lee la ventana en foco (Win32, sin dependencias)
y la clasifica en una categoría de trabajo."""

import ctypes
import re
from ctypes import wintypes

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetLastInputInfo.argtypes = [ctypes.c_void_p]
_user32.GetLastInputInfo.restype = wintypes.BOOL
_user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_user32.OpenInputDesktop.restype = wintypes.HANDLE
_user32.CloseDesktop.argtypes = [wintypes.HANDLE]
_kernel32.GetTickCount.restype = wintypes.DWORD
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

CATEGORIAS = ["coding", "writing", "data", "research", "media", "chat", "general"]
ETIQUETA = {
    "coding": "Programación",
    "writing": "Escritura",
    "data": "Datos / Análisis",
    "research": "Investigación",
    "media": "Diseño / Media",
    "chat": "Chat IA",
    "general": "General",
}

# exe (sin extensión, minúscula) -> categoría
PROCESOS = {
    "coding": {
        "code", "code - insiders", "codium", "cursor", "windsurf",
        "pycharm", "pycharm64", "idea", "idea64", "webstorm", "webstorm64",
        "clion", "clion64", "rider", "rider64", "devenv", "sublime_text",
        "notepad++", "windowsterminal", "openconsole", "conhost",
        "powershell", "pwsh", "cmd", "mintty", "git", "gitkraken", "fork",
        "githubdesktop", "dbeaver", "heidisql", "ssms", "metaeditor64",
        "winmerge", "kdiff3", "filezilla", "winscp", "putty", "mobaxterm",
        "postman", "insomnia", "docker", "dockerdesktop",
    },
    "writing": {
        "winword", "notepad", "obsidian", "notion", "onenote", "typora",
        "marktext", "zettlr", "scrivener", "soffice", "powerpnt",
        "wps", "wpsoffice", "et", "wordpad",
    },
    "data": {
        "excel", "jupyter", "jupyter-lab", "jupyter-notebook", "qtconsole",
        "spyder", "rstudio", "rgui", "matlab", "stata", "eviews",
        "powerbi", "tableau", "terminal64",
    },
    "research": {
        "chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "arc",
        "thorium", "librewolf", "waterfox", "zotero", "mendeley",
        "sumatra", "sumatrapdf", "acrord32", "acrobat", "foxit", "pdf24",
        "okular", "calibre", "anki",
    },
    "media": {
        "figma", "photoshop", "gimp", "photo", "designer", "premiere",
        "afterfx", "encoder", "audition", "davinci", "resolve", "audacity",
        "blender", "camtasia", "obs64", "obs", "handbrake", "shotcut",
        "kdenlive", "vlc", "spotify", "canva",
    },
    "chat": {"chatgpt", "claude", "copilot", "perplexity"},
}
# aplanar el dict de conjuntos a conjunto -> categoría, para lookup O(1)
PROCESO_A_CAT = {p: cat for cat, procs in PROCESOS.items() for p in procs}

# para procesos sin mapeo directo (navegadores, apps raras): el título manda
TITULOS = [
    ("chat", r"\b(chatgpt|claude|gemini|copilot|grok|deepseek|kimi|qwen|perplexity|poe)\b"),
    ("coding", r"(github|gitlab|stack overflow|stackoverflow|pull request|codepen|replit|"
               r"codesandbox|vscode|visual studio|jetbrains|consola|powershell|npm|pip |docker|"
               r"traceback|json|regex|\.(py|js|ts|sql|mq5)\b)"),
    ("data", r"(sheets?\b|excel|jupyter|colab|notebook|dataset|csv|\bsql\b|power bi|tableau|"
             r"metatrader|backtest)"),
    ("writing", r"(google docs|\bword\b|notion|documento|obsidian|medium|substack|borrador|"
                 r"editorial|art[íi]culo|cap[íi]tulo)"),
    ("media", r"(youtube|netflix|figma|canva|photoshop|premiere|spotify|dise[ñn]o|thumbnail)"),
    ("research", r"(arxiv|wikipedia|paper|investigaci|research|journal|documentaci|\.pdf\b)"),
]
_TITULOS_COMP = [(cat, re.compile(rx)) for cat, rx in TITULOS]

NOMBRE_BONITO = {
    "code": "VS Code", "cursor": "Cursor", "windsurf": "Windsurf",
    "windowsterminal": "Windows Terminal", "powershell": "PowerShell",
    "pwsh": "PowerShell", "cmd": "CMD", "msedge": "Edge", "chrome": "Chrome",
    "firefox": "Firefox", "brave": "Brave", "winword": "Word",
    "excel": "Excel", "powerpnt": "PowerPoint", "onenote": "OneNote",
    "devenv": "Visual Studio", "pycharm64": "PyCharm", "idea64": "IntelliJ",
    "notepad++": "Notepad++", "sublime_text": "Sublime Text",
    "explorer": "Explorador", "terminal64": "MetaTrader 5",
    "metaeditor64": "MetaEditor", "obsidian": "Obsidian", "notion": "Notion",
    "figma": "Figma", "spyder": "Spyder", "jupyter-notebook": "Jupyter",
    "python": "Python", "pythonw": "LLM Scout", "chatgpt": "ChatGPT",
}


def _nombre_proceso(pid):
    """Ruta completa del exe de un pid, o '' si no se puede."""
    try:
        h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
            return ""
        finally:
            _kernel32.CloseHandle(h)
    except Exception:
        return ""


def _stem(exe):
    base = exe.replace("/", "\\").rsplit("\\", 1)[-1]
    return base.rsplit(".", 1)[0].lower() if "." in base else base.lower()


def clasificar(proceso_stem, titulo):
    cat = PROCESO_A_CAT.get(proceso_stem)
    if cat is None:
        t = titulo.lower()
        for c, rx in _TITULOS_COMP:
            if rx.search(t):
                cat = c
                break
    return cat or "general"


def tarea_activa():
    """Info de la ventana en foco: dict o None."""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = _nombre_proceso(pid.value)
        stem = _stem(exe) if exe else ""
        n = _user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(max(n, 1) + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        titulo = buf.value
        if not stem and not titulo:
            return None
        cat = clasificar(stem, titulo)
        app = NOMBRE_BONITO.get(stem) or (stem.title() if stem else "?")
        return {"proceso": stem, "app": app, "titulo": titulo[:90],
                "categoria": cat, "etiqueta": ETIQUETA[cat]}
    except Exception:
        return None


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def usuario_activo(max_idle_seg=300):
    """False si el escritorio está bloqueado o no hay input hace max_idle_seg.
    Ante la duda devuelve True: nunca frenar el registro por un error de acá."""
    try:
        h = _user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not h:
            return False  # escritorio bloqueado
        _user32.CloseDesktop(h)
    except Exception:
        pass
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if _user32.GetLastInputInfo(ctypes.byref(lii)):
            idle_ms = (_kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
            return idle_ms < max_idle_seg * 1000
    except Exception:
        pass
    return True


if __name__ == "__main__":
    t = tarea_activa()
    if t:
        print(f"{t['etiqueta']} · {t['app']} · {t['titulo']}")
    else:
        print("sin ventana activa")
