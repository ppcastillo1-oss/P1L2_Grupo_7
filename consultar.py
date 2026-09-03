# -*- coding: utf-8 -*-
r"""
================================================================
 consultar.py  -  PREGUNTARLE AL MODELO POR UN ELEMENTO
================================================================
 Resuelve el caso G y contesta, para la barra que se le pida:
 sus nodos, su seccion, cuanto bajan sus extremos, sus esfuerzos
 internos en EJES LOCALES y el area tributaria de losa que le llega.

 Correr:

   python consultar.py 389            una barra por su elementTag
   python consultar.py --nodo 220     un nodo por su tag
   python consultar.py --en 27.3 18.2 3.91
                                      la barra mas cercana a un punto
   python consultar.py --peores 15    las 15 barras que mas bajan
   python consultar.py --nivel 3.91   todas las barras de un piso

 ----------------------------------------------------------------
 POR QUE eleResponse Y NO eleForce
 ----------------------------------------------------------------
 `ops.eleForce(tag)` devuelve las fuerzas en ejes GLOBALES, no
 locales. Para una viga que corre en X el eje local x coincide con el
 global X, asi que leer eleForce con etiquetas locales PARECE
 funcionar. Para una viga que corre en Y, el momento de gravedad
 aparece en la casilla Mx global -- y leerlo como "torsion" hace
 creer que la viga no flecta y que el modelo esta malo. No lo esta.

 Lo correcto es:
     ops.eleResponse(tag, 'localForce')
     -> [N_i, Vy_i, Vz_i, T_i, My_i, Mz_i,
         N_j, Vy_j, Vz_j, T_j, My_j, Mz_j]

 Bajo gravedad, en una viga con vecxz = (0,0,1): el cortante
 vertical esta en Vz (indice 2) y el momento flector en My
 (indices 4 y 10).
================================================================
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

import openseespy.opensees as ops          # noqa: E402

import modelo_edificio as M                # noqa: E402

GDL = ('ux', 'uy', 'uz', 'rx', 'ry', 'rz')


# ============================================================
def resolver_g():
    """Arma el modelo y resuelve el caso G. Devuelve la topologia."""
    topo = M.construir_modelo()
    M.nuevo_patron()
    carga = M.aplicar_carga_gravitacional(topo)
    if M.resolver() != 0:
        raise RuntimeError('el analisis no convergio')
    return topo, carga


def tipo_de(tag, topo):
    for nombre in ('columnas', 'vigas_x', 'vigas_y', 'muros', 'brazos'):
        for t, _n1, _n2 in topo[nombre]:
            if t == tag:
                return nombre
    return '?'


def nodos_de(tag, topo):
    for nombre in ('columnas', 'vigas_x', 'vigas_y', 'muros', 'brazos'):
        for t, n1, n2 in topo[nombre]:
            if t == tag:
                return n1, n2
    return None


def seccion_de(tag):
    """El nombre de la seccion de una barra, buscando en el modelo."""
    m = M.MODELO
    for t, _n1, _n2, sec, _v, _tipo, _p in m.verticales:
        if t == tag:
            return sec
    for t, _n1, _n2, sec, _L, _p, _k in m.vigas:
        if t == tag:
            return sec
    for t, _n1, _n2, sec, _L, _k in m.brazos:
        if t == tag:
            return sec
    return None


# ============================================================
def mostrar_nodo(n, sangria='  '):
    x, y, z = ops.nodeCoord(n)
    d = ops.nodeDisp(n)
    print('%snodo %-4d (%8.3f, %8.3f, %8.3f)' % (sangria, n, x, y, z))
    print('%s   ux = %+9.4f mm   uy = %+9.4f mm   uz = %+9.4f mm'
          % (sangria, d[0] * 1000, d[1] * 1000, d[2] * 1000))
    print('%s   rx = %+9.2e      ry = %+9.2e      rz = %+9.2e  rad'
          % (sangria, d[3], d[4], d[5]))


def mostrar_barra(tag, topo):
    par = nodos_de(tag, topo)
    if par is None:
        print('No existe la barra %d.' % tag)
        return
    n1, n2 = par
    tipo = tipo_de(tag, topo)
    sec = seccion_de(tag)

    print('=' * 68)
    print(' BARRA %d   (%s)' % (tag, tipo))
    print('=' * 68)

    if sec is not None:
        print('  seccion  %-14s  b = %.2f m   h = %.2f m' % (sec.nombre, sec.b, sec.h))
        print('           A = %.4f m2   Iy = %.6f   Iz = %.6f   J = %.6f m4'
              % (sec.A, sec.Iy, sec.Iz, sec.J))

    a, b = ops.nodeCoord(n1), ops.nodeCoord(n2)
    L = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5
    print('  largo    %.4f m' % L)
    print()
    print('  DESPLAZAMIENTOS DE SUS EXTREMOS')
    mostrar_nodo(n1, '   ')
    mostrar_nodo(n2, '   ')
    baja = max(abs(ops.nodeDisp(n1, 3)), abs(ops.nodeDisp(n2, 3))) * 1000
    print('   -> el extremo que mas baja: %.4f mm' % baja)

    # --- esfuerzos internos, en EJES LOCALES ---
    try:
        f = ops.eleResponse(tag, 'localForce')
    except Exception:
        f = []
    if len(f) >= 12:
        print()
        print('  ESFUERZOS INTERNOS (ejes LOCALES de la barra)')
        print('     %-8s %14s %14s' % ('', 'extremo i', 'extremo j'))
        print('     %-8s %14.4f %14.4f   kN' % ('N  axial', f[0], f[6]))
        print('     %-8s %14.4f %14.4f   kN' % ('Vy', f[1], f[7]))
        print('     %-8s %14.4f %14.4f   kN' % ('Vz', f[2], f[8]))
        print('     %-8s %14.4f %14.4f   kN*m' % ('T  torsion', f[3], f[9]))
        print('     %-8s %14.4f %14.4f   kN*m' % ('My', f[4], f[10]))
        print('     %-8s %14.4f %14.4f   kN*m' % ('Mz', f[5], f[11]))
        if tipo.startswith('viga'):
            print('     -> bajo gravedad: cortante vertical en Vz, '
                  'momento flector en My')

    # --- area tributaria ---
    trib = M.tributarias_por_viga()
    if tag in trib:
        r = trib[tag]
        print()
        print('  AREA TRIBUTARIA DE LOSA')
        print('     nivel     %+.2f m' % M.NIVELES_Z[r['nivel']])
        print('     area      %.4f m2' % r['area'])
        print('     q         %.4f kN/m2   (del plano de cargas)' % r['q'])
        print('     carga     %.4f kN      = q * A' % r['carga'])
        print('     w         %.4f kN/m    = q * A / L' % r['w'])
        print('     poligonos %d' % len(r['poligonos']))
        err = abs(r['w'] * r['luz'] - r['q'] * r['area'])
        print('     w*L = q*A ->  error %.2e kN' % err)
    else:
        print()
        print('  Esta barra no recibe carga de losa '
              '(es vertical, o es un brazo sin area).')


# ============================================================
def peores(topo, cuantas=15):
    """Las barras cuyo extremo baja mas. Para cazar zonas sin apoyo."""
    filas = []
    for nombre in ('vigas_x', 'vigas_y'):
        for tag, n1, n2 in topo[nombre]:
            uz = max(abs(ops.nodeDisp(n1, 3)), abs(ops.nodeDisp(n2, 3)))
            x, y, z = ops.nodeCoord(n1)
            filas.append((uz * 1000, tag, nombre, x, y, z))
    filas.sort(reverse=True)
    print('=' * 68)
    print(' LAS %d BARRAS QUE MAS BAJAN  (caso G)' % cuantas)
    print('=' * 68)
    print('  %-6s %-9s %10s   %s' % ('tag', 'tipo', 'uz [mm]', 'en (x, y, z)'))
    for uz, tag, tipo, x, y, z in filas[:cuantas]:
        print('  %-6d %-9s %10.4f   (%7.2f, %7.2f, %+7.2f)'
              % (tag, tipo, uz, x, y, z))


def del_nivel(topo, z):
    """Todas las barras horizontales de un piso."""
    print('=' * 68)
    print(' BARRAS DEL NIVEL %+.2f' % z)
    print('=' * 68)
    print('  %-6s %-9s %8s %10s %10s   %s'
          % ('tag', 'tipo', 'L [m]', 'uz [mm]', 'A [m2]', 'seccion'))
    trib = M.tributarias_por_viga()
    for nombre in ('vigas_x', 'vigas_y', 'brazos'):
        for tag, n1, n2 in topo[nombre]:
            a, b = ops.nodeCoord(n1), ops.nodeCoord(n2)
            if abs(a[2] - z) > 1e-6 or abs(b[2] - z) > 1e-6:
                continue
            L = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5
            uz = max(abs(ops.nodeDisp(n1, 3)), abs(ops.nodeDisp(n2, 3))) * 1000
            sec = seccion_de(tag)
            print('  %-6d %-9s %8.3f %10.4f %10.4f   %s'
                  % (tag, nombre, L, uz, trib.get(tag, {}).get('area', 0.0),
                     sec.nombre if sec else '?'))


def cerca_de(topo, x, y, z):
    """La barra horizontal cuyo centro esta mas cerca de un punto."""
    mejor, dmin = None, None
    for nombre in ('vigas_x', 'vigas_y', 'brazos', 'columnas', 'muros'):
        for tag, n1, n2 in topo[nombre]:
            a, b = ops.nodeCoord(n1), ops.nodeCoord(n2)
            cx, cy, cz = [(a[i] + b[i]) / 2 for i in range(3)]
            d = (cx - x) ** 2 + (cy - y) ** 2 + (cz - z) ** 2
            if dmin is None or d < dmin:
                mejor, dmin = tag, d
    print('La barra mas cercana a (%.2f, %.2f, %.2f) es la %d, a %.3f m.\n'
          % (x, y, z, mejor, dmin ** 0.5))
    return mejor


# ============================================================
def main(argv):
    topo, carga = resolver_g()
    uz_max = min(ops.nodeDisp(n, 3) for n in topo['coords'])
    print('Caso G resuelto.  carga %.2f kN   UZ maximo %.4f mm\n'
          % (carga, uz_max * 1000))

    if not argv:
        print(__doc__.split('----')[0].split('Correr:')[1])
        peores(topo, 10)
        return 0

    if argv[0] == '--peores':
        peores(topo, int(argv[1]) if len(argv) > 1 else 15)
    elif argv[0] == '--nivel':
        del_nivel(topo, float(argv[1]))
    elif argv[0] == '--nodo':
        mostrar_nodo(int(argv[1]), '  ')
    elif argv[0] == '--en':
        tag = cerca_de(topo, float(argv[1]), float(argv[2]), float(argv[3]))
        mostrar_barra(tag, topo)
    else:
        mostrar_barra(int(argv[0]), topo)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
