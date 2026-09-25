"""Almacenamiento acumulado en SQLite."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS convocatorias (
    id_bdns          TEXT PRIMARY KEY,          -- código BDNS (o hash para no-BDNS)
    fuente           TEXT NOT NULL,             -- bdns | boe | rss | perplexity
    titulo           TEXT NOT NULL,
    organo           TEXT,                      -- nivel2 / nivel3 concatenado
    ambito           TEXT,                      -- Estado | CCAA | Local | Otros
    ccaa             TEXT,                      -- comunidad autónoma detectada
    fecha_publicacion TEXT,                     -- ISO
    fecha_inicio     TEXT,                      -- ISO o NULL
    fecha_fin        TEXT,                      -- ISO o NULL
    texto_inicio     TEXT,
    texto_fin        TEXT,
    abierto          INTEGER,                   -- 1/0/NULL según BDNS
    presupuesto      REAL,
    beneficiarios    TEXT,                      -- JSON lista
    instrumentos     TEXT,
    finalidad        TEXT,
    regiones         TEXT,                      -- JSON lista
    mrr              INTEGER,
    url_ficha        TEXT,
    url_bases        TEXT,
    url_sede         TEXT,
    categorias       TEXT,                      -- JSON lista de claves
    clientes         TEXT,                      -- JSON lista de claves
    resumen_json     TEXT,                      -- resumen ejecutivo (JSON) o NULL
    resumen_proveedor TEXT,
    texto_pdf_chars  INTEGER,
    detalle_json     TEXT,                      -- detalle bruto de la BDNS
    creado           TEXT NOT NULL,
    actualizado      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS noticias (
    id               TEXT PRIMARY KEY,          -- url normalizada
    fuente           TEXT NOT NULL,
    titulo           TEXT NOT NULL,
    url              TEXT NOT NULL,
    fecha            TEXT,
    resumen          TEXT,
    ambito           TEXT,
    categorias       TEXT,
    creado           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS licitaciones (
    id               TEXT PRIMARY KEY,          -- atom id PLACSP
    fuente           TEXT,
    titulo           TEXT NOT NULL,
    expediente       TEXT,
    organo           TEXT,
    organo_padre     TEXT,
    estado           TEXT,
    estado_txt       TEXT,
    tipo             TEXT,
    procedimiento    TEXT,
    cpv              TEXT,                      -- JSON lista
    presupuesto_sin_iva REAL,
    presupuesto_con_iva REAL,
    valor_estimado   REAL,
    fecha_limite     TEXT,
    hora_limite      TEXT,
    lugar            TEXT,
    nuts             TEXT,
    ccaa             TEXT,
    municipio        TEXT,
    duracion         TEXT,
    fondos_ue        TEXT,
    n_lotes          INTEGER,
    clasificacion    TEXT,                      -- JSON: ¿exige clasificación del contratista? cuál
    clasificacion_txt TEXT,                     -- JSON lista: lo que dijera el anuncio en crudo
    url              TEXT,
    documentos       TEXT,                      -- JSON lista
    fecha_publicacion TEXT,
    actualizado      TEXT,
    categorias       TEXT,
    clientes         TEXT,
    creado           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ejecuciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio TEXT, fin TEXT, ok INTEGER,
    nuevas_convocatorias INTEGER, nuevas_noticias INTEGER, resumenes INTEGER, errores TEXT
);
"""


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DB:
    def __init__(self, ruta: Path):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(ruta)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA)
        self._migrar()

    def _migrar(self) -> None:
        """Añade a bases antiguas las columnas que se hayan ido incorporando."""
        faltantes = {
            "ejecuciones": [("nuevas_licitaciones", "INTEGER DEFAULT 0")],
            "licitaciones": [("clasificacion", "TEXT"), ("clasificacion_txt", "TEXT")],
        }
        for tabla, columnas in faltantes.items():
            existentes = [r[1] for r in self.con.execute(f"PRAGMA table_info({tabla})")]
            for nombre, tipo in columnas:
                if nombre not in existentes:
                    self.con.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")
        self.con.commit()

    # ---------------------------------------------------------- convocatorias
    def existe_convocatoria(self, id_bdns: str) -> bool:
        return self.con.execute("SELECT 1 FROM convocatorias WHERE id_bdns=?", (id_bdns,)).fetchone() is not None

    def esta_vacia(self) -> bool:
        return self.con.execute("SELECT COUNT(*) FROM convocatorias").fetchone()[0] == 0

    def guardar_convocatoria(self, c: dict) -> bool:
        """Inserta o actualiza. Devuelve True si era nueva."""
        nueva = not self.existe_convocatoria(c["id_bdns"])
        campos = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in c.items()}
        campos["actualizado"] = _ahora()
        if nueva:
            campos["creado"] = _ahora()
            cols = ", ".join(campos)
            self.con.execute(f"INSERT INTO convocatorias ({cols}) VALUES ({', '.join('?' for _ in campos)})",
                             list(campos.values()))
        else:
            campos.pop("creado", None)
            # no pisar un resumen ya generado con NULL
            if campos.get("resumen_json") is None:
                campos.pop("resumen_json", None)
                campos.pop("resumen_proveedor", None)
            sets = ", ".join(f"{k}=?" for k in campos if k != "id_bdns")
            self.con.execute(f"UPDATE convocatorias SET {sets} WHERE id_bdns=?",
                             [v for k, v in campos.items() if k != "id_bdns"] + [c["id_bdns"]])
        self.con.commit()
        return nueva

    def guardar_resumen(self, id_bdns: str, resumen: dict, proveedor: str, chars_pdf: int | None) -> None:
        self.con.execute(
            "UPDATE convocatorias SET resumen_json=?, resumen_proveedor=?, texto_pdf_chars=?, actualizado=? WHERE id_bdns=?",
            (json.dumps(resumen, ensure_ascii=False), proveedor, chars_pdf, _ahora(), id_bdns))
        self.con.commit()

    def convocatorias_sin_resumen(self, limite: int, rehacer_basicos: bool = True) -> list[sqlite3.Row]:
        """Pendientes de resumen. Con rehacer_basicos, también las que solo tienen el resumen sin LLM
        (proveedor 'basico'), para que mejoren en cuanto haya clave de Gemini. Primero las abiertas."""
        cond = "resumen_json IS NULL" + (" OR resumen_proveedor='basico'" if rehacer_basicos else "")
        return self.con.execute(
            f"SELECT * FROM convocatorias WHERE {cond} "
            "ORDER BY (fecha_fin IS NOT NULL AND fecha_fin >= date('now')) DESC, fecha_publicacion DESC LIMIT ?",
            (limite,)).fetchall()

    def todas_convocatorias(self) -> list[dict]:
        filas = self.con.execute("SELECT * FROM convocatorias ORDER BY fecha_publicacion DESC").fetchall()
        return [self._fila(f) for f in filas]

    # -------------------------------------------------------------- noticias
    def guardar_noticia(self, n: dict) -> bool:
        if self.con.execute("SELECT 1 FROM noticias WHERE id=?", (n["id"],)).fetchone():
            return False
        n = dict(n)
        n["categorias"] = json.dumps(n.get("categorias", []), ensure_ascii=False)
        n["creado"] = _ahora()
        cols = ", ".join(n)
        self.con.execute(f"INSERT INTO noticias ({cols}) VALUES ({', '.join('?' for _ in n)})", list(n.values()))
        self.con.commit()
        return True

    def todas_noticias(self, limite: int = 400) -> list[dict]:
        filas = self.con.execute("SELECT * FROM noticias ORDER BY COALESCE(fecha, creado) DESC LIMIT ?",
                                 (limite,)).fetchall()
        return [self._fila(f) for f in filas]

    # ----------------------------------------------------------- licitaciones
    def guardar_licitacion(self, l: dict) -> bool:
        """Inserta o actualiza (estado/plazo pueden cambiar). Devuelve True si era nueva."""
        nueva = self.con.execute("SELECT 1 FROM licitaciones WHERE id=?", (l["id"],)).fetchone() is None
        campos = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in l.items()}
        if nueva:
            campos["creado"] = _ahora()
            cols = ", ".join(campos)
            self.con.execute(f"INSERT INTO licitaciones ({cols}) VALUES ({', '.join('?' for _ in campos)})", list(campos.values()))
        else:
            sets = ", ".join(f"{k}=?" for k in campos if k != "id")
            self.con.execute(f"UPDATE licitaciones SET {sets} WHERE id=?", [v for k, v in campos.items() if k != "id"] + [l["id"]])
        self.con.commit()
        return nueva

    def todas_licitaciones(self) -> list[dict]:
        filas = self.con.execute("SELECT * FROM licitaciones ORDER BY fecha_publicacion DESC").fetchall()
        return [self._fila(f) for f in filas]

    # ----------------------------------------------------------- ejecuciones
    def registrar_ejecucion(self, inicio: str, ok: bool, nuevas_c: int, nuevas_n: int, resumenes: int,
                            errores: list[str], nuevas_l: int = 0) -> None:
        self.con.execute(
            "INSERT INTO ejecuciones (inicio, fin, ok, nuevas_convocatorias, nuevas_noticias, resumenes, errores, nuevas_licitaciones) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (inicio, _ahora(), int(ok), nuevas_c, nuevas_n, resumenes, json.dumps(errores, ensure_ascii=False), nuevas_l))
        self.con.commit()

    def ultimas_ejecuciones(self, n: int = 10) -> list[dict]:
        return [self._fila(f) for f in self.con.execute(
            "SELECT * FROM ejecuciones ORDER BY id DESC LIMIT ?", (n,)).fetchall()]

    @staticmethod
    def _fila(f: sqlite3.Row) -> dict:
        d = dict(f)
        for k in ("beneficiarios", "regiones", "categorias", "clientes", "resumen_json", "errores", "cpv",
                  "documentos", "clasificacion", "clasificacion_txt"):
            if k in d and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    pass
        d.pop("detalle_json", None)
        return d
