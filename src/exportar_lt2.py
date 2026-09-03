# -*- coding: utf-8 -*-
r"""
================================================================
 exportar_unity.py  -  CONTRATO JSON  OpenSees -> Unity  (LT2)
================================================================
 Corre el modelo del edificio LT2, resuelve el caso G y escribe
 data/modelo_unity.json con el MISMO contrato del laboratorio
 P1L2, para que el visor de Unity lo abra sin tocar una linea
 de C#.

 REGLA DE ORO: OpenSees calcula, el JSON es la fuente de verdad,
 Unity solo MUESTRA. Por eso aca se exporta ya calculado todo lo
 que Unity necesita dibujar:

   - nodos con sus restricciones por GDL (no un booleano);
   - elementos con su tipo, su seccion y su tamano real;
   - EJES LOCALES calculados en Python. Unity NO debe deducirlos:
     dependen de vecxz y de la convencion de OpenSees, y adivinarlos
     en C# es la duplicacion que despues diverge del modelo;
   - diafragmas (maestro + esclavos);
   - el caso de carga G COMPLETO.

 ----------------------------------------------------------------
 EL JSON TIENE QUE DESCRIBIR EL MISMO PROBLEMA QUE RESOLVIO PYTHON
 ----------------------------------------------------------------
 Si se reanaliza desde Unity y el JSON no calza, el servidor
 devuelve otros numeros y NO hay ningun error. En el P1L2 paso dos
 veces: una porque el caso G exportado no traia el peso propio
 (10.04 mm en vez de 11.78) y otra porque las inercias iban ya
 cruzadas y el servidor las cruzaba de nuevo (12.17 mm).

 Por eso al final esta funcion COMPARA la carga exportada contra la
 que se aplico de verdad y falla si no coinciden.

 ----------------------------------------------------------------
 CONVENCION DE Iy / Iz EN EL CONTRATO
 ----------------------------------------------------------------
 Van en EJES DE LA SECCION, no en los huecos de ops.element().
 Quien construya el modelo aplica el cruce segun la geometria:

   horizontal (vecxz = 0,0,1) -> Iy_slot = sec.Iz   (gravedad)
   vertical   (vecxz = 1,0,0) -> Iy_slot = sec.Iy

 Correr:  python src/exportar_unity.py
================================================================
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openseespy.opensees as ops        # noqa: E402

import modelo_lt2 as M                   # noqa: E402

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(_RAIZ, 'data', 'modelo_unity.json')


# ============================================================
def ejes_locales(pi, pj, vecxz):
    r"""
    Los tres versores locales de una barra, con la MISMA convencion
    que usa OpenSees en geomTransf:

        local_x = (j - i) normalizado
        local_z = componente de vecxz perpendicular a local_x
        local_y = local_z x local_x
    """
    dx = [pj[k] - pi[k] for k in range(3)]
    L = math.sqrt(sum(c * c for c in dx))
    if L < 1e-12:
        raise ValueError('barra de largo cero')
    ex = [c / L for c in dx]

    v = list(vecxz)
    proy = sum(v[k] * ex[k] for k in range(3))
    ez = [v[k] - proy * ex[k] for k in range(3)]
    n = math.sqrt(sum(c * c for c in ez))
    if n < 1e-9:
        raise ValueError('vecxz paralelo al eje del elemento')
    ez = [c / n for c in ez]

    ey = [ez[1] * ex[2] - ez[2] * ex[1],
          ez[2] * ex[0] - ez[0] * ex[2],
          ez[0] * ex[1] - ez[1] * ex[0]]
    return ex, ey, ez


def r6(v):
    return [round(float(c), 6) for c in v]


def tipo_de_viga(pi, pj):
    """'viga_x' o 'viga_y' segun hacia donde corre en planta.

    El visor del P1L2 colorea y filtra por estos dos tipos; una barra
    horizontal con cualquier otro nombre no aparece en ningun toggle.
    """
    return 'viga_x' if abs(pj[0] - pi[0]) >= abs(pj[1] - pi[1]) else 'viga_y'


# ============================================================
def main(salida=None):
    salida = salida or SALIDA
    print('Construyendo el modelo LT2 ...')
    m = M.ModeloLT2().preparar().ensamblar('G').resolver()
    r = m.resumen()
    print('  caso G resuelto. Carga total %.2f kN' % r['carga_total'])
    print('  equilibrio: aplicada %.4f = reacciones %.4f (error %.2e)'
          % (r['carga_total'], r['reaccion_vertical'], r['error_equilibrio']))

    coords = m.nodos
    apoyos = set(m.nodos_base)

    # ---------- Nodos ----------
    nodos = []
    for n in sorted(coords):
        x, y, z = coords[n]
        d = ops.nodeDisp(n)
        fijo = n in apoyos
        nodos.append({
            'id': n,
            'x': round(x, 4), 'y': round(y, 4), 'z': round(z, 4),
            'fijo': fijo,
            'restricciones': [1] * 6 if fijo else [0] * 6,
            'auxiliar': False,
            'ux': round(d[0], 9), 'uy': round(d[1], 9), 'uz': round(d[2], 9),
        })

    # ---------- Secciones ----------
    # Iy = inercia LATERAL, Iz = inercia de GRAVEDAD, igual que el P1L2.
    # En modelo_lt2.seccion(): Iz = b*h^3/12 e Iy = h*b^3/12, con b el
    # ancho y h el canto. Para un muro b = espesor y h = largo, asi que
    # su Iz es la inercia FUERTE. Es la misma convencion.
    secciones = []
    for s in sorted(m.secciones.values(), key=lambda s: s.nombre):
        secciones.append({
            'nombre': s.nombre,
            'A': round(s.A, 6),
            'Iy': round(s.Iy, 9),
            'Iz': round(s.Iz, 9),
            'J': round(s.J, 9),
            'b': round(s.b, 4),
            'h': round(s.h, 4),
        })

    # ---------- Elementos ----------
    elementos = []

    def agregar(tag, ni, nj, tipo, sec, vecxz, largo=0.0, espesor=0.0,
                dir_largo=(0.0, 0.0)):
        ex, ey, ez = ejes_locales(coords[ni], coords[nj], vecxz)
        elementos.append({
            'id': tag, 'n1': ni, 'n2': nj,
            'tipo': tipo, 'seccion': sec.nombre,
            'vecxz': r6(vecxz),
            'localX': r6(ex), 'localY': r6(ey), 'localZ': r6(ez),
            # Hacia donde corre el LARGO del muro en planta.
            #
            # Unity no lo puede deducir de vecxz: en un muro vecxz es
            # la NORMAL al muro (asi queda la inercia fuerte donde
            # corresponde), no su direccion. Deducirlo dibujaba todos
            # los muros girados 90 grados -- el del ascensor atravesado
            # y el de fachada metido para adentro del edificio.
            'dir_largo': r6(dir_largo),
            # Solo para muros: su tamano REAL en planta. La barra
            # equivalente vive en el eje baricentrico; sin estos dos
            # numeros Unity dibujaria un muro de 8 m como una columna
            # flaca en medio del vano y no se podria juzgar si esta
            # donde dice el plano.
            'largo': round(float(largo), 4),
            'espesor': round(float(espesor), 4),
        })

    for tag, n1, n2, sec, vecxz, tipo, _peso in m.verticales:
        if tipo == 'muro':
            # vecxz es la normal al muro en planta; el largo corre
            # perpendicular a ella.
            agregar(tag, n1, n2, 'muro', sec, vecxz,
                    largo=sec.h, espesor=sec.b,
                    dir_largo=(-vecxz[1], vecxz[0]))
        else:
            agregar(tag, n1, n2, 'columna', sec, vecxz)

    VEC_HORIZONTAL = (0.0, 0.0, 1.0)
    for tag, n1, n2, sec, _L, _peso, _k in m.vigas:
        agregar(tag, n1, n2, tipo_de_viga(coords[n1], coords[n2]),
                sec, VEC_HORIZONTAL)

    # Los brazos van con tipo PROPIO. No son vigas (no tienen luz ni
    # seccion de viga) ni se pueden dibujar como placa de muro: son
    # horizontales, y la placa de muro usa la distancia entre nodos
    # como ALTURA -- un brazo de 3.6 m salia como una plancha de
    # 3.6 x 3.6 m flotando de canto. Eran las "escaleras" grises que
    # aparecian en el aire.
    for tag, n1, n2, sec, L, _k in m.brazos:
        agregar(tag, n1, n2, 'brazo', sec, VEC_HORIZONTAL)

    # ---------- Diafragmas ----------
    diafragmas = []
    for k, maestro in sorted(m.maestros.items()):
        esclavos = [m.nodo_de[(k, i)] for i in range(len(m.malla_nivel[k][0]))
                    if m.nodo_de[(k, i)] in m.nodos]
        diafragmas.append({'nodo_maestro': maestro, 'nodos': esclavos,
                           'perpendicular': 3})
        # El maestro tambien tiene que estar en la lista de nodos.
        xm, ym, zm = ops.nodeCoord(maestro)
        nodos.append({
            'id': maestro,
            'x': round(xm, 4), 'y': round(ym, 4), 'z': round(zm, 4),
            'fijo': False,
            'restricciones': [0, 0, 1, 1, 1, 0],
            'auxiliar': True,
            'ux': round(ops.nodeDisp(maestro, 1), 9),
            'uy': round(ops.nodeDisp(maestro, 2), 9),
            'uz': round(ops.nodeDisp(maestro, 3), 9),
        })

    # ---------- Areas tributarias ----------
    # Se exporta el area, la luz, la carga Y EL POLIGONO de cada barra:
    # el trapecio o el triangulo que la losa le descarga.
    #
    # Los poligonos van CONCATENADOS con una lista de tamanos, porque
    # JsonUtility de Unity no lee listas de listas. Una viga interior
    # toma un trapecio de un pano (4 vertices) y un triangulo del otro
    # (3): 7 vertices y tamanos [4, 3]. Dividir 7 entre 2 mezclaria los
    # vertices de los dos y dibujaria lineas que no existen.
    tributarias = []
    for tag, n1, n2, _sec, L, _peso, k in m.vigas:
        par = (min(n1, n2), max(n1, n2))
        A = m.area_trib.get(par, 0.0)
        if A <= 0:
            continue
        q = m.cargas_lamina[m.pisos[k - 1]['lamina']]['muerta']
        z = m.niveles[k]
        vertices, tamanos = [], []
        for pg in m.poli_trib.get(par, []):
            if len(pg) < 3:
                continue
            for (px, py) in pg:
                # VerticePlanta solo lleva (x, y): la cota es la del
                # piso y viaja una sola vez, en 'z' del area.
                vertices.append({'x': round(float(px), 4),
                                 'y': round(float(py), 4)})
            tamanos.append(len(pg))
        tributarias.append({
            'elemento': tag, 'nivel': k,
            'area': round(A, 6), 'luz': round(L, 4),
            'qG': round(q, 4),
            'carga_total': round(q * A, 4),
            'w': round(q * A / L, 6),
            'z': round(z, 4),
            'vertices': vertices, 'tamanos': tamanos,
            'n_poligonos': len(tamanos),
        })

    # Los BRAZOS son borde de pano igual que una viga -- son un pedazo
    # de muro -- y por lo tanto tambien reciben losa. Sin exportarlos
    # quedaban huecos blancos justo alrededor del nucleo de ascensores,
    # que es donde mas brazos hay.
    for tag, n1, n2, _sec, L, k in m.brazos:
        par = (min(n1, n2), max(n1, n2))
        A = m.area_trib.get(par, 0.0)
        if A <= 0:
            continue
        q = m.cargas_lamina[m.pisos[k - 1]['lamina']]['muerta']
        z = m.niveles[k]
        vertices, tamanos = [], []
        for pg in m.poli_trib.get(par, []):
            if len(pg) < 3:
                continue
            for (px, py) in pg:
                vertices.append({'x': round(float(px), 4),
                                 'y': round(float(py), 4)})
            tamanos.append(len(pg))
        tributarias.append({
            'elemento': tag, 'nivel': k,
            'area': round(A, 6), 'luz': round(L, 4),
            'qG': round(q, 4),
            'carga_total': round(q * A, 4),
            'w': round(q * A / L, 6),
            'z': round(z, 4),
            'vertices': vertices, 'tamanos': tamanos,
            'n_poligonos': len(tamanos),
        })

    # Los MUROS tambien reciben losa. Donde no hay viga -- el bloque
    # nororiente de esta planta -- el pano descarga directo sobre el
    # muro, y en el modelo eso va como carga PUNTUAL en su baricentro,
    # que es estaticamente equivalente.
    #
    # Sin exportar tambien esos panos, el visor mostraba un hueco
    # blanco de 56 m2 por piso donde en realidad si hay losa cargando:
    # la carga estaba en el modelo, pero no se veia, y quien mirara
    # habria concluido que faltaba.
    #
    # 'luz' es el largo del muro y 'w' la carga repartida sobre el:
    # es la lectura util al senalarlo, y es la misma resultante que el
    # modelo aplica en el nodo.
    for tag, n1, n2, sec, vecxz, tipo, _peso in m.verticales:
        if tipo != 'muro':
            continue
        A = m.area_trib_nodal.get(n2, 0.0)
        if A <= 0:
            continue
        z = coords[n2][2]
        k = next((i for i, zz in enumerate(m.niveles) if abs(zz - z) < 1e-9), None)
        if k is None or k == 0:
            continue
        q = m.cargas_lamina[m.pisos[k - 1]['lamina']]['muerta']
        vertices, tamanos = [], []
        for pg in m.poli_trib_nodal.get(n2, []):
            if len(pg) < 3:
                continue
            for (px, py) in pg:
                vertices.append({'x': round(float(px), 4),
                                 'y': round(float(py), 4)})
            tamanos.append(len(pg))
        L = max(sec.h, 1e-6)
        tributarias.append({
            'elemento': tag, 'nivel': k,
            'area': round(A, 6), 'luz': round(L, 4),
            'qG': round(q, 4),
            'carga_total': round(q * A, 4),
            'w': round(q * A / L, 6),
            'z': round(z, 4),
            'vertices': vertices, 'tamanos': tamanos,
            'n_poligonos': len(tamanos),
        })

    # ---------- Caso de carga G ----------
    # Tiene que ser el caso COMPLETO, el mismo que resolvio Python.
    cargas_dist = []
    cargas_nodales = []
    total = 0.0
    acum = {}

    def nodal(n, fz):
        acum[n] = acum.get(n, 0.0) + fz

    # peso propio de columnas y muros: mitad en cada extremo
    for _tag, n1, n2, _sec, _v, _tipo, peso in m.verticales:
        nodal(n1, -peso / 2.0)
        nodal(n2, -peso / 2.0)
        total += peso

    # vigas: peso propio + losa por area tributaria
    for tag, n1, n2, sec, L, _peso, k in m.vigas:
        q = m.cargas_lamina[m.pisos[k - 1]['lamina']]['muerta']
        A = m.area_trib.get((min(n1, n2), max(n1, n2)), 0.0)
        w = sec.A * m.gamma + q * A / L
        cargas_dist.append({'elemento': tag, 'wy': 0.0,
                            'wz': round(-w, 6), 'wx': 0.0})
        total += w * L

    # brazos: no llevan peso propio (ya esta contado en el muro), pero
    # si la losa que se apoya en ellos
    for tag, n1, n2, _sec, L, k in m.brazos:
        q = m.cargas_lamina[m.pisos[k - 1]['lamina']]['muerta']
        A = m.area_trib.get((min(n1, n2), max(n1, n2)), 0.0)
        if A <= 0:
            continue
        w = q * A / L
        cargas_dist.append({'elemento': tag, 'wy': 0.0,
                            'wz': round(-w, 6), 'wx': 0.0})
        total += w * L

    # losa que se apoya directo sobre un muro: carga puntual en su nodo
    for tag, A in m.area_trib_nodal.items():
        if tag not in m.nodos:
            continue
        z = m.nodos[tag][2]
        k = next((i for i, zz in enumerate(m.niveles) if abs(zz - z) < 1e-9), None)
        if k is None or k == 0:
            continue
        q = m.cargas_lamina[m.pisos[k - 1]['lamina']]['muerta']
        nodal(tag, -q * A)
        total += q * A

    for n, fz in sorted(acum.items()):
        cargas_nodales.append({'nodo': n, 'fx': 0.0, 'fy': 0.0,
                               'fz': round(fz, 6),
                               'mx': 0.0, 'my': 0.0, 'mz': 0.0})

    err = abs(total - r['carga_total'])
    print('  caso G exportado: %.4f kN (aplicado %.4f, error %.3e)'
          % (total, r['carga_total'], err))
    if err > 1e-4:
        raise RuntimeError(
            'El caso G exportado (%.4f kN) no coincide con el que se '
            'resolvio (%.4f kN). Quien reanalice desde Unity obtendria '
            'otros resultados.' % (total, r['carga_total']))

    modelo = {
        'info': {
            'descripcion': 'Edificio LT2 - planos de calculo 2024_22',
            'unidades': 'm, kN, kPa',
            'caso_precalculado': 'G',
            'nota': ('Geometria extraida de los planos DXF. Ejes locales '
                     'calculados en Python. Carga de losa por areas '
                     'tributarias a 45 grados sobre los panos detectados.'),
        },
        'material': {'fpc_MPa': m.fc, 'poisson': m.poisson, 'gamma': m.gamma},
        'secciones': secciones,
        'nodos': nodos,
        'elementos': elementos,
        'diafragmas': diafragmas,
        'brazos_rigidos': [],
        'areas_tributarias': tributarias,
        'casos_de_carga': [{
            'nombre': 'G',
            'descripcion': ('Peso propio + losa + peso muerto adicional del '
                            'plano de cargas. Caso COMPLETO.'),
            'cargas_nodales': cargas_nodales,
            'cargas_distribuidas': cargas_dist,
        }],
        'resumen': {
            'n_nodos': len(nodos),
            'n_elementos': len(elementos),
            'n_columnas': r['columnas'],
            'n_vigas': r['vigas'],
            'n_muros': r['muros'] + r['brazos'],
            'n_apoyos': r['apoyos'],
            'n_diafragmas': r['diafragmas'],
            'carga_total_G': round(r['carga_total'], 4),
            'reaccion_vertical_kN': round(r['reaccion_vertical'], 4),
            'error_equilibrio_kN': r['error_equilibrio'],
            'uz_max_mm': round(r['uz_max_mm'], 4),
            'area_losa_por_piso_m2': {str(k): round(a, 2)
                                      for k, a in sorted(m.area_piso.items())},
        },
    }

    os.makedirs(os.path.dirname(salida), exist_ok=True)
    with open(salida, 'w', encoding='utf-8') as f:
        json.dump(modelo, f, indent=1, ensure_ascii=False)

    print('\n  %d nodos, %d elementos, %d secciones, %d diafragmas'
          % (len(nodos), len(elementos), len(secciones), len(diafragmas)))
    print('  UZ maximo: %.3f mm' % r['uz_max_mm'])
    print('  %s  (%.1f MB)' % (salida, os.path.getsize(salida) / 1e6))
    return 0


if __name__ == '__main__':
    # -o permite escribir el JSON en otra parte (lo usa el
    # laboratorio, que tiene su propio data/).
    _o = None
    if '-o' in sys.argv:
        _o = sys.argv[sys.argv.index('-o') + 1]
    sys.exit(main(_o))
