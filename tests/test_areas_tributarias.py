# -*- coding: utf-8 -*-
"""
Tests del reparto de losa por areas tributarias.

Estos tests existen porque el EQUILIBRIO GLOBAL NO VALIDA EL REPARTO:
si le das el doble de carga a una viga y la mitad a otra, la suma de
reacciones sigue cerrando con error 1e-14. Lo unico que detecta un
reparto mal hecho es verificar la geometria del reparto en si.

Correr:  python tests/test_areas_tributarias.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from areas_tributarias import (          # noqa: E402
    area_poligono,
    area_tributaria_viga,
    poligonos_pano,
    repartir_piso,
    carga_lineal,
)

TOL = 1e-9
fallos = []


def check(condicion, mensaje):
    if condicion:
        print(f"  OK   {mensaje}")
    else:
        print(f"  FALLA {mensaje}")
        fallos.append(mensaje)


def casi(a, b, tol=TOL):
    return abs(a - b) <= tol * max(1.0, abs(b))


# ============================================================
print("\n[1] Formula del cordon (shoelace) contra areas conocidas")
# ============================================================
check(casi(area_poligono([(0, 0), (4, 0), (4, 3), (0, 3)]), 12.0),
      "rectangulo 4x3 -> 12 m2")
check(casi(area_poligono([(0, 0), (4, 0), (0, 3)]), 6.0),
      "triangulo base 4 altura 3 -> 6 m2")
check(casi(area_poligono([(0, 0), (10, 0), (7, 2), (3, 2)]), 14.0),
      "trapecio 10 y 4, altura 2 -> 14 m2")
# El orden inverso (horario) debe dar el mismo valor absoluto.
check(casi(area_poligono([(0, 3), (4, 3), (4, 0), (0, 0)]), 12.0),
      "rectangulo recorrido al reves -> mismo area")


# ============================================================
print("\n[2] Conservacion en un pano: las 4 zonas suman el pano entero")
# ============================================================
PANOS = [
    (4.0, 4.0),    # cuadrado (caso del benchmark de Semana 1)
    (6.0, 4.0),
    (10.0, 3.34),  # pano real de este edificio: muy alargado
    (3.30, 3.34),  # pano real casi cuadrado
    (10.0, 5.02),
    (5.0, 7.53),   # mas alto que ancho -> cumbrera gira 90 grados
    (1.0, 20.0),   # extremo
    (20.0, 1.0),   # extremo, al reves
]

for Lx, Ly in PANOS:
    polis = poligonos_pano(0.0, 0.0, Lx, Ly)
    suma = sum(area_poligono(p) for p in polis.values())
    check(casi(suma, Lx * Ly),
          f"pano {Lx} x {Ly}: suma zonas = {suma:.6f} = area {Lx*Ly:.6f}")


# ============================================================
print("\n[3] El poligono y la formula analitica deben coincidir")
# ============================================================
for Lx, Ly in PANOS:
    polis = poligonos_pano(0.0, 0.0, Lx, Ly)
    # Vigas que corren en X: luz Lx, transversal Ly
    a_poli = area_poligono(polis['y0'])
    a_form = area_tributaria_viga(Lx, Ly)
    check(casi(a_poli, a_form),
          f"pano {Lx}x{Ly} viga X: poligono {a_poli:.6f} = formula {a_form:.6f}")

    # Vigas que corren en Y: luz Ly, transversal Lx
    a_poli = area_poligono(polis['x0'])
    a_form = area_tributaria_viga(Ly, Lx)
    check(casi(a_poli, a_form),
          f"pano {Lx}x{Ly} viga Y: poligono {a_poli:.6f} = formula {a_form:.6f}")


# ============================================================
print("\n[4] Simetria: las dos vigas opuestas de un pano son iguales")
# ============================================================
for Lx, Ly in PANOS:
    polis = poligonos_pano(0.0, 0.0, Lx, Ly)
    check(casi(area_poligono(polis['y0']), area_poligono(polis['y1'])),
          f"pano {Lx}x{Ly}: vigas X opuestas iguales")
    check(casi(area_poligono(polis['x0']), area_poligono(polis['x1'])),
          f"pano {Lx}x{Ly}: vigas Y opuestas iguales")


# ============================================================
print("\n[5] Pano cuadrado: las 4 vigas reciben exactamente A/4")
# ============================================================
L = 5.0
polis = poligonos_pano(0.0, 0.0, L, L)
for borde, p in polis.items():
    check(casi(area_poligono(p), L * L / 4.0),
          f"pano cuadrado {L}x{L}, borde {borde} -> L^2/4 = {L*L/4:.4f}")


# ============================================================
print("\n[6] Conservacion sobre una malla completa (los ejes reales)")
# ============================================================
EJES_X = [8.02, 11.32, 14.72, 18.02, 28.02, 38.02, 48.02, 53.02]
EJES_Y = [46.92, 50.26, 55.20, 60.20, 65.22, 72.75]

trib = repartir_piso(EJES_X, EJES_Y)
suma_areas = sum(r['area'] for r in trib.values())
area_planta = (EJES_X[-1] - EJES_X[0]) * (EJES_Y[-1] - EJES_Y[0])

check(casi(suma_areas, area_planta, tol=1e-9),
      f"suma de areas tributarias {suma_areas:.6f} = area de planta "
      f"{area_planta:.6f} m2")

# Cada viga debe tener area > 0: una viga sin area tributaria es una
# viga que quedo sin carga, y eso normalmente es un bug de indices.
sin_area = [k for k, r in trib.items() if r['area'] <= 0.0]
check(len(sin_area) == 0,
      f"todas las vigas reciben area (sin area: {len(sin_area)})")

# Vigas interiores vs de borde: una interior toca 2 panos.
interiores = [k for k, r in trib.items() if len(r['poligonos']) == 2]
bordes = [k for k, r in trib.items() if len(r['poligonos']) == 1]
check(len(interiores) > 0 and len(bordes) > 0,
      f"hay vigas interiores ({len(interiores)}) y de borde ({len(bordes)})")


# ============================================================
print("\n[7] Conservacion de carga: q*A = w*L viga por viga")
# ============================================================
q_G = 7.75      # kN/m2
peor = 0.0
for clave, reg in trib.items():
    w = carga_lineal(q_G, reg['area'], reg['luz'])
    transferida = w * reg['luz']
    esperada = q_G * reg['area']
    peor = max(peor, abs(transferida - esperada))
check(peor < 1e-10,
      f"conservacion viga a viga: peor error {peor:.3e} kN")

carga_total_losa = q_G * area_planta
carga_total_vigas = sum(
    carga_lineal(q_G, r['area'], r['luz']) * r['luz'] for r in trib.values())
check(casi(carga_total_vigas, carga_total_losa, tol=1e-9),
      f"carga total: losa {carga_total_losa:.4f} kN = vigas "
      f"{carga_total_vigas:.4f} kN")


# ============================================================
print("\n[8] El reparto 50/50 SI se diferencia del de 45 grados")
# ============================================================
# Este test protege contra volver atras al reparto crudo. Si alguien
# reemplaza el metodo por 50/50 y los tests siguen pasando, es que no
# estabamos verificando nada.
Lx, Ly = 10.0, 3.34
a_larga_45 = area_tributaria_viga(Lx, Ly)
a_corta_45 = area_tributaria_viga(Ly, Lx)
a_5050 = Lx * Ly / 4.0
check(abs(a_larga_45 - a_5050) / a_5050 > 0.30,
      f"pano alargado: 45 grados da {a_larga_45:.3f} m2 a la viga larga "
      f"vs {a_5050:.3f} del 50/50 (difieren >30%)")
check(casi(2 * a_larga_45 + 2 * a_corta_45, Lx * Ly),
      "pero el de 45 grados igual conserva el area total")


# ============================================================
print("\n[9] Entradas invalidas fallan con mensaje, no en silencio")
# ============================================================
for mala in [(0.0, 4.0), (-1.0, 4.0), (4.0, 0.0)]:
    try:
        area_tributaria_viga(*mala)
        check(False, f"luz invalida {mala} deberia lanzar ValueError")
    except ValueError:
        check(True, f"luz invalida {mala} lanza ValueError")

try:
    poligonos_pano(0.0, 0.0, 0.0, 5.0)
    check(False, "pano de ancho cero deberia lanzar ValueError")
except ValueError:
    check(True, "pano de ancho cero lanza ValueError")


# ============================================================
print("\n" + "=" * 60)
if fallos:
    print(f"FALLARON {len(fallos)} verificaciones:")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print("TODOS LOS TESTS DE AREAS TRIBUTARIAS PASARON")
print("=" * 60)
