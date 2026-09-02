# Semana 2 — LAB: edificio completo + gravedad + viewer Unity

**Proyecto:** Laboratorio Estructural Digital del Edificio de Ingeniería
**Grupo:** Grupo 7
**Integrantes:** Pedro Castillo, Monserrat Cubillos, Eduardo Vergara
**Fecha:** 1 de septiembre de 2026

---

## 1. Modelo estructural

### 1.1 Geometría (trazable al plano)

Los ejes salen de la capa `RLE-EJES` del plano `2017_67-100.dxf` (cotas
en cm, convertidas a m). Los muros salen de la capa `RLE-MURO` del mismo
plano, extraídos por script — no escritos a mano.

| Parámetro | Valor |
|---|---|
| Ejes en X (8) | 8.02, 11.32, 14.72, 18.02, 28.02, 38.02, 48.02, 53.02 |
| Ejes en Y (6) | 46.92, 50.26, 55.20, 60.20, 65.22, 72.75 |
| Niveles (9) | 0.0, 4.0, 7.5, 11.0, 14.5, 18.0, 21.5, 25.0, 28.5 |
| Planta | 45.00 × 25.83 m = **1 162.35 m²** |
| Altura | 28.5 m |

### 1.2 Elementos

| Tipo | Cantidad | Sección | Modelación |
|---|---|---|---|
| Columnas | 384 | 50 × 50 cm | `elasticBeamColumn`, `vecxz = (1,0,0)` |
| Vigas X | 336 | 30 × 60 cm | `elasticBeamColumn`, `vecxz = (0,0,1)` |
| Vigas Y | 320 | 30 × 80 cm | `elasticBeamColumn`, `vecxz = (0,0,1)` |
| Muros | 192 | 24 muros × 8 niveles | columna ancha, `vecxz` = dirección del muro |
| **Total** | **1 232** | | 656 nodos, 6 GDL c/u |

**Material:** hormigón f'c = 28 MPa, `Ec = 4700·√f'c = 24 870 MPa`,
ν = 0.20, γ = 25 kN/m³.

**Torsión:** `J` por Saint-Venant para sección rectangular llena.
Para la columna 50×50 da **J = 8.80 × 10⁻³ m⁴**. La versión de Semana 1
usaba `min(Iy,Iz)·0.3 = 1.56 × 10⁻³ m⁴`, que no corresponde a ninguna
fórmula y subestimaba la rigidez torsional **5.6 veces**. En un marco
simétrico no se nota; en esta planta irregular sí.

### 1.3 Muros equivalentes

Extraídos de la capa `RLE-MURO` con `src/extraer_muros_dxf.py`. Un muro
se dibuja en el plano como sus **dos caras** (dos segmentos paralelos),
así que el script las empareja para obtener eje y espesor:

1. agrupa segmentos paralelos (tolerancia angular de 1°);
2. busca pares separados entre 0.10 y 0.60 m;
3. exige que se **solapen** longitudinalmente (si no, son dos muros
   distintos alineados, no las dos caras de uno);
4. el eje es el promedio de las caras; el espesor, su separación.

Resultado: **24 muros**, largos de 1.48 a 14.77 m, espesores de 0.10 a
0.30 m. Se agrupan en el perímetro (x ≈ 7.77 y x ≈ 48.17) y en un núcleo
central — consistente con caja de escaleras/ascensores. Varios caen
exactamente sobre ejes conocidos (y = 50.26, y = 60.20), lo que valida
la extracción.

Cada muro se modela como **una barra vertical en su eje baricéntrico**
con la sección del muro completo:

```
A        = L · t
I_fuerte = t · L³/12      (flexión EN el plano del muro)
I_débil  = L · t³/12      (fuera del plano)
```

La relación `I_fuerte/I_débil = (L/t)²` — para un muro de 8.20 m y
0.30 m de espesor son **747**. Por eso la orientación es crítica: un
muro mal orientado aporta 747 veces menos rigidez y *el modelo no avisa*.
Se orienta con `vecxz` en la dirección del muro en planta.

Los nodos de muro se incorporan al **diafragma de su piso**. Sin eso el
muro queda como un voladizo suelto al lado del edificio, aportando
rigidez a nada.

### 1.4 Apoyos

72 nodos empotrados en la fundación (48 de columnas + 24 de muros),
`fix(n, 1,1,1,1,1,1)`. Un apoyo es una **lista explícita de
restricciones por GDL** `[ux,uy,uz,rx,ry,rz]`, no "algo que se ve
empotrado" — el viewer los muestra así al seleccionarlos.

### 1.5 Diafragmas rígidos

Uno por piso (8), con `ops.rigidDiaphragm(3, maestro, *esclavos)` y
nodo maestro en el centroide de la planta.

> **Corrección respecto de la Semana 1.** Antes se usaba
> `equalDOF(maestro, esclavo, 1, 2, 6)`, que obliga a que **todos** los
> nodos del piso tengan el mismo `ux`, `uy` y `rz`. Eso no es un
> diafragma rígido: es un piso que no puede rotar. El diafragma real
> permite rotación y cumple
> `ux_i = ux_m − rz·(y_i − y_m)`, `uy_i = uy_m + rz·(x_i − x_m)`.
> Se verifica en §3.5.

Los GDL fuera del plano del nodo maestro (`uz, rx, ry`) se restringen,
porque el diafragma no los toca y dejarían la matriz singular.
Se usa `constraints('Transformation')`, obligatorio con restricciones
multipunto.

---

## 2. Carga gravitacional y áreas tributarias

### 2.1 Definición de q_G

```
q_G = peso propio de losa + terminaciones uniformes
    = 25 kN/m³ × 0.25 m + 1.5 kN/m²
    = 7.75 kN/m²
```

La losa **no** se modela con elementos finitos. Su carga se transfiere a
las vigas por áreas tributarias explícitas. El peso propio de vigas,
columnas y muros se agrega aparte (cada barra carga el suyo).

### 2.2 Reparto por bisectrices a 45°

Cada paño rectangular se parte trazando bisectrices desde sus 4 esquinas.
La cumbrera corre en la dirección larga:

```
    y1  +--------------------+
        | \                / |   vigas de luz Lx (LARGAS) → TRAPECIO
        |  \______________/  |   ← cumbrera
        |  /              \  |
    y0  | /                \ |   vigas de luz Ly (CORTAS) → TRIÁNGULO
        +--------------------+
       x0                    x1
```

Con `a` = luz de la viga y `b` = luz transversal:

| caso | forma | área |
|---|---|---|
| `b ≤ a` (viga larga) | trapecio | `b(2a − b)/4` |
| `b > a` (viga corta) | triángulo | `a²/4` |

El módulo no calcula solo el área: construye el **polígono real** de cada
zona. Eso permite (a) dibujarlo en Unity, (b) calcular el área por la
fórmula del cordón — un camino **independiente** de la fórmula
analítica — y (c) contestar "qué área tributaria carga esta viga"
señalándola.

Una viga interior toma área de **dos paños**, una de borde de uno solo.
En este piso: **58 vigas interiores y 24 de borde**.

### 2.3 Por qué no sirve el reparto 50/50

La Semana 1 repartía la mitad de la carga a las vigas X y la mitad a las
Y. En un paño cuadrado da lo mismo; en uno alargado no:

| paño 10.00 × 3.34 m | viga larga | viga corta |
|---|---|---|
| bisectrices 45° | **13.91 m²** | **2.79 m²** |
| reparto 50/50 | 8.35 m² | 8.35 m² |

El 50/50 **descarga la viga larga un 40 %** y sobrecarga la corta un
199 %. Sobre la malla completa, la mayor discrepancia entre ambos
métodos es de **36.09 m²** en una sola viga.

> **El equilibrio global no detecta este error.** La carga total es la
> misma en ambos casos, así que la suma de reacciones cierra igual. Lo
> que está mal es *cómo* se reparte. Por eso existe
> `tests/test_areas_tributarias.py`, con un test explícito (`[8]`) que
> falla si alguien vuelve al reparto crudo.

### 2.4 Aplicación en OpenSees

```
w = q_G · A_trib / L        [kN/m]
ops.eleLoad('-ele', tag, '-type', '-beamUniform', 0.0, -w, 0.0)
```

Con `vecxz = (0,0,1)` el eje local *z* de la viga es el vertical, así que
la gravedad va en `Wz` (el **segundo** valor) y con signo negativo.
Se usa la carga uniforme equivalente que **conserva la resultante**; la
carga real que baja de la losa es triangular o trapezoidal, lo que da un
momento de vano algo distinto. Es una idealización documentada, no un
descuido.

---

## 3. Verificaciones

Todas se corren con `python verificar_lab2.py`.

### 3.1 Carga total de losa por piso

| | |
|---|---|
| q_G | 7.7500 kN/m² |
| Área de planta | 1 162.3500 m² |
| **Carga por piso** | **9 008.2125 kN** |
| Pisos cargados | 8 |
| Carga de losa total | 72 065.70 kN |

### 3.2 Suma de áreas tributarias

| | |
|---|---|
| Vigas con área tributaria | 82 |
| Suma de áreas tributarias | 1 162.350000 m² |
| Área de planta | 1 162.350000 m² |
| **Error** | **4.5 × 10⁻¹³ m²** |

Las zonas parten el piso sin huecos ni solapes. Ninguna viga queda con
área cero (una viga sin área es una viga descargada en silencio).

### 3.3 Conservación de carga

| | |
|---|---|
| `w·L = q·A` viga por viga, peor error | 2.8 × 10⁻¹⁴ kN |
| Carga de losa del piso | 9 008.212500 kN |
| Carga transferida a las vigas | 9 008.212500 kN |
| **Error** | **1.8 × 10⁻¹² kN** |

### 3.4 Equilibrio global

| | |
|---|---|
| Carga aplicada G | 121 709.576250 kN |
| Suma de reacciones Rz | 121 709.576250 kN |
| **Error** | **2.2 × 10⁻¹⁰ kN** |
| UZ máximo (descenso) | −11.776 mm |

El descenso máximo de 11.8 mm sobre luces de hasta 10 m es del orden
esperado (≈ L/850).

### 3.5 Compatibilidad del diafragma

Se verifica con una carga **lateral y excéntrica** (aplicada en una
esquina), porque bajo gravedad pura el giro es ≈ 0 y la prueba no
probaría nada.

| | |
|---|---|
| Giro `rz` máximo de piso | 3.81 × 10⁻⁵ rad |
| Peor error en `ux` | **0.0** |
| Peor error en `uy` | **0.0** |
| Peor error en `rz` | **0.0** |

Los nodos cumplen exactamente el movimiento de cuerpo rígido en el
plano, **y el piso sí rota** — o sea la verificación es significativa,
no trivialmente satisfecha.

**Efecto de los muros:** al incorporarlos, el giro máximo de piso bajó de
**8.20 × 10⁻⁵ a 3.81 × 10⁻⁵ rad** (−54 %). Es evidencia numérica de que
los muros están efectivamente tomando torsión y no solo dibujados.

---

## 4. Viewer Unity para QA

`VisorEstructura.cs` dibuja el modelo; `VisorQA.cs` agrega las capas de
control de calidad. Ninguno calcula estructura: los ejes locales, las
áreas y las cargas **vienen ya calculados de Python** en el JSON.

### 4.1 Capas activables

nodos · vigas · columnas · muros · **apoyos** · **diafragmas** ·
**ejes locales** · **IDs** · **áreas tributarias**

Hay filtro por piso: con 1 232 elementos, mirar el edificio entero no
sirve para revisar nada.

### 4.2 Qué contesta al seleccionar un elemento

| Pregunta del profesor | Qué muestra el panel |
|---|---|
| "¿qué elementTag tiene?" | `ELEMENTO 417` |
| "muéstrame este elemento" | resaltado en magenta + filtro de piso |
| "¿qué nodos lo definen?" | `nodos 231 → 237`, con coordenadas |
| "¿qué apoyos tiene?" | `APOYO [1 1 1 1 1 1]` por GDL, en cada nodo |
| "¿cuál es su eje local?" | `local x/y/z` como vectores, y flechas RGB |
| "¿qué área tributaria carga?" | `A_trib 13.911 m² (2 paños)` + polígono |
| "¿cuántos kN de losa llegan?" | `carga 107.81 kN`, `w 10.781 kN/m` |
| — | chequeo en vivo `w·L = q·A` |

### 4.3 Por qué los ejes locales se exportan y no se deducen

Unity **no** deduce la orientación: la recibe. Deducirla en C# sería
duplicar la convención de `geomTransf`, y esa copia terminaría
divergiendo del modelo real sin que nadie se entere. Python calcula
`local_x = (j−i)/|j−i|`, `local_z = vecxz ⊥ local_x`,
`local_y = local_z × local_x` y los exporta.

Los vectores pasan por el **mismo swap de ejes** que las posiciones
(`OpenSees Z-vertical → Unity Y-vertical`); si no, las flechas apuntarían
mal aunque el modelo se viera bien.

### 4.4 Contrato JSON ↔ Unity

`JsonUtility` **falla en silencio**: si un campo C# no calza con la clave
del JSON, no hay error ni warning, queda en su valor por defecto. Un
`uz` mal escrito da deformada plana; un `area` mal escrito da áreas
tributarias en cero.

`tests/test_contrato_unity.py` compara los campos declarados en los `.cs`
contra las claves reales del JSON, verifica que los campos críticos
traigan datos (no solo que existan), y revisa unicidad de IDs y que no
haya elementos huérfanos. **Pasa.**

---

## 5. Reproducibilidad

### 5.1 El laboratorio completo en un notebook

`laboratorio.ipynb` corre toda la cadena de principio a fin:

```
planos DXF → geometría → áreas tributarias → OpenSees → verificaciones → JSON → Unity
```

```bash
python -m pip install -r requirements.txt
jupyter lab laboratorio.ipynb
```

Incluye la **visualización del reparto tributario en planta** (matplotlib),
que permite ver de un vistazo que los paños alargados reparten distinto
a los cuadrados, y una celda final que **abre el visor 3D desde el propio
notebook**.

> El modo *Play* del editor de Unity es interactivo y no se puede
> disparar desde fuera: `-batchmode` y Play son incompatibles. Por eso
> `src/lanzar_unity.py` compila una **aplicación standalone** —eso sí se
> automatiza— y luego ejecutarla es un proceso normal. La primera
> compilación tarda unos minutos; después arranca en segundos y ya no
> hace falta abrir Unity.
>
> El lanzador **exige la versión de Unity que declara el proyecto**
> (`6000.5.10f1`) y falla con mensaje explícito si no está: abrir el
> proyecto con otra versión hace que Unity migre los assets, que es una
> fuente clásica de conflictos en un repo compartido.

### 5.2 Por línea de comandos

```bash
python src/extraer_muros_dxf.py     # muros desde el plano
python verificar_lab2.py            # las 5 verificaciones
python src/exportar_unity.py        # JSON para Unity
python src/lanzar_unity.py          # abrir el visor
python tests/test_areas_tributarias.py
python tests/test_contrato_unity.py
```

| Archivo | Rol |
|---|---|
| `laboratorio.ipynb` | **el laboratorio completo, celda por celda** |
| `src/modelo_edificio.py` | fuente de verdad: geometría, secciones, cargas |
| `src/areas_tributarias.py` | reparto 45°, polígonos, conservación |
| `src/extraer_muros_dxf.py` | muros desde `RLE-MURO` |
| `src/exportar_unity.py` | contrato JSON |
| `src/lanzar_unity.py` | compila y abre el visor desde Python |
| `unity/Assets/Editor/ConfigurarEscena.cs` | arma la escena (idempotente) |
| `unity/Assets/Editor/ConstruirApp.cs` | compila la app standalone |
| `data/muros.json` | 24 muros extraídos |
| `data/modelo_unity.json` | modelo + resultados + áreas tributarias |
| `verificar_lab2.py` | las 5 verificaciones |

---

## 6. Limitaciones asumidas

- La losa no se modela como placa: su carga se idealiza por áreas
  tributarias con carga uniforme equivalente. Conserva la resultante,
  no el momento exacto.
- Los muros van como columna ancha (comportamiento axial-flexural), sin
  captura de corte ni de acoplamiento con las vigas más allá del
  diafragma.
- Se asume que los 24 muros extraídos del piso 1 son continuos hasta el
  nivel 8. Verificar contra las plantas superiores queda pendiente.
- Se modelan 8 ejes en X y 6 en Y; el plano tiene más ejes secundarios
  que no se incorporaron.
