"""Publicación del panel en GitHub Pages (sin necesidad de tener git instalado).

Sube index.html (y datos.json) a un repositorio mediante la API "contents" de GitHub. El repositorio debe tener
GitHub Pages activado (Settings → Pages → Deploy from a branch → main / root). La página queda en
https://<usuario>.github.io/<repo>/  — pública para quien tenga la URL (GitHub Pages no admite contraseña).
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


class GitHubPages:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.repo = (self.cfg.get("repo") or "").strip()          # "usuario/repositorio"
        self.rama = self.cfg.get("rama", "main")
        self.token = os.environ.get("GITHUB_TOKEN")
        self.activo = bool(self.cfg.get("activo") and self.repo and self.token)
        if self.cfg.get("activo") and not self.activo:
            log.info("Publicación en GitHub desactivada: falta 'repo' en config.yaml o GITHUB_TOKEN en .env")

    def _cab(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA}

    def _sha_actual(self, ruta: str) -> str | None:
        r = requests.get(f"{API}/repos/{self.repo}/contents/{ruta}", params={"ref": self.rama},
                         headers=self._cab(), timeout=30)
        if r.status_code == 200:
            return r.json().get("sha")
        if r.status_code == 404:
            return None
        # ficheros > 1 MB: la API contents no los devuelve; se busca el sha en el árbol
        r = requests.get(f"{API}/repos/{self.repo}/git/trees/{self.rama}", params={"recursive": "1"},
                         headers=self._cab(), timeout=30)
        if r.status_code == 200:
            for it in r.json().get("tree", []):
                if it.get("path") == ruta:
                    return it.get("sha")
        return None

    def subir(self, fichero: Path, ruta_repo: str, mensaje: str) -> bool:
        cuerpo = {"message": mensaje, "branch": self.rama,
                  "content": base64.b64encode(fichero.read_bytes()).decode()}
        sha = self._sha_actual(ruta_repo)
        if sha:
            cuerpo["sha"] = sha
        r = requests.put(f"{API}/repos/{self.repo}/contents/{ruta_repo}", json=cuerpo, headers=self._cab(), timeout=120)
        if r.status_code in (200, 201):
            return True
        log.warning("GitHub: no se pudo subir %s → HTTP %s: %s", ruta_repo, r.status_code, r.text[:300])
        return False

    def publicar(self, panel: Path, version: str) -> str | None:
        """Sube index.html y datos.json. Devuelve la URL pública si todo fue bien."""
        if not self.activo:
            return None
        ok = self.subir(panel, "index.html", f"Radar v{version}: panel actualizado")
        datos = panel.with_name("datos.json")
        if datos.exists():
            self.subir(datos, "datos.json", f"Radar v{version}: datos actualizados")
        if not ok:
            return None
        dominio = (self.cfg.get("dominio") or "").strip()
        if dominio and self._sha_actual("CNAME") is None:
            # fichero CNAME: GitHub Pages lo usa para el dominio propio (además hay que ponerlo en Settings → Pages)
            tmp = panel.with_name("CNAME"); tmp.write_text(dominio + "\n", encoding="utf-8")
            self.subir(tmp, "CNAME", "Dominio propio de GitHub Pages")
        usuario, repo = self.repo.split("/", 1)
        url = self.cfg.get("url") or (f"https://{dominio}/" if dominio else f"https://{usuario}.github.io/{repo}/")
        log.info("Panel publicado en %s", url)
        return url
