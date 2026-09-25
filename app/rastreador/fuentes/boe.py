"""Fuente BOE — API abierta de sumario diario.

GET https://www.boe.es/datosabiertos/api/boe/sumario/AAAAMMDD  (cabecera Accept: application/json obligatoria)
Sección 3 = Otras disposiciones (convocatorias, bases), 5B = Anuncios (extractos de convocatoria con nº BDNS).
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from ..util import http_get, normalizar

log = logging.getLogger("rastreador.boe")
URL = "https://www.boe.es/datosabiertos/api/boe/sumario/{}"
RE_BDNS = re.compile(r"BDNS\s*\(?\s*Identif\.?\s*\)?\s*:?\s*(\d{5,7})", re.I)


def _lista(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


class BOE:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.secciones = set(cfg.get("secciones", ["3", "5B"]))
        self.re_ayuda = re.compile(cfg["regex_ayuda"], re.I)
        self.re_energia = re.compile(cfg["regex_energia"], re.I)

    def sumario(self, dia: date) -> list[dict]:
        r = http_get(URL.format(dia.strftime("%Y%m%d")), headers={"Accept": "application/json"})
        if r is None or r.status_code != 200:
            return []
        try:
            datos = r.json()
        except ValueError:
            return []
        items = []
        for diario in _lista(datos.get("data", {}).get("sumario", {}).get("diario")):
            for sec in _lista(diario.get("seccion")):
                if str(sec.get("codigo")) not in self.secciones:
                    continue
                for dep in _lista(sec.get("departamento")):
                    grupos = _lista(dep.get("epigrafe")) or [dep]
                    for ep in grupos:
                        for it in _lista(ep.get("item")):
                            titulo = it.get("titulo") or ""
                            if not (self.re_ayuda.search(titulo) and self.re_energia.search(normalizar(titulo) + " " + titulo)):
                                continue
                            url_html = it.get("url_html") or ""
                            if url_html and url_html.startswith("/"):
                                url_html = "https://www.boe.es" + url_html
                            items.append({
                                "id": it.get("identificador"),
                                "titulo": titulo.strip(),
                                "departamento": dep.get("nombre"),
                                "seccion": sec.get("codigo"),
                                "url": url_html or f"https://www.boe.es/diario_boe/txt.php?id={it.get('identificador')}",
                                "fecha": dia.isoformat(),
                            })
        return items

    def buscar_periodo(self, desde: date, hasta: date) -> list[dict]:
        salida = []
        d = desde
        while d <= hasta:
            salida.extend(self.sumario(d))
            d += timedelta(days=1)
        log.info("BOE %s → %s: %d anuncios relevantes", desde, hasta, len(salida))
        return salida

    @staticmethod
    def numero_bdns(item: dict) -> str | None:
        """Intenta extraer el nº BDNS del texto del anuncio (extractos de convocatoria)."""
        r = http_get(item["url"], timeout=30)
        if r is None or r.status_code != 200:
            return None
        m = RE_BDNS.search(r.text)
        return m.group(1) if m else None
