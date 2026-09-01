# AGENTS.md — reglas para agentes de IA en este repo

Laboratorio estructural digital 3D del Edificio de Ingeniería (UANDES).
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
