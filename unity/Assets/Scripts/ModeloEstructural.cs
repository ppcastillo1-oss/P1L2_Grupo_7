/*
================================================================
  ModeloEstructural.cs
================================================================
  FUENTE DE VERDAD del modelo de datos en Unity.

  Antes habia DOS juegos de clases para lo mismo:
    VisorEstructura.cs      -> NodoJSON, ElementoJSON, ModeloJSON
    AnalizadorEstructural.cs-> Nodo, Seccion, Elemento
  incompatibles entre si, asi que el visor no podia mandar al
  servidor lo que dibujaba, y el analizador no podia dibujar lo
  que mandaba. Ahora ambos usan ESTAS clases.

  ----------------------------------------------------------------
  REGLA DE ORO DE JsonUtility
  ----------------------------------------------------------------
  JsonUtility (el parser JSON que trae Unity) tiene tres limites que
  mandan sobre todo el diseno de este archivo:

    1. NO lee diccionarios con claves arbitrarias.
       Por eso "secciones" es una LISTA, no un diccionario, y por eso
       la respuesta del servidor tambien viene en listas.

    2. Solo serializa campos PUBLICOS de clases marcadas
       [System.Serializable]. Las propiedades (get/set) las ignora.

    3. Serializa SIEMPRE todos los campos. Un array que no asignaste
       sale como []. El servidor esta preparado: trata la lista vacia
       como "ausente".

  Los nombres de los campos deben calzar EXACTO con las claves del
  JSON. Si renombras uno aca, se rompe en silencio: JsonUtility no
  avisa, simplemente deja el campo en su valor por defecto.
  Hay un test que lo verifica: test_contrato_unity.py

  Unidades: m, kN, kPa (consistentes con OpenSees).
================================================================
*/

using System.Collections.Generic;

// ================================================================
// PARTE 1: DEFINICION DEL MODELO
//   (lo que Unity lee de modelo_unity.json y manda al servidor)
// ================================================================

// OJO con el nombre: NO se puede llamar 'Material' a secas, porque
// choca con UnityEngine.Material (el material grafico). Como esta clase
// vive en el namespace global, le GANA al 'using UnityEngine', y
// cualquier 'new Material(Shader.Find(...))' del proyecto deja de
// compilar. Y en Unity un solo error de compilacion bloquea
// Add Component para TODOS los scripts.
[System.Serializable]
public class MaterialModelo
{
    public float fpc_MPa = 25f;    // resistencia del hormigon
    public float poisson = 0.2f;
    public float gamma = 25f;      // peso especifico kN/m3
}

[System.Serializable]
public class Seccion
{
    public string nombre;          // "C50x50", "VX30x60", "MURO_M1"...
    public float A;                // area m2
    public float Iy;               // inercia m4
    public float Iz;
    public float J;                // torsion m4

    // Dimensiones REALES en metros, para poder dibujar el perfil.
    // b = ancho (a lo largo del eje local y)
    // h = canto (a lo largo del eje local z)
    public float b;
    public float h;

    public bool TienePerfil { get { return b > 0.001f && h > 0.001f; } }
}

[System.Serializable]
public class Nodo
{
    public int id;
    public float x, y, z;          // coordenadas OpenSees (Z vertical)

    public bool fijo;              // true = empotrado (los 6 GDL)

    // true = nodo intermedio creado al subdividir una viga. No es un
    // nudo del marco: existe para poder dibujar la flecha del vano.
    // El servidor lo ignora; solo cambia como se ve.
    public bool auxiliar;

    // Restriccion por grado de libertad: [ux,uy,uz,rx,ry,rz], 1 = fijo.
    // Vacio o ausente -> manda 'fijo'. Una rotula es [1,1,1,0,0,0].
    public int[] restricciones;

    // Deformada precalculada del caso G, para dibujar sin servidor.
    // NO son parte de la definicion del modelo; el servidor los ignora.
    public float ux, uy, uz;
}

[System.Serializable]
public class Elemento
{
    public int id;
    public int n1, n2;             // nodos que conecta
    public string seccion;         // debe existir en la lista de secciones
    public string tipo;            // "columna", "viga_x", "viga_y", "muro"

    // Orienta el eje fuerte de la seccion. Vacio = automatico segun la
    // geometria. Necesario para muros: hacia donde apunta su plano.
    public float[] vecxz;

    // Ejes locales YA CALCULADOS en Python, en coordenadas OpenSees.
    // Unity los DIBUJA; no los deduce. Deducirlos en C# seria duplicar
    // la convencion de geomTransf, y esa copia terminaria divergiendo
    // del modelo real sin que nadie se entere.
    public float[] localX;
    public float[] localY;
    public float[] localZ;

    // Solo para tipo == "muro": su tamano real en planta.
    // El muro se modela como UNA barra en su eje baricentrico ("columna
    // ancha"), asi que sin esto se dibujaria como una columna delgada y
    // no se podria comparar contra el plano.
    public float largo;
    public float espesor;

    public bool EsMuro { get { return tipo == "muro"; } }
}


// ================================================================
// AREAS TRIBUTARIAS
//   El poligono de losa que descarga sobre una viga, ya recortado
//   por las bisectrices a 45 grados. Viene calculado de Python.
// ================================================================
[System.Serializable]
public class VerticePlanta
{
    public float x, y;             // coordenadas de planta (OpenSees)
}

[System.Serializable]
public class AreaTributaria
{
    public int elemento;           // elementTag de la viga que carga
    public int nivel;
    public float area;             // m2
    public float luz;              // m
    public float qG;               // kN/m2
    public float carga_total;      // kN   = qG * area
    public float w;                // kN/m = carga_total / luz
    public float z;                // cota del piso
    // Los poligonos vienen CONCATENADOS (JsonUtility no lee listas de
    // listas) y 'tamanos' dice cuantos vertices tiene cada uno.
    public VerticePlanta[] vertices;
    public int[] tamanos;
    public int n_poligonos;

    /// <summary>
    /// Recorre los poligonos devolviendo (inicio, cantidad) de cada uno.
    ///
    /// NO se puede dividir vertices.Length entre n_poligonos: los
    /// poligonos NO miden todos lo mismo. Una viga interior toma un
    /// TRAPECIO de un pano (4 vertices) y un TRIANGULO del otro (3),
    /// o sea 7 en total; repartir 7/2 = 3 mezcla los vertices de uno
    /// con los del otro y dibuja lineas cruzadas que no existen.
    /// </summary>
    public System.Collections.Generic.IEnumerable<int[]> Poligonos()
    {
        if (vertices == null || vertices.Length < 3) yield break;

        if (tamanos != null && tamanos.Length > 0)
        {
            int inicio = 0;
            foreach (int cuantos in tamanos)
            {
                if (cuantos >= 3 && inicio + cuantos <= vertices.Length)
                    yield return new[] { inicio, cuantos };
                inicio += cuantos;
            }
            yield break;
        }

        // Sin 'tamanos' (JSON viejo): al menos dibujar todo como UN
        // poligono, que es preferible a inventar una particion mala.
        yield return new[] { 0, vertices.Length };
    }
}

[System.Serializable]
public class Diafragma
{
    public int nodo_maestro;       // normalmente el centro de masa del piso
    public int[] nodos;            // nodos esclavos (misma cota)
    public int perpendicular = 3;  // 3 = diafragma horizontal
}

[System.Serializable]
public class BrazoRigido
{
    public int maestro;
    public int esclavo;
    public string tipo = "beam";   // "beam" = traslaciones Y rotaciones
}

[System.Serializable]
public class CargaNodal
{
    public int nodo;
    public float fx, fy, fz;       // kN
    public float mx, my, mz;       // kN*m
}

[System.Serializable]
public class CargaDistribuida
{
    public int elemento;
    // Componentes en EJES LOCALES de la barra.
    // La gravedad va en wz (negativo) para vigas horizontales.
    public float wy, wz, wx;
}

[System.Serializable]
public class CasoDeCarga
{
    public string nombre;          // "G", "Q", "EX", "EY"
    public string descripcion;
    public List<CargaNodal> cargas_nodales;
    public List<CargaDistribuida> cargas_distribuidas;
}

[System.Serializable]
public class InfoModelo
{
    public string descripcion;
    public string unidades;
    public string caso_precalculado;
    public string nota;
}

// Contenedor: representa modelo_unity.json completo.
// Este MISMO objeto se manda al servidor sin transformar nada.
[System.Serializable]
public class ModeloEstructural
{
    public InfoModelo info;
    public MaterialModelo material;   // la clave JSON sigue siendo 'material'
    public List<Seccion> secciones;
    public List<Nodo> nodos;
    public List<Elemento> elementos;
    public List<Diafragma> diafragmas;
    public List<BrazoRigido> brazos_rigidos;
    public List<CasoDeCarga> casos_de_carga;
    public List<AreaTributaria> areas_tributarias;

    // --- Indice de areas tributarias por elementTag ---
    [System.NonSerialized]
    private Dictionary<int, AreaTributaria> _tribPorElemento;

    /// Area tributaria de una viga. null si esa viga no carga losa
    /// (una columna, por ejemplo).
    public AreaTributaria TributariaDe(int elementTag)
    {
        if (_tribPorElemento == null)
        {
            _tribPorElemento = new Dictionary<int, AreaTributaria>();
            if (areas_tributarias != null)
                foreach (AreaTributaria a in areas_tributarias)
                    _tribPorElemento[a.elemento] = a;
        }
        AreaTributaria r;
        return _tribPorElemento.TryGetValue(elementTag, out r) ? r : null;
    }

    // --- Indices para buscar rapido (no se serializan) ---
    [System.NonSerialized]
    private Dictionary<int, Nodo> _porId;

    /// Busca un nodo por id. Devuelve null si no existe.
    public Nodo NodoPorId(int id)
    {
        if (_porId == null)
        {
            _porId = new Dictionary<int, Nodo>();
            if (nodos != null)
                foreach (Nodo n in nodos) _porId[n.id] = n;
        }
        Nodo r;
        return _porId.TryGetValue(id, out r) ? r : null;
    }

    /// Hay que llamarlo si se agregan o quitan nodos.
    public void InvalidarIndice() { _porId = null; _porSeccion = null; }

    [System.NonSerialized]
    private Dictionary<string, Seccion> _porSeccion;

    /// Busca una seccion por nombre. null si no existe.
    public Seccion SeccionPorNombre(string nombre)
    {
        if (string.IsNullOrEmpty(nombre)) return null;
        if (_porSeccion == null)
        {
            _porSeccion = new Dictionary<string, Seccion>();
            if (secciones != null)
                foreach (Seccion s in secciones) _porSeccion[s.nombre] = s;
        }
        Seccion r;
        return _porSeccion.TryGetValue(nombre, out r) ? r : null;
    }

    public CasoDeCarga CasoPorNombre(string nombre)
    {
        if (casos_de_carga == null) return null;
        foreach (CasoDeCarga c in casos_de_carga)
            if (c.nombre == nombre) return c;
        return null;
    }
}


// ================================================================
// PARTE 2: RESPUESTA DEL SERVIDOR
// ================================================================

[System.Serializable]
public class DespNodo
{
    public int id;
    public float ux, uy, uz;       // traslaciones (m)
    public float rx, ry, rz;       // rotaciones (rad)
}

[System.Serializable]
public class ReacNodo
{
    public int id;
    public float fx, fy, fz;       // kN
    public float mx, my, mz;       // kN*m
}

[System.Serializable]
public class FuerzaElemento
{
    public int id;
    // Esfuerzos en EJES LOCALES de la barra (no globales):
    // [N_i,Vy_i,Vz_i,T_i,My_i,Mz_i, N_j,Vy_j,Vz_j,T_j,My_j,Mz_j]
    // Bajo gravedad: cortante vertical en Vz (idx 2),
    // momento flector en My (idx 4 y 10).
    public float[] f;

    public float N_i  { get { return f != null && f.Length > 0 ? f[0] : 0f; } }
    public float Vz_i { get { return f != null && f.Length > 2 ? f[2] : 0f; } }
    public float My_i { get { return f != null && f.Length > 4 ? f[4] : 0f; } }
    public float My_j { get { return f != null && f.Length > 10 ? f[10] : 0f; } }
}

// Un caso de carga resuelto (G, Q, EX, EY...).
[System.Serializable]
public class CasoResultado
{
    public string nombre;
    public bool ok;
    public float max_desplazamiento;
    public List<DespNodo> desplazamientos;
    public List<ReacNodo> reacciones;
    public List<FuerzaElemento> fuerzas_elementos;
}

[System.Serializable]
public class RespuestaServidor
{
    public bool ok;
    public string error;

    // Etiquetas 'tipo' que no calzan con la geometria real del elemento.
    // No son errores (el modelo se resolvio igual), pero delatan datos
    // mal importados del DXF.
    public List<string> avisos;

    // --- Forma PLANA: cuando se manda un solo caso de carga ---
    public float max_desplazamiento;
    public List<DespNodo> desplazamientos;
    public List<ReacNodo> reacciones;
    public List<FuerzaElemento> fuerzas_elementos;

    // --- Forma MULTI-CASO: cuando se manda "casos_de_carga" ---
    // Si viene con contenido, manda esta y se ignora la plana.
    public List<CasoResultado> casos;

    /// Normaliza ambas formas a una lista de casos.
    public List<CasoResultado> ComoCasos()
    {
        if (casos != null && casos.Count > 0) return casos;

        List<CasoResultado> l = new List<CasoResultado>();
        if (desplazamientos != null && desplazamientos.Count > 0)
        {
            l.Add(new CasoResultado {
                nombre = "unico", ok = ok,
                max_desplazamiento = max_desplazamiento,
                desplazamientos = desplazamientos,
                reacciones = reacciones,
                fuerzas_elementos = fuerzas_elementos
            });
        }
        return l;
    }
}


// ================================================================
// PARTE 3: CONVERSION DE EJES  (el swap que todos olvidan)
// ================================================================
public static class Ejes
{
    /// OpenSees usa Z vertical; Unity usa Y vertical.
    ///   Unity(x, z_opensees, y_opensees)
    /// Si el edificio se ve "acostado", este swap esta mal.
    public static UnityEngine.Vector3 AUnity(float x, float y_os, float z_os)
    {
        return new UnityEngine.Vector3(x, z_os, y_os);
    }

    public static UnityEngine.Vector3 PosicionDe(Nodo n)
    {
        return AUnity(n.x, n.y, n.z);
    }

    /// Posicion deformada = original + desplazamiento * escala.
    /// Siempre se parte de la coordenada ORIGINAL: si se acumulara
    /// sobre la posicion actual, cada recalculo correria la estructura.
    public static UnityEngine.Vector3 PosicionDeformada(
        Nodo n, float ux, float uy, float uz, float escala)
    {
        return AUnity(n.x + ux * escala,
                      n.y + uy * escala,
                      n.z + uz * escala);
    }
}


// ================================================================
// PARTE 4: ETIQUETAS EN LOS OBJETOS DE LA ESCENA
//   conectan el GameObject con el nodeTag/eleTag de OpenSees
// ================================================================
public class DatoNodo : UnityEngine.MonoBehaviour { public int idNodo; }
public class DatoElemento : UnityEngine.MonoBehaviour { public int idElemento; }
