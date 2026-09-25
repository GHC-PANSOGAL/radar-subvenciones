"""Gestión y comprobación de las claves y del correo, en el fichero .env.

    python -m rastreador.claves            # estado, pide lo que falte y lo prueba todo
    python -m rastreador.claves --probar   # solo comprueba, no pide nada
    python -m rastreador.claves --correo   # solo la parte de correo (SMTP)

Existe porque "la he puesto" y "funciona" no son lo mismo: una clave mal pegada, caducada o de otro
proyecto no da error al guardarla, solo hace que todos los resúmenes salgan en modo básico. Con el
correo pasa igual, y peor: un SMTP mal configurado no avisa de nada, simplemente no llega el correo.

La contraseña del buzón se pide con la escritura OCULTA (no se ve al teclearla, como en cualquier
login) y se escribe directamente en el .env de este PC. No hace falta dictársela a nadie ni mandarla
por chat o por correo.
"""
from __future__ import annotations

import getpass
import os
import re
import sys

import requests

from .util import RAIZ, UA, cargar_config, cargar_env

ENV = RAIZ / ".env"
CONFIG = RAIZ / "config.yaml"

CLAVES = {
    "GEMINI_API_KEY": {
        "titulo": "Google Gemini (gratuita) — resúmenes ejecutivos",
        "ayuda": "https://aistudio.google.com/apikey  ->  'Create API key'. Cuenta de Google, sin tarjeta. Empieza por AIza",
        "prefijo": "AIza",
    },
    "GITHUB_TOKEN": {
        "titulo": "GitHub (opcional) — publicar el panel para verlo desde el móvil",
        "ayuda": "https://github.com/settings/personal-access-tokens  ->  permiso Contents: Read and write",
        "prefijo": "github_pat_",
    },
}

# Datos del buzón desde el que salen los avisos. Se piden aparte de las CLAVES porque no son claves
# de API: son cuatro campos de un buzón normal y uno de ellos es una contraseña, que no se teclea a la vista.
CORREO = {
    "SMTP_HOST": {"titulo": "Servidor SMTP", "ayuda": "smtp.office365.com · smtp.ionos.es · smtp.gmail.com · el que diga tu proveedor"},
    "SMTP_PORT": {"titulo": "Puerto", "ayuda": "587 en la inmensa mayoría de los casos (STARTTLS)", "defecto": "587"},
    "SMTP_USER": {"titulo": "Usuario", "ayuda": "la dirección completa del buzón, p. ej. radar@ghcneutral.com"},
    "SMTP_PASS": {"titulo": "Contraseña", "ayuda": "no se verá mientras la escribes; si el buzón tiene 2FA, usa una contraseña de aplicación",
                  "oculto": True},
}


def _leer() -> dict[str, str]:
    """Valores actuales del .env (claves de API y datos del buzón)."""
    valores = {}
    if not ENV.exists():
        return valores
    for linea in ENV.read_text(encoding="utf-8").splitlines():
        crudo = linea.strip()
        comentada = crudo.startswith("#")
        l = crudo.lstrip("#").strip()
        if "=" not in l:
            continue
        k, v = l.split("=", 1)
        k = k.strip()
        # Las líneas comentadas cuentan para las CLAVES (el .env.example las trae así, como plantilla),
        # pero NO para el buzón: un "# SMTP_PASS=..." es un hueco por rellenar, no una contraseña puesta.
        # Sin esto, el script daba el buzón por configurado y el envío fallaba sin explicar por qué.
        if comentada and k in CORREO:
            continue
        if k in CLAVES or k in CORREO:
            valores[k] = v.strip().strip('"').strip("'")
    return valores


def _es_marcador(valor: str, prefijo: str) -> bool:
    """¿Es un hueco sin rellenar? (vacío o el ejemplo con equis)"""
    v = (valor or "").strip()
    return not v or set(v.replace(prefijo, "").replace("-", "").lower()) <= {"x"}


def estado() -> dict[str, tuple[bool, str]]:
    v = _leer()
    salida = {}
    for k, meta in CLAVES.items():
        val = v.get(k, "")
        puesta = not _es_marcador(val, meta["prefijo"])
        salida[k] = (puesta, (val[:8] + "…" + val[-4:]) if puesta and len(val) > 14 else "")
    return salida


def estado_correo() -> dict[str, tuple[bool, str]]:
    """Igual que estado(), para el buzón. La contraseña nunca se enseña, ni recortada."""
    v = _leer()
    salida = {}
    for k in CORREO:
        val = (v.get(k, "") or "").strip()
        puesto = bool(val) and set(val.lower()) != {"x"}
        if k == "SMTP_PASS":
            salida[k] = (puesto, "(oculta)" if puesto else "")
        else:
            salida[k] = (puesto, val)
    return salida


def _proveedor_actual() -> str:
    try:
        return (cargar_config().get("avisos") or {}).get("proveedor", "fichero")
    except Exception:  # noqa: BLE001
        return "fichero"


def _poner_proveedor(nuevo: str) -> bool:
    """Cambia avisos.proveedor en config.yaml. Toca esa línea y nada más.

    Es el interruptor de verdad: con 'fichero' el programa NO manda nada, deja el correo en data/avisos/.
    Tener los datos del buzón en el .env no sirve de nada mientras esto siga en 'fichero'.
    """
    try:
        texto = CONFIG.read_text(encoding="utf-8")
    except OSError:
        return False
    nuevo_texto, n = re.subn(r"(?m)^(\s*proveedor:\s*)(brevo|resend|smtp|fichero)(\s*(?:#.*)?)$",
                             lambda m: m.group(1) + nuevo + m.group(3), texto, count=1)
    if not n:
        return False
    CONFIG.write_text(nuevo_texto, encoding="utf-8")
    return True


def probar_correo(destino: str) -> tuple[bool, str]:
    """Manda un correo de prueba de verdad y devuelve el motivo exacto si el servidor lo rechaza."""
    cargar_env()
    from . import correo
    faltan = [k for k in CORREO if not os.environ.get(k, "").strip()]
    if faltan:
        return False, "Faltan datos del buzón en el .env: " + ", ".join(faltan)
    try:
        cav = dict((cargar_config().get("avisos") or {}))
    except Exception:  # noqa: BLE001
        cav = {}
    cav["proveedor"] = "smtp"
    cav.setdefault("remitente", os.environ.get("SMTP_USER", ""))
    ok, msg = correo.probar(cav, destino)
    if ok:
        return True, f"Correo de prueba enviado a {destino}. Míralo en la bandeja (y en spam)."
    pista = ""
    m = msg.lower()
    if "535" in msg or "authentication" in m or "auth" in m:
        pista = ("  →  El servidor rechaza usuario/contraseña. Si el buzón tiene verificación en dos pasos, "
                 "hace falta una contraseña de aplicación, no la normal.")
    elif "timed out" in m or "timeout" in m or "unreachable" in m or "getaddrinfo" in m:
        pista = ("  →  No se llega al servidor. Suele ser el cortafuegos o el antivirus de la empresa "
                 "bloqueando el puerto 587 de salida.")
    elif "starttls" in m or "ssl" in m or "wrong version" in m:
        pista = "  →  Puerto y cifrado no encajan. Prueba 587 (STARTTLS); si tu proveedor usa SSL directo, es el 465."
    elif "5.7.60" in msg or "denied" in m or "not allowed" in m:
        pista = f"  →  El buzón no tiene permiso para enviar como '{cav.get('remitente')}'. Pon de remitente el propio usuario."
    return False, f"{msg}{pista}"


def _escribir(nuevas: dict[str, str]) -> None:
    lineas = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    for k, v in nuevas.items():
        nueva = f"{k}={v}" if v else f"# {k}="
        for i, linea in enumerate(lineas):
            if linea.strip().lstrip("#").strip().startswith(k + "="):
                lineas[i] = nueva
                break
        else:
            lineas.append(nueva)
    ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def probar_gemini() -> tuple[bool, str]:
    """Llamada real y mínima a Gemini. Devuelve (funciona, mensaje)."""
    cargar_env()
    clave = os.environ.get("GEMINI_API_KEY", "").strip()
    if _es_marcador(clave, "AIza"):
        return False, "No hay clave de Gemini en el .env: los resúmenes saldrán en modo básico."
    try:
        modelo = (cargar_config().get("llm") or {}).get("gemini_modelo", "gemini-2.5-flash")
    except Exception:  # noqa: BLE001
        modelo = "gemini-2.5-flash"
    # llamada directa (no http_post_json) para poder enseñar EL MOTIVO que devuelve Google:
    # "API key not valid", "quota exceeded", "model not found"… es justo lo que hace falta saber
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
            json={"contents": [{"role": "user", "parts": [{"text": "Responde solo: OK"}]}],
                  "generationConfig": {"maxOutputTokens": 10, "temperature": 0}},
            headers={"x-goog-api-key": clave, "Content-Type": "application/json", "User-Agent": UA},
            timeout=60)
    except requests.RequestException as e:
        return False, f"No se ha podido conectar con Google ({type(e).__name__}). ¿Hay internet o proxy de empresa?"
    try:
        datos = r.json()
    except ValueError:
        return False, f"Respuesta inesperada de Google (HTTP {r.status_code})."
    if r.status_code != 200 or "error" in datos:
        e = datos.get("error", {}) if isinstance(datos, dict) else {}
        motivo = e.get("message") or r.text[:200]
        pista = ""
        if "API key not valid" in motivo or r.status_code in (400, 401):
            pista = "  →  La clave no vale. Cópiala otra vez de aistudio.google.com/apikey, entera y sin espacios."
        elif r.status_code == 429 or "quota" in motivo.lower():
            pista = "  →  Límite del nivel gratuito alcanzado. Vuelve a probar dentro de un rato."
        elif r.status_code == 404:
            pista = f"  →  El modelo '{modelo}' no existe para esta clave. Cámbialo en config.yaml (llm.gemini_modelo)."
        return False, f"Google rechaza la clave (HTTP {r.status_code}): {motivo[:200]}{pista}"
    try:
        texto = "".join(p.get("text", "") for p in datos["candidates"][0]["content"]["parts"])
        return True, f"Clave correcta. Gemini ({modelo}) responde: {texto.strip()[:40]}"
    except (KeyError, IndexError, TypeError):
        return True, f"La clave funciona, pero la respuesta de {modelo} ha llegado con un formato raro."


def _pedir_correo() -> None:
    """Pide los cuatro datos del buzón. La contraseña, con la escritura oculta."""
    est = estado_correo()
    print("-" * 66)
    print("  CORREO — buzón desde el que salen los avisos")
    print("-" * 66)
    for k, meta in CORREO.items():
        puesto, muestra = est[k]
        print(f"  {k:10s} {muestra if puesto else 'SIN PONER'}")
    print(f"  proveedor de envío en config.yaml: {_proveedor_actual()}")
    print()

    nuevas = {}
    for k, meta in CORREO.items():
        puesto = est[k][0]
        print(f"--- {meta['titulo']}")
        print(f"    {meta['ayuda']}")
        if puesto:
            pista = "Intro = dejar lo que hay"
        elif meta.get("defecto"):
            pista = f"Intro = {meta['defecto']}"
        else:
            pista = "obligatorio"
        if meta.get("oculto"):
            v = getpass.getpass(f"    {meta['titulo']} ({pista}): ").strip()
        else:
            v = input(f"    {meta['titulo']} ({pista}): ").strip()
        if not v and not puesto and meta.get("defecto"):
            v = meta["defecto"]
        if v:
            nuevas[k] = v
        print()

    if nuevas:
        _escribir(nuevas)
        print("Guardado en", ENV, "(la contraseña no se muestra en ningún sitio)")
    if _proveedor_actual() != "smtp":
        if _poner_proveedor("smtp"):
            print("config.yaml: avisos.proveedor pasa de 'fichero' a 'smtp'. A partir de ahora se envía de verdad.")
        else:
            print("AVISO: no he podido cambiar avisos.proveedor en config.yaml. Cámbialo a 'smtp' a mano.")
    print()


def main() -> None:
    solo_probar = "--probar" in sys.argv
    solo_correo = "--correo" in sys.argv
    print()
    print("=" * 66)
    print("  Claves y correo del Radar de subvenciones y licitaciones")
    print("  Fichero:", ENV)
    print("=" * 66)
    est = estado()
    if not solo_correo:
        for k, meta in CLAVES.items():
            puesta, muestra = est[k]
            print(f"  {k:16s} {'PUESTA ' + muestra if puesta else 'NO PUESTA'}   ({meta['titulo']})")
        print()

    if not solo_probar and not solo_correo:
        nuevas = {}
        for k, meta in CLAVES.items():
            puesta = est[k][0]
            print(f"--- {k}: {meta['titulo']}")
            print(f"    {meta['ayuda']}")
            aviso = "Intro = dejar la que hay" if puesta else "Intro = dejarlo en blanco"
            v = input(f"    Pega la clave ({aviso}): ").strip()
            if v:
                if not v.startswith(meta["prefijo"]):
                    print(f"    AVISO: lo normal es que empiece por '{meta['prefijo']}'. Se guarda igualmente.")
                nuevas[k] = v
            print()
        if nuevas:
            _escribir(nuevas)
            print("Guardado en", ENV)
            print()

    if not solo_probar:
        _pedir_correo()

    if not solo_correo:
        print("Comprobando la clave de Gemini contra Google…")
        ok, msg = probar_gemini()
        print(("  [OK]  " if ok else "  [X]   ") + msg)
        if ok:
            print("  Los resúmenes básicos que ya tengas se rehacen solos en las próximas ejecuciones.")
        print()

    destino = (_leer().get("SMTP_USER") or "").strip()
    if destino:
        print(f"Mandando un correo de prueba a {destino}…")
        ok, msg = probar_correo(destino)
        print(("  [OK]  " if ok else "  [X]   ") + msg)
        if not ok:
            print("       Los avisos NO van a salir hasta que esto diga [OK].")
        print()


if __name__ == "__main__":
    main()
