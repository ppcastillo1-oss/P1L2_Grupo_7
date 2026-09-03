# -*- coding: utf-8 -*-
r"""
================================================================
 extraer.py  -  DEL JUEGO DE PLANOS A UN JSON DE GEOMETRIA
================================================================
 Orquesta todo el ingestor y deja dos archivos:

   data/geometria_<perfil>.json   la geometria, para el modelo
   reports/geometria_<perfil>.md  la auditoria, para leerla

 Uso:
   python src/planos/extraer.py <carpeta_dxf> --perfil lt2_2024_22

 ----------------------------------------------------------------
 LO QUE HACE, EN ORDEN
 ----------------------------------------------------------------
 1. Lee las plantas y saca los EJES con nombre de cada una.
 2. REGISTRA las plantas entre si por los ejes que comparten
    nombre. Sin este paso, cada lamina esta en su propio origen y
    la fundacion queda corrida 5 m respecto de los pilares --
    silenciosamente.
 3. Saca muros y pilares de cada planta, ya en el origen comun.
 4. Lee las elevaciones y saca los NIVELES, verificando que el
    desfase del dibujo sea el mismo para todas las cotas.
 5. Escribe la geometria y una auditoria de todo lo que quedo
    dudoso.

 ----------------------------------------------------------------
 QUE NO HACE
 ----------------------------------------------------------------
 No arma el modelo de OpenSees. Este JSON es la ENTRADA del
 modelo, no el modelo: separar las dos cosas es lo que permite
 revisar la lectura del plano por su cuenta, y lo que permite que
 el dia de manana entre otro juego de planos por el mismo tubo.
================================================================
"""
from __future__ import annotations

import argparse
import json
import math
import math
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)

import alineacion            # noqa: E402
import ejes as mod_ejes      # noqa: E402
import lectura               # noqa: E402
import muros as mod_muros    # noqa: E402
import niveles as mod_niveles  # noqa: E402
import perfil as mod_perfil  # noqa: E402
import pilares as mod_pilares  # noqa: E402
import losas as mod_losas    # noqa: E402
import vigas as mod_vigas    # noqa: E402

_RAIZ = os.path.dirname(os.path.dirname(_AQUI))


# ============================================================
def _lado(cfg, lado, ejes_ref, signo):
    """
    Un borde de la ventana. Se declara de una de dos formas:

        "ymax": {"eje": "1", "margen": 1.5}   un eje CON NOMBRE
        "xmax": {"coord": 42.75}              una coordenada

    El eje con nombre es lo preferible: sobrevive a que el plano se
    redibuje. La coordenada hace falta cuando el borde no cae sobre
    ningun eje -- el caso tipico es una JUNTA DE DILATACION, que corre
    entre dos ejes y no tiene uno propio.

    `signo` es -1 para los bordes minimos y +1 para los maximos, asi
    que el margen siempre ABRE la ventana.
    """
    d = cfg.get(lado)
    if d is None:
        return None
    if 'coord' in d:
        return float(d['coord']) + signo * float(d.get('margen', 0.0))
    nombre = d['eje']
    for e in ejes_ref:
        if e.nombre == nombre:
            return e.coord + signo * float(d.get('margen', 0.0))
    raise SystemExit(
        'La ventana pide el eje %r para el borde %s y esa lamina no lo '
        'tiene. Ejes disponibles: %s'
        % (nombre, lado, ', '.join(sorted(e.nombre for e in ejes_ref))))


def _ventana(perfil, ejes_ref):
    """
    Caja donde vive el edificio que se esta modelando.

    Hay dos modos, y la diferencia entre ellos importa:

    `malla_de_ejes` -- toda la malla mas un margen. Sirve para separar
    la planta de las VISTAS DE DETALLE dibujadas al lado en las mismas
    capas. No sabe distinguir un edificio de otro.

    `ejes_nombrados` -- cada borde es un eje con nombre. Sirve cuando
    la lamina trae MAS DE UNA ESTRUCTURA: una etapa anterior al otro
    lado de la junta de dilatacion, una rampa de acceso, el edificio
    vecino. Todo eso tiene ejes propios y cae fuera de los ejes del
    edificio; recortar por la malla completa lo dejaba adentro.

    Es tambien el mecanismo con el que dos personas se reparten un
    mismo juego de planos: cada una declara los ejes que acotan SU
    cuerpo, y los dos modelos quedan en el mismo sistema de
    coordenadas sin pisarse.

    Devuelve None si el perfil no pide recortar.
    """
    cfg = perfil.datos.get('ventana')
    if not cfg:
        return None
    modo = cfg.get('modo')

    if modo == 'ejes_nombrados':
        caja = (_lado(cfg, 'xmin', ejes_ref, -1), _lado(cfg, 'ymin', ejes_ref, -1),
                _lado(cfg, 'xmax', ejes_ref, +1), _lado(cfg, 'ymax', ejes_ref, +1))
        if any(c is None for c in caja):
            raise SystemExit('La ventana `ejes_nombrados` necesita los cuatro '
                             'bordes: xmin, ymin, xmax, ymax.')
        return caja

    if modo != 'malla_de_ejes':
        return None
    xs = [e.coord for e in ejes_ref if e.direccion == 'X']
    ys = [e.coord for e in ejes_ref if e.direccion == 'Y']
    if not xs or not ys:
        return None
    m = float(cfg.get('margen', 3.0))
    return (min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)


def _recortar_segmentos(segmentos, ventana):
    """(dentro, cuantos_quedaron_fuera). Un segmento entra si entra entero."""
    if ventana is None:
        return segmentos, 0
    x0, y0, x1, y1 = ventana
    dentro = [s for s in segmentos
              if x0 <= s.x1 <= x1 and x0 <= s.x2 <= x1
              and y0 <= s.y1 <= y1 and y0 <= s.y2 <= y1]
    return dentro, len(segmentos) - len(dentro)


# ============================================================
def _describir_eje(x1, y1, x2, y2):
    """(angulo, offset perpendicular, largo) del eje de un elemento."""
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return None
    ux, uy = dx / L, dy / L
    if (ux < 0) or (abs(ux) < 1e-9 and uy < 0):    # sentido canonico
        ux, uy = -ux, -uy
    ang = math.degrees(math.atan2(uy, ux)) % 180.0
    d = -x1 * uy + y1 * ux                          # coordenada normal
    return ang, d, L


def alinear_casi_colineales(muros, vigas, tol, tol_ang=2.0):
    """
    Pone sobre UN MISMO EJE los elementos que son casi colineales.

    Por que hace falta. Una fachada no es un solo elemento: hay una
    viga de 0.60 de ancho a lo largo de casi todo el frente y, en las
    esquinas, un muro de 0.30. Los dos comparten la CARA EXTERIOR del
    edificio -- en el LT2, y = 10.63 -- pero como tienen anchos
    distintos sus EJES no coinciden: la viga en 10.93 y el muro en
    10.78, 15 cm de diferencia.

    Modelados cada uno en su eje, el perimetro del edificio queda en
    zigzag: en cada esquina hay un escalon de 10 a 15 cm, el borde de
    los panos se quiebra y las areas tributarias salen con astillas
    diagonales en vez de terminar en angulo recto.

    Que se hace. Los elementos paralelos cuyos ejes estan a menos de
    `tol` se llevan al eje del MAS LARGO del grupo -- el que manda la
    linea de fachada. Mover un muro de 1.45 m unos 15 cm no cambia
    nada estructural (se comprueba corriendo el modelo), y a cambio el
    perimetro queda recto.

    Es una SIMPLIFICACION declarada, con su tolerancia en el perfil, y
    devuelve la lista de lo que movio para que quede en la auditoria.
    """
    if tol <= 0:
        return muros, vigas, {'aplicado': False}

    piezas = ([('muro', i, m['x1'], m['y1'], m['x2'], m['y2']) for i, m in enumerate(muros)]
              + [('viga', i, v['x1'], v['y1'], v['x2'], v['y2']) for i, v in enumerate(vigas)])
    descritas = []
    for tipo, i, x1, y1, x2, y2 in piezas:
        d = _describir_eje(x1, y1, x2, y2)
        if d is not None:
            descritas.append((tipo, i, d[0], d[1], d[2]))

    grupos = []
    for pieza in descritas:
        for g in grupos:
            ang0, d0 = g[0][2], g[0][3]
            if (min(abs(pieza[2] - ang0), 180.0 - abs(pieza[2] - ang0)) <= tol_ang
                    and abs(pieza[3] - d0) <= tol):
                g.append(pieza)
                break
        else:
            grupos.append([pieza])

    movidos = []
    for g in grupos:
        if len(g) < 2:
            continue
        tipo_m, i_m, ang_m, d_objetivo, largo_m = max(g, key=lambda p: p[4])
        for tipo, i, ang, d, largo in g:
            if abs(d - d_objetivo) < 1e-9:
                continue
            lista = muros if tipo == 'muro' else vigas
            e = lista[i]
            corr = d_objetivo - d
            # mover el eje = correrlo por su NORMAL
            ux = math.cos(math.radians(ang))
            uy = math.sin(math.radians(ang))
            nx, ny = -uy, ux
            e['x1'] += nx * corr
            e['y1'] += ny * corr
            e['x2'] += nx * corr
            e['y2'] += ny * corr
            movidos.append({'tipo': tipo, 'corrimiento_m': round(corr, 4),
                            'largo_m': round(largo, 2),
                            'se_alineo_con': '%s de %.2f m' % (tipo_m, largo_m)})

    return muros, vigas, {
        'aplicado': True, 'tolerancia_m': tol,
        'elementos_movidos': len(movidos),
        'corrimiento_maximo_m': (max(abs(x['corrimiento_m']) for x in movidos)
                                 if movidos else 0.0),
        'detalle': movidos,
    }


# ============================================================
def extraer(carpeta, perfil):
    """Devuelve el diccionario de geometria completo."""
    plantas_declaradas = perfil.datos.get('hojas', {})
    elevaciones = perfil.datos.get('elevaciones', [])

    # --- 1. leer las plantas y sus ejes ---------------------
    hojas, ejes_por_hoja = {}, {}
    for papel, nombre in plantas_declaradas.items():
        ruta = os.path.join(carpeta, nombre + '.dxf')
        if not os.path.isfile(ruta):
            print('  AVISO: falta la lamina %s (%s)' % (nombre, papel))
            continue
        print('  leyendo %s (%s)...' % (nombre, papel), flush=True)
        h = lectura.leer(ruta, perfil)
        hojas[nombre] = h
        E, aud = mod_ejes.extraer(h, perfil)
        ejes_por_hoja[nombre] = (E, aud)

    if not hojas:
        raise SystemExit('No se pudo leer ninguna planta.')

    # --- 2. registrar las plantas entre si ------------------
    # La referencia es la planta tipo si esta declarada; si no, la
    # lamina con mas ejes (la que mas informacion aporta).
    referencia = perfil.hoja('planta_tipo')
    if referencia not in ejes_por_hoja:
        referencia = max(ejes_por_hoja, key=lambda n: len(ejes_por_hoja[n][0]))
    ejes_ref = ejes_por_hoja[referencia][0]

    registros = {}
    for nombre, (E, _aud) in ejes_por_hoja.items():
        registros[nombre] = alineacion.registrar(ejes_ref, E)

    # --- 3. la ventana de interes ---------------------------
    # Una lamina trae la planta Y vistas de detalle al lado, en las
    # mismas capas. Lo que cae lejos de la malla de ejes no es parte
    # de la planta. Se descarta contandolo, no en silencio.
    ventana = _ventana(perfil, ejes_ref)

    # --- 4. muros y pilares, ya alineados -------------------
    plantas = {}
    for nombre, h in hojas.items():
        reg = registros[nombre]
        dx, dy = reg.dx, reg.dy

        segs_muro = alineacion.desplazar_segmentos(
            h.segmentos_de(perfil, 'muros'), dx, dy)
        segs_muro, fuera_muro = _recortar_segmentos(segs_muro, ventana)
        M, audM = mod_muros.extraer(
            segs_muro,
            espesor_min=perfil.opcion('muros', 'espesor_min', 0.10),
            espesor_max=perfil.opcion('muros', 'espesor_max', 0.60),
            largo_min=perfil.opcion('muros', 'largo_min', 1.0))

        segs_pilar = alineacion.desplazar_segmentos(
            h.segmentos_de(perfil, 'pilares'), dx, dy)
        segs_pilar, fuera_pilar = _recortar_segmentos(segs_pilar, ventana)
        etiquetas = alineacion.desplazar_puntos(
            h.textos_de(perfil, 'etiquetas'), dx, dy)
        PI, audP = mod_pilares.extraer(segs_pilar, etiquetas)

        segs_viga = alineacion.desplazar_segmentos(
            h.segmentos_de(perfil, 'vigas'), dx, dy)
        segs_viga, fuera_viga = _recortar_segmentos(segs_viga, ventana)
        VG, audV = mod_vigas.extraer(
            segs_viga, etiquetas,
            ancho_min=perfil.opcion('vigas', 'ancho_min', 0.15),
            ancho_max=perfil.opcion('vigas', 'ancho_max', 1.20),
            largo_min=perfil.opcion('vigas', 'largo_min', 1.0),
            gap_colineal=perfil.opcion('vigas', 'gap_colineal',
                                       mod_vigas.GAP_COLINEAL))

        M, VG, aud_alin = alinear_casi_colineales(
            mod_muros.a_json(M), mod_vigas.a_json(VG),
            tol=perfil.opcion('muros', 'alinear_ejes_casi_colineales', 0.0))

        audM['descartados_fuera_de_la_ventana'] = fuera_muro
        audP['descartados_fuera_de_la_ventana'] = fuera_pilar
        audV['descartados_fuera_de_la_ventana'] = fuera_viga

        papel = next((k for k, v in plantas_declaradas.items() if v == nombre), nombre)
        plantas[nombre] = {
            'papel': papel,
            'registro': {'dx': round(dx, 4), 'dy': round(dy, 4),
                         'residuo_max': (None if reg.residuo_max == float('inf')
                                         else round(reg.residuo_max, 5)),
                         'ok': reg.ok,
                         'ejes_usados_x': reg.ejes_usados_x,
                         'ejes_usados_y': reg.ejes_usados_y},
            'ejes': mod_ejes.a_json(alineacion.desplazar_ejes(
                ejes_por_hoja[nombre][0], dx, dy)),
            'muros': M,
            'pilares': mod_pilares.a_json(PI),
            'vigas': VG,
            'auditoria': {'ejes': ejes_por_hoja[nombre][1],
                          'alineacion_de_ejes': aud_alin,
                          'muros': audM,
                          'pilares': audP,
                          'vigas': audV},
        }

    # --- 5. niveles desde las elevaciones -------------------
    resultados_niveles = {}
    for nombre in elevaciones:
        ruta = os.path.join(carpeta, nombre + '.dxf')
        if not os.path.isfile(ruta):
            print('  AVISO: falta la elevacion %s' % nombre)
            continue
        print('  leyendo %s (elevacion)...' % nombre, flush=True)
        h = lectura.leer(ruta, perfil)
        resultados_niveles[nombre] = mod_niveles.extraer(h)

    combinados = mod_niveles.combinar(resultados_niveles) if resultados_niveles else []
    n_elev = len(resultados_niveles)
    # Un nivel confirmado por TODAS las elevaciones es un piso del
    # edificio. Uno que sale en una sola es una cota local (un
    # antepecho, una losa de sala de maquinas). La distincion la
    # hacen los votos, no el criterio de quien programa.
    consenso = [c for c in combinados if c['laminas'] == n_elev] if n_elev else []

    # --- 6. espesor de losa, desde los rotulos ---------------
    losas_json, aud_losas = [], None
    cfg_losa = perfil.datos.get('rotulos_de_losa')
    if cfg_losa:
        ref_ruta = os.path.join(carpeta, referencia + '.dxf')
        panos, aud_losas = mod_losas.extraer(
            ref_ruta,
            bloque=cfg_losa['bloque'],
            tag_espesor=cfg_losa['tag_espesor'],
            tag_nombre=cfg_losa.get('tag_nombre'),
            factor_espesor=mod_perfil.A_METROS[cfg_losa.get('unidades_espesor', 'cm')],
            factor_posicion=perfil.factor)
        reg_ref = registros[referencia]
        losas_json = [dict(d, x=round(d['x'] + reg_ref.dx, 3),
                           y=round(d['y'] + reg_ref.dy, 3))
                      for d in mod_losas.a_json(panos)]

    return {
        'proyecto': perfil.nombre,
        'perfil': os.path.basename(perfil.ruta or ''),
        'carpeta_dxf': os.path.abspath(carpeta),
        'unidades': 'm  (el dibujo estaba en %s)' % perfil.unidades,
        'lamina_de_referencia': referencia,
        'ventana': ({'xmin': round(ventana[0], 3), 'ymin': round(ventana[1], 3),
                     'xmax': round(ventana[2], 3), 'ymax': round(ventana[3], 3)}
                    if ventana else None),
        'ejes': mod_ejes.a_json(ejes_ref),
        'niveles': {
            'confirmados_por_todas_las_elevaciones': [c['z'] for c in consenso],
            'alturas_entre_niveles': [round(b['z'] - a['z'], 3)
                                      for a, b in zip(consenso, consenso[1:])],
            'todos': combinados,
            'por_lamina': {n: aud for n, (_N, _d, aud) in resultados_niveles.items()},
        },
        'plantas': plantas,
        'losas': {'panos': losas_json, 'auditoria': aud_losas},
        # Dinteles DECLARADOS en el perfil: elementos que el plano no
        # dibuja y que el modelo supone. Viajan con la geometria para
        # que el modelo no tenga que abrir el perfil, pero se llaman
        # asi --'perfil_'-- para que nadie los confunda con algo leido
        # del DXF.
        'perfil_dinteles': perfil.datos.get('dinteles', []),
        'materiales': perfil.datos.get('materiales', {}),
        'cargas': perfil.datos.get('cargas', {}),
        'niveles_del_modelo': perfil.datos.get('niveles_del_modelo', {}),
    }


# ============================================================
def escribir_informe(geo, ruta):
    L = []
    a = L.append
    a('# Geometria extraida de los planos\n')
    a('**Proyecto:** %s  ' % geo['proyecto'])
    a('**Perfil:** `%s`  ' % geo['perfil'])
    a('**Planos:** `%s`  ' % geo['carpeta_dxf'])
    a('**Unidades:** %s\n' % geo['unidades'])

    a('\n## Ejes (lamina de referencia: `%s`)\n' % geo['lamina_de_referencia'])
    a('| Direccion | Ejes |')
    a('|---|---|')
    for d in ('X', 'Y'):
        a('| %s (%d) | %s |' % (
            'vertical, x constante' if d == 'X' else 'horizontal, y constante',
            len(geo['ejes'][d]),
            ' · '.join('**%s**=%.3f' % (e['nombre'], e['coord']) for e in geo['ejes'][d])))

    a('\n## Niveles\n')
    niv = geo['niveles']
    a('Confirmados por **todas** las elevaciones: `%s`\n'
      % ', '.join('%+.2f' % z for z in niv['confirmados_por_todas_las_elevaciones']))
    a('Alturas entre niveles: `%s`\n'
      % ', '.join('%.2f' % h for h in niv['alturas_entre_niveles']))
    a('\n| Cota z (m) | En cuantas elevaciones | Laminas |')
    a('|---:|---:|---|')
    for c in niv['todos']:
        a('| %+8.3f | %d | %s |' % (c['z'], c['laminas'],
                                    ', '.join(x.split('-')[-1] for x in c['visto_en'])))

    a('\n### Verificacion del desfase de cada elevacion\n')
    a('El desfase `y_dibujo - cota` debe ser el MISMO para todas las cotas de una lamina.')
    a('Si lo es, la lectura de niveles esta verificada por dentro.\n')
    a('| Lamina | Desfase (m) | Dispersion (m) | Coherente | Cotas usadas | Descartadas |')
    a('|---|---:|---:|---|---:|---:|')
    for lam, aud in niv['por_lamina'].items():
        a('| `%s` | %.3f | %.4f | %s | %d | %d |' % (
            lam, aud.get('desfase', 0), aud.get('dispersion_del_desfase', 0),
            'si' if aud.get('coherente') else '**NO**',
            aud.get('cotas_usadas', 0), len(aud.get('cotas_descartadas', []))))

    a('\n## Registro de las plantas\n')
    a('Cada lamina se dibuja en su propio origen. Se corren todas al de `%s`'
      % geo['lamina_de_referencia'])
    a('usando los ejes que comparten nombre. El residuo mide cuanto NO calzan')
    a('despues de correrlas: si es grande, algo esta mal leido.\n')
    a('| Lamina | Papel | dx (m) | dy (m) | Residuo (m) | Ejes usados |')
    a('|---|---|---:|---:|---:|---|')
    for nombre, p in geo['plantas'].items():
        r = p['registro']
        a('| `%s` | %s | %+.3f | %+.3f | %s | X: %s / Y: %s |' % (
            nombre, p['papel'], r['dx'], r['dy'],
            ('%.5f' % r['residuo_max']) if r['residuo_max'] is not None else 'n/a',
            ','.join(r['ejes_usados_x']) or '—',
            ','.join(r['ejes_usados_y']) or '—'))

    a('\n## Muros\n')
    a('Un muro se dibuja como sus dos caras. La **cobertura** es que porcentaje')
    a('del largo dibujado quedo emparejado: lo que falta es muro que el modelo')
    a('NO va a tener.\n')
    a('| Lamina | Muros | Cobertura | Caras sin pareja | Largo total (m) | Espesores (m) |')
    a('|---|---:|---:|---:|---:|---|')
    for nombre, p in geo['plantas'].items():
        m = p['auditoria']['muros']
        a('| `%s` | %d | %.1f %% | %d | %.2f | %s |' % (
            nombre, m['muros_emparejados'], 100 * m['cobertura'],
            m['caras_sin_pareja'], m['largo_total_muros'],
            ', '.join('%.2f×%d' % (e, n) for e, n in m['espesores'])))

    a('\n## Pilares\n')
    a('| Lamina | Pilares | Grupos | Secciones | Contorno abierto | No rectangulares | Etiqueta no calza |')
    a('|---|---:|---:|---|---:|---:|---:|')
    for nombre, p in geo['plantas'].items():
        q = p['auditoria']['pilares']
        a('| `%s` | %d | %d | %s | %d | %d | %d |' % (
            nombre, q['pilares'], q['grupos_encontrados'],
            ', '.join('%s×%d' % (s, n) for s, n in q['secciones']),
            len(q['contorno_abierto']), len(q['grupos_no_rectangulares']),
            len(q['etiqueta_no_calza_con_el_dibujo'])))

    a('\n## Vigas\n')
    a('El **ancho** se mide del dibujo; el **alto** se lee de la etiqueta')
    a('(`V. 60/80` = 60 de ancho x 80 de alto). Que el ancho medido calce con')
    a('el rotulo es una verificacion cruzada: las dos cifras vienen de fuentes')
    a('distintas del plano.\n')
    a('| Lamina | Vigas | Cobertura | Con etiqueta | Sin alto | Ancho no calza | Secciones |')
    a('|---|---:|---:|---:|---:|---:|---|')
    for nombre, p in geo['plantas'].items():
        v = p['auditoria']['vigas']
        a('| `%s` | %d | %.1f %% | %d | %d | %d | %s |' % (
            nombre, v['vigas'], 100 * v['cobertura'], v['con_etiqueta'],
            v['sin_alto'], len(v['ancho_no_calza_con_la_etiqueta']),
            ', '.join('%s×%d' % (s, n) for s, n in v['secciones'])))

    if geo.get('losas', {}).get('auditoria'):
        al = geo['losas']['auditoria']
        a('\n## Losa\n')
        a('El espesor de losa no se puede medir en planta: se lee del atributo')
        a('`%s` del bloque `%s`, que tiene nombre y por lo tanto no hay que'
          % (al.get('tag_espesor', 'ESP'), al['bloque']))
        a('adivinar cual de los numeros del plano es.\n')
        a('| Panos rotulados | Espesores (m) | Espesor unico | Rotulos ilegibles |')
        a('|---:|---|---|---:|')
        a('| %d | %s | %s | %d |' % (
            al['panos'],
            ', '.join('%.2f×%d' % (e, n) for e, n in al['espesores']),
            'si' if al['espesor_unico'] else '**NO**',
            al['rotulos_sin_espesor_legible']))

    if geo.get('materiales', {}).get('hormigon'):
        hm = geo['materiales']['hormigon']
        a('\n## Material\n')
        a("Hormigon **%s**, f'c = **%.0f MPa**, gamma = %.0f kN/m3.\n"
          % (hm.get('designacion', '?'), hm.get('fc_MPa', 0),
             hm.get('peso_especifico_kNm3', 0)))
        a('> %s' % hm.get('_fuente', ''))

    a('\n## Lo que quedo dudoso\n')
    dudas = []
    for nombre, p in geo['plantas'].items():
        ae = p['auditoria']['ejes']
        if ae['burbujas_sin_clasificar']:
            dudas.append('`%s`: burbujas de eje sin clasificar: %s' % (
                nombre, [b['nombre'] for b in ae['burbujas_sin_clasificar']]))
        if ae['sin_linea_de_apoyo']:
            dudas.append('`%s`: ejes rotulados sin linea de eje que los respalde: %s'
                         % (nombre, ae['sin_linea_de_apoyo']))
        am = p['auditoria']['muros']
        if am['caras_sin_pareja']:
            dudas.append('`%s`: %d caras de muro sin pareja (largos %s m)' % (
                nombre, am['caras_sin_pareja'], am['caras_sin_pareja_largos'][:5]))
        aq = p['auditoria']['pilares']
        if aq['grupos_no_rectangulares']:
            dudas.append('`%s`: %d grupos de la capa de pilares que no son rectangulos'
                         % (nombre, len(aq['grupos_no_rectangulares'])))
        if aq['etiqueta_no_calza_con_el_dibujo']:
            dudas.append('`%s`: %d pilares donde la etiqueta no calza con lo medido'
                         % (nombre, len(aq['etiqueta_no_calza_con_el_dibujo'])))
        av = p['auditoria']['vigas']
        if av['sin_alto']:
            dudas.append('`%s`: %d vigas sin etiqueta cerca, o sea SIN ALTO conocido'
                         % (nombre, av['sin_alto']))
        if av['ancho_no_calza_con_la_etiqueta']:
            dudas.append('`%s`: %d vigas donde el ancho medido no calza con el rotulo'
                         % (nombre, len(av['ancho_no_calza_con_la_etiqueta'])))
        if not p['registro']['ok']:
            dudas.append('`%s`: el registro contra la lamina de referencia NO cierra'
                         % nombre)
    if dudas:
        for d in dudas:
            a('- %s' % d)
    else:
        a('Nada.')

    a('\n> Esto es una lectura del plano, no una interpretacion estructural.')
    a('> Los puntos dudosos hay que resolverlos MIRANDO el plano: la geometria')
    a('> sola no alcanza para decidirlos.\n')

    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


# ============================================================
def main():
    ap = argparse.ArgumentParser(
        description='Extrae geometria estructural de un juego de planos DXF.')
    ap.add_argument('carpeta', help='carpeta con los .dxf convertidos')
    ap.add_argument('--perfil', required=True,
                    help='nombre o ruta del perfil (ej: lt2_2024_22)')
    ap.add_argument('--salida', default=None, help='ruta del geometria.json')
    args = ap.parse_args()

    perfil = mod_perfil.cargar(args.perfil)
    print('Perfil: %s' % perfil.nombre)
    geo = extraer(args.carpeta, perfil)

    base = os.path.splitext(os.path.basename(perfil.ruta))[0]
    destino = args.salida or os.path.join(_RAIZ, 'data', 'geometria_%s.json' % base)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, 'w', encoding='utf-8') as f:
        json.dump(geo, f, indent=1, ensure_ascii=False)

    informe = os.path.join(_RAIZ, 'reports', 'geometria_%s.md' % base)
    os.makedirs(os.path.dirname(informe), exist_ok=True)
    escribir_informe(geo, informe)

    print('\nEjes:    %d en X, %d en Y' % (len(geo['ejes']['X']), len(geo['ejes']['Y'])))
    print('Niveles: %s' % geo['niveles']['confirmados_por_todas_las_elevaciones'])
    for nombre, p in geo['plantas'].items():
        print('%-16s %2d muros, %2d pilares, %2d vigas   (dx=%+.3f dy=%+.3f)' % (
            nombre, len(p['muros']), len(p['pilares']), len(p['vigas']),
            p['registro']['dx'], p['registro']['dy']))
    print('\n  %s' % destino)
    print('  %s' % informe)


if __name__ == '__main__':
    main()
