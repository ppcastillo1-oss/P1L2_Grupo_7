# -*- coding: utf-8 -*-
r"""
================================================================
 perfil.py  -  EL PERFIL DE UN JUEGO DE PLANOS
================================================================
 Un perfil es un JSON que traduce "como dibuja ESTA oficina" al
 vocabulario del modelo estructural:

     "los muros estan en la capa RLE-MURO"
     "el dibujo esta en centimetros"
     "las burbujas de eje son circulos con un texto adentro"

 Toda la parte del ingestor que depende del proyecto vive en el
 perfil. El codigo NO conoce ningun nombre de capa: si manana hay
 que leer los planos de otra oficina, se escribe otro perfil y no
 se toca una linea de Python.

 Ese es el punto: que esto sirva para el proximo proyecto, no solo
 para este.

 ----------------------------------------------------------------
 ESTRUCTURA DE UN PERFIL
 ----------------------------------------------------------------
 {
   "nombre":   "LT2 / 2024_22",
   "unidades": "cm",                  <- factor a metros
   "roles": {
     "ejes":    {"capas": ["RLE-EJES"]},
     "muros":   {"capas": ["RLE-MURO"], "espesor_min": 0.10, ...},
     ...
   },
   "hojas": { "planta_tipo": "2024_22-101", ... }
 }

 Los nombres de capa admiten comodines de shell:
     "RLE-*"      todas las que empiecen con RLE-
     "*MURO*"     todas las que contengan MURO

 ----------------------------------------------------------------
 CAPAS DENTRO DE XREFS
 ----------------------------------------------------------------
 Cuando un plano referencia otro dibujo (XREF), AutoCAD renombra
 sus capas anteponiendo el nombre de la referencia:

     RLE-MURO   ->   EJE 1$0$RLE-MURO

 El perfil se escribe con el nombre LIMPIO y el emparejador quita
 ese prefijo antes de comparar. Si no, ninguna capa de una
 elevacion calzaria nunca y el plano se leeria vacio SIN ERROR.
================================================================
"""
from __future__ import annotations

import fnmatch
import json
import os
import re

# Factor de conversion a METROS. El modelo estructural trabaja en
# metros; la conversion se hace AL LEER, nunca despues.
A_METROS = {'mm': 0.001, 'cm': 0.01, 'm': 1.0,
            'pulgadas': 0.0254, 'pies': 0.3048}

# Prefijo que AutoCAD le pone a las capas que vienen de un XREF:
#   <nombre de la referencia> $ <nivel> $ <capa original>
_PREFIJO_XREF = re.compile(r'^.*\$\d+\$')


def limpiar_capa(nombre):
    """Quita el prefijo de XREF de un nombre de capa.

    >>> limpiar_capa('EJE 1$0$RLE-MURO')
    'RLE-MURO'
    >>> limpiar_capa('RLE-MURO')
    'RLE-MURO'
    """
    return _PREFIJO_XREF.sub('', nombre or '')


class Perfil(object):
    """Perfil de un juego de planos, cargado desde JSON."""

    def __init__(self, datos, ruta=None):
        self.datos = datos
        self.ruta = ruta
        self.nombre = datos.get('nombre', os.path.basename(ruta or 'sin nombre'))

        unidades = datos.get('unidades', 'cm')
        if unidades not in A_METROS:
            raise ValueError('Unidad desconocida en el perfil: %r (validas: %s)'
                             % (unidades, ', '.join(sorted(A_METROS))))
        self.unidades = unidades
        self.factor = A_METROS[unidades]

        self.roles = datos.get('roles', {})
        self.hojas = datos.get('hojas', {})

    # --------------------------------------------------------
    @classmethod
    def cargar(cls, ruta):
        with open(ruta, encoding='utf-8') as f:
            return cls(json.load(f), ruta)

    # --------------------------------------------------------
    def capas_de(self, rol):
        """Patrones de capa declarados para un rol. [] si no esta."""
        return list(self.roles.get(rol, {}).get('capas', []))

    def opcion(self, rol, clave, por_defecto=None):
        """Un parametro del rol (espesor_min, largo_min, ...)."""
        return self.roles.get(rol, {}).get(clave, por_defecto)

    def roles_declarados(self):
        return sorted(self.roles)

    # --------------------------------------------------------
    def calza(self, capa, rol):
        """True si la capa (aun con prefijo de XREF) pertenece al rol."""
        patrones = self.capas_de(rol)
        if not patrones:
            return False
        limpia = limpiar_capa(capa).upper()
        return any(fnmatch.fnmatch(limpia, p.upper()) for p in patrones)

    def rol_de(self, capa):
        """Rol al que pertenece una capa, o None. El primero que calce."""
        for rol in self.roles:
            if self.calza(capa, rol):
                return rol
        return None

    # --------------------------------------------------------
    def hoja(self, clave):
        """Nombre de archivo (sin extension) declarado para un papel.

        Ej.: perfil.hoja('planta_tipo') -> '2024_22-101'
        """
        return self.hojas.get(clave)

    def __repr__(self):
        return '<Perfil %r  unidades=%s  roles=%s>' % (
            self.nombre, self.unidades, ', '.join(self.roles_declarados()))


# ============================================================
def cargar(nombre_o_ruta, carpeta_perfiles=None):
    """
    Carga un perfil por ruta directa o por nombre corto.

        cargar('perfiles/lt2_2024_22.json')
        cargar('lt2_2024_22')            # busca en perfiles/
    """
    if os.path.isfile(nombre_o_ruta):
        return Perfil.cargar(nombre_o_ruta)

    if carpeta_perfiles is None:
        aqui = os.path.dirname(os.path.abspath(__file__))
        carpeta_perfiles = os.path.join(aqui, '..', '..', 'perfiles')

    candidato = os.path.join(carpeta_perfiles, nombre_o_ruta)
    if not candidato.endswith('.json'):
        candidato += '.json'
    if os.path.isfile(candidato):
        return Perfil.cargar(candidato)

    disponibles = sorted(f[:-5] for f in os.listdir(carpeta_perfiles)
                         if f.endswith('.json')) if os.path.isdir(carpeta_perfiles) else []
    raise FileNotFoundError('No encontre el perfil %r. Disponibles: %s'
                            % (nombre_o_ruta, ', '.join(disponibles) or '(ninguno)'))
