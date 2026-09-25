"""Fuente BDNS / SNPSAP — API pública (sin clave).

Endpoints verificados (sept. 2026):
  GET {base}/convocatorias/busqueda   ?vpd=GE&descripcion=&descripcionTipoBusqueda=2&fechaDesde=dd/MM/yyyy
                                      &fechaHasta=dd/MM/yyyy&finalidad=13&tipoAdministracion=A
                                      &order=fechaRecepcion&direccion=desc&page=0&pageSize=200
  GET {base}/convocatorias            ?vpd=GE&numConv=921227          -> detalle
  GET {base}/convocatorias/documentos ?idDocumento=1499368            -> PDF
Ficha pública: https://www.infosubvenciones.es/bdnstrans/GE/es/convocatoria/{numConv}
"""
from __future__ import annotations

import io
import logging
import time
from datetime import date, timedelta

from ..util import fecha_es, http_get, normalizar, parse_fecha

log = logging.getLogger("rastreador.bdns")

FICHA = "https://www.infosubvenciones.es/bdnstrans/GE/es/convocatoria/{}"

NUTS_CCAA = {
    "ES11": "Galicia", "ES12": "Asturias", "ES13": "Cantabria", "ES21": "País Vasco", "ES22": "Navarra",
    "ES23": "La Rioja", "ES24": "Aragón", "ES30": "Comunidad de Madrid", "ES41": "Castilla y León",
    "ES42": "Castilla-La Mancha", "ES43": "Extremadura", "ES51": "Cataluña", "ES52": "Comunidad Valenciana",
    "ES53": "Baleares", "ES61": "Andalucía", "ES62": "Región de Murcia", "ES63": "Ceuta", "ES64": "Melilla",
    "ES70": "Canarias",
}
PALABRAS_CCAA = {
    "galicia": "Galicia", "xunta": "Galicia", "asturias": "Asturias", "cantabria": "Cantabria",
    "pais vasco": "País Vasco", "euskadi": "País Vasco", "navarra": "Navarra", "rioja": "La Rioja",
    "aragon": "Aragón", "madrid": "Comunidad de Madrid", "castilla y leon": "Castilla y León",
    "castilla-la mancha": "Castilla-La Mancha", "castilla la mancha": "Castilla-La Mancha",
    "extremadura": "Extremadura", "cataluna": "Cataluña", "catalunya": "Cataluña", "generalitat de catalunya": "Cataluña",
    "valenciana": "Comunidad Valenciana", "generalitat valenciana": "Comunidad Valenciana",
    "illes balears": "Baleares", "baleares": "Baleares", "andalucia": "Andalucía", "murcia": "Región de Murcia",
    "ceuta": "Ceuta", "melilla": "Melilla", "canarias": "Canarias",
}
AMBITO = {"ESTADO": "Estado", "AUTONOMICA": "CCAA", "AUTONÓMICA": "CCAA", "LOCAL": "Local", "OTROS": "Otros"}


def _iso(valor) -> str | None:
    f = parse_fecha(valor)
    return f.isoformat() if f else None


def detectar_ccaa(*textos: str | None, regiones: list[str] | None = None) -> str | None:
    for r in regiones or []:
        cod = (r or "").split(" ")[0].strip()
        for pref, nombre in NUTS_CCAA.items():
            if cod.startswith(pref):
                return nombre
    t = normalizar(" ".join(x for x in textos if x))
    for palabra, nombre in PALABRAS_CCAA.items():
        if palabra in t:
            return nombre
    return None


class BDNS:
    def __init__(self, cfg: dict):
        self.base = cfg["base_url"].rstrip("/")
        self.cfg = cfg
        self.pausa = float(cfg.get("pausa_segundos", 0.6))

    # ------------------------------------------------------------- búsqueda
    def _buscar(self, params: dict) -> list[dict]:
        resultados, page = [], 0
        while True:
            p = {"vpd": "GE", "order": "fechaRecepcion", "direccion": "desc", "page": page,
                 "pageSize": self.cfg.get("page_size", 200), **params}
            r = http_get(f"{self.base}/convocatorias/busqueda", params=p, headers={"Accept": "application/json"})
            if r is None or r.status_code != 200:
                log.warning("Búsqueda BDNS sin respuesta (%s)", params)
                break
            try:
                datos = r.json()
            except ValueError:
                log.warning("Respuesta BDNS no JSON")
                break
            if "codigo" in datos and "content" not in datos:
                log.warning("Error BDNS: %s", datos)
                break
            resultados.extend(datos.get("content", []))
            if datos.get("last", True):
                break
            page += 1
            time.sleep(self.pausa)
        return resultados

    def buscar_periodo(self, desde: date, hasta: date) -> dict[str, dict]:
        """Une la consulta por finalidad (Industria y Energía) y la de texto libre. Devuelve {numConv: item}.

        Los periodos largos (carga histórica) se trocean: la BDNS responde mal a ventanas de cientos de días."""
        dias_trozo = int(self.cfg.get("dias_por_consulta", 45))
        if (hasta - desde).days > dias_trozo:
            union: dict[str, dict] = {}
            ini = desde
            n_trozos = ((hasta - desde).days // dias_trozo) + 1
            for i in range(n_trozos):
                fin = min(ini + timedelta(days=dias_trozo - 1), hasta)
                log.info("BDNS histórico, tramo %d/%d: %s → %s", i + 1, n_trozos, ini, fin)
                union.update(self._buscar_tramo(ini, fin))
                ini = fin + timedelta(days=1)
                if ini > hasta:
                    break
            log.info("BDNS %s → %s: %d convocatorias candidatas (histórico)", desde, hasta, len(union))
            return union
        return self._buscar_tramo(desde, hasta)

    def _buscar_tramo(self, desde: date, hasta: date) -> dict[str, dict]:
        base = {"fechaDesde": fecha_es(desde), "fechaHasta": fecha_es(hasta)}
        encontrados: dict[str, dict] = {}
        tipos = self.cfg.get("tipos_administracion") or [None]
        for tipo in tipos:
            extra = {"tipoAdministracion": tipo} if tipo else {}
            for fin in self.cfg.get("finalidades", []):
                for it in self._buscar({**base, **extra, "finalidad": fin}):
                    encontrados[it["numeroConvocatoria"]] = it
                time.sleep(self.pausa)
            texto = self.cfg.get("texto_libre")
            if texto:
                for it in self._buscar({**base, **extra, "descripcion": texto, "descripcionTipoBusqueda": 2}):
                    encontrados[it["numeroConvocatoria"]] = it
                time.sleep(self.pausa)
        log.info("BDNS %s → %s: %d convocatorias candidatas", desde, hasta, len(encontrados))
        return encontrados

    # -------------------------------------------------------------- detalle
    def detalle(self, num_conv: str) -> dict | None:
        r = http_get(f"{self.base}/convocatorias", params={"vpd": "GE", "numConv": num_conv},
                     headers={"Accept": "application/json"})
        if r is None or r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def descargar_pdf_texto(self, detalle: dict, max_chars: int) -> str:
        """Descarga el primer documento PDF de la convocatoria y extrae su texto (pypdf)."""
        docs = detalle.get("documentos") or []
        if not docs:
            return ""
        # Preferir el texto en castellano de la convocatoria
        def _prioridad(d: dict) -> tuple:
            desc = normalizar(d.get("descripcion")) + " " + normalizar(d.get("nombreFic"))
            return (
                0 if any(k in desc for k in ("bases reguladoras", "bases", "convocatoria", "extracto")) else 1,
                0 if "castellano" in desc else 1,
                0 if (d.get("nombreFic") or "").lower().endswith(".pdf") else 1,
                -(d.get("tamanio") or 0),
            )
        docs = sorted(docs, key=_prioridad)
        for d in docs[:3]:
            r = http_get(f"{self.base}/convocatorias/documentos", params={"idDocumento": d["id"]}, timeout=90)
            if r is None or r.status_code != 200 or not r.content:
                continue
            try:
                from pypdf import PdfReader
                lector = PdfReader(io.BytesIO(r.content))
                texto = "\n".join((pag.extract_text() or "") for pag in lector.pages[:250])
                if len(texto.strip()) > 200:
                    return texto[:max_chars]
            except Exception as e:  # noqa: BLE001
                log.debug("No se pudo leer PDF %s: %s", d.get("nombreFic"), e)
        return ""

    # ------------------------------------------------------- normalización
    @staticmethod
    def a_registro(item: dict, det: dict | None) -> dict:
        det = det or {}
        organo = det.get("organo") or {}
        nivel1 = organo.get("nivel1") or item.get("nivel1") or ""
        nivel2 = organo.get("nivel2") or item.get("nivel2") or ""
        nivel3 = organo.get("nivel3") or item.get("nivel3") or ""
        regiones = [r.get("descripcion", "") for r in det.get("regiones") or []]
        beneficiarios = [b.get("descripcion", "").strip() for b in det.get("tiposBeneficiarios") or []]
        instrumentos = ", ".join(i.get("descripcion", "").strip() for i in det.get("instrumentos") or [])
        titulo = item.get("descripcion") or det.get("descripcion") or ""
        ambito = AMBITO.get(normalizar(nivel1).upper(), nivel1.title() or None)
        ccaa = detectar_ccaa(nivel2, nivel3, regiones=regiones)
        if ambito == "Estado" and not ccaa:
            ccaa = "Nacional"
        return {
            "id_bdns": str(item.get("numeroConvocatoria") or det.get("codigoBDNS")),
            "fuente": "bdns",
            "titulo": titulo.strip(),
            "organo": " · ".join(x for x in (nivel2, nivel3) if x and x != nivel2) or nivel2,
            "ambito": ambito,
            "ccaa": ccaa,
            "fecha_publicacion": (parse_fecha(item.get("fechaRecepcion") or det.get("fechaRecepcion")) or date.today()).isoformat(),
            "fecha_inicio": _iso(det.get("fechaInicioSolicitud")),
            "fecha_fin": _iso(det.get("fechaFinSolicitud")),
            "texto_inicio": det.get("textInicio"),
            "texto_fin": det.get("textFin"),
            "abierto": None if det.get("abierto") is None else int(bool(det.get("abierto"))),
            "presupuesto": det.get("presupuestoTotal"),
            "beneficiarios": beneficiarios,
            "instrumentos": instrumentos,
            "finalidad": det.get("descripcionFinalidad"),
            "regiones": regiones,
            "mrr": int(bool(item.get("mrr") or det.get("mrr"))),
            "url_ficha": FICHA.format(item.get("numeroConvocatoria") or det.get("codigoBDNS")),
            "url_bases": det.get("urlBasesReguladoras"),
            "url_sede": det.get("sedeElectronica"),
            "detalle_json": None,
        }
