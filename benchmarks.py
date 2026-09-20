# -*- coding: utf-8 -*-
"""Benchmarks + recomendación.

Orden de fuentes (de mejor a peor, todo con gracia si falla):
  1. Artificial Analysis (si existe la env var ARTIFICIAL_ANALYSIS_API_KEY) -> cache 24 h
  2. Cache de esa consulta viva (hasta 24 h de antigüedad)
  3. Snapshot local data/benchmarks.json (siempre disponible)
Además consulta los modelos que ofrece FreeLLMAPI local (puerto 3001) para
marcar cuáles recomendaciones se pueden usar ya mismo.
"""

import datetime as dt
import json
import math
import os
import re
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).parent
DATA = AQUI / "data"
SNAPSHOT = DATA / "benchmarks.json"
CACHE = DATA / "cache_benchmarks.json"
CACHE_PRECIOS = DATA / "cache_precios.json"
TTL_SEG = 24 * 3600
URL_AA = "https://artificialanalysis.ai/api/v2/data/llms/models"
URL_OPENROUTER = "https://openrouter.ai/api/v1/models"
BASE_LOCAL = "http://127.0.0.1:3001/v1/models"
CFG_LOCAL = Path(r"C:\Users\chito\FreeLLMAPI\freeapi_config.json")

# peso de cada dimensión según la tarea detectada (suman 1)
# la dimensión principal manda; el precio es desempate, no criterio
PESOS = {
    "coding":   {"coding": .55, "reasoning": .20, "speed": .10, "long_context": .05, "writing": .05, "price": .05},
    "writing":  {"writing": .75, "reasoning": .05, "long_context": .10, "speed": .05, "price": .05},
    "data":     {"reasoning": .55, "coding": .20, "long_context": .10, "speed": .10, "price": .05},
    "research": {"long_context": .35, "reasoning": .35, "writing": .20, "price": .10},
    "media":    {"vision": .40, "writing": .30, "speed": .20, "price": .10},
    "chat":     {"writing": .40, "reasoning": .30, "speed": .20, "price": .10},
    "general":  {"reasoning": .30, "writing": .25, "coding": .15, "speed": .15, "price": .15},
}

MOTIVOS = {
    "coding": "líder en código (SWE-bench)",
    "writing": "mejor escritura natural",
    "reasoning": "más razonamiento (GPQA/MATH)",
    "long_context": "mejor con documentos largos",
    "vision": "mejor con imágenes",
    "speed": "respuestas muy rápidas",
    "price": "gran relación precio/calidad",
}

_STOP = {"the", "api", "chat", "free", "latest", "instruct", "com", "v1"}


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _familia(s):
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) >= 3 and t not in _STOP}


def match_ids(nombre, ids):
    """Primer id de la lista que coincida con el nombre (norm exacto/substring
    o familia compartida), o None. Sirve para gateways y para precios."""
    n = _norm(nombre)
    fam = _familia(nombre)
    for lid in ids:
        l = _norm(lid)
        if not l:
            continue
        if l == n or l in n or n in l:
            return lid
        if _familia(lid) & fam:
            return lid
    return None


# chat web de cada familia, para el botón "Abrir"
WEB_URLS = [
    ("claude", "https://claude.ai/new"),
    ("gpt", "https://chatgpt.com/"),
    ("gemini", "https://gemini.google.com/app"),
    ("grok", "https://grok.com/"),
    ("glm", "https://chat.z.ai/"),
    ("kimi", "https://www.kimi.com/"),
    ("deepseek", "https://chat.deepseek.com/"),
    ("qwen", "https://chat.qwen.ai/"),
    ("mistral", "https://chat.mistral.ai/"),
    ("devstral", "https://chat.mistral.ai/"),
    ("llama", "https://www.meta.ai/"),
    ("granite", "https://www.ibm.com/products/watsonx-ai"),
]


def url_web(nombre):
    fam = _familia(nombre)
    for k, u in WEB_URLS:
        if k in fam:
            return u
    return ""


# ---------------------------------------------------------------- snapshot ---

def _snapshot():
    obj = json.loads(SNAPSHOT.read_text("utf-8"))
    return obj["models"], obj.get("source", "snapshot local")


# ------------------------------------------------------- datos vivos (opt) ---

def _intentar_vivos():
    """Artificial Analysis si hay key en el entorno. None si no se puede."""
    key = os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY", "").strip()
    if not key:
        return None
    try:
        req = urllib.request.Request(
            URL_AA, headers={"x-api-key": key, "User-Agent": "LLMScout/0.1"})
        with urllib.request.urlopen(req, timeout=8) as r:
            datos = json.loads(r.read().decode("utf-8"))
        filas = datos if isinstance(datos, list) else datos.get("data", [])
        modelos = []
        for f in filas:
            nombre = f.get("model_name") or f.get("name")
            if not nombre:
                continue
            q = f.get("intelligence_index") or f.get("artificial_analysis_intelligence_index") or 0
            vel = f.get("median_output_tokens_per_second") or f.get("median_output_tokens_per_s") or 0
            precio = f.get("price_usd_per_mtok_blended_3_to_1") or f.get("price_usd_per_mtok") or 0
            modelos.append({"id": _norm(nombre), "name": nombre,
                            "provider": (f.get("model_maker") or {}).get("name", "") if isinstance(f.get("model_maker"), dict) else str(f.get("model_maker", "")),
                            "scores": {}, "_q": float(q or 0), "_vel": float(vel or 0), "_precio": float(precio or 0)})
        if len(modelos) < 5:
            return None
        qs = [m["_q"] for m in modelos]
        vmin, vmax = min(qs), max(qs)
        rango = (vmax - vmin) or 1
        for m in modelos:
            base = round(40 + 60 * (m["_q"] - vmin) / rango)
            m["scores"] = {"coding": base, "writing": base, "reasoning": base,
                           "long_context": base, "vision": base,
                           "speed": min(100, max(20, round(m["_vel"] / 5))),
                           "price": min(100, max(5, round(100 - m["_precio"] * 20)))}
            for k in ("_q", "_vel", "_precio"):
                m.pop(k)
        return modelos, "Artificial Analysis (en vivo, aprox.)"
    except Exception:
        return None


def _leer_cache():
    try:
        obj = json.loads(CACHE.read_text("utf-8"))
        if time.time() - obj["ts"] < TTL_SEG:
            return obj["models"], obj["fuente"]
    except Exception:
        pass
    return None


def _guardar_cache(modelos, fuente):
    try:
        CACHE.write_text(json.dumps({"ts": time.time(), "models": modelos,
                                     "fuente": fuente}, ensure_ascii=False), "utf-8")
    except Exception:
        pass


# ----------------------------------------------------- modelos locales (3001)

def _clave_local():
    k = os.environ.get("FREELLMAPI_KEY", "").strip()
    if k:
        return k
    try:
        obj = json.loads(CFG_LOCAL.read_text("utf-8-sig"))
    except Exception:
        return ""
    halladas = []

    def _recorrer(o):
        if isinstance(o, dict):
            for kk, vv in o.items():
                if isinstance(vv, str) and len(vv) >= 16 and any(
                        t in kk.lower() for t in ("key", "token", "secret")):
                    halladas.append(vv)
                else:
                    _recorrer(vv)
        elif isinstance(o, list):
            for v in o:
                _recorrer(v)

    _recorrer(obj)
    return halladas[0] if halladas else ""


def models_locales(timeout=2.5):
    """Lista de ids de modelos que ofrece FreeLLMAPI local, o [] si no hay."""
    claves = [""]
    k = _clave_local()
    if k:
        claves.append(k)
    for k in claves:
        try:
            headers = {"User-Agent": "LLMScout/0.1"}
            if k:
                headers["Authorization"] = "Bearer " + k
            req = urllib.request.Request(BASE_LOCAL, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                obj = json.loads(r.read().decode("utf-8"))
            items = obj.get("data", obj if isinstance(obj, list) else [])
            ids = []
            for it in items:
                mid = it.get("id", "") if isinstance(it, dict) else str(it)
                if mid:
                    ids.append(mid)
            if ids:
                return ids
        except Exception:
            continue
    return []


def es_local(nombre, locales):
    """Match por familia: 'GLM-5.3' cuenta como local si 3001 ofrece glm-5.3-flash."""
    return match_ids(nombre, locales) is not None


# --------------------------------------------------- precios vivos (OpenRouter)

def _score_precio(precio_blended):
    """USD/M tok mezcla 3:1 -> score 0-100 (barato = alto). Escala log."""
    if precio_blended <= 0:
        return 99
    return min(99, max(2, round(65 - 9 * math.log(precio_blended))))


def _score_contexto(ctx):
    """context_length -> score 0-100. 8k≈45, 128k≈64, 1M≈79, 10M≈93."""
    if not ctx or ctx <= 0:
        return None
    return min(97, max(30, round(45 + (math.log10(ctx) - 3.9) * 16)))


def refrescar_precios():
    """Baja precios y contexto de OpenRouter (público, sin key) y cachea 24 h."""
    try:
        req = urllib.request.Request(URL_OPENROUTER,
                                     headers={"User-Agent": "LLMScout/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            datos = json.loads(r.read().decode("utf-8"))
        filas = datos.get("data", [])
        if len(filas) < 10:
            return False
        precios = {}
        for f in filas:
            mid = f.get("id") or ""
            if not mid:
                continue
            pr = f.get("pricing") or {}
            try:
                p_in = float(pr.get("prompt") or 0)
                p_out = float(pr.get("completion") or 0)
            except (TypeError, ValueError):
                p_in = p_out = 0.0
            blended = (p_in * 3 + p_out) / 4 * 1e6
            precios[mid] = {"price": _score_precio(blended),
                            "long_context": _score_contexto(f.get("context_length") or 0)}
        DATA.mkdir(parents=True, exist_ok=True)
        CACHE_PRECIOS.write_text(json.dumps({"ts": time.time(), "precios": precios}),
                                 "utf-8")
        return True
    except Exception:
        return False


def _aplicar_precios(modelos):
    """Refresca price y long_context del snapshot con lo cacheado de OpenRouter.
    Devuelve (modelos, n_coincidencias)."""
    try:
        obj = json.loads(CACHE_PRECIOS.read_text("utf-8"))
        if time.time() - obj["ts"] > TTL_SEG:
            return modelos, 0
        precios = obj["precios"]
        hits = 0
        for m in modelos:
            hit = match_ids(m["name"], precios.keys())
            if not hit:
                continue
            hits += 1
            m["scores"]["price"] = precios[hit]["price"]
            lc = precios[hit]["long_context"]
            if lc is not None:
                m["scores"]["long_context"] = lc
        return modelos, hits
    except Exception:
        return modelos, 0


# ------------------------------------------------------------- recomendación -

def cargar(filtro_local_ids=None):
    """(modelos, fuente). filtro_local_ids limita a los de FreeLLMAPI."""
    modelos = None
    fuente = ""
    en_cache = _leer_cache()
    if en_cache:
        modelos, fuente = en_cache
    if modelos is None:
        vivos = _intentar_vivos()
        if vivos:
            modelos, fuente = vivos
            _guardar_cache(modelos, fuente)
    if modelos is None:
        modelos, fuente = _snapshot()
    modelos, hits = _aplicar_precios(modelos)
    if hits:
        fuente += f" · precios OpenRouter ({hits} modelos)"
    if filtro_local_ids:
        acotados = [m for m in modelos if es_local(m["name"], filtro_local_ids)]
        if acotados:
            modelos = acotados
            fuente += " · filtro FreeLLMAPI"
    return modelos, fuente


def recomendar(categoria, modelos, k=3):
    """Top k para una categoría: [(indice, motivo, modelo)] ordenado."""
    if not modelos:
        return []
    pesos = PESOS.get(categoria, PESOS["general"])
    medias = {d: sum(m["scores"].get(d, 50) for m in modelos) / len(modelos)
              for d in pesos}
    out = []
    for m in modelos:
        sc = m["scores"]
        indice = sum(sc.get(d, 50) * p for d, p in pesos.items())
        dim, mejor = None, -1e9
        for d, p in pesos.items():
            if p < .10:
                continue
            ventaja = (sc.get(d, 50) - medias[d]) * p
            if ventaja > mejor:
                dim, mejor = d, ventaja
        out.append((round(indice, 1), MOTIVOS.get(dim, "buena opción general"), m))
    out.sort(key=lambda t: -t[0])
    return out[:k]


if __name__ == "__main__":
    ms, f = cargar()
    print(f"fuente: {f} · {len(ms)} modelos")
    for cat in ("coding", "writing", "data"):
        print(f"\n— {cat} —")
        for ind, mot, m in recomendar(cat, ms):
            print(f"  {m['name']:24} índice {ind:5.1f} · {mot}")
