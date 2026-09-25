# Historial de versiones — Radar de subvenciones y licitaciones

## 1.16.0 (23/09/2026)
- **Corregido: se daban por CERRADAS convocatorias que seguían abiertas.** La BDNS deja `fecha_fin` vacía
  en 137 de las 341 convocatorias que tenemos (4 de cada 10) y escribe el plazo en prosa: "a los cuatro
  meses de su publicación", "20 días hábiles a partir del siguiente a la publicación del extracto",
  "hasta el 30 de septiembre de 2026". El panel no leía ese texto: daba la convocatoria por cerrada a los
  60 días de publicarse. Consecuencia: desaparecían del filtro "Solo abiertas" semanas antes de vencer.
- Nuevo módulo `rastreador/plazos.py`: traduce ese texto a una fecha (exacta si el texto la dice, estimada
  si da un plazo relativo a la publicación; los días hábiles descuentan sábados y domingos, no festivos,
  así que el cálculo se queda corto y nunca alarga el plazo). Los plazos que no vencen por calendario
  —concesión directa, convenios, "hasta agotar crédito"— pasan a "plazo por confirmar", que es lo honesto:
  ni están abiertas a solicitud ni se pueden dar por cerradas.
- En el panel, la fecha deducida se enseña marcada como **deducida** (con el texto original en el tooltip),
  para no hacer pasar por dato de la BDNS algo que hemos calculado nosotros.
- Efecto sobre los datos actuales: abiertas 64 → 73, plazo por confirmar 8 → 17, y 27 convocatorias dejan
  de estar mal clasificadas. En la Comunidad de Madrid se pasa de **1 abierta a 8**, entre ellas la del
  Ayuntamiento de Madrid de 50.000.000 € para rehabilitación, que vence el 30/09/2026.
- La fecha deducida NO se escribe en la base: se recalcula al generar el panel. El día que la BDNS rellene
  la fecha real, manda la real sin tener que limpiar nada.

## 1.15.2 (22/09/2026)
- **Corregido: al suscribirse no aparecía nadie en la tabla.** El alta se guardaba en la base LOCAL de ese PC,
  no en la compartida, así que el panel compartido —que es el que abre el acceso directo— seguía diciendo
  "Todavía no hay nadie suscrito" hasta el siguiente rastreo completo.
  Ahora `avisos --guardar` trabaja contra la carpeta compartida de principio a fin: coge el bloqueo, se trae la
  base, apunta el alta, **regenera el panel**, lo devuelve todo y abre el panel para que se vea al momento.
- Como todo eso lo hace Python y no el `.bat`, funciona también en los PCs cuyo `actualizar_y_abrir.bat` sea
  de una versión anterior: llega con la autoactualización, sin reinstalar.

## 1.15.1 (22/09/2026)
- Avisos, alta de varias personas: botón **«Añadir a otra persona»** que vacía el formulario, y al guardar se
  **regenera el panel y se vuelve a abrir**, así la lista de suscritos se ve al momento en vez de esperar al
  siguiente rastreo (daba la sensación de que no se había guardado).

## 1.15.0 (22/09/2026)
- **El programa se actualiza solo.** Al empezar cada ejecución mira si en la carpeta compartida hay una
  versión posterior; si la hay, se copia los ficheros encima y se reinicia con el código nuevo. Se acabó
  tener que pasar INSTALAR.bat en cada PC cada vez que cambia algo.
  - Se copian `rastreador/`, `assets/`, `deploy/`, los YAML y los README.
  - **Nunca** se tocan `.env`, `data/`, `panel/` ni `.venv`, y de `config.yaml` se conserva la
    `carpeta_compartida` de ese PC, que es distinta en cada equipo.
  - Sigue haciendo falta INSTALAR.bat para lo que el programa no puede cambiarse a sí mismo: el acceso
    directo del escritorio, la tarea de las 08:30, el protocolo `radarghc://` y las dependencias nuevas.
    Cuando detecta que eso ha cambiado, lo avisa en el registro.
  - `--sin-autoactualizar` para saltárselo.

## 1.14.1 (22/09/2026)
- **Aviso de versión desfasada en el panel.** El programa se ejecuta desde una copia en
  `%LOCALAPPDATA%\GHC\Radar`, así que dejar ficheros nuevos en la carpeta de OneDrive **no actualiza nada**
  hasta que se vuelve a pasar `INSTALAR.bat`. Es fácil quedarse con una versión vieja sin enterarse. Ahora el
  panel compara su versión con la de la carpeta compartida y, si hay una más nueva, lo dice arriba del todo.

## 1.14.0 (22/09/2026)
### Avisos por correo
- **Pestaña «Avisos»** en el panel: marcas tu correo, las CCAA y las temáticas que sigues, y si quieres
  subvenciones, licitaciones o las dos. Guardar usa el protocolo `radarghc://` que ya existía, así que la
  suscripción la apunta el propio programa en la **base compartida** y vale para todos los PCs.
- **Un solo correo al día**, después del rastreo, con las novedades que encajen. Si no hay nada, no se manda
  nada. Al darse de alta no llega el histórico de golpe: solo lo que entre a partir de ese momento.
- El correo lleva la ficha de cada novedad: plazo, importe, % de ayuda, ayuda máxima, encaje GHC y las
  condiciones clave en las subvenciones; plazo, presupuesto y **clasificación exigida** en las licitaciones.
- **Solo envía el PC que rastrea** (el que tiene el bloqueo) y lo ya avisado queda anotado en
  `avisos_enviados` de la base compartida: nadie recibe lo mismo dos veces aunque rastreen varios PCs.
- Envío desacoplado (`rastreador/correo.py`): `brevo` | `resend` | `smtp` | `fichero`. Se sale por API HTTPS
  a propósito: no depende de puertos SMTP que la red pueda tener cerrados ni de la autenticación básica de
  Microsoft 365, que está en retirada y choca con los Security Defaults de Entra ID.
- `proveedor: fichero` viene por defecto: deja los correos en `data/avisos/` para verlos antes de mandar nada.
- Consola: `python -m rastreador.avisos` (listar), `--probar correo@x`, `--enviar`, `--borrar correo@x`.
- `--sin-avisos` en el rastreo para saltárselos en una ejecución concreta.

## 1.13.1 (18/09/2026)
- **Corregido el fallo de la 1.13.0**: la instalación se paraba en «Get-Content: No se puede enlazar el argumento
  al parámetro 'Path' porque es nulo». Al mover la pregunta de la clave de Gemini más abajo se movió también la
  línea que definía `$envFile`, y el bloque del token de GitHub se quedaba sin ella. Ahora `$envFile` se define
  justo después de copiar el `.env`.
- El token de GitHub tampoco se pregunta ya en los PCs que solo consultan: como la clave de Gemini, solo se pide
  en el que va a rastrear.

## 1.13.0 (17/09/2026)
Objetivo: que un compañero nuevo solo tenga que hacer doble clic en `INSTALAR.bat`.

- **La carpeta compartida se localiza sola.** Como `INSTALAR.bat` se ejecuta *desde* la carpeta de OneDrive,
  el instalador usa el `_compartido` que tiene al lado, sin depender de `${OneDriveCommercial}` ni de cómo
  tenga cada PC montado OneDrive. Si no lo encuentra ahí, prueba lo que diga el `config.yaml` y, en último
  recurso, lo busca por los OneDrive del equipo. La ruta absoluta resultante se escribe en el `config.yaml`
  de esa instalación.
- **Datos desde el primer segundo**: al arrancar, el programa se trae la base compartida antes de generar el
  panel, así que el PC nuevo ve las convocatorias y licitaciones sin rastrear nada.
- **No se pregunta la clave de Gemini** si ya hay base compartida: los resúmenes viajan dentro de ella. Solo
  la pide el PC que va a rastrear. (`CLAVES.bat` sigue disponible para ponerla cuando se quiera.)
- **Salvaguarda contra pérdida de datos**: si la base local tiene menos registros que la compartida, no se
  sube. Antes, un PC que no hubiera podido traerse la compartida podía sobrescribirla con una casi vacía y
  cargarse el trabajo de todos.

## 1.12.0 (17/09/2026)
- **Corregido: el acceso directo abría el panel LOCAL de cada PC**, no el compartido. Por eso un compañero
  recién instalado veía 0 y 0 aunque otro ya hubiera rastreado: su panel local estaba vacío y solo se
  llenaba cuando rastreaba él. Ahora el acceso directo apunta al `index.html` de la carpeta compartida
  siempre que se vea desde ese PC, y el instalador dice cuál de los dos ha puesto.
- `actualizar_y_abrir.bat` (botón "⟳ Actualizar ahora") también abre el panel compartido si existe.
- **`COMPROBAR.bat`** (y `python -m rastreador.diagnostico`): dice qué ve ese PC — si resuelve la carpeta
  compartida y dónde, qué hay en la base local y en la compartida, quién actualizó por última vez, qué
  panel abre el acceso directo y si hay clave de Gemini — y termina con qué hacer.
- El instalador lanza ese diagnóstico al terminar.

## 1.11.3 (16/09/2026)
- **Corregido: el instalador no volvía a pedir la clave de Gemini.** Solo preguntaba cuando el `.env` parecía
  vacío, así que si en la primera instalación se pegaba mal o se dejaba algo escrito, reinstalar no servía de
  nada y no había forma de cambiarla. Ahora pregunta siempre y enseña la que hay (Intro = dejarla).
- **`CLAVES.bat`** (y `python -m rastreador.claves`): pone las claves y, sobre todo, **comprueba que la de
  Gemini funciona de verdad** con una llamada real a Google. Tener la clave escrita y que la clave sirva no
  son lo mismo: una clave mal pegada no da ningún error, solo deja todos los resúmenes en modo básico.
- El instalador hace esa misma comprobación al final y avisa si falla.

## 1.11.2 (16/09/2026)
- **`CARGAR_HISTORICO.bat`**: doble clic y hace la carga desde `general.fecha_historico` sobre la instalación
  de `%LOCALAPPDATA%\GHC\Radar`, sin tener que abrir una consola ni escribir rutas. Se puede cortar y relanzar.

## 1.11.1 (16/09/2026)
- El histórico arranca en **2025-01-01** (`general.fecha_historico`), no en 2024. La mitad de trabajo: 624 días
  en vez de 989. Para ir más atrás puntualmente: `--desde 2024-01-01`.

## 1.11.0 (16/09/2026)
### Histórico desde 2024 y filtro por año
- `python -m rastreador.run --historico` carga todo desde `general.fecha_historico` (2025-01-01) y
  `--desde AAAA-MM-DD` desde la fecha que se quiera. La consulta a la BDNS se trocea en ventanas de 45 días
  (`bdns.dias_por_consulta`) porque la API responde mal a periodos largos, y va registrando el avance.
- El panel tiene un selector **"Desde 20XX"** en subvenciones y en licitaciones: elegir 2025 muestra todo lo
  publicado del 01/01/2025 a hoy. Los años se sacan de los datos que haya.
- El filtro de estado pasa a **"Todas (incluidas cerradas)"** por defecto, para ver también las que ya acabaron.
- Licitaciones: `leer_historico()` usa los ficheros agregados de la PLACSP (`licitaciones.historico_urls`).
  Los feeds Atom normales no sirven para ir atrás: van ~1 día por página de 7-15 MB.

### Resúmenes más fiables
- El modelo debe devolver, por cada dato numérico o de plazo, la **frase literal** del documento de donde sale
  (campo `citas`). El programa **comprueba esas citas contra el texto real del PDF**: si no aparecen, es señal
  de invención y se marca.
- Las fechas y el presupuesto del resumen se **contrastan con los campos estructurados de la BDNS**; las
  discrepancias salen en un recuadro "Revisar" dentro de la ficha.
- **La confianza la calcula el programa**, no el modelo: según si hubo PDF, citas verificadas, campos en
  "No consta" y discrepancias. Antes el modelo se autocalificaba y casi siempre decía "alta".
- **Segunda pasada de verificación** (`llm.verificar: true`) cuando la confianza no sale alta: se le devuelve
  su JSON con el texto para que corrija lo que no esté respaldado.
- Campos nuevos en la ficha: ayuda máxima, procedimiento de concesión, plazo de ejecución, compatibilidad con
  otras ayudas, dónde se solicita, "queda por confirmar" y el desplegable de citas.
- Se leen hasta 250 páginas y 120.000 caracteres del PDF (antes 80 y 60.000) y se elige mejor el documento
  (bases reguladoras / convocatoria / extracto, en castellano, el más extenso).
- Los resúmenes "básicos" (los hechos sin clave de Gemini) se rehacen automáticamente en cuanto haya clave.

### Clasificación del contratista en licitaciones
- Columna nueva en la tabla y bloque en la ficha: **si la licitación exige clasificación y cuál**.
- Primero se busca en el propio anuncio (CODICE). Como lo normal es que no venga —se detalla en el PCAP—, se
  deduce: obras con valor estimado ≥ 500.000 € la exigen (art. 77.1.a LCSP); por debajo no; servicios y
  suministros tampoco (art. 77.1.b). Grupo y subgrupo se proponen por CPV y objeto (RD 1098/2001 art. 25) y la
  categoría por anualidad media (art. 26). Queda marcado como orientativo cuando es deducido.

### Instalación sin internet
- Las librerías (requests, pypdf, PyYAML y dependencias) van dentro del ZIP en `vendor\`: pip instala desde ahí
  y solo tira de internet si falla.
- `DESCARGAR_PYTHON.bat`: ejecutándolo una vez en un PC con internet deja el instalador de Python en `vendor\`,
  y a partir de ahí INSTALAR.bat funciona en cualquier PC aunque python.org esté bloqueado.

## 1.10.3 (16/09/2026)
- Carpeta compartida: `...\04_SOFTWARE\RADAR SUBVENCIONES Y LICITACIONES_CLAUDE\_compartido` (antes `..._IA`).
  Es una subcarpeta de la carpeta del programa: así la base compartida, el panel, `estado.json` y `radar.lock`
  no se mezclan con el código ni con INSTALAR.bat.

## 1.10.1 (15/09/2026)
- **La instalación abre el panel antes de rastrear**: ya no hay que esperar a que termine la carga para ver algo.
- **La primera carga usa `--inicial`**: como el ZIP trae una base de datos, la base no estaba "vacía" y el instalador
  cargaba solo 3 días en vez de los 120 que anunciaba. Corregido.
- **`data/rastreador.log` se escribe siempre** (antes solo lo generaba la tarea programada, redirigiendo la salida).
  Se recorta al pasar de 2 MB.
- PLACSP: se registra cuándo empieza cada página y cuánto tarda, y hay un tope de tiempo para la etapa
  (`licitaciones.tiempo_max_segundos`, 240 s por defecto); lo que falte se recoge en la ejecución siguiente.
- Los resúmenes ejecutivos se registran uno a uno ("Resumen 7/25: …"), para que no parezca que el programa se ha colgado.
- El instalador avisa del tiempo real de la primera carga (10-25 min), no de 3-6.

## 1.10.0 (15/09/2026)
- **Mapa propio, sin teselas externas**: OpenStreetMap devolvía 403 ("Access blocked") y el mapa salía empedrado de avisos.
  Ahora el panel dibuja España en SVG a partir de `assets/es-provincias.json` (52 provincias simplificadas, 117 KB).
  Desaparecen las dos dependencias externas del panel: Leaflet (cdnjs) y las teselas de OSM; el mapa funciona sin internet.
- Canarias en un inserto propio, las convocatorias de ámbito nacional en un recuadro aparte (ya no se solapan con Madrid),
  lista lateral "por territorio" ordenada por número, y burbujas proporcionadas al tamaño del lienzo (móvil incluido).
- **Zoom y desplazamiento** propios: botones +/− y ⤢ (volver a ver toda España), rueda del ratón, doble clic,
  arrastrar para mover y pellizco en móvil. Las burbujas y el grosor de las fronteras no crecen con el zoom.
- Pinchar una burbuja o una fila de la lista filtra la tabla; volver a pincharla quita el filtro.

## 1.9.3 (05/09/2026)
- Título de la página "RADAR SUBVENCIONES Y LICITACIONES GHC-PANSOGAL", favicon e icono de pantalla de inicio (móvil) con el radar.
- 1.9.2: el instalador vuelve a pedir claves vacías y muestra su estado al final.

## 1.9.0 (05/09/2026)
- Publicación automática del panel en GitHub Pages (`publicacion.github` + `GITHUB_TOKEN`), para abrirlo desde el móvil con una URL.

## 1.8.0 (05/09/2026)
- Panel adaptado a móvil: cabecera y filtros apilados, tablas en modo tarjeta, mapa reducido, ficha a pantalla completa.

## 1.7.1 (05/09/2026)
- Carpeta compartida: OneDrive/PANSOGAL/00_COMERCIAL_ESTUDIOS/01_ESTUDIOS/02_DOCUMENTOS DE TRABAJO/04_SOFTWARE/RADAR SUBVENCIONES Y LICITACIONES_IA (1.7.2).

## 1.7.0 (05/09/2026)
- Varios PCs pueden actualizar el mismo radar: la base de datos y el panel viven en la carpeta compartida de OneDrive
  (`general.carpeta_compartida`). Cada ejecución trae la base, rastrea y la devuelve; bloqueo `radar.lock` para que
  dos PCs no actualicen a la vez; en modo automático (`--auto`) se omite si el panel se actualizó hace < 6 h.
- Sustituye a `copias_panel` de la 1.6.0.

## 1.6.0 (05/09/2026)
- Copia automática del panel a una carpeta compartida (OneDrive/SharePoint) para que los compañeros lo abran sin instalar nada (`general.copias_panel`; el instalador lo pregunta).

## 1.5.0 (04/09/2026)
- El programa pasa a llamarse "Radar de subvenciones y licitaciones" (acceso directo, tarea programada, título del panel).
- Nuevo icono: un radar (assets/radar.ico, diseño propio).

## 1.4.0 (04/09/2026)
- Botón "⟳ Actualizar ahora" dentro del panel (protocolo radarghc://); desaparece el segundo acceso directo.
- Número de versión visible en la cabecera y el pie del panel, en el instalador y en este fichero.

## 1.3.0 (04/09/2026)
- Resúmenes ejecutivos con Google Gemini (clave gratuita de AI Studio) como proveedor por defecto; Perplexity desactivado.

## 1.2.0 (04/09/2026)
- Instalador Windows (INSTALAR.bat): Python automático, tarea programada 08:30, accesos directos, icono GHC. DESINSTALAR.bat.

## 1.1.0 (04/09/2026)
- Logos GHC y Pansogal en el panel. Selector Subvenciones / Licitaciones. Mapa de España por provincia/CCAA.
- Licitaciones de la PLACSP (feeds Atom CODICE) filtradas por CPV y texto, con ficha detallada y enlaces a pliegos.

## 1.0.0 (04/09/2026)
- Primera versión: BDNS + BOE + RSS de organismos, filtro temático, resúmenes ejecutivos, panel acumulado, despliegue Linux.
