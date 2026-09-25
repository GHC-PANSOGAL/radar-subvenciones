"""Envío de correo, con el proveedor desacoplado.

Proveedores (`avisos.proveedor` en config.yaml):

* ``brevo``   — API HTTPS, nivel gratuito ~300 correos/día. Clave en ``BREVO_API_KEY``.
* ``resend``  — API HTTPS, nivel gratuito. Clave en ``RESEND_API_KEY``.
* ``smtp``    — servidor SMTP clásico (``SMTP_HOST``, ``SMTP_USER``, ``SMTP_PASS``).
                AVISO: en Microsoft 365, el envío SMTP con autenticación básica está en retirada
                y es incompatible con los Security Defaults de Entra ID. Puede dejar de funcionar.
* ``fichero`` — no envía nada: deja el correo en ``data/avisos/`` para verlo. Útil para probar.

Se usan APIs HTTPS en lugar de SMTP a propósito: no dependen de puertos que la red de la empresa
pueda tener cerrados, ni de una política de Microsoft que está cambiando.
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import requests

from .util import RAIZ, UA

log = logging.getLogger("rastreador.correo")


def _limpiar(html: str) -> str:
    """Versión en texto plano, para los clientes que no muestran HTML."""
    t = re.sub(r"<br\s*/?>|</p>|</h[12]>|</li>", "\n", html)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _brevo(cfg: dict, destino: str, asunto: str, html: str) -> tuple[bool, str]:
    clave = os.environ.get("BREVO_API_KEY", "").strip()
    if not clave:
        return False, "Falta BREVO_API_KEY en el .env"
    try:
        r = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json={"sender": {"email": cfg["remitente"], "name": cfg.get("remitente_nombre", "Radar GHC")},
                  "to": [{"email": destino}], "subject": asunto,
                  "htmlContent": html, "textContent": _limpiar(html)},
            headers={"api-key": clave, "Content-Type": "application/json", "User-Agent": UA},
            timeout=60)
    except requests.RequestException as e:
        return False, f"No se ha podido conectar con Brevo ({type(e).__name__})"
    if r.status_code in (200, 201, 202):
        return True, "enviado"
    return False, f"Brevo HTTP {r.status_code}: {r.text[:200]}"


def _resend(cfg: dict, destino: str, asunto: str, html: str) -> tuple[bool, str]:
    clave = os.environ.get("RESEND_API_KEY", "").strip()
    if not clave:
        return False, "Falta RESEND_API_KEY en el .env"
    remite = f'{cfg.get("remitente_nombre", "Radar GHC")} <{cfg["remitente"]}>'
    try:
        r = requests.post("https://api.resend.com/emails",
                          json={"from": remite, "to": [destino], "subject": asunto,
                                "html": html, "text": _limpiar(html)},
                          headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json",
                                   "User-Agent": UA},
                          timeout=60)
    except requests.RequestException as e:
        return False, f"No se ha podido conectar con Resend ({type(e).__name__})"
    if r.status_code in (200, 201, 202):
        return True, "enviado"
    return False, f"Resend HTTP {r.status_code}: {r.text[:200]}"


def _smtp(cfg: dict, destino: str, asunto: str, html: str) -> tuple[bool, str]:
    host = os.environ.get("SMTP_HOST", "").strip()
    usuario = os.environ.get("SMTP_USER", "").strip()
    clave = os.environ.get("SMTP_PASS", "").strip()
    if not (host and usuario and clave):
        return False, "Faltan SMTP_HOST / SMTP_USER / SMTP_PASS en el .env"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = asunto, cfg.get("remitente") or usuario, destino
    msg.set_content(_limpiar(html))
    msg.add_alternative(html, subtype="html")
    try:
        puerto = int(os.environ.get("SMTP_PORT", "587"))
        # 465 = SSL directo desde el saludo; 587 (y el resto) = conexión en claro y STARTTLS después.
        # Confundirlos da un error de SSL que no dice nada útil, así que se elige por puerto.
        if puerto == 465:
            with smtplib.SMTP_SSL(host, puerto, timeout=60) as s:
                s.login(usuario, clave)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, puerto, timeout=60) as s:
                s.starttls()
                s.login(usuario, clave)
                s.send_message(msg)
        return True, "enviado"
    except (smtplib.SMTPException, OSError) as e:
        return False, f"SMTP: {e}"


def _fichero(cfg: dict, destino: str, asunto: str, html: str) -> tuple[bool, str]:
    carpeta = RAIZ / "data" / "avisos"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = f"{datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^a-zA-Z0-9]', '_', destino)}.html"
    ruta = carpeta / nombre
    ruta.write_text(f"<!-- Para: {destino}\n     Asunto: {asunto} -->\n{html}", encoding="utf-8")
    return True, f"guardado en {ruta}"


PROVEEDORES = {"brevo": _brevo, "resend": _resend, "smtp": _smtp, "fichero": _fichero}


def enviar(cfg_avisos: dict, destino: str, asunto: str, html: str) -> tuple[bool, str]:
    """Devuelve (enviado, mensaje). Nunca lanza excepción: un fallo de correo no debe cortar el rastreo."""
    prov = (cfg_avisos or {}).get("proveedor", "fichero")
    fn = PROVEEDORES.get(prov)
    if not fn:
        return False, f"Proveedor de correo desconocido: {prov}"
    if prov != "fichero" and not (cfg_avisos or {}).get("remitente"):
        return False, "Falta avisos.remitente en config.yaml (la dirección desde la que se envía)"
    try:
        return fn(cfg_avisos, destino, asunto, html)
    except Exception as e:  # noqa: BLE001
        log.exception("Fallo enviando correo a %s", destino)
        return False, f"{type(e).__name__}: {e}"


def probar(cfg_avisos: dict, destino: str) -> tuple[bool, str]:
    html = ("<p>Esto es una prueba del Radar de subvenciones y licitaciones de GHC.</p>"
            "<p>Si lo estás leyendo, los avisos por correo funcionan.</p>")
    return enviar(cfg_avisos, destino, "Prueba del Radar GHC", html)
