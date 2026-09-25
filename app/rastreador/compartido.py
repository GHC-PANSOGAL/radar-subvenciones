"""Carpeta compartida (OneDrive / red) para que varios PCs actualicen el mismo radar.

Esquema "traer → ejecutar → llevar":
  1. Si hay un bloqueo reciente de otro PC, no se ejecuta.
  2. Se copia la base de datos compartida a local si es más nueva que la local.
  3. Se ejecuta el rastreo en local.
  4. Se copian base de datos y panel a la carpeta compartida (escritura atómica) y se libera el bloqueo.
En modo automático (tarea programada) se omite la ejecución si el panel compartido se actualizó hace poco,
para que cinco PCs a las 08:30 no repitan el mismo trabajo ni choquen entre sí.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("rastreador.compartido")
FICHEROS_PANEL = ("index.html", "datos.json")
NOMBRE_DB = "subvenciones.sqlite"
BLOQUEO = "radar.lock"
ESTADO = "estado.json"


def _pc() -> str:
    return f"{os.environ.get('USERNAME') or os.environ.get('USER') or '?'}@{socket.gethostname()}"


def _copiar_atomico(origen: Path, destino: Path) -> None:
    tmp = destino.with_name(destino.name + ".tmp")
    shutil.copyfile(origen, tmp)
    tmp.replace(destino)


class Compartido:
    def __init__(self, carpeta: str | None, db_local: Path, panel_local: Path, minutos_bloqueo: int = 30):
        self.carpeta = self._resolver(carpeta)
        self.db_local, self.panel_local = db_local, panel_local
        self.minutos_bloqueo = minutos_bloqueo
        self.activo = bool(self.carpeta)

    @staticmethod
    def _resolver(carpeta: str | None) -> Path | None:
        """Expande variables (${OneDriveCommercial}, %USERPROFILE%, ~). Si no se resuelven, se desactiva."""
        if not carpeta:
            return None
        ruta = os.path.expandvars(os.path.expanduser(carpeta))
        if "${" in ruta or "%" in ruta:
            # segunda oportunidad: OneDrive personal en vez del de empresa
            alt = carpeta.replace("${OneDriveCommercial}", "${OneDrive}").replace("%OneDriveCommercial%", "%OneDrive%")
            ruta = os.path.expandvars(os.path.expanduser(alt))
        if "${" in ruta or "%" in ruta:
            log.warning("Carpeta compartida sin resolver (%s): variable de entorno no definida; se trabaja solo en local.", carpeta)
            return None
        return Path(ruta)

    # ------------------------------------------------------------ estado
    def _estado(self) -> dict:
        try:
            return json.loads((self.carpeta / ESTADO).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def ultima_actualizacion(self) -> datetime | None:
        e = self._estado()
        try:
            return datetime.fromisoformat(e["actualizado"])
        except (KeyError, ValueError):
            return None

    def actualizado_hace_menos_de(self, horas: float) -> bool:
        u = self.ultima_actualizacion()
        return bool(u and datetime.now() - u < timedelta(hours=horas))

    # ------------------------------------------------------------ bloqueo
    def bloquear(self) -> bool:
        """True si se obtiene el bloqueo; False si otro PC está actualizando."""
        if not self.activo:
            return True
        try:
            self.carpeta.mkdir(parents=True, exist_ok=True)
            lock = self.carpeta / BLOQUEO
            if lock.exists():
                try:
                    datos = json.loads(lock.read_text(encoding="utf-8"))
                    desde = datetime.fromisoformat(datos.get("desde"))
                    if datetime.now() - desde < timedelta(minutes=self.minutos_bloqueo) and datos.get("pc") != _pc():
                        log.warning("Otro PC (%s) está actualizando desde %s; se omite esta ejecución.",
                                    datos.get("pc"), desde.strftime("%H:%M"))
                        return False
                except (ValueError, TypeError):
                    pass  # bloqueo corrupto: se sobrescribe
            lock.write_text(json.dumps({"pc": _pc(), "desde": datetime.now().isoformat(timespec="seconds")}),
                            encoding="utf-8")
            return True
        except OSError as e:
            log.warning("Carpeta compartida no accesible (%s); se continúa solo en local.", e)
            self.activo = False
            return True

    def liberar(self) -> None:
        if self.activo:
            try:
                (self.carpeta / BLOQUEO).unlink(missing_ok=True)
            except OSError:
                pass

    # -------------------------------------------------------------- traer
    def traer(self) -> None:
        """Copia la base compartida a local si es más reciente (o si no hay local)."""
        if not self.activo:
            return
        remota = self.carpeta / NOMBRE_DB
        if not remota.exists():
            return
        try:
            if not self.db_local.exists() or remota.stat().st_mtime > self.db_local.stat().st_mtime + 1:
                self.db_local.parent.mkdir(parents=True, exist_ok=True)
                _copiar_atomico(remota, self.db_local)
                log.info("Base de datos compartida traída de %s", self.carpeta)
        except OSError as e:
            log.warning("No se pudo traer la base compartida: %s", e)

    # -------------------------------------------------------------- llevar
    @staticmethod
    def _filas(db: Path) -> int:
        """Convocatorias + licitaciones de una base. -1 si no se puede leer."""
        if not db.exists():
            return 0
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            n = (c.execute("SELECT COUNT(*) FROM convocatorias").fetchone()[0]
                 + c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0])
            c.close()
            return n
        except sqlite3.Error:
            return -1

    def llevar(self, version: str) -> None:
        """Copia base de datos y panel a la carpeta compartida y anota el estado.

        Con una salvaguarda: si la base local tiene MENOS registros que la compartida, no se sube.
        Pasa cuando un PC no ha podido traerse la compartida (fichero ocupado, OneDrive a medio
        sincronizar) y rastrea sobre una base casi vacía: sin esto, se cargaría el trabajo de todos.
        """
        if not self.activo:
            return
        remota = self.carpeta / NOMBRE_DB
        n_local, n_remota = self._filas(self.db_local), self._filas(remota)
        if n_remota > 0 and 0 <= n_local < n_remota:
            log.warning("NO se sube la base a la carpeta compartida: la local tiene %d registros y la compartida %d. "
                        "Seguramente no se pudo traer la compartida al empezar. Se conserva la compartida.",
                        n_local, n_remota)
            return
        try:
            _copiar_atomico(self.db_local, self.carpeta / NOMBRE_DB)
            for nombre in FICHEROS_PANEL:
                origen = self.panel_local.with_name(nombre)
                if origen.exists():
                    _copiar_atomico(origen, self.carpeta / nombre)
            (self.carpeta / ESTADO).write_text(json.dumps({
                "actualizado": datetime.now().isoformat(timespec="seconds"), "pc": _pc(), "version": version,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            log.info("Panel y base de datos llevados a %s", self.carpeta)
        except OSError as e:
            log.warning("No se pudo copiar a la carpeta compartida: %s", e)
