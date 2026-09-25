"""Orquestador de la ejecución diaria.

    python -m rastreador.run            # ejecución normal
    python -m rastreador.run --inicial  # fuerza carga histórica (ventana_dias_inicial)
    python -m rastreador.run --solo-panel   # regenera el panel sin consultar fuentes
    python -m rastreador.run --sin-llm      # no genera resúmenes LLM en esta ejecución
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import time
from datetime import datetime

from . import __version__, autoactualizar, avisos, clasificacion, panel, resumen
from .compartido import Compartido
from .publicar import GitHubPages
from .db import DB
from .filtro import Filtro
from .fuentes.bdns import BDNS, detectar_ccaa
from .fuentes.boe import BOE
from .fuentes.perplexity import PerplexitySearch
from .fuentes.placsp import PLACSP
from .fuentes.rss import RSS
from .util import RAIZ, cargar_config, cargar_env, configurar_logging, dias_atras, hoy, parse_fecha

log = logging.getLogger("rastreador.run")


def _id_url(url: str) -> str:
    return hashlib.sha1(url.strip().lower().encode()).hexdigest()[:16]


def ejecutar(args) -> int:
    cargar_env()
    cfg = cargar_config()
    g = cfg["general"]
    configurar_logging(args.log)

    # ¿hay una versión más nueva en la carpeta compartida? Se instala sola y se reinicia con ella,
    # para no depender de que cada uno se acuerde de pasar INSTALAR.bat.
    if not args.sin_autoactualizar:
        nueva = autoactualizar.actualizar(cfg)
        if nueva:
            autoactualizar.reiniciar(nueva)
            cfg = cargar_config()          # por si el reinicio no ha sido posible
            g = cfg["general"]
    comp = Compartido(g.get("carpeta_compartida"), RAIZ / g["db"], RAIZ / g["panel"])
    if args.auto and comp.activo and comp.actualizado_hace_menos_de(float(g.get("min_horas_entre_actualizaciones", 6))):
        log.info("El panel compartido se actualizó hace menos de %s h; nada que hacer.", g.get("min_horas_entre_actualizaciones", 6))
        return 0
    if not comp.bloquear():
        return 0
    comp.traer()
    db = DB(RAIZ / g["db"])
    filtro = Filtro(cfg)
    inicio = datetime.now().isoformat(timespec="seconds")
    errores: list[str] = []
    nuevas_c = nuevas_n = n_res = nuevas_l = 0

    if not args.solo_panel:
        hasta = hoy()
        if args.historico or args.desde:
            texto = args.desde or g.get("fecha_historico") or "2025-01-01"
            desde = parse_fecha(texto) or dias_atras(g["ventana_dias_inicial"])
            log.info("CARGA HISTÓRICA: %s → %s (%d días). Puede tardar horas; se puede cortar y reanudar.",
                     desde, hasta, (hasta - desde).days)
        else:
            ventana = g["ventana_dias_inicial"] if (args.inicial or db.esta_vacia()) else g["ventana_dias"]
            desde = dias_atras(ventana)
        log.info("Ventana de rastreo: %s → %s", desde, hasta)

        # ------------------------------------------------------------ BDNS
        if cfg["bdns"].get("activo", True):
            try:
                bdns = BDNS(cfg["bdns"])
                candidatas = bdns.buscar_periodo(desde, hasta)
                total_c = len(candidatas)
                for i_c, (num, item) in enumerate(candidatas.items(), 1):
                    if total_c > 200 and i_c % 50 == 0:
                        log.info("BDNS: procesada %d/%d (nuevas hasta ahora: %d)", i_c, total_c, nuevas_c)
                    if not filtro.es_relevante(item.get("descripcion"), item.get("descripcionLeng")):
                        continue
                    if db.existe_convocatoria(num) and not args.inicial:
                        continue
                    det = bdns.detalle(num)
                    time.sleep(bdns.pausa)
                    reg = bdns.a_registro(item, det)
                    texto_benef = " ".join(reg["beneficiarios"])
                    reg["categorias"] = filtro.categorias_de(reg["titulo"], reg.get("finalidad"))
                    reg["clientes"] = filtro.clientes_de(reg["titulo"], texto_benef)
                    if db.guardar_convocatoria(reg):
                        nuevas_c += 1
                        log.info("Nueva convocatoria %s [%s] %s", num, reg.get("ccaa"), reg["titulo"][:90])
            except Exception as e:  # noqa: BLE001
                log.exception("Fallo en BDNS")
                errores.append(f"BDNS: {e}")

        # ------------------------------------------------------------- BOE
        if cfg["boe"].get("activo", True):
            try:
                boe = BOE(cfg["boe"])
                for it in boe.buscar_periodo(desde, hasta):
                    if not filtro.es_relevante(it["titulo"]):
                        continue
                    nid = _id_url(it["url"])
                    if db.guardar_noticia({"id": nid, "fuente": "BOE", "titulo": it["titulo"], "url": it["url"],
                                           "fecha": it["fecha"], "resumen": f"{it.get('departamento') or ''} · Sección {it['seccion']}",
                                           "ambito": "Estado", "categorias": filtro.categorias_de(it["titulo"])}):
                        nuevas_n += 1
            except Exception as e:  # noqa: BLE001
                log.exception("Fallo en BOE")
                errores.append(f"BOE: {e}")

        # ------------------------------------------------------------- RSS
        if cfg["rss"].get("activo", True):
            try:
                for it in RSS(cfg["rss"]).leer_todos():
                    if not filtro.es_relevante(it["titulo"], it.get("resumen")):
                        continue
                    nid = _id_url(it["url"])
                    if db.guardar_noticia({"id": nid, "fuente": it["fuente"], "titulo": it["titulo"], "url": it["url"],
                                           "fecha": it.get("fecha"), "resumen": it.get("resumen"),
                                           "ambito": it.get("ambito"),
                                           "categorias": filtro.categorias_de(it["titulo"], it.get("resumen"))}):
                        nuevas_n += 1
            except Exception as e:  # noqa: BLE001
                log.exception("Fallo en RSS")
                errores.append(f"RSS: {e}")

        # ------------------------------------------------------ Perplexity
        if cfg["perplexity_search"].get("activo", True):
            try:
                for it in PerplexitySearch(cfg["perplexity_search"]).buscar_todas():
                    if not filtro.es_relevante(it["titulo"], it.get("resumen")):
                        continue
                    nid = _id_url(it["url"])
                    ccaa = detectar_ccaa(it["titulo"], it.get("resumen"))
                    if db.guardar_noticia({"id": nid, "fuente": "Perplexity", "titulo": it["titulo"], "url": it["url"],
                                           "fecha": it.get("fecha"), "resumen": it.get("resumen"),
                                           "ambito": ccaa or "España",
                                           "categorias": filtro.categorias_de(it["titulo"], it.get("resumen"))}):
                        nuevas_n += 1
            except Exception as e:  # noqa: BLE001
                log.exception("Fallo en Perplexity")
                errores.append(f"Perplexity: {e}")

        # ---------------------------------------------------- licitaciones
        if cfg.get("licitaciones", {}).get("activo", True):
            try:
                lcfg = cfg["licitaciones"]
                placsp = PLACSP(lcfg)
                if args.historico or args.desde:
                    lote = placsp.leer_historico(desde, lambda t: filtro.es_relevante(t))
                else:
                    lote = placsp.leer(dias_atras(lcfg.get("ventana_dias", 2)), lambda t: filtro.es_relevante(t))
                for lic in lote:
                    lic["ccaa"] = detectar_ccaa(lic.get("lugar"), lic.get("organo_padre"), regiones=[lic.get("nuts") or ""])
                    lic["categorias"] = filtro.categorias_de(lic["titulo"])
                    lic["clientes"] = filtro.clientes_de(lic["titulo"], lic.get("organo"))
                    lic["clasificacion"] = clasificacion.analizar(lic)
                    if db.guardar_licitacion(lic):
                        nuevas_l += 1
                        log.info("Nueva licitación [%s] %s", lic.get("ccaa"), lic["titulo"][:90])
            except Exception as e:  # noqa: BLE001
                log.exception("Fallo en PLACSP")
                errores.append(f"PLACSP: {e}")

        # ------------------------------------------------ resúmenes ejecutivos
        if not args.sin_llm:
            try:
                bdns = BDNS(cfg["bdns"])
                pendientes = db.convocatorias_sin_resumen(g["max_resumenes_por_ejecucion"])
                log.info("Resúmenes pendientes: %d", len(pendientes))
                for i, fila in enumerate(pendientes, 1):
                    conv = DB._fila(fila)
                    log.info("Resumen %d/%d: %s", i, len(pendientes), (conv.get("titulo") or "")[:70])
                    texto = ""
                    usa_llm = cfg.get("llm", {}).get("proveedor", "ninguno") != "ninguno"
                    if usa_llm and cfg["bdns"].get("descargar_pdf", True) and conv["fuente"] == "bdns":
                        det = bdns.detalle(conv["id_bdns"]) or {}
                        texto = bdns.descargar_pdf_texto(det, g["max_caracteres_pdf"])
                    res, prov = resumen.generar(conv, texto, cfg.get("llm", {}))
                    db.guardar_resumen(conv["id_bdns"], res, prov, len(texto) or None)
                    n_res += 1
                    time.sleep(float(cfg.get("llm", {}).get("pausa_segundos", 1)) if prov not in ("basico",) else 0.2)
            except Exception as e:  # noqa: BLE001
                log.exception("Fallo generando resúmenes")
                errores.append(f"Resumen: {e}")

    # ------------------------------------------------------------------ panel
    db.registrar_ejecucion(inicio, not errores, nuevas_c, nuevas_n, n_res, errores, nuevas_l)
    ruta_panel = panel.generar(db, cfg, RAIZ / g["panel"])
    # Copia para internet, sin datos de personas. Se genera aquí, con la base todavía abierta, porque
    # la publicación ocurre más abajo cuando ya se ha cerrado.
    ruta_publica = None
    if (cfg.get("publicacion", {}).get("github") or {}).get("activo"):
        try:
            ruta_publica = panel.generar(db, cfg, (RAIZ / g["panel"]).parent / "publico" / "index.html",
                                         publico=True)
        except Exception as e:  # noqa: BLE001
            log.warning("No se ha podido generar el panel público (%s); NO se publicará nada.", e)

    # avisos por correo: solo los manda este PC porque es el que tiene el bloqueo compartido
    if not args.sin_avisos:
        try:
            n = avisos.enviar_todo(db, cfg, __version__)
            if n:
                log.info("Avisos por correo enviados: %d", n)
        except Exception as e:  # noqa: BLE001
            log.exception("Fallo enviando los avisos por correo")
            errores.append(f"Avisos: {e}")
    db.con.close()
    comp.llevar(__version__)
    comp.liberar()
    # se sube SIEMPRE la copia pública: si no se ha podido generar, no se sube nada, antes que
    # publicar por error el panel interno con los correos de la plantilla dentro
    if ruta_publica:
        try:
            GitHubPages(cfg.get("publicacion", {}).get("github")).publicar(ruta_publica, __version__)
        except Exception as e:  # noqa: BLE001
            log.warning("Publicación en GitHub fallida: %s", e)
    log.info("Panel generado: %s  (nuevas convocatorias: %d, licitaciones: %d, noticias: %d, resúmenes: %d, errores: %d)",
             ruta_panel, nuevas_c, nuevas_l, nuevas_n, n_res, len(errores))
    return 1 if errores else 0


def main() -> None:
    p = argparse.ArgumentParser(description="Rastreador diario de subvenciones GHC")
    p.add_argument("--inicial", action="store_true", help="recarga la ventana inicial (ventana_dias_inicial)")
    p.add_argument("--historico", action="store_true", help="carga todo desde general.fecha_historico (por defecto 2025-01-01)")
    p.add_argument("--desde", metavar="AAAA-MM-DD", help="carga desde esta fecha concreta")
    p.add_argument("--solo-panel", action="store_true", help="solo regenerar el panel")
    p.add_argument("--sin-llm", action="store_true", help="no generar resúmenes LLM")
    p.add_argument("--sin-avisos", action="store_true", help="no enviar los avisos por correo de esta ejecución")
    p.add_argument("--sin-autoactualizar", action="store_true", help="no buscar versiones nuevas en la carpeta compartida")
    p.add_argument("--auto", action="store_true", help="ejecución programada: se omite si el panel compartido es reciente")
    p.add_argument("--log", default="INFO")
    sys.exit(ejecutar(p.parse_args()))


if __name__ == "__main__":
    main()
