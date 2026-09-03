# -*- coding: utf-8 -*-
r"""
================================================================
 alineacion.py  -  PONER TODAS LAS LAMINAS EN EL MISMO ORIGEN
================================================================
 Cada lamina de un juego de planos tiene su PROPIO origen de
 dibujo. No es un error del CAD: cada plano se dibuja donde le
 acomoda al dibujante dentro de su formato.

 Medido en este juego (LT2 / 2024_22):

     eje    lamina 100      lamina 101     diferencia
     A'        5.96 m        10.96 m         5.00 m
     A         9.74 m        14.74 m         5.00 m
     B        17.24 m        22.24 m         5.00 m
     ...

 y la lamina 102 esta corrida 3.20 m en Y respecto de la 101.

 Si uno junta los muros de la 100 con los pilares de la 101 sin
 registrar las laminas, el edificio queda con la fundacion corrida
 5 metros respecto de los pilares. **Y no hay ningun error**: el
 modelo se arma, corre, y da numeros. Solo esta mal.

 ----------------------------------------------------------------
 COMO SE REGISTRA
 ----------------------------------------------------------------
 Los ejes tienen NOMBRE. El eje "B" de la lamina 100 y el eje "B"
 de la 101 son el mismo eje del edificio. Entonces:

     dx = promedio( x_referencia[e] - x_lamina[e] )   sobre los
                                        ejes verticales comunes
     dy = idem con los ejes horizontales comunes

 Y ademas se mide el RESIDUO: si despues de correr la lamina los
 ejes no calzan dentro de una tolerancia, es que las laminas no
 estan a la misma escala o que un eje esta mal leido. Eso se
 reporta; no se tapa.

 ----------------------------------------------------------------
 PARA QUE SIRVE MAS ALLA DE ESTE PROYECTO
 ----------------------------------------------------------------
 Es el mismo mecanismo con el que se unen DOS EDIFICIOS modelados
 por separado: si comparten ejes con el mismo nombre, se registran
 por nombre; si no, hay que declarar a mano el desplazamiento
 entre sus origenes (funcion 'desplazar').
================================================================
"""
from __future__ import annotations

import collections

Registro = collections.namedtuple(
    'Registro', 'dx dy ejes_usados_x ejes_usados_y residuo_max ok')

# Tolerancia del residuo, en metros. Dos laminas del mismo juego
# deben calzar bastante mejor que esto; 2 cm ya es sospechoso.
TOL_RESIDUO = 0.02


def _por_nombre(ejes, direccion):
    return {e.nombre: e.coord for e in ejes if e.direccion == direccion}


def registrar(ejes_referencia, ejes_lamina, tol=TOL_RESIDUO):
    """
    Calcula el desplazamiento que lleva 'ejes_lamina' al sistema de
    'ejes_referencia', usando los ejes que comparten nombre.

    Devuelve un Registro. Si no hay ejes comunes en una direccion,
    el desplazamiento de esa direccion queda en 0.0 y se reporta.
    """
    resultados = {}
    for direccion, clave in (('X', 'dx'), ('Y', 'dy')):
        ref = _por_nombre(ejes_referencia, direccion)
        lam = _por_nombre(ejes_lamina, direccion)
        comunes = sorted(set(ref) & set(lam))
        if comunes:
            diffs = [ref[n] - lam[n] for n in comunes]
            desp = sum(diffs) / len(diffs)
            residuo = max(abs(d - desp) for d in diffs)
        else:
            desp, residuo = 0.0, float('inf')
        resultados[direccion] = (desp, comunes, residuo)

    dx, usados_x, res_x = resultados['X']
    dy, usados_y, res_y = resultados['Y']
    residuo_max = max(r for r in (res_x, res_y) if r != float('inf')) \
        if (res_x != float('inf') or res_y != float('inf')) else float('inf')

    return Registro(dx=dx, dy=dy,
                    ejes_usados_x=usados_x, ejes_usados_y=usados_y,
                    residuo_max=residuo_max,
                    ok=(residuo_max <= tol))


def desplazar_segmentos(segmentos, dx, dy):
    """Aplica el desplazamiento a una lista de Segmento."""
    return [s._replace(x1=s.x1 + dx, y1=s.y1 + dy,
                       x2=s.x2 + dx, y2=s.y2 + dy) for s in segmentos]


def desplazar_puntos(items, dx, dy):
    """Aplica el desplazamiento a namedtuples que tengan campos x, y."""
    return [i._replace(x=i.x + dx, y=i.y + dy) for i in items]


def desplazar_ejes(ejes, dx, dy):
    return [e._replace(coord=e.coord + (dx if e.direccion == 'X' else dy))
            for e in ejes]


def informe(nombre_lamina, reg):
    """Una linea legible por lamina, para la auditoria."""
    estado = 'OK' if reg.ok else ('SIN EJES COMUNES' if reg.residuo_max == float('inf')
                                  else 'RESIDUO ALTO')
    return ('%-16s dx=%+8.3f m  dy=%+8.3f m  '
            'ejes X: %-28s ejes Y: %-24s residuo=%s  %s' % (
                nombre_lamina, reg.dx, reg.dy,
                ','.join(reg.ejes_usados_x) or '(ninguno)',
                ','.join(reg.ejes_usados_y) or '(ninguno)',
                ('%.4f m' % reg.residuo_max) if reg.residuo_max != float('inf') else 'n/a',
                estado))
