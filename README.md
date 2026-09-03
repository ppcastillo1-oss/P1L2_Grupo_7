# P1 — Semana 2 · Edificio completo + gravedad + viewer Unity

Laboratorio estructural digital del **edificio LT2**, armado entero desde sus
planos de cálculo `2024_22`.
Grupo 7 — Pedro Castillo, Monserrat Cubillos, Eduardo Vergara.

> **Regla de oro:** OpenSees **calcula** → el JSON es la **fuente de verdad** →
> Unity solo **muestra**. Nunca se mete cálculo estructural en C#.

> **Cambio de estructura.** Este laboratorio modelaba el Edificio de Ingeniería
> idealizado como una grilla regular (8 × 6 ejes × 9 niveles, una columna en cada
> cruce). Ahora modela el **LT2**, que no es una grilla: 8 pilares y 9 muros sin
> simetría, vigas que se cruzan entre ellas, una caja de ascensores y una planta
> que no es un rectángulo lleno. El código del laboratorio es el mismo; lo que
> cambió es de dónde sale la estructura. Ver el encabezado de
> `src/modelo_edificio.py` y la §1 de [reports/semana02.md](reports/semana02.md).

---

## Estado

| | |
|---|---|
| Nodos | 247 |
| Elementos | 430 (40 columnas, 230 vigas, 45 muros, 115 brazos rígidos) |
| Apoyos | 17 empotrados en z = −7.97 |
| Diafragmas rígidos | 5 (uno por piso) |
| Niveles | −7.97 · −4.01 · −0.05 · +3.91 · +7.87 · +11.83 |
| Área de losa | 496.87 m² por piso (suma de los paños detectados) |
| q_G | 6.300 kN/m² plantas tipo · 5.711 kN/m² cielo 4° piso (del plano de cargas) |
| Carga total G | 34 011.06 kN |
| Error de equilibrio | 8.7 × 10⁻⁸ kN |
| UZ máximo | −6.72 mm |

Las **5 verificaciones del Lab pasan**: `python verificar_lab2.py`

### El modelo del LT2

La estructura la construye `src/modelo_lt2.py` con `malla.py`, `panos.py` y el
ingestor de planos `src/planos/`. El desarrollo de ese modelo vive en
[A1P1.0_Grupo_7](https://github.com/bitscochits/A1P1.0_Grupo_7) y de ahi se
**copia** a este repo: el laboratorio se entrega solo, asi que quien clone este
repositorio puede correrlo sin bajar nada mas.

Sus propias verificaciones tambien estan aca:

```powershell
python verificar_lt2.py     # 36 checks del modelo del LT2
python test_planos.py       # 51 checks del ingestor de planos
```

---

## Cómo correrlo

### 1. Una sola vez, después de clonar

```bash
.\setup.ps1
```

Crea el entorno virtual `.venv` dentro del repo, instala todo y avisa si
falta Unity. Si PowerShell bloquea el script, correr antes en esa misma
terminal:

```bash
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2. El notebook (recomendado)

Todo el laboratorio de principio a fin, celda por celda: geometría →
áreas tributarias (con gráficos) → OpenSees → verificaciones → JSON →
**abre el visor 3D desde el propio notebook**.

Hay dos formas equivalentes; da lo mismo cuál se use.

**a) VS Code** — todo en una ventana, sin navegador:

```bash
code .
```

Abrir `laboratorio.ipynb`, y arriba a la derecha en **Select Kernel**
elegir el `.venv` del repo (`.venv\Scripts\python.exe`). Requiere la
extensión *Jupyter* de Microsoft. El archivo `.vscode/settings.json` ya
deja apuntado el intérprete y la carpeta de trabajo.

**b) Jupyter Lab** — en el navegador:

```bash
.\lab.ps1
```

En ambos casos: `Run All` para correrlo entero, o celda por celda para
la defensa.

### 3. O por línea de comandos

Las 5 verificaciones (carga de losa, suma de áreas tributarias,
conservación, equilibrio, compatibilidad del diafragma):

```bash
.\.venv\Scripts\python.exe verificar_lab2.py
```

Abrir el visor sin notebook:

```bash
.\.venv\Scripts\python.exe src\lanzar_unity.py
```

Para regenerar el JSON que consume Unity:

```bash
python src/exportar_unity.py
```

Para re-extraer los muros desde los planos:

```bash
python src/extraer_muros_dxf.py
```

Tests:

```bash
python tests/test_areas_tributarias.py
```

```bash
python tests/test_contrato_unity.py
```

---

## Para entender el modelo

📘 **[`docs/GUIA_conceptos.md`](docs/GUIA_conceptos.md)** — qué es cada
cosa y por qué está ahí: GDL, apoyos, ejes locales, IDs, diafragma
rígido, áreas tributarias, muros equivalentes, superposición, las 5
verificaciones y las limitaciones del modelo.

Material de estudio para la **defensa individual**: una demo que
funciona pero que el grupo no sabe explicar no cuenta como lograda.

---

## Estructura

```
src/
├── modelo_edificio.py      ← FUENTE DE VERDAD: geometría, secciones, cargas
├── areas_tributarias.py    ← reparto 45°, polígonos y conservación
├── extraer_muros_dxf.py    ← muros desde el plano real (capa RLE-MURO)
├── exportar_unity.py       ← contrato JSON OpenSees → Unity
└── servidor_opensees.py    ← servidor Flask (Honors, opcional)

data/
├── muros.json              ← 24 muros extraídos del DXF
└── modelo_unity.json       ← el modelo + resultados + áreas tributarias

unity/Assets/Scripts/
├── ModeloEstructural.cs    ← clases de datos (fuente de verdad en C#)
├── VisorEstructura.cs      ← dibuja el modelo
├── VisorQA.cs              ← capas de QA + inspector de áreas tributarias
└── CamaraOrbital.cs        ← navegación

tests/                      ← áreas tributarias y contrato JSON↔Unity
verificar_lab2.py           ← las 5 verificaciones del Lab
reports/semana02.md         ← informe
```

---

## Lo que cambió respecto de la Semana 1

**1. Áreas tributarias a 45°** (antes: reparto 50/50).
En los paños alargados de este edificio (hasta 10.00 × 3.34 m) el 50/50
descargaba la viga larga un 40 %. La mayor discrepancia entre ambos
métodos llega a **36 m²** en una sola viga.
El equilibrio global **no** detecta este error: la carga total es la
misma, lo que estaba mal era el reparto. Por eso hay tests dedicados.

**2. Cargas distribuidas** (`eleLoad -beamUniform`) en vez de cargas
puntuales en los nodos. La losa descarga *a lo largo* de la viga.

**3. Diafragma rígido de verdad** (`rigidDiaphragm`) en vez de
`equalDOF(m, s, 1, 2, 6)`, que obligaba a que todos los nodos del piso
tuvieran el mismo `ux` — eso no es un diafragma rígido, es un piso que
no puede rotar.

**4. Muros equivalentes** extraídos del plano (capa `RLE-MURO`),
modelados como columna ancha y ligados al diafragma de cada piso.
Al agregarlos, el giro de piso bajó de 8.20 × 10⁻⁵ a 3.81 × 10⁻⁵ rad:
los muros efectivamente toman torsión.

**5. Torsión J por Saint-Venant** en vez de `min(Iy,Iz)*0.3`, que no
corresponde a ninguna fórmula y subestimaba J unas 5.6 veces.

---

## El viewer (Unity)

**Versión fijada: Unity 6000.5.10f1.** No actualizar durante el proyecto.

Abrir `unity/` con esa versión. La escena se arma sola:

> menú **Laboratorio → Configurar escena**

Eso conecta `Visor` (VisorEstructura + VisorQA) con la `Main Camera`
(CamaraOrbital) y guarda la escena. Es idempotente: correrlo dos veces
no duplica nada. También se puede hacer sin abrir el editor:

```bash
Unity.exe -batchmode -quit -projectPath unity -executeMethod ConfigurarEscena.Configurar
```

El JSON ya está en `Assets/StreamingAssets/`.

**Controles:** arrastrar con el botón izquierdo orbita · botón derecho
o central panea · rueda hace zoom · `F` encuadra todo el modelo ·
**click sin arrastrar** selecciona una barra.

> Nota: `activeInputHandler` está en **Both**. El proyecto trae el
> paquete Input System, pero los scripts usan la API clásica
> (`Input.GetMouseButton`); con el modo "solo Input System nuevo" esas
> llamadas lanzan excepción en runtime y no se podría ni orbitar ni
> seleccionar.

Capas que se prenden y apagan: nodos, vigas, columnas, muros, **apoyos,
diafragmas, ejes locales, IDs, áreas tributarias**. Hay filtro por piso
(con 1 232 elementos, mirar el edificio entero no sirve para revisar).

**Perfiles reales.** El toggle *Perfiles (b × h)* dibuja cada barra con
su sección verdadera en vez de un cilindro genérico: se ve que una viga
es 30×80 y otra 30×60. La orientación usa los **ejes locales exportados
desde Python**, así que el perfil que se ve es literalmente el que se
calculó.

**Deformada con escala.** Toggle *Ver deformada* + slider de ×1 a ×2000
(y botones ×1 / ×100 / ×500 / ×1000). Los desplazamientos reales son de
milímetros sobre un edificio de 28 m: sin amplificar no se ve nada. La
escala es **puramente gráfica** — no toca el análisis.

### Modificar el modelo en vivo (opcional)

Se puede mover nodos, cambiar secciones, crear y borrar barras, y pedir
un **reanálisis real**. Como la app compilada no puede correr OpenSees
(es Python), Unity manda el modelo por HTTP y Python devuelve los
resultados — la misma separación de siempre, ahora en vivo.

Hay que levantar el servidor **antes** de abrir el visor:

```bash
.\.venv\Scripts\python.exe src\lanzar_unity.py servidor
```

Escucha solo en `127.0.0.1`. Sin él el visor funciona igual; solo no se
puede reanalizar.

> `tests/test_reanalisis.py` verifica que reanalizar desde el JSON
> reproduzca **exactamente** el resultado de `modelo_edificio.py`
> (diferencia 5×10⁻⁹ m). Sin esa comprobación, el servidor puede
> resolver un problema levemente distinto y nadie se entera.

Click sobre una barra y el panel contesta:
`elementTag`, tipo, nodos, largo, **restricciones de cada apoyo por GDL**,
**ejes locales**, **área tributaria**, **kN de losa que le llegan** y el
chequeo `w·L = q·A`.
