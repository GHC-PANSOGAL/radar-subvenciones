"""Perplexity — Search API (rastreo abierto) y Agent API (resúmenes).

Docs: https://docs.perplexity.ai  (Search: POST /search · Agent: POST /v1/agent)
El endpoint clásico /chat/completions (Sonar) se retira el 27/09/2026: no se usa.
"""
from __future__ import annotations

import json
import logging
import os

from ..util import dias_atras, fecha_us, http_post_json

log = logging.getLogger("rastreador.perplexity")
URL_SEARCH = "https://api.perplexity.ai/search"
URL_AGENT = "https://api.perplexity.ai/v1/agent"
RECENCIA_DIAS = {"hour": 1, "day": 1, "week": 7, "month": 31, "year": 365}


def _clave() -> str | None:
    return os.environ.get("PERPLEXITY_API_KEY")


def disponible() -> bool:
    return bool(_clave())


def _cab() -> dict:
    return {"Authorization": f"Bearer {_clave()}", "Content-Type": "application/json"}


class PerplexitySearch:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def buscar(self, consulta: str) -> list[dict]:
        cuerpo = {
            "query": consulta,
            "max_results": int(self.cfg.get("max_resultados", 15)),
            "country": self.cfg.get("pais", "ES"),
            "search_language_filter": ["es"],
            "search_recency_filter": self.cfg.get("recencia", "week"),
        }
        if self.cfg.get("dominios"):
            cuerpo["search_domain_filter"] = self.cfg["dominios"][:20]
        datos = http_post_json(URL_SEARCH, cuerpo, _cab(), timeout=60)
        if not datos:
            return []
        salida = []
        for r in datos.get("results", []):
            salida.append({
                "titulo": (r.get("title") or "").strip(),
                "url": r.get("url") or "",
                "fecha": (r.get("date") or r.get("last_updated") or "")[:10] or None,
                "resumen": (r.get("snippet") or "")[:600],
                "fuente": "Perplexity",
                "consulta": consulta,
            })
        return [s for s in salida if s["titulo"] and s["url"]]

    def buscar_todas(self) -> list[dict]:
        if not disponible():
            log.info("Perplexity: sin PERPLEXITY_API_KEY, se omite el rastreo abierto")
            return []
        salida = []
        for q in self.cfg.get("consultas", []):
            res = self.buscar(q)
            log.info("Perplexity '%s…': %d resultados", q[:45], len(res))
            salida.extend(res)
        return salida


def resumir_con_agente(modelo: str, instrucciones: str, entrada: str, esquema: dict) -> dict | None:
    """Agent API con salida JSON estructurada. Sin búsqueda web (el texto ya viene dado)."""
    cuerpo = {
        "model": modelo,
        "instructions": instrucciones,
        "input": entrada,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "resumen_ejecutivo", "schema": esquema, "strict": False}},
    }
    datos = http_post_json(URL_AGENT, cuerpo, _cab(), timeout=180)
    if not datos:
        return None
    texto = datos.get("output_text")
    if not texto:
        for item in datos.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        texto = c.get("text")
    if not texto:
        return None
    return _json_de_texto(texto)


def _json_de_texto(texto: str) -> dict | None:
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.strip("`")
        texto = texto[4:] if texto.lower().startswith("json") else texto
    ini, fin = texto.find("{"), texto.rfind("}")
    if ini == -1 or fin == -1:
        return None
    try:
        return json.loads(texto[ini:fin + 1])
    except ValueError:
        return None
