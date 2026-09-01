# -*- coding: utf-8 -*-
r"""
================================================================
 verificar_lab2.py  -  LAS 5 VERIFICACIONES QUE PIDE EL LAB 2
================================================================
   1. carga total de losa por piso
   2. suma de areas tributarias
   3. conservacion de carga
   4. equilibrio global
   5. compatibilidad del diafragma

 Correr:  python verificar_lab2.py

 Devuelve codigo de salida 1 si alguna falla, para que se pueda usar
 en CI o antes de un commit.
================================================================
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

import openseespy.opensees as ops          # noqa: E402

import areas_tributarias as at             # noqa: E402
import modelo_edificio as M                # noqa: E402

fallos = []


def check(cond, titulo, detalle=""):
    marca = "OK  " if cond else "FALLA"
    print(f"  [{marca}] {titulo}")
    if detalle:
        print(f"         {detalle}")
    if not cond:
        fallos.append(titulo)


def titulo(n, texto):
    print("\n" + "=" * 68)
    print(f" {n}. {texto}")
    print("=" * 68)


# ============================================================
titulo(1, "CARGA TOTAL DE LOSA POR PISO")
# ============================================================
# La carga de losa de un piso debe ser q_G por el area de planta.
# Es el numero contra el que se compara todo lo demas.
carga_losa_piso = M.Q_G * M.AREA_PLANTA
pisos_cargados = M.nNiveles - 1

print(f"  q_G            = {M.Q_G:.4f} kN/m2"
      f"  (losa {M.GAMMA}*{M.ESPESOR_LOSA} + terminaciones {M.TERMINACIONES})")
print(f"  area de planta = {M.AREA_PLANTA:.4f} m2")
print(f"  carga por piso = {carga_losa_piso:.4f} kN")
print(f"  pisos cargados = {pisos_cargados}")
print(f"  carga de losa total = {carga_losa_piso * pisos_cargados:.4f} kN")

check(carga_losa_piso > 0, "la carga de piso es positiva y esta definida")


# ============================================================
titulo(2, "SUMA DE AREAS TRIBUTARIAS")
# ============================================================
# Las zonas tributarias parten el piso sin huecos ni solapes: su suma
# tiene que dar exactamente el area de planta.
trib = M.tributarias_por_viga()
suma_areas = sum(r['area'] for r in trib.values())
err_area = abs(suma_areas - M.AREA_PLANTA)

print(f"  vigas con area tributaria = {len(trib)}")
print(f"  suma de areas tributarias = {suma_areas:.6f} m2")
print(f"  area de planta            = {M.AREA_PLANTA:.6f} m2")

check(err_area < 1e-9,
      "suma de areas tributarias = area de planta",
      f"error {err_area:.3e} m2")

# Ninguna viga puede quedarse sin area: si pasa, es un bug de indices
# y esa viga estaria descargada en silencio.
sin_area = [k for k, r in trib.items() if r['area'] <= 0.0]
check(not sin_area, "todas las vigas reciben area tributaria",
      f"vigas sin area: {len(sin_area)}")

# Contraste explicito contra el reparto 50/50 de la Semana 1.
print("\n  Comparacion con el reparto 50/50 (pano mas alargado):")
peor_clave, peor_dif = None, 0.0
for (tipo, ix, iy), reg in trib.items():
    if tipo == 'X':
        pano = (M.EJES_X[ix + 1] - M.EJES_X[ix])
    else:
        pano = (M.EJES_Y[iy + 1] - M.EJES_Y[iy])
    dif = abs(reg['area'] - pano * reg['luz'] / 2.0)
    if dif > peor_dif:
        peor_dif, peor_clave = dif, (tipo, ix, iy)
print(f"    mayor discrepancia en la viga {peor_clave}: {peor_dif:.3f} m2")
print("    -> el equilibrio global NO detecta esta diferencia (ver punto 4)")


# ============================================================
titulo(3, "CONSERVACION DE CARGA  (q*A = w*L)")
# ============================================================
# Cada viga debe recibir exactamente la carga de su area tributaria.
peor = 0.0
for clave, reg in trib.items():
    w = at.carga_lineal(M.Q_G, reg['area'], reg['luz'])
    peor = max(peor, abs(w * reg['luz'] - M.Q_G * reg['area']))

check(peor < 1e-9, "viga por viga: w*L = q*A", f"peor error {peor:.3e} kN")

transferida = sum(
    at.carga_lineal(M.Q_G, r['area'], r['luz']) * r['luz'] for r in trib.values())
err_cons = abs(transferida - carga_losa_piso)
print(f"  carga de losa del piso      = {carga_losa_piso:.6f} kN")
print(f"  carga transferida a vigas   = {transferida:.6f} kN")
check(err_cons < 1e-8, "la losa no pierde ni gana carga al bajar a las vigas",
      f"error {err_cons:.3e} kN")


# ============================================================
titulo(4, "EQUILIBRIO GLOBAL")
# ============================================================
topo = M.construir_modelo()
print(f"  columnas {len(topo['columnas'])} | vigas X {len(topo['vigas_x'])} | "
      f"vigas Y {len(topo['vigas_y'])} | muros {len(topo['muros'])}")
print(f"  apoyos {len(topo['apoyos'])} | diafragmas {len(topo['diafragmas'])}")

M.nuevo_patron()
aplicada = M.aplicar_carga_gravitacional(topo, M.Q_G, incluir_peso_propio=True)
ok = M.resolver()
check(ok == 0, "el analisis converge")

sumRz = sum(ops.nodeReaction(n, 3) for n in topo['apoyos'])
err_eq = abs(aplicada - sumRz)
print(f"  carga aplicada G        = {aplicada:.6f} kN")
print(f"  suma de reacciones Rz   = {sumRz:.6f} kN")
check(err_eq < 1e-6, "sum(F aplicadas) = sum(R)", f"error {err_eq:.3e} kN")

uz_max = min(ops.nodeDisp(n, 3) for n in topo['coords'])
print(f"  UZ maximo (descenso)    = {uz_max*1000:.4f} mm")
check(abs(uz_max) < 0.10,
      "el descenso maximo tiene orden de magnitud razonable (< 100 mm)",
      f"UZ = {uz_max*1000:.3f} mm")


# ============================================================
titulo(5, "COMPATIBILIDAD DEL DIAFRAGMA")
# ============================================================
r"""
Un diafragma rigido NO obliga a que todos los nodos del piso tengan
el mismo ux. El piso se mueve como cuerpo rigido EN SU PLANO, y con
carga excentrica ademas ROTA. Lo que debe cumplirse es:

    rz_i = rz_m                        (mismo giro)
    ux_i = ux_m - rz*(y_i - y_m)
    uy_i = uy_m + rz*(x_i - x_m)

Confundir esto con "todos los ux iguales" es un error facil: hace
parecer que el diafragma no funciona cuando si lo hace. Por eso se
verifica con una carga LATERAL, que es la que hace rotar el piso;
bajo gravedad pura el giro es ~0 y la prueba no probaria nada.
"""
topo = M.construir_modelo()
M.nuevo_patron()

# Carga lateral en X, triangulo invertido, aplicada en un solo borde
# del piso para que sea EXCENTRICA y el diafragma tenga que rotar.
for lev in range(1, M.nNiveles):
    F = 10.0 * lev
    ops.load(M.id_nodo(lev, 0, 0), F, 0.0, 0.0, 0.0, 0.0, 0.0)

ok = M.resolver()
check(ok == 0, "el analisis lateral converge")

peor_ux = peor_uy = peor_rz = 0.0
giro_maximo = 0.0

for lev in range(1, M.nNiveles):
    maestro = M.id_maestro(lev)
    xm, ym, _ = topo['coords'][maestro]
    ux_m = ops.nodeDisp(maestro, 1)
    uy_m = ops.nodeDisp(maestro, 2)
    rz_m = ops.nodeDisp(maestro, 6)
    giro_maximo = max(giro_maximo, abs(rz_m))

    for ix in range(M.nX):
        for iy in range(M.nY):
            n = M.id_nodo(lev, ix, iy)
            xi, yi, _ = topo['coords'][n]
            ux_esp = ux_m - rz_m * (yi - ym)
            uy_esp = uy_m + rz_m * (xi - xm)
            peor_ux = max(peor_ux, abs(ops.nodeDisp(n, 1) - ux_esp))
            peor_uy = max(peor_uy, abs(ops.nodeDisp(n, 2) - uy_esp))
            peor_rz = max(peor_rz, abs(ops.nodeDisp(n, 6) - rz_m))

print(f"  giro rz maximo de piso      = {giro_maximo:.6e} rad")
print(f"  peor error en ux            = {peor_ux:.3e} m")
print(f"  peor error en uy            = {peor_uy:.3e} m")
print(f"  peor error en rz            = {peor_rz:.3e} rad")

check(peor_ux < 1e-9 and peor_uy < 1e-9,
      "los nodos del piso cumplen el movimiento de cuerpo rigido")
check(peor_rz < 1e-12, "todos los nodos del piso comparten el giro rz")
check(giro_maximo > 1e-12,
      "el piso SI rota (la prueba es significativa, no trivial)",
      f"rz = {giro_maximo:.3e} rad")


# ============================================================
print("\n" + "=" * 68)
if fallos:
    print(f" FALLARON {len(fallos)} VERIFICACIONES:")
    for f in fallos:
        print("   -", f)
    print("=" * 68)
    sys.exit(1)
print(" LAS 5 VERIFICACIONES DEL LAB 2 PASARON")
print("=" * 68)
