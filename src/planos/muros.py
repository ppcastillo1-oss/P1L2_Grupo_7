# -*- coding: utf-8 -*-
r"""
================================================================
 muros.py  -  MUROS: DE DOS CARAS A UN EJE CON ESPESOR
================================================================
 Un muro no se dibuja como una linea. Se dibuja como sus DOS
 CARAS: dos segmentos paralelos separados por el espesor.

       cara 1  ---------------------------
                                            } espesor
       cara 2  ---------------------------

 El modelo estructural necesita lo contrario: UN eje (la linea
 media) y un espesor, para poner ahi la "columna ancha".

 ----------------------------------------------------------------
 EL EMPAREJADO
 ----------------------------------------------------------------
 Dos segmentos son las caras del mismo muro si:

   1. son PARALELOS (dentro de una tolerancia angular);
   2. estan separados por una distancia perpendicular dentro del
      rango de espesores de muro plausibles;
   3. se SOLAPAN longitudinalmente. Sin esta condicion, dos muros
      distintos alineados uno detras del otro se emparejan entre
      si y aparece un muro fantasma que cruza el edificio.

 ----------------------------------------------------------------
 DOS ERRORES YA COMETIDOS EN ESTE PROYECTO (Semana 2)
 ----------------------------------------------------------------
 1. Agrupar por direccion REDONDEADA parte en dos grupos las caras
    de un mismo muro cuando el CAD las dejo con decimas de grado de
    diferencia. Salian muros DUPLICADOS con espesores distintos
    (0.10 y 0.50 m para el mismo muro). Por eso aca la comparacion
    angular es con tolerancia, no por grupos discretos.

 2. Una cara puede emparejarse con varias. Hay que llevar un indice
    GLOBAL de caras ya usadas y resolver primero los pares que mas
    se solapan; si no, la misma cara alimenta dos muros.

 ----------------------------------------------------------------
 POR QUE SE CONSUMEN TRAMOS Y NO CARAS ENTERAS
 ----------------------------------------------------------------
 Marcar la cara completa como "ya usada" pierde muros de verdad.
 En esta planta hay una cara de 9.44 m enfrentada a DOS caras, de
 4.90 m y 4.34 m, separadas por un vano:

     ---------------------------------------  cara larga (9.44)
     ----------------   -------------------   dos caras (vano en medio)

 Con el criterio "una cara, un muro", el primer tramo se lleva la
 cara larga y el segundo queda huerfano: un muro real desaparece
 del modelo sin que nada avise.

 Por eso lo que se consume es el TRAMO (el intervalo a lo largo de
 la cara), no la cara. La cara larga entrega dos pedazos y se
 modelan los dos muros.

 ----------------------------------------------------------------
 LO QUE ESTE METODO NO PUEDE RESOLVER
 ----------------------------------------------------------------
 Donde hay tres lineas paralelas juntas (muro con pilar embebido,
 o dos muros pegados), "la cara mas cercana" puede elegir mal. Eso
 NO se resuelve con geometria: hay que mirar el plano. El extractor
 reporta esos casos en la auditoria en vez de inventar.
================================================================
"""
from __future__ import annotations

import collections
import math

try:
    from . import lectura
except ImportError:
    import lectura

Muro = collections.namedtuple('Muro', 'x1 y1 x2 y2 largo espesor angulo')

TOL_ANGULO = 2.0        # grados: cuanto pueden diferir dos caras "paralelas"
SOLAPE_MIN = 0.5        # m: solape longitudinal minimo para aceptar el par

# Holgura de 1 mm en los limites de espesor. Los planos estan
# dibujados al centimetro, pero el espesor se calcula restando
# coordenadas: un muro de 0.60 m sale 0.6000000000000001 y queda
# FUERA de un limite de 0.60 escrito como <=. Se perdian muros
# reales por el ultimo bit del punto flotante.
EPS_ESPESOR = 1e-3


def _diferencia_angular(a, b):
    """Diferencia entre dos angulos en [0,180), considerando el ciclo."""
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _describir(s):
    """
    Parametriza una cara en un sistema comun a todas las paralelas:

        u  direccion unitaria CANONICA (siempre 'hacia la derecha',
           o hacia arriba si es vertical). Asi dos caras dibujadas
           en sentidos opuestos comparten parametro.
        t  intervalo [t1, t2] de la cara proyectada sobre u desde el
           origen global.
        d  distancia con signo a la recta paralela que pasa por el
           origen (la coordenada perpendicular).

    Con esto, comparar dos caras es comparar numeros: el espesor es
    |d_a - d_b| y el solape es la interseccion de los intervalos t.
    """
    L = lectura.largo(s)
    ux, uy = (s.x2 - s.x1) / L, (s.y2 - s.y1) / L
    if (ux < 0) or (abs(ux) < 1e-9 and uy < 0):     # canonizar el sentido
        ux, uy = -ux, -uy
    t1 = s.x1 * ux + s.y1 * uy
    t2 = s.x2 * ux + s.y2 * uy
    if t1 > t2:
        t1, t2 = t2, t1
    d = -s.x1 * uy + s.y1 * ux                       # componente normal
    return {'seg': s, 'u': (ux, uy), 't': (t1, t2), 'd': d,
            'ang': lectura.angulo(s), 'consumido': []}


def _libre(intervalo, consumidos, minimo):
    """
    Mayor sub-intervalo de 'intervalo' que no pisa ninguno de
    'consumidos'. None si no queda ninguno de largo >= minimo.
    """
    ini, fin = intervalo
    trozos = [(ini, fin)]
    for (ci, cf) in consumidos:
        nuevos = []
        for (a, b) in trozos:
            if cf <= a or ci >= b:              # no se tocan
                nuevos.append((a, b))
                continue
            if ci > a:
                nuevos.append((a, ci))
            if cf < b:
                nuevos.append((cf, b))
        trozos = nuevos
    if not trozos:
        return None
    mejor = max(trozos, key=lambda ab: ab[1] - ab[0])
    return mejor if (mejor[1] - mejor[0]) >= minimo else None


TOL_FUSION = 0.02       # m: hueco maximo para dar dos trozos por la misma recta


def fusionar_colineales(segmentos, tol=TOL_FUSION, gap_puente=0.0, largo_min=0.0):
    """
    Une los trozos consecutivos de una MISMA recta.

    Una cara no se dibuja como un segmento: se dibuja como una
    polilinea, y AutoCAD la entrega partida en cada vertice. La cara
    oeste del techo del LT2 llega en cuatro trozos de 0.28, 1.55,
    0.46 y 3.39 m -- una sola recta desde y=12.754 hasta y=18.729.

    Eso importa porque `extraer` tira las caras mas cortas que
    `largo_min` ANTES de emparejar. Los trozos de 0.28 y 0.46 m se
    perdian, el emparejamiento arrancaba un metro mas arriba, y la
    viga de fachada del techo quedaba empezando en el aire a 1.09 m
    del muro donde en realidad apoya.

    Fusionar no inventa nada: dos trozos colineales que se tocan SON
    una recta. Lo que sigue emparejando por intervalos es el mismo
    mecanismo de siempre, y si sobre esa recta hay dos muros
    distintos los sigue separando.

    `gap_puente` cierra ademas un hueco mayor, PERO SOLO si uno de los
    dos lados mide menos que `largo_min`. Eso distingue dos cosas que
    se parecen y no son iguales:

      - un CRUCE: donde otro elemento topa contra este muro, su cara
        interior queda cortada por el espesor del que llega. En la
        esquina poniente del LT2 la cara exterior corre entera de
        y=9.839 a 12.754, y la interior viene en 0.79 + hueco de
        0.30 + 1.83. Los 0.79 se descartaban por cortos, el muro
        salia de 1.82 m en vez de 2.92 y la esquina quedaba en L
        cuando el plano dibuja una T.

      - una PUERTA: los dos tramos son muro de verdad y los dos miden
        mas que `largo_min`. Ahi no se fusiona nada: son dos muros con
        un vano, y como tales van al modelo (unidos despues por el
        dintel, que en el modelo es un brazo rigido).

    Devuelve (segmentos, auditoria).
    """
    if not segmentos:
        return [], {'entraron': 0, 'salieron': 0, 'fusiones': 0}

    # Agrupar por recta: misma direccion y misma coordenada normal.
    grupos = []                       # [{'ang','d','u','trozos':[(t1,t2)],'capa'}]
    for s in segmentos:
        if lectura.largo(s) <= 0:
            continue
        info = _describir(s)
        for g in grupos:
            if (_diferencia_angular(g['ang'], info['ang']) <= TOL_ANGULO
                    and abs(g['d'] - info['d']) <= tol
                    and g['capa'] == s.capa):
                g['trozos'].append(info['t'])
                break
        else:
            grupos.append({'ang': info['ang'], 'd': info['d'], 'u': info['u'],
                           'capa': s.capa, 'trozos': [info['t']]})

    salida, fusiones, puentes = [], 0, []
    for g in grupos:
        for t1, t2 in sorted(g['trozos']):
            if salida and salida[-1][0] is g and t1 - salida[-1][2] <= tol:
                salida[-1][2] = max(salida[-1][2], t2)
                fusiones += 1
            else:
                salida.append([g, t1, t2])

    if gap_puente > 0.0 and largo_min > 0.0:
        unidos_2 = []
        for g, t1, t2 in salida:
            if unidos_2 and unidos_2[-1][0] is g:
                hueco = t1 - unidos_2[-1][2]
                corto = min(unidos_2[-1][2] - unidos_2[-1][1], t2 - t1) < largo_min
                if 0.0 <= hueco <= gap_puente and corto:
                    unidos_2[-1][2] = max(unidos_2[-1][2], t2)
                    puentes.append(round(hueco, 3))
                    continue
            unidos_2.append([g, t1, t2])
        salida = unidos_2

    unidos = []
    for g, t1, t2 in salida:
        ux, uy = g['u']
        nx, ny = -uy, ux
        d = g['d']
        unidos.append(lectura.Segmento(
            x1=ux * t1 + nx * d, y1=uy * t1 + ny * d,
            x2=ux * t2 + nx * d, y2=uy * t2 + ny * d, capa=g['capa']))

    return unidos, {'entraron': len(segmentos), 'salieron': len(unidos),
                    'fusiones': fusiones,
                    'puentes_sobre_un_cruce': len(puentes),
                    'huecos_puenteados': sorted(puentes, reverse=True)}


def extraer(segmentos, espesor_min=0.10, espesor_max=0.60, largo_min=1.0):
    """
    Empareja caras y devuelve (muros, auditoria).

    'segmentos' son los de la capa de muros, ya en metros y ya
    alineados al origen comun.
    """
    # Primero se rearman las rectas que el dibujo entrego partidas;
    # recien despues se descarta por largo. Al reves se pierden los
    # pedazos cortos de una cara larga (ver fusionar_colineales).
    # El hueco que puede abrir un CRUCE es, como mucho, el espesor del
    # elemento que cruza: por eso el tope del puente es `espesor_max`.
    segmentos, aud_fusion = fusionar_colineales(
        segmentos, gap_puente=espesor_max + EPS_ESPESOR, largo_min=largo_min)
    caras = [s for s in segmentos if lectura.largo(s) >= largo_min]
    descartadas_cortas = len(segmentos) - len(caras)
    info = [_describir(s) for s in caras]

    # --- todos los pares candidatos --------------------------
    candidatos = []
    for i in range(len(info)):
        a = info[i]
        for j in range(i + 1, len(info)):
            b = info[j]
            if _diferencia_angular(a['ang'], b['ang']) > TOL_ANGULO:
                continue
            espesor = abs(a['d'] - b['d'])
            if not (espesor_min - EPS_ESPESOR <= espesor <= espesor_max + EPS_ESPESOR):
                continue
            ini = max(a['t'][0], b['t'][0])
            fin = min(a['t'][1], b['t'][1])
            if fin - ini < SOLAPE_MIN:
                continue
            candidatos.append((fin - ini, espesor, i, j, ini, fin))

    # --- resolver: primero los pares que mas se solapan -------
    # Asi un muro largo y claro se queda con su tramo antes de que
    # un detalle corto se lo robe.
    candidatos.sort(key=lambda c: -c[0])

    muros = []
    rechazados_por_ocupado = 0
    for solape, espesor, i, j, ini, fin in candidatos:
        a, b = info[i], info[j]
        tramo = _libre((ini, fin), a['consumido'] + b['consumido'], SOLAPE_MIN)
        if tramo is None:
            rechazados_por_ocupado += 1
            continue
        t_ini, t_fin = tramo
        a['consumido'].append(tramo)
        b['consumido'].append(tramo)

        # eje = linea media, recortada al tramo donde las dos caras
        # coexisten (fuera de ese tramo no hay muro de dos caras)
        ux, uy = a['u']
        nx, ny = -uy, ux
        d_medio = (a['d'] + b['d']) / 2.0
        x1 = ux * t_ini + nx * d_medio
        y1 = uy * t_ini + ny * d_medio
        x2 = ux * t_fin + nx * d_medio
        y2 = uy * t_fin + ny * d_medio

        muros.append(Muro(x1=x1, y1=y1, x2=x2, y2=y2,
                          largo=math.hypot(x2 - x1, y2 - y1),
                          espesor=espesor,
                          angulo=a['ang']))

    sin_pareja = [c['seg'] for c in info if not c['consumido']]

    # Cuanto de cada cara quedo sin emparejar: es la medida honesta
    # de "cuanto muro dibujado NO llego al modelo".
    largo_caras = sum(lectura.largo(c['seg']) for c in info)
    largo_consumido = sum(f - i for c in info for (i, f) in c['consumido'])

    auditoria = {
        'segmentos_en_la_capa': len(segmentos),
        'fusion_de_rectas': aud_fusion,
        'descartados_por_cortos': descartadas_cortas,
        'caras_consideradas': len(caras),
        'muros_emparejados': len(muros),
        'caras_sin_pareja': len(sin_pareja),
        'caras_sin_pareja_largos': sorted(
            [round(lectura.largo(s), 2) for s in sin_pareja], reverse=True)[:10],
        'tramos_rechazados_por_ocupado': rechazados_por_ocupado,
        'largo_total_caras': round(largo_caras, 2),
        'largo_de_cara_emparejado': round(largo_consumido, 2),
        'cobertura': round(largo_consumido / largo_caras, 4) if largo_caras else 0.0,
        'largo_total_muros': round(sum(m.largo for m in muros), 2),
        'espesores': sorted(collections.Counter(
            round(m.espesor, 2) for m in muros).items()),
    }
    return muros, auditoria


def a_json(muros):
    return [{'x1': round(m.x1, 4), 'y1': round(m.y1, 4),
             'x2': round(m.x2, 4), 'y2': round(m.y2, 4),
             'largo': round(m.largo, 4), 'espesor': round(m.espesor, 3)}
            for m in muros]
