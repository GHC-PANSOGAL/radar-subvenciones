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

        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp_destino = destino.with_name(destino.name + ".descarga")
        shutil.copyfile(descomprimida, tmp_destino)
        tmp_destino.replace(destino)
        log.info("Base traída de GitHub: %d convocatorias, %d licitaciones (antes %d/%d).",
                 nuevas[0], nuevas[1], actuales[0], actuales[1])
        return True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
