# -*- coding: utf-8 -*-
r"""
================================================================
 losas.py  -  ESPESOR DE LOSA, DESDE LOS ROTULOS DEL PLANO
================================================================
 El espesor de la losa NO se puede medir en una planta: la losa se
 ve de canto solo en los cortes. Pero esta rotulado, y el rotulo
 no es texto suelto: es un BLOQUE con atributos.

 En LT2, cada pano de losa lleva un bloque 'losa-ne' con:

     N%%DL = "0100"   el numero del pano
     ESP   = "15"     el espesor, en cm

 Leer atributos de bloque en vez de texto suelto es mas confiable:
 el atributo tiene NOMBRE, asi que no hay que adivinar cual de los
 numeros del plano es el espesor.

 ----------------------------------------------------------------
 POR QUE ESTE MODULO NO USA lectura.py
 ----------------------------------------------------------------
 lectura.py aplana todo a primitivas y se queda con el TEXTO de
 cada atributo, pero pierde su TAG -- que es justamente lo que
 identifica al espesor. Aca se va al DXF directo a buscar el
 bloque por nombre.

 El espesor se lee de TODOS los panos y se reporta la distribucion.
 Si el plano tiene panos de espesores distintos, hay que saberlo:
 un espesor unico promediado cambia el peso de la losa y nadie se
 entera.
================================================================
"""
from __future__ import annotations

import collections

import ezdxf

Pano = collections.namedtuple('Pano', 'nombre espesor x y')


def extraer(ruta_dxf, bloque, tag_espesor, tag_nombre=None,
            factor_espesor=0.01, factor_posicion=0.01):
    """
    Lee los rotulos de losa de una lamina.

    'factor_espesor'  convierte el valor del atributo a metros
                      (los rotulos vienen en cm: "15" -> 0.15).
    'factor_posicion' convierte las coordenadas del dibujo a metros.

    Devuelve (panos, auditoria).
    """
    doc = ezdxf.readfile(ruta_dxf)
    panos = []
    sin_espesor = 0

    for ins in doc.modelspace().query('INSERT'):
        if ins.dxf.name != bloque:
            continue
        atributos = {}
        for a in (ins.attribs or []):
            atributos[str(a.dxf.tag).strip()] = str(a.dxf.text).strip()

        crudo = atributos.get(tag_espesor, '').replace(',', '.')
        try:
            espesor = float(crudo) * factor_espesor
        except ValueError:
            sin_espesor += 1
            continue

        panos.append(Pano(nombre=atributos.get(tag_nombre or '', ''),
                          espesor=espesor,
                          x=float(ins.dxf.insert.x) * factor_posicion,
                          y=float(ins.dxf.insert.y) * factor_posicion))

    espesores = collections.Counter(round(p.espesor, 3) for p in panos)
    auditoria = {
        'bloque': bloque,
        'tag_espesor': tag_espesor,
        'panos': len(panos),
        'rotulos_sin_espesor_legible': sin_espesor,
        'espesores': sorted(espesores.items()),
        'espesor_unico': (len(espesores) == 1),
        'espesor_dominante': (espesores.most_common(1)[0][0] if espesores else None),
    }
    return panos, auditoria


def a_json(panos):
    return [{'nombre': p.nombre, 'espesor': round(p.espesor, 3),
             'x': round(p.x, 3), 'y': round(p.y, 3)} for p in panos]
