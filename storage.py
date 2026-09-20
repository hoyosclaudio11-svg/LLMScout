# -*- coding: utf-8 -*-
"""Registro de impresiones y adopciones en SQLite: la métrica del MVP
es la tasa de adopción (usos / sugerencias mostradas)."""

import datetime as dt
import sqlite3
import threading
import time

_CREAR = """
CREATE TABLE IF NOT EXISTS impresiones(
    id INTEGER PRIMARY KEY,
    ts REAL, fecha TEXT, categoria TEXT, modelo TEXT, posicion INTEGER);
CREATE TABLE IF NOT EXISTS usos(
    id INTEGER PRIMARY KEY,
    ts REAL, fecha TEXT, categoria TEXT, modelo TEXT, posicion INTEGER);
CREATE TABLE IF NOT EXISTS usos_reales(
    id INTEGER PRIMARY KEY,
    ts REAL, fecha TEXT, categoria TEXT, modelo TEXT,
    impresion_id INTEGER, request_id INTEGER UNIQUE);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS ix_imp ON impresiones(categoria, modelo, ts);
CREATE INDEX IF NOT EXISTS ix_uso ON usos(modelo, ts);
"""

# no volver a contar la misma sugerencia para el mismo modelo antes de 10 min
_DEDUPE_SEG = 600


def _hoy():
    return dt.date.today().isoformat()


class DB:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.Lock()
        with self.lock:
            con = sqlite3.connect(self.path)
            try:
                con.executescript(_CREAR)
                con.commit()
            finally:
                con.close()

    def _ejecutar(self, sql, params=(), fetch=False):
        with self.lock:
            con = sqlite3.connect(self.path)
            try:
                cur = con.execute(sql, params)
                filas = cur.fetchall() if fetch else None
                con.commit()
                return filas
            finally:
                con.close()

    def impresiones(self, categoria, sugeridos):
        """sugeridos: [(modelo_id, posicion)] con dedupe de 10 min."""
        ahora = time.time()
        for mid, pos in sugeridos:
            ult = self._ejecutar(
                "SELECT ts FROM impresiones WHERE categoria=? AND modelo=? "
                "ORDER BY ts DESC LIMIT 1", (categoria, mid), fetch=True)
            if ult and ahora - ult[0][0] < _DEDUPE_SEG:
                continue
            self._ejecutar(
                "INSERT INTO impresiones(ts, fecha, categoria, modelo, posicion) "
                "VALUES(?,?,?,?,?)", (ahora, _hoy(), categoria, mid, pos))

    def uso(self, categoria, modelo, posicion):
        self._ejecutar(
            "INSERT INTO usos(ts, fecha, categoria, modelo, posicion) "
            "VALUES(?,?,?,?,?)", (time.time(), _hoy(), categoria, modelo, posicion))

    # ---- adopciones reales (cruzadas con los pedidos de ModelMatch) ----

    def meta_get(self, k):
        f = self._ejecutar("SELECT v FROM meta WHERE k=?", (k,), fetch=True)
        return f[0][0] if f else None

    def meta_set(self, k, v):
        self._ejecutar("INSERT INTO meta(k, v) VALUES(?,?) "
                       "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    def impresiones_recientes(self, limite=500):
        """[(id, categoria, modelo, ts)] más nuevas primero."""
        return self._ejecutar(
            "SELECT id, categoria, modelo, ts FROM impresiones "
            "ORDER BY ts DESC LIMIT ?", (limite,), fetch=True)

    def creditar(self, request_id, ts, categoria, modelo, impresion_id):
        """Credita una adopción real (idempotente por request_id). -> bool."""
        cur = None
        with self.lock:
            con = sqlite3.connect(self.path)
            try:
                cur = con.execute(
                    "INSERT OR IGNORE INTO usos_reales"
                    "(ts, fecha, categoria, modelo, impresion_id, request_id) "
                    "VALUES(?,?,?,?,?,?)",
                    (ts, _hoy(), categoria, modelo, impresion_id, request_id))
                con.commit()
            finally:
                con.close()
        return bool(cur and cur.rowcount)

    def tasa(self):
        """dict con reales/manuales/impresiones de hoy y totales."""
        h = _hoy()
        def uno(sql, p=()):
            return self._ejecutar(sql, p, fetch=True)[0][0]
        return {
            "reales_hoy": uno("SELECT COUNT(*) FROM usos_reales WHERE fecha=?", (h,)),
            "manuales_hoy": uno("SELECT COUNT(*) FROM usos WHERE fecha=?", (h,)),
            "imp_hoy": uno("SELECT COUNT(*) FROM impresiones WHERE fecha=?", (h,)),
            "reales_tot": uno("SELECT COUNT(*) FROM usos_reales"),
            "manuales_tot": uno("SELECT COUNT(*) FROM usos"),
            "imp_tot": uno("SELECT COUNT(*) FROM impresiones"),
        }

    def usos_por_modelo(self, dias=30):
        """{modelo: usos_tuyos} (reales + manuales) del período."""
        desde = (dt.date.today() - dt.timedelta(days=dias)).isoformat()
        out = {}
        for m, n in self._ejecutar(
                "SELECT modelo, COUNT(*) FROM usos_reales WHERE fecha>=? GROUP BY modelo",
                (desde,), fetch=True):
            out[m] = out.get(m, 0) + n
        for m, n in self._ejecutar(
                "SELECT modelo, COUNT(*) FROM usos WHERE fecha>=? GROUP BY modelo",
                (desde,), fetch=True):
            out[m] = out.get(m, 0) + n
        return out

    def resumen(self, dias=30):
        """[(modelo, reales, manuales, impresiones)] del período, por uso desc."""
        desde = (dt.date.today() - dt.timedelta(days=dias)).isoformat()
        imp = dict(self._ejecutar(
            "SELECT modelo, COUNT(*) FROM impresiones WHERE fecha>=? GROUP BY modelo",
            (desde,), fetch=True))
        reales = dict(self._ejecutar(
            "SELECT modelo, COUNT(*) FROM usos_reales WHERE fecha>=? GROUP BY modelo",
            (desde,), fetch=True))
        manuales = dict(self._ejecutar(
            "SELECT modelo, COUNT(*) FROM usos WHERE fecha>=? GROUP BY modelo",
            (desde,), fetch=True))
        filas = [(m, reales.get(m, 0), manuales.get(m, 0), imp.get(m, 0))
                 for m in set(imp) | set(reales) | set(manuales)]
        filas.sort(key=lambda f: (-(f[1] + f[2]), -f[3]))
        return filas
