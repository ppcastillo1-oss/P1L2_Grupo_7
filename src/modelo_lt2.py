# -*- coding: utf-8 -*-
r"""
================================================================
 modelo_lt2.py  -  MODELO OPENSEES DEL EDIFICIO LT2
================================================================
 Construye el modelo 3D lineal elastico del edificio LT2 a partir
 de data/geometria_lt2_2024_22.json, que es lo que produjo el
 ingestor de planos (src/planos/).

 Unidades: m, kN, kPa.

 ----------------------------------------------------------------
 DE DONDE SALE CADA COSA
 ----------------------------------------------------------------
 Nada esta escrito a mano. Todo viene del plano, y cada dato dice
 de que lamina salio:

   ejes y posiciones   plantas 101 / 102, registradas entre si
   niveles             las 6 elevaciones (7 cotas, las 6 coinciden)
   pilares 0.70x0.70   medidos del dibujo, confirmados por 'P.70x70'
   muros e=0.20..0.60  medidos, confirmados por 'M.H.A. e=..'
   vigas ancho/alto    ancho medido, alto leido de 'V. 60/80'
   losa e=0.15         atributo ESP de los 22 bloques 'losa-ne'
   hormigon G35_10     nota de la lamina 100: f'c = 35 MPa

 ----------------------------------------------------------------
 COMO SE ARMA LA MALLA (no es una grilla regular)
 ----------------------------------------------------------------
 Este edificio NO es un marco ortogonal de nudos en cada cruce de
 ejes: son 8 pilares y 15 muros repartidos irregularmente. Poner
 nodos en los 10x8 = 80 cruces de la malla de ejes daria 72 nodos
 vacios por piso.

 Entonces los nodos salen de los ELEMENTOS:

   ancla = un punto donde hay algo vertical
           - un pilar   -> su centro
           - un muro    -> el centro de su eje (columna ancha)

 y las vigas se cuelgan de las anclas mas cercanas.

 ----------------------------------------------------------------
 LOS MUROS VAN COMO COLUMNA ANCHA
 ----------------------------------------------------------------
 Un muro es UN elemento vertical en su eje baricentrico, con
 seccion espesor x largo. Su eje fuerte se orienta con 'vecxz':

     vecxz = normal al muro en planta  ->  eje local y a lo largo
                                           del muro  ->  Iz = t*L^3/12

 La relacion I_fuerte/I_debil es (L/t)^2, o sea hasta 1600 en este
 edificio (un muro de 8 m y 20 cm). Un muro mal orientado aporta
 1600 veces menos rigidez Y EL MODELO NO AVISA. Por eso la
 orientacion se verifica en verificar_lt2.py.

 ----------------------------------------------------------------
 LO QUE ESTE MODELO TODAVIA NO HACE  (declarado, no escondido)
 ----------------------------------------------------------------
 1. Se pierde un ~4 % del area de losa por piso: una franja del
    bloque norte (x 31.1 a 35.5, y 33.5 a 37.8, unos 19 m2) esta
    bordeada por dos muros paralelos SIN nada que cierre el pano,
    asi que no forma cara y su carga no entra. Esta medido: la
    auditoria dice cuantos muros quedaron sin area tributaria.

 2. Se supone CONTINUIDAD de muros y pilares hacia arriba: una
    lamina de losa no vuelve a dibujar los muros que ya venian de
    abajo. Sin esa suposicion el ultimo piso quedaba colgando.

 3. Quedan puntos SIN APOYO en el nivel +11.83 (el peor, en
    x = 14.85, y = 20.06). Son extremos de viga de techo que en la
    lamina 102 terminan en el aire. verificar_lt2.py los detecta y
    NO aprueba ese nivel.

 4. La fundacion se reemplaza por empotramiento en z = -7.97.
 5. Lineal elastico. Sin fisuracion, sin no linealidad.
 6. La losa no se modela como placa; solo baja su carga.
 7. Falta la CARGA LINEAL del plano de cargas (tabiques y
    antepechos sobre vigas).

 ----------------------------------------------------------------
 LA CARGA DE LOSA VA POR AREAS TRIBUTARIAS  (como en el P1)
 ----------------------------------------------------------------
 Los panos no vienen dados por una grilla: se encuentran como las
 CARAS del grafo plano de las vigas del piso (panos.py). Cada pano
 se reparte por bisectrices a 45 grados.

 Los muros tambien son borde de pano. En la zona norte de esta
 planta no hay ninguna viga: la losa se apoya directo sobre muros.
 Como un muro es UNA columna ancha en su baricentro, su area
 tributaria va como carga PUNTUAL en su nodo, no repartida.

 Repartir por LARGO DE VIGA -- que es lo que hacia la primera
 version -- conserva la resultante y por lo tanto el equilibrio
 cierra igual de bien, pero reparte mal. En un pano de 10.00 x 3.34
 la viga CORTA recibiria 4.18 m2 donde le tocan 2.79: un 50 % de
 mas. Es el mismo tipo de error del reparto 50/50 de la Semana 1, y
 el equilibrio no lo detecta NUNCA.
================================================================
"""
from __future__ import annotations

import collections
import json
import math
import os

import openseespy.opensees as ops

import malla
import panos

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)

GEOMETRIA = os.path.join(_RAIZ, 'data', 'geometria_lt2_2024_22.json')

# ============================================================
# TOLERANCIAS DE ARMADO  (metros)
# ============================================================
TOL_ANCLA = 0.15      # dos anclas mas cerca que esto son la misma
HOLGURA_PILAR = 0.50  # cuanto puede pasarse una viga del borde del pilar
HOLGURA_MURO = 0.60   # idem, medido contra el EJE del muro
TOL_PANO = 0.30       # con que tolerancia cierran los bordes de un pano
HOLGURA_ESQUINA = 0.10  # holgura para dar dos muros por una esquina

# El peso muerto adicional y la sobrecarga NO se suponen: salen del
# PLANO DE CARGAS (lamina 700), que trae un valor distinto para las
# plantas tipo y para el cielo del piso 4. Estan en el perfil.

# Cuanto mas rigido que una viga es un brazo (lado de la seccion
# equivalente al cuadrado). El brazo NO es una viga: es el pedazo de
# muro entre el extremo real de la viga y el baricentro de la columna
# ancha que representa al muro.
FACTOR_BRAZO = 25.0

# Un elemento vertical, una vez que existe, sigue hacia arriba. Ver
# la explicacion en preparar(). Ponerlo en False deja solo los muros
# y pilares que cada lamina redibuja.
CONTINUIDAD_VERTICAL = True


# ============================================================
# 1. SECCIONES
# ============================================================
def J_rectangular(b, h):
    """
    Torsion de Saint-Venant para seccion rectangular llena.

    NO es min(Iy,Iz)*0.3: esa expresion no corresponde a ninguna
    formula y subestima J varias veces.
    """
    a = max(b, h)
    t = min(b, h)
    return a * t ** 3 * (1.0 / 3.0 - 0.21 * (t / a) * (1.0 - t ** 4 / (12.0 * a ** 4)))


Seccion = collections.namedtuple('Seccion', 'nombre b h A Iy Iz J')


def seccion(nombre, b, h):
    """
    Propiedades en EJES DE LA SECCION, no en los huecos de
    ops.element(). El cruce lo aplica quien construye el elemento,
    segun su geometria. Exportar las inercias ya cruzadas y volver
    a cruzarlas en el otro lado es un error que este proyecto ya
    cometio una vez.

        Iz : inercia para flexion que desplaza en la direccion 'b'
        Iy : inercia para flexion que desplaza en la direccion 'h'
    """
    return Seccion(nombre=nombre, b=b, h=h, A=b * h,
                   Iy=h * b ** 3 / 12.0,
                   Iz=b * h ** 3 / 12.0,
                   J=J_rectangular(b, h))


# ============================================================
# 2. GEOMETRIA DE ANCLAS
# ============================================================
Ancla = collections.namedtuple('Ancla', 'x y tipo datos')


def anclas_de(planta):
    """Los puntos donde hay algo vertical, con su seccion."""
    salida = []
    for q in planta['pilares']:
        salida.append(Ancla(x=q['x'], y=q['y'], tipo='pilar', datos=q))
    for m in planta['muros']:
        salida.append(Ancla(x=(m['x1'] + m['x2']) / 2.0,
                            y=(m['y1'] + m['y2']) / 2.0,
                            tipo='muro', datos=m))
    return salida


def fusionar(anclas, tol=TOL_ANCLA):
    """
    Junta anclas que son la misma cosa vista en dos laminas.

    Se conserva el pilar por sobre el muro cuando coinciden: un
    pilar embebido en un muro se dibuja en las dos capas.
    """
    salida = []
    for a in anclas:
        for i, b in enumerate(salida):
            if math.hypot(a.x - b.x, a.y - b.y) <= tol:
                if a.tipo == 'pilar' and b.tipo != 'pilar':
                    salida[i] = a
                break
        else:
            salida.append(a)
    return salida


def _huella(a):
    """Radio en planta de un ancla: hasta donde llega su hormigon."""
    if a.tipo == 'pilar':
        return max(a.datos['b'], a.datos['h']) / 2.0
    return a.datos['espesor'] / 2.0


def _eje(a):
    """El eje del muro como segmento. None para un pilar."""
    if a.tipo == 'pilar':
        return None
    m = a.datos
    return (m['x1'], m['y1'], m['x2'], m['y2'])


def _se_tocan(a, b):
    """
    True si los dos elementos verticales son una sola pieza de
    hormigon: sus huellas en planta se solapan.

    El criterio no es una distancia inventada -- es la suma de las dos
    semihuellas mas una holgura chica. Un muro de 0.60 y uno de 0.30
    se tocan si sus ejes llegan a 0.45 m; un pilar de 0.70 y un muro
    de 0.25, a 0.475 m.

    Se mide contra el CUERPO del otro, no contra su punta. En una L se
    tocan las dos puntas, pero en una T la punta de un muro topa
    contra el costado del otro a media altura, y un pilar puede estar
    embebido en el extremo de un muro.
    """
    limite = _huella(a) + _huella(b) + HOLGURA_ESQUINA
    ea, eb = _eje(a), _eje(b)
    if ea is None and eb is None:
        return math.hypot(a.x - b.x, a.y - b.y) <= limite
    if ea is None:
        return _dist_a_segmento(a.x, a.y, *eb) <= limite
    if eb is None:
        return _dist_a_segmento(b.x, b.y, *ea) <= limite
    for p in ((ea[0], ea[1]), (ea[2], ea[3])):
        if _dist_a_segmento(p[0], p[1], *eb) <= limite:
            return True
    for p in ((eb[0], eb[1]), (eb[2], eb[3])):
        if _dist_a_segmento(p[0], p[1], *ea) <= limite:
            return True
    return False


def _punto_de_union(a, b):
    """
    Por donde tiene que pasar la union de dos elementos verticales que
    se tocan, para que el borde del pano gire en ANGULO RECTO:

      - muro con muro no paralelos : el cruce de sus dos ejes;
      - pilar con muro            : el pilar proyectado sobre el eje
                                    del muro;
      - ejes paralelos o dos pilares : None, el brazo va directo.
    """
    ea, eb = _eje(a), _eje(b)
    if ea is None and eb is None:
        return None
    if ea is None:
        return _proyectar(a.x, a.y, *eb)
    if eb is None:
        return _proyectar(b.x, b.y, *ea)
    return _cruce_de_ejes(a.datos, b.datos)


def _partir_en_los_nodos(nodos, brazos, tol=0.05):
    """
    Parte cada brazo en los nodos que caen ENCIMA de el.

    Dos aristas superpuestas rompen la busqueda de panos, y no de una
    forma que se note: el recorrido de caras decide por donde seguir
    ordenando los vecinos POR ANGULO, y dos vecinos colineales tienen
    el mismo angulo. Al elegir el equivocado el recorrido se salta un
    nodo, la cara interior se funde con la exterior y desaparece.

    Paso en el LT2 con la puerta del muro oriente: el brazo directo
    entre los dos tramos pasaba por encima del nodo de esquina que
    los une con el muro transversal. Se perdio un pano de 45 m2 sin
    ningun error.
    """
    salida, partidos = [], 0
    for b in brazos:
        xi, yi = nodos[b.i].x, nodos[b.i].y
        xj, yj = nodos[b.j].x, nodos[b.j].y
        L = math.hypot(xj - xi, yj - yi)
        if L < 1e-9:
            continue
        ux, uy = (xj - xi) / L, (yj - yi) / L
        encima = [(0.0, b.i), (L, b.j)]
        for idx, n in enumerate(nodos):
            if idx in (b.i, b.j):
                continue
            t = (n.x - xi) * ux + (n.y - yi) * uy
            if not (tol < t < L - tol):
                continue
            if abs(-(n.x - xi) * uy + (n.y - yi) * ux) <= tol:
                encima.append((t, idx))
        if len(encima) > 2:
            partidos += 1
        cadena = [i for _t, i in sorted(encima)]
        for a, c in zip(cadena, cadena[1:]):
            if a == c:
                continue
            d = math.hypot(nodos[c].x - nodos[a].x, nodos[c].y - nodos[a].y)
            if d > 1e-9:
                salida.append(malla.Tramo(i=a, j=c, largo=d, viga=None))
    return salida, partidos


def _cruce_de_ejes(ma, mb):
    """
    Punto donde se cruzan los ejes (las RECTAS, no los tramos) de dos
    muros. None si son paralelos -- dos tramos del mismo muro a los
    lados de una puerta, por ejemplo.
    """
    x1, y1, x2, y2 = ma['x1'], ma['y1'], ma['x2'], ma['y2']
    x3, y3, x4, y4 = mb['x1'], mb['y1'], mb['x2'], mb['y2']
    d1x, d1y = x2 - x1, y2 - y1
    d2x, d2y = x4 - x3, y4 - y3
    den = d1x * d2y - d1y * d2x
    L1 = math.hypot(d1x, d1y)
    L2 = math.hypot(d2x, d2y)
    if L1 < 1e-9 or L2 < 1e-9 or abs(den) < 1e-6 * L1 * L2:
        return None
    t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / den
    return (x1 + t * d1x, y1 + t * d1y)


def _proyectar(px, py, x1, y1, x2, y2):
    """Pie de la perpendicular de (px,py) sobre la RECTA del segmento."""
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return (x1, y1)
    t = ((px - x1) * dx + (py - y1) * dy) / L2
    return (x1 + t * dx, y1 + t * dy)


def _dist_a_segmento(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0.0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def ancla_para(px, py, anclas):
    """
    A que ancla se cuelga un extremo de viga.

    Contra un PILAR se mide al centro; contra un MURO se mide al
    EJE del muro (no a su centro), porque una viga puede llegar a
    cualquier punto a lo largo del muro. El nodo, eso si, es
    siempre el baricentro: el muro es UNA columna ancha.
    """
    mejor, mejor_d = None, None
    for i, a in enumerate(anclas):
        if a.tipo == 'pilar':
            limite = max(a.datos['b'], a.datos['h']) / 2.0 + HOLGURA_PILAR
            d = math.hypot(px - a.x, py - a.y)
        else:
            m = a.datos
            limite = m['espesor'] / 2.0 + HOLGURA_MURO
            d = _dist_a_segmento(px, py, m['x1'], m['y1'], m['x2'], m['y2'])
        if d <= limite and (mejor_d is None or d < mejor_d):
            mejor, mejor_d = i, d
    return mejor


# ============================================================
# 3. EL MODELO
# ============================================================
class ModeloLT2(object):

    def __init__(self, ruta=GEOMETRIA):
        with open(ruta, encoding='utf-8') as f:
            self.geo = json.load(f)

        hm = self.geo['materiales']['hormigon']
        self.fc = hm['fc_MPa']
        self.poisson = hm['poisson']
        self.gamma = hm['peso_especifico_kNm3']
        self.Ec = 4700.0 * math.sqrt(self.fc) * 1000.0        # kPa
        self.Gc = self.Ec / (2.0 * (1.0 + self.poisson))

        nm = self.geo['niveles_del_modelo']
        self.z_base = nm['base']
        self.pisos = nm['pisos']
        self.niveles = [self.z_base] + [p['z'] for p in self.pisos]

        self.espesor_losa = self.geo['losas']['auditoria']['espesor_dominante']
        self.peso_losa = self.espesor_losa * self.gamma      # kN/m2

        # Cargas por lamina, desde el plano de cargas (kgf/m2 -> kN/m2).
        cargas = self.geo.get('cargas', {})
        g = cargas.get('g_ms2', 9.80665)
        self.cargas_lamina = {}
        for lamina, c in cargas.get('por_lamina', {}).items():
            self.cargas_lamina[lamina] = {
                'muerta': self.peso_losa + c['peso_muerto_adicional_kgf_m2'] * g / 1000.0,
                'viva': c['sobrecarga_kgf_m2'] * g / 1000.0,
            }

        self.avisos = []
        self.dinteles_supuestos = set()
        # Puntos donde el plano rotula un pano de losa. Sirven para
        # distinguir una cara con losa de un hueco (ver panos.py).
        self.rotulos_de_losa = [
            (p['x'], p['y'])
            for p in self.geo.get('losas', {}).get('panos', [])]
        self.secciones = {}
        self._construido = False

    # --------------------------------------------------------
    def _sec(self, nombre, b, h):
        if nombre not in self.secciones:
            self.secciones[nombre] = seccion(nombre, b, h)
        return self.secciones[nombre]

    def _planta(self, lamina):
        return self.geo['plantas'][lamina]

    # --------------------------------------------------------
    def preparar(self):
        """Arma nodos, elementos y cargas EN PYTHON, sin tocar OpenSees.

        Separar el armado del ensamblado permite auditar la malla
        (cuantos nodos, que quedo suelto, que se descarto) antes de
        que OpenSees opine. Cuando la matriz sale singular, OpenSees
        dice "U(i,i) = 0" y no dice cual es el elemento culpable.
        """
        planta_de_piso = [p['lamina'] for p in self.pisos]

        # --- anclas por nivel -------------------------------
        # El piso k va de niveles[k] a niveles[k+1] y su geometria es
        # la de la lamina del CIELO. Un nivel necesita las anclas del
        # piso de abajo Y del de arriba, para que una columna que
        # sigue subiendo tenga nodo donde apoyarse.
        # Los verticales de cada piso, con CONTINUIDAD hacia arriba.
        #
        # Una lamina de losa no vuelve a dibujar los muros que ya
        # venian de abajo. La 102 ("cielo piso 4") trae 9 muros donde
        # la 101 trae 15, pero SI dibuja vigas de techo encima de esos
        # muros que no redibuja. Sin continuidad, esas vigas quedan
        # colgando de la nada: el ultimo piso daba -192 mm mientras el
        # resto del edificio daba -3.
        #
        # La regla es que un elemento vertical, una vez que existe,
        # sigue hacia arriba mientras haya piso encima. Es una
        # SUPOSICION -- razonable y la norma en un edificio, pero
        # suposicion -- y esta declarada como tal.
        self.verticales_de_piso = []
        heredados = []
        for k in range(len(self.pisos)):
            propios = anclas_de(self._planta(planta_de_piso[k]))
            juntos = fusionar(propios + heredados)
            self.continuados = len(juntos) - len(fusionar(propios))
            self.verticales_de_piso.append(juntos)
            heredados = juntos if CONTINUIDAD_VERTICAL else []

        self.anclas_nivel = []
        for k in range(len(self.niveles)):
            acumula = []
            if k > 0:
                acumula += self.verticales_de_piso[k - 1]
            if k < len(self.pisos):
                acumula += self.verticales_de_piso[k]
            self.anclas_nivel.append(fusionar(acumula))

        # --- mallar cada nivel ------------------------------
        # malla.mallar() pone las anclas PRIMERO en su lista de nodos,
        # asi que el indice de un ancla se conserva. De eso depende
        # que los elementos verticales encuentren su nodo arriba y
        # abajo.
        self.malla_nivel = []
        self.auditoria_malla = []
        for k in range(len(self.niveles)):
            anclas = [self._como_dict(a) for a in self.anclas_nivel[k]]
            vigas = self._vigas_de_nivel(k, planta_de_piso)
            nodos, tramos, brazos, aud = malla.mallar(anclas, vigas)
            if k > 0:
                nodos, brazos, aud_esq = self._cerrar_esquinas(k, nodos, brazos)
                aud.update(aud_esq)
            self.malla_nivel.append((nodos, tramos, brazos))
            self.auditoria_malla.append(aud)

        # --- nodos ------------------------------------------
        self.nodos = {}           # tag -> (x, y, z)
        self.nodo_de = {}         # (nivel, indice_en_la_malla) -> tag
        tag = 1
        for k, z in enumerate(self.niveles):
            for i, n in enumerate(self.malla_nivel[k][0]):
                self.nodos[tag] = (n.x, n.y, z)
                self.nodo_de[(k, i)] = tag
                tag += 1
        self._siguiente_tag = tag

        # --- elementos verticales ---------------------------
        self.verticales = []      # (tag, n1, n2, seccion, vecxz, tipo, peso)
        etag = 1
        for k in range(len(self.pisos)):
            lamina = planta_de_piso[k]
            altura = self.niveles[k + 1] - self.niveles[k]

            for a in self.verticales_de_piso[k]:
                i_ab = self._indice(self.anclas_nivel[k], a)
                i_ar = self._indice(self.anclas_nivel[k + 1], a)
                if i_ab is None or i_ar is None:
                    self.avisos.append(
                        'piso %d: un %s en (%.2f, %.2f) no encontro nodo '
                        'arriba o abajo' % (k + 1, a.tipo, a.x, a.y))
                    continue

                if a.tipo == 'pilar':
                    b, h = a.datos['b'], a.datos['h']
                    sec = self._sec('P %.2fx%.2f' % (b, h), b, h)
                    vecxz = (1.0, 0.0, 0.0)
                else:
                    m = a.datos
                    L, t = m['largo'], m['espesor']
                    sec = self._sec('M %.2fx%.2f' % (t, L), t, L)
                    # normal al muro en planta: deja el eje local y a
                    # lo largo del muro, o sea Iz = t*L^3/12 (fuerte)
                    ux = (m['x2'] - m['x1']) / L
                    uy = (m['y2'] - m['y1']) / L
                    vecxz = (-uy, ux, 0.0)

                peso = sec.A * altura * self.gamma
                self.verticales.append(
                    (etag, self.nodo_de[(k, i_ab)], self.nodo_de[(k + 1, i_ar)],
                     sec, vecxz, a.tipo, peso))
                etag += 1

        # --- vigas (ya partidas en tramos) ------------------
        self.vigas = []           # (tag, n1, n2, seccion, largo, peso, nivel)
        self.brazos = []          # (tag, n1, n2, seccion, largo, nivel)
        for k in range(1, len(self.niveles)):
            _nodos, tramos, brazos = self.malla_nivel[k]
            for t in tramos:
                v = t.viga
                sec = self._sec('V %.2fx%.2f' % (v['ancho'], v['alto']),
                                v['ancho'], v['alto'])
                peso = sec.A * t.largo * self.gamma
                self.vigas.append((etag, self.nodo_de[(k, t.i)],
                                   self.nodo_de[(k, t.j)], sec, t.largo, peso, k))
                etag += 1

            # Brazos: el tramo de muro entre el extremo real de la
            # viga y el baricentro donde vive la columna ancha. No
            # llevan peso propio (ya esta contado en el muro) ni
            # carga de losa: no son estructura nueva, son el muro.
            for b in brazos:
                self.brazos.append((etag, self.nodo_de[(k, b.i)],
                                    self.nodo_de[(k, b.j)], self._sec_brazo(),
                                    b.largo, k))
                etag += 1

        self._podar_lo_que_no_llega_al_suelo()
        self._areas_tributarias()
        self._construido = True
        return self

    # --------------------------------------------------------
    def _areas_tributarias(self):
        """
        Reparte la losa de cada piso a sus vigas por AREAS
        TRIBUTARIAS a 45 grados, el mismo criterio del P1.

        Los panos no vienen dados: se encuentran como las caras del
        grafo plano que forman las vigas del piso (ver panos.py).
        De paso, la suma de las areas de los panos da el AREA DE
        PLANTA DE VERDAD, en vez de la envolvente convexa.

        Se corre DESPUES de la poda: si un elemento no llego al
        modelo, su area tributaria tampoco tiene que llegar.
        """
        self.area_trib = {}       # (tag1, tag2) -> m2, carga repartida
        self.poli_trib = {}       # (tag1, tag2) -> [poligono, ...]
        self.area_trib_nodal = {}  # tag -> m2, carga puntual (muros)
        self.poli_trib_nodal = {}  # tag -> [poligono, ...]
        self.area_piso = {}
        self.aud_panos = {}
        self.grafo_pano = {}   # nivel -> (puntos, aristas), para auditar

        for k in range(1, len(self.niveles)):
            z = self.niveles[k]
            tags = [t for t, (_x, _y, zz) in self.nodos.items() if abs(zz - z) < 1e-9]
            if len(tags) < 4:
                continue
            indice = {t: i for i, t in enumerate(tags)}
            puntos = [(self.nodos[t][0], self.nodos[t][1]) for t in tags]

            def nodo_2d(x, y):
                """Indice del punto (x, y); lo agrega si no estaba."""
                for i, (px, py) in enumerate(puntos):
                    if math.hypot(px - x, py - y) <= TOL_PANO:
                        return i
                puntos.append((x, y))
                return len(puntos) - 1

            aristas, de_viga = [], {}
            for _e, n1, n2, _s, _L, _p, kk in self.vigas:
                if kk == k:
                    a = (indice[n1], indice[n2])
                    aristas.append(a)
                    de_viga[(min(a), max(a))] = (n1, n2)
            # Los brazos son pedazos de muro, y la losa tambien se
            # apoya en ellos: sin incluirlos, los panos que bordean
            # un muro no cierran y su carga se perderia.
            for _e, n1, n2, _s, _L, kk in self.brazos:
                if kk == k:
                    a = (indice[n1], indice[n2])
                    aristas.append(a)
                    de_viga[(min(a), max(a))] = (n1, n2)

            # --- los MUROS tambien son borde de pano ---------
            # En la zona norte de esta planta (ejes 8A y 8B) no hay
            # ninguna viga: la losa se apoya directamente sobre los
            # muros. Sin estas aristas esos panos no cierran y su
            # carga -- casi la mitad del piso -- desaparece del
            # modelo sin que el equilibrio se entere, porque el
            # equilibrio compara contra la carga APLICADA.
            #
            # Un muro es UNA columna ancha en su baricentro, asi que
            # su area tributaria no puede ir repartida: va como carga
            # PUNTUAL en su nodo, que es estaticamente equivalente.
            de_muro = {}
            for a in self.verticales_de_piso[k - 1]:
                if a.tipo != 'muro':
                    continue
                i_ancla = self._indice(self.anclas_nivel[k], a)
                if i_ancla is None:
                    continue
                tag = self.nodo_de[(k, i_ancla)]
                if tag not in self.nodos:
                    continue
                m = a.datos
                # El muro entra PARTIDO en cada nodo que cae sobre su
                # eje: su baricentro (donde vive su barra y donde
                # llegan los brazos) y los nodos de esquina donde se
                # cruza con otro muro.
                #
                # Con el muro entero de punta a punta, esos nodos
                # quedaban FUERA del borde y el pano no cerraba: eran
                # 46 m2 del bloque oriente con el baricentro, y otros
                # 44 con los nodos de esquina.
                largo = math.hypot(m['x2'] - m['x1'], m['y2'] - m['y1'])
                if largo < 1e-9:
                    continue
                ux = (m['x2'] - m['x1']) / largo
                uy = (m['y2'] - m['y1']) / largo
                sobre_el_eje = []
                for idx, (px, py) in enumerate(list(puntos)):
                    t = (px - m['x1']) * ux + (py - m['y1']) * uy
                    if not (-TOL_PANO <= t <= largo + TOL_PANO):
                        continue
                    perp = abs(-(px - m['x1']) * uy + (py - m['y1']) * ux)
                    if perp <= TOL_PANO:
                        sobre_el_eje.append((t, idx))
                sobre_el_eje.append((0.0, nodo_2d(m['x1'], m['y1'])))
                sobre_el_eje.append((largo, nodo_2d(m['x2'], m['y2'])))
                sobre_el_eje.append((
                    (a.x - m['x1']) * ux + (a.y - m['y1']) * uy,
                    nodo_2d(a.x, a.y)))
                cadena = []
                for _t, idx in sorted(sobre_el_eje):
                    if not cadena or cadena[-1] != idx:
                        cadena.append(idx)
                for par in zip(cadena, cadena[1:]):
                    if par[0] == par[1]:
                        continue
                    aristas.append(par)
                    de_muro[(min(par), max(par))] = tag

            self.grafo_pano[k] = (list(puntos), list(aristas))
            areas, polis, aud = panos.repartir_piso(
                puntos, aristas, rotulos_de_losa=self.rotulos_de_losa)
            for clave, a in areas.items():
                if clave in de_muro:
                    tag = de_muro[clave]
                    self.area_trib_nodal[tag] = self.area_trib_nodal.get(tag, 0.0) + a
                    if clave in polis:
                        self.poli_trib_nodal.setdefault(tag, []).extend(polis[clave])
                elif clave in de_viga:
                    t1, t2 = de_viga[clave]
                    par = (min(t1, t2), max(t1, t2))
                    self.area_trib[par] = a
                    if clave in polis:
                        self.poli_trib[par] = polis[clave]

            aud['area_a_muros'] = round(
                sum(a for c, a in areas.items() if c in de_muro), 2)
            aud['area_a_vigas'] = round(
                sum(a for c, a in areas.items() if c in de_viga), 2)
            self.area_piso[k] = aud['area_total']
            self.aud_panos[k] = aud

    # --------------------------------------------------------
    def _cerrar_esquinas(self, k, nodos, brazos):
        """
        Cierra en ANGULO RECTO las esquinas donde dos muros son una
        sola pieza de hormigon.

        El problema no es que falte la union: es POR DONDE va.

        Un muro se modela como una columna ancha en su baricentro. Si
        se unen dos baricentros con un brazo directo, el brazo cruza
        la esquina EN DIAGONAL. Estructuralmente da casi lo mismo,
        pero el borde del pano pasa a ser esa diagonal y el area
        tributaria de la esquina sale triangulada en vez de
        rectangular. En el visor se ve como un corte a 45 grados
        comiendose el vertice, y en el nucleo de ascensores como un
        escalonamiento.

        Lo que hay ahi de verdad es hormigon a lo largo de los dos
        muros hasta el punto donde se cruzan sus EJES. Asi que se
        pone un nodo en ese cruce y se va con dos brazos:

            baricentro A  --->  cruce de ejes  --->  baricentro B

        Los dos brazos corren A LO LARGO de su muro, el borde del pano
        gira en angulo recto y la esquina queda rectangular.

        Dos muros COLINEALES (los dos tramos a cada lado de una
        puerta) no tienen cruce de ejes: ahi el brazo directo ya va
        sobre el eje y se deja como esta.
        """
        nodos = list(nodos)
        brazos = list(brazos)
        verticales = list(enumerate(self.anclas_nivel[k]))

        def nodo_en(x, y):
            for i, n in enumerate(nodos):
                if math.hypot(n.x - x, n.y - y) <= TOL_ANCLA:
                    return i
            nodos.append(malla.Nodo(x=x, y=y, tipo='esquina', datos=None))
            return len(nodos) - 1

        def arma(i, j):
            if i == j:
                return
            L = math.hypot(nodos[i].x - nodos[j].x, nodos[i].y - nodos[j].y)
            if L < 1e-6:
                return
            brazos.append(malla.Tramo(i=i, j=j, largo=L, viga=None))

        en_angulo, directas = 0, 0
        for ii in range(len(verticales)):
            for jj in range(ii + 1, len(verticales)):
                ia, a = verticales[ii]
                ib, b = verticales[jj]
                if not _se_tocan(a, b):
                    continue
                punto = _punto_de_union(a, b)
                if punto is None:
                    # No hay un punto de giro: los dos ejes son la
                    # misma recta (dos tramos de muro a los lados de
                    # una puerta) o son dos pilares. El brazo directo
                    # ya va por donde corresponde.
                    arma(ia, ib)
                    directas += 1
                    continue
                ic = nodo_en(punto[0], punto[1])
                arma(ia, ic)
                arma(ic, ib)
                en_angulo += 1

        brazos, partidos = _partir_en_los_nodos(nodos, brazos)
        return nodos, brazos, {'esquinas_en_angulo': en_angulo,
                               'esquinas_directas': directas,
                               'brazos_partidos': partidos}

    # --------------------------------------------------------
    def _podar_lo_que_no_llega_al_suelo(self):
        """
        Todo pedazo de estructura tiene que poder bajar la carga
        hasta un apoyo. Lo que no, es un mecanismo.

        malla.py ya verifica la conectividad DENTRO de cada piso,
        pero eso no alcanza: un muro que aparece en la lamina 102 y
        no en la 101 genera un tramo vertical entre +7.87 y +11.83
        con NADA debajo. En el plano de cada piso se ve conectado; en
        3D es un palo colgando.

        Sintoma cuando esto pasa: el analisis "corre" y devuelve
        UZ = -1.2e14 mm. LAPACK no siempre falla con la matriz
        singular: a veces devuelve un numero enorme, que es peor,
        porque parece un resultado.
        """
        padre = {t: t for t in self.nodos}

        def raiz(i):
            while padre[i] != i:
                padre[i] = padre[padre[i]]
                i = padre[i]
            return i

        def unir(i, j):
            ri, rj = raiz(i), raiz(j)
            if ri != rj:
                padre[rj] = ri

        for _e, n1, n2, _s, _v, _t, _p in self.verticales:
            unir(n1, n2)
        for _e, n1, n2, _s, _L, _p, _k in self.vigas:
            unir(n1, n2)
        for _e, n1, n2, _s, _L, _k in self.brazos:
            unir(n1, n2)

        en_el_suelo = {raiz(t) for t, (_x, _y, z) in self.nodos.items()
                       if abs(z - self.z_base) < 1e-9}

        v_antes, b_antes = len(self.verticales), len(self.vigas)
        self.podados = [
            {'tipo': tipo, 'nodo': n1,
             'posicion': [round(c, 2) for c in self.nodos[n1]]}
            for (_e, n1, _n2, _s, _v, tipo, _p) in self.verticales
            if raiz(n1) not in en_el_suelo]

        self.verticales = [v for v in self.verticales
                           if raiz(v[1]) in en_el_suelo]
        self.vigas = [v for v in self.vigas if raiz(v[1]) in en_el_suelo]
        self.brazos = [b for b in self.brazos if raiz(b[1]) in en_el_suelo]

        usados = set()
        for _e, n1, n2, *_r in self.verticales:
            usados.add(n1); usados.add(n2)
        for _e, n1, n2, *_r in self.vigas:
            usados.add(n1); usados.add(n2)
        for _e, n1, n2, *_r in self.brazos:
            usados.add(n1); usados.add(n2)

        self.nodos = {t: p for t, p in self.nodos.items() if t in usados}
        self.podado_resumen = {
            'verticales_descartados': v_antes - len(self.verticales),
            'vigas_descartadas': b_antes - len(self.vigas),
            'detalle': self.podados[:10],
        }

    def _sec_brazo(self):
        """Seccion del brazo rigido.

        Un brazo representa un pedazo de MURO, no una viga: tiene que
        ser mucho mas rigido que la viga que llega, o vuelve a
        aparecer la flexibilidad inventada que se queria evitar.
        Se usa la seccion de viga mas grande escalada por
        FACTOR_BRAZO. Que el resultado no dependa del factor se
        comprueba en verificar_lt2.py barriendolo.
        """
        if 'BRAZO' not in self.secciones:
            b = h = math.sqrt(FACTOR_BRAZO) * 0.8
            self.secciones['BRAZO'] = seccion('BRAZO', b, h)
        return self.secciones['BRAZO']

    # --------------------------------------------------------
    @staticmethod
    def _como_dict(a):
        """Un ancla, en la forma que espera malla.mallar()."""
        if a.tipo == 'pilar':
            alcance = max(a.datos['b'], a.datos['h']) / 2.0 + HOLGURA_PILAR
        else:
            alcance = a.datos['espesor'] / 2.0 + HOLGURA_MURO
        return {'x': a.x, 'y': a.y, 'tipo': a.tipo,
                'alcance': alcance, 'datos': a.datos}

    def _vigas_de_nivel(self, k, planta_de_piso):
        """
        Vigas que van en el nivel k.

        El nivel k es el CIELO del piso k, asi que sus vigas salen de
        la lamina del piso k. El nivel 0 (la base) no lleva vigas: la
        fundacion se reemplaza por empotramiento.

        A las vigas sin alto conocido se les pone la seccion mas
        repetida de su lamina. Descartarlas seria peor: dejan huecos
        en la malla y desconectan vigas que si estaban bien leidas.
        """
        if k == 0:
            return []
        vigas = list(self._planta(planta_de_piso[k - 1])['vigas'])
        conocidas = [v for v in vigas if v['alto']]
        if not conocidas:
            return []
        dominante = collections.Counter(
            (v['ancho'], v['alto']) for v in conocidas).most_common(1)[0][0]

        salida = []
        for v in vigas:
            if v['alto'] is None:
                v = dict(v, ancho=dominante[0], alto=dominante[1],
                         alto_supuesto=True)
                self.avisos.append(
                    'nivel %+.2f: viga sin alto en el plano; se le puso la '
                    'seccion mas repetida %.2fx%.2f'
                    % (self.niveles[k], dominante[0], dominante[1]))
            salida.append(v)

        # DINTELES SUPUESTOS -- declarados en el perfil, no leidos del
        # plano. Un vano entre dos muros (una puerta, el acceso a la
        # caja de ascensores) deja el borde de la losa sin nada, y el
        # modelo no puede saber solo si ahi hay dintel o si la losa
        # vuela. Se declara en el perfil, con nombre y con el porque,
        # y aparece en la auditoria como supuesto.
        for d in self.geo.get('perfil_dinteles', []):
            if d.get('desde_nivel', 1) <= k <= d.get('hasta_nivel', 99):
                salida.append(dict(d['viga'], supuesta=True,
                                   nombre=d.get('nombre', 'dintel')))
                self.dinteles_supuestos.add(d.get('nombre', 'dintel'))
        return salida

    @staticmethod
    def _indice(anclas, a, tol=TOL_ANCLA):
        for i, b in enumerate(anclas):
            if math.hypot(a.x - b.x, a.y - b.y) <= tol:
                return i
        return None

    # --------------------------------------------------------
    def area_de_planta(self):
        """
        Area de losa por piso.

        Se toma la envolvente convexa de los nodos del piso tipo. Es
        una COTA SUPERIOR si la planta es irregular; se reporta al
        lado del rectangulo de la malla de ejes para poder juzgarla.
        Con el borde de losa del plano cerrado esto se reemplaza por
        el area de verdad.
        """
        pts = sorted({(round(n.x, 3), round(n.y, 3))
                      for n in self.malla_nivel[1][0]})
        if len(pts) < 3:
            return 0.0
        # envolvente convexa (monotone chain)
        def cruz(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        abajo = []
        for p in pts:
            while len(abajo) >= 2 and cruz(abajo[-2], abajo[-1], p) <= 0:
                abajo.pop()
            abajo.append(p)
        arriba = []
        for p in reversed(pts):
            while len(arriba) >= 2 and cruz(arriba[-2], arriba[-1], p) <= 0:
                arriba.pop()
            arriba.append(p)
        casco = abajo[:-1] + arriba[:-1]
        area = 0.0
        for i in range(len(casco)):
            x1, y1 = casco[i]
            x2, y2 = casco[(i + 1) % len(casco)]
            area += x1 * y2 - x2 * y1
        return abs(area) / 2.0

    # --------------------------------------------------------
    def ensamblar(self, caso='G', con_diafragmas=True, girar_muros=False):
        """
        Construye el modelo en OpenSees y aplica el caso de carga.

        caso=None construye sin aplicar ninguna carga: sirve para
        armar el modelo y despues cargarlo a mano (una carga lateral
        para verificar el diafragma, por ejemplo).

        girar_muros=True gira 90 grados el eje fuerte de TODOS los
        muros. No es una opcion de modelacion: es un experimento de
        control. Un muro tiene hasta 1000 veces mas inercia en un eje
        que en el otro, asi que si el resultado no cambia al girarlos,
        los muros no estaban tomando nada.
        """
        if not self._construido:
            self.preparar()

        ops.wipe()
        ops.model('basic', '-ndm', 3, '-ndf', 6)

        for tag, (x, y, z) in self.nodos.items():
            ops.node(tag, x, y, z)

        # apoyos: empotramiento en la base
        self.nodos_base = [t for t, (_x, _y, z) in self.nodos.items()
                           if abs(z - self.z_base) < 1e-9]
        for t in self.nodos_base:
            ops.fix(t, 1, 1, 1, 1, 1, 1)

        # transformaciones: una por vecxz distinto
        self._transf = {}
        def transf(vecxz):
            clave = tuple(round(c, 6) for c in vecxz)
            if clave not in self._transf:
                tag = len(self._transf) + 1
                ops.geomTransf('Linear', tag, *clave)
                self._transf[clave] = tag
            return self._transf[clave]

        # --- elementos verticales ---------------------------
        # Verticales: los ejes locales NO se cruzan (el eje local y
        # queda donde lo pone vecxz).
        for etag, n1, n2, sec, vecxz, tipo, _peso in self.verticales:
            if girar_muros and tipo == 'muro':
                # Girar 90 grados en planta el eje fuerte del muro.
                vecxz = (-vecxz[1], vecxz[0], 0.0)
            ops.element('elasticBeamColumn', etag, n1, n2, sec.A,
                        self.Ec, self.Gc, sec.J, sec.Iy, sec.Iz,
                        transf(vecxz))

        # --- vigas ------------------------------------------
        # Horizontales con vecxz = (0,0,1): el eje local z queda
        # VERTICAL, asi que la flexion por gravedad es alrededor del
        # eje local y. Por eso la inercia de gravedad (Iz de la
        # seccion) va en el hueco de Iy. Este cruce es la fuente de
        # error clasica del proyecto: se aplica UNA sola vez, aca.
        tv = transf((0.0, 0.0, 1.0))
        for etag, n1, n2, sec, _L, _peso, _k in self.vigas:
            ops.element('elasticBeamColumn', etag, n1, n2, sec.A,
                        self.Ec, self.Gc, sec.J, sec.Iz, sec.Iy, tv)

        for etag, n1, n2, sec, _L, _k in self.brazos:
            ops.element('elasticBeamColumn', etag, n1, n2, sec.A,
                        self.Ec, self.Gc, sec.J, sec.Iz, sec.Iy, tv)

        # --- diafragmas rigidos -----------------------------
        self.maestros = {}
        for k in (range(1, len(self.niveles)) if con_diafragmas else ()):
            z = self.niveles[k]
            nodos_piso = [self.nodo_de[(k, i)]
                          for i in range(len(self.malla_nivel[k][0]))
                          if self.nodo_de[(k, i)] in self.nodos]
            if len(nodos_piso) < 2:
                continue
            xs = [self.nodos[t][0] for t in nodos_piso]
            ys = [self.nodos[t][1] for t in nodos_piso]
            maestro = self._siguiente_tag
            self._siguiente_tag += 1
            ops.node(maestro, sum(xs) / len(xs), sum(ys) / len(ys), z)
            # El maestro no tiene elementos: sus GDL fuera del plano
            # del diafragma quedarian sueltos y la matriz singular.
            ops.fix(maestro, 0, 0, 1, 1, 1, 0)
            ops.rigidDiaphragm(3, maestro, *nodos_piso)
            self.maestros[k] = maestro

        if caso is not None:
            self.aplicar_cargas(caso)
        return self

    # --------------------------------------------------------
    def aplicar_cargas(self, caso):
        """
        Caso G  : peso propio + losa + terminaciones
        Caso Q  : sobrecarga sobre la losa

        Tres caminos, y cada uno esta donde esta por una razon:

        1. PESO PROPIO de columnas y muros -> carga NODAL, mitad a
           cada extremo. Es exacto y evita discutir en que eje local
           cae la gravedad de una columna.

        2. PESO PROPIO de vigas y LOSA -> carga DISTRIBUIDA sobre la
           viga (eleLoad -beamUniform). La losa se reparte por AREAS
           TRIBUTARIAS a 45 grados (self.area_trib, ver panos.py):

               w = q * A_trib / L        =>   w*L = q*A

           No por largo de viga. Los dos repartos conservan la
           resultante --lo unico que el equilibrio puede comprobar--
           pero repartir por largo sobrecarga la viga corta de un
           pano alargado un 50 %.

        3. LOSA QUE APOYA DIRECTO SOBRE UN MURO -> carga PUNTUAL en
           su baricentro (self.area_trib_nodal). Un muro se modela
           como UNA columna ancha, asi que su area tributaria no
           puede ir repartida; el punto es estaticamente equivalente.

        Con vecxz = (0,0,1) el eje local z de la viga es el vertical,
        asi que la gravedad va en el SEGUNDO valor de beamUniform y
        con signo negativo.
        """
        ops.timeSeries('Linear', 1)
        ops.pattern('Plain', 1, 1)

        self.carga_total = 0.0
        self.area_planta = sum(self.area_piso.values()) / max(1, len(self.area_piso))

        if caso == 'G':
            # peso propio de columnas y muros
            for _etag, n1, n2, _sec, _v, _t, peso in self.verticales:
                ops.load(n1, 0, 0, -peso / 2.0, 0, 0, 0)
                ops.load(n2, 0, 0, -peso / 2.0, 0, 0, 0)
                self.carga_total += peso
            # peso propio de vigas, distribuido
            for etag, _n1, _n2, sec, L, peso, _k in self.vigas:
                w = sec.A * self.gamma
                ops.eleLoad('-ele', etag, '-type', '-beamUniform', 0.0, -w, 0.0)
                self.carga_total += peso

        # losa: a cada viga le llega la carga de SU area tributaria
        planta_de_piso = [p['lamina'] for p in self.pisos]
        for k in range(1, len(self.niveles)):
            c = self.cargas_lamina.get(planta_de_piso[k - 1])
            if c is None:
                self.avisos.append('nivel %+.2f: sin cargas declaradas en el perfil'
                                   % self.niveles[k])
                continue
            q = c['muerta'] if caso == 'G' else c['viva']

            elementos = ([(e, n1, n2, L, kk) for (e, n1, n2, _s, L, _p, kk)
                          in self.vigas if kk == k] +
                         [(e, n1, n2, L, kk) for (e, n1, n2, _s, L, kk)
                          in self.brazos if kk == k])
            for etag, n1, n2, L, _kk in elementos:
                A = self.area_trib.get((min(n1, n2), max(n1, n2)), 0.0)
                if A <= 0 or L <= 0:
                    continue
                w = q * A / L                     # kN/m,  w*L = q*A
                ops.eleLoad('-ele', etag, '-type', '-beamUniform', 0.0, -w, 0.0)
                self.carga_total += q * A

            # La losa que se apoya directo sobre un muro llega a su
            # nodo como carga puntual (el muro es una columna ancha).
            for tag, A in self.area_trib_nodal.items():
                if abs(self.nodos[tag][2] - self.niveles[k]) > 1e-9:
                    continue
                ops.load(tag, 0, 0, -q * A, 0, 0, 0)
                self.carga_total += q * A

    # --------------------------------------------------------
    def resolver(self):
        # Transformation es OBLIGATORIO con rigidDiaphragm: son
        # restricciones multipunto y 'Plain' no las trata.
        ops.system('BandGeneral')
        ops.numberer('RCM')
        ops.constraints('Transformation')
        ops.integrator('LoadControl', 1.0)
        ops.algorithm('Linear')
        ops.analysis('Static')
        ok = ops.analyze(1)
        if ok != 0:
            raise RuntimeError('El analisis no convergio (codigo %d)' % ok)
        return self

    # --------------------------------------------------------
    def resumen(self):
        uz = {t: ops.nodeDisp(t, 3) for t in self.nodos}
        peor = min(uz, key=lambda t: uz[t])
        reacciones = 0.0
        ops.reactions()
        for t in self.nodos_base:
            reacciones += ops.nodeReaction(t, 3)
        return {
            'nodos': len(self.nodos),
            'columnas': sum(1 for v in self.verticales if v[5] == 'pilar'),
            'muros': sum(1 for v in self.verticales if v[5] == 'muro'),
            'vigas': len(self.vigas),
            'brazos': len(self.brazos),
            'apoyos': len(self.nodos_base),
            'diafragmas': len(self.maestros),
            'area_planta': self.area_planta,
            'carga_total': self.carga_total,
            'reaccion_vertical': reacciones,
            'error_equilibrio': abs(reacciones - self.carga_total),
            'uz_max_mm': uz[peor] * 1000.0,
            'nodo_uz_max': peor,
            'posicion_uz_max': self.nodos[peor],
        }


# ============================================================
def main():
    m = ModeloLT2().preparar()

    print('=' * 64)
    print('  MODELO LT2  -  armado desde los planos')
    print('=' * 64)
    print('Material: G35_10   f\'c = %.0f MPa   Ec = %.0f MPa   gamma = %.0f kN/m3'
          % (m.fc, m.Ec / 1000.0, m.gamma))
    print('Losa: e = %.2f m  ->  peso propio %.2f kN/m2' % (m.espesor_losa, m.peso_losa))
    for lam, c in sorted(m.cargas_lamina.items()):
        print('   %s   G = %.2f kN/m2   Q = %.2f kN/m2   (del plano de cargas)'
              % (lam, c['muerta'], c['viva']))
    print('Niveles: %s' % ', '.join('%+.2f' % z for z in m.niveles))
    print()
    print('Secciones distintas: %d' % len(m.secciones))
    for s in sorted(m.secciones.values(), key=lambda s: s.nombre):
        print('   %-16s A=%.4f m2  Iy=%.5f  Iz=%.5f  J=%.5f'
              % (s.nombre, s.A, s.Iy, s.Iz, s.J))

    print('\nMallado por nivel:')
    print('   %9s %7s %6s %6s %7s %10s'
          % ('nivel', 'anclas', 'vigas', 'nodos', 'tramos', 'flotantes'))
    for k, aud in enumerate(m.auditoria_malla):
        print('   %+9.2f %7d %6d %6d %7d %10d'
              % (m.niveles[k], aud['anclas'], aud['vigas_de_entrada'],
                 aud['nodos'], aud['tramos_de_viga'] + aud['brazos'],
                 len(aud['tramos_flotantes_descartados'])))

    flotantes = sum(len(a['tramos_flotantes_descartados'])
                    for a in m.auditoria_malla)
    if flotantes:
        print('\n   %d tramos de viga no tocaban ningun elemento vertical'
              ' y se descartaron.' % flotantes)
    pod = m.podado_resumen
    if pod['verticales_descartados'] or pod['vigas_descartadas']:
        print('\n   Poda por no llegar al suelo: %d elementos verticales y %d '
              'tramos de viga.' % (pod['verticales_descartados'],
                                   pod['vigas_descartadas']))
        for d in pod['detalle'][:5]:
            print('      %-6s en %s' % (d['tipo'], d['posicion']))

    for a, n in collections.Counter(m.avisos).most_common(8):
        print('   AVISO (x%d): %s' % (n, a))

    m.ensamblar('G').resolver()
    r = m.resumen()

    print('\n' + '-' * 64)
    print('  RESULTADO  (caso G)')
    print('-' * 64)
    print('  nodos %d   columnas %d   muros %d   vigas %d   brazos %d   '
          'apoyos %d   diafragmas %d'
          % (r['nodos'], r['columnas'], r['muros'], r['vigas'], r['brazos'],
             r['apoyos'], r['diafragmas']))
    print('  area de losa por piso (suma de los panos):')
    for k in sorted(m.area_piso):
        a = m.aud_panos[k]
        print('     %+7.2f  %8.2f m2   %3d panos   a vigas %7.2f  a muros %7.2f  '
              'conservacion %.1e m2'
              % (m.niveles[k], m.area_piso[k], a['caras_encontradas'],
                 a['area_a_vigas'], a['area_a_muros'],
                 a['error_de_conservacion']))
    print('  carga total aplicada : %12.3f kN' % r['carga_total'])
    print('  suma de reacciones   : %12.3f kN' % r['reaccion_vertical'])
    print('  error de equilibrio  : %12.3e kN' % r['error_equilibrio'])
    print('  UZ maximo            : %12.4f mm  en el nodo %d %s'
          % (r['uz_max_mm'], r['nodo_uz_max'],
             tuple(round(c, 2) for c in r['posicion_uz_max'])))
    return m


if __name__ == '__main__':
    main()
