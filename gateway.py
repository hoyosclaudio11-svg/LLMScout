# -*- coding: utf-8 -*-
"""Adopción real: cruza las impresiones de LLM Scout con los pedidos que
ModelMatch Desktop registra en su SQLite (datos/modelmatch.db).

Si se sugirió un modelo y dentro de la ventana de crédito hay un pedido
resuelto (status 200) a ese modelo o su familia -> adopción verificada.
El botón "✓ Usé este" queda como fallback manual.
"""

import datetime as dt
import sqlite3
from pathlib import Path

import benchmarks

VENTANA_MIN = 60  # minutos entre sugerencia y pedido para contar adopción


def _abrir(mm_db):
    """Conexión de lectura a la DB de ModelMatch, o None si no está."""
    p = Path(mm_db)
    if not p.exists():
        return None
    try:
        return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        try:
            return sqlite3.connect(str(p), timeout=5)
        except sqlite3.Error:
            return None


def _parse_ts(s):
    """El ts de ModelMatch es texto local 'YYYY-MM-DD HH:MM:SS'."""
    try:
        return dt.datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    except (ValueError, TypeError):
        return 0.0


def _coincide(modelo_sugerido, modelo_pedido):
    a, b = benchmarks._norm(modelo_sugerido), benchmarks._norm(modelo_pedido)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return bool(benchmarks._familia(modelo_sugerido)
                & benchmarks._familia(modelo_pedido))


def inicial(db, mm_db):
    """Primera corrida: el watermark arranca en el último request histórico,
    para no creditar pedidos previos a instalar el cruce."""
    if db.meta_get("gateway_wm") is not None:
        return True
    con = _abrir(mm_db)
    if con is None:
        return False
    try:
        mx = con.execute("SELECT COALESCE(MAX(id), 0) FROM requests").fetchone()[0]
        db.meta_set("gateway_wm", str(mx))
        return True
    except sqlite3.Error:
        return False
    finally:
        con.close()


def chequear(db, mm_db):
    """Procesa pedidos nuevos desde el watermark. -> n adopciones nuevas,
    o None si el gateway no está disponible."""
    con = _abrir(mm_db)
    if con is None:
        return None
    try:
        wm_raw = db.meta_get("gateway_wm")
        if wm_raw is None:
            return 0  # sin inicializar (inicial() falló): no procesar histórico
        wm = int(wm_raw)
        filas = con.execute(
            "SELECT id, ts, modelo_usado, modelo_pedido FROM requests "
            "WHERE id > ? AND status = 200 ORDER BY id", (wm,)).fetchall()
        if not filas:
            return 0
        impresiones = db.impresiones_recientes()
        creditados = 0
        nuevo_wm = wm
        for rid, ts, usado, pedido in filas:
            nuevo_wm = max(nuevo_wm, rid)
            nombre = usado or pedido
            t_ped = _parse_ts(ts)
            if not nombre or not t_ped:
                continue
            for iid, cat, modelo, t_imp in impresiones:  # vienen desc por ts
                if t_imp > t_ped:
                    continue
                if t_ped - t_imp > VENTANA_MIN * 60:
                    break  # más viejas que la ventana: no seguir
                if _coincide(modelo, nombre):
                    if db.creditar(rid, t_ped, cat, modelo, iid):
                        creditados += 1
                    break
        db.meta_set("gateway_wm", str(nuevo_wm))
        return creditados
    except (sqlite3.Error, ValueError):
        return None
    finally:
        con.close()
