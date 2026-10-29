"""Las suscripciones viven en GitHub, no solo en OneDrive.

El problema que resuelve, que costó dos suscripciones el 29/10/2026:

Cuando alguien se da de alta desde el panel, el alta se escribe en la base de OneDrive. Pero desde que
rastrea GitHub Actions, la base buena es la de la rama ``datos``: GitHub la descarga, rastrea y la
vuelve a subir entera, sin enterarse nunca de lo que pasó en OneDrive. Y al abrir el panel, el PC se
baja la de GitHub y **sustituye** la suya. Resultado: el alta desaparece sin dejar rastro, y además
nunca llega a GitHub, que es quien manda los correos.

La solución es sacar las suscripciones de la base y ponerlas en un fichero propio, pequeño, en la rama
``datos``: ``suscripciones.json``. Ese fichero es la verdad. El PC lo lee y lo escribe al dar de alta
o de baja; GitHub lo lee al empezar cada rastreo y lo vuelca en su base antes de enviar nada.

Leerlo no necesita token (el repositorio es público). Escribirlo sí. Un PC sin token puede dar de alta
igualmente, pero el alta se queda en local: por eso se avisa bien claro cuando eso pasa.
"""
from __future__ import annotations

import base64
import json
import logging
import os

import requests

from .util import UA

log = logging.getLogger("rastreador.suscripciones")

API = "https://api.github.com"
FICHERO = "suscripciones.json"
RAMA = "datos"


def _repo(cfg: dict) -> str:
    return ((cfg.get("publicacion") or {}).get("github") or {}).get("repo", "").strip()


def leer_remoto(cfg: dict) -> list[dict] | None:
    """Las suscripciones que hay en GitHub. None si no se puede saber (no se asume que no hay)."""
    repo = _repo(cfg)
    if not repo:
        return None
    url = f"https://raw.githubusercontent.com/{repo}/{RAMA}/{FICHERO}"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
    except requests.RequestException as e:
        log.info("No se ha podido leer %s de GitHub (%s)", FICHERO, type(e).__name__)
        return None
    if r.status_code == 404:
        return []          # todavía no existe: no es un error
    if r.status_code != 200:
        log.info("No se ha podido leer %s de GitHub (HTTP %s)", FICHERO, r.status_code)
        return None
    try:
        d = r.json()
        return d if isinstance(d, list) else None
    except ValueError:
        return None


def subir(cfg: dict, suscripciones: list[dict]) -> tuple[bool, str]:
    """Escribe el fichero en la rama datos. Devuelve (ok, mensaje)."""
    repo = _repo(cfg)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not repo:
        return False, "No hay repositorio configurado en config.yaml"
    if not token:
        return False, ("Este PC no tiene GITHUB_TOKEN en el .env: el alta queda SOLO en este equipo y "
                       "no recibirá avisos. Ponlo con CLAVES.bat, o pide a quien lo tenga que repita el alta.")
    cab = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
           "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA}
    cuerpo = {
        "message": f"Suscripciones de avisos ({len(suscripciones)})",
        "branch": RAMA,
        "content": base64.b64encode(
            json.dumps(suscripciones, ensure_ascii=False, indent=1).encode()).decode(),
    }
    try:
        r = requests.get(f"{API}/repos/{repo}/contents/{FICHERO}", params={"ref": RAMA},
                         headers=cab, timeout=60)
        if r.status_code == 200:
            cuerpo["sha"] = r.json().get("sha")
        r = requests.put(f"{API}/repos/{repo}/contents/{FICHERO}", json=cuerpo, headers=cab, timeout=90)
    except requests.RequestException as e:
        return False, f"No se ha podido conectar con GitHub ({type(e).__name__})"
    if r.status_code in (200, 201):
        return True, f"{len(suscripciones)} suscripciones guardadas en GitHub"
    return False, f"GitHub HTTP {r.status_code}: {r.text[:200]}"


def fusionar_en_base(db, cfg: dict) -> int:
    """Vuelca en la base las suscripciones de GitHub. Devuelve cuántas se han añadido o cambiado.

    Se usa al principio del rastreo: sin esto, GitHub manda los correos sin saber quién se dio de alta
    desde un PC. Lo de GitHub manda, porque es donde se guarda al darse de alta.
    """
    remotas = leer_remoto(cfg)
    if remotas is None:
        log.info("No se han podido leer las suscripciones de GitHub; se usan las de la base.")
        return 0
    from . import avisos
    actuales = {s["email"]: s for s in avisos.listar(db)}
    n = 0
    for s in remotas:
        email = (s.get("email") or "").strip().lower()
        if not email:
            continue
        if _distintas(actuales.get(email), s):
            avisos.guardar(db, s)
            n += 1
    return n


# Campos que de verdad definen una suscripción. Comparar los diccionarios enteros no sirve: traen
# fechas y claves que cambian solas, y entonces cada ejecución decía "2 cambiadas" sin que lo fueran.
CAMPOS = ("nombre", "ccaa", "categorias", "subvenciones", "licitaciones", "activo")


def _distintas(a: dict | None, b: dict) -> bool:
    if a is None:
        return True
    for k in CAMPOS:
        va, vb = a.get(k), b.get(k)
        if isinstance(va, list) or isinstance(vb, list):
            if sorted(va or []) != sorted(vb or []):
                return True
        elif bool(va) != bool(vb) if k in ("subvenciones", "licitaciones", "activo") else va != vb:
            return True
    return False
