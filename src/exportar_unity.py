# -*- coding: utf-8 -*-
r"""
================================================================
 exportar_unity.py  -  CONTRATO JSON  OpenSees -> Unity
================================================================
 Corre el modelo, resuelve el caso G y escribe
 data/modelo_unity.json, que es lo que lee el visor.

 REGLA DE ORO: OpenSees calcula, el JSON es la fuente de verdad,
 Unity solo MUESTRA. Por eso el JSON no lleva la geometria a secas:
 lleva ya calculado todo lo que Unity necesita dibujar --nodos con
 sus restricciones por GDL, elementos con su seccion, EJES LOCALES,
 diafragmas, areas tributarias como poligonos y el caso de carga
 completo.

 ----------------------------------------------------------------
 POR QUE ESTE ARCHIVO ES UN ENVOLTORIO
 ----------------------------------------------------------------
 El exportador de verdad es `src/exportar_lt2.py`: el que sabe que
 campos pide el C# y con que convencion. Este archivo hace una sola
 cosa: llamarlo y pedirle que escriba en `data/modelo_unity.json`,
 que es donde el visor y los tests del laboratorio lo buscan.

 Se conserva este nombre porque es el que usan el notebook, el
 README y la costumbre: `python src/exportar_unity.py`.

 Correr:  python src/exportar_unity.py
================================================================
"""
from __future__ import annotations

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)

sys.path.insert(0, _AQUI)

import modelo_edificio as M                # noqa: E402  (resuelve LT2_SRC)

sys.path.insert(0, M.LT2_SRC)

import exportar_lt2 as _exportador_lt2      # noqa: E402

SALIDA = os.path.join(_RAIZ, 'data', 'modelo_unity.json')


def main():
    print('Estructura: edificio LT2 (planos de calculo 2024_22)')
    print('Exportador: %s' % os.path.join(M.LT2_SRC, 'exportar_lt2.py'))
    print()
    return _exportador_lt2.main(SALIDA)


if __name__ == '__main__':
    sys.exit(main())
