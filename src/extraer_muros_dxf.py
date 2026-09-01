# -*- coding: utf-8 -*-
r"""
================================================================
 extraer_muros_dxf.py  -  MUROS DESDE EL PLANO REAL
================================================================
 Lee la capa RLE-MURO del plano de planta y produce data/muros.json,
 que es lo que consume modelo_edificio.py.

 Asi la geometria de los muros es TRAZABLE al plano: no esta escrita
 a mano en el codigo, sale del DXF y se puede regenerar.

 ----------------------------------------------------------------
 COMO ESTA DIBUJADO UN MURO EN EL PLANO
 ----------------------------------------------------------------
 Un muro no se dibuja como una linea, sino como sus DOS CARAS: dos
 segmentos paralelos separados por el espesor.

       cara 1  ---------------------------
                                            } espesor
       cara 2  ---------------------------

 Para modelarlo como "columna ancha" necesitamos el EJE (la linea
 media) y el ESPESOR, asi que hay que emparejar las caras:

   1. se agrupan los segmentos por direccion (paralelos);
   2. dentro de cada grupo se buscan pares separados por una
      distancia chica (entre 10 y 60 cm: el rango de espesores de
      muro razonables);
   3. el par debe SOLAPARSE longitudinalmente (si no, son dos muros
      distintos alineados, no las dos caras de uno).

 El eje resultante es el promedio de las dos caras y el espesor la
 distancia entre ellas.

 ----------------------------------------------------------------
 UNIDADES
 ----------------------------------------------------------------
 El DXF esta en CENTIMETROS (convencion de los planos). Todo se
 convierte a METROS al leer, para no arrastrar el error.

 Correr:  python src/extraer_muros_dxf.py
================================================================
"""
import json
import math
import os
import sys

import ezdxf

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)

# El plano de planta con las capas estructurales (RLE-*).
PLANO = os.path.join(_RAIZ, '..', 'P1A1_Grupo_7', 'Planos', '2017_67-100.dxf')
CAPA_MURO = 'RLE-MURO'

CM_A_M = 0.01

# Espesores de muro plausibles (m). Fuera de este rango, el par de
# lineas no es un muro (puede ser una cota, un detalle, un mueble).
ESPESOR_MIN = 0.10
ESPESOR_MAX = 0.60

# Largo minimo para considerarlo muro estructural (m). Los tramos muy
# cortos suelen ser detalles de dibujo, no muros.
LARGO_MIN = 1.0

# Ventana de la planta modelada (m). Fuera de esto hay otros sectores
# del plano que no forman parte del modelo.
X_MIN, X_MAX = 8.02, 53.02
Y_MIN, Y_MAX = 46.92, 72.75
MARGEN = 1.0


# ============================================================
def segmentos_de_capa(ruta, capa):
    """Devuelve los segmentos (x1,y1,x2,y2) de una capa, en metros."""
    try:
        doc = ezdxf.readfile(ruta)
    except Exception:
        from ezdxf import recover
        doc, _ = recover.readfile(ruta)

    segs = []

    def agregar(x1, y1, x2, y2):
        segs.append((x1 * CM_A_M, y1 * CM_A_M, x2 * CM_A_M, y2 * CM_A_M))

    def procesar(e):
        t = e.dxftype()
        if t == 'LINE':
            a, b = e.dxf.start, e.dxf.end
            agregar(a.x, a.y, b.x, b.y)
        elif t == 'LWPOLYLINE':
            pts = [(p[0], p[1]) for p in e.get_points()]
            if getattr(e, 'closed', False) and len(pts) > 2:
                pts.append(pts[0])
            for p, q in zip(pts[:-1], pts[1:]):
                agregar(p[0], p[1], q[0], q[1])
        elif t == 'POLYLINE':
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            for p, q in zip(pts[:-1], pts[1:]):
                agregar(p[0], p[1], q[0], q[1])

    for e in doc.modelspace():
        if e.dxftype() == 'INSERT':
            try:
                for sub in e.virtual_entities():
                    if sub.dxf.layer.endswith(capa):
                        procesar(sub)
            except Exception:
                pass
        elif e.dxf.layer.endswith(capa):
            procesar(e)

    return segs


# ============================================================
def _largo(s):
    return math.hypot(s[2] - s[0], s[3] - s[1])


def _direccion(s):
    """Vector unitario del segmento, normalizado a semiplano superior
    para que una linea y la misma al reves caigan en el mismo grupo."""
    dx, dy = s[2] - s[0], s[3] - s[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return (0.0, 0.0)
    dx, dy = dx / L, dy / L
    if dy < -1e-9 or (abs(dy) <= 1e-9 and dx < 0):
        dx, dy = -dx, -dy
    return (dx, dy)


def _proy(s, d):
    """Proyecciones de los extremos sobre la direccion d (para ver
    si dos segmentos se solapan a lo largo)."""
    t1 = s[0] * d[0] + s[1] * d[1]
    t2 = s[2] * d[0] + s[3] * d[1]
    return (min(t1, t2), max(t1, t2))


def _dist_perpendicular(s1, s2, d):
    """Distancia perpendicular entre dos rectas paralelas."""
    nx, ny = -d[1], d[0]
    c1 = s1[0] * nx + s1[1] * ny
    c2 = s2[0] * nx + s2[1] * ny
    return abs(c1 - c2)


def _angulo(s):
    """Angulo de la recta en [0, pi): una linea y la misma al reves dan
    el mismo valor."""
    ang = math.atan2(s[3] - s[1], s[2] - s[0]) % math.pi
    return ang


def emparejar_caras(segs, tol_ang=math.radians(1.0)):
    """
    Empareja segmentos paralelos y proximos: cada par son las dos
    caras de un muro. Devuelve la lista de muros con eje y espesor.

    Se comparan TODOS los segmentos contra todos (son pocos) usando
    una tolerancia angular, en vez de agrupar por direccion redondeada.
    Redondear la direccion metia dos caras del mismo muro en grupos
    distintos cuando el CAD las dejaba con una decima de grado de
    diferencia, y entonces cada una se emparejaba con otra linea: salia
    el mismo muro dos veces con espesores distintos.

    Cada cara se usa UNA sola vez (indice global en `usados`).
    """
    utiles = [s for s in segs if _largo(s) >= LARGO_MIN]
    # El mas largo primero: los muros principales se emparejan antes de
    # que un tramo corto les robe una cara.
    utiles.sort(key=_largo, reverse=True)

    angs = [_angulo(s) for s in utiles]
    muros = []
    usados = set()

    for i, s1 in enumerate(utiles):
        if i in usados:
            continue
        d = _direccion(s1)
        mejor = mejor_e = mejor_j = None

        for j in range(len(utiles)):
            if j == i or j in usados:
                continue
            # Paralelas dentro de la tolerancia (ojo con el salto 0/pi).
            da = abs(angs[i] - angs[j]) % math.pi
            da = min(da, math.pi - da)
            if da > tol_ang:
                continue

            s2 = utiles[j]
            e = _dist_perpendicular(s1, s2, d)
            if not (ESPESOR_MIN <= e <= ESPESOR_MAX):
                continue

            # Deben solaparse a lo largo; si no, son muros distintos
            # alineados uno tras otro, no las dos caras de uno.
            a1, b1 = _proy(s1, d)
            a2, b2 = _proy(s2, d)
            solape = min(b1, b2) - max(a1, a2)
            if solape < LARGO_MIN * 0.5:
                continue

            # Ante varias candidatas, la cara opuesta es la MAS CERCANA:
            # cualquier otra paralela mas lejos es otro muro.
            if mejor is None or e < mejor_e:
                mejor, mejor_e, mejor_j = s2, e, j

        if mejor is None:
            continue

        usados.add(i)
        usados.add(mejor_j)

        # Eje = promedio de las dos caras, recortado al tramo comun.
        a1, b1 = _proy(s1, d)
        a2, b2 = _proy(mejor, d)
        t0, t1 = max(a1, a2), min(b1, b2)

        nx, ny = -d[1], d[0]
        c = ((s1[0] * nx + s1[1] * ny) + (mejor[0] * nx + mejor[1] * ny)) / 2.0
        x1, y1 = d[0] * t0 + nx * c, d[1] * t0 + ny * c
        x2, y2 = d[0] * t1 + nx * c, d[1] * t1 + ny * c

        muros.append({
            'x1': round(x1, 3), 'y1': round(y1, 3),
            'x2': round(x2, 3), 'y2': round(y2, 3),
            'espesor': round(mejor_e, 3),
            'largo': round(math.hypot(x2 - x1, y2 - y1), 3),
        })

    return muros


def dentro_de_planta(m):
    """Descarta muros fuera de la ventana de planta modelada."""
    for x, y in ((m['x1'], m['y1']), (m['x2'], m['y2'])):
        if not (X_MIN - MARGEN <= x <= X_MAX + MARGEN):
            return False
        if not (Y_MIN - MARGEN <= y <= Y_MAX + MARGEN):
            return False
    return True


def orientacion(m):
    dx, dy = abs(m['x2'] - m['x1']), abs(m['y2'] - m['y1'])
    if dy < 0.05 * max(dx, 1e-9):
        return 'X'
    if dx < 0.05 * max(dy, 1e-9):
        return 'Y'
    return 'oblicuo'


# ============================================================
def main():
    ruta = os.path.abspath(PLANO)
    if not os.path.exists(ruta):
        print(f"No encuentro el plano: {ruta}")
        return 1

    print(f"Leyendo {os.path.basename(ruta)}, capa {CAPA_MURO} ...")
    segs = segmentos_de_capa(ruta, CAPA_MURO)
    print(f"  segmentos en la capa      : {len(segs)}")
    print(f"  con largo >= {LARGO_MIN} m       : "
          f"{sum(1 for s in segs if _largo(s) >= LARGO_MIN)}")

    muros = emparejar_caras(segs)
    print(f"  pares de caras emparejados: {len(muros)}")

    muros = [m for m in muros if dentro_de_planta(m)]
    print(f"  dentro de la planta       : {len(muros)}")

    muros.sort(key=lambda m: -m['largo'])
    for k, m in enumerate(muros, 1):
        m['id'] = f"M{k}"
        m['orientacion'] = orientacion(m)
        m['desde_nivel'] = 1
        m['hasta_nivel'] = 8

    print(f"\n{'id':<5}{'x1':>9}{'y1':>9}{'x2':>9}{'y2':>9}"
          f"{'largo':>8}{'esp':>7}  orient")
    print("-" * 68)
    for m in muros:
        print(f"{m['id']:<5}{m['x1']:>9.2f}{m['y1']:>9.2f}{m['x2']:>9.2f}"
              f"{m['y2']:>9.2f}{m['largo']:>8.2f}{m['espesor']:>7.2f}"
              f"  {m['orientacion']}")

    salida = os.path.join(_RAIZ, 'data', 'muros.json')
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    with open(salida, 'w', encoding='utf-8') as f:
        json.dump({
            'fuente': os.path.basename(ruta),
            'capa': CAPA_MURO,
            'unidades': 'm',
            'nota': ('Ejes y espesores obtenidos emparejando las dos caras '
                     'dibujadas de cada muro. Ver src/extraer_muros_dxf.py.'),
            'muros': muros,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nEscrito: {salida}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
