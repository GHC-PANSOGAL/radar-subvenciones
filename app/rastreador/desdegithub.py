"""Traerse la base de datos que rastrea GitHub Actions.

Desde que el rastreo lo hace GitHub todos los días a las 06:30 UTC (encienda alguien el PC o no), la
base buena ya no es la de OneDrive: es la de la rama ``datos`` del repositorio. Sin esto, el panel que
abre el acceso directo del escritorio se va quedando viejo aunque los avisos lleguen puntuales, que es
la peor combinación posible: todo parece funcionar y los datos son de hace una semana.

Lo que hace: descargar ``subvenciones.sqlite.gz`` de la rama ``datos`` y, **solo si trae más registros
que la que hay**, dejarla en la carpeta compartida. Esa comprobación no es paranoia: si un día el
workflow falla a medias y sube una base a medio hacer, sobrescribirla encima de la buena destruiría el
histórico de todos a la vez.

No hace falta token: el repositorio es público. Si no hay internet o GitHub no responde, se sigue con
lo que haya en local — esto nunca debe impedir que el programa arranque.
"""
from __future__ import annotations

import gzip
import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path

from .util import UA, http_get

log = logging.getLogger("rastreador.desdegithub")

PLANTILLA = "https://raw.githubusercontent.com/{repo}/{rama}/subvenciones.sqlite.gz"
RAMA = "datos"


def _contar(db: Path) -> tuple[int, int]:
    """(convocatorias, licitaciones). (-1, -1) si no se puede abrir o no es una base válida."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        n_c = con.execute("SELECT COUNT(*) FROM convocatorias").fetchone()[0]
        n_l = con.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]
        con.close()
        return n_c, n_l
    except sqlite3.Error:
        return -1, -1


def _salvar_suscripciones(actual: Path, nueva: Path) -> int:
    """Copia a `nueva` las suscripciones que estén en `actual` y no en ella. Devuelve cuántas."""
    if not actual.exists():
        return 0
    try:
        viejo = sqlite3.connect(f"file:{actual}?mode=ro", uri=True)
        viejo.row_factory = sqlite3.Row
        filas = viejo.execute("SELECT * FROM suscripciones").fetchall()
        viejo.close()
    except sqlite3.Error:
        return 0
    if not filas:
        return 0
    try:
        con = sqlite3.connect(nueva)
        ya = {r[0] for r in con.execute("SELECT email FROM suscripciones")}
        cols = [d[0] for d in con.execute("SELECT * FROM suscripciones LIMIT 0").description]
        n = 0
        for f in filas:
            if f["email"] in ya:
                continue
            valores = [f[c] if c in f.keys() else None for c in cols]
            con.execute(f"INSERT INTO suscripciones ({','.join(cols)}) "
                        f"VALUES ({','.join('?' * len(cols))})", valores)
            n += 1
        if n:
            con.commit()
            log.warning("Se han conservado %d suscripciones que estaban aquí y no en la base de "
                        "GitHub. Revisa que estén sincronizadas.", n)
        con.close()
        return n
    except sqlite3.Error as e:
        log.warning("No se han podido conservar las suscripciones locales (%s)", e)
        return 0


def traer(cfg: dict, destino: Path) -> bool:
    """Deja en `destino` la base de GitHub si mejora la que hay. Devuelve True si la ha sustituido."""
    gh = (cfg.get("publicacion") or {}).get("github") or {}
    repo = (gh.get("repo") or "").strip()
    if not repo:
        return False

    url = PLANTILLA.format(repo=repo, rama=RAMA)
    r = http_get(url, headers={"User-Agent": UA}, timeout=120)
    if r is None or r.status_code != 200 or not r.content:
        log.info("No se ha podido traer la base de GitHub (se sigue con la local).")
        return False

    tmp_dir = Path(tempfile.mkdtemp(prefix="radar_gh_"))
    try:
        descomprimida = tmp_dir / "bajada.sqlite"
        try:
            descomprimida.write_bytes(gzip.decompress(r.content))
        except (OSError, EOFError, gzip.BadGzipFile) as e:
            log.warning("La base descargada de GitHub no se puede descomprimir (%s); se ignora.", e)
            return False

        nuevas = _contar(descomprimida)
        if nuevas[0] < 0:
            log.warning("La base descargada de GitHub no es una base válida; se ignora.")
            return False

        actuales = _contar(destino) if destino.exists() else (0, 0)
        if actuales[0] > nuevas[0] or actuales[1] > nuevas[1]:
            # Puede pasar si el workflow falló a medias. Mejor quedarse con lo que hay que perder histórico.
            log.warning("La base de GitHub trae MENOS registros (%d/%d) que la actual (%d/%d): no se sustituye.",
                        nuevas[0], nuevas[1], actuales[0], actuales[1])
            return False
        if actuales == nuevas:
            log.info("La base de GitHub es la misma que ya hay (%d convocatorias, %d licitaciones).", *nuevas)
            return False

        # Las suscripciones del fichero de aquí NO se tiran: la base que baja de GitHub se escribió
        # allí y no sabe nada de las altas hechas desde un PC desde entonces. Sustituir sin más borró
        # dos altas el 29/10/2026 sin dejar rastro. Se copian a la base nueva antes de sustituir.
        _salvar_suscripciones(destino, descomprimida)

        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp_destino = destino.with_name(destino.name + ".descarga")
        shutil.copyfile(descomprimida, tmp_destino)
        tmp_destino.replace(destino)
        log.info("Base traída de GitHub: %d convocatorias, %d licitaciones (antes %d/%d).",
                 nuevas[0], nuevas[1], actuales[0], actuales[1])
        return True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
