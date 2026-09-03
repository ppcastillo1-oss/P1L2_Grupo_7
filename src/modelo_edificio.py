# -*- coding: utf-8 -*-
r"""
================================================================
 modelo_edificio.py  -  LA ESTRUCTURA DEL LABORATORIO
================================================================
 Este modulo es la FUENTE DE VERDAD del modelo para todo el
 laboratorio: el notebook, verificar_lab2.py y exportar_unity.py
 importan de aca y de ningun otro lado.

 Unidades: m, kN, kPa (consistentes).

 ----------------------------------------------------------------
 QUE CAMBIO
 ----------------------------------------------------------------
 Hasta la Semana 2 la estructura era el Edificio de Ingenieria
 idealizado como una GRILLA REGULAR: 8 ejes en X por 6 en Y por 9
 niveles, con una columna en cada cruce y una viga en cada tramo de
 eje. Toda la geometria cabia en tres listas de numeros.

 Ahora la estructura es el edificio **LT2**, armado entero desde sus
 planos de calculo `2024_22`. Y no es una grilla:

   - 8 pilares y 9 muros repartidos sin simetria;
   - las vigas no siguen los ejes: se cruzan entre ellas;
   - hay una caja de ascensores, un vano de fachada y esquinas en T;
   - la planta no es un rectangulo lleno.

 Por eso el modelo del LT2 no es "una grilla con otros numeros": es
 un pipeline propio (leer el DXF -> emparejar caras -> mallar ->
 encontrar los panos), que vive en el repo `A1P1.0_Grupo_7`.

 ----------------------------------------------------------------
 POR QUE UN ADAPTADOR
 ----------------------------------------------------------------
 Este archivo NO reimplementa el LT2: lo IMPORTA y le pone encima la
 misma interfaz que el laboratorio ya usaba.

 El modelo se DESARROLLA en el repo A1P1.0_Grupo_7 (ahi esta el
 ingestor de planos y sus tests) y de ahi se COPIA a `src/` de este
 repo. Se copia y no se referencia porque el laboratorio tiene que
 entregarse solo: quien clone este repositorio debe poder correrlo
 sin bajar nada mas.

 Para iterar contra la copia de A1P1.0 sin sincronizar cada vez:
     $env:LT2_SRC = "C:\ruta\a\A1P1.0_Grupo_7\src"

 Lo que el laboratorio conserva sin cambios: el notebook y sus
 secciones, las 5 verificaciones, el contrato JSON, el visor de
 Unity, el servidor de reanalisis y los tests.

 ----------------------------------------------------------------
 LO QUE NO SE PUDO CONSERVAR, Y POR QUE
 ----------------------------------------------------------------
 `id_nodo(nivel, ix, iy)` no existe mas. En una grilla cada nodo es
 el cruce del eje ix con el eje iy, asi que un nodo tiene direccion.
 En el LT2 los nodos salen de MALLAR las vigas: 46 nodos por piso en
 posiciones que no forman grilla, y el cruce del eje C con el eje 2
 puede no tener ningun nodo. Inventar un indice (ix, iy) seria
 mentir sobre la geometria.

 En su lugar: `nodos_del_nivel(nivel)` y `nodo_mas_cercano(x, y, nivel)`.

 `construir_modelo(con_muros=False)` tampoco: en la grilla los muros
 eran un extra sobre un marco que se sostenia solo. En el LT2 hay 115
 brazos rigidos que cuelgan de los muros, asi que sacarlos deja
 vigas flotando y la matriz singular. El experimento de control
 equivalente es `girar_muros=True`, que gira 90 grados el eje fuerte
 de todos los muros: un muro tiene hasta 1000 veces mas inercia en un
 eje que en el otro, asi que si el resultado no cambia al girarlos,
 los muros no estaban tomando nada.

 Las dos siguen existiendo como funciones, pero solo para levantar un
 error que EXPLICA como salir de ahi: la causa mas probable de que
 alguien las llame no es un bug, es una celda vieja de una sesion de
 Jupyter que quedo abierta.
================================================================
"""
from __future__ import annotations

import json
import os
import sys

import openseespy.opensees as ops

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)


# ============================================================
# 0. DONDE VIVE EL MODELO DEL LT2
# ============================================================
def _ruta_del_lt2():
    """
    Encuentra el modulo del modelo del LT2.

    Primero busca la copia que vive en ESTE repo (src/modelo_lt2.py).
    El laboratorio se entrega solo: quien clone este repositorio tiene
    que poder correrlo sin bajar nada mas.

    El modelo se desarrolla en el repo A1P1.0_Grupo_7 y de ahi se
    copia. Si se quiere trabajar contra ESA copia --para no tener que
    sincronizar mientras se itera-- se declara su ruta en la variable
    de entorno LT2_SRC y manda esa.
    """
    declarada = os.environ.get('LT2_SRC')
    candidatas = ([declarada] if declarada else []) + [
        _AQUI,                                          # la copia local
        os.path.join(os.path.dirname(_RAIZ), 'A1P1.0_Grupo_7', 'src'),
    ]
    for c in candidatas:
        if c and os.path.isfile(os.path.join(c, 'modelo_lt2.py')):
            return os.path.abspath(c)
    raise RuntimeError(
        'No encuentro src/modelo_lt2.py. Se busco en:\n  ' +
        '\n  '.join(str(c) for c in candidatas))


LT2_SRC = _ruta_del_lt2()
if LT2_SRC not in sys.path:
    sys.path.insert(0, LT2_SRC)

import modelo_lt2 as _LT2                  # noqa: E402
import panos as _panos                     # noqa: E402

RUTA_GEOMETRIA = _LT2.GEOMETRIA
with open(RUTA_GEOMETRIA, encoding='utf-8') as _f:
    GEOMETRIA = json.load(_f)


# ============================================================
# 1. GEOMETRIA  (toda leida del plano, nada escrito a mano)
# ============================================================
# Los ejes son los que rotula el calculista, con su nombre. En la
# grilla vieja los ejes DEFINIAN la estructura; aca son referencia:
# sirven para registrar las laminas entre si y para acotar el
# edificio, pero no hay una columna en cada cruce.
EJES = {d: [(e['nombre'], e['coord']) for e in GEOMETRIA['ejes'][d]]
        for d in ('X', 'Y')}
EJES_X = [c for _n, c in EJES['X']]
EJES_Y = [c for _n, c in EJES['Y']]
NOMBRES_X = [n for n, _c in EJES['X']]
NOMBRES_Y = [n for n, _c in EJES['Y']]

nX, nY = len(EJES_X), len(EJES_Y)

# Los niveles del modelo salen de las 6 elevaciones: una cota es un
# piso del edificio solo si las SEIS coinciden en ella.
_NM = GEOMETRIA['niveles_del_modelo']
NIVELES_Z = [_NM['base']] + [p['z'] for p in _NM['pisos']]
nNiveles = len(NIVELES_Z)
ALTURA = NIVELES_Z[-1] - NIVELES_Z[0]

# La junta de dilatacion: el LT2 termina aca y al otro lado empieza
# otro cuerpo, estructuralmente separado.
VENTANA = GEOMETRIA['ventana']

# Un piso "tipo": los cuatro de abajo comparten lamina y carga.
NIVEL_TIPO = 1


# ============================================================
# 2. MATERIAL Y SECCIONES
# ============================================================
_HORM = GEOMETRIA['materiales']['hormigon']
FPC = float(_HORM['fc_MPa'])            # MPa, de la nota de la lamina 100
POISSON = float(_HORM.get('poisson', 0.20))
GAMMA = float(_HORM.get('gamma_kN_m3', 25.0))
Ec = 4700.0 * (FPC ** 0.5) * 1000.0     # kPa
Gc = Ec / (2.0 * (1.0 + POISSON))

J_rectangular = _LT2.J_rectangular      # Saint-Venant, la misma del lab


def seccion_muro(largo, espesor):
    """Seccion equivalente de un muro modelado como columna ancha."""
    return _LT2.seccion('M %.2fx%.2f' % (espesor, largo), espesor, largo)


# Las secciones del LT2 no son tres fijas: salen medidas del plano y
# hay una por cada tamano distinto que aparece. Se llenan al construir
# el modelo; las tres constantes se conservan para el codigo del lab
# que las nombra, apuntando a la mas repetida de cada tipo.
SECCIONES = {}
SEC_COLUMNA = 'P 0.70x0.70'
SEC_VIGA_X = 'V 0.60x0.80'
SEC_VIGA_Y = 'V 0.60x0.80'


# ============================================================
# 3. CARGA DE PISO  (del plano de cargas, lamina 700)
# ============================================================
# En la grilla vieja q_G era un numero escrito a mano
# (25*0.25 + 1.5 = 7.75). Aca sale del PLANO DE CARGAS, y no es un
# solo numero: la lamina 700 da un peso muerto adicional distinto
# para las plantas tipo y para el cielo del 4o piso.
ESPESOR_LOSA = GEOMETRIA['losas']['auditoria']['espesor_dominante']
_CARGAS = GEOMETRIA['cargas']
_G_MS2 = _CARGAS['g_ms2']
PESO_LOSA = GAMMA * ESPESOR_LOSA                     # kN/m2

_POR_LAMINA = _CARGAS['por_lamina']
_LAMINA_TIPO = _NM['pisos'][0]['lamina']
_LAMINA_TECHO = _NM['pisos'][-1]['lamina']

TERMINACIONES = (_POR_LAMINA[_LAMINA_TIPO]['peso_muerto_adicional_kgf_m2']
                 * _G_MS2 / 1000.0)                  # kN/m2
Q_G = PESO_LOSA + TERMINACIONES                      # kN/m2, planta tipo
Q_Q = (_POR_LAMINA[_LAMINA_TIPO]['sobrecarga_kgf_m2']
       * _G_MS2 / 1000.0)                            # kN/m2, sobrecarga

TERMINACIONES_TECHO = (_POR_LAMINA[_LAMINA_TECHO]['peso_muerto_adicional_kgf_m2']
                       * _G_MS2 / 1000.0)
Q_G_TECHO = PESO_LOSA + TERMINACIONES_TECHO
Q_Q_TECHO = (_POR_LAMINA[_LAMINA_TECHO]['sobrecarga_kgf_m2']
             * _G_MS2 / 1000.0)


def carga_de_piso(nivel):
    """q_G del nivel: el techo tiene su propio peso muerto adicional."""
    return Q_G_TECHO if nivel == nNiveles - 1 else Q_G


# ============================================================
# 4. LOS MUROS DEL PLANO
# ============================================================
def cargar_muros():
    """
    Los muros de la planta tipo, con eje y espesor, tal como los
    emparejo el ingestor a partir de sus dos caras dibujadas.
    """
    muros = GEOMETRIA['plantas'][_LAMINA_TIPO]['muros']
    return [dict(m, id=i + 1) for i, m in enumerate(muros)]


def cargar_pilares():
    """Los pilares de la planta tipo, medidos del dibujo."""
    return GEOMETRIA['plantas'][_LAMINA_TIPO]['pilares']


def cargar_vigas():
    """Las vigas de la planta tipo, con su ancho medido y su alto rotulado."""
    return GEOMETRIA['plantas'][_LAMINA_TIPO]['vigas']


# ============================================================
# 5. AVISO DE CELDA VIEJA
# ============================================================
# La causa mas probable de que alguien llame a `id_nodo` o a
# `construir_modelo(con_muros=False)` no es un error de programacion:
# es una CELDA VIEJA. El notebook se actualizo con la estructura
# nueva, pero una sesion de Jupyter que ya estaba abierta sigue
# teniendo en memoria la version anterior, y ejecutarla daba un error
# que no decia como salir de ahi.
_CELDA_VIEJA = (
    '\n'
    'Estas ejecutando una celda del laboratorio ANTERIOR (el de la grilla\n'
    'regular). El notebook en disco ya no usa esta llamada.\n'
    '\n'
    'COMO ARREGLARLO: recarga el notebook desde el disco.\n'
    '   JupyterLab : File -> Reload Notebook from Disk,\n'
    '                y despues Kernel -> Restart Kernel and Run All Cells\n'
    '   VS Code    : cerra la pestana del notebook y volve a abrirla\n'
    '\n'
)


# ============================================================
# 6. EL MODELO
# ============================================================
# El modelo del LT2 es un objeto; el laboratorio esperaba funciones de
# modulo. Se guarda la instancia aca para que las funciones del lab
# sigan funcionando igual.
MODELO = None            # la instancia de ModeloLT2 ya ensamblada
TOPOLOGIA = {}


def construir_modelo(con_diafragmas=True, girar_muros=False, con_muros=None):
    """
    Levanta el modelo completo del LT2 en OpenSees, SIN cargas.

    Devuelve la topologia en el mismo formato que usaba el lab:
    listas de columnas, vigas_x, vigas_y, muros, brazos, apoyos y
    diafragmas, cada elemento como (tag, ni, nj).

    Las vigas se separan en X e Y por hacia donde corren en planta,
    que es lo que el visor colorea y filtra.
    """
    global MODELO
    if con_muros is False:
        raise NotImplementedError(_CELDA_VIEJA + (
            'Lo que pedia esa celda: construir_modelo(con_muros=False).\n'
            '\n'
            'Por que no aplica: en la grilla vieja los muros eran un extra\n'
            'sobre un marco que se sostenia solo. En el LT2 hay 115 brazos\n'
            'rigidos que cuelgan de los muros, asi que sacarlos deja vigas\n'
            'flotando y la matriz sale singular.\n'
            '\n'
            'El experimento de control equivalente es girar_muros=True: gira\n'
            '90 grados el eje fuerte de todos los muros. Un muro tiene hasta\n'
            '1000 veces mas inercia en un eje que en el otro, asi que si el\n'
            'resultado no cambia al girarlos, no estaban tomando nada.'))

    MODELO = _LT2.ModeloLT2().preparar()
    MODELO.ensamblar(None, con_diafragmas=con_diafragmas,
                     girar_muros=girar_muros)

    SECCIONES.clear()
    for _nombre, s in MODELO.secciones.items():
        SECCIONES[s.nombre] = {'nombre': s.nombre, 'A': s.A, 'Iy': s.Iy,
                               'Iz': s.Iz, 'J': s.J, 'b': s.b, 'h': s.h}

    columnas, muros = [], []
    for tag, n1, n2, _sec, _v, tipo, _peso in MODELO.verticales:
        (muros if tipo == 'muro' else columnas).append((tag, n1, n2))

    vigas_x, vigas_y = [], []
    for tag, n1, n2, _sec, _L, _peso, _k in MODELO.vigas:
        a, b = MODELO.nodos[n1], MODELO.nodos[n2]
        destino = vigas_x if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else vigas_y
        destino.append((tag, n1, n2))

    brazos = [(tag, n1, n2) for tag, n1, n2, _s, _L, _k in MODELO.brazos]

    TOPOLOGIA.clear()
    TOPOLOGIA.update({
        'coords': dict(MODELO.nodos),
        'columnas': columnas,
        'vigas_x': vigas_x,
        'vigas_y': vigas_y,
        'muros': muros,
        'brazos': brazos,
        'apoyos': list(MODELO.nodos_base),
        'diafragmas': [(m, nodos_del_nivel(k))
                       for k, m in sorted(MODELO.maestros.items())],
        'n_elementos': (len(columnas) + len(vigas_x) + len(vigas_y)
                        + len(muros) + len(brazos)),
    })
    return TOPOLOGIA


def _exigir_modelo():
    if MODELO is None:
        raise RuntimeError('Corre primero construir_modelo().')
    return MODELO


# ============================================================
# 7. NODOS  (sin indices de grilla: no hay grilla)
# ============================================================
def nodos_del_nivel(nivel):
    """Los tags de los nodos de un nivel. Reemplaza a id_nodo(lev, ix, iy)."""
    m = _exigir_modelo()
    z = NIVELES_Z[nivel]
    return [t for t, (_x, _y, zz) in m.nodos.items() if abs(zz - z) < 1e-9]


def nodo_mas_cercano(x, y, nivel):
    """El nodo del nivel mas cercano a (x, y). Para cargar un punto."""
    m = _exigir_modelo()
    cands = nodos_del_nivel(nivel)
    if not cands:
        raise RuntimeError('el nivel %d no tiene nodos' % nivel)
    return min(cands, key=lambda t: (m.nodos[t][0] - x) ** 2
               + (m.nodos[t][1] - y) ** 2)


def nodo_de_esquina(nivel, esquina='SO'):
    """
    Un nodo de esquina del nivel, para aplicar carga EXCENTRICA.

    La verificacion del diafragma necesita que el piso GIRE: con la
    carga en el centro de masa el giro es cero y la prueba se cumple
    sola sin probar nada.
    """
    objetivo = {'SO': (VENTANA['xmin'], VENTANA['ymin']),
                'SE': (VENTANA['xmax'], VENTANA['ymin']),
                'NO': (VENTANA['xmin'], VENTANA['ymax']),
                'NE': (VENTANA['xmax'], VENTANA['ymax'])}[esquina]
    return nodo_mas_cercano(objetivo[0], objetivo[1], nivel)


def id_maestro(nivel):
    """El nodo maestro del diafragma de un nivel."""
    return _exigir_modelo().maestros[nivel]


def id_nodo(nivel, ix, iy):
    """
    NO EXISTE en esta estructura. Se conserva solo para dar un mensaje
    util a quien ejecute una celda vieja.
    """
    raise NotImplementedError(_CELDA_VIEJA + (
        'Lo que pedia esa celda: id_nodo(nivel=%r, ix=%r, iy=%r).\n'
        '\n'
        'Por que no existe: en una grilla cada nodo es el cruce del eje ix\n'
        'con el eje iy, asi que un nodo tiene direccion. En el LT2 los nodos\n'
        'salen de MALLAR las vigas --46 por piso, en posiciones que no forman\n'
        'grilla-- y el cruce del eje C con el eje 2 puede no tener ningun\n'
        'nodo. Inventar un indice (ix, iy) seria mentir sobre la geometria.\n'
        '\n'
        'En su lugar:\n'
        '   nodos_del_nivel(nivel)          todos los nodos de un piso\n'
        '   nodo_mas_cercano(x, y, nivel)   el nodo mas cercano a un punto\n'
        '   nodo_de_esquina(nivel, "SO")    para cargar excentrico'
        % (nivel, ix, iy)))


NODOS_POR_PISO = None       # se llena al construir: no es nX*nY


# ============================================================
# 8. AREAS TRIBUTARIAS
# ============================================================
def tributarias_por_viga(nivel=None):
    """
    Area tributaria de cada barra, indexada por su elementTag.

    `nivel=None` devuelve TODOS los pisos; un entero, solo ese. En la
    grilla vieja el reparto era el mismo para todos los pisos porque
    la planta no cambiaba con la altura. Aca la planta del techo sale
    de otra lamina y su carga de piso es distinta, asi que hay un
    reparto POR PISO y hay que decir de cual se habla.

    Cambia respecto de la grilla en dos cosas mas, y las dos son
    porque la planta es irregular:

      - la clave es el elementTag, no ('X'|'Y', ix, iy): no hay grilla
        que indexar;
      - los panos hay que ENCONTRARLOS. Son las caras del grafo plano
        que forman las vigas y los muros de cada piso, y de ellas se
        descartan las que el plano no rotula como losa (el hueco del
        ascensor). Ver panos.py.

    El criterio de reparto es el MISMO del lab: bisectrices a 45
    grados, o sea que cada pedazo de losa carga al lado que tiene mas
    cerca. En un pano rectangular sale el trapecio y el triangulo de
    las formulas cerradas, y eso se verifica.
    """
    m = _exigir_modelo()
    salida = {}

    def guardar(tag, par, k, largo, q):
        if nivel is not None and k != nivel:
            return
        A = m.area_trib.get(par, 0.0)
        if A <= 0:
            return
        salida[tag] = {
            'area': A,
            'luz': largo,
            'nivel': k,
            'q': q,
            'carga': q * A,
            'w': q * A / largo if largo > 0 else 0.0,
            'poligonos': m.poli_trib.get(par, []),
        }

    for tag, n1, n2, _sec, L, _peso, k in m.vigas:
        guardar(tag, (min(n1, n2), max(n1, n2)), k, L, carga_de_piso(k))
    for tag, n1, n2, _sec, L, k in m.brazos:
        guardar(tag, (min(n1, n2), max(n1, n2)), k, L, carga_de_piso(k))

    # Los muros tambien reciben losa: donde no hay viga, el pano
    # descarga directo sobre el muro. Va como carga PUNTUAL en su
    # baricentro, que es estaticamente equivalente.
    for tag, _n1, n2, sec, _v, tipo, _peso in m.verticales:
        if tipo != 'muro':
            continue
        A = m.area_trib_nodal.get(n2, 0.0)
        if A <= 0:
            continue
        z = m.nodos[n2][2]
        k = next((i for i, zz in enumerate(NIVELES_Z) if abs(zz - z) < 1e-9), None)
        if k is None or k == 0:
            continue
        if nivel is not None and k != nivel:
            continue
        q = carga_de_piso(k)
        salida[tag] = {'area': A, 'luz': sec.h, 'nivel': k, 'q': q,
                       'carga': q * A, 'w': q * A / max(sec.h, 1e-9),
                       'poligonos': m.poli_trib_nodal.get(n2, [])}
    return salida


def area_de_piso(nivel):
    """
    Area de losa de UN piso. No es la misma en todos: la del techo
    sale de otra lamina, y aunque den casi igual, comparar contra el
    promedio deja un residuo que despues parece un error de
    conservacion de carga.
    """
    return _exigir_modelo().area_piso.get(nivel, 0.0)


def area_de_planta():
    """Area de losa de un piso: la suma de los panos detectados."""
    m = _exigir_modelo()
    if not m.area_piso:
        return 0.0
    return sum(m.area_piso.values()) / len(m.area_piso)


AREA_PLANTA = None          # se llena al construir


# ============================================================
# 9. CARGAS
# ============================================================
def nuevo_patron(tag=1):
    """
    Deja el modelo listo para un caso de carga nuevo.

    Las tres llamadas son obligatorias y omitir cualquiera da
    resultados silenciosamente malos:

      reset()              si no, los desplazamientos del caso
                           anterior se acumulan;
      setTime(0.0)         el timeSeries Linear escala por el tiempo y
                           cada analyze(1) lo incrementa, asi que el
                           2o caso saldria x2;
      remove(loadPattern)  si no, las cargas anteriores siguen
                           actuando.

    NO crea el timeSeries ni el pattern: eso lo hace quien aplica la
    carga (aplicar_carga_gravitacional / aplicar_sobrecarga). Crearlos
    aca hacia que OpenSees rechazara el segundo con
    "could not add timeseries to domain".
    """
    m = _exigir_modelo()
    ops.reset()
    ops.setTime(0.0)
    try:
        ops.remove('loadPattern', tag)
    except Exception:
        pass
    return m


def aplicar_carga_gravitacional(topo=None, q=None, incluir_peso_propio=True):
    """
    Aplica el caso G: peso propio + losa por areas tributarias.

    Devuelve la carga total aplicada [kN], para verificar equilibrio.

    `q` se acepta para no romper la firma que usaba el lab, pero se
    IGNORA: en el LT2 la carga de piso no es un numero suelto, sale del
    plano de cargas y es distinta en el techo. Pasarla a mano abriria
    la puerta a que el informe y el modelo digan cosas distintas.
    """
    m = _exigir_modelo()
    if q is not None and abs(q - Q_G) > 1e-9:
        print('AVISO: se ignora q=%.4f. La carga de piso sale del plano de '
              'cargas: %.4f kN/m2 en las plantas tipo y %.4f en el techo.'
              % (q, Q_G, Q_G_TECHO))
    if not incluir_peso_propio:
        raise NotImplementedError(
            'El caso G del LT2 incluye siempre el peso propio. Exportar un '
            'G sin peso propio fue uno de los errores del lab: el JSON '
            'describia otro problema que el que resolvio Python, y el '
            'reanalisis daba 10.04 mm donde el modelo daba 11.78.')
    m.aplicar_cargas('G')
    return m.carga_total


def aplicar_sobrecarga(topo=None):
    """Aplica el caso Q (sobrecarga de uso). Devuelve el total [kN]."""
    m = _exigir_modelo()
    m.aplicar_cargas('Q')
    return m.carga_total


def resolver():
    """Resuelve el sistema. Devuelve 0 si convergio."""
    _exigir_modelo()
    ops.system('BandGeneral')
    ops.numberer('RCM')
    # 'Transformation' es obligatorio con rigidDiaphragm: son
    # restricciones multipunto y 'Plain' no las trata.
    ops.constraints('Transformation')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')
    ok = ops.analyze(1)
    # Sin reactions() las reacciones salen TODAS CERO, y la
    # verificacion de equilibrio "falla" con el modelo sano.
    if ok == 0:
        ops.reactions()
    return ok


# ============================================================
# 10. RESUMEN
# ============================================================
def resumen():
    """Los numeros del modelo, para el informe y el notebook."""
    m = _exigir_modelo()
    return {
        'nodos': len(m.nodos),
        'columnas': len(TOPOLOGIA.get('columnas', [])),
        'vigas': (len(TOPOLOGIA.get('vigas_x', []))
                  + len(TOPOLOGIA.get('vigas_y', []))),
        'muros': len(TOPOLOGIA.get('muros', [])),
        'brazos': len(TOPOLOGIA.get('brazos', [])),
        'apoyos': len(TOPOLOGIA.get('apoyos', [])),
        'diafragmas': len(TOPOLOGIA.get('diafragmas', [])),
        'area_planta': area_de_planta(),
        'niveles': NIVELES_Z,
    }


# Se construye una vez al importar para que las constantes que
# dependen del modelo (AREA_PLANTA, NODOS_POR_PISO) tengan valor sin
# que el usuario tenga que acordarse de llamar a construir_modelo().
def _inicializar():
    global AREA_PLANTA, NODOS_POR_PISO
    construir_modelo()
    AREA_PLANTA = area_de_planta()
    NODOS_POR_PISO = len(nodos_del_nivel(NIVEL_TIPO))


_inicializar()
