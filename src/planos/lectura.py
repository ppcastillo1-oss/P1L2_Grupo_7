# -*- coding: utf-8 -*-
r"""
================================================================
 lectura.py  -  DEL DXF A PRIMITIVAS EN METROS
================================================================
 Convierte una hoja DXF en cuatro listas planas y neutras:

     segmentos   (x1, y1, x2, y2)      <- lineas y polilineas
     textos      (texto, x, y)
     circulos    (x, y, radio)
     arcos       (x, y, radio, ang1, ang2)

 Todo en METROS y con las coordenadas ya en el sistema del dibujo.
 De aqui para arriba nadie vuelve a hablar de DXF.

 ----------------------------------------------------------------
 POR QUE HAY QUE "APLANAR" LOS BLOQUES
 ----------------------------------------------------------------
 Recorrer el modelspace NO alcanza. En estos planos:

   - la lamina 300 (elevaciones) tiene 193 entidades en modelspace
     y 17.657 dentro de definiciones de bloque;
   - toda la geometria de las elevaciones viene de XREFs
     (P:\2024\2024-22\ING\XREF ELEV\EJE 1.dwg), insertados como un
     bloque con su propia rotacion, escala y desplazamiento.

 Si uno solo mira el modelspace, la elevacion se lee VACIA y el
 codigo no da ningun error: simplemente devuelve cero muros. Es el
 mismo tipo de falla silenciosa que el JsonUtility de Unity.

 Por eso cada INSERT se expande con virtual_entities(), que aplica
 la transformacion del bloque, y se baja recursivamente por los
 bloques anidados.

 ----------------------------------------------------------------
 UNIDADES
 ----------------------------------------------------------------
 El factor sale del PERFIL, no de $INSUNITS: estos planos declaran
 "sin especificar" y estan en centimetros. La conversion se hace
 aca, al leer, y nunca mas.
================================================================
"""
from __future__ import annotations

import collections
import logging
import math
import os

import ezdxf

# ezdxf avisa "copy process ignored ACDB_BLOCKREPRESENTATION_DATA(...)"
# una vez por cada entidad al expandir bloques dinamicos: en la lamina
# 300 son mas de 200 lineas de ruido que tapan cualquier mensaje util.
# Es informativo -- se refiere a datos que solo le sirven a AutoCAD para
# re-editar el bloque, no a su geometria, que es lo unico que leemos.
logging.getLogger('ezdxf').setLevel(logging.ERROR)

try:                                    # como paquete (import src.planos)
    from .perfil import limpiar_capa
except ImportError:                     # como script suelto
    from perfil import limpiar_capa

# ---- primitivas ------------------------------------------------
Segmento = collections.namedtuple('Segmento', 'x1 y1 x2 y2 capa')
Texto = collections.namedtuple('Texto', 'texto x y capa altura rotacion')
Circulo = collections.namedtuple('Circulo', 'x y radio capa')
Arco = collections.namedtuple('Arco', 'x y radio ang1 ang2 capa')

# Profundidad maxima de anidamiento de bloques. Los planos reales
# llegan a 3-4 niveles (lamina -> xref -> bloque -> subbloque);
# el tope evita colgarse si un dibujo tiene una referencia circular.
MAX_PROFUNDIDAD = 8


def largo(s):
    return math.hypot(s.x2 - s.x1, s.y2 - s.y1)


def angulo(s):
    """Angulo del segmento en grados, normalizado a [0, 180)."""
    a = math.degrees(math.atan2(s.y2 - s.y1, s.x2 - s.x1)) % 180.0
    return a


class Hoja(object):
    """Las primitivas de una lamina, ya en metros."""

    def __init__(self, archivo, factor):
        self.archivo = archivo
        self.factor = factor
        self.segmentos = []
        self.textos = []
        self.circulos = []
        self.arcos = []
        self.ignoradas = collections.Counter()

    # --- consultas por capa ---------------------------------
    def _filtrar(self, items, perfil, rol):
        return [i for i in items if perfil.calza(i.capa, rol)]

    def segmentos_de(self, perfil, rol):
        return self._filtrar(self.segmentos, perfil, rol)

    def textos_de(self, perfil, rol):
        return self._filtrar(self.textos, perfil, rol)

    def circulos_de(self, perfil, rol):
        return self._filtrar(self.circulos, perfil, rol)

    def capas(self):
        """Capas presentes (nombre limpio) con su conteo de primitivas."""
        c = collections.Counter()
        for grupo in (self.segmentos, self.textos, self.circulos, self.arcos):
            for i in grupo:
                c[limpiar_capa(i.capa)] += 1
        return c

    def extension(self):
        """(xmin, ymin, xmax, ymax) de los segmentos, en metros."""
        if not self.segmentos:
            return None
        xs = [v for s in self.segmentos for v in (s.x1, s.x2)]
        ys = [v for s in self.segmentos for v in (s.y1, s.y2)]
        return (min(xs), min(ys), max(xs), max(ys))

    def __repr__(self):
        return '<Hoja %s: %d segmentos, %d textos, %d circulos>' % (
            os.path.basename(self.archivo), len(self.segmentos),
            len(self.textos), len(self.circulos))


# ============================================================
def _texto_de(e):
    """Contenido legible de un TEXT / MTEXT / ATTRIB."""
    try:
        if e.dxftype() == 'MTEXT':
            return e.plain_text()
        return e.dxf.text
    except Exception:
        return ''


def _agregar(hoja, e, f):
    """Traduce UNA entidad DXF a primitivas. f = factor a metros."""
    tipo = e.dxftype()
    capa = e.dxf.layer

    # float() explicito: ezdxf devuelve a veces numpy.float64, y un
    # numpy.float64 revienta json.dump sin decir por que.
    if tipo == 'LINE':
        a, b = e.dxf.start, e.dxf.end
        hoja.segmentos.append(Segmento(float(a.x) * f, float(a.y) * f,
                                       float(b.x) * f, float(b.y) * f, capa))

    elif tipo == 'LWPOLYLINE':
        pts = [(float(p[0]) * f, float(p[1]) * f) for p in e.get_points('xy')]
        if e.closed and len(pts) > 2:
            pts.append(pts[0])
        for p, q in zip(pts, pts[1:]):
            hoja.segmentos.append(Segmento(p[0], p[1], q[0], q[1], capa))

    elif tipo == 'POLYLINE':
        try:
            pts = [(float(v.dxf.location.x) * f, float(v.dxf.location.y) * f)
                   for v in e.vertices]
        except Exception:
            hoja.ignoradas[tipo] += 1
            return
        if e.is_closed and len(pts) > 2:
            pts.append(pts[0])
        for p, q in zip(pts, pts[1:]):
            hoja.segmentos.append(Segmento(p[0], p[1], q[0], q[1], capa))

    elif tipo in ('TEXT', 'MTEXT', 'ATTRIB'):
        t = (_texto_de(e) or '').strip()
        if not t:
            return
        p = e.dxf.insert if e.dxf.hasattr('insert') else e.dxf.get('align_point', (0, 0, 0))
        try:
            altura = float(e.dxf.get('height', e.dxf.get('char_height', 0.0))) * f
        except Exception:
            altura = 0.0
        try:
            rot = float(e.dxf.get('rotation', 0.0))
        except Exception:
            rot = 0.0
        hoja.textos.append(Texto(t, float(p[0]) * f, float(p[1]) * f, capa, altura, rot))

    elif tipo == 'CIRCLE':
        c = e.dxf.center
        hoja.circulos.append(Circulo(float(c.x) * f, float(c.y) * f,
                                     float(e.dxf.radius) * f, capa))

    elif tipo == 'ARC':
        c = e.dxf.center
        hoja.arcos.append(Arco(float(c.x) * f, float(c.y) * f, float(e.dxf.radius) * f,
                               float(e.dxf.start_angle), float(e.dxf.end_angle), capa))

    else:
        # HATCH, DIMENSION, SOLID, LEADER, ... no aportan geometria
        # estructural: se cuentan para poder declararlo, no se leen.
        hoja.ignoradas[tipo] += 1


def _recorrer(entidades, hoja, f, profundidad):
    for e in entidades:
        if e.dxftype() == 'INSERT':
            if profundidad >= MAX_PROFUNDIDAD:
                hoja.ignoradas['INSERT (demasiado anidado)'] += 1
                continue
            # virtual_entities() aplica posicion, escala y rotacion
            # del bloque: las coordenadas salen ya en el sistema de
            # la lamina. Hacerlo a mano es la forma clasica de
            # dibujar todo corrido y no darse cuenta.
            try:
                hijas = list(e.virtual_entities())
            except Exception:
                hoja.ignoradas['INSERT (no se pudo expandir)'] += 1
                continue
            _recorrer(hijas, hoja, f, profundidad + 1)
            # los atributos del bloque (rotulo, etiquetas de eje)
            for att in getattr(e, 'attribs', []):
                _agregar(hoja, att, f)
        else:
            _agregar(hoja, e, f)


# ============================================================
def leer(ruta, perfil):
    """Lee una lamina DXF completa (modelspace + bloques) en metros."""
    doc = ezdxf.readfile(ruta)
    hoja = Hoja(ruta, perfil.factor)
    _recorrer(doc.modelspace(), hoja, perfil.factor, 0)
    return hoja


def leer_varias(carpeta, nombres, perfil):
    """Lee varias laminas por nombre base ('2024_22-101')."""
    hojas = {}
    for nombre in nombres:
        ruta = os.path.join(carpeta, nombre if nombre.endswith('.dxf') else nombre + '.dxf')
        if not os.path.isfile(ruta):
            raise FileNotFoundError('Falta la lamina %s' % ruta)
        hojas[nombre] = leer(ruta, perfil)
    return hojas


def xrefs_de(ruta):
    """Referencias externas de una lamina: (nombre, ruta declarada)."""
    doc = ezdxf.readfile(ruta)
    fuera = []
    for b in doc.blocks:
        camino = b.block.dxf.get('xref_path', '')
        if camino:
            fuera.append((b.name, camino, sum(1 for _ in b)))
    return fuera
