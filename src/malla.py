# -*- coding: utf-8 -*-
r"""
================================================================
 malla.py  -  DE EJES DIBUJADOS A UNA MALLA CONECTADA
================================================================
 El plano da ejes sueltos: 45 vigas, 8 pilares, 15 muros, cada uno
 con sus coordenadas. Eso NO es un modelo: para que sea un modelo
 los elementos tienen que compartir nodos.

 ----------------------------------------------------------------
 EL ERROR QUE MOTIVA ESTE MODULO
 ----------------------------------------------------------------
 La primera version colgaba cada extremo de viga del pilar o muro
 mas cercano. Descarto 215 de 246 vigas y la matriz salio singular.

 La razon es que en este edificio la mayoria de las vigas NO llegan
 a un pilar: llegan a OTRA VIGA. Hay 23 puntos verticales por piso
 y 45 vigas. Buscar solo pilares y muros deja fuera casi todo.

 Ademas los ejes ni siquiera se tocan: el eje de una viga se corta
 en la CARA de la viga a la que llega, no en su eje. Un encuentro
 en T queda con los dos ejes separados hasta medio ancho de viga
 (0.30 m con las vigas de 60 de este edificio). Buscar coincidencia
 exacta de extremos no encuentra nada.

 ----------------------------------------------------------------
 LO QUE HACE
 ----------------------------------------------------------------
 1. Toma como nodos PRIORITARIOS las anclas verticales (centro de
    pilar, baricentro de muro). Son las que mandan: si una viga
    termina cerca de un pilar, el nodo es el pilar.

 2. Para cada viga junta todos los puntos donde debe partirse:
      - sus dos extremos;
      - las anclas que caen sobre su eje;
      - los cruces con las otras vigas.
    Los cruces se aceptan con un margen, porque los ejes se cortan
    en la cara y no llegan a tocarse.

 3. Funde los puntos cercanos en un solo nodo (las anclas absorben
    a los demas) y parte cada viga en tramos entre nodos
    consecutivos.

 4. Verifica la CONECTIVIDAD: un grupo de vigas que no toca ningun
    elemento vertical flota. En el modelo eso da matriz singular, y
    el mensaje de OpenSees no dice cual es la viga culpable. Aca se
    detecta y se reporta con coordenadas.
================================================================
"""
from __future__ import annotations

import collections
import math

Nodo = collections.namedtuple('Nodo', 'x y tipo datos')
Tramo = collections.namedtuple('Tramo', 'i j largo viga')

TOL_NODO = 0.25       # m: dos puntos mas cerca que esto son el mismo nodo
MARGEN_CRUCE = 0.60   # m: cuanto puede sobresalir un cruce del tramo dibujado

# Tope de cuanto se puede correr un extremo de viga para llegar al
# nodo de un ancla.
#
# Sin este tope pasa algo feo. Un muro se modela como UNA columna
# ancha en su baricentro, asi que una viga que llega a la PUNTA de un
# muro de 8 m se estira 4 m para alcanzar el baricentro. Si eso pasa
# en los dos extremos, una viga de 8 m del plano se transforma en un
# elemento de 20 m que no existe. Medido: aparecio uno de 19.99 m y
# dio 678 mm de flecha donde el resto del piso daba 4.
#
# Con el tope, esas vigas no se conectan al muro y quedan reportadas.
# La solucion de fondo es el brazo rigido, no un tope mas grande.
ESTIRAMIENTO_MAX = 1.5

# Debajo de este estiramiento, la viga se lleva hasta el baricentro
# del muro en vez de conectarse con un brazo.
#
# El brazo existe para no inventar vano: una viga que llega a la punta
# de un muro de 8 m se estiraria 4 m. Pero en un muro CORTO el
# baricentro queda a un paso, y el brazo solo agrega un nodo mas y un
# elemento mas sin cambiar nada. Medido en el LT2 (10 brazos de 0.74 m
# en los muros de 1.45 m de las esquinas):
#
#     con brazo   UZ max = 6.6555 mm
#     estirando   UZ max = 6.6493 mm    ->   0.09 % de diferencia
#
# Se elige estirar: mismo resultado con 10 nodos y 10 elementos menos,
# y sin nodos dobles pegados en el visor.
BRAZO_MINIMO = 0.80


# (dx, dy) YA es un vector unitario: se calcula como (x2-x1)/L. Por
# eso estas dos funciones NO dividen por L.
#
# Dividir de mas fue un error caro: la distancia perpendicular de un
# muro que estaba a 20 m de una viga salia 20/6.65 = 0.26 m, o sea
# "pegado", y el mallador conectaba vigas con muros del otro extremo
# del edificio. Aparecian elementos de 20 m que no existen en el
# plano y una flecha de 678 mm donde el piso daba 4.
def _proyeccion(px, py, x1, y1, dx, dy, L):
    """Distancia, EN METROS, desde el inicio del eje hasta la proyeccion."""
    return (px - x1) * dx + (py - y1) * dy


def _distancia_perp(px, py, x1, y1, dx, dy, L):
    """Distancia perpendicular del punto a la recta del eje, en metros."""
    return abs(-(px - x1) * dy + (py - y1) * dx)


def _cruce(a, b):
    """
    Punto donde se cruzan los ejes de dos vigas, o None si son
    paralelos. Devuelve (x, y, ta, tb) con ta y tb en metros desde
    el inicio de cada viga.
    """
    ax, ay = a['x1'], a['y1']
    bx, by = b['x1'], b['y1']
    adx, ady, aL = a['dx'], a['dy'], a['L']
    bdx, bdy, bL = b['dx'], b['dy'], b['L']
    den = adx * bdy - ady * bdx
    if abs(den) < 1e-9:
        return None                      # paralelas
    ta = ((bx - ax) * bdy - (by - ay) * bdx) / den
    tb = ((bx - ax) * ady - (by - ay) * adx) / den
    return (ax + adx * ta, ay + ady * ta, ta, tb)


def _dist_a_segmento(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0.0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


# ============================================================
def m_datos(a):
    """El dict del muro de un ancla."""
    return a['datos']


def _proyectar_en_eje(px, py, m):
    """Pie de la perpendicular de (px, py) sobre el EJE del muro."""
    x1, y1, x2, y2 = m['x1'], m['y1'], m['x2'], m['y2']
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return (x1, y1)
    t = ((px - x1) * dx + (py - y1) * dy) / L2
    return (x1 + t * dx, y1 + t * dy)


def _sin_extremos_falsos(e, margen):
    """
    Agrega los dos extremos DIBUJADOS de la viga como cortes, salvo
    los que no son un nodo de verdad.

    El dibujo corta una viga en la CARA de aquello contra lo que
    llega, no en su eje. Una viga que baja por el eje C arranca en
    y = 11.23, que es la cara de la viga de fachada cuyo eje esta en
    y = 10.93. El cruce de ejes ya pone un nodo en 10.93; si ademas
    se conserva el extremo dibujado quedan DOS nodos a 0.30 m unidos
    por un trozo de viga de 0.30 m que no existe en ninguna parte.

    En el LT2 eran 50 pares por modelo: en el visor se veian como
    nodos dobles pegados, y en el calculo como tramos de 30 cm.

    La regla: el extremo dibujado se descarta si hay OTRO corte --un
    ancla o un cruce de ejes-- a menos de `margen` de el. Si no hay
    ninguno, el extremo es un extremo real y se conserva.
    """
    cortes = list(e['cortes'])
    sobran = 0
    for t_ext in e.get('extremos', ()):
        cerca = any(abs(t - t_ext) <= margen for t, _ia in cortes)
        if cerca:
            sobran += 1
        else:
            cortes.append([t_ext, None])
    return cortes, sobran


# ============================================================
def mallar(anclas, vigas, tol_nodo=TOL_NODO, margen=MARGEN_CRUCE,
           estiramiento_max=ESTIRAMIENTO_MAX, brazo_minimo=BRAZO_MINIMO):
    """
    anclas : lista de dicts {x, y, tipo, alcance, datos}
             'alcance' = hasta que distancia atrae a un extremo de viga
    vigas  : lista de dicts {x1, y1, x2, y2, ancho, alto, ...}

    Devuelve (nodos, tramos, auditoria).
    """
    # --- preparar los ejes de viga ---------------------------
    ejes = []
    for v in vigas:
        L = math.hypot(v['x2'] - v['x1'], v['y2'] - v['y1'])
        if L < 1e-6:
            continue
        ejes.append({'x1': v['x1'], 'y1': v['y1'], 'x2': v['x2'], 'y2': v['y2'],
                     'dx': (v['x2'] - v['x1']) / L, 'dy': (v['y2'] - v['y1']) / L,
                     'L': L, 'viga': v, 'cortes': []})

    # --- 1. las anclas son los nodos prioritarios ------------
    nodos = [Nodo(x=a['x'], y=a['y'], tipo=a['tipo'], datos=a.get('datos'))
             for a in anclas]

    def nodo_en(x, y, tipo='viga'):
        """Indice del nodo en (x, y); lo crea si no existe."""
        for i, n in enumerate(nodos):
            if math.hypot(n.x - x, n.y - y) <= tol_nodo:
                return i
        nodos.append(Nodo(x=x, y=y, tipo=tipo, datos=None))
        return len(nodos) - 1

    # --- 2. puntos de corte de cada viga ---------------------
    # Cada corte es (t, ancla) donde 't' es la distancia desde el
    # inicio de la viga y 'ancla' el indice del ancla si el nodo debe
    # SER esa ancla, o None si el nodo va sobre el eje de la viga.
    #
    # La distincion importa: si el corte de un ancla se pusiera sobre
    # el eje de la viga, ese punto no coincidiria con el nodo del
    # pilar o del muro y la viga quedaria colgando al lado, sin
    # conectarse a nada. Es exactamente lo que pasaba antes: 396
    # tramos "flotantes" y matriz singular.
    estiramientos = []
    brazos_pedidos = []          # (x, y, indice_de_ancla)

    # Los dos extremos DIBUJADOS de la viga entran como cortes, pero
    # marcados: mas abajo se descartan si a su lado hay un corte de
    # verdad (un ancla o un cruce de ejes). Ver _sin_extremos_falsos.
    for e in ejes:
        e['extremos'] = [0.0, e['L']]

    for e in ejes:
        for ia, a in enumerate(anclas):
            # --- caso (a): un EXTREMO de la viga llega al ancla ---
            # La viga se estira hasta el nodo del ancla (el centro del
            # pilar, o el baricentro del muro). El estiramiento se mide.
            for t_ext, (px, py) in ((0.0, (e['x1'], e['y1'])),
                                    (e['L'], (e['x2'], e['y2']))):
                if a['tipo'] == 'muro':
                    m = a['datos']
                    d = _dist_a_segmento(px, py, m['x1'], m['y1'], m['x2'], m['y2'])
                else:
                    d = math.hypot(px - a['x'], py - a['y'])
                if d > a['alcance']:
                    continue
                estira = math.hypot(px - a['x'], py - a['y'])
                if estira <= tol_nodo:
                    # El extremo YA esta en el nodo del ancla.
                    e['cortes'].append([t_ext, ia])
                elif a['tipo'] == 'pilar':
                    # A un PILAR la viga se estira hasta su EJE.
                    #
                    # Es la convencion de cualquier modelo de barras:
                    # las vigas y las columnas se cortan en el eje, y
                    # el largo de calculo de la viga es la distancia
                    # entre ejes. El plano dibuja la viga terminando
                    # en la CARA del pilar, que es donde termina el
                    # hormigon de la viga, no donde termina el
                    # elemento estructural.
                    #
                    # Lo que se estira es medio pilar: 0.35 m en el
                    # LT2. Un brazo rigido ahi seria mas exacto (es el
                    # rigid end offset), pero a cambio la viga deja de
                    # llegar al pilar: en el visor se ve un vano de
                    # 0.35 m entre la viga y la columna, y en el plano
                    # la viga SI llega. Vale mas que el modelo se
                    # parezca al plano.
                    e['cortes'].append([t_ext, ia])
                    estiramientos.append(estira)
                elif estira <= brazo_minimo:
                    # Muro corto: el baricentro queda a un paso del
                    # extremo de la viga. Ver la nota de brazo_minimo.
                    e['cortes'].append([t_ext, ia])
                    estiramientos.append(estira)
                else:
                    # Un MURO es otra cosa: se modela como UNA columna
                    # ancha en su baricentro, que puede estar a metros
                    # del punto donde llega la viga. Estirar la viga
                    # hasta alla inventaria vano y flexibilidad donde
                    # el muro es rigido --- una viga que llega a la
                    # punta de un muro de 8 m se estiraria 4 m. Se
                    # deja el nodo sobre el muro y se pide un BRAZO
                    # RIGIDO hasta el baricentro.
                    #
                    # El nodo va en el EJE del muro, no en su cara. El
                    # dibujo corta la viga en la cara -- la viga de
                    # fachada sur termina en x = 42.45 y el eje del
                    # muro oriente esta en 42.577 -- y con el nodo en
                    # la cara el brazo sale inclinado 13 cm y la
                    # esquina del edificio queda en diagonal en vez de
                    # en angulo recto.
                    #
                    # Solo se acepta si el corrimiento va A LO LARGO
                    # de la viga: si la moviera de lado le haria un
                    # codo, y eso pasa cuando la viga es casi paralela
                    # al muro (ahi el eje comun se arregla antes, en
                    # el ingestor).
                    qx, qy = _proyectar_en_eje(px, py, m_datos(a))
                    dpx, dpy = qx - px, qy - py
                    avance = dpx * e['dx'] + dpy * e['dy']
                    de_lado = abs(-dpx * e['dy'] + dpy * e['dx'])
                    if de_lado <= tol_nodo:
                        t_nuevo = t_ext + avance
                        brazos_pedidos.append((qx, qy, ia))
                        e['cortes'].append([t_nuevo, None])
                    else:
                        brazos_pedidos.append((px, py, ia))
                    estiramientos.append(estira)

            # --- caso (b): el ancla cae EN MEDIO de la viga -------
            # Aca se mide contra el NODO del ancla, no contra su
            # huella: partir la viga en un punto que despues salta
            # metros al costado deformaria la geometria.
            t = _proyeccion(a['x'], a['y'], e['x1'], e['y1'], e['dx'], e['dy'], e['L'])
            if tol_nodo < t < e['L'] - tol_nodo:
                d = _distancia_perp(a['x'], a['y'], e['x1'], e['y1'],
                                    e['dx'], e['dy'], e['L'])
                if d <= a['alcance']:
                    e['cortes'].append([t, ia])
                    estiramientos.append(d)

    # --- caso (c): cruces entre vigas ------------------------
    # Los ejes de dos vigas que se encuentran en T no llegan a
    # tocarse: el que llega se corta en la CARA del otro. Por eso el
    # cruce se acepta con un margen de medio ancho de viga.
    for i in range(len(ejes)):
        for j in range(i + 1, len(ejes)):
            r = _cruce(ejes[i], ejes[j])
            if r is None:
                continue
            _x, _y, ta, tb = r
            if (-margen <= ta <= ejes[i]['L'] + margen and
                    -margen <= tb <= ejes[j]['L'] + margen):
                # El corte va en el CRUCE DE LOS EJES, aunque caiga un
                # poco fuera del tramo dibujado. Nada de recortarlo al
                # extremo.
                #
                # Recortandolo, la viga en Y se quedaba con su nodo en
                # (27.35, 18.48) y la viga en X con el suyo en
                # (27.65, 18.18): 0.42 m de distancia, dos nodos
                # distintos, y las dos vigas SIN CONECTARSE aunque en
                # el plano se cruzan. Asi se perdian 100 tramos y con
                # ellos zonas enteras del piso.
                #
                # Un modelo de barras une los ejes en el cruce; que el
                # dibujo corte cada eje en la cara del otro es una
                # convencion de dibujo, no geometria estructural.
                ejes[i]['cortes'].append([ta, None])
                ejes[j]['cortes'].append([tb, None])

    # --- 3. partir cada viga ---------------------------------
    tramos = []
    extremos_descartados = 0
    for e in ejes:
        cortes, sobran = _sin_extremos_falsos(e, margen)
        extremos_descartados += sobran
        cortes = sorted(cortes, key=lambda c: c[0])
        fundidos = []
        for t, ia in cortes:
            if fundidos and t - fundidos[-1][0] < tol_nodo:
                # Al fundir dos cortes cercanos manda el del ancla:
                # el nodo tiene que quedar donde esta el elemento
                # vertical, no a 20 cm.
                if fundidos[-1][1] is None and ia is not None:
                    fundidos[-1][1] = ia
                continue
            fundidos.append([t, ia])
        if len(fundidos) < 2:
            continue

        indices = []
        for t, ia in fundidos:
            if ia is not None:
                indices.append(ia)
            else:
                indices.append(nodo_en(e['x1'] + e['dx'] * t,
                                       e['y1'] + e['dy'] * t))

        for a, b in zip(indices, indices[1:]):
            if a == b:
                continue
            L = math.hypot(nodos[b].x - nodos[a].x, nodos[b].y - nodos[a].y)
            if L < tol_nodo:
                continue
            tramos.append(Tramo(i=a, j=b, largo=L, viga=e['viga']))

    # --- 3b. brazos hacia el baricentro de los muros ---------
    # Un muro se modela como UNA columna ancha en su baricentro. Una
    # viga que llega a su punta queda a metros de ese nodo. Estirar
    # la viga hasta alla le inventa vano; dejarla suelta la deja sin
    # apoyo. Lo que corresponde es un BRAZO corto y rigido, que es lo
    # que fisicamente hay: el propio muro.
    #
    # Un brazo solo tiene sentido si en su punta LLEGA UNA VIGA: es lo
    # que une esa viga con el muro. Si la punta se quedo sin viga --
    # pasa cuando ese mismo extremo termino estirandose hasta el eje
    # de un pilar vecino -- el brazo queda colgando del muro, sin
    # unir nada. No revienta el analisis (el muro llega al suelo, asi
    # que la poda no lo ve) pero en el visor es un palo saliendo de
    # la nada. Se descartan y se cuentan.
    con_viga = set()
    for t in tramos:
        con_viga.add(t.i)
        con_viga.add(t.j)

    brazos = []
    vistos = set()
    sin_viga = 0
    for (px, py, ia) in brazos_pedidos:
        i = nodo_en(px, py)
        if i == ia:
            continue
        if i not in con_viga:
            sin_viga += 1
            continue
        clave = (min(i, ia), max(i, ia))
        if clave in vistos:
            continue
        vistos.add(clave)
        L = math.hypot(nodos[i].x - nodos[ia].x, nodos[i].y - nodos[ia].y)
        brazos.append(Tramo(i=i, j=ia, largo=L, viga=None))

    # --- 4. conectividad -------------------------------------
    # Un grupo de vigas que no toca ningun elemento vertical flota:
    # el diafragma lo sujeta en el plano, pero verticalmente queda
    # libre y la matriz sale singular. OpenSees dice "U(i,i)=0" y no
    # dice cual es la viga.
    padre = list(range(len(nodos)))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for t in tramos + brazos:
        ri, rj = raiz(t.i), raiz(t.j)
        if ri != rj:
            padre[rj] = ri

    verticales = {i for i, n in enumerate(nodos) if n.tipo in ('pilar', 'muro')}
    grupos_apoyados = {raiz(i) for i in verticales}

    tramos_flotantes = [t for t in tramos if raiz(t.i) not in grupos_apoyados]
    tramos = [t for t in tramos if raiz(t.i) in grupos_apoyados]

    # Se describen ANTES de compactar los nodos: despues los indices
    # cambian y apuntarian a otro lado (o fuera de la lista).
    descripcion_flotantes = [
        {'centro': [round((nodos[t.i].x + nodos[t.j].x) / 2, 2),
                    round((nodos[t.i].y + nodos[t.j].y) / 2, 2)],
         'largo': round(t.largo, 2)} for t in tramos_flotantes]

    # --- 5. sacar los nodos que quedaron sin nada -------------
    # Al descartar los tramos flotantes sus nodos quedan sin ningun
    # elemento. Si igual se crean, el diafragma les fija ux, uy y rz
    # pero uz, rx y ry quedan libres: matriz singular, y OpenSees
    # solo dice "U(i,i) = 0".
    #
    # Las anclas se conservan siempre y en su orden original: el
    # indice de un ancla es como los elementos verticales encuentran
    # su nodo en el piso de arriba y en el de abajo.
    brazos = [b for b in brazos if raiz(b.i) in grupos_apoyados]
    usados = ({t.i for t in tramos} | {t.j for t in tramos} |
              {b.i for b in brazos} | {b.j for b in brazos} | verticales)
    huerfanos = [i for i in range(len(nodos)) if i not in usados]

    if huerfanos:
        nuevo_indice = {}
        compactados = []
        for i, n in enumerate(nodos):
            if i in usados:
                nuevo_indice[i] = len(compactados)
                compactados.append(n)
        nodos = compactados
        tramos = [t._replace(i=nuevo_indice[t.i], j=nuevo_indice[t.j])
                  for t in tramos]
        brazos = [b._replace(i=nuevo_indice[b.i], j=nuevo_indice[b.j])
                  for b in brazos]

    auditoria = {
        'anclas': len(anclas),
        'vigas_de_entrada': len(vigas),
        'nodos': len(nodos),
        'nodos_de_ancla': len(verticales),
        'nodos_de_cruce_de_vigas': len(nodos) - len(verticales),
        'tramos_de_viga': len(tramos),
        'tramos_flotantes_descartados': descripcion_flotantes,
        'nodos_huerfanos': len(huerfanos),
        'subdivision_media': (round(len(tramos) / len(vigas), 2) if vigas else 0),
        'brazos': len(brazos),
        'extremos_dibujados_descartados': extremos_descartados,
        'brazos_sin_viga_descartados': sin_viga,
        'estiramiento_max': (round(max(estiramientos), 3) if estiramientos else 0.0),
        'estiramiento_mediano': (round(sorted(estiramientos)[len(estiramientos) // 2], 3)
                                 if estiramientos else 0.0),
    }
    return nodos, tramos, brazos, auditoria
