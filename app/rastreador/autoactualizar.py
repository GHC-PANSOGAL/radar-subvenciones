"""Actualización automática desde la carpeta compartida.

El programa se ejecuta desde una copia en ``%LOCALAPPDATA%\\GHC\\Radar``, no desde OneDrive. Hasta ahora,
dejar una versión nueva en la carpeta compartida no servía de nada: había que volver a pasar INSTALAR.bat
en cada PC, y era facilísimo quedarse atrás sin enterarse.

Con esto, al empezar cada ejecución el programa mira si en la carpeta de origen (la que contiene
``_compartido``) hay una versión posterior y, si la hay, se copia los ficheros encima y se reinicia con el
código nuevo. Nadie tiene que hacer nada.

Qué se copia y qué NO:

* **Sí**: ``rastreador/``, ``assets/``, ``deploy/``, ``organismos.yaml``, ``requirements.txt``,
  ``README.md``, ``.env.example`` y ``config.yaml``.
* **No, jamás**: ``.env`` (las claves), ``data/`` (la base), ``panel/`` y ``.venv``.
* De ``config.yaml`` se conserva la línea ``carpeta_compartida`` de este PC, que la calculó el instalador
  y es distinta en cada equipo.

Lo que esto NO puede hacer y sigue necesitando INSTALAR.bat: cambiar el acceso directo del escritorio,
la tarea programada, el registro del protocolo ``radarghc://`` o instalar dependencias nuevas. Cuando
detecta que alguna de esas cosas ha cambiado, lo avisa en el registro.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from pathlib import Path

from . import __version__
from .util import RAIZ

log = logging.getLogger("rastreador.autoactualizar")

COPIAR_CARPETAS = ("rastreador", "assets", "deploy")
COPIAR_FICHEROS = ("organismos.yaml", "requirements.txt", "README.md", "CHANGELOG.md", ".env.example")
NUNCA = (".env", "data", "panel", ".venv")
BANDERA = "RADAR_YA_ACTUALIZADO"     # evita reinicios en bucle si algo va mal


def _version_de(carpeta: Path) -> str | None:
    try:
        t = (carpeta / "rastreador" / "__init__.py").read_text(encoding="utf-8")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', t)
        return m.group(1) if m else None
    except OSError:
        return None


def _posterior(a: str, b: str) -> bool:
    try:
        return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))
    except (ValueError, AttributeError):
        return False


def origen(cfg: dict) -> Path | None:
    """Carpeta desde la que se instala: la que contiene `_compartido`."""
    comp = (cfg.get("general") or {}).get("carpeta_compartida") or ""
    if not comp:
        return None
    ruta = Path(os.path.expandvars(os.path.expanduser(comp)))
    if "${" in str(ruta) or "%" in str(ruta):
        return None
    padre = ruta.parent
    return padre if (padre / "rastreador" / "__init__.py").exists() else None


def _config_fusionado(nuevo: Path, actual: Path) -> str | None:
    """El config nuevo, pero conservando la carpeta_compartida que calculó el instalador aquí."""
    try:
        texto_nuevo = nuevo.read_text(encoding="utf-8")
        texto_actual = actual.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'(?m)^\s*carpeta_compartida:\s*(.+)$', texto_actual)
    if not m:
        return texto_nuevo
    return re.sub(r'(?m)^(\s*carpeta_compartida:\s*).*$', lambda x: x.group(1) + m.group(1), texto_nuevo)


def actualizar(cfg: dict) -> str | None:
    """Copia la versión nueva si la hay. Devuelve la versión instalada o None."""
    if os.environ.get(BANDERA):
        return None
    org = origen(cfg)
    if not org:
        return None
    nueva = _version_de(org)
    if not nueva or not _posterior(nueva, __version__):
        return None

    log.info("Hay una versión nueva en la carpeta compartida: %s (aquí está la %s). Actualizando…",
             nueva, __version__)
    try:
        # avisos para lo que esto no puede hacer solo
        try:
            if (org / "requirements.txt").read_text(encoding="utf-8") != \
               (RAIZ / "requirements.txt").read_text(encoding="utf-8"):
                log.warning("Las dependencias han cambiado: pasa INSTALAR.bat cuando puedas.")
        except OSError:
            pass
        ps_org, ps_local = org / "deploy/windows/instalar.ps1", RAIZ / "deploy/windows/instalar.ps1"
        instalador_cambia = ps_org.exists() and ps_local.exists() and \
            ps_org.read_bytes() != ps_local.read_bytes()

        for carpeta in COPIAR_CARPETAS:
            o, d = org / carpeta, RAIZ / carpeta
            if not o.is_dir():
                continue
            shutil.copytree(o, d, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for fichero in COPIAR_FICHEROS:
            if (org / fichero).exists():
                shutil.copy2(org / fichero, RAIZ / fichero)
        fusionado = _config_fusionado(org / "config.yaml", RAIZ / "config.yaml")
        if fusionado:
            (RAIZ / "config.yaml").write_text(fusionado, encoding="utf-8")

        log.info("Actualizado a la versión %s.", nueva)
        if instalador_cambia:
            log.warning("El instalador ha cambiado: el acceso directo, la tarea de las 08:30 o el protocolo "
                        "radarghc:// pueden necesitar que pases INSTALAR.bat una vez.")
        return nueva
    except (OSError, shutil.Error) as e:
        log.warning("No se ha podido actualizar solo (%s). Se sigue con la versión %s.", e, __version__)
        return None


def reiniciar(nueva: str) -> None:
    """Vuelve a lanzar el programa con el código recién copiado (los módulos viejos ya están en memoria)."""
    log.info("Reiniciando con la versión %s…", nueva)
    entorno = dict(os.environ, **{BANDERA: nueva})
    try:
        os.execve(sys.executable, [sys.executable, "-m", "rastreador.run", *sys.argv[1:]], entorno)
    except OSError as e:  # noqa: BLE001
        log.warning("No se ha podido reiniciar (%s); la versión nueva se usará en la próxima ejecución.", e)
