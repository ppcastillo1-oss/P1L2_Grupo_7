# -*- coding: utf-8 -*-
r"""
Verifica que el JSON que genera Python calce con las clases C# que lo
leen en Unity.

POR QUE EXISTE ESTE TEST
JsonUtility (el parser de Unity) NO avisa cuando un campo no calza:
simplemente deja la variable en su valor por defecto. Una clave mal
escrita no da error ni warning, solo un modelo que se dibuja raro. Un
'uz' mal escrito da deformada plana; un 'area' mal escrito da areas
tributarias en cero. Y como no hay excepcion, se descubre tarde.

Este test compara los campos declarados en los .cs contra las claves
reales del JSON exportado.

Correr:  python tests/test_contrato_unity.py
"""
import json
import os
import re
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)

JSON = os.path.join(_RAIZ, 'data', 'modelo_unity.json')
CS = os.path.join(_RAIZ, 'unity', 'Assets', 'Scripts', 'ModeloEstructural.cs')

fallos = []


def check(cond, msg, detalle=""):
    print(f"  [{'OK  ' if cond else 'FALLA'}] {msg}")
    if detalle:
        print(f"         {detalle}")
    if not cond:
        fallos.append(msg)


# ============================================================
# Parseo simple del C#: campos publicos de cada clase serializable
# ============================================================
def campos_de_clases(ruta):
    with open(ruta, encoding='utf-8') as f:
        src = f.read()

    # Fuera comentarios, para no confundir ejemplos de las notas con
    # codigo real.
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    src = re.sub(r'//[^\n]*', '', src)

    clases = {}
    for m in re.finditer(r'class\s+(\w+)\s*\{', src):
        nombre = m.group(1)
        # Recorta hasta cerrar la llave de la clase.
        i = m.end() - 1
        prof, j = 0, i
        while j < len(src):
            if src[j] == '{':
                prof += 1
            elif src[j] == '}':
                prof -= 1
                if prof == 0:
                    break
            j += 1
        cuerpo = src[i:j]

        campos = set()
        # public <tipo> a, b, c;   (ignora propiedades con { get; })
        for d in re.finditer(
                r'public\s+[\w<>\[\]\.]+\s+([\w\s,]+?)\s*(?:=[^;]*)?;', cuerpo):
            grupo = d.group(1)
            if '(' in grupo:
                continue
            for nom in grupo.split(','):
                nom = nom.strip()
                if nom and re.fullmatch(r'\w+', nom):
                    campos.add(nom)
        clases[nombre] = campos
    return clases


print("Leyendo contrato...")
if not os.path.exists(JSON):
    print(f"No existe {JSON}. Corre primero: python src/exportar_unity.py")
    sys.exit(1)

with open(JSON, encoding='utf-8') as f:
    datos = json.load(f)

clases = campos_de_clases(CS)
print(f"  clases C# encontradas: {len(clases)}")


# ============================================================
print("\n[1] Cada clave del JSON tiene su campo en C#")
# ============================================================
def comparar(nombre_clase, muestra, ignorar=()):
    """Toda clave del JSON debe existir como campo publico en el C#."""
    if nombre_clase not in clases:
        check(False, f"la clase {nombre_clase} existe en el C#")
        return
    campos = clases[nombre_clase]
    faltan = [k for k in muestra
              if k not in campos and k not in ignorar]
    check(not faltan,
          f"{nombre_clase}: todas las claves del JSON estan en el C#",
          f"sin campo C#: {faltan}" if faltan else "")


comparar('ModeloEstructural', datos.keys(), ignorar=('resumen',))
comparar('Nodo', datos['nodos'][0].keys())
comparar('Elemento', datos['elementos'][0].keys())
comparar('Seccion', datos['secciones'][0].keys())
comparar('Diafragma', datos['diafragmas'][0].keys())
comparar('AreaTributaria', datos['areas_tributarias'][0].keys())
comparar('VerticePlanta', datos['areas_tributarias'][0]['vertices'][0].keys())
comparar('CasoDeCarga', datos['casos_de_carga'][0].keys())
comparar('CargaDistribuida',
         datos['casos_de_carga'][0]['cargas_distribuidas'][0].keys())
comparar('InfoModelo', datos['info'].keys())


# ============================================================
print("\n[2] Los campos que Unity necesita SI traen datos")
# ============================================================
# Un campo presente pero vacio es igual de malo que uno ausente: se
# dibuja "algo" y parece que funciona.
e0 = datos['elementos'][0]
check(e0.get('localX') and len(e0['localX']) == 3,
      "los elementos traen ejes locales calculados")
check(any(n['fijo'] for n in datos['nodos']),
      "hay nodos marcados como apoyo")
check(len(datos['diafragmas']) > 0, "hay diafragmas exportados")
check(len(datos['areas_tributarias']) > 0, "hay areas tributarias exportadas")

t0 = datos['areas_tributarias'][0]
check(t0['area'] > 0 and len(t0['vertices']) >= 3,
      "las areas tributarias traen area y poligono")


# ------------------------------------------------------------
# Los poligonos NO miden todos lo mismo: una viga interior toma un
# TRAPECIO de un pano (4 vertices) y un TRIANGULO del otro (3).
# Sin 'tamanos', Unity partia los vertices por division entera
# (7 / 2 = 3) y dibujaba lineas cruzadas que no existen. Este bloque
# existe para que ese bug no vuelva.
# ------------------------------------------------------------
sin_tam = [t['elemento'] for t in datos['areas_tributarias']
           if not t.get('tamanos')]
check(not sin_tam,
      "toda area tributaria declara el tamano de cada poligono",
      f"sin 'tamanos': {len(sin_tam)}" if sin_tam else "")

descuadres = [t['elemento'] for t in datos['areas_tributarias']
              if sum(t.get('tamanos', [])) != len(t['vertices'])]
check(not descuadres,
      "sum(tamanos) = cantidad de vertices",
      f"descuadrados: {descuadres[:5]}" if descuadres else "")

degenerados = [t['elemento'] for t in datos['areas_tributarias']
               if any(k < 3 for k in t.get('tamanos', []))]
check(not degenerados,
      "ningun poligono tiene menos de 3 vertices")

mal_contados = [t['elemento'] for t in datos['areas_tributarias']
                if len(t.get('tamanos', [])) != t['n_poligonos']]
check(not mal_contados,
      "len(tamanos) = n_poligonos")

# El caso que estaba roto tiene que existir de verdad en los datos; si
# no, este test estaria pasando por vacio.
mixtos = [t for t in datos['areas_tributarias']
          if len(set(t.get('tamanos', []))) > 1]
check(len(mixtos) > 0,
      "hay vigas con poligonos de distinto tamano (el caso que fallaba)",
      f"{len(mixtos)} vigas mezclan trapecio y triangulo")

# ------------------------------------------------------------
# Muros: sin largo/espesor el visor los dibuja como columnas flacas.
# ------------------------------------------------------------
muros = [e for e in datos['elementos'] if e['tipo'] == 'muro']
if muros:
    sin_geom = [m['id'] for m in muros
                if m.get('largo', 0) <= 0 or m.get('espesor', 0) <= 0]
    check(not sin_geom,
          "los muros traen largo y espesor para dibujarlos",
          f"sin geometria: {len(sin_geom)}" if sin_geom else "")

    sin_vec = [m['id'] for m in muros
               if not m.get('vecxz') or len(m['vecxz']) < 3]
    check(not sin_vec,
          "los muros traen vecxz (orientacion de su eje fuerte)")


# ============================================================
print("\n[3] Coherencia numerica de lo exportado")
# ============================================================
peor = 0.0
for t in datos['areas_tributarias']:
    peor = max(peor, abs(t['w'] * t['luz'] - t['qG'] * t['area']))
check(peor < 1e-3,
      "en el JSON se cumple w*L = q*A viga por viga",
      f"peor error {peor:.3e} kN")

r = datos['resumen']
check(r['error_equilibrio_kN'] < 1e-6,
      "el resumen reporta equilibrio cerrado",
      f"error {r['error_equilibrio_kN']:.3e} kN")

ids = [e['id'] for e in datos['elementos']]
check(len(ids) == len(set(ids)), "los elementTag son unicos")
ids_n = [n['id'] for n in datos['nodos']]
check(len(ids_n) == len(set(ids_n)), "los nodeTag son unicos")

nodos_set = set(ids_n)
huerfanos = [e['id'] for e in datos['elementos']
             if e['n1'] not in nodos_set or e['n2'] not in nodos_set]
check(not huerfanos,
      "todos los elementos referencian nodos existentes",
      f"huerfanos: {huerfanos[:5]}" if huerfanos else "")

tags = set(ids)
trib_malas = [t['elemento'] for t in datos['areas_tributarias']
              if t['elemento'] not in tags]
check(not trib_malas,
      "toda area tributaria apunta a un elemento existente")


# ============================================================
print("\n" + "=" * 60)
if fallos:
    print(f"FALLARON {len(fallos)}:")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print("EL CONTRATO JSON <-> UNITY ESTA SANO")
print("=" * 60)
