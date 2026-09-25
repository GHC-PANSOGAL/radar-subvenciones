"""Interpretación del plazo de presentación cuando la BDNS no da una fecha de fin estructurada.

El problema que resuelve: en la BDNS, cuatro de cada diez convocatorias llegan con ``fecha_fin`` vacía
y el plazo escrito en prosa en ``texto_fin``: "A LOS CUATRO MESES DE SU PUBLICACIÓN", "20 DÍAS HÁBILES
A PARTIR DEL SIGUIENTE A LA PUBLICACIÓN DEL EXTRACTO", "HASTA EL 30 DE SEPTIEMBRE DE 2026". Hasta ahora
el panel las daba por CERRADAS a los 60 días de publicarse, sin mirar ese texto. Resultado: convocatorias
abiertas desaparecían del filtro "Solo abiertas" semanas antes de vencer.

Aquí se traduce ese texto a una fecha. Tres resultados posibles:

* ``exacta``   — el texto dice una fecha concreta (31/10/2025, "30 de septiembre de 2026").
* ``estimada`` — el texto da un plazo relativo a la publicación (meses, días hábiles, días naturales).
                 Se calcula sobre ``fecha_publicacion``; los días hábiles descuentan sábados y domingos,
                 no los festivos (no merece la pena arrastrar el calendario laboral de cada municipio:
                 el error es de días y siempre en el lado conservador, nunca alarga el plazo).
* ``sin_plazo``— convocatorias sin plazo cerrado: concesión directa, convenios nominativos, "hasta agotar
                 crédito". No se pueden dar por cerradas por antigüedad, pero tampoco son "abiertas" en el
                 sentido de que se pueda presentar una solicitud: el panel las marca "plazo por confirmar".

La fecha estimada NO se escribe en la base: se recalcula al generar el panel. Así, el día que la BDNS
rellene la fecha real, manda la real sin tener que limpiar nada.
"""
from __future__ import annotations

import datetime
import re
import unicodedata

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    # gallego
    "xaneiro": 1, "febreiro": 2, "maio": 5, "xuno": 6, "xullo": 7, "decembro": 12,
    # catalán / valenciano
    "gener": 1, "febrer": 2, "marc": 3, "maig": 5, "juny": 6, "juliol": 7, "agost": 8,
    "setembre": 9, "novembre": 11, "desembre": 12,
}

NUM = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "catro": 4, "quatre": 4,
    "cinco": 5, "cinc": 5, "seis": 6, "sis": 6, "siete": 7, "set": 7, "ocho": 8, "vuit": 8,
    "nueve": 9, "nou": 9, "diez": 10, "deu": 10, "once": 11, "doce": 12, "quince": 15, "quinze": 15,
    "veinte": 20, "vint": 20, "treinta": 30, "trenta": 30, "cuarenta": 40, "corenta": 40,
    "quaranta": 40, "sesenta": 60, "seixanta": 60,
}

# Plazos que no vencen por calendario: concesión directa, convenios, "hasta agotar crédito".
SIN_PLAZO = (
    "sin plazo", "agote", "agotar", "esgot", "hasta que se declare", "hasta el traslado",
    "abierto permanente", "permanentemente abierto", "no procede", "concesion directa",
)

DIAS_MES = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def _habiles(inicio: datetime.date, n: int) -> datetime.date:
    """Suma n días hábiles (lunes a viernes). No descuenta festivos: se queda corto, nunca largo."""
    d, quedan = inicio, n
    while quedan > 0:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:
            quedan -= 1
    return d


def _bisiesto(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def _sumar_meses(f: datetime.date, n: int) -> datetime.date:
    m = f.month - 1 + n
    y, m = f.year + m // 12, m % 12 + 1
    tope = 29 if (m == 2 and _bisiesto(y)) else DIAS_MES[m - 1]
    return datetime.date(y, m, min(f.day, tope))


def interpretar_fin(texto: str | None, publicacion: datetime.date | None) -> tuple[datetime.date | None, str]:
    """Devuelve (fecha_fin, tipo). tipo: exacta | estimada | sin_plazo | desconocida."""
    t = _norm(texto)
    if not t:
        return None, "desconocida"

    # "hasta el 31 de diciembre de 2025, o bien hasta el agotamiento del crédito": manda la fecha.
    # Se mira antes que SIN_PLAZO, si no el "agotamiento" se comería una fecha perfectamente válida.
    m = re.search(r"hasta\s+(?:el\s+)?(\d{1,2})\s+de\s+([a-z]+)\s+de[l]?\s+(\d{4})", t)
    if m and m[2] in MESES:
        try:
            return datetime.date(int(m[3]), MESES[m[2]], int(m[1])), "exacta"
        except ValueError:
            pass

    if any(k in t for k in SIN_PLAZO):
        return None, "sin_plazo"

    # dd/mm/aaaa
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", t)
    if m:
        try:
            return datetime.date(int(m[3]), int(m[2]), int(m[1])), "exacta"
        except ValueError:
            pass

    # "30 de septiembre de 2026" / "once de octubre de dos mil veintiséis"
    m = re.search(r"\b(\d{1,2}|[a-z]+)\s+de\s+([a-z]+)\s+de[l]?\s+(dos mil [a-z]+|\d{4})\b", t)
    if m and m[2] in MESES:
        dia = int(m[1]) if m[1].isdigit() else NUM.get(m[1], 0)
        anio = int(m[3]) if m[3].isdigit() else _anio_letras(m[3])
        if dia and anio:
            try:
                return datetime.date(anio, MESES[m[2]], dia), "exacta"
            except ValueError:
                pass

    if not publicacion:
        return None, "desconocida"

    # plazo relativo a la publicación
    m = re.search(r"\b(\d{1,3}|[a-z]+)\s+(mes[oe]?s?|dias?|dies|jornadas)\b", t)
    if m:
        n = int(m[1]) if m[1].isdigit() else NUM.get(m[1], 0)
        if n:
            if m[2].startswith("mes"):
                return _sumar_meses(publicacion, n), "estimada"
            if "habil" in t or "habils" in t or "laborable" in t:
                return _habiles(publicacion, n), "estimada"
            return publicacion + datetime.timedelta(days=n), "estimada"

    # "un mes", "el mismo día en que se produjo la publicación del mes siguiente"
    if re.search(r"\bmes siguiente\b", t):
        return _sumar_meses(publicacion, 1), "estimada"
    if re.search(r"\bdos meses despues\b|\bdos meses mas tarde\b", t):
        return _sumar_meses(publicacion, 2), "estimada"

    return None, "desconocida"


def _anio_letras(t: str) -> int:
    """'dos mil veintiséis' -> 2026. Solo cubre 2020-2039, que es todo lo que va a aparecer."""
    t = t.replace("dos mil", "").strip()
    if not t:
        return 2000
    directo = NUM.get(t)
    if directo:
        return 2000 + directo
    m = re.match(r"(veinti|treinta y |veinte|treinta)\s*([a-z]*)", t)
    if not m:
        return 0
    base = 20 if m[1].startswith("vein") else 30
    return 2000 + base + NUM.get(m[2], 0)
