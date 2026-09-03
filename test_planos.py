# -*- coding: utf-8 -*-
"""
================================================================
 test_planos.py
================================================================
 Verifica el ingestor de planos (src/planos/).

 POR QUE ESTE TEST EXISTE
 ------------------------
 Leer un plano falla EN SILENCIO. No hay ninguna excepcion que
 avise de que:

   - una capa vino de un XREF y se llama "EJE 1$0$RLE-MURO", asi
     que ningun patron le calzo y la lamina se leyo vacia;
   - la lamina de fundaciones estaba corrida 5 m respecto de la
     planta tipo y quedo mal montada sobre los pilares;
   - una cara de muro larga alimentaba dos tramos y el segundo se
     perdio;
   - un contorno de pilares que no cierra se leyo como un pilar
     del tamano de su caja envolvente.

 Todos esos casos producen un modelo que corre, se ve bien, y esta
 malo. Por eso cada uno tiene aca un test con un numero conocido.

 La ultima seccion contrasta contra los planos REALES del proyecto
 LT2; si no estan en el disco, se salta con aviso (los DXF no se
 versionan: pesan 160 MB).

 Correr con:  python test_planos.py
================================================================
"""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'src', 'planos'))

import alineacion            # noqa: E402
import ejes as mod_ejes      # noqa: E402
import lectura               # noqa: E402
import muros as mod_muros    # noqa: E402
import niveles as mod_niveles  # noqa: E402
import perfil as mod_perfil  # noqa: E402
import pilares as mod_pilares  # noqa: E402

fallos = []


def check(nombre, condicion, detalle=''):
    estado = 'OK  ' if condicion else 'FALLA'
    print('  [%s] %s%s' % (estado, nombre, ('   ' + detalle) if detalle else ''))
    if not condicion:
        fallos.append(nombre)


def seg(x1, y1, x2, y2, capa='RLE-MURO'):
    return lectura.Segmento(x1, y1, x2, y2, capa)


print('=' * 64)
print('  TEST: INGESTOR DE PLANOS')
print('=' * 64)

# ============================================================
print('\n1. Capas que vienen de un XREF')
# AutoCAD renombra las capas referenciadas: "EJE 1$0$RLE-MURO".
# Si el emparejador no quita ese prefijo, TODA la geometria de las
# elevaciones se lee vacia y no hay ningun error.
check('quita el prefijo de xref',
      mod_perfil.limpiar_capa('EJE 1$0$RLE-MURO') == 'RLE-MURO')
check('no toca una capa normal',
      mod_perfil.limpiar_capa('RLE-MURO') == 'RLE-MURO')
check('soporta anidamiento',
      mod_perfil.limpiar_capa("EJE 1'$0$RLE-EJE") == 'RLE-EJE')

p = mod_perfil.Perfil({'unidades': 'cm',
                       'roles': {'muros': {'capas': ['RLE-MURO']},
                                 'ejes_lineas': {'capas': ['RLE-EJE*']}}})
check('el perfil reconoce la capa con prefijo', p.calza('EJE 1$0$RLE-MURO', 'muros'))
check('el comodin funciona', p.calza('RLE-EJES', 'ejes_lineas'))
check('no confunde roles', not p.calza('RLE-PILAR', 'muros'))
check('factor a metros desde cm', abs(p.factor - 0.01) < 1e-12)

# ============================================================
print('\n2. Secciones escritas en el plano')
check("lee 'P.70x70'", mod_pilares.seccion_de_texto('P.70x70') == (0.70, 0.70))
check("lee 'V. 60/80'", mod_pilares.seccion_de_texto('V. 60/80') == (0.60, 0.80))
check("lee '20/120'", mod_pilares.seccion_de_texto('V.F. 20/120') == (0.20, 1.20))
check("rechaza 'P.' (el rotulo viene partido en dos textos)",
      mod_pilares.seccion_de_texto('P.') is None)
check('respeta metros si ya vienen en metros',
      mod_pilares.seccion_de_texto('0.70x0.70') == (0.70, 0.70))

# ============================================================
print('\n3. Muros: una cara larga puede alimentar VARIOS tramos')
# Esta es la regresion que motivo consumir tramos en vez de caras.
# Una cara de 10 m enfrentada a dos de 4 m con un vano en medio:
#
#     ----------------------------------------  cara larga
#     ----------------      ------------------  dos caras, vano en medio
#
# Con "una cara, un muro" el segundo tramo DESAPARECE del modelo.
caras = [seg(0.0, 0.0, 10.0, 0.0),
         seg(0.0, 0.25, 4.0, 0.25),
         seg(6.0, 0.25, 10.0, 0.25)]
M, aud = mod_muros.extraer(caras)
check('salen los DOS muros, no uno', len(M) == 2, 'salieron %d' % len(M))
check('espesor correcto en ambos',
      all(abs(m.espesor - 0.25) < 1e-9 for m in M))
check('largos 4.0 y 4.0',
      sorted(round(m.largo, 6) for m in M) == [4.0, 4.0],
      str(sorted(round(m.largo, 3) for m in M)))
check('el eje queda a media altura',
      all(abs(m.y1 - 0.125) < 1e-9 for m in M))

# ============================================================
print('\n4. Muros: lo que NO debe emparejarse')
# Dos muros alineados uno detras del otro, sin solape: si se
# emparejan, aparece un muro fantasma que cruza el edificio.
sin_solape = [seg(0.0, 0.0, 4.0, 0.0), seg(6.0, 0.25, 10.0, 0.25)]
M2, _ = mod_muros.extraer(sin_solape)
check('sin solape longitudinal no hay muro', len(M2) == 0)

# Dos lineas paralelas demasiado separadas no son un muro.
lejos = [seg(0.0, 0.0, 5.0, 0.0), seg(0.0, 2.0, 5.0, 2.0)]
M3, _ = mod_muros.extraer(lejos)
check('separacion fuera del rango de espesores no es muro', len(M3) == 0)

# Un espesor JUSTO en el limite si debe entrar: restando coordenadas,
# 0.60 sale 0.6000000000000001 y un "<=" pelado lo dejaba fuera.
limite = [seg(0.0, 0.1, 5.0, 0.1), seg(0.0, 0.7, 5.0, 0.7)]
M4, _ = mod_muros.extraer(limite, espesor_max=0.60)
check('un espesor exactamente igual al maximo entra', len(M4) == 1,
      'el punto flotante lo dejaba fuera')

# ============================================================
print('\n5. Muros: la cobertura mide lo que NO llego al modelo')
Mc, audc = mod_muros.extraer(caras)
# La cobertura cuenta el largo consumido en LAS DOS caras de cada
# par: 8 m de la cara larga + 8 m de las dos cortas = 16 m, sobre
# 10+4+4 = 18 m de cara dibujada. Los 2 m que faltan son el tramo
# de la cara larga que da al vano, donde no hay muro.
check('cobertura = 16/18 (2 m de cara dan al vano)',
      abs(audc['cobertura'] - 16.0 / 18.0) < 1e-4,
      'cobertura=%.4f' % audc['cobertura'])

# ============================================================
print('\n6. Pilares: aceptar lo abierto, rechazar lo que sobra')
# Rectangulo perfecto de 0.70 x 0.70
cerrado = [seg(0, 0, .7, 0), seg(.7, 0, .7, .7), seg(.7, .7, 0, .7), seg(0, .7, 0, 0)]
P1, a1 = mod_pilares.extraer(cerrado)
check('un rectangulo cerrado es un pilar', len(P1) == 1)
check('mide 0.70 x 0.70', abs(P1[0].b - .7) < 1e-9 and abs(P1[0].h - .7) < 1e-9)
check('queda marcado como cerrado', P1[0].cerrado is True)

# Un lado abierto (pasa donde llega un muro): sigue siendo un pilar.
abierto = [seg(0, 0, .45, 0), seg(.7, 0, .7, .7), seg(.7, .7, 0, .7), seg(0, .7, 0, 0)]
P2, a2 = mod_pilares.extraer(abierto)
check('un contorno abierto sigue siendo un pilar', len(P2) == 1)
check('se marca como NO cerrado', P2[0].cerrado is False)
check('la auditoria lo reporta', len(a2['contorno_abierto']) == 1)

# Lineas de mas: NO es un rectangulo. Aceptarlo convertiria cualquier
# maraña en un pilar del tamano de su caja envolvente.
sobra = cerrado + [seg(0, 0, .7, .7)]          # una diagonal
P3, a3 = mod_pilares.extraer(sobra)
check('un grupo con lineas de mas se rechaza', len(P3) == 0)
check('y se reporta como no rectangular', len(a3['grupos_no_rectangulares']) == 1)

# ============================================================
print('\n7. Pilares: la etiqueta se contrasta contra el dibujo')
Texto = lectura.Texto
etiquetas = [Texto('P.', .8, .8, 'RLE-TEXTO-1', .1, 0),
             Texto('70x70', .9, .9, 'RLE-TEXTO-1', .1, 0)]
P4, a4 = mod_pilares.extraer(cerrado, etiquetas)
check("elige '70x70' y no el 'P.' mas cercano", P4[0].etiqueta == '70x70')
check('y confirma que calza con lo medido', P4[0].calza_etiqueta is True)

malas = [Texto('30x30', .9, .9, 'RLE-TEXTO-1', .1, 0)]
P5, a5 = mod_pilares.extraer(cerrado, malas)
check('una etiqueta que no calza se reporta',
      len(a5['etiqueta_no_calza_con_el_dibujo']) == 1)

# ============================================================
print('\n8. Registro de laminas por ejes con nombre')
Eje = mod_ejes.Eje
ref = [Eje('A', 'X', 10.0, 2, True), Eje('B', 'X', 17.5, 2, True),
       Eje('1', 'Y', 27.2, 2, True), Eje('2', 'Y', 18.3, 2, True)]
corrida = [e._replace(coord=e.coord - (5.0 if e.direccion == 'X' else 0.3))
           for e in ref]
reg = alineacion.registrar(ref, corrida)
check('recupera dx = +5.000', abs(reg.dx - 5.0) < 1e-12, 'dx=%.6f' % reg.dx)
check('recupera dy = +0.300', abs(reg.dy - 0.3) < 1e-12, 'dy=%.6f' % reg.dy)
check('residuo nulo', reg.residuo_max < 1e-12)
check('el registro se declara valido', reg.ok)

# Si un eje esta mal leido, el residuo lo delata.
mala = list(corrida)
mala[0] = mala[0]._replace(coord=mala[0].coord + 0.4)
reg2 = alineacion.registrar(ref, mala)
check('un eje mal leido sube el residuo', reg2.residuo_max > 0.1,
      'residuo=%.3f' % reg2.residuo_max)
check('y el registro se declara NO valido', not reg2.ok)

# Sin ejes en comun no se puede registrar, y hay que saberlo.
otro = [Eje('Z', 'X', 1.0, 2, True), Eje('9', 'Y', 1.0, 2, True)]
reg3 = alineacion.registrar(ref, otro)
check('sin ejes comunes el registro se marca invalido', not reg3.ok)

# ============================================================
print('\n9. Niveles: el desfase constante es la verificacion')
Hoja = lectura.Hoja
h = Hoja('sintetica', 0.01)
# Cotas reales, todas con el mismo desfase (22.416), y dos textos
# que NO son cotas: deben caerse solos.
for z in (-7.97, -4.01, -0.05, 3.91, 7.87, 11.83):
    h.textos.append(Texto('%+.2f' % z, 0.0, z + 22.416, '0', .1, 0))
h.textos.append(Texto('+3.91', 0.0, 99.0, '0', .1, 0))       # cota descolgada
h.textos.append(Texto('0.350', 0.0, 1.0, 'DEFPOINTS', .1, 0))  # diametro de fierro

N, desfase, aud = mod_niveles.extraer(h)
check('encuentra los 6 niveles', len(N) == 6, 'encontro %d' % len(N))
check('desfase = 22.416', abs(desfase - 22.416) < 1e-9, 'desfase=%.4f' % desfase)
check('el desfase es coherente', aud['coherente'])
check('altura entre pisos constante = 3.96',
      all(abs(a - 3.96) < 1e-9 for a in aud['alturas_entre_pisos'][1:]),
      str(aud['alturas_entre_pisos']))
check('descarta la cota descolgada', len(aud['cotas_descartadas']) == 1)
check('ignora la capa DEFPOINTS', all('0.350' not in str(c)
                                      for c in aud['cotas_descartadas']))

# ============================================================
print('\n10. Contra los planos reales (LT2 / 2024_22)')
CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '..', 'Planos', 'LT2_CAL_dxf')
PERFIL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      'perfiles', 'lt2_2024_22.json')

if not os.path.isdir(CARPETA):
    print('  [SALTA] no estan los DXF en %s' % CARPETA)
    print('          generarlos con src/planos/dwg_a_dxf.ps1')
else:
    perfil = mod_perfil.cargar(PERFIL)
    hoja = lectura.leer(os.path.join(CARPETA, '2024_22-101.dxf'), perfil)
    E, audE = mod_ejes.extraer(hoja, perfil)

    check('planta tipo: 18 ejes con nombre', len(E) == 18, '%d ejes' % len(E))
    check('  10 verticales y 8 horizontales',
          audE['ejes_X'] == 10 and audE['ejes_Y'] == 8,
          'X=%d Y=%d' % (audE['ejes_X'], audE['ejes_Y']))
    check('  ninguna burbuja quedo sin clasificar',
          not audE['burbujas_sin_clasificar'],
          str(audE['burbujas_sin_clasificar']))
    nombres = {e.nombre for e in E}
    check("  estan los ejes con apostrofe (A', 1', 8B)",
          {"A'", "1'", '8B'} <= nombres)

    M, audM = mod_muros.extraer(hoja.segmentos_de(perfil, 'muros'))
    check('planta tipo: 15 muros', len(M) == 15, '%d muros' % len(M))
    check('  ninguna cara de muro sin pareja', audM['caras_sin_pareja'] == 0)
    check('  cobertura sobre 95%%', audM['cobertura'] > 0.95,
          '%.1f%%' % (100 * audM['cobertura']))

    PI, audP = mod_pilares.extraer(hoja.segmentos_de(perfil, 'pilares'),
                                   hoja.textos_de(perfil, 'etiquetas'))
    check('planta tipo: 8 pilares', len(PI) == 8, '%d pilares' % len(PI))
    check('  todos 0.70 x 0.70',
          all(abs(q.b - .70) < 1e-6 and abs(q.h - .70) < 1e-6 for q in PI))
    check('  ninguna etiqueta contradice al dibujo',
          not audP['etiqueta_no_calza_con_el_dibujo'])

    # Registro: la lamina de fundaciones esta corrida 5.00 m en X.
    hoja100 = lectura.leer(os.path.join(CARPETA, '2024_22-100.dxf'), perfil)
    E100, _ = mod_ejes.extraer(hoja100, perfil)
    reg100 = alineacion.registrar(E, E100)
    check('fundaciones esta corrida dx = +5.000 m',
          abs(reg100.dx - 5.0) < 0.001, 'dx=%.4f' % reg100.dx)
    check('  con residuo bajo 1 mm sobre 10 ejes',
          reg100.residuo_max < 0.001 and len(reg100.ejes_usados_x) == 10,
          'residuo=%.5f m, %d ejes' % (reg100.residuo_max,
                                       len(reg100.ejes_usados_x)))

    # Niveles: los 6 planos de elevacion deben coincidir.
    res = {}
    for lam in perfil.datos['elevaciones']:
        ruta = os.path.join(CARPETA, lam + '.dxf')
        if os.path.isfile(ruta):
            res[lam] = mod_niveles.extraer(lectura.leer(ruta, perfil))
    check('se leyeron las 6 elevaciones', len(res) == 6)
    check('cada elevacion tiene su desfase coherente',
          all(a['coherente'] for (_N, _d, a) in res.values()))
    consenso = [c['z'] for c in mod_niveles.combinar(res)
                if c['laminas'] == len(res)]
    check('7 cotas confirmadas por TODAS las elevaciones',
          consenso == [-8.57, -7.97, -4.01, -0.05, 3.91, 7.87, 11.83],
          str(consenso))
    alturas = [round(b - a, 3) for a, b in zip(consenso[1:], consenso[2:])]
    check('  altura entre pisos constante = 3.96 m',
          all(abs(a - 3.96) < 1e-9 for a in alturas), str(alturas))

# ============================================================
print('\n' + '=' * 64)
if fallos:
    print('  %d TEST(S) FALLARON:' % len(fallos))
    for f in fallos:
        print('    - %s' % f)
    raise SystemExit(1)
print('  TODOS LOS TESTS PASARON')
print('=' * 64)
