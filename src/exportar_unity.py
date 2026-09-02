# -*- coding: utf-8 -*-
r"""
================================================================
 exportar_unity.py  -  CONTRATO JSON  OpenSees -> Unity
================================================================
 Corre el modelo, resuelve el caso G y escribe modelo_unity.json.

 REGLA DE ORO: OpenSees calcula, el JSON es la fuente de verdad,
 Unity solo MUESTRA. Por eso aqui se exporta TODO lo que Unity
 necesita mostrar ya calculado:

   - nodos, con sus restricciones por GDL (no un booleano "apoyo");
   - elementos, con su tipo y su seccion;
   - EJES LOCALES de cada elemento, calculados en Python.
     Unity NO debe deducirlos: la orientacion depende de vecxz y de
     la convencion de OpenSees, y adivinarla en C# es justo el tipo
     de duplicacion que termina divergiendo del modelo real;
   - DIAFRAGMAS (maestro + esclavos);
   - AREAS TRIBUTARIAS como POLIGONOS, con su area y la carga que
     transfieren. Es lo que alimenta el Tributary Area Inspector y
     lo que permite contestar "cuantos kN de losa llegan a esta
     viga" senalandola.

 Unidades: m, kN. Coordenadas en ejes OpenSees (Z vertical); el
 swap a Y-vertical lo hace Unity en CoordinateMap/Ejes.

 Correr:  python src/exportar_unity.py
================================================================
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openseespy.opensees as ops        # noqa: E402

import areas_tributarias as at           # noqa: E402
import modelo_edificio as M              # noqa: E402

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
def ejes_locales(pi, pj, vecxz):
    r"""
    Calcula los tres versores locales de una barra, con la MISMA
    convencion que usa OpenSees en geomTransf:

        local_x = (j - i) normalizado
        local_z = componente de vecxz perpendicular a local_x
        local_y = local_z  x  local_x

    Se exporta para que Unity los DIBUJE, no los adivine.
    """
    dx = [pj[k] - pi[k] for k in range(3)]
    L = math.sqrt(sum(c * c for c in dx))
    if L < 1e-12:
        raise ValueError("barra de largo cero")
    ex = [c / L for c in dx]

    dot = sum(vecxz[k] * ex[k] for k in range(3))
    ez = [vecxz[k] - dot * ex[k] for k in range(3)]
    nz = math.sqrt(sum(c * c for c in ez))
    if nz < 1e-9:
        raise ValueError("vecxz es paralelo al eje del elemento")
    ez = [c / nz for c in ez]

    ey = [ez[1] * ex[2] - ez[2] * ex[1],
          ez[2] * ex[0] - ez[0] * ex[2],
          ez[0] * ex[1] - ez[1] * ex[0]]

    return ex, ey, ez


def r6(v):
    return [round(float(c), 6) for c in v]


# ============================================================
def main():
    print("Construyendo el modelo ...")
    topo = M.construir_modelo()
    coords = topo['coords']

    M.nuevo_patron()
    carga_G = M.aplicar_carga_gravitacional(topo, M.Q_G, incluir_peso_propio=True)
    ok = M.resolver()
    if ok != 0:
        print("El analisis NO convergio")
        return 1
    print(f"  caso G resuelto. Carga total {carga_G:.2f} kN")

    sumRz = sum(ops.nodeReaction(n, 3) for n in topo['apoyos'])
    print(f"  equilibrio: aplicada {carga_G:.4f} = reacciones {sumRz:.4f} "
          f"(error {abs(carga_G - sumRz):.2e})")

    apoyos = set(topo['apoyos'])

    # ---------- Nodos ----------
    nodos = []
    for n in sorted(coords):
        x, y, z = coords[n]
        d = ops.nodeDisp(n)
        es_apoyo = n in apoyos
        nodos.append({
            'id': n,
            'x': round(x, 4), 'y': round(y, 4), 'z': round(z, 4),
            'fijo': es_apoyo,
            'restricciones': [1, 1, 1, 1, 1, 1] if es_apoyo else [0] * 6,
            'auxiliar': False,
            'ux': round(d[0], 9), 'uy': round(d[1], 9), 'uz': round(d[2], 9),
        })

    # ---------- Elementos + ejes locales ----------
    VEC_VERTICAL = (1.0, 0.0, 0.0)
    VEC_HORIZONTAL = (0.0, 0.0, 1.0)
    elementos = []

    def agregar(tag, ni, nj, tipo, seccion, vecxz, largo=0.0, espesor=0.0):
        ex, ey, ez = ejes_locales(coords[ni], coords[nj], vecxz)
        elementos.append({
            'id': tag, 'n1': ni, 'n2': nj,
            'tipo': tipo, 'seccion': seccion,
            'vecxz': r6(vecxz),
            'localX': r6(ex), 'localY': r6(ey), 'localZ': r6(ez),
            # Solo para muros: su tamano REAL en planta. La barra
            # equivalente vive en el eje baricentrico, asi que sin estos
            # dos numeros Unity la dibujaria como una columna delgada y
            # no se podria juzgar si el muro esta donde dice el plano.
            'largo': round(float(largo), 4),
            'espesor': round(float(espesor), 4),
        })

    for (tag, ni, nj) in topo['columnas']:
        agregar(tag, ni, nj, 'columna', M.SEC_COLUMNA, VEC_VERTICAL)
    for (tag, ni, nj, lev, ix, iy) in topo['vigas_x']:
        agregar(tag, ni, nj, 'viga_x', M.SEC_VIGA_X, VEC_HORIZONTAL)
    for (tag, ni, nj, lev, ix, iy) in topo['vigas_y']:
        agregar(tag, ni, nj, 'viga_y', M.SEC_VIGA_Y, VEC_HORIZONTAL)
    for m in topo['muros']:
        dx, dy = m['dir']
        agregar(m['tag'], m['ni'], m['nj'], 'muro',
                f"MURO_{m['muro_id']}", (dx, dy, 0.0),
                largo=m['largo'], espesor=m['espesor'])

    # ---------- Secciones ----------
    secciones = []
    for nombre, s in M.SECCIONES.items():
        secciones.append({
            'nombre': nombre, 'A': round(s['A'], 6),
            'Iy': round(s['I_grav'], 9), 'Iz': round(s['I_lat'], 9),
            'J': round(s['J'], 9),
        })

    # ---------- Diafragmas ----------
    diafragmas = [{'nodo_maestro': m, 'nodos': e, 'perpendicular': 3}
                  for (m, e) in topo['diafragmas']]

    # ---------- Areas tributarias (poligonos) ----------
    # Se exporta el poligono de cada viga de un piso tipo, junto con
    # el area y la carga que transfiere. Unity los dibuja tal cual.
    trib = M.tributarias_por_viga()
    tributarias = []
    for (tag, ni, nj, lev, ix, iy) in topo['vigas_x'] + topo['vigas_y']:
        tipo = 'X' if (tag, ni, nj, lev, ix, iy) in topo['vigas_x'] else 'Y'
        reg = trib[(tipo, ix, iy)]
        w = at.carga_lineal(M.Q_G, reg['area'], reg['luz'])

        # Los poligonos van CONCATENADOS en 'vertices' (JsonUtility de
        # Unity no lee listas de listas), y 'tamanos' dice cuantos
        # vertices tiene cada uno.
        #
        # OJO: no se puede asumir que todos midan lo mismo. Una viga
        # interior suele tomar un TRAPECIO de un pano (4 vertices) y un
        # TRIANGULO del otro (3): 7 en total. Repartirlos como 7/2 = 3
        # mezcla vertices de un poligono con los del otro y dibuja
        # lineas que no existen.
        poli = []
        tamanos = []
        for p in reg['poligonos']:
            tamanos.append(len(p))
            for (px, py) in p:
                poli.append({'x': round(px, 4), 'y': round(py, 4)})

        tributarias.append({
            'elemento': tag,
            'nivel': lev,
            'area': round(reg['area'], 6),
            'luz': round(reg['luz'], 4),
            'qG': M.Q_G,
            'carga_total': round(M.Q_G * reg['area'], 4),
            'w': round(w, 6),
            'z': round(M.NIVELES_Z[lev], 4),
            'vertices': poli,
            'tamanos': tamanos,
            'n_poligonos': len(reg['poligonos']),
        })

    # ---------- Casos de carga ----------
    cargas_dist = []
    for (tag, ni, nj, lev, ix, iy) in topo['vigas_x']:
        reg = trib[('X', ix, iy)]
        cargas_dist.append({
            'elemento': tag, 'wy': 0.0,
            'wz': round(-at.carga_lineal(M.Q_G, reg['area'], reg['luz']), 6),
            'wx': 0.0})
    for (tag, ni, nj, lev, ix, iy) in topo['vigas_y']:
        reg = trib[('Y', ix, iy)]
        cargas_dist.append({
            'elemento': tag, 'wy': 0.0,
            'wz': round(-at.carga_lineal(M.Q_G, reg['area'], reg['luz']), 6),
            'wx': 0.0})

    modelo = {
        'info': {
            'descripcion': 'Edificio de Ingenieria UANDES - Semana 2',
            'unidades': 'm, kN, kPa',
            'caso_precalculado': 'G',
            'nota': ('Ejes locales calculados en Python (OpenSees manda). '
                     'Areas tributarias por bisectrices a 45 grados.'),
        },
        'material': {'fpc_MPa': M.FPC, 'poisson': M.POISSON, 'gamma': M.GAMMA},
        'secciones': secciones,
        'nodos': nodos,
        'elementos': elementos,
        'diafragmas': diafragmas,
        'brazos_rigidos': [],
        'areas_tributarias': tributarias,
        'casos_de_carga': [{
            'nombre': 'G',
            'descripcion': 'Peso propio + losa + terminaciones (q_G por areas tributarias)',
            'cargas_nodales': [],
            'cargas_distribuidas': cargas_dist,
        }],
        'resumen': {
            'n_nodos': len(nodos),
            'n_elementos': len(elementos),
            'n_columnas': len(topo['columnas']),
            'n_vigas': len(topo['vigas_x']) + len(topo['vigas_y']),
            'n_muros': len(topo['muros']),
            'n_apoyos': len(topo['apoyos']),
            'n_diafragmas': len(topo['diafragmas']),
            'area_planta_m2': round(M.AREA_PLANTA, 4),
            'qG_kNm2': M.Q_G,
            'carga_losa_por_piso_kN': round(M.Q_G * M.AREA_PLANTA, 4),
            'carga_total_G_kN': round(carga_G, 4),
            'suma_reacciones_kN': round(sumRz, 4),
            'error_equilibrio_kN': round(abs(carga_G - sumRz), 12),
        },
    }

    salida = os.path.join(_RAIZ, 'data', 'modelo_unity.json')
    with open(salida, 'w', encoding='utf-8') as f:
        json.dump(modelo, f, indent=1, ensure_ascii=False)
    print(f"\nEscrito {salida}")
    print(f"  {len(nodos)} nodos | {len(elementos)} elementos | "
          f"{len(tributarias)} areas tributarias")

    # Copia a StreamingAssets para que Unity lo lea directo.
    destino = os.path.join(_RAIZ, 'unity', 'Assets', 'StreamingAssets',
                           'modelo_unity.json')
    if os.path.isdir(os.path.dirname(destino)):
        with open(destino, 'w', encoding='utf-8') as f:
            json.dump(modelo, f, indent=1, ensure_ascii=False)
        print(f"  copiado a {destino}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
