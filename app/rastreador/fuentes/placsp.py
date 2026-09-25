"""Licitaciones públicas — Plataforma de Contratación del Sector Público (PLACSP), feeds Atom CODICE.

Feeds (verificados 04/09/2026):
  https://contrataciondelestado.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom   (PLACSP)
  https://contrataciondelestado.es/sindicacion/sindicacion_1044/PlataformasAgregadasSinMenores.atom          (plataformas CCAA)
Cada página trae 130-500 entries (7-15 MB); link rel="next" va hacia atrás en el tiempo. Sin API de búsqueda.
Se parsea en streaming (iterparse) para no cargar 15 MB en memoria.
"""
from __future__ import annotations

import io
import logging
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime

import requests

from ..util import UA, normalizar

log = logging.getLogger("rastreador.placsp")

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cac-place-ext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbc-place-ext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}
ATOM = "{http://www.w3.org/2005/Atom}"
ESTADOS = {"PRE": "Anuncio previo", "PUB": "En plazo", "EV": "Pendiente de adjudicación", "ADJ": "Adjudicada",
           "RES": "Resuelta", "ANUL": "Anulada"}
TIPOS = {"1": "Suministros", "2": "Servicios", "3": "Obras", "21": "Gestión de servicios públicos",
         "22": "Concesión de servicios", "31": "Concesión de obras", "32": "Concesión de obras públicas",
         "40": "Colaboración público-privada", "7": "Administrativo especial", "8": "Privado", "50": "Patrimonial"}
PROCEDIMIENTOS = {"1": "Abierto", "2": "Restringido", "3": "Negociado sin publicidad", "4": "Negociado con publicidad",
                  "5": "Diálogo competitivo", "6": "Contrato menor", "7": "Basado en acuerdo marco", "8": "Concurso de proyectos",
                  "9": "Abierto simplificado", "10": "Asociación para la innovación", "11": "Asociación para la innovación",
                  "12": "Sistema dinámico de adquisición", "13": "Licitación con negociación", "100": "Normas internas",
                  "999": "Otros"}


# Etiquetas de CODICE donde puede venir la clasificación empresarial exigida. Se buscan por nombre local
# (sin espacio de nombres) porque la PLACSP no siempre usa el mismo prefijo.
CLAVES_CLASIF = ("BusinessClassification", "ClassificationScheme", "ClassificationCategory",
                 "TendererQualificationRequest", "SpecificTendererRequirement", "RequiredBusinessClassification")
# ItemClassificationCode es el CPV: no es clasificación del contratista
CLAVES_EXCLUIDAS = ("ItemClassificationCode",)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clasificacion_del_anuncio(cfs) -> list[str]:
    """Textos del anuncio relacionados con la clasificación exigida al contratista (puede venir vacío:
    lo normal es que la clasificación se detalle en el PCAP y no en el anuncio estructurado)."""
    if cfs is None:
        return []
    textos: list[str] = []
    dentro = False
    for el in cfs.iter():
        nombre = _local(el.tag)
        if nombre in CLAVES_EXCLUIDAS:
            continue
        pertinente = any(k in nombre for k in CLAVES_CLASIF)
        if pertinente:
            dentro = True
        if (pertinente or dentro) and el.text and el.text.strip():
            t = el.text.strip()
            if len(t) > 1 and t not in textos:
                textos.append(f"{nombre}: {t}" if not pertinente else t)
        if len(textos) >= 12:
            break
    return textos


def _t(el, ruta: str) -> str | None:
    x = el.find(ruta, NS) if el is not None else None
    return (x.text or "").strip() if x is not None and x.text else None


def _fecha(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:19]).date().isoformat()
    except ValueError:
        return s[:10]


class PLACSP:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.feeds = cfg.get("feeds", [])
        self.prefijos_cpv = [str(p) for p in cfg.get("cpv_prefijos", [])]
        self.estados = set(cfg.get("estados", ["PUB", "PRE"]))
        self.max_paginas = int(cfg.get("max_paginas", 6))
        # tope de tiempo para toda la etapa: cada página son 7-15 MB y el servidor es lento
        self.tiempo_max = float(cfg.get("tiempo_max_segundos", 240))

    # ---------------------------------------------------------------- red
    def _iter_entries(self, url: str):
        """Genera (entry_element) en streaming y devuelve al final la URL 'next' vía StopIteration.value."""
        siguiente = None
        try:
            with requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=(20, 180)) as r:
                if r.status_code != 200:
                    log.warning("PLACSP %s → HTTP %s", url, r.status_code)
                    return None
                r.raw.decode_content = True
                for evento, el in ET.iterparse(r.raw, events=("end",)):
                    if el.tag == ATOM + "entry":
                        yield el
                        el.clear()
                    elif el.tag == ATOM + "link" and el.get("rel") == "next":
                        siguiente = el.get("href")
        except (requests.RequestException, ET.ParseError) as e:
            log.warning("PLACSP fallo leyendo %s: %s", url, e)
        return siguiente

    # ------------------------------------------------------------ parseo
    def parsear(self, e) -> dict | None:
        cfs = e.find("cac-place-ext:ContractFolderStatus", NS)
        if cfs is None:
            return None
        pp = cfs.find("cac:ProcurementProject", NS)
        estado = _t(cfs, "cbc-place-ext:ContractFolderStatusCode")
        cpvs = [x.text.strip() for x in cfs.findall(".//cbc:ItemClassificationCode", NS) if x.text]
        lotes = cfs.findall("cac:ProcurementProjectLot", NS)
        loc = pp.find("cac:RealizedLocation", NS) if pp is not None else None
        if loc is None and lotes:
            loc = lotes[0].find("cac:ProcurementProject/cac:RealizedLocation", NS)
        docs = []
        for tag, nombre in (("cac:LegalDocumentReference", "Pliego administrativo (PCAP)"),
                            ("cac:TechnicalDocumentReference", "Pliego técnico (PPT)")):
            for d in cfs.findall(tag, NS):
                uri = _t(d, "cac:Attachment/cac:ExternalReference/cbc:URI")
                if uri:
                    docs.append({"nombre": nombre, "fichero": _t(d, "cbc:ID"), "url": uri})
        fondos = cfs.find("cac:TenderingTerms/cbc:FundingProgramCode", NS)
        enlace = e.find("atom:link", NS)
        return {
            "id": _t(e, "atom:id"),
            "titulo": _t(e, "atom:title") or _t(pp, "cbc:Name") or "",
            "expediente": _t(cfs, "cbc:ContractFolderID"),
            "organo": _t(cfs, "cac-place-ext:LocatedContractingParty/cac:Party/cac:PartyName/cbc:Name"),
            "organo_padre": _t(cfs, "cac-place-ext:LocatedContractingParty/cac-place-ext:ParentLocatedParty/cac:PartyName/cbc:Name"),
            "estado": estado,
            "estado_txt": ESTADOS.get(estado or "", estado),
            "tipo": TIPOS.get(_t(pp, "cbc:TypeCode") or "", _t(pp, "cbc:TypeCode")),
            "procedimiento": PROCEDIMIENTOS.get(_t(cfs, "cac:TenderingProcess/cbc:ProcedureCode") or "", None),
            "cpv": sorted(set(cpvs)),
            "presupuesto_sin_iva": _num(_t(pp, "cac:BudgetAmount/cbc:TaxExclusiveAmount")),
            "presupuesto_con_iva": _num(_t(pp, "cac:BudgetAmount/cbc:TotalAmount")),
            "valor_estimado": _num(_t(pp, "cac:BudgetAmount/cbc:EstimatedOverallContractAmount")),
            "fecha_limite": _t(cfs, "cac:TenderingProcess/cac:TenderSubmissionDeadlinePeriod/cbc:EndDate"),
            "hora_limite": _t(cfs, "cac:TenderingProcess/cac:TenderSubmissionDeadlinePeriod/cbc:EndTime"),
            "lugar": _t(loc, "cbc:CountrySubentity") if loc is not None else None,
            "nuts": _t(loc, "cbc:CountrySubentityCode") if loc is not None else None,
            "municipio": _t(loc, "cac:Address/cbc:CityName") if loc is not None else None,
            "duracion": _duracion(pp),
            "fondos_ue": (fondos.get("name") if fondos is not None else None) or _t(cfs, "cac:TenderingTerms/cbc:FundingProgramCode"),
            "n_lotes": len(lotes),
            "clasificacion_txt": clasificacion_del_anuncio(cfs),
            "url": enlace.get("href") if enlace is not None else None,
            "documentos": docs,
            "fecha_publicacion": _t(cfs, "cac-place-ext:ValidNoticeInfo/cac-place-ext:AdditionalPublicationStatus/"
                                          "cac-place-ext:AdditionalPublicationDocumentReference/cbc:IssueDate")
                                 or _fecha(_t(e, "atom:updated")),
            "actualizado": _fecha(_t(e, "atom:updated")),
        }

    def cpv_relevante(self, cpvs: list[str]) -> bool:
        return any(c.startswith(p) for c in cpvs for p in self.prefijos_cpv)

    # -------------------------------------------------------------- lectura
    def leer(self, desde: date, filtro_texto) -> list[dict]:
        """Recorre los feeds hacia atrás hasta `desde` o max_paginas. filtro_texto(titulo) -> bool."""
        salida, vistos = [], set()
        t0 = time.monotonic()
        for f in self.feeds:
            url, pagina = f["url"], 0
            while url and pagina < self.max_paginas:
                if time.monotonic() - t0 > self.tiempo_max:
                    log.warning("PLACSP: alcanzado el tope de %.0f s; se continúa en la siguiente ejecución.", self.tiempo_max)
                    return salida
                pagina += 1
                tp = time.monotonic()
                log.info("PLACSP %s pág.%d: descargando…", f["nombre"], pagina)
                gen = self._iter_entries(url)
                mas_antiguo, n = None, 0
                while True:
                    try:
                        e = next(gen)
                    except StopIteration as fin:
                        url = fin.value
                        break
                    n += 1
                    upd = _fecha(_t(e, "atom:updated"))
                    if upd and (mas_antiguo is None or upd < mas_antiguo):
                        mas_antiguo = upd
                    lic = self.parsear(e)
                    if not lic or not lic["id"] or lic["id"] in vistos:
                        continue
                    if lic["estado"] not in self.estados:
                        continue
                    if lic["fecha_limite"] and lic["fecha_limite"] < date.today().isoformat():
                        continue
                    texto = " ".join(x for x in (lic["titulo"], lic["organo"]) if x)
                    if not (self.cpv_relevante(lic["cpv"]) or filtro_texto(texto)):
                        continue
                    vistos.add(lic["id"])
                    lic["fuente"] = f["nombre"]
                    salida.append(lic)
                log.info("PLACSP %s pág.%d: %d entries en %.0f s (más antigua %s), relevantes acumuladas %d",
                         f["nombre"], pagina, n, time.monotonic()-tp, mas_antiguo, len(salida))
                if mas_antiguo and mas_antiguo < desde.isoformat():
                    break
        return salida


    # ------------------------------------------------------- histórico (ficheros agregados)
    def leer_historico(self, desde: date, filtro_texto) -> list[dict]:
        """Carga histórica de licitaciones a partir de los ficheros agregados anuales/mensuales que publica
        la PLACSP, si están disponibles.

        Los feeds Atom normales solo sirven para el día a día: van hacia atrás página a página (7-15 MB cada
        una, ~1 día por página), así que llegar a 2024 por ahí supondría descargar miles de páginas. La vía
        buena son los ficheros agregados; se prueban varios patrones de URL y se usa el primero que responda.
        Si ninguno responde, se avisa y no se hace nada (mejor eso que tirarse horas descargando)."""
        patrones = self.cfg.get("historico_urls") or []
        if not patrones:
            log.warning("No hay patrones de URL para el histórico de licitaciones (licitaciones.historico_urls).")
            return []
        salida, vistos = [], set()
        hoy_ = date.today()
        periodos = []
        y, m = desde.year, desde.month
        while (y, m) <= (hoy_.year, hoy_.month):
            periodos.append((y, m))
            m += 1
            if m > 12:
                y, m = y + 1, 1
        anios = sorted({y for y, _ in periodos})

        probados: set[str] = set()
        for patron in patrones:
            claves = [{"anio": a, "mes": ""} for a in anios] if "{mes}" not in patron else                      [{"anio": a, "mes": f"{mm:02d}"} for a, mm in periodos]
            encontrado_alguno = False
            for k in claves:
                url = patron.format(anio=k["anio"], mes=k["mes"])
                if url in probados:
                    continue
                probados.add(url)
                n = self._leer_zip(url, desde, filtro_texto, salida, vistos)
                if n is not None:
                    encontrado_alguno = True
            if encontrado_alguno:
                break
        if not salida:
            log.warning("El histórico de licitaciones no ha devuelto nada: revisa licitaciones.historico_urls "
                        "(las URL de los ficheros agregados de la PLACSP cambian de sitio con el tiempo).")
        return salida

    def _leer_zip(self, url: str, desde: date, filtro_texto, salida: list, vistos: set) -> int | None:
        """Descarga un ZIP agregado y procesa los .atom que contenga. None si la URL no existe."""
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=(20, 600))
            if r.status_code != 200 or not r.content:
                log.info("Histórico PLACSP: %s → HTTP %s", url, r.status_code)
                return None
        except requests.RequestException as e:
            log.info("Histórico PLACSP: %s no accesible (%s)", url, e)
            return None
        n0 = len(salida)
        try:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                nombres = [x for x in z.namelist() if x.lower().endswith((".atom", ".xml"))]
                log.info("Histórico PLACSP: %s → %d ficheros (%.1f MB)", url, len(nombres), len(r.content)/1e6)
                for nombre in nombres:
                    with z.open(nombre) as f:
                        self._procesar_atom(f, desde, filtro_texto, salida, vistos, url)
        except zipfile.BadZipFile:
            log.info("Histórico PLACSP: %s no es un ZIP", url)
            return None
        log.info("Histórico PLACSP: %s → %d licitaciones relevantes", url, len(salida) - n0)
        return len(salida) - n0

    def _procesar_atom(self, flujo, desde: date, filtro_texto, salida: list, vistos: set, origen: str) -> None:
        try:
            for _, el in ET.iterparse(flujo, events=("end",)):
                if el.tag != ATOM + "entry":
                    continue
                upd = _fecha(_t(el, "atom:updated"))
                lic = self.parsear(el)
                el.clear()
                if not lic or not lic["id"] or lic["id"] in vistos:
                    continue
                if upd and upd < desde.isoformat():
                    continue
                texto = " ".join(x for x in (lic["titulo"], lic["organo"]) if x)
                if not (self.cpv_relevante(lic["cpv"]) or filtro_texto(texto)):
                    continue
                vistos.add(lic["id"])
                lic["fuente"] = "PLACSP histórico"
                salida.append(lic)
        except ET.ParseError as e:
            log.warning("Histórico PLACSP: XML ilegible en %s (%s)", origen, e)


def _num(s: str | None) -> float | None:
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _duracion(pp) -> str | None:
    if pp is None:
        return None
    d = pp.find("cac:PlannedPeriod/cbc:DurationMeasure", NS)
    if d is not None and d.text:
        unidad = {"MON": "meses", "DAY": "días", "ANN": "años", "YEA": "años"}.get(d.get("unitCode", ""), d.get("unitCode", ""))
        return f"{d.text} {unidad}"
    ini, fin = _t(pp, "cac:PlannedPeriod/cbc:StartDate"), _t(pp, "cac:PlannedPeriod/cbc:EndDate")
    if ini or fin:
        return f"{ini or '?'} → {fin or '?'}"
    return None
