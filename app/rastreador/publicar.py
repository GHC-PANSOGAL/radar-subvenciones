"""Publicación del panel en GitHub Pages (sin necesidad de tener git instalado).

El panel se publica en una rama propia (``gh-pages``) que se **reescribe entera** en cada publicación:
cada vez se crea un commit SIN padre y se fuerza la rama a apuntar a él.

Por qué así y no un commit normal: el panel pesa 13 MB y el datos.json otros 14, y git guarda cada
versión entera porque son ficheros que comprimen mal y cambian por todas partes. Publicando a diario
en ``main``, el repositorio crecía unos 27 MB al día — en un año, gigabytes, y GitHub acaba avisando.
Con un commit huérfano no hay historial que acumular: la rama siempre tiene exactamente una versión.

El histórico de los datos no se pierde por esto: vive en la base de datos (rama ``datos``), que es
donde tiene sentido. Lo que se tira es el historial de un fichero generado, que no le sirve a nadie.

Requisito: Settings → Pages → Deploy from a branch → **gh-pages / root**. La página queda en
https://<usuario>.github.io/<repo>/ — pública para quien tenga la URL (Pages no admite contraseña).
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

import requests

from .util import UA

log = logging.getLogger("rastreador.publicar")
API = "https://api.github.com"
RAMA_PANEL = "gh-pages"


class GitHubPages:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.repo = (self.cfg.get("repo") or "").strip()          # "usuario/repositorio"
        self.rama = self.cfg.get("rama_panel") or RAMA_PANEL
        self.token = os.environ.get("GITHUB_TOKEN")
        self.activo = bool(self.cfg.get("activo") and self.repo and self.token)
        if self.cfg.get("activo") and not self.activo:
            log.info("Publicación en GitHub desactivada: falta 'repo' en config.yaml o GITHUB_TOKEN en .env")

    def _cab(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA}

    def _post(self, ruta: str, cuerpo: dict, timeout: int = 180) -> dict | None:
        r = requests.post(f"{API}/repos/{self.repo}/{ruta}", json=cuerpo, headers=self._cab(), timeout=timeout)
        if r.status_code in (200, 201):
            return r.json()
        log.warning("GitHub %s → HTTP %s: %s", ruta, r.status_code, r.text[:300])
        return None

    def _blob(self, fichero: Path) -> str | None:
        """Sube el contenido de un fichero y devuelve su sha."""
        d = self._post("git/blobs", {"content": base64.b64encode(fichero.read_bytes()).decode(),
                                     "encoding": "base64"})
        return d.get("sha") if d else None

    def _forzar_rama(self, commit_sha: str) -> bool:
        """Apunta la rama al commit nuevo. Si no existe, la crea."""
        r = requests.patch(f"{API}/repos/{self.repo}/git/refs/heads/{self.rama}",
                           json={"sha": commit_sha, "force": True}, headers=self._cab(), timeout=60)
        if r.status_code == 200:
            return True
        if r.status_code == 422:      # la rama todavía no existe
            d = self._post("git/refs", {"ref": f"refs/heads/{self.rama}", "sha": commit_sha})
            return d is not None
        log.warning("GitHub: no se pudo mover la rama %s → HTTP %s: %s", self.rama, r.status_code, r.text[:300])
        return False

    def publicar(self, panel: Path, version: str) -> str | None:
        """Sube index.html (y datos.json) reescribiendo la rama. Devuelve la URL pública si todo fue bien."""
        if not self.activo:
            return None

        ficheros = [(panel, "index.html")]
        datos = panel.with_name("datos.json")
        if datos.exists():
            ficheros.append((datos, "datos.json"))
        dominio = (self.cfg.get("dominio") or "").strip()

        arbol = []
        for ruta, nombre in ficheros:
            sha = self._blob(ruta)
            if not sha:
                log.warning("No se ha podido subir %s; se cancela la publicación.", nombre)
                return None
            arbol.append({"path": nombre, "mode": "100644", "type": "blob", "sha": sha})
        if dominio:
            # CNAME: GitHub Pages lo usa para el dominio propio. Al reescribir la rama entera hay que
            # volver a ponerlo cada vez, o el dominio se perdería en la primera publicación.
            d = self._post("git/blobs", {"content": base64.b64encode((dominio + "\n").encode()).decode(),
                                         "encoding": "base64"})
            if d:
                arbol.append({"path": "CNAME", "mode": "100644", "type": "blob", "sha": d["sha"]})

        t = self._post("git/trees", {"tree": arbol})
        if not t:
            return None
        # parents vacío = commit huérfano: la rama se queda con una sola versión y no acumula historial
        c = self._post("git/commits", {"message": f"Radar v{version}: panel actualizado",
                                       "tree": t["sha"], "parents": []})
        if not c or not self._forzar_rama(c["sha"]):
            return None

        usuario, repo = self.repo.split("/", 1)
        url = self.cfg.get("url") or (f"https://{dominio}/" if dominio else f"https://{usuario}.github.io/{repo}/")
        log.info("Panel publicado en %s (rama %s, reescrita)", url, self.rama)
        return url
