"""Clasificación temática: decide si un elemento es relevante y con qué etiquetas."""
from __future__ import annotations

import re

from .util import normalizar


def _patron(palabras: list[str]) -> re.Pattern:
    """Palabras cortas (<=5) exigen palabra completa; el resto admite sufijos (fotovoltaic -> fotovoltaicas)."""
    partes = []
    for p in palabras:
        p = normalizar(p)
        partes.append(rf"\b{re.escape(p)}\b" if len(p) <= 5 else rf"\b{re.escape(p)}")
    return re.compile("|".join(partes))


class Filtro:
    def __init__(self, config: dict):
        self.categorias = {
            k: {"etiqueta": v["etiqueta"], "fuerte": bool(v.get("fuerte", True)), "re": _patron(v["palabras"])}
            for k, v in config["categorias"].items()
        }
        self.exclusiones = [normalizar(p) for p in config.get("exclusiones", [])]
        self.clientes = {
            k: {"etiqueta": v["etiqueta"], "re": _patron(v["palabras"])}
            for k, v in config.get("clientes_ghc", {}).items()
        }
        # CPV -> categoria. Sin esto, el programa guardaba una licitacion por su CPV pero no la
        # etiquetaba (las etiquetas salian solo del titulo), y como el aviso exige etiqueta, nunca
        # avisaba: 1.172 de 3.430 licitaciones estaban guardadas y mudas. Un titulo como "sustitucion
        # del sistema de produccion de agua fria destinado a la climatizacion" no contiene ninguna
        # palabra clave, pero su CPV 45331230 dice exactamente lo que es.
        self.cpv_categorias = {
            str(pref): cat for pref, cat in (config.get("licitaciones", {}).get("cpv_categorias") or {}).items()
        }

    def categorias_de_cpv(self, cpvs: list[str] | None) -> list[str]:
        """Categorias implicadas por los codigos CPV, por prefijo y de mas especifico a mas general."""
        salida = []
        for c in cpvs or []:
            c = str(c).strip()
            for pref in sorted(self.cpv_categorias, key=len, reverse=True):
                if c.startswith(pref):
                    cat = self.cpv_categorias[pref]
                    if cat not in salida:
                        salida.append(cat)
                    break
        return salida

    def categorias_de(self, *textos: str | None) -> list[str]:
        """Devuelve las claves de categoría que aparecen en los textos (vacío = no relevante)."""
        t = normalizar(" ".join(x for x in textos if x))
        if not t:
            return []
        if any(ex in t for ex in self.exclusiones):
            return []
        cats = [k for k, c in self.categorias.items() if c["re"].search(t)]
        # Relevante solo si al menos una categoría "fuerte" coincide; las débiles solo etiquetan
        if not any(self.categorias[k]["fuerte"] for k in cats):
            return []
        return cats

    def clientes_de(self, *textos: str | None) -> list[str]:
        t = normalizar(" ".join(x for x in textos if x))
        return [k for k, c in self.clientes.items() if c["re"].search(t)]

    def etiqueta_categoria(self, clave: str) -> str:
        return self.categorias.get(clave, {}).get("etiqueta", clave)

    def etiqueta_cliente(self, clave: str) -> str:
        return self.clientes.get(clave, {}).get("etiqueta", clave)

    def es_relevante(self, *textos: str | None) -> bool:
        return bool(self.categorias_de(*textos))

    def puntuacion(self, *textos: str | None) -> int:
        """Número de categorías que coinciden — para ordenar por 'encaje'."""
        return len(self.categorias_de(*textos))
