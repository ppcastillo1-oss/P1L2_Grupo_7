# -*- coding: utf-8 -*-
r"""
================================================================
 vigas.py  -  VIGAS: EL ANCHO SE MIDE, EL ALTO SE LEE
================================================================
 En planta, una viga se dibuja igual que un muro: sus dos caras.
 Del dibujo sale su EJE y su ANCHO -- pero no su ALTO, porque el
 alto no se ve en planta.

 El alto esta escrito: "V. 60/80" quiere decir 60 cm de ancho por
 80 cm de alto. Asi que:

     ancho  <- se MIDE del dibujo (distancia entre caras)
     alto   <- se LEE de la etiqueta

 y el ancho medido se CONTRASTA contra el primer numero de la
 etiqueta. Cuando no calzan, uno de los dos esta mal y hay que
 mirar el plano; el extractor lo reporta y no elige por su cuenta.

 Esa doble via es lo que hace confiable el resultado: si el alto
 saliera de la misma fuente que el ancho, no habria con que
 comprobarlo.

 ----------------------------------------------------------------
 EL EMPAREJADO ES EL MISMO QUE EL DE LOS MUROS
 ----------------------------------------------------------------
 Se reusa muros.extraer() con otro rango de espesores. Una viga y
 un muro se dibujan igual; lo que cambia es el rango plausible
 (una viga puede tener 20 cm de ancho, un muro tambien, pero una
 viga puede llegar a 60-80 cm y un muro de 1.20 m no existe).

 Medido en la planta tipo de LT2: 45 vigas, 98.2 % de cobertura,
 anchos 0.20 / 0.30 / 0.40 / 0.60 -- que son exactamente los que
 dicen las etiquetas V. 20/..., V. 30/80, V. 40/80 y V. 60/80.
================================================================
"""
from __future__ import annotations

import collections
import math

try:
    from . import muros as mod_muros
    from . import pilares as mod_pilares
except ImportError:
    import muros as mod_muros
    import pilares as mod_pilares

Viga = collections.namedtuple(
    'Viga', 'x1 y1 x2 y2 largo ancho alto etiqueta calza_ancho')

DIST_ETIQUETA_MAX = 3.0     # m: cuan lejos puede estar el rotulo de su viga
TOL_ANCHO = 0.03            # m: cuanto puede diferir lo medido de lo rotulado
ALTO_POR_DEFECTO = None     # sin etiqueta no se inventa un alto


GAP_COLINEAL = 1.5      # m: hueco maximo entre dos trozos de la MISMA viga
                        # (valor por defecto; el perfil lo puede subir --
                        # ver 'gap_colineal' en la opcion 'vigas')
TOL_OFFSET = 0.05       # m: cuanto puede diferir la posicion de sus ejes


def unir_colineales(vigas, gap_max=GAP_COLINEAL, tol_ang=2.0,
                    tol_offset=TOL_OFFSET, tol_ancho=0.03):
    """
    Junta los trozos de una misma viga.

    Una viga larga no se dibuja de una sola pieza: se corta donde la
    cruza otra viga, donde hay un vano de losa, o simplemente donde
    el dibujante levanto el lapiz. Al emparejar caras, cada trozo
    sale como una viga distinta.

    Eso rompe el modelo de una forma que no avisa. En la lamina 102
    la viga de fachada de x = 11.30 salio en cuatro trozos con huecos
    de 0.75 a 1.10 m, y los trozos del medio terminaban EN EL AIRE:
    sus extremos no llegaban a ningun muro. Eran voladizos. Bajaban
    204 mm donde la mediana del piso era 4 mm.

    En la lamina 101 la misma viga tambien sale en trozos, pero ahi
    los huecos caen justo donde la cruza una viga transversal, asi
    que se conectaban igual y no se notaba nada. El mismo defecto,
    visible en una lamina e invisible en la otra.

    Dos trozos son la misma viga si: son paralelos, tienen el mismo
    ancho, sus ejes estan a la misma altura, y el hueco entre ellos
    es chico. Un hueco grande SI es dos vigas distintas.
    """
    if not vigas:
        return [], {'entraron': 0, 'salieron': 0, 'uniones': 0}

    # Se agrupa comparando con TOLERANCIA, no redondeando a casillas.
    #
    # Redondear parece equivalente y no lo es. Con casillas de 2 grados,
    # un trozo dibujado con angulo -0.00006 grados cae en 179.99994 al
    # aplicar el modulo 180, y termina en una casilla distinta que su
    # continuacion de +0.00006. Asi, diez trozos de la MISMA viga del
    # techo quedaron en dos grupos alternados y no se unio ninguno.
    # El sintoma no fue un error: fue una viga de techo cortada en
    # pedazos que bajaba 145 mm.
    descritos = []
    for v in vigas:
        L = math.hypot(v.x2 - v.x1, v.y2 - v.y1)
        ux, uy = (v.x2 - v.x1) / L, (v.y2 - v.y1) / L
        if (ux < 0) or (abs(ux) < 1e-9 and uy < 0):     # sentido canonico
            ux, uy = -ux, -uy
        t1 = v.x1 * ux + v.y1 * uy
        t2 = v.x2 * ux + v.y2 * uy
        if t1 > t2:
            t1, t2 = t2, t1
        d = -v.x1 * uy + v.y1 * ux
        descritos.append((t1, t2, ux, uy, d, v))

    grupos = []
    for item in descritos:
        _t1, _t2, ux, uy, d, v = item
        for g in grupos:
            _a, _b, gux, guy, gd, gv = g[0]
            # coseno del angulo entre las dos direcciones canonicas
            cos = abs(ux * gux + uy * guy)
            if (cos > math.cos(math.radians(tol_ang))
                    and abs(d - gd) <= tol_offset
                    and abs(v.ancho - gv.ancho) <= tol_ancho):
                g.append(item)
                break
        else:
            grupos.append([item])

    salida, uniones = [], 0
    for trozos in grupos:
        trozos.sort()
        actual = list(trozos[0])
        for t in trozos[1:]:
            if t[0] - actual[1] <= gap_max:
                actual[1] = max(actual[1], t[1])
                # El alto lo pone el trozo que SI traia etiqueta.
                if actual[5].alto is None and t[5].alto is not None:
                    actual[5] = t[5]
                uniones += 1
            else:
                salida.append(actual)
                actual = list(t)
        salida.append(actual)

    unidas = []
    for t1, t2, ux, uy, d, v in salida:
        nx, ny = -uy, ux
        x1, y1 = ux * t1 + nx * d, uy * t1 + ny * d
        x2, y2 = ux * t2 + nx * d, uy * t2 + ny * d
        unidas.append(v._replace(x1=x1, y1=y1, x2=x2, y2=y2,
                                 largo=math.hypot(x2 - x1, y2 - y1)))

    return unidas, {'entraron': len(vigas), 'salieron': len(unidas),
                    'uniones': uniones}


def _distancia_a_segmento(px, py, x1, y1, x2, y2):
    """Distancia de un punto al segmento (no a la recta)."""
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0.0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def extraer(segmentos, etiquetas=(), ancho_min=0.15, ancho_max=1.20,
            largo_min=1.0, gap_colineal=GAP_COLINEAL):
    """
    Devuelve (vigas, auditoria).

    'segmentos'    : los de la capa de vigas, en metros y alineados.
    'etiquetas'    : textos de seccion ("V. 60/80"). De ahi sale el alto.
    'gap_colineal' : hueco maximo, en metros, para dar dos trozos por
                     la misma viga. Depende de COMO dibuja el
                     calculista, asi que se declara en el perfil.
    """
    ejes, aud = mod_muros.extraer(segmentos, espesor_min=ancho_min,
                                  espesor_max=ancho_max, largo_min=largo_min)

    # Solo sirven las etiquetas que se pueden leer como seccion:
    # el rotulo del plano viene partido ("V." por un lado, "60/80"
    # por otro) y tomar el texto mas cercano a secas devuelve "V.".
    utiles = [(t, mod_pilares.seccion_de_texto(t.texto)) for t in etiquetas]
    utiles = [(t, s) for (t, s) in utiles if s]

    vigas = []
    rechazadas = []
    for e in ejes:
        etiqueta, alto, calza = None, ALTO_POR_DEFECTO, None

        # El ANCHO MEDIDO es la llave del emparejado, no la distancia.
        #
        # Elegir "la etiqueta mas cercana" a secas falla feo: en la
        # lamina 102 el rotulo "45/30" -- que no es una viga -- aparece
        # 42 veces y le ganaba por cercania a 35 de las 56 vigas,
        # dandoles 30 cm de alto. Se veia como un modelo normal.
        #
        # En "60/80" el primer numero es el ancho. Si no calza con lo
        # que mide el dibujo, esa etiqueta NO es de esta viga.
        cerca = [(_distancia_a_segmento(t.x, t.y, e.x1, e.y1, e.x2, e.y2), t, sec)
                 for (t, sec) in utiles]
        cerca = [c for c in cerca if c[0] <= DIST_ETIQUETA_MAX]
        calzan = [c for c in cerca if abs(c[2][0] - e.espesor) <= TOL_ANCHO]

        if calzan:
            _d, t, sec = min(calzan, key=lambda c: c[0])
            etiqueta, alto, calza = t.texto.strip(), sec[1], True
        elif cerca:
            # Habia rotulos cerca pero ninguno declara este ancho.
            # Antes de inventar un alto, se reporta.
            _d, t, sec = min(cerca, key=lambda c: c[0])
            rechazadas.append({'centro': [round((e.x1 + e.x2) / 2, 3),
                                          round((e.y1 + e.y2) / 2, 3)],
                               'ancho_medido': round(e.espesor, 3),
                               'etiqueta_mas_cercana': t.texto.strip()})
            calza = False

        vigas.append(Viga(x1=e.x1, y1=e.y1, x2=e.x2, y2=e.y2,
                          largo=e.largo, ancho=e.espesor, alto=alto,
                          etiqueta=etiqueta, calza_ancho=calza))

    # Unir los trozos de una misma viga (ver unir_colineales).
    vigas, aud_union = unir_colineales(vigas, gap_max=gap_colineal)

    discrepan = rechazadas

    aud_v = dict(aud)
    aud_v.update({
        'vigas': len(vigas),
        'con_etiqueta': sum(1 for v in vigas if v.etiqueta),
        'sin_alto': sum(1 for v in vigas if v.alto is None),
        'ancho_no_calza_con_la_etiqueta': discrepan,
        'secciones': sorted(collections.Counter(
            ('%.2f/%.2f' % (v.ancho, v.alto)) if v.alto else '%.2f/?' % v.ancho
            for v in vigas).items()),
        'largo_total_vigas': round(sum(v.largo for v in vigas), 2),
        'union_de_trozos': aud_union,
    })
    return vigas, aud_v


def a_json(vigas):
    return [{'x1': round(v.x1, 4), 'y1': round(v.y1, 4),
             'x2': round(v.x2, 4), 'y2': round(v.y2, 4),
             'largo': round(v.largo, 4),
             'ancho': round(v.ancho, 3),
             'alto': (round(v.alto, 3) if v.alto else None),
             'etiqueta': v.etiqueta}
            for v in vigas]
