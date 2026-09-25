# Radar de subvenciones y licitaciones (GHC)

Versión actual: ver `CHANGELOG.md` (se muestra también en la cabecera y el pie del panel).

Programa independiente que cada día (08:30) rastrea las convocatorias de ayudas, las licitaciones públicas y las noticias sobre renovables (solar, baterías), eficiencia energética (aerotermia, geotermia, rehabilitación de edificios) y descarbonización de empresas en España, y mantiene un **panel web acumulado** con todas las convocatorias vigentes. Al pinchar en una convocatoria se abre su **resumen ejecutivo**: fechas de inicio y fin, importe y % subvencionable, qué y quién se subvenciona y condiciones importantes.

## Fuentes

| Fuente | Qué aporta | Clave necesaria |
|---|---|---|
| **BDNS / infosubvenciones.es** (API pública) | Todas las convocatorias de Estado, CCAA, diputaciones y ayuntamientos, con plazos, presupuesto, beneficiarios y PDF oficial. Es la fuente principal. | No |
| **PLACSP** (feeds Atom de la Plataforma de Contratación del Sector Público + plataformas autonómicas agregadas) | Licitaciones en plazo filtradas por códigos CPV de energía/climatización/aislamiento y por palabras clave. Sin API de búsqueda: se recorren las páginas del feed hacia atrás (`licitaciones.max_paginas`, 7-15 MB cada una). | No |
| **BOE** (API de sumario diario) | Convocatorias y extractos publicados en el BOE (secciones III y V.B). | No |
| **RSS** de IDAE, CDTI, FENERCOM, EVE, FAEN, IVACE, IBE, EREN, Canarias, JCCM, PROCESA y boletines (BOCM, DOE, BOCYL, BOIB) | Noticias y avisos de los organismos autonómicos. | No |
| **Google Gemini** (AI Studio, nivel gratuito) | Lee el PDF de cada convocatoria y redacta el resumen ejecutivo. Alternativas: Anthropic o Perplexity (de pago). | Sí, gratuita (`GEMINI_API_KEY`) |
| **Perplexity Search API** (opcional, desactivada) | Rastreo abierto de internet. De pago. | `PERPLEXITY_API_KEY` |

Sin claves el programa funciona (BDNS + BOE + PLACSP + RSS) con resúmenes básicos construidos con los campos de la
BDNS. Solo el PC que ejecuta el rastreo necesita la clave de Gemini: los resúmenes se guardan en la base compartida
y los demás los ven sin tener clave. Los resúmenes básicos se rehacen solos en cuanto se pone la clave.

### Fiabilidad del resumen

El modelo tiene que devolver la frase literal del documento que respalda cada cifra y cada plazo. El programa
comprueba esas citas contra el texto real del PDF, contrasta fechas e importe con la BDNS y **calcula él mismo la
confianza** (alta / media / baja); si no sale alta, hace una segunda pasada de verificación con el modelo
(`llm.verificar`). Las discrepancias aparecen en un recuadro «Revisar» dentro de la ficha, y el desplegable
«De dónde sale cada dato» muestra las citas y si se han verificado.

Para poner o cambiar las claves después de instalar: **`CLAVES.bat`**, que además hace una llamada real a
Google para confirmar que la clave funciona (una clave mal pegada no da error: simplemente deja todos los
resúmenes en modo básico).

**Clave gratuita de Gemini**: entra en https://aistudio.google.com/apikey con tu cuenta de Google → *Create API key* → copia la clave (empieza por `AIza`). No pide tarjeta. El programa usa `gemini-2.5-flash`, que es gratuito; con una pausa de 7 s entre resúmenes se respeta el límite del nivel gratuito.

La lista de organismos gestores de ayudas de energía de las 17 CCAA + Ceuta y Melilla está en `organismos.yaml` y se muestra en la pestaña **Organismos** del panel.

## Instalación en un PC Windows (doble clic)

1. Descomprime el ZIP en cualquier carpeta y haz doble clic en **`INSTALAR.bat`**. Las librerías de Python van
   incluidas en `vendor\`, así que no hace falta internet para instalarlas. Si el PC no tiene Python y
   python.org está bloqueado, ejecuta antes **`DESCARGAR_PYTHON.bat`** una vez en un PC con internet: deja el
   instalador de Python en `vendor\` y a partir de ahí la instalación es totalmente offline.
2. El instalador instala Python 3.12 si no lo tienes (descarga oficial, solo para tu usuario), copia el programa a `%LOCALAPPDATA%\GHC\Radar`, pide la clave gratuita de Gemini (opcional, Intro para saltar), crea la tarea diaria de las **08:30** en el Programador de tareas y deja el acceso directo **Radar de subvenciones y licitaciones** (icono de radar) en el escritorio. Dentro del panel, el botón **⟳ Actualizar ahora** lanza el rastreo en el momento (2-5 min) y vuelve a abrir el panel; la primera vez el navegador pide permiso para abrir "Radar de subvenciones y licitaciones" (protocolo `radarghc://`).
3. Abre el panel enseguida y a continuación hace la primera carga de 120 días, que tarda **entre 10 y 25 minutos**
   (PLACSP descarga páginas de 7-15 MB y los resúmenes esperan 7 s entre llamadas a Gemini). No cierres la ventana;
   cuando termine, pulsa F5 en el navegador. El progreso se sigue en `data\rastreador.log`.

Si el PC está apagado a las 08:30, la tarea se ejecuta al encenderlo (con sesión iniciada). Para cambiar la hora: Programador de tareas → "Radar de subvenciones y licitaciones (GHC)". Para quitarlo todo: `DESINSTALAR.bat`. Para actualizar a una versión nueva del programa: volver a ejecutar `INSTALAR.bat` (conserva la base de datos y el `.env`).

## Instalación en un servidor Linux

```bash
# 1. Copiar la carpeta al servidor y entrar en ella
cp .env.example .env            # poner GEMINI_API_KEY
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m rastreador.run          # primera carga (últimos 120 días), 2-5 min
```

Programar a las 08:30 con una de estas opciones:

* **systemd** (recomendado): `sudo bash deploy/instalar.sh` — instala en `/opt/subvenciones-ghc`, crea el timer y lanza la primera carga.
* **cron**: copiar la línea de `deploy/cron.txt` a `crontab -e`.
* **Docker**: `cd deploy && docker compose up -d` — contenedor con cron interno + nginx sirviendo el panel en el puerto 8080.

## Panel

* Selector **Líneas de subvención / Licitaciones públicas** en la parte superior; cada modo tiene sus KPIs, filtros y tabla.
* **Mapa de España** dibujado por el propio panel (SVG, sin librerías ni teselas externas: funciona sin internet) con un punto
  por provincia o comunidad donde hay convocatorias o licitaciones; el tamaño indica cuántas y al pinchar se filtra la tabla.
  Canarias va en un inserto y las convocatorias de ámbito nacional en un recuadro aparte. A la derecha, la lista de territorios
  ordenada por número. Se amplía con los botones +/− (⤢ vuelve a ver toda España), con la rueda, con doble clic,
  arrastrando para mover y con pellizco en el móvil. El contorno de las provincias está en `assets/es-provincias.json` (sustituible).
* Logos de GHC y Pansogal embebidos (`assets/logo-*-small.png`; para cambiarlos basta con sustituir esos ficheros).
* Al pinchar una licitación: plazo y hora límite, presupuesto sin/con IVA, valor estimado, tipo y procedimiento,
  lugar (NUTS), duración, lotes, fondos UE, CPV, enlaces a PCAP/PPT y **si exige clasificación del contratista y cuál**.
* Selector **"Desde 20XX"** en ambas pestañas: muestra todo lo publicado desde el 1 de enero de ese año hasta hoy.

## Compartir por OneDrive / SharePoint: varios PCs actualizan el mismo radar

**Instalación de un compañero: doble clic en `INSTALAR.bat` desde la carpeta de OneDrive y ya está.** El
instalador detecta la carpeta compartida por su propia ubicación (el `_compartido` que tiene al lado), la
fija como ruta absoluta en el `config.yaml` de esa instalación, se trae la base y abre el panel con todo
dentro. No se le pide la clave de Gemini: los resúmenes vienen en la base compartida.

`general.carpeta_compartida` en `config.yaml` apunta a `...\04_SOFTWARE\RADAR SUBVENCIONES Y LICITACIONES_CLAUDE\_compartido`,
una subcarpeta de OneDrive de empresa sincronizada (separada del código del programa, que vive en la carpeta padre). En ella viven la base de datos compartida (`subvenciones.sqlite`), el panel (`index.html`, `datos.json`), `estado.json` (quién actualizó y cuándo) y `radar.lock` (bloqueo temporal).

* **Quien tenga el programa instalado** puede actualizar: al pulsar "Actualizar ahora" (o a las 08:30) su PC trae la base compartida, rastrea y devuelve base y panel. Un bloqueo de 30 min evita que dos PCs actualicen a la vez; la tarea de las 08:30 (`--auto`) no repite el trabajo si el panel se actualizó hace menos de `min_horas_entre_actualizaciones` (6 h).
* **Quien no lo tenga instalado** abre `index.html` desde la carpeta compartida y ve lo mismo.
* El acceso directo del escritorio abre el **panel compartido**, no el local: así todos ven el último
  rastreo lo haya hecho quien lo haya hecho. Si un PC no ve la carpeta compartida, el instalador avisa y
  deja el acceso directo apuntando al panel local de ese PC (que solo se actualiza cuando rastrea él).
* **Si a alguien le salen 0 subvenciones y 0 licitaciones**: `COMPROBAR.bat`. Dice si ese PC ve la carpeta
  compartida, qué hay en cada base de datos y qué hacer.
* La carpeta debe estar marcada "Conservar siempre en este dispositivo" en OneDrive (no "solo en la nube").
* Riesgo residual: si OneDrive tarda en sincronizar y dos PCs actualizan con pocos minutos de diferencia, gana la última copia; se pierde como mucho el trabajo de esa ejecución, que se rehace en la siguiente.

## Publicar el panel en GitHub Pages (móvil)

1. En GitHub: **New repository** → nombre p. ej. `radar-subvenciones`, **Public** (Pages en repositorio privado requiere plan de pago y la página sería pública igualmente), marcar "Add a README". Crear.
2. En el repositorio: **Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: main / (root) → Save**.
3. Token: https://github.com/settings/personal-access-tokens → **Generate new token** (fine-grained) → Repository access: solo ese repositorio → Permissions → Repository permissions → **Contents: Read and write** → Generate. Copiar el token (`github_pat_…`).
4. En `config.yaml`: `publicacion.github.repo: "usuario/radar-subvenciones"`. En `.env`: `GITHUB_TOKEN=github_pat_…` (el instalador lo pide).
5. Tras la siguiente actualización, el panel estará en `https://usuario.github.io/radar-subvenciones/` (la primera vez tarda 1-2 minutos en aparecer). En el móvil: abrir en Safari/Chrome → "Añadir a pantalla de inicio".

Solo hace falta el token en un PC; los demás pueden seguir actualizando la base compartida sin publicar. La página es pública para quien conozca la URL: contiene solo información pública (BDNS, BOE, PLACSP) y los logos.

## Actualizaciones

El programa se ejecuta desde una copia en `%LOCALAPPDATA%\GHC\Radar`, no desde OneDrive. Desde la 1.15.0
**se actualiza solo**: al empezar cada ejecución compara su versión con la de la carpeta compartida y, si hay
una posterior, se copia los ficheros y se reinicia con ella. No hay que hacer nada.

Solo hace falta volver a pasar `INSTALAR.bat` cuando cambia algo que el programa no puede cambiarse a sí
mismo: el acceso directo, la tarea programada de las 08:30, el protocolo `radarghc://` o las dependencias.
El propio programa lo avisa en el registro cuando detecta ese caso, y el panel muestra un cartel si la
versión instalada se ha quedado atrás.

## Avisos por correo

Pestaña **Avisos** del panel: correo, CCAA y temáticas que sigues, y si quieres subvenciones, licitaciones o
las dos. Se recibe **un correo al día** después del rastreo con lo nuevo que encaje; si no hay nada, no se
manda nada. Solo se avisa de lo que entre a partir del alta.

Para que salgan de verdad hay que elegir por dónde se envía, en `config.yaml` → `avisos.proveedor`:

| Proveedor | Clave en `.env` | Notas |
|---|---|---|
| `fichero` | — | Por defecto. No envía: deja el correo en `data/avisos/`. Para probar |
| `brevo` | `BREVO_API_KEY` | API HTTPS, nivel gratuito ~300 correos/día. Verificar el dominio para no caer en spam |
| `resend` | `RESEND_API_KEY` | Igual que el anterior |
| `smtp` | `SMTP_HOST/USER/PASS` | Servidor SMTP clásico. **En Microsoft 365 la autenticación básica está en retirada** y es incompatible con los Security Defaults: puede dejar de funcionar sin aviso |

Probar el envío sin esperar al rastreo: `python -m rastreador.avisos --probar tu@correo.com`

Solo envía el PC que hace el rastreo, y lo ya avisado queda anotado en la base compartida, así que nadie
recibe lo mismo dos veces aunque rastreen varios PCs.

## Ver el panel

El panel es un único fichero, `panel/index.html`, sin servidor de aplicaciones. Opciones:

* Abrirlo directamente en el navegador (o sincronizar la carpeta `panel/` con Drive/OneDrive).
* Servirlo con `cd panel && python3 -m http.server 8080` o con nginx apuntando a la carpeta (`deploy/docker-compose.yml` ya lo hace).
* Junto al HTML se genera `panel/datos.json` con los mismos datos por si se quieren consumir desde Excel/Power BI.

## Uso

```bash
python -m rastreador.run                   # ejecución diaria normal
python -m rastreador.run --historico       # TODO desde general.fecha_historico (2025-01-01). Horas.
python -m rastreador.run --desde 2024-01-01  # desde otra fecha concreta
python -m rastreador.run --inicial         # recarga la ventana inicial (ventana_dias_inicial)
python -m rastreador.run --solo-panel      # regenera el panel sin consultar fuentes
python -m rastreador.run --sin-llm         # no genera resúmenes en esta ejecución
```

En Windows no hace falta consola: doble clic en **`CARGAR_HISTORICO.bat`**, que lanza `--historico` sobre la
instalación de `%LOCALAPPDATA%\GHC\Radar`.

La carga histórica se puede cortar (Ctrl+C) y reanudar: lo ya guardado no se vuelve a pedir. Los resúmenes
ejecutivos se van generando poco a poco, `general.max_resumenes_por_ejecucion` por ejecución.

### Qué se puede recuperar del histórico y qué no

| | Histórico |
|---|---|
| **Subvenciones (BDNS)** | Sí, completo. La API admite cualquier periodo; se trocea en ventanas de 45 días |
| **BOE** | Sí, por sumario diario |
| **Licitaciones (PLACSP)** | Solo si responden los ficheros agregados de `licitaciones.historico_urls`. Los feeds Atom normales van hacia atrás ~1 día por página de 7-15 MB: llegar a 2025 serían cientos de páginas y varios GB |

Registro en `data/rastreador.log` (se escribe en toda ejecución y se recorta al pasar de 2 MB); base de datos en
`data/subvenciones.sqlite` (borrarla = empezar de cero). Si una ejecución parece parada, mira el registro: las páginas
de PLACSP tardan 15-60 s cada una y cada resumen ejecutivo espera 7 s.

## Configuración (`config.yaml`)

* `categorias`: palabras clave por temática. Las marcadas `fuerte: true` hacen relevante una convocatoria por sí solas; las `fuerte: false` solo etiquetan. Se admite prefijo (`fotovoltaic` cubre fotovoltaica/fotovoltaicas).
* `exclusiones`: descartan ruido (subvenciones nominativas, becas, cooperación internacional…).
* `clientes_ghc`: detección de encaje con comunidades de propietarios, agro e industria.
* `bdns.texto_libre`: la BDNS busca por prefijo, por eso se usan raíces (`energ`, `fotovolta`, `aeroterm`…).
* `perplexity_search.consultas`: las búsquedas abiertas diarias (cada una cuesta ~0,005 $).
* `llm.proveedor`: `gemini` (gratis) | `anthropic` | `perplexity` | `ninguno`. `max_resumenes_por_ejecucion` limita los resúmenes por día.
* `licitaciones.cpv_prefijos`: prefijos CPV que hacen relevante una licitación (además del texto). `max_paginas` controla cuántas páginas del feed se leen por ejecución (≈13 s y 15 MB cada una).
* `general.dias_vigencia_sin_fecha`: cuántos días se considera "plazo por confirmar" una convocatoria sin fecha de fin estructurada.

## Estados de una convocatoria

* **Abierta**: fecha de fin ≥ hoy, o la BDNS la marca abierta.
* **Próxima**: fecha de inicio futura.
* **Plazo por confirmar**: la BDNS solo da el plazo como texto ("un mes desde la publicación en el BOP…"); se mantiene visible los días indicados en `dias_vigencia_sin_fecha`. El resumen ejecutivo suele concretar la fecha leyendo el PDF.
* **Cerrada**: fecha de fin pasada (oculta por defecto en el panel).

## Coste orientativo

BDNS, BOE, PLACSP, RSS y Gemini (nivel gratuito): 0 €. Solo si activas Perplexity o Anthropic hay coste (del orden de 2–3 $/mes).

## Aviso

Los resúmenes ejecutivos se generan automáticamente a partir del PDF oficial y pueden contener errores: verificar siempre contra las bases reguladoras antes de presentar una solicitud. Los nombres de las direcciones generales autonómicas cambian con cada reestructuración; `organismos.yaml` refleja lo verificado el 04/09/2026.
