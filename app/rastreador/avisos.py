"""Avisos por correo: quién quiere qué y qué se le manda.

Un resumen al día, después del rastreo, con lo nuevo que encaje con los filtros de cada persona.
Si no hay nada nuevo, no se manda nada.

Reglas para no dar la lata ni duplicar:

* **Solo envía el PC que rastrea**, que es el que tiene el bloqueo de la carpeta compartida.
* **Lo ya avisado se anota en la base compartida** (`avisos_enviados`), así que ningún otro PC
  vuelve a mandar lo mismo aunque también rastree.
* Al darse de alta no llega una avalancha con el histórico: solo se avisa de lo que entre
  a partir de ese momento (`desde`).

Uso desde línea de órdenes:

    python -m rastreador.avisos --listar
    python -m rastreador.avisos --guardar "radarghc://avisos?..."   (lo llama el panel)
    python -m rastreador.avisos --probar correo@ejemplo.com
    python -m rastreador.avisos --enviar                            (fuerza el envío ahora)
"""
from __future__ import annotations

import json
import logging
import sys
import urllib.parse
from datetime import datetime
from html import escape

from . import correo
from .db import DB
from .util import RAIZ, cargar_config, cargar_env, configurar_logging, parse_fecha

log = logging.getLogger("rastreador.avisos")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS suscripciones (
    email        TEXT PRIMARY KEY,
    nombre       TEXT,
    ccaa         TEXT,                  -- JSON lista; vacía = todas
    categorias   TEXT,                  -- JSON lista; vacía = todas
    subvenciones INTEGER DEFAULT 1,
    licitaciones INTEGER DEFAULT 1,
    activo       INTEGER DEFAULT 1,
    desde        TEXT,                  -- no se avisa de lo anterior a esta fecha
    creado       TEXT,
    actualizado  TEXT
);
CREATE TABLE IF NOT EXISTS avisos_enviados (
    email   TEXT NOT NULL,
    tipo    TEXT NOT NULL,              -- convocatoria | licitacion
    id      TEXT NOT NULL,
    enviado TEXT NOT NULL,
    PRIMARY KEY (email, tipo, id)
);
"""


def preparar(db: DB) -> None:
    db.con.executescript(ESQUEMA)
    db.con.commit()


# --------------------------------------------------------------------- suscripciones
def listar(db: DB) -> list[dict]:
    preparar(db)
    filas = db.con.execute("SELECT * FROM suscripciones ORDER BY email").fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        for k in ("ccaa", "categorias"):
            try:
                d[k] = json.loads(d[k] or "[]")
            except ValueError:
                d[k] = []
        salida.append(d)
    return salida


def guardar(db: DB, s: dict) -> str:
    """Alta o modificación de una suscripción. Devuelve un mensaje para enseñar por pantalla."""
    preparar(db)
    email = (s.get("email") or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        return f"Correo no válido: {email or '(vacío)'}"
    ahora = datetime.now().isoformat(timespec="seconds")
    existe = db.con.execute("SELECT desde, creado FROM suscripciones WHERE email=?", (email,)).fetchone()
    datos = (
        email,
        (s.get("nombre") or "").strip(),
        json.dumps(s.get("ccaa") or [], ensure_ascii=False),
        json.dumps(s.get("categorias") or [], ensure_ascii=False),
        int(bool(s.get("subvenciones", True))),
        int(bool(s.get("licitaciones", True))),
        int(bool(s.get("activo", True))),
        (existe["desde"] if existe else ahora),
        (existe["creado"] if existe else ahora),
        ahora,
    )
    db.con.execute(
        "INSERT OR REPLACE INTO suscripciones "
        "(email, nombre, ccaa, categorias, subvenciones, licitaciones, activo, desde, creado, actualizado) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)", datos)
    db.con.commit()
    que = " y ".join(x for x in (("subvenciones" if s.get("subvenciones", True) else ""),
                                 ("licitaciones" if s.get("licitaciones", True) else "")) if x) or "nada"
    ambito = ", ".join(s.get("ccaa") or []) or "todas las CCAA"
    if not s.get("activo", True):
        return f"Avisos desactivados para {email}"
    return f"{'Actualizada' if existe else 'Creada'} la suscripción de {email}: {que} · {ambito}"


def borrar(db: DB, email: str) -> str:
    preparar(db)
    db.con.execute("DELETE FROM suscripciones WHERE email=?", (email.strip().lower(),))
    db.con.commit()
    return f"Suscripción de {email} eliminada"


def desde_url(url: str) -> dict:
    """Lee radarghc://avisos?email=..&nombre=..&ccaa=ES11,ES30&cat=..&sub=1&lic=1&activo=1"""
    p = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(p.query)
    uno = lambda k, d="": (q.get(k) or [d])[0]  # noqa: E731
    lista = lambda k: [x for x in uno(k).split(",") if x]  # noqa: E731
    return {
        "email": uno("email"), "nombre": uno("nombre"),
        "ccaa": lista("ccaa"), "categorias": lista("cat"),
        "subvenciones": uno("sub", "1") == "1", "licitaciones": uno("lic", "1") == "1",
        "activo": uno("activo", "1") == "1",
    }


# --------------------------------------------------------------------- selección
def _encaja(fila: dict, sus: dict) -> bool:
    ccaa = sus.get("ccaa") or []
    if ccaa:
        # se admite tanto el nombre ("Galicia") como el código NUTS2 del geo
        suyo = {fila.get("ccaa") or "", (fila.get("geo") or {}).get("codigo") or ""}
        if not (suyo & set(ccaa)):
            return False
    cats = sus.get("categorias") or []
    if cats and not (set(fila.get("categorias") or []) & set(cats)):
        return False
    return True


def pendientes(db: DB, sus: dict) -> tuple[list[dict], list[dict]]:
    """Novedades que tocan avisar a esta persona: (convocatorias, licitaciones)."""
    ya = {(r["tipo"], r["id"]) for r in db.con.execute(
        "SELECT tipo, id FROM avisos_enviados WHERE email=?", (sus["email"],))}
    desde = sus.get("desde") or ""
    convs, lics = [], []
    if sus.get("subvenciones"):
        for c in db.todas_convocatorias():
            if (c.get("creado") or "") < desde or ("convocatoria", c["id_bdns"]) in ya:
                continue
            if _encaja(c, sus):
                convs.append(c)
    if sus.get("licitaciones"):
        hoy = datetime.now().date().isoformat()
        for l in db.todas_licitaciones():
            if (l.get("creado") or "") < desde or ("licitacion", l["id"]) in ya:
                continue
            if l.get("fecha_limite") and l["fecha_limite"] < hoy:
                continue          # plazo ya vencido: no molestamos con ello
            if _encaja(l, sus):
                lics.append(l)
    return convs, lics


# --------------------------------------------------------------------- redacción
def _eur(v) -> str:
    try:
        return f"{float(v):,.0f} €".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def _fecha(v) -> str:
    f = parse_fecha(v)
    return f.strftime("%d/%m/%Y") if f else "—"


def _ficha_convocatoria(c: dict) -> str:
    r = c.get("resumen_json") or {}
    if not isinstance(r, dict):
        r = {}
    conf = r.get("confianza")
    color = {"alta": "#0b6b3a", "media": "#b26a00"}.get(conf, "#b3261e")
    filas = [
        ("Órgano", escape(c.get("organo") or "—")),
        ("Ámbito", escape(c.get("ccaa") or c.get("ambito") or "—")),
        ("Plazo", f"{escape(str(r.get('fecha_inicio') or _fecha(c.get('fecha_inicio'))))} → "
                  f"<b>{escape(str(r.get('fecha_fin') or _fecha(c.get('fecha_fin'))))}</b>"),
        ("Importe", escape(str(r.get("importe") or _eur(c.get("presupuesto"))))),
        ("% de ayuda", escape(str(r.get("porcentaje") or "No consta"))),
        ("Ayuda máxima", escape(str(r.get("cuantia_maxima") or "No consta"))),
    ]
    tabla = "".join(f'<tr><td style="padding:2px 10px 2px 0;color:#5b6770;white-space:nowrap">{k}</td>'
                    f'<td style="padding:2px 0">{v}</td></tr>' for k, v in filas)
    cuerpo = escape(str(r.get("resumen") or c.get("titulo") or ""))
    encaje = ""
    if r.get("encaje_ghc"):
        encaje = (f'<div style="margin-top:6px;padding:6px 10px;background:#f0f7f3;border-left:3px solid #1c7c54">'
                  f'<b>Encaje GHC:</b> {escape(str(r["encaje_ghc"]))}'
                  f'{" — " + escape(str(r["encaje_motivo"])) if r.get("encaje_motivo") else ""}</div>')
    cond = (r.get("condiciones") or [])[:4]
    condiciones = ("<ul style='margin:6px 0 0;padding-left:18px'>" +
                   "".join(f"<li>{escape(str(x))}</li>" for x in cond) + "</ul>") if cond else ""
    return f"""
    <div style="border:1px solid #dfe5e2;border-radius:8px;padding:12px 14px;margin-bottom:14px">
      <div style="font-size:15px;font-weight:600;color:#14332a">{escape(r.get('titulo_corto') or c.get('titulo') or '')}</div>
      <div style="font-size:11px;color:#5b6770;margin:2px 0 8px">BDNS {escape(str(c.get('id_bdns')))} ·
        publicada {_fecha(c.get('fecha_publicacion'))} ·
        <span style="color:{color}">{escape('confianza ' + conf) if conf else 'resumen aún no generado'}</span></div>
      <p style="margin:0 0 8px">{cuerpo}</p>
      <table style="font-size:13px;border-collapse:collapse">{tabla}</table>
      {encaje}{condiciones}
      <div style="margin-top:10px"><a href="{escape(c.get('url_ficha') or '')}"
         style="color:#0f5d3d">Ver la ficha en la BDNS</a></div>
    </div>"""


def _ficha_licitacion(l: dict) -> str:
    cl = l.get("clasificacion") or {}
    if not isinstance(cl, dict):
        cl = {}
    clas = "No consta"
    if cl.get("exigida") is True:
        clas = "Sí — " + (" / ".join(cl.get("codigos") or []) or "?") + (f" · cat. {cl['categoria']}" if cl.get("categoria") else "")
    elif cl.get("exigida") is False:
        clas = "No exigible"
    filas = [
        ("Órgano", escape(l.get("organo") or "—")),
        ("Lugar", escape(l.get("lugar") or l.get("ccaa") or "—")),
        ("Límite de ofertas", f"<b>{_fecha(l.get('fecha_limite'))}"
                              f"{' ' + escape(l['hora_limite'][:5]) if l.get('hora_limite') else ''}</b>"),
        ("Presupuesto (sin IVA)", _eur(l.get("presupuesto_sin_iva"))),
        ("Tipo", escape(f"{l.get('tipo') or '—'} · {l.get('procedimiento') or ''}")),
        ("Clasificación", escape(clas)),
    ]
    tabla = "".join(f'<tr><td style="padding:2px 10px 2px 0;color:#5b6770;white-space:nowrap">{k}</td>'
                    f'<td style="padding:2px 0">{v}</td></tr>' for k, v in filas)
    return f"""
    <div style="border:1px solid #dfe5e2;border-radius:8px;padding:12px 14px;margin-bottom:14px">
      <div style="font-size:15px;font-weight:600;color:#14332a">{escape(l.get('titulo') or '')}</div>
      <div style="font-size:11px;color:#5b6770;margin:2px 0 8px">Exp. {escape(l.get('expediente') or '—')} ·
        publicada {_fecha(l.get('fecha_publicacion'))}</div>
      <table style="font-size:13px;border-collapse:collapse">{tabla}</table>
      <div style="margin-top:10px"><a href="{escape(l.get('url') or '')}"
         style="color:#0f5d3d">Ver la licitación</a></div>
    </div>"""


def redactar(sus: dict, convs: list[dict], lics: list[dict], version: str) -> tuple[str, str]:
    hoy = datetime.now().strftime("%d/%m/%Y")
    trozos = [f"<b>{len(convs)} subvención(es)</b>" if convs else "",
              f"<b>{len(lics)} licitación(es)</b>" if lics else ""]
    titular = " y ".join(x for x in trozos if x)
    ambito = ", ".join(sus.get("ccaa") or []) or "toda España"
    cuerpo = ""
    if convs:
        cuerpo += '<h2 style="font-size:16px;color:#0f5d3d;margin:18px 0 10px">Subvenciones nuevas</h2>'
        cuerpo += "".join(_ficha_convocatoria(c) for c in convs)
    if lics:
        cuerpo += '<h2 style="font-size:16px;color:#1d4ed8;margin:18px 0 10px">Licitaciones nuevas</h2>'
        cuerpo += "".join(_ficha_licitacion(l) for l in lics)

    html = f"""<div style="font-family:Segoe UI,system-ui,sans-serif;font-size:14px;color:#1f2a2e;max-width:680px">
      <div style="background:#0f1a0a;color:#fff;padding:12px 16px;border-radius:8px 8px 0 0">
        <div style="font-size:16px;font-weight:600">Radar de subvenciones y licitaciones</div>
        <div style="font-size:12px;opacity:.75">GHC · Pansogal — {hoy}</div>
      </div>
      <div style="border:1px solid #dfe5e2;border-top:none;border-radius:0 0 8px 8px;padding:16px">
        <p style="margin:0 0 6px">{('Hola ' + escape(sus['nombre']) + ', h') if sus.get('nombre') else 'H'}oy hay
           {titular} que encajan con lo que sigues ({escape(ambito)}).</p>
        {cuerpo}
        <hr style="border:none;border-top:1px solid #dfe5e2;margin:18px 0">
        <div style="font-size:11px;color:#5b6770">
          Los resúmenes se generan automáticamente a partir de los documentos oficiales y pueden contener
          errores: verifica siempre contra las bases reguladoras y los pliegos antes de decidir.<br>
          Radar v{escape(version)} · para cambiar o quitar estos avisos, pestaña «Avisos» del panel.
        </div>
      </div>
    </div>"""
    asunto = f"Radar GHC {hoy}: " + " y ".join(
        x for x in ([f"{len(convs)} subvención(es)"] if convs else []) + ([f"{len(lics)} licitación(es)"] if lics else []))
    return asunto, html


# --------------------------------------------------------------------- envío
def enviar_todo(db: DB, cfg: dict, version: str, forzar: bool = False) -> int:
    """Manda a cada suscriptor su resumen. Devuelve cuántos correos han salido."""
    cav = (cfg.get("avisos") or {})
    if not cav.get("activo") and not forzar:
        return 0
    preparar(db)
    enviados = 0
    for sus in listar(db):
        if not sus.get("activo"):
            continue
        convs, lics = pendientes(db, sus)
        if not convs and not lics:
            log.info("Avisos: nada nuevo para %s", sus["email"])
            continue
        tope = int(cav.get("max_por_correo", 25))
        convs, lics = convs[:tope], lics[:tope]
        asunto, html = redactar(sus, convs, lics, version)
        ok, msg = correo.enviar(cav, sus["email"], asunto, html)
        if ok:
            ahora = datetime.now().isoformat(timespec="seconds")
            db.con.executemany("INSERT OR REPLACE INTO avisos_enviados (email,tipo,id,enviado) VALUES (?,?,?,?)",
                               [(sus["email"], "convocatoria", c["id_bdns"], ahora) for c in convs] +
                               [(sus["email"], "licitacion", l["id"], ahora) for l in lics])
            db.con.commit()
            enviados += 1
            log.info("Aviso enviado a %s: %d convocatorias, %d licitaciones (%s)",
                     sus["email"], len(convs), len(lics), msg)
        else:
            log.warning("NO se ha podido avisar a %s: %s", sus["email"], msg)
    return enviados


def ensayo(db: DB, cfg: dict, version: str, n: int = 3) -> str:
    """Manda a cada suscriptor un aviso de ENSAYO con sus 3 novedades más recientes.

    Para qué: `--probar` solo demuestra que el SMTP acepta la contraseña. Esto demuestra la cadena
    entera —filtros, redacción, envío— con contenido real, que es lo que de verdad hay que ver
    funcionando antes de fiarse.

    No toca nada: NO apunta nada en `avisos_enviados` y NO mueve la fecha `desde`, así que estas
    mismas convocatorias volverán a avisarse cuando toque. Se puede repetir las veces que haga falta.

    Devuelve (texto, todo_ok). El segundo valor importa en GitHub Actions: sin él, el paso salía en
    verde aunque no hubiera salido ni un correo.
    """
    cav = dict(cfg.get("avisos") or {})
    salida, todo_ok = [], True
    for sus in listar(db):
        if not sus.get("activo"):
            continue
        # se ignora la fecha 'desde' a propósito: si no, en un día tranquilo no habría nada que enseñar
        falso = dict(sus, desde="")
        convs, lics = pendientes(db, falso)
        convs, lics = convs[:n], lics[:n]
        if not convs and not lics:
            salida.append(f"  [!]   {sus['email']}: no hay NADA que encaje con sus filtros. "
                          f"Revisa las CCAA y las temáticas marcadas.")
            continue
        asunto, html = redactar(sus, convs, lics, version)
        ok, msg = correo.enviar(cav, sus["email"], f"[ENSAYO] {asunto}", html)
        todo_ok = todo_ok and ok
        salida.append(("  [OK]  " if ok else "  [X]   ") +
                      f"{sus['email']}: {len(convs)} convocatorias, {len(lics)} licitaciones — {msg}")
    if not salida:
        return "No hay ninguna suscripción activa.", True
    return ("Ensayo de aviso (no se apunta como enviado; volverás a recibirlas cuando toque):\n"
            + "\n".join(salida)), todo_ok


# --------------------------------------------------------------------- consola
def _guardar_compartido(cfg: dict, version: str, s: dict) -> str:
    """Alta/baja contra la base COMPARTIDA, regenerando el panel para que se vea al momento.

    Sin esto, la suscripción se quedaba en la base local de ese PC y no aparecía en el panel
    compartido (que es el que abre el acceso directo) hasta el siguiente rastreo completo.
    """
    from . import panel
    from .compartido import Compartido
    g = cfg["general"]
    db_local, panel_local = RAIZ / g["db"], RAIZ / g["panel"]
    comp = Compartido(g.get("carpeta_compartida"), db_local, panel_local)
    comp.bloquear()
    try:
        comp.traer()                      # partir de lo que haya en la carpeta compartida
        db = DB(db_local)
        msg = guardar(db, s)
        panel.generar(db, cfg, panel_local)   # el panel se regenera con la lista al día
        db.con.close()
        comp.llevar(version)              # y se devuelve todo a la carpeta compartida
    finally:
        comp.liberar()
    return msg


def _abrir_panel(cfg: dict) -> None:
    """Abre el panel compartido (o el local) para ver el resultado sin tener que buscarlo."""
    from .compartido import Compartido
    g = cfg["general"]
    comp = Compartido(g.get("carpeta_compartida"), RAIZ / g["db"], RAIZ / g["panel"])
    destino = (comp.carpeta / "index.html") if comp.activo and (comp.carpeta / "index.html").exists() \
        else RAIZ / g["panel"]
    try:
        import os
        os.startfile(str(destino))        # solo existe en Windows
    except (AttributeError, OSError):
        print(f"Abre el panel en: {destino}")


def main() -> None:
    cargar_env()
    configurar_logging("INFO")
    cfg = cargar_config()
    from . import __version__
    args = sys.argv[1:]

    if "--guardar" in args:
        url = args[args.index("--guardar") + 1]
        s = desde_url(url)
        if not s.get("email"):
            print("Nada que guardar: no venía ningún correo.")
            return
        print(_guardar_compartido(cfg, __version__, s))
        _abrir_panel(cfg)
        return

    db = DB(RAIZ / cfg["general"]["db"])
    if "--borrar" in args:
        print(borrar(db, args[args.index("--borrar") + 1]))
    elif "--probar" in args:
        destino = args[args.index("--probar") + 1]
        ok, msg = correo.probar(cfg.get("avisos") or {}, destino)
        print(("  [OK]  " if ok else "  [X]   ") + msg)
    elif "--enviar" in args:
        print(f"Correos enviados: {enviar_todo(db, cfg, __version__, forzar=True)}")
    elif "--ensayo" in args:
        texto, ok = ensayo(db, cfg, __version__)
        print(texto)
        if not ok:
            # salir con error a propósito: si no, en GitHub Actions el paso sale en verde
            # aunque no haya salido ni un correo, y uno se queda pensando que funciona
            print("\nAlgún envío ha fallado.")
            db.con.close()
            sys.exit(1)
    else:
        subs = listar(db)
        print(f"\nSuscripciones ({len(subs)}):")
        for s in subs:
            print(f"  {'ON ' if s['activo'] else 'off'} {s['email']:35s} "
                  f"{'subv ' if s['subvenciones'] else '     '}{'lic ' if s['licitaciones'] else '    '} "
                  f"{', '.join(s['ccaa']) or 'todas las CCAA'}")
        print()
    db.con.close()


if __name__ == "__main__":
    main()
