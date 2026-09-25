"""Diagnóstico de una instalación: qué ve este PC y qué no.

    python -m rastreador.diagnostico

Pensado para cuando un compañero dice "a mí me salen 0 subvenciones". Responde a las tres preguntas
que importan: ¿este PC ve la carpeta compartida?, ¿qué hay en la base local y en la compartida?, y
¿qué panel está abriendo el acceso directo?
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from . import __version__
from .compartido import Compartido
from .util import RAIZ, cargar_config, cargar_env

OK, MAL, AVISO = "  [OK] ", "  [X]  ", "  [!]  "


def _contar(db: Path) -> tuple[int, int, str]:
    """(convocatorias, licitaciones, fecha más antigua). (-1, -1, "") si no se puede leer."""
    if not db.exists():
        return -1, -1, ""
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        n_c = c.execute("SELECT COUNT(*) FROM convocatorias").fetchone()[0]
        n_l = c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]
        mn = c.execute("SELECT MIN(fecha_publicacion) FROM convocatorias").fetchone()[0]
        c.close()
        return n_c, n_l, mn or ""
    except sqlite3.Error:
        return -1, -1, ""


def _cuenta(db: Path) -> str:
    n_c, n_l, mn = _contar(db)
    if n_c < 0:
        return "no existe o no se puede leer"
    return f"{n_c} convocatorias, {n_l} licitaciones (la más antigua: {mn or '—'})"


def main() -> None:  # noqa: C901
    cargar_env()
    cfg = cargar_config()
    g = cfg["general"]
    db_local = RAIZ / g["db"]
    panel_local = RAIZ / g["panel"]

    print()
    print("=" * 74)
    print(f"  Radar de subvenciones y licitaciones — diagnóstico (v{__version__})")
    print(f"  Instalación: {RAIZ}")
    print("=" * 74)
    print()

    # ------------------------------------------------------------ carpeta compartida
    print("CARPETA COMPARTIDA")
    print(f"  Configurada: {g.get('carpeta_compartida')}")
    comp = Compartido(g.get("carpeta_compartida"), db_local, panel_local)
    if not comp.activo:
        print(MAL + "NO se ha podido resolver en este PC.")
        print("       Suele ser que OneDrive no tiene sincronizada esa carpeta, o que aquí cuelga de otra ruta.")
        print("       Variables de este PC:")
        for v in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
            print(f"         {v} = {os.environ.get(v) or '(no definida)'}")
        print("       Este PC trabaja SOLO EN LOCAL: no ve lo que rastreen los demás.")
    else:
        print(f"  Resuelta en: {comp.carpeta}")
        if comp.carpeta.exists():
            print(OK + "Existe y es accesible.")
            db_comp = comp.carpeta / "subvenciones.sqlite"
            print(f"       Base compartida: {_cuenta(db_comp)}")
            est = comp.carpeta / "estado.json"
            if est.exists():
                try:
                    d = json.loads(est.read_text(encoding="utf-8"))
                    print(f"       Última actualización: {d.get('actualizado')} desde {d.get('pc')} (v{d.get('version')})")
                except ValueError:
                    pass
            panel_comp = comp.carpeta / "index.html"
            print(f"       Panel compartido: {'sí' if panel_comp.exists() else 'NO (nadie ha rastreado todavía)'}")
        else:
            print(MAL + "La ruta se resuelve pero la carpeta NO existe en este PC.")
            print("       Comprueba en OneDrive que está sincronizada y marcada")
            print("       'Conservar siempre en este dispositivo' (no 'solo en la nube').")
    print()

    # ------------------------------------------------------------------- base local
    print("BASE DE DATOS LOCAL")
    print(f"  {db_local}")
    print(f"  {_cuenta(db_local)}")
    if _contar(db_local)[0] == 0:
        print(AVISO + "Vacía: este PC no ha rastreado nada todavía y tampoco ha traído la base compartida.")
    print()

    # ------------------------------------------------------------------- qué panel
    print("PANEL")
    print(f"  Local:      {panel_local}  ({'existe' if panel_local.exists() else 'NO existe'})")
    if comp.activo:
        print(f"  Compartido: {comp.carpeta / 'index.html'}  "
              f"({'existe' if (comp.carpeta / 'index.html').exists() else 'NO existe'})")
        print("  El acceso directo del escritorio debería abrir el COMPARTIDO: es el que actualizan todos.")
    print()

    # ------------------------------------------------------------------ clave LLM
    print("RESÚMENES")
    prov = (cfg.get("llm") or {}).get("proveedor", "ninguno")
    clave = os.environ.get("GEMINI_API_KEY", "").strip()
    tiene = bool(clave) and set(clave.replace("AIza", "").replace("-", "").lower()) != {"x"}
    print(f"  Proveedor: {prov}")
    print((OK if tiene else AVISO) + ("Clave de Gemini presente (comprueba que funciona con CLAVES.bat)."
                                      if tiene else "Sin clave de Gemini: los resúmenes salen en modo básico."))
    print("       Solo hace falta en el PC que rastrea; los resúmenes viajan en la base compartida.")
    print()

    # ------------------------------------------------------------------ conclusión
    print("=" * 74)
    if not comp.activo or not comp.carpeta.exists():
        print("  QUÉ HACER: arreglar primero la carpeta compartida. Mientras no se vea, este PC")
        print("  no compartirá nada con los demás por mucho que actualice.")
    elif not (comp.carpeta / "subvenciones.sqlite").exists():
        print("  QUÉ HACER: nadie ha rastreado todavía. Que alguien ejecute CARGAR_HISTORICO.bat")
        print("  o pulse 'Actualizar ahora'.")
    elif _contar(db_local)[0] <= 0:
        print("  QUÉ HACER: pulsa 'Actualizar ahora' en el panel (o ejecuta actualizar.bat) una vez:")
        print("  al arrancar se trae la base compartida y el panel se rellena.")
    else:
        print("  Todo apunta a que esta instalación está bien. Si el panel se ve vacío, es la")
        print("  página cacheada del navegador: pulsa F5.")
    print("=" * 74)
    print()


if __name__ == "__main__":
    main()
