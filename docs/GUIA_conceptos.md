# Guía de conceptos — qué es cada cosa y por qué está ahí

> Material de estudio para la **defensa individual**. El profesor puede
> preguntarle a cualquier integrante sobre cualquier parte, y una demo
> que funciona pero que el grupo no sabe explicar *no cuenta como
> lograda*.
>
> Cada sección dice **qué es**, **por qué importa** y **dónde está en el
> código**.

---

## 1. Nodo y grados de libertad (GDL)

Un **nodo** es un punto del modelo. En un modelo 3D de barras, cada nodo
tiene **6 grados de libertad**: tres desplazamientos y tres giros.

```
    1: ux   desplazamiento en X        4: rx   giro alrededor de X
    2: uy   desplazamiento en Y        5: ry   giro alrededor de Y
    3: uz   desplazamiento en Z        6: rz   giro alrededor de Z
```

"Grado de libertad" = una forma independiente en que ese punto se puede
mover. Resolver la estructura es justamente **encontrar esos 6 números
por cada nodo**.

Nuestro modelo tiene 656 nodos → unas 3 936 incógnitas.

**En el código:** `ops.model('basic', '-ndm', 3, '-ndf', 6)` en
[`src/modelo_edificio.py`](../src/modelo_edificio.py).
`ndm = 3` son las dimensiones del espacio; `ndf = 6` los GDL por nodo.

> **Si te preguntan:** "¿por qué 6 y no 3?" → Porque una barra no solo
> se traslada: también gira. Si solo hubiera traslaciones, no existiría
> el momento flector y las vigas no podrían trabajar a flexión.

---

## 2. Apoyos (restricciones)

Un apoyo **no es un dibujito**: es una lista explícita de qué GDL están
impedidos.

```
ops.fix(nodo, 1, 1, 1, 1, 1, 1)
             ux uy uz rx ry rz      1 = restringido, 0 = libre
```

- `[1,1,1,1,1,1]` → **empotramiento**: no se mueve ni gira.
- `[1,1,1,0,0,0]` → **rótula**: no se traslada pero puede girar.

En este modelo los 72 nodos de fundación están **empotrados** (48 de
columnas + 24 de muros).

**En el visor:** al hacer click en una barra, el panel muestra
`APOYO [1 1 1 1 1 1]` en cada nodo. Eso es lo que hay que contestar si
preguntan "¿qué apoyos tiene?" — no "está empotrado" a ojo.

> **Si te preguntan:** "¿cómo sabes que ese apoyo está bien?" → Un apoyo
> correcto tiene **desplazamiento cero** y **reacción distinta de cero**.
> Si un apoyo se mueve, le falta una restricción; si su reacción es
> cero, no está tomando carga.

---

## 3. Ejes locales vs. ejes globales

Los **ejes globales** (X, Y, Z) son los del edificio completo y no
cambian. Los **ejes locales** van pegados a cada barra:

```
    local x  →  siempre a lo largo de la barra (del nodo i al j)
    local y  →  perpendicular
    local z  →  perpendicular al otro
```

**Por qué importa:** las preguntas de ingeniería son locales. "¿Cuánto
axial tiene esta columna?" tiene sentido a lo largo de *su* eje, no en la
X del edificio. Si preguntas "¿cuál es la fuerza en X global de esta
columna?", la respuesta cambia según cómo esté inclinada — no significa
nada por sí sola.

### El vector `vecxz`

Conocer los nodos i y j solo define el eje **x** local. Faltan `y` y `z`:
la barra podría estar "girada" sobre su propio eje. Eso lo define
`vecxz`, un vector auxiliar:

```python
ops.geomTransf('Linear', tag, vx, vy, vz)
```

- Columnas y muros: `vecxz = (1, 0, 0)`
- Vigas: `vecxz = (0, 0, 1)`

**Regla que no se puede romper:** `vecxz` **nunca** puede ser paralelo al
eje de la barra. Para una columna vertical, `(0,0,1)` sería paralelo a
ella misma y OpenSees falla.

**En el código:** [`src/exportar_unity.py`](../src/exportar_unity.py),
función `ejes_locales()`, calcula los tres versores y los exporta.
**Unity no los deduce, los recibe** — deducirlos en C# sería copiar la
convención de OpenSees, y esa copia terminaría divergiendo sin que nadie
se entere.

> **Error clásico ya cometido en este proyecto:** `ops.eleForce(tag)`
> devuelve fuerzas en ejes **globales**. Para leer N/V/M hay que usar
> `ops.eleResponse(tag, 'localForce')`. Con el primero, una columna
> parecía dominada por *cortante* (imposible bajo gravedad: lo dominante
> es el **axial**) y una viga en Y parecía **no flectar**, porque su
> momento caía en la casilla `Mx` global.

---

## 4. IDs (`nodeTag` y `elementTag`)

Cada nodo y cada elemento tiene un **número único**. No es decoración:
es lo que permite que el mismo elemento sea *la misma cosa* a lo largo de
toda la cadena.

```
plano  →  data/  →  OpenSees  →  JSON  →  Unity  →  AR
                    elementTag 417 es SIEMPRE el mismo elemento
```

**Por qué importa:** cuando el profesor apunta a una barra y pregunta
"¿qué elementTag tiene?", esa respuesta tiene que servir para ir al
JSON, al script de Python y al resultado. Si Unity usara su propio
identificador interno (`GetInstanceID()`), esa cadena se rompería: ese
número pertenece a Unity, no al modelo estructural.

**En el visor:** el toggle **IDs** dibuja el número de cada elemento
flotando sobre él. Solo se dibujan los ~120 más cercanos a la cámara,
porque poner 1 232 textos 3D a la vez hunde los cuadros por segundo.

**Verificación asociada:** `test_contrato_unity.py` comprueba que los
`elementTag` sean **únicos** y que ningún elemento apunte a un nodo que
no existe.

---

## 5. Diafragma rígido

### Qué es

Una losa de hormigón es **muy rígida dentro de su propio plano**: es
casi imposible estirarla o deformarla horizontalmente. En cambio, fuera
de su plano (hacia arriba y abajo) es flexible.

Modelarla con elementos finitos sería carísimo y no es el objetivo. En
vez de eso se impone una **restricción cinemática**: todos los nodos de
un piso se mueven como un **cuerpo rígido en el plano horizontal**.

### Lo que NO significa

> **Un diafragma rígido NO obliga a que todos los nodos tengan el mismo
> `ux`.**

Esa es la confusión más común. El piso se mueve como cuerpo rígido *en
su plano*, y con carga excéntrica **además rota**. Lo que sí debe
cumplirse es:

```
    rz_i = rz_m                          (todos giran igual)
    ux_i = ux_m − rz · (y_i − y_m)
    uy_i = uy_m + rz · (x_i − x_m)
```

Un nodo lejos del centro se mueve **más** que el maestro, justamente por
la rotación. Confundir esto hace parecer que "el diafragma no funciona"
cuando sí lo hace.

### El nodo maestro

Se crea un nodo extra en el centro del piso. Los demás quedan atados a
él. Sus GDL **fuera del plano** (`uz, rx, ry`) hay que restringirlos: el
diafragma no los toca y dejarían la matriz de rigidez singular (sin
solución).

```python
ops.fix(maestro, 0, 0, 1, 1, 1, 0)    # libera ux, uy, rz
ops.rigidDiaphragm(3, maestro, *esclavos)
```

El `3` es la dirección **perpendicular** al plano rígido: Z, o sea un
diafragma horizontal.

### Un detalle que rompe todo si falta

```python
ops.constraints('Transformation')
```

Con `rigidDiaphragm` hay restricciones **multipunto** (un GDL depende de
otros). El manejador `Plain` no sabe tratarlas.

### Cómo lo verificamos

Con una carga **lateral y excéntrica** (en una esquina), porque bajo
gravedad pura el giro es ≈ 0 y la prueba se cumpliría sola sin probar
nada. Resultado: los nodos cumplen la relación de cuerpo rígido con
error **exactamente 0**, y el piso **sí rota** (3.8 × 10⁻⁵ rad).

**Efecto de los muros:** al agregarlos, el giro bajó de 8.2 × 10⁻⁵ a
3.8 × 10⁻⁵ rad (**−54 %**). Es evidencia numérica de que los muros
están tomando torsión.

**En el visor:** el toggle **Diafragmas** dibuja el nodo maestro y un
radio a cada nodo atado a él. Sirve para ver de inmediato si algún nodo
quedó fuera del diafragma de su piso.

> **Corrección respecto de la Semana 1:** antes se usaba
> `equalDOF(m, s, 1, 2, 6)`, que fuerza el **mismo** `ux`, `uy` y `rz` en
> todos los nodos. Eso no es un diafragma rígido: es un piso que **no
> puede rotar**.

---

## 6. Áreas tributarias

### El problema

La losa recibe la carga (peso propio + terminaciones), pero **no la
modelamos**. Entonces, ¿cómo llega esa carga a las vigas?

### La regla de las bisectrices a 45°

Se traza una bisectriz desde cada esquina del paño. La losa queda
dividida en cuatro zonas, y cada zona descarga sobre la viga que tiene
al lado:

```
    y1  +--------------------+
        | \                / |   vigas LARGAS  → TRAPECIO
        |  \______________/  |   ← línea de cumbrera
        |  /              \  |
    y0  | /                \ |   vigas CORTAS  → TRIÁNGULO
        +--------------------+
       x0                    x1
```

La cumbrera corre siempre en la dirección **larga** del paño.

Con `a` = luz de la viga y `b` = luz transversal:

| caso | forma | área |
|---|---|---|
| `b ≤ a` (viga larga) | trapecio | `b(2a − b)/4` |
| `b > a` (viga corta) | triángulo | `a²/4` |

Después, la carga se pasa a carga lineal sobre la viga:

```
    w = q · A_tributaria / L        [kN/m]
```

### Por qué NO se reparte 50/50

Es tentador dar la mitad a las vigas X y la mitad a las Y. En un paño
cuadrado da lo mismo; en uno alargado, no:

| paño 10.00 × 3.34 m | viga larga | viga corta |
|---|---|---|
| bisectrices 45° | **13.91 m²** | **2.79 m²** |
| reparto 50/50 | 8.35 m² | 8.35 m² |

El 50/50 **descarga la viga larga un 40 %**.

> **Lo más importante de entender:** el **equilibrio global NO detecta
> este error**. La carga total es la misma en ambos casos, así que la
> suma de reacciones cierra igual. Lo que está mal es *cómo se reparte*.
> Por eso existe `tests/test_areas_tributarias.py`, con un test que
> falla si alguien vuelve al reparto crudo.

### Vigas interiores vs. de borde

Una viga **interior** toca dos paños (uno a cada lado) y acumula dos
zonas; una de **borde**, una sola. En este piso: 58 interiores y 24 de
borde.

**En el visor:** el toggle **Áreas tributarias** dibuja el polígono real.
Al seleccionar una viga, el panel contesta `A_trib`, los kN de losa que
le llegan y el chequeo `w·L = q·A` en vivo.

---

## 7. Muros equivalentes ("columna ancha")

Un muro no se modela como placa. Se idealiza como **una barra vertical**
en su eje baricéntrico, con la sección del muro completo:

```
    A         = L · t
    I_fuerte  = t · L³/12      (flexión EN el plano del muro)
    I_débil   = L · t³/12      (fuera del plano)
```

La relación `I_fuerte / I_débil = (L/t)²`. Para un muro de 8.20 m y
0.30 m de espesor son **747**.

> **Por eso la orientación es crítica:** un muro mal orientado aporta
> 747 veces menos rigidez de la que debería, **y el modelo no avisa**.
> Se orienta con `vecxz` apuntando en la dirección del muro en planta.

### Los muros van atados al diafragma

Los nodos del muro se agregan al diafragma de su piso. Sin eso el muro
queda como un **voladizo suelto al lado del edificio**: aporta rigidez a
nada. La forma de detectarlo: si agregar muros no cambia la respuesta,
no están conectados.

---

## 8. Casos de carga y superposición

| caso | qué es |
|---|---|
| **G** | gravedad: peso propio + losa + terminaciones |
| **Q** | carga viva (misma geometría tributaria, otra intensidad) |
| **EX** | sismo pseudoestático lateral en X |
| **EY** | sismo pseudoestático lateral en Y |

Como el modelo es **lineal**, vale la superposición:

```
    R = λ_G·R_G + λ_Q·R_Q + λ_EX·R_EX + λ_EY·R_EY
```

**Consecuencia práctica:** cambiar los factores de combinación **no**
requiere volver a correr OpenSees — basta combinar resultados ya
calculados. Cambiar una sección, un apoyo, `E` o la geometría **sí**
lo requiere, porque cambia la matriz de rigidez.

---

## 9. Las 5 verificaciones y qué prueba cada una

| # | Verificación | Qué detecta | Qué **no** detecta |
|---|---|---|---|
| 1 | Carga total de losa por piso | que `q_G` y el área estén bien | nada del reparto |
| 2 | Suma de áreas tributarias = área de planta | huecos o solapes en el reparto | si una viga recibe el área equivocada |
| 3 | Conservación `w·L = q·A` | pérdida de carga al pasar a las vigas | mal reparto entre vigas |
| 4 | Equilibrio global `ΣF = ΣR` | cargas mal aplicadas, apoyos mal puestos | **el reparto** (ver arriba) |
| 5 | Compatibilidad del diafragma | diafragma mal armado o nodos sueltos | — |

> **La idea central:** el equilibrio es **necesario pero no suficiente**.
> Cierra igual aunque el reparto esté mal, aunque las inercias estén
> cruzadas o aunque leas las fuerzas en los ejes equivocados. Por eso
> cada cosa tiene su propia verificación.

---

## 10. La arquitectura: por qué OpenSees calcula y Unity solo muestra

```
    OpenSees (Python)  →  JSON  →  Unity  →  AR
       CALCULA          fuente    MUESTRA
                        de verdad
```

**Nunca se mete cálculo estructural en C#.** Si algo hay que calcularlo,
va en Python y viaja por el JSON. Motivos:

1. **Una sola fuente de verdad.** Si Unity recalculara los ejes locales
   o las áreas, existirían dos versiones de la misma regla y con el
   tiempo divergirían.
2. **Si se pierde la escena de Unity**, el modelo se reconstruye entero
   desde `data/`.
3. **Se verifica una sola vez**, en Python, con tests.

### El contrato JSON

`JsonUtility` (el parser de Unity) **falla en silencio**: si un campo de
C# no calza con la clave del JSON, no hay error ni aviso — queda en su
valor por defecto. Un `uz` mal escrito da deformada plana sin decir nada.

Por eso existe `tests/test_contrato_unity.py`, que compara los campos
declarados en los `.cs` contra las claves reales del JSON.

---

## 11. El swap de ejes OpenSees → Unity

- **OpenSees:** Z es vertical (convención de ingeniería).
- **Unity:** Y es vertical (convención de videojuego).

```
    Unity(x, z_opensees, y_opensees)
```

Si el edificio se ve **acostado**, este swap está mal.

**Detalle que se olvida:** los **vectores** (ejes locales, direcciones)
también tienen que pasar por el mismo swap que las posiciones. Si no,
las flechas apuntan mal aunque el modelo se vea bien.

---

## 12. Preguntas que probablemente hará el profesor

| Pregunta | Dónde está la respuesta |
|---|---|
| "Muéstrame este elemento del plano" | filtro por piso + click; se resalta |
| "¿Qué `elementTag` tiene?" | panel del visor, primera línea |
| "¿Qué apoyos tiene?" | panel: `APOYO [1 1 1 1 1 1]` por GDL |
| "¿Cuál es su eje local?" | panel: `local x/y/z` + toggle de flechas RGB |
| "¿Qué área tributaria carga esta viga?" | panel: `A_trib` + polígono dibujado |
| "¿Cuántos kN de losa le llegan?" | panel: `carga` y `w`, con `w·L = q·A` |
| "¿Por qué el diafragma no da el mismo `ux`?" | §5 de esta guía |
| "¿Cómo sabes que el reparto está bien?" | §6: el equilibrio no lo valida, los tests sí |
| "¿Qué limitaciones tiene el modelo?" | §13 |

---

## 13. Limitaciones que hay que saber declarar

Saber qué **no** hace el modelo es parte de entenderlo:

- La losa no es una placa: su carga se idealiza con áreas tributarias y
  carga uniforme equivalente. **Conserva la resultante, no el momento
  exacto** — la carga real que baja es triangular o trapezoidal.
- Los muros van como columna ancha: capturan comportamiento
  axial-flexural, **no corte** ni acoplamiento con las vigas más allá
  del diafragma.
- **La extracción de muros del DXF no es exhaustiva.** De 163 segmentos
  en la capa `RLE-MURO`, 102 miden menos de 1 m y se descartan, 7 caras
  largas quedaron sin pareja (una de 9.30 m) y 3 pares caen fuera de la
  malla de ejes modelada. Se modelaron 24 muros. Correr
  `src/extraer_muros_dxf.py` imprime esta auditoría.
- Se modelan 8 ejes en X y 6 en Y; el plano tiene ejes secundarios que
  no se incorporaron.
- El modelo global es **lineal elástico**. La capacidad no lineal
  (Fiber Sections, M-φ, P-M) es de la Semana 3 y va **separada**.
