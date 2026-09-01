# -*- coding: utf-8 -*-
r"""
================================================================
 areas_tributarias.py  -  REPARTO DE LA LOSA A LAS VIGAS
================================================================
 La losa NO se modela con elementos finitos. Su carga superficial
 q_G [kN/m2] se transfiere a las vigas por AREAS TRIBUTARIAS,
 trazando las bisectrices a 45 grados desde las esquinas de cada
 pano.

 Este modulo no calcula solo el AREA: construye el POLIGONO real de
 cada zona tributaria. Eso permite:
   - dibujarlo en Unity (Tributary Area Inspector);
   - calcular el area por la formula del cordon (shoelace), o sea
     por un camino INDEPENDIENTE de la formula analitica;
   - contestar "que area tributaria carga esta viga" senalandola.

 ----------------------------------------------------------------
 GEOMETRIA DEL REPARTO A 45 GRADOS
 ----------------------------------------------------------------
 Un pano rectangular Lx x Ly, al trazar bisectrices desde sus 4
 esquinas, queda partido en 4 zonas. Con Ly < Lx:

     y1  +--------------------+
         | \                / |   vigas de luz Lx (LARGAS) -> TRAPECIO
         |  \______________/  |   <- linea de cumbrera
         |  /              \  |
     y0  | /                \ |   vigas de luz Ly (CORTAS) -> TRIANGULO
         +--------------------+
        x0                    x1

 La cumbrera corre en la direccion LARGA, a media altura, y va desde
 x0 + Ly/2 hasta x1 - Ly/2.

 Areas resultantes (a = luz de la viga, b = luz transversal):

     b <= a  -> viga LARGA  -> trapecio   A = b*(2a - b)/4
     b >  a  -> viga CORTA  -> triangulo  A = a^2/4

 Pano cuadrado (a == b): ambas dan L^2/4, las 4 vigas iguales.

 ----------------------------------------------------------------
 POR QUE NO SIRVE REPARTIR 50/50
 ----------------------------------------------------------------
 Es tentador dar la mitad de la carga a las vigas X y la mitad a las
 Y. En un pano cuadrado da lo mismo, pero en uno alargado NO:

     pano 10.00 x 3.34 m (uno real de este edificio)
       reparto 45 grados : viga larga 13.92 m2 | viga corta  2.79 m2
       reparto 50/50     : viga larga  8.35 m2 | viga corta  8.35 m2

 O sea que el 50/50 descarga la viga larga en un 40% y sobrecarga la
 corta en un 199%. El EQUILIBRIO GLOBAL NO DETECTA ESTO: la suma de
 reacciones cierra igual, porque la carga total es la misma; lo que
 esta mal es COMO se reparte. Por eso hay tests dedicados
 (tests/test_areas_tributarias.py) y no basta con mirar el equilibrio.

 Unidades: m, kN, kPa.
================================================================
"""


# ============================================================
# 1. UTILIDADES DE POLIGONO
# ============================================================
def area_poligono(vertices):
    """
    Area de un poligono por la formula del cordon (shoelace):

        A = 1/2 * |sum_i (x_i * y_{i+1} - x_{i+1} * y_i)|

    vertices: lista de (x, y). No hace falta repetir el primero.

    Se usa para verificar el area por un camino distinto al de la
    formula analitica del trapecio/triangulo. Si ambas coinciden, la
    geometria del poligono es consistente con el area declarada.
    """
    if vertices is None or len(vertices) < 3:
        return 0.0
    suma = 0.0
    n = len(vertices)
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        suma += x1 * y2 - x2 * y1
    return abs(suma) / 2.0


# ============================================================
# 2. AREA ANALITICA DE UNA VIGA EN UN PANO
# ============================================================
def area_tributaria_viga(luz_viga, luz_transversal):
    r"""
    Area tributaria (m2) que UNA viga toma de UN pano rectangular,
    por reparto a 45 grados.

        luz_viga        = largo de ESTA viga
        luz_transversal = la otra dimension del pano

    Con a = luz_viga y b = luz_transversal:

        b <= a  -> esta viga es la LARGA -> trapecio  A = b*(2a-b)/4
        b >  a  -> esta viga es la CORTA -> triangulo A = a^2/4

    Conservacion: 2*A_larga + 2*A_corta = Lx*Ly siempre.
    """
    a = float(luz_viga)
    b = float(luz_transversal)
    if a <= 0.0 or b <= 0.0:
        raise ValueError(f"Las luces deben ser positivas: a={a}, b={b}")

    if b <= a:
        return b * (2.0 * a - b) / 4.0     # trapecio
    return a * a / 4.0                     # triangulo


# ============================================================
# 3. POLIGONOS DE LAS 4 ZONAS DE UN PANO
# ============================================================
def poligonos_pano(x0, y0, x1, y1):
    """
    Reparte un pano rectangular [x0,x1] x [y0,y1] en las 4 zonas
    tributarias a 45 grados y devuelve el POLIGONO de cada una.

    Devuelve un dict con 4 claves, una por borde del pano:

        'y0' -> viga del borde inferior (corre en X, luz Lx)
        'y1' -> viga del borde superior (corre en X, luz Lx)
        'x0' -> viga del borde izquierdo (corre en Y, luz Ly)
        'x1' -> viga del borde derecho   (corre en Y, luz Ly)

    cada uno con la lista de vertices (x, y) de su zona.

    La cumbrera corre siempre en la direccion LARGA del pano.
    """
    Lx = float(x1) - float(x0)
    Ly = float(y1) - float(y0)
    if Lx <= 0.0 or Ly <= 0.0:
        raise ValueError(f"Pano invalido: Lx={Lx}, Ly={Ly}")

    if Ly <= Lx:
        # Pano ancho (o cuadrado): la cumbrera corre en X, a media altura.
        ym = (y0 + y1) / 2.0
        xa = x0 + Ly / 2.0      # inicio de la cumbrera
        xb = x1 - Ly / 2.0      # fin de la cumbrera
        # Si el pano es cuadrado, xa == xb y los trapecios degeneran
        # en triangulos: el poligono sigue siendo correcto.
        return {
            'y0': [(x0, y0), (x1, y0), (xb, ym), (xa, ym)],   # trapecio
            'y1': [(x0, y1), (xa, ym), (xb, ym), (x1, y1)],   # trapecio
            'x0': [(x0, y0), (xa, ym), (x0, y1)],             # triangulo
            'x1': [(x1, y0), (x1, y1), (xb, ym)],             # triangulo
        }

    # Pano alto: la cumbrera corre en Y, a media anchura.
    xm = (x0 + x1) / 2.0
    ya = y0 + Lx / 2.0
    yb = y1 - Lx / 2.0
    return {
        'x0': [(x0, y0), (xm, ya), (xm, yb), (x0, y1)],       # trapecio
        'x1': [(x1, y0), (x1, y1), (xm, yb), (xm, ya)],       # trapecio
        'y0': [(x0, y0), (x1, y0), (xm, ya)],                 # triangulo
        'y1': [(x0, y1), (xm, yb), (x1, y1)],                 # triangulo
    }


# ============================================================
# 4. REPARTO SOBRE UNA MALLA COMPLETA DE PISO
# ============================================================
def repartir_piso(ejes_x, ejes_y):
    """
    Recorre TODOS los panos de un piso y acumula, para cada viga, el
    area tributaria que le llega desde los panos que la rodean.

    Una viga interior toca DOS panos (uno a cada lado) y por lo tanto
    acumula dos zonas; una viga de borde toca uno solo. Ese detalle es
    justamente lo que el reparto 50/50 no distingue.

    Las vigas se identifican por su posicion en la malla:
        ('X', ix, iy) = viga que corre en X, del pano ix al ix+1,
                        sobre la linea de eje Y numero iy
        ('Y', ix, iy) = viga que corre en Y, del pano iy al iy+1,
                        sobre la linea de eje X numero ix

    Devuelve dict: clave de viga -> {
        'area'       : area tributaria total (m2),
        'luz'        : largo de la viga (m),
        'poligonos'  : lista de poligonos (uno por pano vecino),
    }
    """
    tributarias = {}

    def acumular(clave, luz, poligono):
        reg = tributarias.setdefault(
            clave, {'area': 0.0, 'luz': luz, 'poligonos': []})
        reg['area'] += area_poligono(poligono)
        reg['poligonos'].append(poligono)

    nx, ny = len(ejes_x), len(ejes_y)

    for ix in range(nx - 1):
        for iy in range(ny - 1):
            x0, x1 = ejes_x[ix], ejes_x[ix + 1]
            y0, y1 = ejes_y[iy], ejes_y[iy + 1]
            polis = poligonos_pano(x0, y0, x1, y1)

            Lx = x1 - x0
            Ly = y1 - y0

            # Las dos vigas que corren en X limitan el pano por abajo
            # (linea de eje iy) y por arriba (linea iy+1).
            acumular(('X', ix, iy),     Lx, polis['y0'])
            acumular(('X', ix, iy + 1), Lx, polis['y1'])

            # Las dos que corren en Y lo limitan por izquierda (eje ix)
            # y derecha (eje ix+1).
            acumular(('Y', ix,     iy), Ly, polis['x0'])
            acumular(('Y', ix + 1, iy), Ly, polis['x1'])

    return tributarias


def carga_lineal(q, area_tributaria, luz):
    """
    Convierte el area tributaria en la carga uniforme equivalente
    sobre la viga:

        w = q * A_trib / L        [kN/m]

    Se usa la equivalente que CONSERVA LA CARGA TOTAL (resultante
    estaticamente equivalente). La carga real que baja de la losa es
    triangular o trapezoidal; repartirla uniforme conserva la
    resultante -- que es lo que exige la verificacion de conservacion
    de carga -- pero da un momento algo distinto al real. Eso se
    documenta y se defiende, no se esconde.
    """
    if luz <= 0.0:
        raise ValueError(f"Luz invalida: {luz}")
    return q * area_tributaria / luz
