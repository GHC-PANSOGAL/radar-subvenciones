"""Resumen ejecutivo de una convocatoria: fechas, importe/%, qué y quién, condiciones.

Proveedores: gemini (AI Studio, gratis) | anthropic (Messages API) | perplexity (Agent API) | ninguno (campos BDNS).

Cómo se intenta que el resumen sea fiable y no una redacción bonita inventada:

1. **Anclaje obligatorio**: el modelo debe devolver, junto a cada dato clave, la frase literal del PDF de
   donde lo ha sacado (`citas`). Las citas se comprueban después contra el texto real del PDF: una cita
   que no aparece en el documento es una señal de invención.
2. **Contraste con la BDNS**: las fechas y el presupuesto que devuelve el modelo se comparan con los
   campos estructurados de la BDNS. Las discrepancias se anotan en `avisos`.
3. **La confianza la calcula el programa**, no el modelo (que siempre tiende a decir "alta"): sale de
   si hubo PDF, cuántas citas se verifican, cuántos campos quedan en "No consta" y si hay discrepancias.
4. **Segunda pasada de verificación** (`llm.verificar`): cuando la confianza calculada no es alta, se
   le devuelve al modelo su propio JSON junto al texto y se le pide que corrija lo que esté mal.
"""
from __future__ import annotations

import json
import logging
import os
import re

from .fuentes import perplexity
from .util import http_post_json, normalizar, parse_fecha

log = logging.getLogger("rastreador.resumen")

CAMPOS_CLAVE = ("fecha_inicio", "fecha_fin", "importe", "porcentaje", "cuantia_maxima",
                "que_se_subvenciona", "quien_puede_solicitar")

ESQUEMA = {
    "type": "object",
    "properties": {
        "titulo_corto": {"type": "string", "description": "Nombre breve y claro de la ayuda (máx. 12 palabras)"},
        "fecha_inicio": {"type": "string", "description": "Inicio del plazo de solicitud (dd/mm/aaaa; si depende de la publicación, escríbelo tal cual)"},
        "fecha_fin": {"type": "string", "description": "Fin del plazo de solicitud (dd/mm/aaaa o el texto exacto de las bases)"},
        "importe": {"type": "string", "description": "Presupuesto total de la convocatoria, con la cifra exacta"},
        "cuantia_maxima": {"type": "string", "description": "Ayuda máxima por beneficiario, por proyecto o por unidad (€/kW, €/m²…)"},
        "porcentaje": {"type": "string", "description": "Porcentaje o intensidad de ayuda sobre el coste subvencionable, desglosado por tipo de beneficiario si varía"},
        "que_se_subvenciona": {"type": "string", "description": "Actuaciones subvencionables (tecnologías, equipos, obras) en 2-4 frases"},
        "quien_puede_solicitar": {"type": "string", "description": "Beneficiarios: tipo de entidad, tamaño, sector, territorio"},
        "procedimiento_concesion": {"type": "string", "description": "Concurrencia competitiva, orden de entrada u otro"},
        "plazo_ejecucion": {"type": "string", "description": "Plazo para ejecutar y justificar las actuaciones"},
        "compatibilidad": {"type": "string", "description": "Compatibilidad o incompatibilidad con otras ayudas (Next Generation, CAE, IDAE, deducciones)"},
        "donde_se_solicita": {"type": "string", "description": "Sede electrónica, registro o plataforma donde se presenta la solicitud"},
        "condiciones": {"type": "array", "items": {"type": "string"},
                        "description": "5-10 condiciones clave: requisitos técnicos (SCOP, kWp, % de ahorro exigido), gastos no elegibles, garantías, obligaciones de mantenimiento"},
        "encaje_ghc": {"type": "string",
                       "description": "Cliente GHC al que encaja: 'comunidades', 'agro', 'industria', combinación o 'bajo'"},
        "encaje_motivo": {"type": "string", "description": "Una frase: por qué encaja o no con SATE/rehabilitación, aerotermia/geotermia/puritermia, FV o BESS"},
        "resumen": {"type": "string", "description": "Resumen ejecutivo de 3-5 frases para un directivo"},
        "citas": {
            "type": "array",
            "description": "Una entrada por cada dato numérico o de plazo que hayas dado, con la frase LITERAL del documento de donde sale",
            "items": {
                "type": "object",
                "properties": {
                    "dato": {"type": "string", "description": "Nombre del campo: fecha_fin, porcentaje, importe…"},
                    "texto_literal": {"type": "string", "description": "Frase copiada tal cual del documento, sin reescribir"},
                },
                "required": ["dato", "texto_literal"],
            },
        },
        "dudas": {"type": "array", "items": {"type": "string"},
                  "description": "Lo que no has podido determinar con el texto disponible y habría que mirar en las bases"},
    },
    "required": ["fecha_inicio", "fecha_fin", "importe", "porcentaje", "que_se_subvenciona",
                 "quien_puede_solicitar", "condiciones", "encaje_ghc", "resumen", "citas"],
}

INSTRUCCIONES = """Eres un analista de subvenciones de GHC (Gestión Huella Carbono, S.L.), empresa española de
rehabilitación y eficiencia energética. GHC tiene tres tipos de cliente: (1) comunidades de propietarios
(rehabilitación energética integral: SATE, ventanas, cubiertas, sustitución de calderas por aerotermia o
geotermia, aislamiento, placas solares); (2) sector agropecuario, granjas de porcino (sustitución de calderas
de gas/gasóleo/pellet por bombas de calor aerotérmicas o geotérmicas, incluida puritermia); (3) industria con
consumos eléctricos elevados (fotovoltaica + baterías BESS).

Tu trabajo NO es redactar bonito: es extraer con exactitud. Reglas innegociables:

1. Cada cifra, porcentaje, fecha y plazo que escribas tiene que estar EN EL TEXTO. Si no está, escribe
   exactamente "No consta". No deduzcas, no completes con lo que sueles ver en otras convocatorias, no
   redondees ni conviertas unidades.
2. Por cada dato numérico o de plazo que des, añade una entrada en "citas" con la frase LITERAL del
   documento de donde lo has sacado, copiada carácter a carácter. Sin cita, el dato no vale: ponlo como
   "No consta".
3. Si el documento se contradice o solo da el plazo en texto ("un mes desde la publicación en el BOP"),
   reproduce el texto tal cual en vez de calcular una fecha.
4. Lo que no puedas determinar, dilo en "dudas". Es preferible un "No consta" a un dato inventado: este
   resumen se usa para decidir si presentarse a una ayuda.
5. Responde ÚNICAMENTE con el JSON del esquema, en español."""

INSTRUCCIONES_VERIFICAR = """Eres el revisor. Te doy el texto de una convocatoria y un JSON que ha extraído otro
analista. Comprueba dato por dato contra el texto y devuelve el JSON CORREGIDO con el mismo esquema.

- Si un dato no aparece literalmente en el texto, cámbialo a "No consta" y quita su cita.
- Si una cita no está literalmente en el texto, bórrala y revisa el dato que sostenía.
- Si encuentras en el texto un dato mejor o más preciso que el que puso el analista, corrígelo y añade su cita.
- No añadas datos nuevos sin cita literal.
- Añade a "dudas" lo que siga sin poder determinarse.
Responde ÚNICAMENTE con el JSON corregido."""


def _entrada(conv: dict, texto_pdf: str) -> str:
    campos = {
        "codigo_bdns": conv.get("id_bdns"), "titulo": conv.get("titulo"), "organo": conv.get("organo"),
        "ambito": conv.get("ambito"), "ccaa": conv.get("ccaa"), "fecha_publicacion_bdns": conv.get("fecha_publicacion"),
        "fecha_inicio_solicitud": conv.get("fecha_inicio") or conv.get("texto_inicio"),
        "fecha_fin_solicitud": conv.get("fecha_fin") or conv.get("texto_fin"),
        "abierto_segun_bdns": conv.get("abierto"), "presupuesto_total": conv.get("presupuesto"),
        "tipos_beneficiarios": conv.get("beneficiarios"), "instrumentos": conv.get("instrumentos"),
        "regiones": conv.get("regiones"), "url_bases": conv.get("url_bases"),
    }
    cab = "DATOS ESTRUCTURADOS (BDNS):\n" + json.dumps(campos, ensure_ascii=False, indent=1)
    if texto_pdf:
        return cab + "\n\nTEXTO DE LA CONVOCATORIA (extracto del PDF oficial):\n" + texto_pdf
    return (cab + "\n\n(No se ha podido obtener el texto del PDF. Usa SOLO los datos estructurados, deja en "
                  "\"No consta\" todo lo que no esté en ellos y no inventes citas.)")


# --------------------------------------------------------------------- proveedores
def _anthropic(modelo: str, instrucciones: str, entrada: str) -> dict | None:
    clave = os.environ.get("ANTHROPIC_API_KEY")
    if not clave:
        return None
    cuerpo = {
        "model": modelo, "max_tokens": 4000, "system": instrucciones + "\nEsquema JSON:\n" + json.dumps(ESQUEMA),
        "messages": [{"role": "user", "content": entrada}],
    }
    datos = http_post_json("https://api.anthropic.com/v1/messages", cuerpo,
                           {"x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                           timeout=240)
    if not datos:
        return None
    texto = "".join(b.get("text", "") for b in datos.get("content", []) if b.get("type") == "text")
    return perplexity._json_de_texto(texto)


def _gemini(modelo: str, instrucciones: str, entrada: str) -> dict | None:
    """Google Gemini API (AI Studio). Nivel gratuito suficiente: gemini-2.5-flash es 'free of charge'."""
    clave = os.environ.get("GEMINI_API_KEY")
    if not clave:
        return None
    cuerpo = {
        "systemInstruction": {"parts": [{"text": instrucciones}]},
        "contents": [{"role": "user", "parts": [{"text": entrada}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8000,
                             "responseMimeType": "application/json", "responseSchema": ESQUEMA},
    }
    datos = http_post_json(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                           cuerpo, {"x-goog-api-key": clave, "Content-Type": "application/json"}, timeout=240)
    if not datos:
        return None
    try:
        texto = "".join(p.get("text", "") for p in datos["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        log.warning("Respuesta Gemini inesperada: %s", str(datos)[:300])
        return None
    return perplexity._json_de_texto(texto)


def _llamar(prov: str, cfg_llm: dict, instrucciones: str, entrada: str) -> dict | None:
    if prov == "perplexity" and perplexity.disponible():
        return perplexity.resumir_con_agente(cfg_llm.get("perplexity_modelo", "perplexity/sonar"),
                                             instrucciones, entrada, ESQUEMA)
    if prov == "anthropic":
        return _anthropic(cfg_llm.get("anthropic_modelo", "claude-sonnet-4-5"), instrucciones, entrada)
    if prov == "gemini":
        return _gemini(cfg_llm.get("gemini_modelo", "gemini-2.5-flash"), instrucciones, entrada)
    return None


# --------------------------------------------------------------------- verificación
def _compacto(t: str) -> str:
    return re.sub(r"\s+", " ", normalizar(t or "")).strip()


def _verificar_citas(res: dict, texto_pdf: str) -> tuple[int, int, list[str]]:
    """¿Aparecen de verdad en el PDF las frases que dice haber copiado? Devuelve (verificadas, total, avisos)."""
    citas = res.get("citas") or []
    if not isinstance(citas, list) or not texto_pdf:
        return 0, len(citas) if isinstance(citas, list) else 0, []
    fuente = _compacto(texto_pdf)
    ok, avisos = 0, []
    for c in citas:
        if not isinstance(c, dict):
            continue
        lit = _compacto(c.get("texto_literal"))
        if len(lit) < 12:
            continue
        # se compara un fragmento: la extracción de PDF parte palabras y mete guiones
        aguja = lit[:70]
        if aguja in fuente:
            ok += 1
            c["verificada"] = True
        else:
            c["verificada"] = False
            avisos.append(f"La cita de «{c.get('dato')}» no se ha encontrado literalmente en el PDF.")
    return ok, len([c for c in citas if isinstance(c, dict)]), avisos


def _contrastar_bdns(res: dict, conv: dict) -> list[str]:
    """Compara fechas y presupuesto del resumen con los campos estructurados de la BDNS."""
    avisos = []
    for campo, campo_bdns, nombre in (("fecha_inicio", "fecha_inicio", "inicio"), ("fecha_fin", "fecha_fin", "fin")):
        bd, llm = conv.get(campo_bdns), res.get(campo)
        if not bd or not llm or "no consta" in normalizar(llm):
            continue
        f = parse_fecha(llm)
        if f and f.isoformat() != bd:
            avisos.append(f"La fecha de {nombre} del resumen ({llm}) no coincide con la de la BDNS "
                          f"({parse_fecha(bd).strftime('%d/%m/%Y') if parse_fecha(bd) else bd}).")
    pres = conv.get("presupuesto")
    imp = _compacto(res.get("importe"))
    if pres and imp and "no consta" not in imp:
        cifras = [float(x.replace(".", "").replace(",", ".")) for x in re.findall(r"\d[\d.]*(?:,\d+)?", imp)
                  if len(x.replace(".", "")) >= 4]
        if cifras and not any(abs(c - pres) <= max(pres * 0.02, 1) for c in cifras):
            avisos.append(f"El presupuesto del resumen no coincide con el de la BDNS ({pres:,.0f} €).".replace(",", "."))
    return avisos


def _no_consta(res: dict) -> int:
    return sum(1 for c in CAMPOS_CLAVE if "no consta" in normalizar(res.get(c) or "no consta"))


def _calcular_confianza(res: dict, conv: dict, texto_pdf: str) -> dict:
    """La confianza la decide el programa, no el modelo."""
    ok, total, avisos_citas = _verificar_citas(res, texto_pdf)
    avisos = avisos_citas + _contrastar_bdns(res, conv)
    huecos = _no_consta(res)

    if not texto_pdf:
        nivel = "baja"
        avisos.append("Sin texto del PDF: el resumen solo usa los campos estructurados de la BDNS.")
    elif total and ok == 0:
        nivel = "baja"
    elif ok >= 3 and huecos <= 1 and not avisos:
        nivel = "alta"
    elif ok >= 2 and huecos <= 3:
        nivel = "media"
    else:
        nivel = "baja"

    res["confianza"] = nivel
    res["citas_verificadas"] = f"{ok}/{total}" if total else "0/0"
    res["avisos"] = avisos
    res["campos_sin_dato"] = huecos
    return res


# --------------------------------------------------------------------- sin LLM
def _basico(conv: dict) -> dict:
    pres = conv.get("presupuesto")
    return {
        "titulo_corto": (conv.get("titulo") or "")[:120],
        "fecha_inicio": conv.get("fecha_inicio") or conv.get("texto_inicio") or "No consta",
        "fecha_fin": conv.get("fecha_fin") or conv.get("texto_fin") or "No consta",
        "importe": f"Presupuesto total: {pres:,.0f} €".replace(",", ".") if pres else "No consta",
        "cuantia_maxima": "No consta (ver bases)",
        "porcentaje": "No consta (ver bases)",
        "que_se_subvenciona": conv.get("titulo") or "",
        "quien_puede_solicitar": "; ".join(conv.get("beneficiarios") or []) or "No consta",
        "procedimiento_concesion": "No consta",
        "plazo_ejecucion": "No consta",
        "compatibilidad": "No consta",
        "donde_se_solicita": conv.get("url_sede") or "No consta",
        "condiciones": [f"Instrumento: {conv['instrumentos']}" if conv.get("instrumentos") else "Consultar bases reguladoras",
                        "Resumen generado sin LLM: revisar la ficha BDNS y las bases reguladoras"],
        "encaje_ghc": ", ".join(conv.get("clientes") or []) or "bajo",
        "encaje_motivo": "Detección automática por palabras clave del título",
        "resumen": conv.get("titulo") or "",
        "citas": [],
        "citas_verificadas": "0/0",
        "dudas": ["Todo el detalle: no se ha leído el documento oficial."],
        "avisos": ["Resumen sin inteligencia artificial: solo campos estructurados de la BDNS."],
        "confianza": "baja",
        "campos_sin_dato": 5,
    }


# --------------------------------------------------------------------- entrada pública
def generar(conv: dict, texto_pdf: str, cfg_llm: dict) -> tuple[dict, str]:
    """Devuelve (resumen, proveedor_usado)."""
    cfg_llm = cfg_llm or {}
    prov = cfg_llm.get("proveedor", "ninguno")
    entrada = _entrada(conv, texto_pdf)
    res = _llamar(prov, cfg_llm, INSTRUCCIONES, entrada) if prov != "ninguno" else None

    if not (res and isinstance(res, dict) and res.get("resumen")):
        if prov != "ninguno":
            log.warning("Resumen LLM no disponible para %s; se usa resumen básico", conv.get("id_bdns"))
        return _basico(conv), "basico"

    if isinstance(res.get("condiciones"), str):
        res["condiciones"] = [res["condiciones"]]
    res.setdefault("condiciones", [])
    res = _calcular_confianza(res, conv, texto_pdf)

    # segunda pasada: solo cuando ha quedado dudoso y hay texto contra el que revisar
    if cfg_llm.get("verificar", True) and texto_pdf and res["confianza"] != "alta":
        entrada_v = entrada + "\n\nJSON DEL PRIMER ANALISTA:\n" + json.dumps(res, ensure_ascii=False)
        rev = _llamar(prov, cfg_llm, INSTRUCCIONES_VERIFICAR, entrada_v)
        if rev and isinstance(rev, dict) and rev.get("resumen"):
            if isinstance(rev.get("condiciones"), str):
                rev["condiciones"] = [rev["condiciones"]]
            rev = _calcular_confianza(rev, conv, texto_pdf)
            antes, despues = res["confianza"], rev["confianza"]
            log.info("Verificación de %s: confianza %s → %s", conv.get("id_bdns"), antes, despues)
            rev["revisado"] = True
            res = rev
    return res, prov
