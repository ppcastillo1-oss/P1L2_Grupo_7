# -*- coding: utf-8 -*-
r"""
================================================================
 lanzar_unity.py  -  ABRIR EL VISOR DESDE PYTHON
================================================================
 Permite disparar la visualizacion Unity desde el notebook, para que
 todo el laboratorio se corra de una sola pasada:

     modelo OpenSees -> JSON -> visor Unity

 Hay dos modos:

   app     compila (una vez) una aplicacion standalone y la ejecuta.
           No necesita tener el editor de Unity abierto y arranca en
           segundos. Es el modo para la DEMO.

   editor  abre el proyecto en el editor de Unity. Sirve para
           trabajar en el visor, no para mostrarlo: hay que apretar
           Play a mano y tarda mucho mas en cargar.

 ----------------------------------------------------------------
 POR QUE NO SE PUEDE "APRETAR PLAY" DESDE PYTHON
 ----------------------------------------------------------------
 El modo Play del editor es interactivo: -batchmode y Play son
 incompatibles. Por eso, para ver el modelo sin tocar el editor, se
 compila una app standalone; eso SI se puede hacer sin interfaz y
 luego ejecutarla es un proceso normal.
================================================================
"""
import os
import shutil
import subprocess
import sys
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)

PROYECTO_UNITY = os.path.join(_RAIZ, 'unity')
CARPETA_BUILD = os.path.join(_RAIZ, 'build')
APP = os.path.join(CARPETA_BUILD, 'LaboratorioEstructural.exe')

JSON_MODELO = os.path.join(_RAIZ, 'data', 'modelo_unity.json')
STREAMING = os.path.join(PROYECTO_UNITY, 'Assets', 'StreamingAssets',
                         'modelo_unity.json')


# ============================================================
# 1. ENCONTRAR EL EDITOR DE UNITY
# ============================================================
def buscar_unity(version=None):
    """
    Busca Unity.exe. Si se pide una version concreta, solo devuelve
    esa; si no, la que coincida con ProjectVersion.txt del proyecto,
    y como ultimo recurso la mas nueva instalada.

    Mezclar versiones de Unity en un proyecto de grupo es una fuente
    clasica de conflictos (Unity reescribe assets al abrirlos con otra
    version), asi que por defecto se exige la del proyecto.
    """
    if version is None:
        version = version_del_proyecto()

    bases = [
        r"C:\Program Files\Unity\Hub\Editor",
        r"C:\Program Files\Unity\Editor",
        os.path.expandvars(r"%LOCALAPPDATA%\Unity\Hub\Editor"),
    ]

    candidatos = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        for nombre in sorted(os.listdir(base), reverse=True):
            exe = os.path.join(base, nombre, 'Editor', 'Unity.exe')
            if os.path.exists(exe):
                candidatos.append((nombre, exe))
        exe = os.path.join(base, 'Unity.exe')
        if os.path.exists(exe):
            candidatos.append(('?', exe))

    if not candidatos:
        raise FileNotFoundError(
            "No encontre Unity.exe. Instala Unity desde Unity Hub.")

    if version:
        for nombre, exe in candidatos:
            if nombre == version:
                return exe
        disponibles = ", ".join(n for n, _ in candidatos)
        raise FileNotFoundError(
            f"El proyecto pide Unity {version} y no esta instalada.\n"
            f"Instaladas: {disponibles}\n"
            f"Instalala desde Unity Hub, o pasa version='<otra>' "
            f"asumiendo el riesgo de que Unity migre los assets.")

    return candidatos[0][1]


def version_del_proyecto():
    """Lee la version exacta que declara el proyecto."""
    ruta = os.path.join(PROYECTO_UNITY, 'ProjectSettings',
                        'ProjectVersion.txt')
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding='utf-8') as f:
        for linea in f:
            if linea.startswith('m_EditorVersion:'):
                return linea.split(':', 1)[1].strip()
    return None


# ============================================================
# 2. SINCRONIZAR EL MODELO
# ============================================================
def sincronizar_json(verbose=True):
    """
    Copia data/modelo_unity.json a StreamingAssets (proyecto) y, si ya
    hay una app compilada, tambien al StreamingAssets de la build.

    Asi la app muestra SIEMPRE el ultimo modelo calculado sin tener que
    recompilarla. Si se omite este paso, el visor sigue mostrando el
    modelo viejo y no avisa: parece que los cambios no tuvieron efecto.
    """
    if not os.path.exists(JSON_MODELO):
        raise FileNotFoundError(
            f"No existe {JSON_MODELO}. Corre antes exportar_unity.py")

    destinos = [STREAMING]
    build_sa = os.path.join(CARPETA_BUILD,
                            'LaboratorioEstructural_Data', 'StreamingAssets',
                            'modelo_unity.json')
    if os.path.isdir(os.path.dirname(build_sa)):
        destinos.append(build_sa)

    for d in destinos:
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(JSON_MODELO, d)
        if verbose:
            print(f"  modelo copiado a {os.path.relpath(d, _RAIZ)}")
    return destinos


# ============================================================
# 3. CORRER UNITY EN BATCH
# ============================================================
def _correr_unity(metodo, log, timeout=1800, version=None):
    """Ejecuta un metodo de Editor sin abrir la interfaz."""
    unity = buscar_unity(version)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    if os.path.exists(log):
        os.remove(log)

    cmd = [unity, '-batchmode', '-quit', '-nographics',
           '-projectPath', PROYECTO_UNITY,
           '-logFile', log,
           '-executeMethod', metodo]

    print(f"  Unity: {os.path.basename(os.path.dirname(os.path.dirname(unity)))}")
    print(f"  ejecutando {metodo} ... (puede tardar varios minutos)")
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    print(f"  termino en {time.time()-t0:.0f} s (codigo {proc.returncode})")
    return proc.returncode, log


def _errores_del_log(log, n=15):
    """Saca las lineas de error del log de Unity."""
    if not os.path.exists(log):
        return ["(no se genero log)"]
    claves = ('error CS', 'BUILD FALLO', 'Exception', 'Aborting')
    salida = []
    with open(log, encoding='utf-8', errors='replace') as f:
        for linea in f:
            if any(k in linea for k in claves):
                salida.append(linea.rstrip())
    return salida[:n]


# ============================================================
# 4. API PRINCIPAL
# ============================================================
def construir_app(forzar=False, version=None):
    """
    Compila la aplicacion standalone. Si ya existe y no se fuerza, no
    la vuelve a compilar (la build tarda varios minutos).
    """
    if os.path.exists(APP) and not forzar:
        print(f"La app ya existe: {os.path.relpath(APP, _RAIZ)}")
        print("  (usa construir_app(forzar=True) para recompilarla)")
        return APP

    sincronizar_json()
    log = os.path.join(_RAIZ, 'build', 'unity_build.log')
    codigo, log = _correr_unity('ConstruirApp.Construir', log,
                                version=version)

    if codigo != 0 or not os.path.exists(APP):
        print("\nLa compilacion FALLO. Errores del log:")
        for e in _errores_del_log(log):
            print("   ", e)
        raise RuntimeError(f"Unity no genero la app. Log: {log}")

    mb = os.path.getsize(APP) / 1048576
    print(f"App lista: {os.path.relpath(APP, _RAIZ)} ({mb:.1f} MB)")
    return APP


def abrir_visor(construir_si_falta=True, esperar=False):
    """
    Lanza el visor. Es lo que se llama desde el notebook.

    construir_si_falta : compila la app la primera vez.
    esperar            : si True, bloquea hasta que se cierre la app.
                         En un notebook conviene False, para poder
                         seguir usando las celdas.
    """
    sincronizar_json()

    if not os.path.exists(APP):
        if not construir_si_falta:
            raise FileNotFoundError(
                f"No existe {APP}. Corre construir_app() primero.")
        construir_app()

    print(f"Lanzando {os.path.basename(APP)} ...")
    proc = subprocess.Popen([APP], cwd=CARPETA_BUILD)
    if esperar:
        proc.wait()
    else:
        # Un momento para que alcance a fallar de forma visible si el
        # ejecutable esta roto; si no, el notebook diria "lanzado" aunque
        # la ventana nunca aparezca.
        time.sleep(2.0)
        if proc.poll() is not None:
            raise RuntimeError(
                f"La app se cerro de inmediato (codigo {proc.returncode}). "
                f"Revisa {os.path.join(CARPETA_BUILD, 'unity_build.log')}")
        print("Visor abierto. Controles: arrastrar=orbitar, "
              "derecho=panear, rueda=zoom, F=encuadrar, click=inspeccionar.")
    return proc


def abrir_servidor(puerto=5000):
    r"""
    Levanta el servidor de reanalisis en segundo plano.

    Hace falta SOLO para modificar el modelo desde Unity (cambiar una
    seccion, mover un nodo, borrar una barra) y volver a resolverlo. El
    visor funciona sin el; simplemente no se puede reanalizar.

    Por que hace falta un servidor: la app compilada NO puede correr
    OpenSees (es Python). Entonces Unity manda el modelo por HTTP,
    Python lo resuelve y devuelve los desplazamientos. Es la misma
    separacion de siempre -- OpenSees calcula, Unity muestra -- solo que
    ahora en vivo.

    Escucha solo en 127.0.0.1: nadie fuera de este equipo llega.
    """
    servidor = os.path.join(_AQUI, 'servidor_opensees.py')
    if not os.path.exists(servidor):
        raise FileNotFoundError(servidor)

    try:
        import flask  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Falta Flask. Instalalo con:\n"
            "    .venv\\Scripts\\python.exe -m pip install flask")

    print(f"Levantando el servidor de reanalisis en localhost:{puerto} ...")
    proc = subprocess.Popen([sys.executable, servidor, '--puerto', str(puerto)])
    time.sleep(2.0)
    if proc.poll() is not None:
        raise RuntimeError(
            f"El servidor se cerro de inmediato (codigo {proc.returncode}). "
            f"Puede que el puerto {puerto} este ocupado.")
    print("Servidor arriba. En el visor, el panel del editor ya puede")
    print("modificar el modelo y pedir un reanalisis.")
    print("Para detenerlo: proc.terminate() o cerrar esta consola.")
    return proc


def abrir_editor(version=None):
    """
    Abre el proyecto en el editor de Unity (para trabajar en el visor).
    Hay que apretar Play a mano: el modo Play no se puede automatizar
    desde fuera.
    """
    sincronizar_json()
    unity = buscar_unity(version)
    print(f"Abriendo el editor... (tarda ~1 min)")
    print("Cuando cargue: Assets/Scenes/SampleScene -> boton Play")
    return subprocess.Popen([unity, '-projectPath', PROYECTO_UNITY])


# ============================================================
if __name__ == '__main__':
    modo = sys.argv[1] if len(sys.argv) > 1 else 'app'
    if modo == 'editor':
        abrir_editor()
    elif modo == 'build':
        construir_app(forzar='--forzar' in sys.argv)
    elif modo == 'servidor':
        proc = abrir_servidor()
        try:
            proc.wait()          # queda en primer plano hasta Ctrl+C
        except KeyboardInterrupt:
            proc.terminate()
    else:
        abrir_visor()
