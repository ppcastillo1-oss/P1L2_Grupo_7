# -*- coding: utf-8 -*-
r"""
================================================================
 ejes.py  -  LA MALLA DE EJES, CON SUS NOMBRES
================================================================
 Los ejes son el esqueleto del modelo: cada nodo del modelo vive
 en un cruce de ejes, y cada elemento se identifica por los ejes
 que une ("el pilar del cruce B-2"). Si los ejes salen mal, todo
 lo demas sale mal.

 En la Semana 2 los ejes estaban ESCRITOS A MANO en
 modelo_edificio.py:

     EJES_X = [8.02, 11.32, 14.72, ...]

 Numeros sin nombre y sin trazabilidad. Aca se leen del plano y
 conservan el nombre que les puso el calculista (A, A', B, 1, 1',
 8A, 8B), que es el idioma con el que se lee el plano.

 ----------------------------------------------------------------
 COMO ESTA DIBUJADO UN EJE
 ----------------------------------------------------------------
 Dos cosas distintas, en dos capas distintas:

   - la LINEA del eje          (capa "ejes_lineas")
   - la BURBUJA con su nombre  (capa "ejes_rotulos": un circulo
                                con un texto adentro)

 Las burbujas se ponen en los bordes del dibujo, sobre cuatro
 "rieles": arriba y abajo para los ejes verticales, izquierda y
 derecha para los horizontales.

        A'   A    B    C          <- riel superior
        |    |    |    |
   1 ---+----+----+----+--- 1     <- rieles izquierdo y derecho
   2 ---+----+----+----+--- 2
        |    |    |    |
        A'   A    B    C          <- riel inferior

 ----------------------------------------------------------------
 COMO SE DECIDE SI UN EJE ES VERTICAL U HORIZONTAL
 ----------------------------------------------------------------
 1. La mayoria de los ejes tiene DOS burbujas con el mismo nombre.
    Si comparten x -> el eje es vertical (x constante).
    Si comparten y -> el eje es horizontal.
    Esto no admite ambiguedad y no depende de ninguna tolerancia
    fina.

 2. Con esos ejes ya resueltos se deducen los cuatro rieles.

 3. Los ejes con UNA sola burbuja (aca: 1', 1A', 2A', 8A, 8B, B',
    E1, E') se clasifican por el riel sobre el que esta la burbuja.

 Lo que no calza no se adivina: se reporta. Un eje mal orientado
 mueve una fila entera de nodos y el modelo no avisa.
================================================================
"""
from __future__ import annotations

import collections
import math

try:
    from . import lectura
except ImportError:
    import lectura

Eje = collections.namedtuple('Eje', 'nombre direccion coord n_burbujas apoyado_en_linea')
#  direccion: 'X' = eje vertical, de x constante  (recorre Y)
#             'Y' = eje horizontal, de y constante (recorre X)

# Tolerancias en METROS.
TOL_MISMA_COORD = 0.30    # dos burbujas del mismo eje: cuanto pueden diferir
TOL_RIEL = 1.50           # cuan cerca de un riel debe estar una burbuja suelta
TOL_LINEA = 0.30          # cuan cerca debe pasar la linea de eje de su coordenada


# ============================================================
def burbujas(hoja, perfil):
    """
    Burbujas de eje: (nombre, x, y).

    El texto y el circulo son entidades separadas; alcanza con el
    texto, que ya trae su punto de insercion en el centro.
    """
    salida = []
    for t in hoja.textos_de(perfil, 'ejes_rotulos'):
        nombre = t.texto.strip()
        if nombre:
            salida.append((nombre, t.x, t.y))
    return salida


def lineas_de_eje(hoja, perfil, largo_min=2.0):
    """
    Lineas de eje separadas en verticales y horizontales.

    Devuelve dos listas de coordenadas: (xs_verticales, ys_horizontales).
    Las lineas cortas (marcas, ticks) se descartan.
    """
    verticales, horizontales = [], []
    for s in hoja.segmentos_de(perfil, 'ejes_lineas'):
        if lectura.largo(s) < largo_min:
            continue
        a = lectura.angulo(s)
        if a < 5.0 or a > 175.0:
            horizontales.append((s.y1 + s.y2) / 2.0)
        elif 85.0 < a < 95.0:
            verticales.append((s.x1 + s.x2) / 2.0)
    return verticales, horizontales


# ============================================================
def _agrupar(valores, tol):
    """Agrupa valores parecidos y devuelve los promedios de cada grupo."""
    grupos = []
    for v in sorted(valores):
        if grupos and abs(v - grupos[-1][-1]) <= tol:
            grupos[-1].append(v)
        else:
            grupos.append([v])
    return [sum(g) / len(g) for g in grupos]


def _cerca_de(valor, referencias, tol):
    return any(abs(valor - r) <= tol for r in referencias)


def extraer(hoja, perfil):
    """
    Devuelve (ejes, auditoria).

    ejes      : lista de Eje, ordenada por direccion y coordenada
    auditoria : dict con lo que no se pudo resolver
    """
    por_nombre = collections.defaultdict(list)
    for nombre, x, y in burbujas(hoja, perfil):
        por_nombre[nombre].append((x, y))

    resueltos = {}          # nombre -> (direccion, coord)
    ambiguos = []
    sueltas = {}            # nombre -> [(x, y), ...]

    # --- paso 1: los que tienen dos o mas burbujas ---------
    for nombre, puntos in por_nombre.items():
        if len(puntos) < 2:
            sueltas[nombre] = puntos
            continue
        xs = [p[0] for p in puntos]
        ys = [p[1] for p in puntos]
        disp_x = max(xs) - min(xs)
        disp_y = max(ys) - min(ys)
        if disp_x <= TOL_MISMA_COORD and disp_y > TOL_MISMA_COORD:
            resueltos[nombre] = ('X', sum(xs) / len(xs))
        elif disp_y <= TOL_MISMA_COORD and disp_x > TOL_MISMA_COORD:
            resueltos[nombre] = ('Y', sum(ys) / len(ys))
        else:
            # burbujas repetidas del mismo nombre que no se alinean:
            # suele ser el mismo eje dibujado en dos vistas distintas
            # de la misma lamina. No se inventa: se reporta.
            ambiguos.append({'nombre': nombre, 'puntos': [[round(x, 3), round(y, 3)]
                                                          for x, y in puntos]})

    # --- paso 2: los cuatro rieles -------------------------
    # riel de los ejes verticales  = alturas (y) donde se ponen sus burbujas
    # riel de los ejes horizontales = abscisas (x) de sus burbujas
    rieles_y = _agrupar([y for n, (d, _) in resueltos.items() if d == 'X'
                         for _, y in por_nombre[n]], TOL_RIEL)
    rieles_x = _agrupar([x for n, (d, _) in resueltos.items() if d == 'Y'
                         for x, _ in por_nombre[n]], TOL_RIEL)

    xs_lineas, ys_lineas = lineas_de_eje(hoja, perfil)

    # --- paso 3: las burbujas solitarias -------------------
    sin_clasificar = []
    por_linea = []
    for nombre, puntos in sueltas.items():
        x, y = puntos[0]
        en_riel_vertical = _cerca_de(y, rieles_y, TOL_RIEL)     # esta arriba o abajo
        en_riel_horizontal = _cerca_de(x, rieles_x, TOL_RIEL)   # esta a izq o der
        if en_riel_vertical and not en_riel_horizontal:
            resueltos[nombre] = ('X', x)
            continue
        if en_riel_horizontal and not en_riel_vertical:
            resueltos[nombre] = ('Y', y)
            continue

        # No cae en ningun riel conocido. Pasa cuando la planta tiene
        # un cuerpo saliente con su propia fila de burbujas: en estos
        # planos, B' y E1 estan en y = 40.43 m, un riel que ningun eje
        # de dos burbujas usa.
        #
        # Desempate por la LINEA del eje: si hay una linea vertical a
        # esa misma x (y ninguna horizontal a esa y), el eje es
        # vertical. La linea es evidencia del dibujo, no una
        # suposicion sobre donde se rotulan las burbujas.
        hay_vertical = _cerca_de(x, xs_lineas, TOL_LINEA)
        hay_horizontal = _cerca_de(y, ys_lineas, TOL_LINEA)
        if hay_vertical and not hay_horizontal:
            resueltos[nombre] = ('X', x)
            por_linea.append({'nombre': nombre, 'direccion': 'X'})
        elif hay_horizontal and not hay_vertical:
            resueltos[nombre] = ('Y', y)
            por_linea.append({'nombre': nombre, 'direccion': 'Y'})
        else:
            sin_clasificar.append({
                'nombre': nombre,
                'punto': [round(x, 3), round(y, 3)],
                'motivo': ('cae en dos rieles a la vez' if en_riel_vertical else
                           'hay linea de eje en las dos direcciones' if hay_vertical
                           else 'no cae en ningun riel y no hay linea de eje')})

    # --- paso 4: contrastar con las lineas de eje ----------

    ejes = []
    for nombre, (direccion, coord) in resueltos.items():
        refs = xs_lineas if direccion == 'X' else ys_lineas
        ejes.append(Eje(nombre=nombre, direccion=direccion, coord=coord,
                        n_burbujas=len(por_nombre[nombre]),
                        apoyado_en_linea=_cerca_de(coord, refs, TOL_LINEA)))

    ejes.sort(key=lambda e: (e.direccion, e.coord))

    auditoria = {
        'burbujas_leidas': sum(len(p) for p in por_nombre.values()),
        'ejes_resueltos': len(ejes),
        'ejes_X': sum(1 for e in ejes if e.direccion == 'X'),
        'ejes_Y': sum(1 for e in ejes if e.direccion == 'Y'),
        'sin_linea_de_apoyo': [e.nombre for e in ejes if not e.apoyado_en_linea],
        'clasificados_por_linea': por_linea,
        'burbujas_ambiguas': ambiguos,
        'burbujas_sin_clasificar': sin_clasificar,
        'rieles_x': [round(v, 3) for v in rieles_x],
        'rieles_y': [round(v, 3) for v in rieles_y],
    }
    return ejes, auditoria


# ============================================================
def a_json(ejes):
    """Los ejes en la forma que consume el modelo."""
    return {
        'X': [{'nombre': e.nombre, 'coord': round(e.coord, 4)}
              for e in ejes if e.direccion == 'X'],
        'Y': [{'nombre': e.nombre, 'coord': round(e.coord, 4)}
              for e in ejes if e.direccion == 'Y'],
    }


def imprimir(ejes, auditoria):
    print('  ejes verticales   (x constante): %d' % auditoria['ejes_X'])
    for e in ejes:
        if e.direccion == 'X':
            print('      %-6s x = %8.3f m   %s' % (
                e.nombre, e.coord, '' if e.apoyado_en_linea else '<- sin linea de eje'))
    print('  ejes horizontales (y constante): %d' % auditoria['ejes_Y'])
    for e in ejes:
        if e.direccion == 'Y':
            print('      %-6s y = %8.3f m   %s' % (
                e.nombre, e.coord, '' if e.apoyado_en_linea else '<- sin linea de eje'))
    if auditoria['burbujas_ambiguas']:
        print('  AMBIGUAS: %s' % [a['nombre'] for a in auditoria['burbujas_ambiguas']])
    if auditoria['burbujas_sin_clasificar']:
        print('  SIN CLASIFICAR: %s' % [a['nombre'] for a in auditoria['burbujas_sin_clasificar']])
