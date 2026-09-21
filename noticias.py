# -*- coding: utf-8 -*-
"""Noticias de IA del día para LLM Scout — RSS/Atom, stdlib puro.

cargar() -> (items, estado)
    items  : [{"titulo", "fuente", "link", "ts"}] ordenados por fecha
    estado : "ok" | "cache" (falló la red, sirvió cache) | "vacio"

Cache en data/noticias.json con TTL de 30 minutos.
"""

import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

AQUI = Path(__file__).parent
CACHE = AQUI / "data" / "noticias.json"
TTL = 30 * 60          # segundos
MAX_ITEMS = 12         # los que se guardan
POR_FUENTE = 3         # tope por fuente en la lista final (diversidad)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
RUIDO = re.compile(r"disrupt|sponsored|patrocinado", re.I)

FUENTES = [
    ("Google News", "https://news.google.com/rss/search?q=inteligencia+artificial+when:2d&hl=es-419&gl=AR&ceid=AR:es-419", "es"),
    ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/", "en"),
    ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "en"),
]


def _nodo(item, *nombres):
    """Primer hijo cuyo nombre local (sin namespace) esté en `nombres`."""
    for hijo in item.iter():
        if hijo is item:
            continue
        if hijo.tag.rsplit("}", 1)[-1] in nombres:
            return hijo
    return None


def _limpiar(titulo, nombre_fuente):
    """Google News mete ' - Fuente' al final del título: lo sacamos.
    El feed de The Verge trae U+FFFD donde iba un apóstrofe."""
    t = re.sub(r"\s+", " ", titulo or "").replace("�", "'").strip()
    if nombre_fuente == "Google News" and " - " in t:
        t = t.rsplit(" - ", 1)[0]
    return t


def _ts(item):
    """epoch del item; 0 si no hay fecha legible."""
    nodo = _nodo(item, "pubDate", "date", "published", "updated")
    if nodo is None or not (nodo.text or "").strip():
        return 0
    bruto = nodo.text.strip()
    try:
        if bruto[4] == " " and bruto[3] == ",":  # estilo RSS: 'Mon, 21 Sep ...'
            return parsedate_to_datetime(bruto).timestamp()
        return datetime.fromisoformat(bruto.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def _parsear(nombre, url, bytes_xml):
    """Devuelve items de un feed RSS 2.0 o Atom."""
    items = []
    raiz = ET.fromstring(bytes_xml)
    for it in raiz.iter():
        tag = it.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        t_node = _nodo(it, "title")
        titulo = t_node.text if t_node is not None else ""
        if tag == "item":  # RSS
            l_node = _nodo(it, "link")
            link = (l_node.text or l_node.get("href") or "") if l_node is not None else ""
        else:  # Atom: el href vive en el atributo
            link = ""
            for l in it:
                if l.tag.rsplit("}", 1)[-1] == "link":
                    link = (l.get("href") or "").strip()
                    if link:
                        break
        titulo = _limpiar(titulo, nombre)
        if titulo and link:
            items.append({"titulo": titulo[:220], "fuente": nombre,
                          "link": link.strip(), "ts": _ts(it)})
    return items


def _descargar(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def _ordenar(items):
    """Por fecha descendente, con tope por fuente para que una sola
    no se coma la lista. Afuera el ruido promocional."""
    items.sort(key=lambda x: x["ts"], reverse=True)
    por_fuente, salida = {}, []
    for it in items:
        if RUIDO.search(it["titulo"]):
            continue
        n = por_fuente.get(it["fuente"], 0)
        if n < POR_FUENTE:
            por_fuente[it["fuente"]] = n + 1
            salida.append(it)
    return salida


def cargar(forzar=False):
    """Trae noticias (red) o sirve el cache. Nunca lanza excepciones."""
    cache = {}
    try:
        cache = json.loads(CACHE.read_text("utf-8"))
    except Exception:
        pass

    fresco = cache.get("ts", 0) > time.time() - TTL
    if fresco and not forzar:
        return cache.get("items", []), "ok"

    todos = []
    ok = False
    for nombre, url, _idioma in FUENTES:
        try:
            todos.extend(_parsear(nombre, url, _descargar(url)))
            ok = True
        except Exception:
            continue

    if ok and todos:
        items = _ordenar(todos)[:MAX_ITEMS]
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(
                {"ts": time.time(), "items": items}), "utf-8")
        except Exception:
            pass
        return items, "ok"

    if cache.get("items"):
        return cache["items"], "cache"
    return [], "vacio"


def hace(ts):
    """'hace 5 min' / 'hace 2 h' / 'ayer' para mostrar al pie del título."""
    if not ts:
        return ""
    d = time.time() - ts
    if d < 0:
        d = 0
    if d < 3600:
        return f"hace {max(1, int(d // 60))} min"
    if d < 86400:
        return f"hace {int(d // 3600)} h"
    dias = int(d // 86400)
    return "ayer" if dias == 1 else f"hace {dias} días"
