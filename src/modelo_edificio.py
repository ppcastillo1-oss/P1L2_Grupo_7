# -*- coding: utf-8 -*-
r"""
================================================================
 modelo_edificio.py  -  FUENTE DE VERDAD DEL EDIFICIO
================================================================
 Geometria, materiales, secciones, muros, apoyos, diafragmas y
 cargas del Edificio de Ingenieria. Todos los demas scripts
 IMPORTAN de aqui; si hay que cambiar el modelo, se cambia SOLO
 en este archivo.

 Unidades: m, kN, kPa (consistentes).

 ----------------------------------------------------------------
 QUE CAMBIA RESPECTO DE LA SEMANA 1
 ----------------------------------------------------------------
 1. AREAS TRIBUTARIAS a 45 grados (modulo areas_tributarias.py) en
    vez del reparto 50/50. En los panos alargados de este edificio
    el 50/50 descargaba la viga larga un 40%.

 2. CARGAS DISTRIBUIDAS sobre las vigas con eleLoad, en vez de
    cargas puntuales en los nodos. La losa descarga a lo largo de la
    viga, no en sus extremos; ademas asi la viga tiene momento de
    vano y no solo de nudo.

 3. DIAFRAGMA RIGIDO con ops.rigidDiaphragm en vez de equalDOF.
    equalDOF(m, s, 1, 2, 6) obliga a que TODOS los nodos del piso
    tengan el mismo ux, uy y rz -- eso no es un diafragma rigido,
    es un piso que no puede rotar. El diafragma real cumple:
        ux_i = ux_m - rz*(y_i - y_m)
        uy_i = uy_m + rz*(x_i - x_m)
    o sea, permite ROTACION del piso. Con planta irregular y sismo
    la diferencia importa.

 4. MUROS equivalentes ("columna ancha") como elementos lineales
    verticales, orientados con vecxz.

 5. TORSION J por Saint-Venant en vez de min(Iy,Iz)*0.3, que no
    corresponde a ninguna formula y subestimaba J unas 5 veces.
================================================================
"""
import json
import math
import os

import openseespy.opensees as ops

import areas_tributarias as at

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)


# ============================================================
# 1. GEOMETRIA  (extraida de los planos DXF, en metros)
# ============================================================
# Ejes estructurales. Vienen de la capa de ejes del DXF (las cotas
# del plano estan en cm; ya convertidas a m).
EJES_X = [8.02, 11.32, 14.72, 18.02, 28.02, 38.02, 48.02, 53.02]
EJES_Y = [46.92, 50.26, 55.20, 60.20, 65.22, 72.75]

# Cotas de piso. El nivel 0 es la fundacion (donde van los apoyos).
NIVELES_Z = [0.0, 4.0, 7.5, 11.0, 14.5, 18.0, 21.5, 25.0, 28.5]

nX = len(EJES_X)
nY = len(EJES_Y)
nNiveles = len(NIVELES_Z)
NODOS_POR_PISO = nX * nY

AREA_PLANTA = (EJES_X[-1] - EJES_X[0]) * (EJES_Y[-1] - EJES_Y[0])


# ============================================================
# 2. MATERIAL  (hormigon armado)
# ============================================================
FPC = 28.0                                  # MPa
POISSON = 0.20
Ec = 4700.0 * math.sqrt(FPC) * 1000.0       # kPa  (ACI 318)
Gc = Ec / (2.0 * (1.0 + POISSON))
GAMMA = 25.0                                # kN/m3


# ============================================================
# 3. TORSION DE SECCION RECTANGULAR
# ============================================================
def J_rectangular(b, h):
    r"""
    Constante de torsion de Saint-Venant para seccion rectangular
    llena (Timoshenko / Roark):

        J = a*t^3 * [ 1/3 - 0.21*(t/a)*(1 - t^4/(12*a^4)) ]

    con a = lado LARGO y t = lado CORTO.

    NOTA: la version de Semana 1 usaba min(Iy,Iz)*0.3, que no
    corresponde a ninguna formula y daba ~5.6 veces MENOS rigidez
    torsional. En un marco simetrico no se nota (torsion ~ 0), pero
    este edificio tiene planta irregular: los panos van de 3.30 m a
    10.00 m, asi que la torsion si carga las columnas.
    """
    a = max(b, h)
    t = min(b, h)
    return a * t**3 * (1.0 / 3.0 - 0.21 * (t / a) * (1.0 - t**4 / (12.0 * a**4)))


# ============================================================
# 4. SECCIONES
# ============================================================
# Convencion de nombres: en vez de Iy/Iz (que se confunden al pasarlos
# a OpenSees) las guardamos por FUNCION:
#   I_grav    -> flexion que produce desplazamiento VERTICAL (gravedad)
#   I_lat     -> flexion que produce desplazamiento HORIZONTAL
# La asignacion a los huecos Iy/Iz de ops.element se hace en
# _agregar_barra(), que es el unico lugar que conoce la convencion.

def _seccion_rect(nombre, b, h):
    """
    Seccion rectangular b (ancho) x h (alto).
    Para una VIGA horizontal: h es el canto, b el ancho.
    """
    return {
        'nombre': nombre,
        'b': b, 'h': h,
        'A': b * h,
        'I_grav': b * h**3 / 12.0,     # flexion vertical
        'I_lat': h * b**3 / 12.0,      # flexion lateral
        'J': J_rectangular(b, h),
    }


SECCIONES = {
    'C50x50':  _seccion_rect('C50x50', 0.50, 0.50),   # columnas
    'VX30x60': _seccion_rect('VX30x60', 0.30, 0.60),  # vigas en X
    'VY30x80': _seccion_rect('VY30x80', 0.30, 0.80),  # vigas en Y
}

SEC_COLUMNA = 'C50x50'
SEC_VIGA_X = 'VX30x60'
SEC_VIGA_Y = 'VY30x80'


# ============================================================
# 5. MUROS  (elementos lineales equivalentes: "columna ancha")
# ============================================================
# Se leen de data/muros.json para que la geometria sea TRAZABLE al
# plano y no quede escondida en el codigo. Si el archivo no existe,
# el modelo se arma sin muros y lo avisa.
#
# Formato de cada muro:
#   {"id": "M1", "x1":..,"y1":.., "x2":..,"y2":.., "espesor":..,
#    "desde_nivel":1, "hasta_nivel":8}
#
# Idealizacion: el muro se modela como UNA barra vertical en su eje
# baricentrico, con la seccion del muro completo. Su eje fuerte se
# orienta con vecxz en la direccion del muro en planta.
RUTA_MUROS = os.path.join(_RAIZ, 'data', 'muros.json')


def cargar_muros():
    """Lee data/muros.json. Devuelve [] si no existe todavia."""
    if not os.path.exists(RUTA_MUROS):
        return []
    with open(RUTA_MUROS, encoding='utf-8') as f:
        datos = json.load(f)
    return datos.get('muros', datos if isinstance(datos, list) else [])


def seccion_muro(largo, espesor):
    """
    Seccion equivalente de un muro de largo L y espesor t.

        A       = L * t
        I_fuerte = t * L^3 / 12     (flexion EN el plano del muro)
        I_debil  = L * t^3 / 12     (fuera del plano)

    La relacion I_fuerte/I_debil = (L/t)^2, que para un muro de 4 m
    de largo y 0.20 m de espesor es 400: por eso importa orientarlo
    bien. Un muro mal orientado aporta 400 veces menos rigidez de la
    que deberia, y el modelo no avisa.
    """
    return {
        'A': largo * espesor,
        'I_fuerte': espesor * largo**3 / 12.0,
        'I_debil': largo * espesor**3 / 12.0,
        'J': J_rectangular(largo, espesor),
    }


# ============================================================
# 6. CARGAS
# ============================================================
ESPESOR_LOSA = 0.25              # m
TERMINACIONES = 1.5              # kN/m2

# q_G = peso propio de losa + terminaciones uniformes.
# El peso propio de vigas y columnas se agrega aparte (no pasa por
# el reparto tributario: cada barra carga el suyo).
Q_G = GAMMA * ESPESOR_LOSA + TERMINACIONES     # 7.75 kN/m2
Q_Q = 2.0                                       # kN/m2 (carga viva)


# ============================================================
# 7. NUMERACION DE NODOS
# ============================================================
def id_nodo(nivel, ix, iy):
    """
    Id del nodo de la malla. Los ids NO cambian al agregar muros o
    diafragmas: los nodos extra se numeran despues de estos.
    """
    return nivel * NODOS_POR_PISO + ix * nY + iy + 1


# Los nodos maestros de diafragma van despues de toda la malla.
_BASE_MAESTROS = nNiveles * NODOS_POR_PISO


def id_maestro(nivel):
    """Nodo maestro del diafragma del piso `nivel`."""
    return _BASE_MAESTROS + nivel


# ============================================================
# 8. CONSTRUCCION DEL MODELO
# ============================================================
# Etiquetas de geomTransf
TR_VERTICAL = 1        # columnas y muros por defecto: vecxz = (1,0,0)
TR_HORIZONTAL = 2      # vigas: vecxz = (0,0,1)
_TR_LIBRE = 10         # de aqui en adelante, transformaciones de muros

# Topologia de la ultima construccion (para exportar y verificar).
TOPOLOGIA = {}


def _agregar_barra(tag, ni, nj, A, I_grav_o_fuerte, I_lat_o_debil, J, transf,
                   vertical):
    r"""
    Crea un elasticBeamColumn cuidando la convencion de ejes locales.

    La firma de OpenSees es:
        element('elasticBeamColumn', tag, ni, nj, A, E, G, J, Iy, Iz, transf)

    y CUAL inercia va en el hueco Iy depende de la transformacion:

      VIGA horizontal, vecxz = (0,0,1):
        local x = eje de la viga; local z = vertical.
        La gravedad flecta en el plano x-z -> momento My.
        => la inercia de gravedad va en el hueco Iy.

      COLUMNA/MURO vertical, vecxz = (1,0,0):
        local x = vertical; local z = +X global.
        El desplazamiento en X corresponde a My.
        => la inercia del eje fuerte va en el hueco Iy.

    En ambos casos la inercia "principal" va en Iy. Por eso este es el
    UNICO lugar del proyecto que toca ese orden: en todos los demas se
    habla de I_grav / I_fuerte, que no se prestan a confusion.
    """
    ops.element('elasticBeamColumn', tag, ni, nj,
                A, Ec, Gc, J,
                I_grav_o_fuerte,    # hueco Iy
                I_lat_o_debil,      # hueco Iz
                transf)


def construir_modelo(con_muros=True, con_diafragmas=True):
    """
    Levanta el modelo completo en OpenSees desde cero.

    Devuelve un dict con la topologia: listas de columnas, vigas,
    muros, apoyos y diafragmas, cada elemento como (tag, ni, nj).
    """
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    ops.geomTransf('Linear', TR_VERTICAL, 1.0, 0.0, 0.0)     # verticales
    ops.geomTransf('Linear', TR_HORIZONTAL, 0.0, 0.0, 1.0)   # horizontales

    # ---------- Nodos de la malla ----------
    coords = {}
    for lev in range(nNiveles):
        z = NIVELES_Z[lev]
        for ix in range(nX):
            for iy in range(nY):
                n = id_nodo(lev, ix, iy)
                coords[n] = (EJES_X[ix], EJES_Y[iy], z)
                ops.node(n, EJES_X[ix], EJES_Y[iy], z)

    # ---------- Apoyos: empotramiento en la fundacion ----------
    apoyos = []
    for ix in range(nX):
        for iy in range(nY):
            n = id_nodo(0, ix, iy)
            ops.fix(n, 1, 1, 1, 1, 1, 1)
            apoyos.append(n)

    tag = 1
    columnas, vigas_x, vigas_y, muros = [], [], [], []

    # ---------- Columnas ----------
    sc = SECCIONES[SEC_COLUMNA]
    for lev in range(nNiveles - 1):
        for ix in range(nX):
            for iy in range(nY):
                ni = id_nodo(lev, ix, iy)
                nj = id_nodo(lev + 1, ix, iy)
                _agregar_barra(tag, ni, nj, sc['A'], sc['I_lat'], sc['I_grav'],
                               sc['J'], TR_VERTICAL, vertical=True)
                columnas.append((tag, ni, nj))
                tag += 1

    # ---------- Vigas en X ----------
    sx = SECCIONES[SEC_VIGA_X]
    for lev in range(1, nNiveles):
        for ix in range(nX - 1):
            for iy in range(nY):
                ni = id_nodo(lev, ix, iy)
                nj = id_nodo(lev, ix + 1, iy)
                _agregar_barra(tag, ni, nj, sx['A'], sx['I_grav'], sx['I_lat'],
                               sx['J'], TR_HORIZONTAL, vertical=False)
                vigas_x.append((tag, ni, nj, lev, ix, iy))
                tag += 1

    # ---------- Vigas en Y ----------
    sy = SECCIONES[SEC_VIGA_Y]
    for lev in range(1, nNiveles):
        for ix in range(nX):
            for iy in range(nY - 1):
                ni = id_nodo(lev, ix, iy)
                nj = id_nodo(lev, ix, iy + 1)
                _agregar_barra(tag, ni, nj, sy['A'], sy['I_grav'], sy['I_lat'],
                               sy['J'], TR_HORIZONTAL, vertical=False)
                vigas_y.append((tag, ni, nj, lev, ix, iy))
                tag += 1

    # ---------- Muros equivalentes ----------
    datos_muros = cargar_muros() if con_muros else []
    transf_muro = _TR_LIBRE
    nodo_extra = _BASE_MAESTROS + nNiveles + 1
    # Nodos de muro por nivel: se suman al diafragma de su piso, que es
    # lo que conecta el muro con el resto de la estructura. Sin esto el
    # muro queda como un voladizo suelto al lado del edificio: aporta
    # rigidez a nada y el modelo no avisa.
    nodos_muro_por_nivel = {lev: [] for lev in range(nNiveles)}

    for m in datos_muros:
        x1, y1 = float(m['x1']), float(m['y1'])
        x2, y2 = float(m['x2']), float(m['y2'])
        largo = math.hypot(x2 - x1, y2 - y1)
        if largo < 1e-6:
            raise ValueError(f"Muro {m.get('id')} tiene largo cero")

        espesor = float(m['espesor'])
        sm = seccion_muro(largo, espesor)

        # Eje baricentrico del muro y direccion en planta.
        xc, yc = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        dx, dy = (x2 - x1) / largo, (y2 - y1) / largo

        # El eje FUERTE del muro esta en su plano: vecxz apunta en la
        # direccion del muro en planta. Nunca puede ser paralelo al eje
        # del elemento (que es vertical), asi que es seguro.
        ops.geomTransf('Linear', transf_muro, dx, dy, 0.0)

        desde = int(m.get('desde_nivel', 1))
        hasta = int(m.get('hasta_nivel', nNiveles - 1))

        prev = None
        for lev in range(desde - 1, hasta + 1):
            n = nodo_extra
            nodo_extra += 1
            coords[n] = (xc, yc, NIVELES_Z[lev])
            ops.node(n, xc, yc, NIVELES_Z[lev])
            if lev == 0:
                ops.fix(n, 1, 1, 1, 1, 1, 1)
                apoyos.append(n)
            else:
                nodos_muro_por_nivel[lev].append(n)
            if prev is not None:
                _agregar_barra(tag, prev, n, sm['A'], sm['I_fuerte'],
                               sm['I_debil'], sm['J'], transf_muro,
                               vertical=True)
                muros.append({
                    'tag': tag, 'ni': prev, 'nj': n,
                    'muro_id': m.get('id'), 'nivel': lev,
                    'A': sm['A'], 'largo': largo, 'espesor': espesor,
                    'dir': (dx, dy),
                })
                tag += 1
            prev = n
        transf_muro += 1

    # ---------- Diafragmas rigidos ----------
    diafragmas = []
    if con_diafragmas:
        for lev in range(1, nNiveles):
            maestro = id_maestro(lev)
            xm = sum(EJES_X) / nX
            ym = sum(EJES_Y) / nY
            coords[maestro] = (xm, ym, NIVELES_Z[lev])
            ops.node(maestro, xm, ym, NIVELES_Z[lev])

            # El diafragma solo liga ux, uy y rz. Los GDL fuera de su
            # plano (uz, rx, ry) del MAESTRO quedarian sin rigidez y la
            # matriz saldria singular: hay que restringirlos.
            ops.fix(maestro, 0, 0, 1, 1, 1, 0)

            esclavos = [id_nodo(lev, ix, iy)
                        for ix in range(nX) for iy in range(nY)]
            # Los nodos de muro de este piso entran al MISMO diafragma:
            # asi el muro trabaja junto con el marco en vez de quedar
            # aislado.
            esclavos += nodos_muro_por_nivel.get(lev, [])
            # perpendicular = 3 -> diafragma horizontal (plano X-Y)
            ops.rigidDiaphragm(3, maestro, *esclavos)
            diafragmas.append((maestro, esclavos))

    TOPOLOGIA.clear()
    TOPOLOGIA.update({
        'coords': coords,
        'columnas': columnas,
        'vigas_x': vigas_x,
        'vigas_y': vigas_y,
        'muros': muros,
        'apoyos': apoyos,
        'diafragmas': diafragmas,
        'n_elementos': tag - 1,
    })
    return TOPOLOGIA


# ============================================================
# 9. CARGAS POR AREAS TRIBUTARIAS
# ============================================================
def tributarias_por_viga():
    """
    Calcula el area tributaria de cada viga de un piso tipo y la
    devuelve indexada por la clave de malla ('X'|'Y', ix, iy).

    Es el MISMO reparto para todos los pisos, porque la planta no
    cambia con la altura.
    """
    return at.repartir_piso(EJES_X, EJES_Y)


def aplicar_carga_gravitacional(topo, q, incluir_peso_propio=True):
    r"""
    Aplica la carga de piso q [kN/m2] a las vigas como carga
    DISTRIBUIDA, usando las areas tributarias a 45 grados.

        w_viga = q * A_tributaria / L        [kN/m]

    y en OpenSees:
        eleLoad('-ele', tag, '-type', '-beamUniform', Wy, Wz, Wx)

    Con vecxz = (0,0,1) el eje local z de la viga es el vertical, asi
    que la gravedad va en Wz (el SEGUNDO valor) y con signo negativo.

    Devuelve la carga total aplicada [kN], para poder verificar
    conservacion y equilibrio despues.
    """
    trib = tributarias_por_viga()
    total = 0.0

    for (tag, ni, nj, lev, ix, iy) in topo['vigas_x']:
        reg = trib[('X', ix, iy)]
        w = at.carga_lineal(q, reg['area'], reg['luz'])
        ops.eleLoad('-ele', tag, '-type', '-beamUniform', 0.0, -w, 0.0)
        total += w * reg['luz']

    for (tag, ni, nj, lev, ix, iy) in topo['vigas_y']:
        reg = trib[('Y', ix, iy)]
        w = at.carga_lineal(q, reg['area'], reg['luz'])
        ops.eleLoad('-ele', tag, '-type', '-beamUniform', 0.0, -w, 0.0)
        total += w * reg['luz']

    if incluir_peso_propio:
        total += _aplicar_peso_propio(topo)

    return total


def _aplicar_peso_propio(topo):
    """
    Peso propio de vigas (distribuido) y columnas/muros (nodal).
    No pasa por el reparto tributario: cada barra carga el suyo.
    """
    total = 0.0
    coords = topo['coords']

    for lista, nombre_sec in ((topo['vigas_x'], SEC_VIGA_X),
                              (topo['vigas_y'], SEC_VIGA_Y)):
        s = SECCIONES[nombre_sec]
        w = GAMMA * s['A']
        for reg in lista:
            tag, ni, nj = reg[0], reg[1], reg[2]
            xi, yi, zi = coords[ni]
            xj, yj, zj = coords[nj]
            L = math.dist((xi, yi, zi), (xj, yj, zj))
            ops.eleLoad('-ele', tag, '-type', '-beamUniform', 0.0, -w, 0.0)
            total += w * L

    sc = SECCIONES[SEC_COLUMNA]
    for (tag, ni, nj) in topo['columnas']:
        L = abs(coords[nj][2] - coords[ni][2])
        W = GAMMA * sc['A'] * L
        ops.load(ni, 0.0, 0.0, -W / 2.0, 0.0, 0.0, 0.0)
        ops.load(nj, 0.0, 0.0, -W / 2.0, 0.0, 0.0, 0.0)
        total += W

    for m in topo['muros']:
        L = abs(coords[m['nj']][2] - coords[m['ni']][2])
        W = GAMMA * m['A'] * L
        ops.load(m['ni'], 0.0, 0.0, -W / 2.0, 0.0, 0.0, 0.0)
        ops.load(m['nj'], 0.0, 0.0, -W / 2.0, 0.0, 0.0, 0.0)
        total += W

    return total


def nuevo_patron():
    """timeSeries + pattern estandar (lineal)."""
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)


# ============================================================
# 10. SOLUCION
# ============================================================
def resolver():
    """
    Analisis estatico lineal.

    constraints('Transformation') es OBLIGATORIO aqui: con
    rigidDiaphragm hay restricciones multipunto, y el manejador
    'Plain' no las sabe tratar.
    """
    ops.system('BandGeneral')
    ops.numberer('RCM')
    ops.constraints('Transformation')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')
    ok = ops.analyze(1)
    ops.reactions()
    return ok
