# ================================================================
#  dwg_a_dxf.ps1  -  Conversion headless DWG -> DXF
# ================================================================
#  Backend: accoreconsole.exe (el motor de AutoCAD sin interfaz).
#  No abre AutoCAD, no necesita pantalla, y respeta la licencia
#  instalada en la maquina.
#
#  Uso:
#    .\dwg_a_dxf.ps1 -Entrada <carpeta con .dwg> -Salida <carpeta .dxf>
#
#  ----------------------------------------------------------------
#  DOS TRAMPAS QUE COSTARON HORAS (no borrar estos comentarios)
#  ----------------------------------------------------------------
#  1. accoreconsole SE CUELGA si se lanza con stdout conectado a un
#     pipe (por ejemplo `accoreconsole ... | tail`). No falla: queda
#     colgado para siempre sin escribir nada. Hay que lanzarlo con
#     Start-Process y redirigir la salida A UN ARCHIVO.
#
#  2. En un script .scr de AutoCAD el ESPACIO equivale a ENTER. Si la
#     ruta de salida tiene espacios ("Metodos computacionales"), el
#     nombre de archivo se parte en varios "enter" y el comando queda
#     esperando input que nunca llega -> timeout.
#     Por eso el DXF se escribe primero en una carpeta temporal SIN
#     espacios y recien despues se mueve al destino final.
# ================================================================
param(
    [Parameter(Mandatory = $true)][string]$Entrada,
    [Parameter(Mandatory = $true)][string]$Salida,
    [string]$Filtro = '*.dwg',
    [int]$TimeoutSeg = 300,
    [switch]$Rehacer
)

$ErrorActionPreference = 'Stop'

# ---- 1. Encontrar el motor -------------------------------------
$candidatos = @(
    'C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe',
    'C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe',
    'C:\Program Files\Autodesk\AutoCAD 2024\accoreconsole.exe',
    'C:\Program Files\Autodesk\AutoCAD 2023\accoreconsole.exe'
)
$acc = $candidatos | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $acc) {
    throw "No encontre accoreconsole.exe. Rutas probadas:`n  " + ($candidatos -join "`n  ")
}
Write-Output "Motor: $acc"

# ---- 2. Preparar carpetas --------------------------------------
if (-not (Test-Path $Entrada)) { throw "No existe la carpeta de entrada: $Entrada" }
New-Item -ItemType Directory -Force -Path $Salida | Out-Null

# Carpeta de trabajo SIN espacios (ver trampa 2).
$tmp = Join-Path $env:TEMP ('dwg2dxf_' + [guid]::NewGuid().ToString('N').Substring(0, 12))
if ($tmp -match ' ') { throw "El TEMP tiene espacios ($tmp); elegir otra carpeta de trabajo." }
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

$dwgs = @(Get-ChildItem -Path $Entrada -Filter $Filtro -File | Sort-Object Name)
Write-Output "Archivos a convertir: $($dwgs.Count)"

$ok = 0; $fallo = 0; $saltado = 0

foreach ($d in $dwgs) {
    $destino = Join-Path $Salida ($d.BaseName + '.dxf')
    if ((Test-Path $destino) -and (-not $Rehacer)) {
        Write-Output ("SALTO   {0}  (ya existe)" -f $d.Name)
        $saltado++
        continue
    }

    $dxfTmp = Join-Path $tmp ($d.BaseName + '.dxf')
    $scr = Join-Path $tmp ($d.BaseName + '.scr')

    # FILEDIA 0 = responder por linea de comandos en vez de abrir dialogo.
    # 16 = decimales de precision (maxima; no perder coordenadas).
    Set-Content -Path $scr -Encoding ascii -Value @(
        '_.FILEDIA', '0', '_.DXFOUT', $dxfTmp, '16', '_.QUIT'
    )

    $t0 = Get-Date
    $p = Start-Process -FilePath $acc `
        -ArgumentList @('/i', "`"$($d.FullName)`"", '/s', "`"$scr`"", '/l', 'en-US') `
        -NoNewWindow -PassThru `
        -RedirectStandardOutput (Join-Path $tmp "$($d.BaseName).out") `
        -RedirectStandardError  (Join-Path $tmp "$($d.BaseName).err")

    if (-not $p.WaitForExit($TimeoutSeg * 1000)) {
        $p.Kill()
        Write-Output ("TIMEOUT {0}  (>{1}s)" -f $d.Name, $TimeoutSeg)
        $fallo++
        continue
    }
    $seg = [int]((Get-Date) - $t0).TotalSeconds

    if (Test-Path $dxfTmp) {
        Move-Item -Path $dxfTmp -Destination $destino -Force
        $mb = [math]::Round((Get-Item $destino).Length / 1MB, 2)
        Write-Output ("OK      {0} -> {1}.dxf   {2} MB   {3}s" -f $d.Name, $d.BaseName, $mb, $seg)
        $ok++
    }
    else {
        Write-Output ("FALLO   {0}  ({1}s)  ver {2}" -f $d.Name, $seg, (Join-Path $tmp "$($d.BaseName).out"))
        $fallo++
    }
}

Write-Output ''
Write-Output ("Resumen: {0} convertidos, {1} saltados, {2} fallidos" -f $ok, $saltado, $fallo)
if ($fallo -eq 0) { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
else { Write-Output "Logs de los fallidos en: $tmp" }
