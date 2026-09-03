# -*- coding: utf-8 -*-
r"""
================================================================
 niveles.py  -  LAS COTAS DE PISO, DESDE LAS ELEVACIONES
================================================================
 La planta da X e Y. La tercera coordenada -- la altura de cada
 piso -- sale de las laminas de ELEVACION.

 En una elevacion, la altura del edificio esta dibujada en el eje
 Y del dibujo, y cada piso lleva su cota escrita: "-4.01", "+3.91".

 ----------------------------------------------------------------
 LA IDEA: EL DESFASE CONSTANTE ES LA VERIFICACION
 ----------------------------------------------------------------
 El dibujo no empieza en la cota cero: esta corrido. Pero el
 corrimiento es el MISMO para todas las cotas de la lamina:

     desfase = y_dibujo - nivel_escrito

 Medido en la lamina 300 de este proyecto:

     y = 14.446  texto "-7.97"   ->  22.416
     y = 18.406  texto "-4.01"   ->  22.416
     y = 22.366  texto "-0.05"   ->  22.416
     y = 26.326  texto "+3.91"   ->  22.416
     y = 30.286  texto "+7.87"   ->  22.416
     y = 34.246  texto "+11.83"  ->  22.416

 Seis cotas independientes que dan el mismo numero. Eso no es una
 suposicion: es una comprobacion. Y de yapa entrega la regla para
 convertir CUALQUIER geometria de la elevacion a cota real:

     Z = y_dibujo - desfase

 Los textos que NO dan ese desfase no son cotas de nivel (son
 diametros de fierro, espesores, numeros sueltos) y se descartan
 solos, sin tener que enumerar capas basura a mano.

 Si los desfases NO coinciden, la lamina no se lee: se reporta. Un
 nivel mal leido corre un piso entero.
================================================================
"""
from __future__ import annotations

import collections
import re

Nivel = collections.namedtuple('Nivel', 'z y_dibujo textos')

# Una cota de nivel: signo explicito y dos o tres decimales.
# El signo es lo que la separa de "70x70" o de un diametro "0.100":
# el calculista SIEMPRE escribe +3.91 o -4.01, nunca "3.91".
_COTA = re.compile(r'^[+-]\s*\d{1,3}[.,]\d{2,3}$')

TOL_DESFASE = 0.05      # m: cuanto puede variar el desfase entre cotas
TOL_AGRUPAR = 0.05      # m: dos cotas a la misma altura


def _valor(texto):
    t = texto.strip().replace(' ', '').replace(',', '.')
    try:
        return float(t)
    except ValueError:
        return None


def cotas_candidatas(hoja, capas_excluidas=('DEFPOINTS',)):
    """Textos de la lamina que tienen forma de cota de nivel."""
    from perfil import limpiar_capa
    salida = []
    for t in hoja.textos:
        if limpiar_capa(t.capa).upper() in {c.upper() for c in capas_excluidas}:
            continue
        crudo = t.texto.strip().replace('N.P.T.', '').replace('N.T.N.', '').strip()
        if _COTA.match(crudo):
            v = _valor(crudo)
            if v is not None:
                salida.append((v, t.y, crudo))
    return salida


def extraer(hoja, tol_desfase=TOL_DESFASE):
    """
    Devuelve (niveles, desfase, auditoria).

    'desfase' convierte el dibujo a cota real:  Z = y_dibujo - desfase
    """
    candidatas = cotas_candidatas(hoja)
    if not candidatas:
        return [], None, {'cotas_candidatas': 0,
                          'motivo': 'la lamina no tiene textos con forma de cota'}

    # --- el desfase mas votado -----------------------------
    # Se agrupan los desfases: el grupo mas grande es el verdadero.
    # Las cotas falsas dan desfases dispersos y quedan solas.
    desfases = sorted((y - v, v, y, s) for (v, y, s) in candidatas)
    grupos = []
    for d, v, y, s in desfases:
        if grupos and abs(d - grupos[-1][0][0]) <= tol_desfase:
            grupos[-1].append((d, v, y, s))
        else:
            grupos.append([(d, v, y, s)])
    mejor = max(grupos, key=len)
    desfase = sum(g[0] for g in mejor) / len(mejor)
    dispersion = max(abs(g[0] - desfase) for g in mejor)

    # --- agrupar las cotas que estan a la misma altura ------
    por_z = collections.defaultdict(list)
    for _, v, y, s in mejor:
        por_z[round(v, 3)].append(s)

    niveles = [Nivel(z=z, y_dibujo=z + desfase, textos=sorted(set(txt)))
               for z, txt in sorted(por_z.items())]

    descartadas = [{'texto': s, 'y': round(y, 3), 'desfase': round(d, 3)}
                   for g in grupos if g is not mejor for (d, v, y, s) in g]

    auditoria = {
        'cotas_candidatas': len(candidatas),
        'cotas_usadas': len(mejor),
        'cotas_descartadas': descartadas,
        'desfase': round(desfase, 4),
        'dispersion_del_desfase': round(dispersion, 4),
        'coherente': dispersion <= tol_desfase,
        'niveles': [round(n.z, 3) for n in niveles],
        'alturas_entre_pisos': [round(b.z - a.z, 3)
                                for a, b in zip(niveles, niveles[1:])],
    }
    return niveles, desfase, auditoria


def combinar(resultados):
    """
    Junta los niveles leidos de VARIAS elevaciones.

    Un nivel que aparece en varias laminas es mucho mas confiable
    que uno que aparece en una sola: el numero de apariciones se
    conserva para poder decidir cuales entran al modelo y cuales
    son cotas locales (un antepecho, una losa de sala de maquinas).
    """
    votos = collections.Counter()
    origen = collections.defaultdict(list)
    for nombre, (niveles, _desfase, _aud) in resultados.items():
        for n in niveles:
            votos[round(n.z, 3)] += 1
            origen[round(n.z, 3)].append(nombre)
    return [{'z': z, 'laminas': votos[z], 'visto_en': sorted(origen[z])}
            for z in sorted(votos)]
