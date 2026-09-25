"""Utilidades comunes: configuración, HTTP con reintentos, fechas, logging."""
from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import yaml

log = logging.getLogger("rastreador")

RAIZ = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (X11; Linux x86_64) RastreadorSubvencionesGHC/1.0 (+https://ghcneutral.com)"


def cargar_env(ruta: Path | None = None) -> None:
    """Carga variables de un fichero .env (KEY=VALUE) sin dependencias externas."""
    ruta = ruta or RAIZ / ".env"
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cargar_config(ruta: Path | None = None) -> dict:
    ruta = ruta or RAIZ / "config.yaml"
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f)


def cargar_organismos() -> dict:
    with open(RAIZ / "organismos.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def configurar_logging(nivel: str = "INFO") -> None:
    """Registro por consola y, siempre, en data/rastreador.log (se recorta si pasa de 2 MB)."""
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    raiz = logging.getLogger()
    raiz.setLevel(getattr(logging, nivel.upper(), logging.INFO))
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
    consola = logging.StreamHandler()
    consola.setFormatter(fmt)
    raiz.addHandler(consola)
    try:
        ruta = RAIZ / "data" / "rastreador.log"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        if ruta.exists() and ruta.stat().st_size > 2_000_000:
            ruta.replace(ruta.with_suffix(".log.1"))
        fichero = logging.FileHandler(ruta, encoding="utf-8")
        fichero.setFormatter(fmt)
        raiz.addHandler(fichero)
    except OSError as e:  # noqa: BLE001
        raiz.warning("No se pudo abrir el fichero de registro: %s", e)


# ------------------------------------------------------------------ HTTP
_sesion = requests.Session()
_sesion.headers.update({"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})


def http_get(url: str, *, params: dict | None = None, headers: dict | None = None,
             timeout: int = 40, reintentos: int = 3, pausa: float = 1.5) -> requests.Response | None:
    """GET con reintentos exponenciales. Devuelve None si falla definitivamente."""
    ultimo = None
    for intento in range(reintentos):
        try:
            r = _sesion.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code < 500:
                return r
            ultimo = f"HTTP {r.status_code}"
        except requests.RequestException as e:  # noqa: PERF203
            ultimo = str(e)
        time.sleep(pausa * (2 ** intento))
    log.warning("GET %s falló tras %d intentos: %s", url, reintentos, ultimo)
    return None


def http_post_json(url: str, cuerpo: dict, headers: dict, timeout: int = 120,
                   reintentos: int = 2) -> dict | None:
    ultimo = None
    for intento in range(reintentos):
        try:
            r = _sesion.post(url, json=cuerpo, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            ultimo = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code in (400, 401, 403):
                break
        except requests.RequestException as e:  # noqa: PERF203
            ultimo = str(e)
        time.sleep(2 * (intento + 1))
    log.warning("POST %s falló: %s", url, ultimo)
    return None


# ----------------------------------------------------------------- texto
def normalizar(texto: str | None) -> str:
    """Minúsculas y sin acentos, para comparar palabras clave."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


def limpiar_html(texto: str | None) -> str:
    if not texto:
        return ""
    t = re.sub(r"<[^>]+>", " ", texto)
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    t = re.sub(r"&amp;", "&", t)
    return re.sub(r"\s+", " ", t).strip()


# ----------------------------------------------------------------- fechas
def hoy() -> date:
    return date.today()


def fecha_es(d: date) -> str:
    """dd/MM/yyyy (formato que exige la BDNS en parámetros)."""
    return d.strftime("%d/%m/%Y")


def fecha_us(d: date) -> str:
    """MM/DD/YYYY (formato de los filtros de fecha de Perplexity)."""
    return d.strftime("%m/%d/%Y")


def parse_fecha(valor) -> date | None:
    """Acepta yyyy-mm-dd, dd/mm/yyyy, datetime, o None."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def dias_atras(n: int) -> date:
    return hoy() - timedelta(days=n)
