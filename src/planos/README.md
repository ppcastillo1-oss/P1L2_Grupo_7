# Ingestor de planos

Convierte un juego de planos estructurales (DWG/DXF) en un **JSON de
geometría** verificado: ejes con nombre, niveles, muros y pilares, todo
en metros y en un único origen.

```
DWG  ──dwg_a_dxf.ps1──►  DXF  ──extraer.py──►  geometria.json
                                    ▲                 +
                                    │           informe de auditoría
                              perfiles/*.json
                          (lo único que cambia
                            entre proyectos)
```

El JSON es la **entrada** del modelo, no el modelo. Separarlos es lo que
permite revisar la lectura del plano por su cuenta, y lo que permite que
mañana entre otro juego de planos por el mismo tubo.

---

## Correrlo

```powershell
# 1. DWG -> DXF (necesita AutoCAD instalado)
.\src\planos\dwg_a_dxf.ps1 -Entrada "...\LT2_CAL" -Salida "...\LT2_CAL_dxf"
```

```bash
# 2. Ver qué hay adentro
python src/planos/inventario.py "...\LT2_CAL_dxf"

# 3. Extraer la geometría
python src/planos/extraer.py "...\LT2_CAL_dxf" --perfil lt2_2024_22

# 4. Verificar
python test_planos.py
```

---

## Usarlo con OTRO juego de planos

**No se toca el código.** Se escribe un perfil nuevo.

### 1. Convertir e inventariar

```bash
python src/planos/inventario.py <carpeta_dxf>
```

Deja `inventario.md` con las hojas, sus títulos de rótulo, sus capas y
la unidad de dibujo estimada. Ese archivo es el que se lee para escribir
el perfil.

### 2. Copiar un perfil y editarlo

`perfiles/lt2_2024_22.json` sirve de plantilla. Hay que declarar:

| Campo | Qué es |
|---|---|
| `unidades` | `cm`, `mm` o `m`. **Declararla, no adivinarla** — casi todos los planos traen `$INSUNITS = 0`. |
| `roles.*.capas` | Qué capa del CAD cumple cada papel. Admite comodines (`RLE-*`). |
| `hojas` | Qué lámina es la planta tipo, la de fundaciones, etc. |
| `elevaciones` | Las láminas de donde salen los niveles. |
| `ventana` | Recorte a la malla de ejes, para dejar fuera las vistas de detalle. |

Los roles que entiende el extractor hoy:

```
ejes_lineas   ejes_rotulos   muros   pilares   vigas
losa   vanos   fundacion   niveles   etiquetas   contorno_elevacion
```

### 3. Correr y **leer la auditoría**

`reports/geometria_<perfil>.md` no es decorativo. Trae los números con
los que se decide si la lectura sirve:

- **cobertura de muros** — qué porcentaje del largo dibujado quedó
  emparejado. Lo que falta es muro que el modelo *no va a tener*.
- **residuo del registro** — cuánto no calzan las láminas después de
  alinearlas por sus ejes comunes. En LT2 da 0.03 mm sobre 10 ejes.
- **desfase de cada elevación** — todas las cotas de una lámina deben
  dar el mismo desfase. Si lo dan, los niveles están verificados.
- **etiqueta vs dibujo** — cuando el plano dice `P.70x70` y el
  rectángulo mide otra cosa, uno de los dos está mal.
- **lo que quedó dudoso** — se resuelve *mirando el plano*. La geometría
  sola no alcanza.

---

## Por qué el código está escrito así

Leer un plano **falla en silencio**. Ninguno de estos casos lanza una
excepción; todos producen un modelo que corre, se ve bien, y está malo.
Cada uno tiene su test en `test_planos.py`.

### Cada lámina tiene su propio origen

La planta de fundaciones de LT2 está corrida **5.00 m en X** respecto de
la planta tipo, y la del 4º piso **3.20 m en Y**. Juntarlas sin registrar
deja la fundación corrida bajo los pilares.

Se registran por los ejes que **comparten nombre** (`A`, `1'`, `8B`), y
el residuo mide si de verdad calzaron. Es el mismo mecanismo con el que
se unen dos edificios modelados por separado.

### La geometría vive dentro de bloques y XREFs

La lámina 300 tiene 193 entidades en el modelspace y **17 657 dentro de
definiciones de bloque**: las elevaciones son XREFs. Recorrer solo el
modelspace lee la lámina *vacía*, sin error. Por eso `lectura.py` expande
cada `INSERT` con `virtual_entities()`, que aplica la transformación del
bloque, y baja recursivamente.

Y AutoCAD renombra las capas de un XREF: `RLE-MURO` pasa a ser
`EJE 1$0$RLE-MURO`. El perfil se escribe con el nombre limpio y el
emparejador quita el prefijo — si no, ningún patrón calzaría nunca.

### Un muro son dos caras, y una cara puede servir a varios muros

En esta planta hay una cara de 9.44 m enfrentada a dos caras de 4.90 y
4.34 m con un vano en medio. Con el criterio "una cara, un muro" el
segundo tramo desaparece. Por eso se consume el **tramo**, no la cara.
Eso subió la cobertura de 89.9 % a 96.4 % y dejó cero caras sueltas.

### Un pilar abierto sí, uno con líneas de más no

El contorno de un pilar se dibuja abierto donde llega un muro: falta
perímetro, pero sigue siendo un pilar. En cambio, si **sobra** largo, el
grupo no es un rectángulo, y aceptarlo convertiría cualquier maraña de
líneas en un pilar del tamaño de su caja envolvente. Los dos lados del
error significan cosas distintas y se tratan distinto.

### El desfase constante verifica los niveles

En una elevación, `y_dibujo − cota_escrita` da el mismo número para
todas las cotas de la lámina. En la 300: seis cotas independientes,
las seis dan 22.416. Eso no es una suposición, es una comprobación —
y de paso da la regla para convertir cualquier geometría de la
elevación a cota real.

---

## Trampas del entorno (no volver a pisarlas)

**`accoreconsole.exe` se cuelga con stdout en un pipe.** No falla: queda
colgado sin escribir nada. Hay que lanzarlo con `Start-Process` y
redirigir la salida a un archivo.

**En un script `.scr` de AutoCAD el espacio equivale a ENTER.** Si la
ruta de salida tiene espacios (`Metodos computacionales`), el nombre de
archivo se parte y el comando espera input que nunca llega → timeout.
El DXF se escribe primero en un temporal sin espacios.

**`ObjectDBX` no sirve como conversor.** Crear
`ObjectDBX.AxDbDocument.25` fuera de AutoCAD revienta con
`AccessViolationException`.

**`ezdxf` a veces devuelve `numpy.float64`**, y eso hace explotar
`json.dump` sin decir por qué. Las coordenadas se convierten con
`float()` al leer.
