"""¿La licitación exige clasificación del contratista? ¿Y cuál?

Dos vías, en este orden:

1. **Lo que diga el anuncio** (`origen = "anuncio"`). Los feeds CODICE de la PLACSP pueden traer la
   clasificación exigida en `cac:TenderingTerms` (esquemas de clasificación empresarial o requisitos
   específicos del licitador). Cuando viene, es el dato bueno.
2. **Inferencia legal** (`origen = "inferido"`) cuando el anuncio no la trae, que es lo habitual:
   la clasificación se detalla en el PCAP, no en el anuncio estructurado.

   * Art. 77.1.a) LCSP 9/2017: en **contratos de obras con valor estimado ≥ 500.000 €** es requisito
     indispensable estar clasificado. Por debajo de ese umbral no es exigible (puede acreditarse
     solvencia por otros medios, y el licitador puede usar la clasificación para acreditarla).
   * Art. 77.1.b) LCSP: en **contratos de servicios NO es exigible** la clasificación (sirve para
     acreditar solvencia si se tiene).
   * En **suministros** tampoco es exigible.

   El grupo y subgrupo se proponen a partir del CPV y del texto (RD 1098/2001, art. 25) y la categoría
   a partir de la anualidad media (RD 1098/2001, art. 26, redacción vigente: 1 ≤ 150.000 €;
   2 ≤ 360.000; 3 ≤ 840.000; 4 ≤ 2.400.000; 5 ≤ 5.000.000; 6 > 5.000.000).

AVISO: la inferencia es orientativa. Manda siempre el pliego (PCAP).
"""
from __future__ import annotations

import re

from .util import normalizar

# ------------------------------------------------------------------ subgrupos RD 1098/2001 art. 25
SUBGRUPOS = {
    "C-4": "Albañilería, revocos y revestidos",
    "C-6": "Pavimentos, solados y alicatados",
    "C-7": "Aislamientos e impermeabilizaciones",
    "C-8": "Carpintería de madera",
    "C-9": "Carpintería metálica",
    "I-1": "Alumbrado, iluminaciones y balizamientos luminosos",
    "I-2": "Centrales de producción de energía",
    "I-5": "Centros de transformación y distribución en alta tensión",
    "I-6": "Distribución en baja tensión",
    "I-9": "Instalaciones eléctricas sin cualificación específica",
    "J-2": "Instalaciones de ventilación, calefacción y climatización",
    "J-4": "Instalaciones de fontanería y sanitarias",
    "J-5": "Instalaciones mecánicas sin cualificación específica",
    "K-9": "Instalaciones contra incendios",
}

# Palabras del objeto del contrato → subgrupo propuesto. Orden = prioridad.
REGLAS = [
    (["sate", "aislamiento termico", "envolvente termica", "impermeabiliz", "fachada ventilada", "cubierta invertida"], "C-7"),
    (["ventana", "carpinteria de aluminio", "carpinteria metalica", "cerrajeria"], "C-9"),
    (["carpinteria de madera"], "C-8"),
    (["rehabilitacion energetica", "rehabilitacion de fachada", "albañileria", "revoco", "revestimiento"], "C-4"),
    (["aerotermia", "geotermia", "bomba de calor", "climatizacion", "calefaccion", "caldera", "ventilacion",
      "sala de calderas", "district heating", "red de calor"], "J-2"),
    (["fotovoltaic", "autoconsumo", "placas solares", "solar termica", "planta solar", "huerto solar"], "I-2"),
    (["bateria", "almacenamiento energetico", "bess", "acumulacion electrica"], "I-9"),
    (["centro de transformacion", "alta tension", "subestacion"], "I-5"),
    (["alumbrado", "luminaria", "iluminacion"], "I-1"),
    (["baja tension", "instalacion electrica", "cuadro electrico", "linea electrica"], "I-9"),
    (["fontaneria", "acs", "agua caliente sanitaria", "saneamiento"], "J-4"),
    (["contra incendios", "pci", "deteccion de incendios"], "K-9"),
]

# CPV → subgrupo (prefijos). Complementa a las palabras clave.
CPV_SUBGRUPO = [
    ("09331", "I-2"), ("09332", "I-2"), ("45261215", "I-2"), ("31712331", "I-2"),
    ("3140", "I-9"), ("3142", "I-9"), ("3143", "I-9"), ("3144", "I-9"),
    ("4251111", "J-2"), ("4253300", "J-2"), ("45331", "J-2"), ("4216", "J-2"), ("44621", "J-2"),
    ("45251141", "J-2"),
    ("4532", "C-7"), ("45321", "C-7"), ("45261", "C-7"),
    ("4542", "C-9"), ("44221", "C-9"),
    ("45315", "I-9"), ("45311", "I-9"), ("45316", "I-1"),
    ("45332", "J-4"),
]

UMBRAL_OBRAS = 500_000.0          # art. 77.1.a) LCSP 9/2017
CATEGORIAS = [(150_000, "1"), (360_000, "2"), (840_000, "3"), (2_400_000, "4"), (5_000_000, "5")]

# "Grupo C, Subgrupo 4, Categoría 3" y variantes que aparecen en los textos de los anuncios
PATRON_TEXTO = re.compile(
    r"grupo\s*:?\s*([A-K])\b[^A-Za-z0-9]{0,20}(?:subgrupo\s*:?\s*(\d{1,2}))?[^A-Za-z0-9]{0,20}"
    r"(?:categor[ií]a\s*:?\s*([1-6]|[a-fA-F])\b)?",
    re.IGNORECASE)


def _meses(duracion: str | None) -> float | None:
    """Convierte '24 meses' / '2 años' / '540 días' a meses."""
    if not duracion:
        return None
    t = normalizar(duracion)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(mes|año|ano|dia)", t)
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    return {"mes": n, "año": n * 12, "ano": n * 12, "dia": n / 30.4}[m.group(2)]


def categoria_por_anualidad(valor: float | None, duracion: str | None) -> tuple[str | None, float | None]:
    """Devuelve (categoría, anualidad media). La categoría va por anualidad media, no por importe total."""
    if not valor:
        return None, None
    meses = _meses(duracion) or 12.0
    anualidad = valor / max(meses / 12.0, 1.0)     # < 1 año ⇒ la anualidad es el propio importe
    for tope, cat in CATEGORIAS:
        if anualidad <= tope:
            return cat, anualidad
    return "6", anualidad


def subgrupos_probables(titulo: str | None, cpvs: list[str] | None, organo: str | None = None) -> list[str]:
    encontrados: list[str] = []
    for pref, sg in CPV_SUBGRUPO:
        if any((c or "").startswith(pref) for c in cpvs or []) and sg not in encontrados:
            encontrados.append(sg)
    t = normalizar(" ".join(x for x in (titulo, organo) if x))
    for palabras, sg in REGLAS:
        if any(p in t for p in palabras) and sg not in encontrados:
            encontrados.append(sg)
    return encontrados[:3]


def _del_anuncio(lic: dict) -> dict | None:
    """Clasificación tal y como venga en el anuncio (campos crudos extraídos por placsp.py)."""
    crudo = " · ".join(x for x in (lic.get("clasificacion_txt") or []) if x).strip()
    if not crudo:
        return None
    m = PATRON_TEXTO.search(crudo)
    codigos = []
    if m:
        grupo, sub, cat = m.group(1).upper(), m.group(2), m.group(3)
        codigos = [f"{grupo}-{sub}" if sub else grupo]
    return {
        "exigida": True,
        "certeza": "anuncio",
        "codigos": codigos,
        "categoria": (m.group(3).upper() if m and m.group(3) else None),
        "texto": crudo[:400],
        "motivo": "La clasificación viene indicada en el propio anuncio de licitación.",
    }


def analizar(lic: dict) -> dict:
    """Devuelve el bloque de clasificación de una licitación."""
    del_anuncio = _del_anuncio(lic)
    if del_anuncio:
        if not del_anuncio["codigos"]:
            del_anuncio["codigos"] = subgrupos_probables(lic.get("titulo"), lic.get("cpv"), lic.get("organo"))
            del_anuncio["motivo"] += " El grupo/subgrupo concreto no se ha podido leer: los mostrados son una propuesta."
        del_anuncio["descripciones"] = [SUBGRUPOS.get(c, "") for c in del_anuncio["codigos"]]
        return del_anuncio

    tipo = normalizar(lic.get("tipo"))
    valor = lic.get("valor_estimado") or lic.get("presupuesto_sin_iva")
    cat, anualidad = categoria_por_anualidad(valor, lic.get("duracion"))

    if "obra" in tipo:
        if valor and valor >= UMBRAL_OBRAS:
            codigos = subgrupos_probables(lic.get("titulo"), lic.get("cpv"), lic.get("organo"))
            return {
                "exigida": True, "certeza": "inferido", "codigos": codigos,
                "descripciones": [SUBGRUPOS.get(c, "") for c in codigos], "categoria": cat,
                "anualidad_media": anualidad,
                "texto": None,
                "motivo": (f"Contrato de obras con valor estimado {valor:,.0f} € ≥ 500.000 €: la clasificación es "
                           f"requisito indispensable (art. 77.1.a LCSP). Categoría {cat} por anualidad media de "
                           f"{anualidad:,.0f} €.").replace(",", "."),
            }
        if valor:
            return {
                "exigida": False, "certeza": "inferido", "codigos": [], "descripciones": [],
                "categoria": None, "anualidad_media": anualidad, "texto": None,
                "motivo": (f"Contrato de obras con valor estimado {valor:,.0f} € < 500.000 €: no es exigible la "
                           "clasificación (art. 77.1.a LCSP). El órgano puede pedir solvencia por otros medios, y la "
                           "clasificación sirve para acreditarla.").replace(",", "."),
            }
    elif "servicio" in tipo:
        return {
            "exigida": False, "certeza": "inferido", "codigos": [], "descripciones": [],
            "categoria": None, "anualidad_media": anualidad, "texto": None,
            "motivo": "Contrato de servicios: la clasificación no es exigible (art. 77.1.b LCSP), aunque puede "
                      "presentarse para acreditar la solvencia.",
        }
    elif "suministro" in tipo:
        return {
            "exigida": False, "certeza": "inferido", "codigos": [], "descripciones": [],
            "categoria": None, "anualidad_media": anualidad, "texto": None,
            "motivo": "Contrato de suministros: la clasificación no es exigible; se acredita solvencia económica y técnica.",
        }

    return {
        "exigida": None, "certeza": "desconocido", "codigos": [], "descripciones": [],
        "categoria": None, "anualidad_media": anualidad, "texto": None,
        "motivo": "No hay datos suficientes en el anuncio (tipo de contrato o valor estimado) para determinarlo: "
                  "hay que mirar el PCAP.",
    }


def etiqueta(cl: dict | None) -> str:
    """Texto corto para la tabla del panel."""
    if not cl:
        return "—"
    if cl.get("exigida") is None:
        return "?"
    if not cl["exigida"]:
        return "No"
    codigos = "/".join(cl.get("codigos") or []) or "?"
    cat = cl.get("categoria")
    return f"Sí · {codigos}" + (f" · cat. {cat}" if cat else "")
