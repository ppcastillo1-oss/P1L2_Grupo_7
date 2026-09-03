# AGENTS.md — reglas para agentes de IA en este repo

Laboratorio estructural digital 3D del edificio **LT2**, armado desde sus
planos de calculo `2024_22`. El modelo de la estructura vive en el repo
`A1P1.0_Grupo_7` y este laboratorio lo importa (ver el encabezado de
`src/modelo_edificio.py`); aca esta el laboratorio: notebook, las 5
verificaciones, el contrato JSON, el visor de Unity y el servidor.
Grupo 7. Semana 2.

## Units
SI: **m, kN, kPa**. Momento kN·m. `Ec = 4700·√f'c` con f'c en MPa → kPa.
Los planos DXF están en **cm**: convertir al leer, nunca después.

## Structural model
- Modelo global: **lineal elástico 3D**, 6 GDL por nodo.
- Las **losas NO se modelan con elementos finitos**.
- Carga de piso `q_G` = peso propio de losa + terminaciones uniformes.
- La carga de losa se transfiere por **áreas tributarias a 45°**.
- Muros como **elementos lineales equivalentes** (columna ancha).
- El análisis de capacidad RC es **separado** del modelo global.

## Architecture
```
OpenSees (Python) → JSON (fuente de verdad) → Unity (muestra) → AR
```
- OpenSees es dueño del análisis. Unity es dueño de la visualización.
- **Nunca meter cálculo estructural en C#.**
- Si se pierde la escena Unity, el modelo debe reconstruirse desde `data/`.

## Verification rules
1. **Equilibrio** tras cualquier cambio de cargas: `Σ F = Σ R`, error < 1e-6.
2. **Conservación tributaria**: `w·L = q·A` viga por viga.
3. **Suma de áreas tributarias = área de planta**, error < 1e-9.
4. **Unidades** consistentes.
5. **Ejes locales**: visualizarlos, no suponerlos.
6. **Nunca** modificar resultados de referencia sin justificarlo.
7. Todo cambio importante necesita una verificación numérica contra un
   valor conocido.

## Ciclo de trabajo
`Issue → Plan → Build → Test → Review → Merge`

**Buen encargo:** "Implementar la lectura de `tributary_areas.json`. No
modificar el esquema. Verificar que la suma de cargas transferidas sea
igual a `q·A` dentro de 1e-10."

**Mal encargo:** "Haz la herramienta de áreas tributarias."

---

## Trampas ya pisadas (no volver a caer)

### `eleForce` vs `localForce`
`ops.eleForce(tag)` devuelve fuerzas en ejes **GLOBALES**. Para N/V/M de
una barra hay que usar:
```python
ops.eleResponse(tag, 'localForce')
# [N_i, Vy_i, Vz_i, T_i, My_i, Mz_i,  N_j, ...]
```
Esto engañó al proyecto en Semana 1: hacía que una columna pareciera
dominada por **cortante** (imposible bajo gravedad; lo dominante es el
axial) y que una viga en Y **no flectara** (su momento caía en la casilla
`Mx` global).

### El equilibrio NO valida el reparto de cargas
Si le das el doble a una viga y la mitad a otra, la suma de reacciones
cierra igual con error 1e-14. El reparto 50/50 de Semana 1 descargaba la
viga larga un 40 % y el equilibrio nunca lo delató. Por eso existe
`tests/test_areas_tributarias.py`.

### `equalDOF` no es un diafragma rígido
`equalDOF(m, s, 1, 2, 6)` obliga a **mismo `ux`** en todo el piso: eso es
un piso que no puede rotar. El diafragma real (`rigidDiaphragm`) cumple
`ux_i = ux_m − rz·(y_i − y_m)`. Verificar con carga **excéntrica**: bajo
gravedad el giro es ≈ 0 y la prueba no prueba nada.

### `constraints('Transformation')` es obligatorio
Con `rigidDiaphragm` hay restricciones multipunto; `Plain` no las trata.

### `vecxz` de un muro
Orienta el eje fuerte. `I_fuerte/I_débil = (L/t)²` — hasta **747** en
este edificio. Un muro mal orientado aporta 747 veces menos rigidez y el
modelo **no avisa**.

### Un muro suelto no aporta nada
Los nodos de muro deben entrar al **diafragma de su piso**. Si no, el
muro queda como voladizo al lado del edificio. Chequeo: al agregar los
muros el giro de piso debe **bajar** (aquí bajó 54 %).

### `JsonUtility` falla en silencio
Un campo C# que no calza con la clave del JSON no da error ni warning:
queda en su valor por defecto. Un `uz` mal escrito → deformada plana.
`tests/test_contrato_unity.py` compara los `.cs` contra el JSON real.

### Swap de ejes
OpenSees usa **Z vertical**, Unity usa **Y vertical**:
`Unity(x, z_os, y_os)`. Los **vectores** (ejes locales) deben pasar por
el mismo swap que las posiciones, o apuntan mal aunque el modelo se vea
bien.

### `J` de torsión
Saint-Venant, no `min(Iy,Iz)·0.3` (que no es ninguna fórmula y
subestimaba J 5.6 veces).

### El input de Unity puede estar "apagado"
`ProjectSettings.asset` → `activeInputHandler`: `0` = clásico, `1` = solo
Input System nuevo, `2` = ambos. Los scripts usan la API clásica
(`Input.GetMouseButton`); con `1` **lanzan excepción en runtime** y no se
puede ni orbitar ni seleccionar, aunque todo compile sin errores. Debe
quedar en `2`.

### `-batchmode` y Play son incompatibles
No se puede "apretar Play" desde fuera de Unity. Para mostrar el modelo
sin abrir el editor hay que **compilar una app standalone**
(`ConstruirApp.Construir`); eso sí se automatiza. Lo hace
`src/lanzar_unity.py`.

### Compilar Unity sin abrir el editor
```
Unity.exe -batchmode -quit -nographics -projectPath <dir> -logFile <log>
```
Verificar que exista `Library/ScriptAssemblies/Assembly-CSharp.dll`: si no
está, **no compiló nada** y un log "sin errores" no significa nada. Ojo:
la primera importación tarda ~10 min y el proceso sigue vivo aunque el
comando reporte exit 0; lanzar un segundo Unity en paralelo falla con
código 1 (proyecto bloqueado).

### Los shaders se eliminan al compilar
El visor no usa materiales de asset: los crea en runtime con
`new Material(Shader.Find("Universal Render Pipeline/Lit"))`. Pero al
compilar, Unity **elimina** los shaders que no ve referenciados por
ningún material de la escena, y entonces `Shader.Find()` devuelve `null`.

Síntoma: **en el editor se ve bien y la app compilada no dibuja nada**,
con `"No encontre ningun shader utilizable"` + `ArgumentNullException` en
el `Player.log`. Es un error que **solo existe en la build**.

Solución: los shaders van en *Graphics Settings → Always Included
Shaders*. Lo hace solo `ConstruirApp.AsegurarShadersIncluidos()`.

> Lección general: compilar sin errores **no** significa que la app
> funcione. Hay que ejecutarla y leer el `Player.log`
> (`%USERPROFILE%\AppData\LocalLow\<empresa>\<producto>\Player.log`, o
> pasarle `-logFile <ruta>` al ejecutable). Y hay que cerrarla **con
> gracia**: si se mata a la fuerza, el log queda sin vaciar y parece que
> no pasó nada.

### Los polígonos tributarios no miden todos lo mismo
`JsonUtility` no lee listas de listas, así que los polígonos van
**concatenados** en `vertices`. Es tentador partirlos dividiendo
`vertices.Length / n_poligonos`, pero **está mal**: una viga interior
toma un **trapecio** de un paño (4 vértices) y un **triángulo** del otro
(3), o sea 7 en total, y `7 / 2 = 3` mezcla vértices de un polígono con
los del otro → **líneas cruzadas que no existen** en el diagrama.

Afectaba a 88 de las 656 vigas. Por eso el JSON exporta `tamanos`
(vértices por polígono) y `AreaTributaria.Poligonos()` lo usa.
`test_contrato_unity.py` verifica que existan, que `sum(tamanos)` calce
y —importante— que **haya de verdad vigas con polígonos de distinto
tamaño**, para que el test no pase por vacío.

### Un muro dibujado como barra no se puede revisar
El muro se idealiza como "columna ancha": UNA barra en su eje
baricéntrico. Correcto para el cálculo, pero si se dibuja tal cual se ve
una columna flaca en medio del vano y no hay forma de juzgar si está
donde dice el plano. El JSON exporta `largo` y `espesor` del muro y el
visor lo dibuja con su tamaño real, orientado con **el mismo `vecxz`**
con que OpenSees orientó su inercia fuerte — así lo que se ve y lo que
se calculó no pueden desincronizarse.

### El JSON debe describir el MISMO problema que resolvió Python
Si se modifica el modelo desde Unity, el reanálisis lo hace el servidor
**reconstruyendo desde el JSON**. Si el JSON no describe exactamente el
mismo problema, devuelve otros números y **no hay ningún error**. Pasó
dos veces:

1. El caso G exportado traía solo la carga de losa, **sin peso propio**
   de vigas, columnas y muros → 10.04 mm donde Python daba 11.78.
2. Las inercias se exportaban **ya cruzadas**, y el servidor —que cruza
   según la geometría del elemento— las cruzaba **una segunda vez** →
   12.17 mm.

**Convención del contrato:** `Iy`/`Iz` van en **ejes de la sección**, no
en los huecos de `ops.element()`. Quien construya el modelo aplica el
cruce: horizontal → `Iy_slot = sec.Iz`; vertical → `Iy_slot = sec.Iy`.

`tests/test_reanalisis.py` compara el reanálisis contra la deformada
precalculada, nodo por nodo. Es la única forma de cazar esto.

### El JSON tiene que llegar a la build
El visor lee `StreamingAssets/modelo_unity.json`. Al recalcular el modelo
hay que copiarlo tanto al proyecto como a
`build/LaboratorioEstructural_Data/StreamingAssets/`. Lo hace
`lanzar_unity.sincronizar_json()`. Si se omite, el visor muestra el modelo
viejo **sin avisar**.

---

## Registro de uso de IA

### Semana 2
- **Tareas:** áreas tributarias a 45° con polígonos; extracción de muros
  desde la capa `RLE-MURO` del DXF; diafragma rígido correcto; capas de
  QA en Unity; contrato JSON.
- **Verificación:** las 5 del Lab pasan (`verificar_lab2.py`); tests de
  áreas tributarias y de contrato JSON pasan.
- **Revisión crítica — errores detectados y corregidos:**
  1. El emparejado de caras de muro agrupaba por dirección redondeada y
     partía en dos grupos las caras de un mismo muro cuando el CAD las
     dejaba con décimas de grado de diferencia. Salían **muros
     duplicados con espesores distintos** (0.10 y 0.50 m para el mismo
     muro). Se detectó revisando la tabla de salida a ojo. Corregido con
     tolerancia angular y un índice global de caras ya usadas.
  2. Los muros se creaban como líneas verticales **sin conectar** al
     marco: eran voladizos sueltos. Se detectó al notar que agregar
     muros no cambiaba la respuesta. Corregido ligándolos al diafragma.
  3. El peso propio de los muros quedó inicialmente en `W = 0.0`
     (placeholder). Se detectó al revisar el código antes de correr.

### Semana 1
Ver `reports/semana01.md` en el repo `A1P1.0_Grupo_7`.
