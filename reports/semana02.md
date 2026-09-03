# Semana 2 — LAB: edificio completo + gravedad + viewer Unity

**Proyecto:** Laboratorio Estructural Digital
**Estructura:** edificio **LT2**, planos de cálculo `2024_22` (M. Kupfer C., octubre 2024)
**Grupo:** Grupo 7
**Integrantes:** Pedro Castillo, Monserrat Cubillos, Eduardo Vergara

> **Cambio de estructura.** La primera versión de este laboratorio modelaba el
> Edificio de Ingeniería idealizado como una **grilla regular**: 8 ejes en X por 6
> en Y por 9 niveles, con una columna en cada cruce y una viga en cada tramo de eje.
> Toda la geometría cabía en tres listas de números.
>
> Ahora la estructura es el **LT2**, armado entero desde sus planos de cálculo. El
> código del laboratorio es el mismo — el notebook, las 5 verificaciones, el
> contrato JSON, el visor, el servidor de reanálisis y los tests. Lo que cambió es
> de dónde sale la estructura, y eso obligó a cambiar dos cosas de forma. Las dos
> están dichas donde corresponde (§1.6 y §3.5).

---

## 1. Modelo estructural

### 1.1 Geometría (trazable al plano)

Nada de la geometría está escrito a mano. Sale de los planos DXF por script:

```
DWG ──► DXF ──► geometria_lt2_2024_22.json ──► modelo OpenSees
     (AutoCAD headless)      (ingestor)        (modelo_lt2.py)
```

Tres plantas y seis elevaciones:

| Lámina | Lo que dice su propio rótulo |
|---|---|
| `2024_22-100` | PLANTA FUNDACIONES |
| `2024_22-101` | PLANTA CIELO 1° SUBTERRÁNEO a CIELO PISO 3° |
| `2024_22-102` | PLANTA CIELO 4° PISO — (NIVEL SUPERIOR LOSA + 11.83) |
| `2024_22-300` … `305` | seis elevaciones |
| `2024_22-700` | plano de cargas |

Los **ejes** salen de las burbujas de la capa `RLE-EJE`, con el nombre que les puso
el calculista. **Ojo:** en la grilla los ejes *definían* la estructura; acá son
referencia — no hay una columna en cada cruce.

| Dirección | Ejes |
|---|---|
| vertical, x constante (10) | **A'**=10.965 · **A**=14.745 · **B**=22.245 · **C**=32.236 · **B'**=35.415 · **C'**=39.787 · **D**=42.236 · **E1**=42.407 · **D'**=42.919 · **E'**=43.747 |
| horizontal, y constante (8) | **3**=11.047 · **2A'**=15.312 · **2**=18.297 · **1A'**=22.932 · **1'**=23.992 · **1**=27.197 · **8A**=33.617 · **8B**=37.917 |

Los **niveles** salen de las seis elevaciones, y el criterio no lo pone quien
programa: una cota es un piso del edificio sólo si **las seis coinciden** en ella.
Una que aparece en una sola es una cota local (un antepecho, una losa de sala de
máquinas). Siete cotas pasan el filtro: `−8.57, −7.97, −4.01, −0.05, +3.91, +7.87,
+11.83`, con altura entre pisos constante de **3.96 m**.

La verificación interna es el desfase: para cada elevación, `y_dibujo − cota` tiene
que ser el **mismo** para todas sus cotas. Lo es, con dispersión 0.0000 m en las seis.

| | |
|---|---|
| Niveles del modelo (6) | −7.97 (base) · −4.01 · −0.05 · +3.91 · +7.87 · +11.83 |
| Altura | 19.80 m |
| **Área de losa por piso** | **496.87 m²** (suma de los paños detectados) |
| Nodos por piso | 46 — **no** es nX·nY: la planta no es una grilla |

### 1.2 Elementos

| Tipo | Cantidad | Modelación |
|---|---:|---|
| Columnas | 40 | `elasticBeamColumn`, `vecxz = (1,0,0)` |
| Vigas X | 125 | `elasticBeamColumn`, `vecxz = (0,0,1)` |
| Vigas Y | 105 | `elasticBeamColumn`, `vecxz = (0,0,1)` |
| Muros | 45 | columna ancha, `vecxz` = **normal** al muro |
| Brazos rígidos | 115 | pedazos de muro; sección grande |
| **Total** | **430** | 247 nodos, 6 GDL c/u |

**Apoyos:** 17 nodos empotrados en `z = −7.97`.
**Diafragmas:** 5, uno por piso (`rigidDiaphragm`).

**Material:** hormigón **G35_10**, `f'c = 35 MPa` — de la nota de la lámina 100 —,
`Ec = 4700·√f'c = 27 806 MPa`, ν = 0.20, γ = 25 kN/m³.

**Torsión:** `J` por Saint-Venant para sección rectangular llena. Para el pilar
0.70×0.70 da **J = 3.38 × 10⁻² m⁴**. El atajo `min(Iy,Iz)·0.3` no corresponde a
ninguna fórmula y subestima la rigidez torsional 5.6 veces; en un marco simétrico no
se nota, en esta planta irregular sí.

Las secciones **no son tres fijas**: hay una por cada tamaño distinto que aparece en
el plano. Doce en total:

`P 0.70x0.70` · `V 0.25x0.80` · `V 0.30x0.80` · `V 0.40x0.80` · `V 0.60x0.80` ·
`M 0.25x2.68` · `M 0.25x2.82` · `M 0.25x7.95` · `M 0.30x1.45` · `M 0.30x2.40` ·
`M 0.60x2.92` · `BRAZO`

### 1.3 Muros equivalentes

Un muro se dibuja en el plano como sus **dos caras** (dos segmentos paralelos), así
que el ingestor las empareja para obtener eje y espesor:

1. rearma las rectas que el DXF entrega partidas en cada vértice de la polilínea;
2. agrupa segmentos paralelos (tolerancia angular de 1°);
3. busca pares separados entre 0.10 y 0.60 m;
4. exige que se **solapen** longitudinalmente, consumiendo intervalos — una cara
   larga puede servir a varios tramos de muro, con el hueco de una puerta entre
   ellos;
5. el eje es el promedio de las caras; el espesor, su separación.

Resultado en la planta tipo: **9 muros**, largos de 1.45 a 7.95 m, espesores de 0.25
a 0.60 m, con **98.5 % de cobertura** del largo dibujado.

**La verificación cruzada.** Los espesores medidos geométricamente coinciden **uno a
uno** con los rótulos `M.H.A. e=…`: `e=25` ×4, `e=30` ×3, `e=60` ×2 — 9 muros, 9
rótulos. Son dos fuentes distintas del mismo plano.

En las vigas la verificación es análoga: el **ancho** se mide del dibujo y el **alto**
se lee del rótulo (`V. 60/80` = 60 de ancho × 80 de alto). Que el ancho medido calce
con el rótulo declarado es lo que impide asignarle a una viga la sección de otra.

### 1.4 Lo que se dejó afuera, y por qué

Las láminas **no traen sólo el edificio que hay que modelar**. Recortar por *toda* la
malla de ejes no alcanzaba: los dos cuerpos ajenos tienen ejes propios y caían dentro.

**La etapa anterior.** La lámina 102 dibuja, pasada la junta, tres pilares en
`x = 43.15` y sus vigas. Uno de los rótulos dice `+V.I. 15/70 (2ª ETAPA)` y a 60 cm
hay un texto que dice **`ETAPA ANTERIOR`**. La junta la marca el dibujo solo: la cara
este del LT2 está en `x = 42.702` y la cara oeste del otro cuerpo en `x = 42.802`.
Esos **10 cm** son la junta de dilatación que la lámina 700 rotula siete veces.

**La rampa del subterráneo.** Entre los ejes `8A` y `8B` las tres plantas dibujan un
cuerpo con `i = 52.46 %`, `N.S.M. = VAR`, `N.O.G. = VAR` y cotas −7.39 a −2.81, todas
de la elevación 302. Es la rampa de acceso: una losa inclinada sobre muros de
independencia que no pasa del subterráneo. La lámina de techo ni siquiera tiene los
ejes 8A y 8B.

El recorte se declara en el perfil como **cuatro bordes** (`ventana.modo =
"ejes_nombrados"`), cada uno un eje con nombre o —para la junta, que no tiene eje—
una coordenada. Es el mismo mecanismo con el que dos personas se reparten un juego de
planos: cada una declara los ejes que acotan su cuerpo.

### 1.5 Los dos elementos supuestos

El modelo declara **dos dinteles que las láminas no dibujan**, en el perfil y no en
el código, así que se sacan editando un JSON:

| dintel | vano | por qué |
|---|---:|---|
| acceso a la caja de ascensores | 2.65 m | la caja tiene tres muros en U y el cuarto lado es el acceso |
| vano de la fachada oriente | 2.40 m | el muro del eje D viene partido: 10.58–18.53 y 20.93–23.75 |

Un vano de ese ancho entre dos muros de hormigón lleva dintel. Sin ellos el bloque
nororiente entero —45 m² por piso— no cierra como paño y su carga no llega a ninguna
viga. `verificar_lab2.py` los lista como supuesto.

### 1.6 Qué no se pudo conservar del laboratorio anterior

**`id_nodo(nivel, ix, iy)` no existe.** En una grilla cada nodo es el cruce del eje
`ix` con el eje `iy`, así que un nodo tiene dirección. En el LT2 los nodos salen de
**mallar** las vigas: 46 por piso, en posiciones que no forman grilla, y el cruce del
eje C con el eje 2 puede no tener ningún nodo. Inventar un índice `(ix, iy)` sería
mentir sobre la geometría. En su lugar: `nodos_del_nivel(nivel)` y
`nodo_mas_cercano(x, y, nivel)`.

**`construir_modelo(con_muros=False)` tampoco.** En la grilla los muros eran un extra
sobre un marco que se sostenía solo. Acá 115 brazos rígidos cuelgan de los muros, así
que sacarlos deja vigas flotando y la matriz singular. El experimento de control
equivalente está en §3.5.

---

## 2. Carga gravitacional y áreas tributarias

### 2.1 Definición de q_G

En la grilla `q_G` era un número escrito a mano (`25·0.25 + 1.5 = 7.75`). Acá sale del
**plano de cargas** (lámina 700), y **no es un solo número**: la lámina da un peso
muerto adicional distinto para las plantas tipo y para el cielo del 4° piso.

| | peso propio losa | PM adicional | **q_G** | sobrecarga Q |
|---|---:|---:|---:|---:|
| plantas tipo | 25 × 0.15 = 3.750 | 2.550 | **6.300** | 4.903 |
| cielo 4° piso | 3.750 | 1.961 | **5.711** | 2.942 |

Los cuatro valores del plano se verifican contra los que usa el modelo (§3.1). El
espesor de losa `e = 0.15 m` no se puede medir en planta: se lee del atributo `ESP`
de los 22 bloques `losa-ne`, que tienen nombre y por lo tanto no hay que adivinar
cuál de los números del plano es.

### 2.2 Reparto por bisectrices a 45°

La losa **no** se modela como placa: su carga se transfiere a las vigas trazando las
bisectrices a 45° desde las esquinas de cada paño.

| caso | forma | área |
|---|---|---|
| `b ≤ a` (viga larga) | trapecio | `b(2a−b)/4` |
| `b > a` (viga corta) | triángulo | `a²/4` |

**Los paños hay que encontrarlos.** En la grilla venían dados: el rectángulo entre
cuatro ejes consecutivos. Acá la planta es irregular y los paños son las **caras del
grafo plano** que forman las vigas y los muros de cada piso (`panos.py`).

**Y el 45° se calcula, no se dibuja.** Trazar bisectrices es la construcción de
dibujo; lo que *significa* es que cada punto de losa carga al lado que tiene **más
cerca**. Escrito así, la región del lado `i` es el paño recortado por un semiplano
por cada otro lado `j`:

```
dist(x, lado i)  ≤  dist(x, lado j)
```

Dentro de un paño convexo la distancia a un lado es la distancia a su recta, así que
cada condición es un semiplano y el polígono sale exacto por recorte. En un
rectángulo caen solos el trapecio y el triángulo:

| paño 10.00 × 3.34 m | viga larga | viga corta |
|---|---:|---:|
| fórmula cerrada | 13.9111 m² | 2.7889 m² |
| polígono recortado | 13.9111 m² | 2.7889 m² |

**El área que se carga sale del polígono**, no de una fórmula aparte: así lo que se
dibuja y lo que se calcula no pueden decir cosas distintas.

Resultado en el piso tipo: **17 paños, 496.87 m²**, 16 de ellos convexos (reparto
exacto) y uno no convexo (aproximado, con el área reescalada para que la carga se
conserve). Los polígonos **teselan** cada paño con error `0.000000 m²`.

### 2.3 Los muros también son borde de paño

Donde no hay viga, la losa se apoya directo sobre un muro. Como un muro es *una*
columna ancha en su baricentro, su área tributaria no puede ir repartida: va como
carga **puntual** en su nodo, que es estáticamente equivalente. Son **44.47 m²** de
los 496.87 del piso.

### 2.4 Los paños que el plano numera

El plano rotula cada paño de losa con un bloque `losa-ne` que trae su nombre (`0100`,
`0101`, …) — el mismo del que se lee el `e=15`. Eso da un criterio y una verificación.

**El criterio:** una cara con rótulo lleva losa; una cara sin ninguno, no. Cerrada la
caja de ascensores queda una cara de **7.86 m²** perfectamente cerrada, y adentro no
hay losa: es por donde sube el ascensor. Cargarla serían 50 kN por piso inventados.

**La verificación cruzada:** los **22 rótulos caen en 17 caras**, ninguno a más de
1 m de la suya, y la única cara sin rótulo es el hueco del ascensor. La geometría sale
de las líneas de muros y vigas; los rótulos son otra fuente del mismo plano.

(Varios rótulos están escritos fuera del edificio con su línea de referencia
apuntando adentro, así que cada uno se asigna a la cara más cercana, no a la que lo
contiene.)

### 2.5 Por qué no sirve el reparto proporcional

La versión de la Semana 1 daba la mitad de la carga a las vigas X y la mitad a las Y.
El mismo error de fondo aparece si se reparte en proporción al largo:

| paño 10.00 × 3.34 m | viga larga | viga corta |
|---|---:|---:|
| bisectrices 45° | 13.911 m² | 2.789 m² |
| por largo de viga | 12.518 m² | 4.181 m² |
| 50/50 | 8.350 m² | 8.350 m² |

Los tres conservan el área total (33.4 m²) — **y por eso el equilibrio global no
distingue entre ellos**. Pero el reparto por largo sobrecarga la viga corta un
**50 %**, y el 50/50 un 199 %.

### 2.6 Aplicación en OpenSees

- **Losa a las vigas:** `eleLoad('-ele', tag, '-type', '-beamUniform', wy, wz, wx)`
  con `w = q·A_trib/L`. Con `vecxz = (0,0,1)` el eje local *z* de la viga es el
  vertical, así que la gravedad va en `wz` (el **segundo** valor) y con signo
  negativo.
- **Peso propio de columnas y muros:** carga nodal, mitad a cada extremo. Es exacto y
  evita discutir en qué eje local cae la gravedad de una columna.
- **Losa sobre un muro:** carga puntual en su baricentro.

---

## 3. Verificaciones

`python verificar_lab2.py` — las cinco del lab, sobre la estructura nueva.

### 3.1 Carga total de losa por piso

| Nivel | q_G | área | carga |
|---|---:|---:|---:|
| −4.01 | 6.2997 | 496.867 | 3 130.13 kN |
| −0.05 | 6.2997 | 496.867 | 3 130.13 kN |
| +3.91 | 6.2997 | 496.867 | 3 130.13 kN |
| +7.87 | 6.2997 | 496.867 | 3 130.13 kN |
| +11.83 | 5.7113 | 496.867 | 2 837.77 kN |
| | | **total** | **15 358.28 kN** |

Y los cuatro valores del plano de cargas contra los que usa el modelo: PM adic.
plantas tipo 2.550 vs 2.55 · SC 4.903 vs 4.90 · PM adic. cielo 4° 1.961 vs 1.96 ·
SC 2.942 vs 2.94. **Los cuatro calzan.**

### 3.2 Suma de áreas tributarias

Piso por piso, porque el techo sale de otra lámina:

| Nivel | barras | suma | área de los paños | error |
|---|---:|---:|---:|---:|
| −4.01 · −0.05 · +3.91 · +7.87 | 50 | 496.8666 m² | 496.8670 m² | 3.6 × 10⁻⁴ m² |
| +11.83 | 50 | 496.8666 m² | 496.8670 m² | 3.6 × 10⁻⁴ m² |

Ninguna barra queda con área cero, y **toda barra cargada trae su polígono**. Que los
polígonos existan es una comprobación independiente del área: el área se reescala, y
podría cerrar con polígonos mal dibujados.

### 3.3 Conservación de carga

Barra por barra, `w·L = q·A`: peor error **2.8 × 10⁻¹⁴ kN**.
Losa de los pisos 15 358.281 kN contra 15 358.270 kN transferidos a las barras.

### 3.4 Equilibrio global

| | |
|---|---|
| Carga aplicada G | **34 011.0591 kN** |
| Suma de reacciones Rz | **34 011.0591 kN** |
| **Error** | **8.7 × 10⁻⁸ kN** |
| UZ máximo | **−6.7171 mm** |

**Y un chequeo que el equilibrio no puede hacer.** El equilibrio cierra igual de bien
con la carga mal repartida, así que además se verifica que ningún nodo se descuelgue
de su piso — un nodo que baja mucho más que la mediana es una viga que quedó sin
apoyo:

| Nivel | mediana | máximo |
|---|---:|---:|
| −4.01 | 0.71 mm | 4.51 mm |
| −0.05 | 1.26 mm | 5.45 mm |
| +3.91 | 1.48 mm | 6.15 mm |
| +7.87 | 1.55 mm | 6.61 mm |
| +11.83 | 1.50 mm | 6.72 mm |

### 3.5 Compatibilidad del diafragma

Un diafragma rígido **no** obliga a que todos los nodos tengan el mismo `ux`. El piso
se mueve como cuerpo rígido *en su plano* y, con carga excéntrica, además **rota**:

```
rz_i = rz_m
ux_i = ux_m − rz·(y_i − y_m)
uy_i = uy_m + rz·(x_i − x_m)
```

Confundir esto con "todos los `ux` iguales" hace parecer que el diafragma no funciona
cuando sí lo hace. Se verifica con carga **lateral y excéntrica**: bajo gravedad pura
el giro es ≈ 0 y la prueba se cumpliría sola.

La carga va en un nodo de **esquina** de cada piso. En la grilla ese nodo era
`id_nodo(lev, 0, 0)`; acá la planta es irregular, así que se busca el nodo más cercano
a la esquina del edificio.

| | |
|---|---|
| Giro `rz` máximo de piso | 1.4414 × 10⁻⁵ rad |
| Peor error en `ux` | **0.00 m** |
| Peor error en `uy` | **0.00 m** |
| Peor error en `rz` | **0.00 rad** |

**El experimento de control.** En la grilla se comparaba el giro con y sin muros. Acá
no se pueden sacar (115 brazos cuelgan de ellos), así que se les **gira el eje fuerte
90°**: un muro tiene hasta 1000 veces más inercia en un eje que en el otro.

| | giro máximo de piso |
|---|---:|
| muros en su eje fuerte | 1.4414 × 10⁻⁵ rad |
| muros girados 90° | 1.7605 × 10⁻⁵ rad |
| | **+22 %** |

Los muros **sí** están tomando torsión, no son sólo dibujo.

### 3.6 El reanálisis reproduce el modelo

`python tests/test_reanalisis.py` levanta el servidor Flask, le manda el JSON
exportado y compara nodo por nodo contra la deformada que calculó Python:

> 252 nodos comparados, **peor diferencia 5.0 × 10⁻⁹ m** — que es el redondeo del
> JSON a 9 decimales.

Es la verificación que impide que el visor y el informe hablen de un modelo distinto
del que se resolvió. Ya pasó dos veces en este proyecto: una porque el caso G
exportado no traía el peso propio (10.04 mm en vez de 11.78) y otra porque las
inercias iban ya cruzadas y el servidor las cruzaba de nuevo (12.17 mm). Ninguno de
los dos daba error.

---

## 4. Viewer Unity para QA

El visor no es una maqueta: es la herramienta con la que se revisa el modelo contra el
plano. Varios de los errores de esta entrega se encontraron **abriéndolo**, no mirando
números — y los tres primeros no eran del modelo sino del propio visor, que es su
propio tipo de error: invita a "arreglar" un modelo que está sano.

### 4.1 Capas activables

Nodos · nodos auxiliares · columnas · vigas · muros · **brazos rígidos** · perfiles
reales (b × h) · apoyos · diafragmas · IDs · ejes locales · **áreas tributarias** ·
deformada con escala · filtro por piso.

### 4.2 Qué contesta al seleccionar un elemento

`elementTag`, nodos, sección con `A`, `Iy`, `Iz`, `J`, **restricciones por GDL**,
**ejes locales**, **área tributaria** con su polígono, y los kN de losa que le llegan,
con el chequeo `w·L = q·A` en vivo.

### 4.3 Por qué los ejes locales se exportan y no se deducen

Deducirlos en C# sería duplicar la convención de `geomTransf`, y esa copia terminaría
divergiendo del modelo real sin que nadie se entere. Se calculan en Python y viajan en
el JSON; Unity los **dibuja**.

**Y a un campo se le había escapado esa regla.** En un muro, `vecxz` es la **normal**
al muro — es lo que pone la inercia fuerte en el eje correcto. El C# lo leía como si
apuntara *a lo largo*, así que dibujaba cada muro con el largo y el espesor
intercambiados: el núcleo de ascensores atravesado, y el muro de 7.95 m del eje D
"desaparecido" (en realidad dibujado metido 7.95 m hacia adentro de la planta).

Arreglo: Python exporta **`dir_largo`** —hacia dónde corre el largo del muro en
planta— y Unity lo dibuja.

### 4.4 Contrato JSON ↔ Unity

`tests/test_contrato_unity.py` compara los campos del C# contra las claves reales del
JSON. Hace falta porque **`JsonUtility` falla en silencio**: si un campo no calza,
queda en su valor por defecto, sin error ni warning. Una `uz` mal escrita da deformada
plana sin decir nada.

---

## 5. Reproducibilidad

### 5.1 Puesta en marcha

```powershell
.\setup.ps1          # crea .venv e instala requirements.txt
```

El modelo del LT2 vive en el repo `A1P1.0_Grupo_7`, que se espera **al lado** de este.
Si está en otra parte:

```powershell
$env:LT2_SRC = "C:\ruta\a\A1P1.0_Grupo_7\src"
```

### 5.2 El laboratorio completo en un notebook

```powershell
.\lab.ps1            # abre laboratorio.ipynb en JupyterLab
```

`Kernel → Restart & Run All` corre todo: geometría → áreas tributarias → OpenSees →
las 5 verificaciones → JSON → visor.

### 5.3 Por línea de comandos

```powershell
python verificar_lab2.py          # las 5 verificaciones
python src\exportar_unity.py      # modelo -> data\modelo_unity.json
python src\lanzar_unity.py app    # sincroniza el JSON y abre el visor
python tests\test_areas_tributarias.py
python tests\test_contrato_unity.py
python tests\test_reanalisis.py   # necesita flask
```

---

## 6. Limitaciones asumidas

1. **Lineal elástico, sin fisuración.**
2. **La losa no se modela como placa:** sólo baja su carga.
3. **La fundación se reemplaza por empotramiento** en `z = −7.97`. La cota `−8.57` es
   el sello de fundación; empotrar en el sello superior es la simplificación habitual.
4. **Se supone continuidad de muros y pilares hacia arriba.** Una lámina de losa no
   vuelve a dibujar los muros que ya venían de abajo.
5. **Dos dinteles supuestos** (§1.5). Declarados en el perfil, listados por
   `verificar_lab2.py`.
6. **Un paño de 17 reparte con polígonos aproximados** por no ser convexo. El área se
   reescala, así que la carga se conserva exacta aunque el dibujo no lo sea; está
   contado en la auditoría.
7. **Quedan ~16 m² por piso** (3 % de la planta) entre el eje de las vigas de fachada
   y el eje de los muros perimetrales.
8. **Falta la carga lineal** del plano de cargas (tabiques y antepechos: SC = 100 y
   200 kgf/m, PM. ADIC. = 1500 kgf/m sobre vigas).
9. **Sólo el caso G.** Q, EX y EY quedan para la etapa siguiente.
10. **El otro cuerpo va aparte.** La lámina 700 rotula `JUNTA DE DILATACIÓN 10 cm`
    siete veces: los dos cuerpos van estructuralmente separados y no comparten nodos.
    Lo único común es el sistema de coordenadas.
