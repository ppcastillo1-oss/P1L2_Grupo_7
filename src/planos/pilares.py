# -*- coding: utf-8 -*-
r"""
================================================================
 pilares.py  -  PILARES: DE CUATRO LINEAS A UNA SECCION
================================================================
 En planta, un pilar se dibuja como el RECTANGULO de su seccion:
 cuatro segmentos sueltos en la capa de pilares. El modelo necesita
 su CENTRO (donde va el nodo) y sus lados b x h.

 ----------------------------------------------------------------
 COMO SE RECONSTRUYE
 ----------------------------------------------------------------
 1. Se agrupan los segmentos en COMPONENTES CONEXAS: dos segmentos
    quedan en el mismo grupo si comparten un extremo (con
    tolerancia; el CAD casi nunca cierra exacto).

 2. Cada grupo deberia ser un rectangulo. Se verifica antes de
    aceptarlo: el largo total de sus segmentos tiene que ser igual
    al perimetro de su caja envolvente. Si no lo es, el grupo NO es
    un rectangulo (puede ser un pilar en L, un pilar con chaflan, o
    dos pilares que se tocan) y se reporta en vez de aceptarse.

 Esa verificacion es el punto: sin ella, cualquier maraña de lineas
 produce una "seccion" con la caja envolvente como dimensiones, y
 un pilar de 70x70 se convertiria en uno de 300x200 sin que nada
 avise.

 ----------------------------------------------------------------
 ETIQUETAS
 ----------------------------------------------------------------
 El plano rotula las secciones como texto: "P.70x70". Si se le
 pasan los textos de la capa de etiquetas, cada pilar se queda con
 la etiqueta mas cercana a su centro, y ademas se COMPARA la
 seccion leida del texto contra la medida en el dibujo. Cuando no
 calzan, se reporta: uno de los dos esta mal, y hay que mirar.
================================================================
"""
from __future__ import annotations

import collections
import math
import re

try:
    from . import lectura
except ImportError:
    import lectura

Pilar = collections.namedtuple(
    'Pilar', 'x y b h area cerrado etiqueta seccion_etiqueta calza_etiqueta')

TOL_NODO = 0.02          # m: dos extremos "son el mismo punto"
TOL_RECTANGULO = 0.05    # 5%: tolerancia normal de cierre del contorno
FALTA_MAX = 0.35         # 35%: cuanto puede faltar de perimetro (lado abierto)
LADO_MIN = 0.15          # m: menos que esto no es un pilar
LADO_MAX = 3.00          # m: mas que esto es otra cosa (un muro, un corte)
DIST_ETIQUETA_MAX = 2.0  # m: cuan lejos puede estar el texto de su pilar

# "P.70x70", "70/70", "P 30X100", "PILAR 25x60"
_SECCION = re.compile(r'(\d+(?:[.,]\d+)?)\s*[xX/]\s*(\d+(?:[.,]\d+)?)')


def seccion_de_texto(t):
    """Lee 'P.70x70' -> (0.70, 0.70) en metros. None si no calza."""
    m = _SECCION.search(t or '')
    if not m:
        return None
    try:
        a = float(m.group(1).replace(',', '.'))
        b = float(m.group(2).replace(',', '.'))
    except ValueError:
        return None
    # Los rotulos vienen en cm ("70x70"). Si el numero es chico ya
    # viene en metros ("0.70x0.70").
    if a > 5.0:
        a, b = a / 100.0, b / 100.0
    return (a, b)


# ============================================================
def _componentes(segmentos, tol=TOL_NODO):
    """Agrupa segmentos que comparten extremos (union-find sobre una grilla)."""
    padre = list(range(len(segmentos)))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    def unir(i, j):
        ri, rj = raiz(i), raiz(j)
        if ri != rj:
            padre[rj] = ri

    # Indice espacial por celdas de tamano tol, para no comparar
    # todos contra todos (con 300 pilares serian 90.000 pares).
    celdas = collections.defaultdict(list)
    for i, s in enumerate(segmentos):
        for (x, y) in ((s.x1, s.y1), (s.x2, s.y2)):
            celdas[(int(math.floor(x / tol)), int(math.floor(y / tol)))].append((i, x, y))

    for (cx, cy), items in list(celdas.items()):
        vecinos = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                vecinos.extend(celdas.get((cx + dx, cy + dy), ()))
        for (i, xi, yi) in items:
            for (j, xj, yj) in vecinos:
                if i != j and math.hypot(xi - xj, yi - yj) <= tol:
                    unir(i, j)

    grupos = collections.defaultdict(list)
    for i in range(len(segmentos)):
        grupos[raiz(i)].append(segmentos[i])
    return list(grupos.values())


def _rectangulo(grupo):
    """
    Si el grupo es un rectangulo, devuelve (cx, cy, b, h, cerrado).
    Si no lo es, None.

    La prueba es el largo total de los segmentos contra el perimetro
    de la caja envolvente, y los dos lados del error significan cosas
    distintas:

      SOBRA largo  -> hay lineas de mas: el grupo no es un rectangulo
                      (dos pilares pegados, un corte, una diagonal).
                      Se rechaza.

      FALTA largo  -> el contorno esta abierto. Pasa de verdad en el
                      plano: donde un muro llega al pilar, el
                      dibujante no cierra ese lado. Sigue siendo un
                      pilar y sus dimensiones son las de la caja; se
                      acepta marcado como no cerrado.

 Aceptar el exceso seria el error grave: convertiria cualquier
 maraña de lineas en un pilar del tamano de su caja envolvente.
    """
    xs = [v for s in grupo for v in (s.x1, s.x2)]
    ys = [v for s in grupo for v in (s.y1, s.y2)]
    b = max(xs) - min(xs)
    h = max(ys) - min(ys)
    if b <= 0 or h <= 0:
        return None
    perimetro = 2.0 * (b + h)
    total = sum(lectura.largo(s) for s in grupo)

    if total > perimetro * (1.0 + TOL_RECTANGULO):
        return None                                   # sobra: no es rectangulo
    if total < perimetro * (1.0 - FALTA_MAX):
        return None                                   # falta demasiado

    cerrado = total >= perimetro * (1.0 - TOL_RECTANGULO)
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, b, h, cerrado)


# ============================================================
def extraer(segmentos, etiquetas=(), lado_min=LADO_MIN, lado_max=LADO_MAX):
    """
    Devuelve (pilares, auditoria).

    'segmentos' : los de la capa de pilares, en metros y alineados.
    'etiquetas' : textos (namedtuple con .texto, .x, .y) de la capa
                  de etiquetas de seccion. Opcional.
    """
    grupos = _componentes(segmentos)

    pilares = []
    no_rectangulares = []
    fuera_de_rango = []

    for g in grupos:
        r = _rectangulo(g)
        if r is None:
            xs = [v for s in g for v in (s.x1, s.x2)]
            ys = [v for s in g for v in (s.y1, s.y2)]
            no_rectangulares.append({
                'n_segmentos': len(g),
                'centro': [round((min(xs) + max(xs)) / 2, 3),
                           round((min(ys) + max(ys)) / 2, 3)],
                'caja': [round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3)]})
            continue

        cx, cy, b, h, cerrado = r
        if not (lado_min <= b <= lado_max and lado_min <= h <= lado_max):
            fuera_de_rango.append({'centro': [round(cx, 3), round(cy, 3)],
                                   'b': round(b, 3), 'h': round(h, 3)})
            continue

        # Etiqueta mas cercana QUE SE PUEDA LEER COMO SECCION.
        #
        # El rotulo del plano viene partido en dos textos: "P." por un
        # lado y "70x70" por otro. Tomar el texto mas cercano a secas
        # devuelve "P." -- que no dice nada-- y el pilar se queda sin
        # verificacion. Hay que buscar el mas cercano ENTRE LOS QUE
        # traen dimensiones.
        etiqueta, sec = None, None
        candidatas = [(math.hypot(t.x - cx, t.y - cy), t) for t in etiquetas
                      if seccion_de_texto(t.texto)]
        if candidatas:
            dist, cerca = min(candidatas, key=lambda dt: dt[0])
            if dist <= DIST_ETIQUETA_MAX:
                etiqueta = cerca.texto.strip()
                sec = seccion_de_texto(etiqueta)

        calza = None
        if sec:
            # El rotulo puede venir en el otro orden (70x30 vs 30x70).
            calza = (abs(sec[0] - b) < 0.03 and abs(sec[1] - h) < 0.03) or \
                    (abs(sec[1] - b) < 0.03 and abs(sec[0] - h) < 0.03)

        pilares.append(Pilar(x=cx, y=cy, b=b, h=h, area=b * h, cerrado=cerrado,
                             etiqueta=etiqueta, seccion_etiqueta=sec,
                             calza_etiqueta=calza))

    pilares.sort(key=lambda p: (round(p.y, 2), round(p.x, 2)))

    discrepan = [{'centro': [round(p.x, 3), round(p.y, 3)],
                  'medido': [round(p.b, 3), round(p.h, 3)],
                  'etiqueta': p.etiqueta}
                 for p in pilares if p.calza_etiqueta is False]

    auditoria = {
        'segmentos_en_la_capa': len(segmentos),
        'grupos_encontrados': len(grupos),
        'pilares': len(pilares),
        'grupos_no_rectangulares': no_rectangulares,
        'rectangulos_fuera_de_rango': fuera_de_rango,
        'con_etiqueta': sum(1 for p in pilares if p.etiqueta),
        'contorno_abierto': [{'centro': [round(p.x, 3), round(p.y, 3)],
                              'seccion': [round(p.b, 3), round(p.h, 3)]}
                             for p in pilares if not p.cerrado],
        'etiqueta_no_calza_con_el_dibujo': discrepan,
        'secciones': sorted(collections.Counter(
            '%.2fx%.2f' % (min(p.b, p.h), max(p.b, p.h)) for p in pilares).items()),
    }
    return pilares, auditoria


def a_json(pilares):
    return [{'x': round(p.x, 4), 'y': round(p.y, 4),
             'b': round(p.b, 3), 'h': round(p.h, 3),
             'etiqueta': p.etiqueta, 'contorno_cerrado': p.cerrado}
            for p in pilares]
