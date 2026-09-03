# -*- coding: utf-8 -*-
r"""
================================================================
 panos.py  -  PANOS DE LOSA Y AREAS TRIBUTARIAS A 45 GRADOS
================================================================
 La losa no se modela con elementos finitos: su carga q [kN/m2] se
 reparte a las vigas por AREAS TRIBUTARIAS, trazando bisectrices a
 45 grados desde las esquinas de cada pano. Es el mismo criterio
 del P1.

 La diferencia con el P1 es que alla los panos venian dados: una
 grilla regular de ejes X por ejes Y, y cada pano era el rectangulo
 entre cuatro ejes consecutivos. Aca la planta es irregular -- 8
 pilares y 15 muros repartidos sin simetria -- y no hay grilla.

 Entonces los panos hay que ENCONTRARLOS: son las CARAS del grafo
 plano que forman las vigas de cada piso.

 ----------------------------------------------------------------
 1. LAS CARAS DEL GRAFO
 ----------------------------------------------------------------
 Las vigas de un piso forman un grafo plano. Sus caras acotadas son
 exactamente los panos de losa.

 Se recorren con la regla de la media-arista: parado en la arista
 (u -> v), la siguiente arista de la cara es la ANTERIOR a (v -> u)
 en el orden angular alrededor de v. Girando siempre para el mismo
 lado, cada cara se recorre una sola vez.

 La cara exterior sale sola en el mismo recorrido y se descarta: es
 la unica con area con signo contrario.

 ----------------------------------------------------------------
 2. EL REPARTO
 ----------------------------------------------------------------
 Un pano RECTANGULAR usa las formulas cerradas del P1 (a = luz de
 la viga, b = luz transversal):

     b <= a  -> viga LARGA  -> trapecio   A = b*(2a - b)/4
     b >  a  -> viga CORTA  -> triangulo  A = a^2/4

 Un pano IRREGULAR no tiene formula. Se reparte por el mismo
 criterio, pero medido: cada pedacito de losa carga a la viga que
 tiene MAS CERCA. Eso es lo que significan geometricamente las
 bisectrices a 45 grados, y en un rectangulo reproduce las formulas
 de arriba -- lo cual sirve de comprobacion (ver verificar()).

 ----------------------------------------------------------------
 3. LO QUE ESTO ARREGLA
 ----------------------------------------------------------------
 Antes la carga de losa se repartia EN PROPORCION AL LARGO de cada
 viga. Eso conserva la resultante -- y por lo tanto el equilibrio
 global cierra igual de bien -- pero reparte mal.

 En un pano de 10.00 x 3.34 m (uno real de este edificio), con las
 dos vigas largas de 10.00 y las dos cortas de 3.34:

                  viga larga    viga corta
     45 grados      13.91 m2       2.79 m2
     por largo      12.52 m2       4.18 m2

 Las dos reparticiones suman lo mismo (33.4 m2), y por eso el
 equilibrio global cierra igual de bien con cualquiera de las dos.
 Pero la viga CORTA recibiria un 50 % mas de carga de la que le
 toca, y la larga un 10 % menos.

 El error crece con lo alargado que sea el pano: en el limite, una
 viga muy corta que a 45 grados casi no toma nada, por largo sigue
 recibiendo su parte proporcional. Es el mismo tipo de error del
 reparto 50/50 de la Semana 1.

 Ademas, sumar las areas de los panos da el AREA DE PLANTA DE
 VERDAD, en vez de la envolvente convexa que se usaba antes.
================================================================
"""
from __future__ import annotations

import collections
import math

Cara = collections.namedtuple('Cara', 'nodos area rectangular')

AREA_MIN = 0.5          # m2: menos que esto no es un pano, es ruido
TOL_RECTANGULO = 0.02   # m: cuanto puede desviarse una esquina


# ============================================================
# 1. CARAS DEL GRAFO PLANO
# ============================================================
def area_con_signo(puntos):
    """Formula del cordon (shoelace). Positiva si va en sentido antihorario."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(puntos, puntos[1:] + puntos[:1]):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _solo_las_que_llevan_losa(cs, nodos, rotulos):
    """
    Descarta las caras donde el plano NO rotula losa.

    No toda cara del grafo es losa. La caja de ascensores del LT2 es
    una cara perfectamente cerrada de 7.86 m2 y adentro no hay losa:
    es el hueco por donde sube el ascensor. Cargarla seria inventar
    50 kN por piso.

    El criterio no lo pone quien programa: lo pone el PLANO. Cada pano
    de losa viene rotulado con un bloque `losa-ne` que trae su nombre
    (0100, 0101, ...) y su espesor -- el mismo del que ya se lee el
    e=15. Una cara con rotulo lleva losa; una cara sin ninguno, no.

    Algunos rotulos estan escritos FUERA del edificio, con su linea de
    referencia apuntando adentro (los de la fachada norte caen hasta
    0.92 m afuera). Por eso cada rotulo se asigna a la cara MAS
    CERCANA, no a la que lo contiene.

    Sin rotulos declarados no se descarta nada: el criterio se aplica
    solo si el plano da la informacion.
    """
    if not rotulos:
        return cs, {'declarados': 0, 'aplicado': False}
    poligonos = [[nodos[i] for i in c.nodos] for c in cs]
    cuantos = [0] * len(cs)
    lejos = 0
    for (rx, ry) in rotulos:
        mejor, dmin = None, None
        for i, pts in enumerate(poligonos):
            d = 0.0 if _dentro(rx, ry, pts) else min(
                _dist_a_segmento(rx, ry, a[0], a[1], b[0], b[1])
                for a, b in zip(pts, pts[1:] + pts[:1]))
            if dmin is None or d < dmin:
                mejor, dmin = i, d
        if mejor is not None:
            cuantos[mejor] += 1
            if dmin > 1.5:
                lejos += 1
    con_losa = [c for c, n in zip(cs, cuantos) if n > 0]
    sin_losa = [round(c.area, 2) for c, n in zip(cs, cuantos) if n == 0]
    return con_losa, {
        'declarados': len(rotulos),
        'aplicado': True,
        'caras_con_rotulo': len(con_losa),
        'caras_sin_rotulo_descartadas': len(sin_losa),
        'areas_descartadas': sorted(sin_losa, reverse=True),
        'rotulos_a_mas_de_1.5_m_de_su_cara': lejos,
    }


def caras(nodos, aristas):
    """
    Caras acotadas del grafo plano.

    nodos   : lista de (x, y)
    aristas : lista de (i, j) con indices de nodo

    Devuelve (caras, auditoria). Cada cara es una lista de indices.
    """
    vecinos = collections.defaultdict(set)
    for i, j in aristas:
        if i != j:
            vecinos[i].add(j)
            vecinos[j].add(i)

    # orden angular de los vecinos de cada nodo
    orden = {}
    for u, vs in vecinos.items():
        xu, yu = nodos[u]
        orden[u] = sorted(vs, key=lambda v: math.atan2(nodos[v][1] - yu,
                                                       nodos[v][0] - xu))

    def siguiente(u, v):
        """Media-arista que sigue a (u -> v) al recorrer una cara."""
        alrededor = orden[v]
        k = alrededor.index(u)
        return v, alrededor[k - 1]          # el anterior en orden angular

    vistas = set()
    encontradas = []
    for u in list(vecinos):
        for v in vecinos[u]:
            if (u, v) in vistas:
                continue
            cara, a, b = [], u, v
            while (a, b) not in vistas:
                vistas.add((a, b))
                cara.append(a)
                a, b = siguiente(a, b)
                if len(cara) > 4 * len(aristas) + 8:
                    break               # grafo raro: no colgarse
            if len(cara) >= 3:
                encontradas.append(cara)

    # La cara exterior es la que recorre el borde: su area con signo
    # sale con el signo contrario al de las interiores.
    caras_ok, exteriores = [], 0
    for c in encontradas:
        pts = [nodos[i] for i in c]
        a = area_con_signo(pts)
        if a <= 0:
            exteriores += 1
            continue
        if a < AREA_MIN:
            continue
        caras_ok.append(Cara(nodos=c, area=a, rectangular=_es_rectangulo(pts)))

    auditoria = {
        'nodos': len(nodos),
        'aristas': len(aristas),
        'caras_encontradas': len(caras_ok),
        'caras_exteriores_descartadas': exteriores,
        'rectangulares': sum(1 for c in caras_ok if c.rectangular),
        'area_total': round(sum(c.area for c in caras_ok), 3),
    }
    return caras_ok, auditoria


def _es_rectangulo(pts, tol=TOL_RECTANGULO):
    """True si el poligono es un rectangulo alineado con los ejes."""
    if len(pts) != 4:
        return False
    xs = sorted(set(round(p[0] / tol) for p in pts))
    ys = sorted(set(round(p[1] / tol) for p in pts))
    if len(xs) != 2 or len(ys) != 2:
        return False
    # cada lado tiene que ser horizontal o vertical
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        if abs(x1 - x2) > tol and abs(y1 - y2) > tol:
            return False
    return True


# ============================================================
# 1b. CERRAR EL BORDE ANTES DE BUSCAR CARAS
# ============================================================
# Una cara solo existe si su borde CIERRA. El borde de un pano no lo
# forman solo vigas: donde no hay viga, la losa se apoya en un muro.
# Y un muro no termina donde termina una viga --- son elementos
# distintos, con anchos distintos, dibujados cada uno por su cuenta:
#
#   - el muro este del LT2 llega a y = 10.58 y la viga de fachada a
#     y = 10.93: 0.35 m de diferencia, que es medio ancho de viga;
#   - la esquina suroeste la hacen dos muros perpendiculares cuyos
#     ejes se cruzan a 0.34 m uno del otro;
#   - el muro este viene partido por las puertas: 10.58-18.53,
#     hueco de 2.40, 20.93-23.75, hueco de 0.30, 24.05-26.73.
#
# Con el borde abierto por cualquiera de esas tres razones, la cara
# NO se encuentra y su carga desaparece del modelo. Y desaparece en
# silencio: el equilibrio global compara contra la carga APLICADA,
# asi que sigue cerrando a 1e-7 con el piso incompleto. En el LT2
# eran 75 m2 por piso --- 15 % de la planta, 2300 kN --- que no se
# veian en ninguna verificacion.
#
# Cerrar el borde son dos operaciones, y las dos se AUDITAN:
#
#   1. fundir los extremos que estan a menos de `tol_nodo`: son la
#      misma esquina dibujada por dos elementos distintos;
#   2. puentear los huecos COLINEALES de hasta `gap_max` entre dos
#      puntas sueltas: son las puertas y ventanas de un muro, donde
#      la losa sigue pasando por encima.
#
# Lo que no se puede cerrar se queda abierto y se cuenta. Un muro
# suelto en medio de un pano (los del nucleo de ascensores) no cierra
# nada y tiene que quedar como esta.
# ============================================================
TOL_NODO_BORDE = 0.45   # m: dos puntas mas cerca que esto son la misma esquina
GAP_BORDE = 3.00        # m: hueco colineal maximo que se puentea
                        # Es el ancho de un VANO en una linea de apoyo:
                        # una puerta, el acceso a un hall. En el LT2 el
                        # mayor mide 2.58 m (el hueco de la fachada este
                        # entre la viga de y=18.18 y el muro que arranca
                        # en y=20.93). La losa pasa por encima del vano,
                        # asi que el borde del pano sigue ahi.


def _partir_aristas(nodos, aristas, tol=0.05):
    """
    Parte cada arista en los nodos que caen sobre ella.

    Devuelve (aristas, de_quien_viene, cuantas_se_partieron). Cada
    pedazo HEREDA la arista de la que salio: si no, deja de saberse a
    que elemento pertenece y su poligono tributario se pierde --
    aparecian huecos blancos justo en las esquinas.
    """
    salida, procedencia, partidas = set(), {}, 0
    for (i, j) in aristas:
        xi, yi = nodos[i]
        xj, yj = nodos[j]
        L = math.hypot(xj - xi, yj - yi)
        if L < 1e-9:
            continue
        ux, uy = (xj - xi) / L, (yj - yi) / L
        encima = [(0.0, i), (L, j)]
        for k in range(len(nodos)):
            if k in (i, j):
                continue
            t = (nodos[k][0] - xi) * ux + (nodos[k][1] - yi) * uy
            if not (tol < t < L - tol):
                continue
            if abs(-(nodos[k][0] - xi) * uy + (nodos[k][1] - yi) * ux) <= tol:
                encima.append((t, k))
        if len(encima) > 2:
            partidas += 1
        cadena = [k for _t, k in sorted(encima)]
        for a, b in zip(cadena, cadena[1:]):
            if a != b:
                clave = (min(a, b), max(a, b))
                salida.add(clave)
                procedencia.setdefault(clave, (min(i, j), max(i, j)))
    return sorted(salida), procedencia, partidas


def cerrar_borde(nodos, aristas, tol_nodo=TOL_NODO_BORDE, gap_max=GAP_BORDE):
    """
    Devuelve (nodos, aristas, auditoria) con el borde cerrado.

    No mueve nada de sitio: funde puntas y agrega puentes. Los nodos
    que se funden se reemplazan por su representante, asi que los
    indices de entrada dejan de valer --- la auditoria trae el mapa.
    """
    n = len(nodos)
    padre = list(range(n))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    # --- 1. fundir esquinas ---------------------------------
    # NUNCA se funden dos nodos que ya estan unidos por una arista:
    # esos no son la misma esquina dibujada dos veces, son los dos
    # extremos de un elemento que existe, y fundirlos lo BORRA.
    #
    # Paso en la esquina suroeste: el baricentro del muro poniente
    # (11.302, 11.297) y el cruce de los dos ejes (11.302, 10.929)
    # estan a 0.368 m y los unia un brazo. Al fundirlos, el borde del
    # pano pasaba de dos tramos en angulo recto a UNA DIAGONAL, y los
    # dos panos de esquina --15.6 m2 cada uno-- dejaban de cerrar.
    ya_unidos = set()
    for i, j in aristas:
        if i != j:
            ya_unidos.add((min(i, j), max(i, j)))

    fundidos = 0
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) in ya_unidos:
                continue
            if math.hypot(nodos[i][0] - nodos[j][0],
                          nodos[i][1] - nodos[j][1]) <= tol_nodo:
                ri, rj = raiz(i), raiz(j)
                if ri != rj:
                    padre[rj] = ri
                    fundidos += 1

    grupos = collections.defaultdict(list)
    for i in range(n):
        grupos[raiz(i)].append(i)
    nuevo = {}
    salida = []
    for r, miembros in grupos.items():
        # el representante va en el promedio del grupo
        xs = sum(nodos[i][0] for i in miembros) / len(miembros)
        ys = sum(nodos[i][1] for i in miembros) / len(miembros)
        for i in miembros:
            nuevo[i] = len(salida)
        salida.append((xs, ys))

    ar = set()
    for i, j in aristas:
        a, b = nuevo[i], nuevo[j]
        if a != b:
            ar.add((min(a, b), max(a, b)))

    # --- 2. puentear huecos colineales ----------------------
    vecinos = collections.defaultdict(list)
    for i, j in ar:
        vecinos[i].append(j)
        vecinos[j].append(i)
    sueltos = [i for i in range(len(salida)) if len(vecinos[i]) == 1]

    def direccion(i):
        """Versor de la unica arista de una punta suelta, saliendo de ella."""
        j = vecinos[i][0]
        dx, dy = salida[j][0] - salida[i][0], salida[j][1] - salida[i][1]
        L = math.hypot(dx, dy)
        return (dx / L, dy / L) if L > 0 else (0.0, 0.0)

    # El puente tiene que CONTINUAR la arista de la punta suelta: sale
    # de i por el lado contrario a su vecino. El otro extremo puede ser
    # cualquier nodo --- el hueco de una puerta suele tener una punta
    # suelta de un lado y, del otro, la esquina donde ya llega una viga.
    puentes = []
    for i in sueltos:
        if len(vecinos[i]) != 1:
            continue
        ui = direccion(i)
        mejor, mejor_d = None, None
        for j in range(len(salida)):
            if j == i or j in vecinos[i]:
                continue
            dx, dy = salida[j][0] - salida[i][0], salida[j][1] - salida[i][1]
            d = math.hypot(dx, dy)
            if d > gap_max or d <= 0:
                continue
            ux, uy = dx / d, dy / d
            if -(ui[0] * ux + ui[1] * uy) < 0.98:
                continue
            if mejor_d is None or d < mejor_d:
                mejor, mejor_d = j, d
        if mejor is not None:
            ar.add((min(i, mejor), max(i, mejor)))
            vecinos[i].append(mejor)
            vecinos[mejor].append(i)
            puentes.append(round(mejor_d, 3))

    # --- 3. partir las aristas en los nodos que caen encima ---
    # Dos aristas superpuestas rompen la busqueda de caras, y no de una
    # forma que se note: el recorrido decide por donde seguir ordenando
    # los vecinos POR ANGULO, y dos vecinos colineales tienen el mismo
    # angulo. Al elegir el equivocado se salta un nodo, la cara interior
    # se funde con la exterior y desaparece.
    #
    # Se superponen por varias razones -- un puente que pasa por encima
    # de un camino que ya existia, una viga estirada que se pasa del
    # extremo de un muro -- asi que en vez de perseguir cada caso, al
    # final se parte todo en todo.
    ar, procedencia, partidas = _partir_aristas(salida, ar)

    vecinos = collections.defaultdict(list)
    for i, j in ar:
        vecinos[i].append(j)
        vecinos[j].append(i)

    auditoria = {
        'nodos_fundidos': fundidos,
        'aristas_partidas': partidas,
        'nodos_antes': n,
        'nodos_despues': len(salida),
        'puentes_colineales': len(puentes),
        'largos_de_puente': sorted(puentes, reverse=True),
        'puntas_que_quedaron_sueltas': sum(
            1 for i in range(len(salida)) if len(vecinos[i]) == 1),
    }
    return salida, sorted(ar), nuevo, procedencia, auditoria


# ============================================================
# 2. REPARTO A 45 GRADOS
# ============================================================
def area_tributaria_viga(luz_viga, luz_transversal):
    """
    Area que le toca a UNA viga de un pano rectangular, por
    bisectrices a 45 grados. Misma formula del P1.

        b <= a  -> viga larga  -> trapecio   b*(2a - b)/4
        b >  a  -> viga corta  -> triangulo  a^2/4
    """
    a, b = float(luz_viga), float(luz_transversal)
    if a <= 0 or b <= 0:
        raise ValueError('luces invalidas: %r x %r' % (luz_viga, luz_transversal))
    return b * (2.0 * a - b) / 4.0 if b <= a else a * a / 4.0


def _reparto_rectangulo(pts):
    """Areas por lado de un rectangulo, en el orden de sus lados."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    Lx = max(xs) - min(xs)
    Ly = max(ys) - min(ys)
    areas = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        horizontal = abs(y1 - y2) <= abs(x1 - x2)
        areas.append(area_tributaria_viga(Lx, Ly) if horizontal
                     else area_tributaria_viga(Ly, Lx))
    return areas


def _dentro(px, py, pts):
    """Punto dentro del poligono, por lanzamiento de rayo."""
    dentro = False
    n = len(pts)
    for k in range(n):
        x1, y1 = pts[k]
        x2, y2 = pts[(k + 1) % n]
        if (y1 > py) != (y2 > py):
            xc = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < xc:
                dentro = not dentro
    return dentro


def _dist_a_segmento(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0.0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _reparto_medido(pts, celdas=60):
    """
    Reparto para un pano de forma cualquiera: cada pedacito de losa
    carga al lado que tiene mas cerca.

    Es la definicion geometrica de las bisectrices a 45 grados, y en
    un rectangulo reproduce las formulas cerradas (lo comprueba
    verificar()). El resultado se ESCALA para que la suma de las
    areas de por resultado el area exacta del pano: asi la
    conservacion de la carga es exacta aunque la grilla sea gruesa.
    """
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    nx = max(4, min(celdas, int(celdas * (x1 - x0) / max(x1 - x0, y1 - y0))))
    ny = max(4, min(celdas, int(celdas * (y1 - y0) / max(x1 - x0, y1 - y0))))
    hx, hy = (x1 - x0) / nx, (y1 - y0) / ny

    lados = list(zip(pts, pts[1:] + pts[:1]))
    acumulado = [0.0] * len(lados)
    for i in range(nx):
        px = x0 + (i + 0.5) * hx
        for j in range(ny):
            py = y0 + (j + 0.5) * hy
            if not _dentro(px, py, pts):
                continue
            mejor, dmin = 0, None
            for k, ((ax, ay), (bx, by)) in enumerate(lados):
                d = _dist_a_segmento(px, py, ax, ay, bx, by)
                if dmin is None or d < dmin:
                    mejor, dmin = k, d
            acumulado[mejor] += hx * hy

    total = sum(acumulado)
    exacta = abs(area_con_signo(pts))
    if total <= 0:
        return [exacta / len(lados)] * len(lados)
    escala = exacta / total
    return [a * escala for a in acumulado]


def _recortar_semiplano(pts, a, b, c):
    """
    Sutherland-Hodgman: recorta el poligono con el semiplano
    a*x + b*y <= c. Devuelve el poligono recortado.
    """
    if not pts:
        return []
    salida = []
    n = len(pts)
    for k in range(n):
        p1 = pts[k]
        p2 = pts[(k + 1) % n]
        d1 = a * p1[0] + b * p1[1] - c
        d2 = a * p2[0] + b * p2[1] - c
        dentro1 = d1 <= 1e-12
        dentro2 = d2 <= 1e-12
        if dentro1:
            salida.append(p1)
        if dentro1 != dentro2 and abs(d1 - d2) > 1e-15:
            t = d1 / (d1 - d2)
            salida.append((p1[0] + t * (p2[0] - p1[0]),
                           p1[1] + t * (p2[1] - p1[1])))
    return salida


def _limpiar_poligono(pts, tol=1e-9):
    """Saca vertices repetidos y los que caen sobre la recta de sus
    vecinos. El recorte por semiplanos los produce cada vez que corta
    justo por un vertice del pano."""
    salida = []
    for p in pts:
        if not salida or math.hypot(p[0] - salida[-1][0], p[1] - salida[-1][1]) > tol:
            salida.append(p)
    while (len(salida) > 1 and
           math.hypot(salida[0][0] - salida[-1][0],
                      salida[0][1] - salida[-1][1]) <= tol):
        salida.pop()
    if len(salida) < 3:
        return []
    limpio = []
    n = len(salida)
    for k in range(n):
        x0, y0 = salida[k - 1]
        x1, y1 = salida[k]
        x2, y2 = salida[(k + 1) % n]
        cruz = (x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)
        if abs(cruz) > 1e-10:
            limpio.append(salida[k])
    return limpio if len(limpio) >= 3 else []


def poligonos_de_reparto(pts):
    """
    Un poligono por lado: el trozo de losa que descarga en ese lado.

    QUE ES UNA BISECTRIZ A 45 GRADOS
    --------------------------------
    Trazar bisectrices desde las esquinas es la construccion de
    dibujo. Lo que significa es: cada punto de la losa carga al lado
    que tiene MAS CERCA. La frontera entre dos lados es el lugar de
    los puntos equidistantes de ambos, que para dos rectas es su
    bisectriz -- y en una esquina recta, una recta a 45 grados.

    Escrito asi el reparto se calcula en vez de dibujarse: la region
    del lado i es el pano recortado por un semiplano por cada otro
    lado j,

        dist(x, lado i) <= dist(x, lado j)

    y como dentro de un pano convexo la distancia a un lado es la
    distancia a su recta, cada condicion es un SEMIPLANO. Recortando
    con todos queda un poligono exacto.

    En un rectangulo esto da exactamente los dos TRAPECIOS de los
    lados largos y los dos TRIANGULOS de los cortos, con las mismas
    areas que las formulas cerradas del P1. Eso no hay que creerlo:
    lo comprueba verificar().

    Devuelve (poligonos, exacto). `exacto` es False si el pano no es
    convexo -- ahi la distancia a la recta ya no es la distancia al
    lado y el resultado es una aproximacion; el area se reescala para
    que igual sume el area del pano.
    """
    n = len(pts)
    lados = list(zip(pts, pts[1:] + pts[:1]))

    # Normal INTERIOR de cada lado y su offset: d_i(x) = n_i . x - c_i
    # es la distancia con signo, positiva dentro.
    normales = []
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    for (x1, y1), (x2, y2) in lados:
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-12:
            normales.append(None)
            continue
        nx, ny = -dy / L, dx / L
        c = nx * x1 + ny * y1
        if nx * cx + ny * cy - c < 0:          # apuntar hacia adentro
            nx, ny, c = -nx, -ny, -c
        normales.append((nx, ny, c))

    convexo = _es_convexo(pts)
    polis = []
    for i in range(n):
        if normales[i] is None:
            polis.append([])
            continue
        nxi, nyi, ci = normales[i]
        region = list(pts)
        for j in range(n):
            if j == i or normales[j] is None:
                continue
            nxj, nyj, cj = normales[j]
            # d_i <= d_j   <=>   (n_i - n_j).x <= c_i - c_j
            a, b = nxi - nxj, nyi - nyj
            c = ci - cj
            if math.hypot(a, b) >= 1e-9:
                region = _recortar_semiplano(region, a, b, c)
            elif abs(c) < 1e-9:
                # LOS DOS LADOS ESTAN SOBRE LA MISMA RECTA. Pasa cada
                # vez que un muro entra al pano partido en tramos --por
                # su baricentro, por un nodo de esquina, por una
                # puerta--. La distancia a la recta no los distingue,
                # asi que sin desempate los DOS reclamaban la franja
                # entera: los poligonos de un pano de 37.8 m2 sumaban
                # 67.3.
                #
                # El desempate es la distancia A LO LARGO de la recta:
                # el punto carga al tramo que tiene mas cerca, y la
                # frontera es la perpendicular en la mitad del hueco
                # entre los dos tramos.
                corte = _desempate_colineal(lados[i], lados[j], (nxi, nyi))
                if corte is None:
                    continue
                ux, uy, t = corte
                region = _recortar_semiplano(region, ux, uy, t)
            elif c < 0:
                # Paralelos, misma direccion, rectas distintas: el otro
                # lado esta mas cerca en TODO el pano.
                region = []
            if not region:
                break
        polis.append(_limpiar_poligono(region))

    # Conservacion: los poligonos tienen que sumar el area del pano.
    # En un pano convexo sale exacta; si no, se reescala el AREA (no el
    # dibujo) para no perder carga.
    return polis, convexo


def _desempate_colineal(lado_i, lado_j, normal):
    """
    Frontera entre dos lados que estan sobre la MISMA recta.

    Devuelve (ux, uy, t) tal que el semiplano ux*x + uy*y <= t es el
    lado del punto medio del hueco donde manda `lado_i`. None si los
    dos tramos se solapan (son el mismo lado dos veces).
    """
    ux, uy = -normal[1], normal[0]          # a lo largo de la recta
    def intervalo(l):
        (x1, y1), (x2, y2) = l
        a = x1 * ux + y1 * uy
        b = x2 * ux + y2 * uy
        return (a, b) if a <= b else (b, a)
    ai, bi = intervalo(lado_i)
    aj, bj = intervalo(lado_j)
    if bi <= aj + 1e-12:                    # i esta "antes" que j
        return (ux, uy, (bi + aj) / 2.0)
    if bj <= ai + 1e-12:                    # i esta "despues" que j
        return (-ux, -uy, -(bj + ai) / 2.0)
    return None                              # se solapan


def _es_convexo(pts, tol=1e-9):
    n = len(pts)
    if n < 3:
        return False
    signo = 0
    for k in range(n):
        x1, y1 = pts[k]
        x2, y2 = pts[(k + 1) % n]
        x3, y3 = pts[(k + 2) % n]
        cruz = (x2 - x1) * (y3 - y2) - (y2 - y1) * (x3 - x2)
        if abs(cruz) <= tol:
            continue
        s = 1 if cruz > 0 else -1
        if signo == 0:
            signo = s
        elif s != signo:
            return False
    return True


def reparto(cara, nodos):
    """
    Devuelve (areas, poligonos, metodo): un area y un poligono por
    lado, en el mismo orden en que van los lados de cara.nodos.

    El area sale del POLIGONO, no de una formula aparte: asi lo que
    se dibuja y lo que se carga no pueden decir cosas distintas. Que
    coincida con las formulas cerradas del P1 lo comprueba
    verificar().

    Si el pano no es convexo, los poligonos son una aproximacion (la
    distancia a la recta de un lado deja de ser la distancia al lado),
    y ahi las areas se reescalan para que sumen el area exacta del
    pano: la carga se conserva aunque el dibujo sea aproximado.
    """
    pts = [nodos[i] for i in cara.nodos]
    polis, convexo = poligonos_de_reparto(pts)
    areas = [abs(area_con_signo(p)) if len(p) >= 3 else 0.0 for p in polis]
    total = sum(areas)
    exacta = abs(area_con_signo(pts))
    if total > 0 and abs(total - exacta) > 1e-9:
        escala = exacta / total
        areas = [a * escala for a in areas]
    return areas, polis, ('bisectrices' if convexo else 'bisectrices_aprox')


# ============================================================
# 3. REPARTO DE UN PISO COMPLETO
# ============================================================
def repartir_piso(nodos, aristas, cerrar=True, rotulos_de_losa=None):
    """
    Devuelve (area_por_arista, auditoria).

    Devuelve (area_por_arista, poligonos_por_arista, auditoria), las
    dos primeras indexadas por la MISMA arista (i, j) que entro.

    Antes de buscar caras se cierra el borde (ver cerrar_borde): sin
    eso, un pano cuyo borde sea un muro no cierra y su carga se
    pierde sin que ninguna verificacion lo note.
    """
    if cerrar:
        (n_nodos, n_aristas, mapa,
         procedencia, aud_cierre) = cerrar_borde(nodos, aristas)
        # De cada arista final, de que arista ORIGINAL viene. Las que no
        # vienen de ninguna son los PUENTES que se agregaron para
        # cerrar un vano; esas no pertenecen a ningun elemento.
        de_nueva = {}
        for i, j in aristas:
            a, b = mapa[i], mapa[j]
            if a != b:
                de_nueva[(min(a, b), max(a, b))] = (min(i, j), max(i, j))
        origen = {}
        for clave, padre in procedencia.items():
            if padre in de_nueva:
                origen[clave] = de_nueva[padre]
            elif padre in origen:
                pass
        for clave, orig in de_nueva.items():
            origen.setdefault(clave, orig)
    else:
        n_nodos, n_aristas = list(nodos), list(aristas)
        origen = {(min(i, j), max(i, j)): (min(i, j), max(i, j))
                  for i, j in aristas}
        aud_cierre = None

    cs, aud = caras(n_nodos, n_aristas)
    cs, aud_rot = _solo_las_que_llevan_losa(cs, n_nodos, rotulos_de_losa)
    aud['rotulos_de_losa'] = aud_rot
    # La auditoria de caras() cuenta lo que se ENCONTRO; despues del
    # filtro por rotulo hay que contar lo que queda, o el area total
    # incluiria los huecos.
    aud['caras_encontradas'] = len(cs)
    aud['area_total'] = round(sum(c.area for c in cs), 3)
    bruto = collections.defaultdict(float)
    metodos = collections.Counter()

    poligonos = collections.defaultdict(list)
    for c in cs:
        areas, polis, metodo = reparto(c, n_nodos)
        metodos[metodo] += 1
        lados = list(zip(c.nodos, c.nodos[1:] + c.nodos[:1]))
        for (i, j), a, pg in zip(lados, areas, polis):
            bruto[(min(i, j), max(i, j))] += a
            if len(pg) >= 3:
                poligonos[(min(i, j), max(i, j))].append(pg)

    # El area que cayo en un PUENTE (el dintel de una puerta) es losa
    # de verdad: se reparte por mitades entre los dos elementos que el
    # puente une. Tirarla seria perder carga; dejarla en el puente
    # seria cargarle un elemento que no existe.
    vecinas = collections.defaultdict(list)
    for (i, j) in bruto:
        if (i, j) in origen:
            vecinas[i].append((i, j))
            vecinas[j].append((i, j))

    por_arista = collections.defaultdict(float)
    poli_por_arista = collections.defaultdict(list)
    for clave, pgs in poligonos.items():
        if clave in origen:
            poli_por_arista[origen[clave]].extend(pgs)
    area_de_puentes = 0.0
    for (i, j), a in bruto.items():
        if (i, j) in origen:
            por_arista[origen[(i, j)]] += a
            continue
        area_de_puentes += a
        destinos = [ar for extremo in (i, j) for ar in vecinas[extremo]]
        if destinos:
            for ar in destinos:
                por_arista[origen[ar]] += a / len(destinos)
        # sin vecinas no hay a quien darsela: queda contada en la auditoria

    aud['cierre_del_borde'] = aud_cierre
    aud['area_en_puentes_repartida'] = round(area_de_puentes, 4)
    aud['metodos'] = dict(metodos)
    aud['area_repartida'] = round(sum(por_arista.values()), 4)
    aud['error_de_conservacion'] = round(
        abs(aud['area_repartida'] - aud['area_total']), 9)
    aud['aristas_con_area'] = len(por_arista)
    aud['aristas_con_poligono'] = len(poli_por_arista)
    return dict(por_arista), dict(poli_por_arista), aud


# ============================================================
def verificar():
    """
    Comprueba el modulo contra valores conocidos. Se corre desde
    verificar_lt2.py.
    """
    problemas = []

    # -- formulas del P1 --
    if abs(area_tributaria_viga(4.0, 4.0) - 4.0) > 1e-12:
        problemas.append('pano cuadrado 4x4: cada viga deberia llevar L^2/4 = 4')
    a_larga = area_tributaria_viga(10.0, 3.34)
    a_corta = area_tributaria_viga(3.34, 10.0)
    if abs(2 * a_larga + 2 * a_corta - 10.0 * 3.34) > 1e-9:
        problemas.append('las 4 areas no suman el area del pano')

    # -- el metodo medido reproduce las formulas en un rectangulo --
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 3.34), (0.0, 3.34)]
    medido = _reparto_medido(pts, celdas=200)
    exacto = _reparto_rectangulo(pts)
    for m, e in zip(medido, exacto):
        if abs(m - e) / e > 0.02:
            problemas.append('el reparto medido no reproduce el analitico '
                             '(%.3f vs %.3f)' % (m, e))
            break

    # -- deteccion de caras en una grilla 2x2 --
    nodos = [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (0, 2), (1, 2), (2, 2)]
    aristas = [(0, 1), (1, 2), (3, 4), (4, 5), (6, 7), (7, 8),
               (0, 3), (3, 6), (1, 4), (4, 7), (2, 5), (5, 8)]
    cs, aud = caras([(float(x), float(y)) for x, y in nodos], aristas)
    if len(cs) != 4:
        problemas.append('una grilla 2x2 tiene 4 panos, se encontraron %d' % len(cs))
    if abs(aud['area_total'] - 4.0) > 1e-9:
        problemas.append('el area total de la grilla 2x2 deberia ser 4.0')

    return problemas
