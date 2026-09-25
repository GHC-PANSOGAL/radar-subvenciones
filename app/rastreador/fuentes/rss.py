"""Fuente RSS — feeds de organismos y boletines (sin dependencias: parser XML propio)."""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

from ..util import http_get, limpiar_html

log = logging.getLogger("rastreador.rss")
NS = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}


def _fecha(texto: str | None) -> str | None:
    if not texto:
        return None
    texto = texto.strip()
    try:
        return parsedate_to_datetime(texto).date().isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def leer_feed(url: str) -> list[dict]:
    r = http_get(url, timeout=30, reintentos=2)
    if r is None or r.status_code != 200 or not r.content:
        return []
    contenido = r.content
    try:
        raiz = ET.fromstring(contenido)
    except ET.ParseError:
        try:  # algunos boletines declaran ISO-8859-1 pero sirven bytes sucios
            raiz = ET.fromstring(contenido.decode("latin-1", "ignore").encode("utf-8"))
        except ET.ParseError:
            log.debug("Feed no parseable: %s", url)
            return []
    items = []
    # RSS 2.0
    for it in raiz.iter("item"):
        items.append({
            "titulo": limpiar_html(it.findtext("title")),
            "url": (it.findtext("link") or it.findtext("guid") or "").strip(),
            "fecha": _fecha(it.findtext("pubDate") or it.findtext("dc:date", namespaces=NS)),
            "resumen": limpiar_html(it.findtext("description"))[:600],
        })
    # Atom
    for it in raiz.iter("{http://www.w3.org/2005/Atom}entry"):
        enlace = it.find("atom:link", NS)
        items.append({
            "titulo": limpiar_html(it.findtext("atom:title", namespaces=NS)),
            "url": (enlace.get("href") if enlace is not None else "") or "",
            "fecha": _fecha(it.findtext("atom:updated", namespaces=NS) or it.findtext("atom:published", namespaces=NS)),
            "resumen": limpiar_html(it.findtext("atom:summary", namespaces=NS) or it.findtext("atom:content", namespaces=NS))[:600],
        })
    return [i for i in items if i["titulo"] and i["url"]]


class RSS:
    def __init__(self, cfg: dict):
        self.feeds = cfg.get("feeds", [])

    def leer_todos(self) -> list[dict]:
        salida = []
        for f in self.feeds:
            items = leer_feed(f["url"])
            for it in items:
                it["fuente"] = f["nombre"]
                it["ambito"] = f.get("ambito")
            log.info("RSS %-28s %3d elementos", f["nombre"], len(items))
            salida.extend(items)
        return salida
