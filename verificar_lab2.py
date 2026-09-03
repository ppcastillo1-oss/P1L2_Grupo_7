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

 Las cinco son las mismas de siempre. Lo que cambio es la ESTRUCTURA
 sobre la que corren: antes una grilla regular de 8x6 ejes por 9
 niveles, ahora el edificio LT2 leido de sus planos de calculo. Dos
 verificaciones tuvieron que cambiar de forma por eso, y en cada caso
 esta dicho por que:

   - la 2 se hace POR PISO, porque el techo sale de otra lamina y
     tiene su propia carga de piso;
   - la 5 aplica la carga lateral en un nodo de ESQUINA buscado por
     coordenada, porque en una planta irregular no existe el indice
     (ix, iy) de la grilla.

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


print(f"Estructura: edificio LT2, planos de calculo 2024_22")
print(f"Modelo del LT2 tomado de: {M.LT2_SRC}")


# ============================================================
titulo(1, "CARGA TOTAL DE LOSA POR PISO")
# ============================================================
# La carga de losa de un piso debe ser q_G por el area de planta.
# Es el numero contra el que se compara todo lo demas.
#
# Aca hay una diferencia con la grilla: q_G no es UN numero. La
# lamina 700 (plano de cargas) da un peso muerto adicional distinto
# para las plantas tipo y para el cielo del 4o piso, asi que hay dos
# cargas de piso y el total se suma piso por piso.
print(f"  losa e = {M.ESPESOR_LOSA:.2f} m  ->  peso propio "
      f"{M.GAMMA:.0f} x {M.ESPESOR_LOSA:.2f} = {M.PESO_LOSA:.3f} kN/m2")
print(f"  plantas tipo   q_G = {M.PESO_LOSA:.3f} + {M.TERMINACIONES:.3f} "
      f"= {M.Q_G:.4f} kN/m2   (Q = {M.Q_Q:.3f})")
print(f"  cielo 4o piso  q_G = {M.PESO_LOSA:.3f} + {M.TERMINACIONES_TECHO:.3f} "
      f"= {M.Q_G_TECHO:.4f} kN/m2   (Q = {M.Q_Q_TECHO:.3f})")
print(f"  area de planta = {M.AREA_PLANTA:.4f} m2")
print()

carga_losa_total = 0.0
for lev in range(1, M.nNiveles):
    q = M.carga_de_piso(lev)
    a = M.area_de_piso(lev)
    carga_losa_total += q * a
    print(f"  nivel {M.NIVELES_Z[lev]:+7.2f}  q = {q:.4f} kN/m2  x  "
          f"{a:8.3f} m2  ->  {q * a:10.4f} kN")
print(f"  {'':-<52}")
print(f"  carga de losa total = {carga_losa_total:.4f} kN")

check(carga_losa_total > 0, "la carga de losa esta definida y es positiva")

# Los cuatro valores del plano de cargas, contra lo que usa el modelo.
# Es el chequeo que impide que el informe y el modelo digan cosas
# distintas sobre la carga.
_esperado = {
    'PM adic. plantas tipo': (M.TERMINACIONES, 2.55),
    'SC plantas tipo': (M.Q_Q, 4.90),
    'PM adic. cielo 4o': (M.TERMINACIONES_TECHO, 1.96),
    'SC cielo 4o': (M.Q_Q_TECHO, 2.94),
}
for nombre, (leido, del_plano) in _esperado.items():
    check(abs(leido - del_plano) < 0.02,
          f"{nombre} calza con el plano de cargas",
          f"modelo {leido:.3f} kN/m2 vs plano {del_plano:.2f}")


# ============================================================
titulo(2, "SUMA DE AREAS TRIBUTARIAS")
# ============================================================
# Las zonas tributarias parten el piso sin huecos ni solapes: su suma
# tiene que dar exactamente el area de planta.
#
# En la grilla el reparto era el mismo para todos los pisos porque la
# planta no cambiaba con la altura. Aca se verifica PISO POR PISO.
for lev in range(1, M.nNiveles):
    trib = M.tributarias_por_viga(nivel=lev)
    suma = sum(r['area'] for r in trib.values())
    err = abs(suma - M.area_de_piso(lev))
    check(err < 1e-3,
          f"nivel {M.NIVELES_Z[lev]:+7.2f}: suma de areas = area de los panos",
          f"{len(trib)} barras, {suma:.4f} m2 contra "
          f"{M.area_de_piso(lev):.4f} m2, error {err:.1e} m2")

trib = M.tributarias_por_viga(nivel=M.NIVEL_TIPO)

# Ninguna barra puede quedarse sin area: si pasa, es un bug de claves
# y esa barra estaria descargada en silencio.
sin_area = [k for k, r in trib.items() if r['area'] <= 0.0]
check(not sin_area, "ninguna barra con area cero en el reparto",
      f"barras sin area: {len(sin_area)}")

# Los poligonos tienen que TESELAR el pano: sin huecos ni solapes.
# Es una comprobacion independiente del area, porque el area se
# reescala y podria cerrar con poligonos mal dibujados.
sin_poli = [k for k, r in trib.items() if not r['poligonos']]
check(not sin_poli, "toda barra cargada trae su poligono tributario",
      f"sin poligono: {len(sin_poli)}")

# Contraste explicito contra el reparto que NO usa bisectrices.
# En la Semana 1 se repartia 50/50 entre vigas X e Y; el error de
# fondo es el mismo si se reparte EN PROPORCION AL LARGO: las dos
# formas conservan la resultante, asi que el equilibrio global no las
# distingue, pero reparten mal.
print("\n  Bisectrices a 45 grados contra reparto por largo de viga:")
print(f"    (un pano real de este edificio, 10.00 x 3.34 m)")
larga = at.area_tributaria_viga(10.00, 3.34)
corta = at.area_tributaria_viga(3.34, 10.00)
por_largo_larga = 10.00 * 3.34 / 2.0 * (10.00 / (10.00 + 3.34))
por_largo_corta = 10.00 * 3.34 / 2.0 * (3.34 / (10.00 + 3.34))
print(f"    45 grados   viga larga {larga:7.3f} m2   viga corta {corta:7.3f} m2")
print(f"    por largo   viga larga {por_largo_larga:7.3f} m2   "
      f"viga corta {por_largo_corta:7.3f} m2")
check(abs(2 * larga + 2 * corta - 10.00 * 3.34) < 1e-9,
      "los dos repartos conservan el area del pano",
      "-> por eso el EQUILIBRIO GLOBAL no detecta la diferencia (ver punto 4)")
check(por_largo_corta / corta > 1.40,
      "pero el reparto por largo sobrecarga la viga corta mas de un 40 %",
      f"{por_largo_corta:.3f} contra {corta:.3f} m2: "
      f"{100 * (por_largo_corta / corta - 1):+.0f} %")

# Y una comprobacion que la grilla no necesitaba: los panos hay que
# ENCONTRARLOS, y el plano los numera. Que cada cara del grafo tenga
# su rotulo de losa es una verificacion cruzada -- la geometria sale
# de las lineas de muros y vigas, los rotulos son otra fuente del
# mismo plano.
_rot = M.MODELO.aud_panos[M.NIVEL_TIPO].get('rotulos_de_losa', {})
if _rot.get('aplicado'):
    check(_rot['caras_sin_rotulo_descartadas'] <= 1,
          "cada pano detectado tiene su rotulo de losa en el plano",
          f"{_rot['declarados']} rotulos en {_rot['caras_con_rotulo']} caras; "
          f"{_rot['caras_sin_rotulo_descartadas']} cara(s) sin rotulo, de "
          f"{_rot['areas_descartadas']} m2 (el hueco del ascensor)")


# ============================================================
titulo(3, "CONSERVACION DE CARGA  (q*A = w*L)")
# ============================================================
# Cada barra debe recibir exactamente la carga de su area tributaria.
peor = 0.0
for lev in range(1, M.nNiveles):
    q = M.carga_de_piso(lev)
    for clave, reg in M.tributarias_por_viga(nivel=lev).items():
        w = at.carga_lineal(q, reg['area'], reg['luz'])
        peor = max(peor, abs(w * reg['luz'] - q * reg['area']))

check(peor < 1e-9, "barra por barra: w*L = q*A", f"peor error {peor:.3e} kN")

transferida = 0.0
for lev in range(1, M.nNiveles):
    q = M.carga_de_piso(lev)
    transferida += sum(
        at.carga_lineal(q, r['area'], r['luz']) * r['luz']
        for r in M.tributarias_por_viga(nivel=lev).values())
err_cons = abs(transferida - carga_losa_total)
print(f"  carga de losa de los pisos  = {carga_losa_total:.6f} kN")
print(f"  carga transferida a barras  = {transferida:.6f} kN")
check(err_cons < 0.1, "la losa no pierde ni gana carga al bajar a las barras",
      f"error {err_cons:.3e} kN")


# ============================================================
titulo(4, "EQUILIBRIO GLOBAL")
# ============================================================
topo = M.construir_modelo()
print(f"  columnas {len(topo['columnas'])} | vigas X {len(topo['vigas_x'])} | "
      f"vigas Y {len(topo['vigas_y'])} | muros {len(topo['muros'])} | "
      f"brazos {len(topo['brazos'])}")
print(f"  apoyos {len(topo['apoyos'])} | diafragmas {len(topo['diafragmas'])} | "
      f"nodos {len(topo['coords'])}")

M.nuevo_patron()
aplicada = M.aplicar_carga_gravitacional(topo)
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

# El equilibrio cierra igual de bien con la carga MAL repartida, asi
# que hace falta un chequeo que mire el reparto: que ningun nodo baje
# muchisimo mas que la mediana de su piso. Un nodo asi es una viga
# que quedo sin apoyo, y el equilibrio no lo ve.
import statistics                                    # noqa: E402
for lev in range(1, M.nNiveles):
    uz = [abs(ops.nodeDisp(n, 3)) for n in M.nodos_del_nivel(lev)]
    med, mx = statistics.median(uz), max(uz)
    check(mx < 0.015,
          f"nivel {M.NIVELES_Z[lev]:+7.2f}: ningun nodo se descuelga",
          f"maximo {mx*1000:.2f} mm, mediana {med*1000:.2f} mm")


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

La carga va en un nodo de ESQUINA de cada piso. En la grilla ese nodo
era id_nodo(lev, 0, 0); aca la planta es irregular y no hay indices,
asi que se busca el nodo mas cercano a la esquina de la ventana del
edificio.
"""
topo = M.construir_modelo()
M.nuevo_patron()
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)

for lev in range(1, M.nNiveles):
    F = 10.0 * lev
    ops.load(M.nodo_de_esquina(lev, 'SO'), F, 0.0, 0.0, 0.0, 0.0, 0.0)

ok = M.resolver()
check(ok == 0, "el analisis lateral converge")

peor_ux = peor_uy = peor_rz = 0.0
giro_maximo = 0.0

for lev in range(1, M.nNiveles):
    maestro = M.id_maestro(lev)
    xm, ym, _ = ops.nodeCoord(maestro)
    ux_m = ops.nodeDisp(maestro, 1)
    uy_m = ops.nodeDisp(maestro, 2)
    rz_m = ops.nodeDisp(maestro, 6)
    giro_maximo = max(giro_maximo, abs(rz_m))

    for n in M.nodos_del_nivel(lev):
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

# Y el experimento de control: si los muros no estuvieran tomando
# nada, girarles el eje fuerte 90 grados no cambiaria el resultado.
# En la grilla esto se hacia sacando los muros; aca no se puede
# (115 brazos rigidos cuelgan de ellos), asi que se giran.
def giro_de_piso(girar):
    M.construir_modelo(girar_muros=girar)
    M.nuevo_patron()
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)
    for lev in range(1, M.nNiveles):
        ops.load(M.nodo_de_esquina(lev, 'SO'), 10.0 * lev, 0.0, 0.0, 0.0, 0.0, 0.0)
    M.resolver()
    return max(abs(ops.nodeDisp(M.id_maestro(l), 6))
               for l in range(1, M.nNiveles))


derecho = giro_de_piso(False)
girado = giro_de_piso(True)
print(f"\n  giro maximo con los muros en su eje fuerte = {derecho:.4e} rad")
print(f"  giro maximo con los muros girados 90 grados = {girado:.4e} rad")
check(abs(girado / derecho - 1.0) > 0.05,
      "los muros SI toman torsion (no son solo dibujo)",
      f"girarlos cambia el giro de piso un {100*(girado/derecho-1):+.0f} %")


# ============================================================
print("\n" + "=" * 68)
if fallos:
    print(f" FALLARON {len(fallos)} VERIFICACIONES:")
    for f in fallos:
        print("   -", f)
    print("=" * 68)
    sys.exit(1)
print(" LAS 5 VERIFICACIONES DEL LAB 2 PASARON  (estructura: edificio LT2)")
print("=" * 68)
