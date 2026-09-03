# -*- coding: utf-8 -*-
r"""
================================================================
 inventario.py  -  QUE HAY ADENTRO DE UN JUEGO DE PLANOS
================================================================
 Primer paso OBLIGATORIO antes de extraer geometria de un juego de
 planos nuevo. Recorre una carpeta de DXF y responde:

   - que hojas hay y como se llaman (rotulo del plano);
   - que capas tiene cada hoja y cuantas entidades de cada tipo;
   - en que unidades esta dibujado (declarada + estimada);
   - que extension ocupa el dibujo.

 Con eso se escribe el PERFIL del proyecto (perfiles/*.json), que es
 lo que le dice a los extractores "los muros estan en la capa X".

 Sin este paso uno termina hardcodeando nombres de capa de un
 proyecto y el codigo no sirve para el siguiente.

 ----------------------------------------------------------------
 Uso
 ----------------------------------------------------------------
   python src/planos/inventario.py <carpeta_dxf> [-o salida.json]

 Deja dos archivos al lado:
   inventario.json  - datos crudos, para que los lean los extractores
   inventario.md    - tabla legible, para pegar en el informe
================================================================
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

try:
    import ezdxf
except ImportError:  # pragma: no cover
    sys.exit("Falta ezdxf.  pip install ezdxf")


# ============================================================
# Unidades
# ============================================================
# $INSUNITS del encabezado DXF. Muchos planos chilenos lo dejan en 0
# ("sin especificar"), asi que hay que estimar por el tamano.
INSUNITS = {
    0: 'sin especificar', 1: 'pulgadas', 2: 'pies', 4: 'mm',
    5: 'cm', 6: 'm', 8: 'micrones', 9: 'mils', 10: 'yardas',
}

# Factor de conversion a METROS. El modelo estructural trabaja
# siempre en metros; la conversion se hace AL LEER, nunca despues.
A_METROS = {'mm': 0.001, 'cm': 0.01, 'm': 1.0, 'pulgadas': 0.0254, 'pies': 0.3048}


def estimar_unidad(ancho, alto):
    """
    Adivina la unidad de dibujo a partir del tamano de la planta.

    Un edificio real mide entre ~5 m y ~500 m de lado. Si el dibujo
    dice 4500, esos 4500 son centimetros (45 m); si dice 45000, son
    milimetros. Es una heuristica: el perfil del proyecto puede
    sobreescribirla, y debe hacerlo si hay dudas.
    """
    lado = max(ancho, alto)
    if lado <= 0:
        return None, 'dibujo vacio'
    for unidad in ('m', 'cm', 'mm'):
        en_metros = lado * A_METROS[unidad]
        if 5.0 <= en_metros <= 500.0:
            return unidad, '%.1f x %.1f %s = %.1f x %.1f m' % (
                ancho, alto, unidad, ancho * A_METROS[unidad], alto * A_METROS[unidad])
    return None, 'no calza con ninguna unidad plausible (lado=%.1f)' % lado


# ============================================================
# Lectura de una hoja
# ============================================================
def rotulo_de(doc):
    """
    Textos del rotulo (vineta) del plano: numero de lamina, titulo,
    fecha, calculista. Vienen como ATRIBUTOS de un bloque INSERT.

    No hay un estandar: cada oficina nombra sus tags distinto, asi
    que se devuelven todos y el perfil decide cuales importan.
    """
    atributos = {}
    for ins in doc.modelspace().query('INSERT'):
        if not ins.attribs:
            continue
        for att in ins.attribs:
            tag = str(att.dxf.tag).strip()
            valor = str(att.dxf.text).strip()
            if tag and valor:
                # Si el mismo tag aparece dos veces, se guarda el primero
                # no vacio; los rotulos suelen repetirse en las vistas.
                atributos.setdefault(tag, valor)
    return atributos


def inventariar_hoja(ruta):
    """Devuelve el diccionario de inventario de UN archivo DXF."""
    hoja = {'archivo': os.path.basename(ruta),
            'mb': round(os.path.getsize(ruta) / 1e6, 2)}
    try:
        doc = ezdxf.readfile(ruta)
    except Exception as exc:
        hoja['error'] = '%s: %s' % (type(exc).__name__, exc)
        return hoja

    msp = doc.modelspace()

    # --- capas: cuantas entidades de cada tipo ---
    por_capa = collections.defaultdict(collections.Counter)
    for e in msp:
        por_capa[e.dxf.layer][e.dxftype()] += 1

    hoja['capas'] = {
        capa: {'total': sum(tipos.values()), 'tipos': dict(tipos.most_common())}
        for capa, tipos in sorted(por_capa.items(), key=lambda kv: -sum(kv[1].values()))
    }
    hoja['n_capas'] = len(por_capa)
    hoja['n_entidades'] = sum(sum(t.values()) for t in por_capa.values())

    # --- unidades ---
    cod = doc.header.get('$INSUNITS', 0)
    hoja['insunits'] = INSUNITS.get(cod, 'codigo %s' % cod)

    # --- extension del dibujo ---
    # OJO: $EXTMIN/$EXTMAX incluyen el rotulo y las vistas de detalle,
    # asi que son mas grandes que la planta. Sirven para la unidad,
    # no como contorno del edificio.
    emin = doc.header.get('$EXTMIN', (0, 0, 0))
    emax = doc.header.get('$EXTMAX', (0, 0, 0))
    ancho, alto = emax[0] - emin[0], emax[1] - emin[1]
    hoja['extension'] = {'min': [round(v, 3) for v in emin[:2]],
                         'max': [round(v, 3) for v in emax[:2]],
                         'ancho': round(ancho, 2), 'alto': round(alto, 2)}
    unidad, razon = estimar_unidad(ancho, alto)
    hoja['unidad_estimada'] = unidad
    hoja['unidad_razon'] = razon

    # --- rotulo ---
    hoja['rotulo'] = rotulo_de(doc)

    # --- presentaciones (layouts), suelen nombrar el formato ---
    hoja['layouts'] = [l.name for l in doc.layouts if l.name != 'Model']

    return hoja


# ============================================================
# Reporte
# ============================================================
def resumen_capas(hojas):
    """Capas agregadas de todo el juego: en cuantas hojas aparece cada una."""
    en_hojas = collections.Counter()
    entidades = collections.Counter()
    for h in hojas:
        for capa, info in h.get('capas', {}).items():
            en_hojas[capa] += 1
            entidades[capa] += info['total']
    return [{'capa': c, 'hojas': en_hojas[c], 'entidades': entidades[c]}
            for c in sorted(en_hojas, key=lambda c: (-en_hojas[c], -entidades[c]))]


def escribir_md(inv, ruta):
    L = []
    L.append('# Inventario de planos\n')
    L.append('Carpeta: `%s`\n' % inv['carpeta'])
    L.append('Hojas leidas: **%d**  ·  capas distintas: **%d**\n'
             % (len(inv['hojas']), len(inv['capas_del_juego'])))

    L.append('\n## Hojas\n')
    L.append('| Archivo | MB | Entidades | Capas | Unidad ($INSUNITS / estimada) | Titulo del rotulo |')
    L.append('|---|---:|---:|---:|---|---|')
    for h in inv['hojas']:
        if 'error' in h:
            L.append('| `%s` | %.2f | — | — | — | ERROR: %s |'
                     % (h['archivo'], h['mb'], h['error']))
            continue
        titulo = ' / '.join(list(h['rotulo'].values())[:2]) if h['rotulo'] else ''
        L.append('| `%s` | %.2f | %d | %d | %s / **%s** | %s |'
                 % (h['archivo'], h['mb'], h['n_entidades'], h['n_capas'],
                    h['insunits'], h['unidad_estimada'], titulo[:60]))

    L.append('\n## Capas de todo el juego\n')
    L.append('| Capa | Hojas donde aparece | Entidades totales |')
    L.append('|---|---:|---:|')
    for c in inv['capas_del_juego']:
        L.append('| `%s` | %d | %d |' % (c['capa'], c['hojas'], c['entidades']))

    L.append('\n## Capas por hoja\n')
    for h in inv['hojas']:
        if 'error' in h:
            continue
        L.append('\n### `%s`\n' % h['archivo'])
        if h['rotulo']:
            L.append('Rotulo: ' + ' · '.join('**%s**: %s' % (k, v)
                                             for k, v in list(h['rotulo'].items())[:8]) + '\n')
        L.append('| Capa | Entidades | Tipos |')
        L.append('|---|---:|---|')
        for capa, info in h['capas'].items():
            tipos = ', '.join('%s×%d' % (t, n) for t, n in list(info['tipos'].items())[:5])
            L.append('| `%s` | %d | %s |' % (capa, info['total'], tipos))

    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


# ============================================================
def inventariar(carpeta):
    dxfs = sorted(f for f in os.listdir(carpeta) if f.lower().endswith('.dxf'))
    if not dxfs:
        sys.exit('No hay archivos .dxf en %s' % carpeta)
    hojas = []
    for i, nombre in enumerate(dxfs, 1):
        print('  [%2d/%d] %s' % (i, len(dxfs), nombre), flush=True)
        hojas.append(inventariar_hoja(os.path.join(carpeta, nombre)))
    return {'carpeta': os.path.abspath(carpeta),
            'hojas': hojas,
            'capas_del_juego': resumen_capas(hojas)}


def main():
    ap = argparse.ArgumentParser(description='Inventario de un juego de planos DXF.')
    ap.add_argument('carpeta', help='carpeta con los .dxf')
    ap.add_argument('-o', '--salida', default=None,
                    help='ruta del inventario.json (por defecto, dentro de la carpeta)')
    args = ap.parse_args()

    print('Inventariando %s' % args.carpeta)
    inv = inventariar(args.carpeta)

    destino = args.salida or os.path.join(args.carpeta, 'inventario.json')
    with open(destino, 'w', encoding='utf-8') as f:
        json.dump(inv, f, indent=1, ensure_ascii=False)
    md = os.path.splitext(destino)[0] + '.md'
    escribir_md(inv, md)

    print('\n%d hojas, %d capas distintas' % (len(inv['hojas']), len(inv['capas_del_juego'])))
    print('  %s' % destino)
    print('  %s' % md)


if __name__ == '__main__':
    main()
