"""Generación del panel web acumulado (HTML autocontenido, sin servidor ni dependencias)."""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__
from . import avisos, clasificacion
from .db import DB
from .filtro import Filtro
from .geo import localizar
from .plazos import interpretar_fin
from .util import RAIZ, cargar_organismos, hoy, parse_fecha


def _logo(nombre: str) -> str:
    ruta = RAIZ / "assets" / f"logo-{nombre}-small.png"
    if not ruta.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(ruta.read_bytes()).decode()

PLANTILLA = Path(__file__).with_name("panel_plantilla.html")
# Mapa base propio (provincias simplificadas): evita depender de servidores de teselas externos
GEOJSON = RAIZ / "assets" / "es-provincias.json"


def estado_convocatoria(c: dict, dias_sin_fecha: int) -> str:
    """abierta | proxima | plazo_por_confirmar | cerrada

    Cuando la BDNS no da `fecha_fin` (pasa en ~4 de cada 10), antes se daba la convocatoria por cerrada
    a los `dias_sin_fecha` de publicarse sin leer `texto_fin`. Eso escondía convocatorias abiertas.
    Ahora se interpreta ese texto (ver rastreador/plazos.py) y solo se recurre a la antigüedad si de ahí
    no sale nada. La fecha deducida queda en c["fecha_fin_estimada"] para que el panel la enseñe.
    """
    h = hoy()
    ini, fin = parse_fecha(c.get("fecha_inicio")), parse_fecha(c.get("fecha_fin"))
    if ini and ini > h:
        return "proxima"
    if fin:
        return "abierta" if fin >= h else "cerrada"

    deducida, tipo = interpretar_fin(c.get("texto_fin"), parse_fecha(c.get("fecha_publicacion")))
    c["fin_tipo"] = tipo
    if deducida:
        c["fecha_fin_estimada"] = deducida.isoformat()
        return "abierta" if deducida >= h else "cerrada"
    if tipo == "sin_plazo":
        # Concesión directa, convenios, "hasta agotar crédito": no vencen por calendario, pero tampoco
        # son una convocatoria a la que uno pueda presentarse. Ni abierta ni cerrada.
        return "plazo_por_confirmar"

    if c.get("abierto") == 1:
        return "abierta"
    pub = parse_fecha(c.get("fecha_publicacion")) or h
    return "plazo_por_confirmar" if (h - pub).days <= dias_sin_fecha else "cerrada"


def _version_disponible(cfg: dict) -> str | None:
    """Versión que hay en la carpeta de OneDrive de donde se instala.

    El programa se ejecuta desde una copia en %LOCALAPPDATA%, así que dejar ficheros nuevos en OneDrive
    NO actualiza nada: hay que volver a pasar INSTALAR.bat. Esto lo detecta y el panel lo avisa, que si no
    uno se queda con una versión vieja sin enterarse.
    """
    comp = (cfg.get("general") or {}).get("carpeta_compartida") or ""
    if not comp or "${" in comp or "%" in comp:
        return None
    try:
        init = Path(comp).parent / "rastreador" / "__init__.py"
        m = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"))
        return m.group(1) if m else None
    except OSError:
        return None


def _mas_nueva(a: str, b: str) -> bool:
    """¿a es posterior a b? Comparación por partes numéricas."""
    try:
        return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))
    except (ValueError, AttributeError):
        return False


def generar(db: DB, cfg: dict, destino: Path, publico: bool = False) -> Path:
    """Genera el panel. Con publico=True, el que se sube a internet: SIN datos de personas.

    Motivo: el panel lleva los datos incrustados dentro del propio HTML, y entre ellos iba la tabla de
    suscripciones —correo, nombre y qué CCAA vigila cada uno—. El panel se publica en GitHub Pages, que
    es una web pública. O sea: los correos de la plantilla estaban publicados en internet, indexables y
    raspables. Las convocatorias son información pública y da igual que se vean; los correos de las
    personas no lo son.
    """
    filtro = Filtro(cfg)
    dias = cfg["general"].get("dias_vigencia_sin_fecha", 60)
    convs = db.todas_convocatorias()
    for c in convs:
        c["estado"] = estado_convocatoria(c, dias)
        c["categorias_txt"] = [filtro.etiqueta_categoria(k) for k in (c.get("categorias") or [])]
        c["clientes_txt"] = [filtro.etiqueta_cliente(k) for k in (c.get("clientes") or [])]
        c["puntuacion"] = len(c.get("categorias") or []) + len(c.get("clientes") or [])
        c["geo"] = localizar(c.get("regiones") or [], c.get("ccaa"))
    lics = db.todas_licitaciones()
    h = hoy().isoformat()
    for l in lics:
        l["estado_panel"] = "abierta" if (not l.get("fecha_limite") or l["fecha_limite"] >= h) else "cerrada"
        l["categorias_txt"] = [filtro.etiqueta_categoria(k) for k in (l.get("categorias") or [])]
        l["clientes_txt"] = [filtro.etiqueta_cliente(k) for k in (l.get("clientes") or [])]
        l["puntuacion"] = len(l.get("categorias") or []) + len(l.get("clientes") or [])
        l["geo"] = localizar([l.get("nuts") or ""], l.get("ccaa"))
        # lo que venga del anuncio se respeta; lo inferido se recalcula en cada panel para que las
        # licitaciones guardadas antes también lo tengan y se beneficien de las mejoras en las reglas
        cl = l.get("clasificacion")
        if not (isinstance(cl, dict) and cl.get("certeza") == "anuncio"):
            l["clasificacion"] = clasificacion.analizar(l)
    noticias = db.todas_noticias()
    for n in noticias:
        n["categorias_txt"] = [filtro.etiqueta_categoria(k) for k in (n.get("categorias") or [])]
    datos = {
        "generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "version": __version__,
        "version_disponible": (lambda v: v if v and _mas_nueva(v, __version__) else None)(_version_disponible(cfg)),
        "convocatorias": convs,
        "licitaciones": lics,
        "logos": {"ghc": _logo("ghc"), "pansogal": _logo("pansogal")},
        "noticias": noticias,
        "organismos": cargar_organismos(),
        "ejecuciones": [] if publico else db.ultimas_ejecuciones(15),
        # datos de personas: solo en el panel interno (OneDrive), nunca en el que se sube a internet
        "suscripciones": [] if publico else avisos.listar(db),
        "publico": publico,
        "categorias": {k: v["etiqueta"] for k, v in filtro.categorias.items()},
        "clientes": {k: v["etiqueta"] for k, v in filtro.clientes.items()},
        "kpis": {
            "abiertas": sum(1 for c in convs if c["estado"] == "abierta"),
            "por_confirmar": sum(1 for c in convs if c["estado"] == "plazo_por_confirmar"),
            "proximas": sum(1 for c in convs if c["estado"] == "proxima"),
            "licitaciones_abiertas": sum(1 for l in lics if l["estado_panel"] == "abierta"),
            "licitaciones_nuevas_7d": sum(1 for l in lics if (parse_fecha(l.get("creado")) or hoy()) >= hoy() - timedelta(days=7)),
            "nuevas_7d": sum(1 for c in convs if (parse_fecha(c.get("fecha_publicacion")) or hoy()) >= hoy() - timedelta(days=7)),
            "noticias_7d": sum(1 for n in noticias if (parse_fecha(n.get("fecha")) or parse_fecha(n.get("creado")) or hoy()) >= hoy() - timedelta(days=7)),
        },
    }
    geo_txt = GEOJSON.read_text(encoding="utf-8").replace("</", "<\\/") if GEOJSON.exists() else "null"
    html = PLANTILLA.read_text(encoding="utf-8").replace(
        "/*__DATOS__*/null", json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")).replace(
        "/*__GEO__*/null", geo_txt)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html, encoding="utf-8")
    # copia de los datos en JSON por si se quiere consumir desde otra herramienta
    destino.with_name("datos.json").write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return destino
