# Instalador Windows del Radar de subvenciones y licitaciones GHC
# - Instala Python 3.12 si no existe (descarga oficial de python.org, instalacion de usuario)
# - Copia el programa a %LOCALAPPDATA%\GHC\Radar y crea el entorno virtual
# - Programa la tarea diaria a las 08:30 (se ejecuta al encender si el PC estaba apagado)
# - Crea en el escritorio el acceso directo "Radar de subvenciones y licitaciones" (abre el panel)
# - Registra el protocolo radarghc:// para que el botón "Actualizar ahora" del panel lance el rastreo

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Origen  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # carpeta del ZIP descomprimido
$Destino = Join-Path $env:LOCALAPPDATA "GHC\Radar"
$Tarea   = "Radar de subvenciones y licitaciones (GHC)"
$Nombre  = "Radar de subvenciones y licitaciones"
$Version = (Select-String -Path (Join-Path $Origen "rastreador\__init__.py") -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "$Nombre — instalador de la versión $Version" -ForegroundColor Cyan
$Hora    = "08:30"

function Paso($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Green }

# ---------------------------------------------------------------- Python
Paso "Comprobando Python"
$py = $null
function Probar-Python($exe, $arg) {
    try {
        $salida = if ($arg) { & $exe $arg -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null }
                  else      { & $exe      -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null }
        if ($LASTEXITCODE -eq 0 -and [int]("$salida".Trim()) -ge 311) { return $true }
    } catch {}
    return $false
}
foreach ($cand in @(@("py", "-3.12"), @("py", "-3"), @("python", $null))) {
    if (Probar-Python $cand[0] $cand[1]) { $py = $cand; break }
}
if (-not $py) {
    # 1) instalador de Python incluido en la carpeta (vendor\): instalacion sin internet
    $inst = $null
    $local = Get-ChildItem -Path (Join-Path $Origen "vendor") -Filter "python-3.*-amd64.exe" -ErrorAction SilentlyContinue |
             Sort-Object Name -Descending | Select-Object -First 1
    if ($local) {
        Paso "Python no encontrado: usando el instalador incluido ($($local.Name))"
        $inst = $local.FullName
    } else {
        # 2) si no viene incluido, se descarga
        Paso "Python 3.11+ no encontrado: descargando Python 3.12 (unos 25 MB)"
        $inst = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
        try {
            Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile $inst
        } catch {
            throw ("No hay Python en este PC, no viene incluido en vendor\ y no se ha podido descargar ($($_.Exception.Message)). " +
                   "Ejecuta DESCARGAR_PYTHON.bat en un PC con internet para dejarlo incluido en la carpeta, o instala Python 3.12 desde python.org.")
        }
    }
    Write-Host "Instalando Python (solo para este usuario)…"
    Start-Process -FilePath $inst -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1" -Wait
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = @("py", "-3.12")
    if (-not (Probar-Python $py[0] $py[1])) { throw "No se pudo instalar Python. Instalalo desde python.org y vuelve a ejecutar INSTALAR.bat" }
}
Write-Host "Usando: $($py -join ' ')"

# ---------------------------------------------------------------- copia
Paso "Copiando el programa a $Destino"
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
foreach ($d in @("rastreador", "assets", "deploy")) {
    Copy-Item -Path (Join-Path $Origen $d) -Destination $Destino -Recurse -Force
}
foreach ($f in @("config.yaml", "organismos.yaml", "requirements.txt", "README.md", ".env.example")) {
    Copy-Item -Path (Join-Path $Origen $f) -Destination $Destino -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $Destino "data"), (Join-Path $Destino "panel") | Out-Null
# conservar una base de datos y un .env anteriores si existen; copiar los del ZIP solo si no hay
if (-not (Test-Path (Join-Path $Destino ".env"))) {
    if (Test-Path (Join-Path $Origen ".env")) { Copy-Item (Join-Path $Origen ".env") $Destino }
    else { Copy-Item (Join-Path $Origen ".env.example") (Join-Path $Destino ".env") }
}
if ((-not (Test-Path (Join-Path $Destino "data\subvenciones.sqlite"))) -and (Test-Path (Join-Path $Origen "data\subvenciones.sqlite"))) {
    Copy-Item (Join-Path $Origen "data\subvenciones.sqlite") (Join-Path $Destino "data")
}
$envFile = Join-Path $Destino ".env"

# ---------------------------------------------------------------- carpeta compartida (OneDrive)
$cfgFile = Join-Path $Destino "config.yaml"
$cfgTxt  = Get-Content $cfgFile -Raw -Encoding UTF8
# ---------------------------------------------------------------- carpeta compartida
# Clave para que un PC nuevo no tenga que tocar nada: INSTALAR.bat se ejecuta DESDE la carpeta
# compartida de OneDrive, asi que la sabemos sin depender de variables de entorno. Se resuelve
# por este orden y la ruta absoluta que salga se escribe en el config.yaml instalado.
Paso "Localizando la carpeta compartida"
$comp = $null
$candidatos = @()
$candidatos += (Join-Path $Origen "_compartido")                 # 1) junto al INSTALAR.bat que se ha ejecutado
if ($cfgTxt -match 'carpeta_compartida: "([^"]*)"') {            # 2) lo que diga el config, con variables expandidas
    $cfgComp = $Matches[1] -replace "/", "\\"
    $cfgComp = $cfgComp -replace '\$\{OneDriveCommercial\}', $(if ($env:OneDriveCommercial) { $env:OneDriveCommercial } else { $env:OneDrive })
    if ($cfgComp -and $cfgComp -notmatch '[\$%]') { $candidatos += $cfgComp }
}
foreach ($c in $candidatos) { if ($c -and (Test-Path $c)) { $comp = (Resolve-Path $c).Path; break } }

if (-not $comp) {                                                # 3) ultimo recurso: buscarla en los OneDrive del PC
    foreach ($raiz in @($env:OneDriveCommercial, $env:OneDrive, $env:OneDriveConsumer) | Where-Object { $_ -and (Test-Path $_) }) {
        $hallado = Get-ChildItem -Path $raiz -Directory -Recurse -Depth 6 -Filter "_compartido" -ErrorAction SilentlyContinue |
                   Where-Object { $_.Parent.Name -like "RADAR SUBVENCIONES*" } | Select-Object -First 1
        if ($hallado) { $comp = $hallado.FullName; break }
    }
}

if ($comp) {
    Write-Host "  Carpeta compartida: $comp" -ForegroundColor Green
    New-Item -ItemType Directory -Force -Path $comp | Out-Null
    # se fija la ruta absoluta: asi este PC no depende de como tenga montado OneDrive
    $escapada = $comp -replace "\\", "/"
    $cfgTxt = [regex]::Replace($cfgTxt, '(?m)^(\s*carpeta_compartida:\s*).*$', ('${1}"' + $escapada + '"'))
    Set-Content -Path $cfgFile -Value $cfgTxt -Encoding UTF8
    $dbComp = Join-Path $comp "subvenciones.sqlite"
    if (Test-Path $dbComp) {
        Write-Host ("  Hay base compartida ({0:N1} MB): este PC la traera y vera los datos desde el primer momento." -f ((Get-Item $dbComp).Length/1MB)) -ForegroundColor Green
    } else {
        Write-Host "  Todavia no hay base compartida: este PC hara la primera carga." -ForegroundColor DarkGray
    }
} else {
    Write-Host "  AVISO: no se ha encontrado la carpeta compartida desde este PC." -ForegroundColor Yellow
    Write-Host "         El programa funcionara SOLO EN LOCAL. Ejecuta COMPROBAR.bat despues para ver por que." -ForegroundColor Yellow
}

# ---------------------------------------------------------------- clave Gemini
# Un PC que solo consulta no necesita clave: los resumenes viajan dentro de la base compartida.
# Solo se pregunta si este PC va a ser el que rastree (todavia no hay base compartida).
if ($comp -and (Test-Path (Join-Path $comp "subvenciones.sqlite"))) {
    Write-Host ""
    Write-Host "  Clave de Gemini: no hace falta en este PC. Los resumenes vienen en la base compartida." -ForegroundColor DarkGray
    Write-Host "  (si quieres que este PC tambien los genere, ejecuta CLAVES.bat cuando quieras)" -ForegroundColor DarkGray
} else {
    $envTxt  = Get-Content $envFile -Raw
    if ($envTxt -notmatch "GEMINI_API_KEY") { $envTxt += "`r`nGEMINI_API_KEY=AIza-xxxxxxxx`r`n" }   # .env de una versión anterior
    # Se pregunta SIEMPRE, mostrando lo que hay: antes solo preguntaba si la clave "parecia vacia",
    # asi que una clave mal pegada se quedaba ahi para siempre y no habia forma de cambiarla reinstalando.
    $actual = ""
    if ($envTxt -match "(?m)^\s*#?\s*GEMINI_API_KEY=\s*(\S+)\s*$") { $actual = $Matches[1] }
    $vacia = ($actual -eq "") -or ($actual -replace "[xX\-]", "" ) -eq "AIza" -or ($actual -match "^AIza-x+$")
    Paso "Clave de Google Gemini (gratuita) — resúmenes ejecutivos"
    if ($vacia) { Write-Host "  Ahora mismo: NO PUESTA (los resúmenes saldrán en modo básico)" -ForegroundColor Yellow }
    else        { Write-Host "  Ahora mismo: $($actual.Substring(0,[Math]::Min(8,$actual.Length)))…$($actual.Substring([Math]::Max(0,$actual.Length-4)))" -ForegroundColor Green }
    Write-Host "  Se obtiene en https://aistudio.google.com/apikey  ->  'Create API key' (cuenta de Google, sin tarjeta)."
    $k = Read-Host "  Pega tu GEMINI_API_KEY (Intro = dejar lo que hay)"
    if ($k.Trim()) {
        $envTxt = $envTxt -replace "(?m)^\s*#?\s*GEMINI_API_KEY=.*$", "GEMINI_API_KEY=$($k.Trim())"
        Set-Content -Path $envFile -Value $envTxt -Encoding UTF8
    } elseif ($vacia) {
        $envTxt = $envTxt -replace "(?m)^\s*#?\s*GEMINI_API_KEY=.*$", "# GEMINI_API_KEY="
        Set-Content -Path $envFile -Value $envTxt -Encoding UTF8
    }

    # ---------------------------------------------------------------- GitHub (opcional)
    $envTxt = Get-Content $envFile -Raw
    if ($envTxt -notmatch "GITHUB_TOKEN") { $envTxt += "`r`nGITHUB_TOKEN=github_pat_xxxxxxxx`r`n" }
    if ($envTxt -match "(?m)^\s*#?\s*GITHUB_TOKEN=\s*(github_pat_x+)?\s*$") {
        Paso "Token de GitHub para publicar el panel en GitHub Pages (opcional)"
        Write-Host "Solo hace falta en UN PC (el que publica). Token fine-grained con permiso Contents: Read and write."
        $g = Read-Host "Pega tu GITHUB_TOKEN (o pulsa Intro para omitir)"
        if ($g.Trim()) { $envTxt = $envTxt -replace "(?m)^\s*#?\s*GITHUB_TOKEN=.*$", "GITHUB_TOKEN=$($g.Trim())" }
        else { $envTxt = $envTxt -replace "(?m)^\s*#?\s*GITHUB_TOKEN=.*$", "# GITHUB_TOKEN=" }
        Set-Content -Path $envFile -Value $envTxt -Encoding UTF8
    }
}

# ---------------------------------------------------------------- entorno virtual
Paso "Creando entorno Python e instalando dependencias"
Set-Location $Destino
if ($py[1]) { & $py[0] $py[1] -m venv .venv } else { & $py[0] -m venv .venv }
if (-not (Test-Path ".\.venv\Scripts\python.exe")) { throw "No se pudo crear el entorno virtual (.venv)." }
$vendor = Join-Path $Origen "vendor"
$hayRuedas = (Test-Path $vendor) -and (Get-ChildItem $vendor -Filter *.whl -ErrorAction SilentlyContinue)
if ($hayRuedas) {
    Write-Host "Instalando dependencias desde la carpeta vendor (sin internet)…"
    & ".\.venv\Scripts\python.exe" -m pip install --quiet --no-index --find-links "$vendor" -r requirements.txt
}
if (-not $hayRuedas -or $LASTEXITCODE -ne 0) {
    if ($hayRuedas) { Write-Host "No ha funcionado desde vendor; se intenta desde internet…" -ForegroundColor Yellow }
    & ".\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    & ".\.venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
}
if ($LASTEXITCODE -ne 0) { throw "Fallo instalando dependencias (pip)." }

# ---------------------------------------------------------------- scripts de ejecución
$actualizar = Join-Path $Destino "actualizar.bat"
@"
@echo off
set PYTHONUTF8=1
cd /d "$Destino"
".venv\Scripts\python.exe" -m rastreador.run --auto >> "data\rastreador.log" 2>&1
"@ | Set-Content -Path $actualizar -Encoding ASCII

$actualizarYAbrir = Join-Path $Destino "actualizar_y_abrir.bat"
@"
@echo off
setlocal
set PYTHONUTF8=1
chcp 65001 >nul
cd /d "$Destino"
set "URL=%~1"
rem El panel usa el mismo protocolo para dos cosas: actualizar y guardar una suscripcion de avisos.
rem Se compara por sustitucion de cadena en vez de echo+findstr para no romper con los & de la URL.
if not "%URL%"=="%URL:avisos=%" (
  ".venv\Scripts\python.exe" -m rastreador.avisos --guardar "%URL%"
  rem se regenera el panel para que la lista de suscritos se vea al momento
  ".venv\Scripts\python.exe" -m rastreador.run --solo-panel --sin-avisos --sin-autoactualizar --log WARNING
  if exist "$comp\index.html" ( start "" "$comp\index.html" ) else ( start "" "panel\index.html" )
  echo.
  echo Listo. Para anadir a otra persona, cambia el correo en la pestana Avisos y vuelve a guardar.
  timeout /t 4 >nul
  exit /b 0
)
echo Actualizando el Radar de subvenciones y licitaciones... (2-5 minutos)
".venv\Scripts\python.exe" -m rastreador.run
if exist "$comp\index.html" ( start "" "$comp\index.html" ) else ( start "" "panel\index.html" )
"@ | Set-Content -Path $actualizarYAbrir -Encoding ASCII

# ---------------------------------------------------------------- tarea programada
Paso "Programando la ejecución diaria a las $Hora"
$accion  = New-ScheduledTaskAction -Execute $actualizar -WorkingDirectory $Destino
$disparo = New-ScheduledTaskTrigger -Daily -At $Hora
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
Unregister-ScheduledTask -TaskName $Tarea -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "Radar subvenciones GHC" -Confirm:$false -ErrorAction SilentlyContinue   # nombre antiguo
Register-ScheduledTask -TaskName $Tarea -Action $accion -Trigger $disparo -Settings $ajustes -Description "Rastreo diario de subvenciones y licitaciones de energía (GHC)" | Out-Null
Write-Host "Tarea '$Tarea' creada (si el PC está apagado a las $Hora, se ejecuta al encenderlo)."

# ---------------------------------------------------------------- accesos directos
Paso "Creando accesos directos en el escritorio"
$escritorio = [Environment]::GetFolderPath("Desktop")
$icono = Join-Path $Destino "assets\radar.ico"
$ws = New-Object -ComObject WScript.Shell

# El panel bueno es el de la carpeta compartida: es el que actualizan todos los PCs.
# El acceso directo YA NO abre el HTML directamente. Abre un .bat que primero se trae de GitHub la base
# que rastreo el servidor esta madrugada, regenera el panel y luego lo abre. Son unos diez segundos.
#
# Por que cambio: desde que rastrea GitHub Actions y no los PCs, el index.html de OneDrive solo se
# actualizaba cuando alguien ejecutaba el programa. Es decir, el acceso directo abria datos viejos
# mientras los avisos por correo llegaban puntuales: todo parecia ir bien y no iba.
$abridor = Join-Path $Destino "abrir_radar.bat"
@"
@echo off
rem Lo que ejecuta el acceso directo del escritorio: trae de GitHub la base que rastreo el
rem servidor esta madrugada, regenera el panel y lo abre. NO rastrea (de eso se encarga GitHub).
setlocal
set PYTHONUTF8=1
chcp 65001 >nul
cd /d "$Destino"
".venv\Scripts\python.exe" -m rastreador.abrir
if errorlevel 1 pause
"@ | Set-Content -Path $abridor -Encoding ASCII

$lnk = $ws.CreateShortcut((Join-Path $escritorio "$Nombre.lnk"))
if (Test-Path $abridor) {
    $lnk.TargetPath = $abridor
    $lnk.WorkingDirectory = $Destino
    Write-Host "  El acceso directo traera los datos del dia antes de abrir el panel." -ForegroundColor Green
} else {
    # plan B: comportamiento anterior, abrir el HTML tal cual
    $panelLocal = Join-Path $Destino "panel\index.html"
    $panelDestino = $panelLocal
    if ($comp -and (Test-Path $comp)) { $panelDestino = Join-Path $comp "index.html" }
    $lnk.TargetPath = $panelDestino
    $lnk.WorkingDirectory = Split-Path $panelDestino
    Write-Host "  AVISO: no encuentro abrir_radar.bat; el acceso directo abrira el panel tal cual." -ForegroundColor Yellow
}
$lnk.IconLocation = "$icono,0"
$lnk.Description = "$Nombre — GHC"
$lnk.WindowStyle = 7          # minimizado: la consola aparece un momento y se quita
$lnk.Save()

foreach ($viejo in @("Actualizar Radar GHC.lnk", "Radar GHC.lnk")) { Remove-Item (Join-Path $escritorio $viejo) -ErrorAction SilentlyContinue }   # nombres de versiones anteriores

# ---------------------------------------------------------------- protocolo radarghc:// (botón "Actualizar ahora" del panel)
Paso "Registrando el protocolo radarghc:// para el botón 'Actualizar ahora'"
$reg = "HKCU:\Software\Classes\radarghc"
New-Item -Path $reg -Force | Out-Null
Set-ItemProperty -Path $reg -Name "(Default)" -Value "URL:$Nombre"
Set-ItemProperty -Path $reg -Name "URL Protocol" -Value ""
New-Item -Path "$reg\DefaultIcon" -Force | Out-Null
Set-ItemProperty -Path "$reg\DefaultIcon" -Name "(Default)" -Value "$icono,0"
New-Item -Path "$reg\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path "$reg\shell\open\command" -Name "(Default)" -Value "`"$actualizarYAbrir`" `"%1`"" 

# ---------------------------------------------------------------- primera carga
$env:PYTHONUTF8 = "1"
# comprobacion real de la clave: una llamada minima a Google, para no descubrir dentro de un mes
# que todos los resumenes salian en modo basico porque la clave estaba mal pegada
Paso "Comprobando la clave de Gemini"
& ".\.venv\Scripts\python.exe" -m rastreador.claves --probar

# 1) generar y abrir el panel con lo que ya haya, para no dejar al usuario mirando una consola
Paso "Abriendo el panel"
& ".\.venv\Scripts\python.exe" -m rastreador.run --solo-panel
Start-Process (Join-Path $Destino "panel\index.html")
# 2) carga histórica completa (la base que viene en el ZIP no cuenta como "vacía", por eso hace falta --inicial)
Paso "Primera carga de datos (últimos 120 dias). Tarda entre 10 y 25 minutos: NO cierres esta ventana."
Write-Host "   Fuentes lentas: PLACSP descarga paginas de 7-15 MB y los resumenes esperan 7 s entre llamadas a Gemini." -ForegroundColor DarkGray
Write-Host "   Progreso detallado en $Destino\data\rastreador.log" -ForegroundColor DarkGray
& ".\.venv\Scripts\python.exe" -m rastreador.run --inicial
Write-Host ""
Write-Host "Instalación terminada ($Nombre v$Version)." -ForegroundColor Green
Write-Host "  Panel:      $Destino\panel\index.html  (acceso directo '$Nombre' en el escritorio)"
Write-Host "  Registro:   $Destino\data\rastreador.log"
Write-Host "  Configurar: $Destino\config.yaml  y  $Destino\.env"
$envFin = Get-Content $envFile -Raw
Write-Host ("  Clave Gemini:  " + $(if ($envFin -match "(?m)^GEMINI_API_KEY=AIza[^x\s]") { "puesta" } else { "NO puesta (resúmenes básicos)" }))
Write-Host ("  Token GitHub:  " + $(if ($envFin -match "(?m)^GITHUB_TOKEN=github_pat_[^x\s]") { "puesto" } else { "NO puesto (no se publica en GitHub Pages)" }))
Write-Host "  El panel ya esta abierto: pulsa F5 en el navegador para ver los datos recien cargados." -ForegroundColor Cyan
Write-Host ""
Paso "Comprobacion final"
& ".\.venv\Scripts\python.exe" -m rastreador.diagnostico
