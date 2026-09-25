"""Centroides aproximados (lat, lon) de provincias (NUTS3) y comunidades (NUTS2) para el mapa del panel."""

NUTS3 = {
    "ES111": ("A Coruña", 43.20, -8.45), "ES112": ("Lugo", 43.00, -7.55), "ES113": ("Ourense", 42.20, -7.60),
    "ES114": ("Pontevedra", 42.45, -8.55), "ES120": ("Asturias", 43.30, -5.90), "ES130": ("Cantabria", 43.20, -4.00),
    "ES211": ("Araba/Álava", 42.85, -2.70), "ES212": ("Gipuzkoa", 43.15, -2.20), "ES213": ("Bizkaia", 43.25, -2.85),
    "ES220": ("Navarra", 42.70, -1.65), "ES230": ("La Rioja", 42.30, -2.50), "ES241": ("Huesca", 42.15, -0.15),
    "ES242": ("Teruel", 40.65, -0.90), "ES243": ("Zaragoza", 41.60, -1.00), "ES300": ("Madrid", 40.45, -3.70),
    "ES411": ("Ávila", 40.60, -5.00), "ES412": ("Burgos", 42.35, -3.60), "ES413": ("León", 42.60, -5.90),
    "ES414": ("Palencia", 42.40, -4.50), "ES415": ("Salamanca", 40.90, -6.10), "ES416": ("Segovia", 41.05, -4.10),
    "ES417": ("Soria", 41.65, -2.55), "ES418": ("Valladolid", 41.65, -4.75), "ES419": ("Zamora", 41.70, -5.90),
    "ES421": ("Albacete", 38.85, -1.95), "ES422": ("Ciudad Real", 38.90, -3.90), "ES423": ("Cuenca", 40.00, -2.20),
    "ES424": ("Guadalajara", 40.80, -2.60), "ES425": ("Toledo", 39.80, -4.20), "ES431": ("Badajoz", 38.70, -6.30),
    "ES432": ("Cáceres", 39.65, -6.20), "ES511": ("Barcelona", 41.65, 1.95), "ES512": ("Girona", 42.05, 2.70),
    "ES513": ("Lleida", 41.95, 1.05), "ES514": ("Tarragona", 41.15, 0.80), "ES521": ("Alicante", 38.50, -0.60),
    "ES522": ("Castellón", 40.20, -0.20), "ES523": ("Valencia", 39.40, -0.70), "ES531": ("Eivissa-Formentera", 38.95, 1.40),
    "ES532": ("Mallorca", 39.65, 2.95), "ES533": ("Menorca", 39.95, 4.05), "ES611": ("Almería", 37.20, -2.35),
    "ES612": ("Cádiz", 36.55, -5.85), "ES613": ("Córdoba", 38.00, -4.80), "ES614": ("Granada", 37.30, -3.30),
    "ES615": ("Huelva", 37.55, -6.90), "ES616": ("Jaén", 38.00, -3.45), "ES617": ("Málaga", 36.80, -4.65),
    "ES618": ("Sevilla", 37.40, -5.85), "ES620": ("Murcia", 38.00, -1.50), "ES630": ("Ceuta", 35.89, -5.32),
    "ES640": ("Melilla", 35.29, -2.94), "ES703": ("El Hierro", 27.75, -18.00), "ES704": ("Fuerteventura", 28.40, -14.00),
    "ES705": ("Gran Canaria", 27.95, -15.60), "ES706": ("La Gomera", 28.10, -17.25), "ES707": ("La Palma", 28.65, -17.85),
    "ES708": ("Lanzarote", 29.00, -13.60), "ES709": ("Tenerife", 28.30, -16.60),
}

NUTS2 = {
    "ES11": ("Galicia", 42.75, -7.90), "ES12": ("Asturias", 43.30, -5.90), "ES13": ("Cantabria", 43.20, -4.00),
    "ES21": ("País Vasco", 43.05, -2.60), "ES22": ("Navarra", 42.70, -1.65), "ES23": ("La Rioja", 42.30, -2.50),
    "ES24": ("Aragón", 41.50, -0.70), "ES30": ("Comunidad de Madrid", 40.45, -3.70), "ES41": ("Castilla y León", 41.75, -4.80),
    "ES42": ("Castilla-La Mancha", 39.50, -3.00), "ES43": ("Extremadura", 39.20, -6.20), "ES51": ("Cataluña", 41.80, 1.60),
    "ES52": ("Comunidad Valenciana", 39.40, -0.60), "ES53": ("Baleares", 39.60, 2.95), "ES61": ("Andalucía", 37.45, -4.80),
    "ES62": ("Región de Murcia", 38.00, -1.50), "ES63": ("Ceuta", 35.89, -5.32), "ES64": ("Melilla", 35.29, -2.94),
    "ES70": ("Canarias", 28.30, -16.00), "ES": ("España", 40.20, -3.70),
}

CCAA_A_NUTS2 = {v[0]: k for k, v in NUTS2.items()}


def localizar(nuts_codes: list[str] | None, ccaa: str | None) -> dict | None:
    """Devuelve {"nombre", "lat", "lon", "nivel"} a partir de códigos NUTS (preferencia NUTS3) o del nombre de CCAA."""
    for c in nuts_codes or []:
        c = (c or "").split(" ")[0].strip().upper()
        if c in NUTS3:
            n, la, lo = NUTS3[c]
            return {"nombre": n, "lat": la, "lon": lo, "nivel": "provincia", "codigo": c}
    for c in nuts_codes or []:
        c = (c or "").split(" ")[0].strip().upper()[:4]
        if c in NUTS2 and c != "ES":
            n, la, lo = NUTS2[c]
            return {"nombre": n, "lat": la, "lon": lo, "nivel": "ccaa", "codigo": c}
    if ccaa and ccaa in CCAA_A_NUTS2:
        c = CCAA_A_NUTS2[ccaa]
        n, la, lo = NUTS2[c]
        return {"nombre": n, "lat": la, "lon": lo, "nivel": "ccaa", "codigo": c}
    if ccaa == "Nacional":
        return {"nombre": "España (ámbito nacional)", "lat": 40.20, "lon": -3.70, "nivel": "nacional", "codigo": "ES"}
    return None
