"""Abrir el panel con los datos del día, sin rastrear.

    python -m rastreador.abrir

Esto es lo que ejecuta el acceso directo del escritorio. Hace tres cosas y ninguna tarda:

1. Se trae de GitHub la base que rastreó el workflow esta madrugada (2,5 MB comprimidos).
2. Regenera el panel con ella.
3. Lo abre.

En total, unos diez segundos. **No rastrea**: rastrear son siete minutos y ya lo hace GitHub todos los
días a las 06:30 UTC, encienda alguien el PC o no. Quien quiera forzar un rastreo completo tiene el
botón "Actualizar ahora" del propio panel.

Si no hay internet, se abre el panel que haya, que es lo que uno espera de un acceso directo: que abra
algo. Un panel de ayer es infinitamente mejor que un error.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from . import __version__, desdegithub, panel
from .compartido import Compartido
from .db import DB
from .util import RAIZ, cargar_config, cargar_env, configurar_logging

log = logging.getLogger("rastreador.abrir")


def _abrir(ruta: Path) -> None:
    try:
        os.startfile(str(ruta))          # solo existe en Windows
    except AttributeError:
        os.system(f'xdg-open "{ruta}" >/dev/null 2>&1 &')
    except OSError as e:
        print(f"No se ha podido abrir solo ({e}). Ábrelo a mano:\n  {ruta}")


def main() -> int:
    cargar_env()
    configurar_logging("INFO")
    cfg = cargar_config()
    g = cfg["general"]
    comp = Compartido(g.get("carpeta_compartida"), RAIZ / g["db"], RAIZ / g["panel"])

    print(f"Radar de subvenciones y licitaciones  v{__version__}")
    print("Trayendo los datos de hoy…")

    destino_panel = (comp.carpeta / "index.html") if comp.activo else (RAIZ / g["panel"])
    db_path = (comp.carpeta / "subvenciones.sqlite") if comp.activo else (RAIZ / g["db"])

    cambiada = False
    try:
        cambiada = desdegithub.traer(cfg, db_path)
    except Exception as e:  # noqa: BLE001
        log.warning("Sin conexión con GitHub (%s): se abre el panel que ya había.", e)

    if cambiada or not destino_panel.exists():
        try:
            db = DB(db_path)
            panel.generar(db, cfg, destino_panel)
            db.con.close()
            print(f"Panel actualizado: {destino_panel}")
        except Exception as e:  # noqa: BLE001
            log.warning("No se ha podido regenerar el panel (%s); se abre el que había.", e)
    else:
        print("Ya tenías los datos del día.")

    if not destino_panel.exists():
        print("No hay ningún panel que abrir. Ejecuta INSTALAR.bat o pulsa 'Actualizar ahora'.")
        return 1
    _abrir(destino_panel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
