# -*- coding: utf-8 -*-
r"""
Verifica que REANALIZAR el modelo desde el JSON reproduzca el MISMO
resultado que calculo Python.

POR QUE EXISTE
Cuando se modifica el modelo desde Unity (mover un nodo, cambiar una
seccion, borrar una barra) el reanalisis lo hace el servidor Flask, que
reconstruye el modelo A PARTIR DEL JSON. Si el JSON no describe
exactamente el mismo problema que resolvio modelo_lt2.py, el
servidor devuelve numeros distintos a los del informe y NADIE SE ENTERA:
no hay error, solo resultados un poco distintos.

Dos formas reales en que eso paso en este proyecto:

1. El caso G exportado traia solo la carga de losa, sin el peso propio
   de vigas, columnas y muros. Daba 10.04 mm donde Python daba 11.78.

2. Las inercias se exportaban ya cruzadas, y el servidor -- que cruza
   segun la geometria del elemento -- las cruzaba UNA SEGUNDA VEZ.
   Daba 12.17 mm.

Ambos errores son invisibles sin esta comparacion.

Correr:  python tests/test_reanalisis.py
         (necesita flask; si no esta, el test se salta y lo dice)
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)

JSON = os.path.join(_RAIZ, 'data', 'modelo_unity.json')
SERVIDOR = os.path.join(_RAIZ, 'src', 'servidor_opensees.py')
PUERTO = 5099
TOL = 1e-7          # m. El JSON redondea a 9 decimales.

fallos = []


def check(cond, msg, detalle=""):
    print(f"  [{'OK  ' if cond else 'FALLA'}] {msg}")
    if detalle:
        print(f"         {detalle}")
    if not cond:
        fallos.append(msg)


try:
    import flask  # noqa: F401
except ImportError:
    print("Flask no esta instalado: se salta el test de reanalisis.")
    print("  .venv\\Scripts\\python.exe -m pip install flask")
    sys.exit(0)

if not os.path.exists(JSON):
    print(f"No existe {JSON}. Corre antes: python src/exportar_unity.py")
    sys.exit(1)

with open(JSON, encoding='utf-8') as f:
    modelo = json.load(f)

print(f"Modelo: {len(modelo['nodos'])} nodos, "
      f"{len(modelo['elementos'])} elementos")

base = f'http://127.0.0.1:{PUERTO}'
proc = subprocess.Popen([sys.executable, SERVIDOR, '--puerto', str(PUERTO)],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True)
try:
    # ------------------------------------------------------------
    print("\n[1] El servidor responde")
    # ------------------------------------------------------------
    vivo = False
    for _ in range(30):
        try:
            with urllib.request.urlopen(base + '/ping', timeout=2):
                vivo = True
                break
        except Exception:
            time.sleep(1)
    check(vivo, "el servidor levanta y contesta /ping")
    if not vivo:
        sys.exit(1)

    # ------------------------------------------------------------
    print("\n[2] Acepta el modelo completo del edificio")
    # ------------------------------------------------------------
    req = urllib.request.Request(
        base + '/analizar', data=json.dumps(modelo).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode('utf-8', 'replace')
        check(False, "el servidor acepta el modelo", f"HTTP {e.code}: {cuerpo[:300]}")
        sys.exit(1)

    check(resp.get('ok') is True, "el analisis resuelve",
          resp.get('error', '')[:200])

    casos = resp.get('casos') or []
    desp = (casos[0].get('desplazamientos') if casos
            else resp.get('desplazamientos')) or []
    check(len(desp) > 0, "devuelve desplazamientos",
          f"{len(desp)} nodos")

    # ------------------------------------------------------------
    print("\n[3] Reproduce EXACTAMENTE el analisis de Python")
    # ------------------------------------------------------------
    # La deformada precalculada viaja en los propios nodos del JSON.
    previo = {n['id']: n for n in modelo['nodos']}
    peor, cual = 0.0, None
    comparados = 0
    for d in desp:
        n = previo.get(d['id'])
        if n is None:
            continue
        comparados += 1
        for k in ('ux', 'uy', 'uz'):
            e = abs(float(d[k]) - float(n[k]))
            if e > peor:
                peor, cual = e, (d['id'], k)

    # El LT2 tiene 252 nodos (la grilla vieja tenia 656): el tope solo
    # esta para que el test no pase con una respuesta vacia.
    check(comparados > 200, "se comparan todos los nodos",
          f"{comparados} nodos comparados")
    check(peor < TOL,
          "el reanalisis da los mismos desplazamientos que modelo_lt2.py",
          f"peor diferencia {peor:.3e} m en {cual}")

    # Un chequeo de orden de magnitud, por si algun dia el JSON
    # quedara con la deformada en cero y todo "coincidiera".
    uz_max = max(abs(float(n['uz'])) for n in modelo['nodos'])
    check(uz_max > 1e-4,
          "la deformada de referencia no es trivialmente cero",
          f"UZ maximo {uz_max*1000:.3f} mm")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print("\n" + "=" * 60)
if fallos:
    print(f"FALLARON {len(fallos)}:")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print("EL REANALISIS REPRODUCE EL MODELO DE PYTHON")
print("=" * 60)
