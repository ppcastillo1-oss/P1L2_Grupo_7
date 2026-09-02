/*
================================================================
  VisorEstructura.cs
================================================================
  DIBUJA el modelo estructural en 3D. Nada mas.

  No habla con el servidor ni define clases de datos: usa las de
  ModeloEstructural.cs. Quien calcula es AnalizadorEstructural.cs,
  que le pasa los desplazamientos ya resueltos.

  Esta separacion es la misma regla del CLAUDE.md: OpenSees calcula,
  Unity muestra.

  ----------------------------------------------------------------
  COMO USARLO
  1. Copia modelo_unity.json a Assets/StreamingAssets/
     (generalo con: python generar_json_unity.py)
  2. Crea un GameObject vacio, llamalo "Visor".
  3. Arrastra este script encima.
  4. Play. Deberias ver el marco en 3D.

  Para ver la deformada de otros casos (Q, EX, EY) necesitas el
  servidor corriendo y el script AnalizadorEstructural.
  ----------------------------------------------------------------
*/

using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

public class VisorEstructura : MonoBehaviour
{
    [Header("Archivo")]
    public string nombreArchivo = "modelo_unity.json";

    [Header("Apariencia")]
    public float radioNodo = 0.15f;
    [Tooltip("Nodos intermedios de las vigas. Se dibujan mas chicos "
           + "para que no compitan con los nudos reales del marco.")]
    public float radioNodoAuxiliar = 0.05f;
    public float grosorBarra = 0.05f;
    public Color colorColumna = new Color(0.36f, 0.62f, 1f);    // azul
    public Color colorViga = new Color(0.88f, 0.48f, 0.37f);    // naranjo
    public Color colorMuro = new Color(0.65f, 0.65f, 0.70f);    // gris
    public Color colorApoyo = new Color(0.18f, 0.60f, 0.37f);   // verde
    public Color colorNodoAuxiliar = new Color(0.55f, 0.58f, 0.62f); // gris
    public Color colorDeformada = Color.yellow;

    [Header("Deformada")]
    public bool mostrarDeformada = false;
    [Tooltip("Amplifica el desplazamiento. Los mm reales no se verian.")]
    public float factorEscala = 300f;

    [Header("Perfiles")]
    [Tooltip("Dibuja cada barra con su seccion REAL (b x h) en vez de un "
           + "cilindro generico. Asi se ve que una viga es 30x80 y otra "
           + "30x60, que es lo que se revisa a ojo contra el plano.")]
    public bool verPerfiles = false;

    [Header("Capas visibles")]
    public bool verNodos = true;
    [Tooltip("Los nodos intermedios de las vigas. Apagalos para ver "
           + "solo los nudos del marco.")]
    public bool verNodosAuxiliares = true;
    public bool verColumnas = true;
    public bool verVigas = true;
    public bool verMuros = true;

    // --- Estado ---
    /// El modelo cargado. AnalizadorEstructural lo lee para mandarlo
    /// al servidor: es el MISMO objeto, no una copia.
    public ModeloEstructural Modelo { get; private set; }

    // Desplazamientos actualmente dibujados, indexados por id de nodo.
    private Dictionary<int, DespNodo> deformadaActual = new Dictionary<int, DespNodo>();

    private List<GameObject> objetosCreados = new List<GameObject>();

    // Objetos de la escena indexados por el id de OpenSees. Es lo que
    // permite seleccionar y resaltar desde EditorEstructura.
    private Dictionary<int, GameObject> objetoDeNodo = new Dictionary<int, GameObject>();
    private Dictionary<int, GameObject> objetoDeElemento = new Dictionary<int, GameObject>();

    public GameObject ObjetoDeNodo(int id)
    {
        GameObject g;
        return objetoDeNodo.TryGetValue(id, out g) ? g : null;
    }

    public GameObject ObjetoDeElemento(int id)
    {
        GameObject g;
        return objetoDeElemento.TryGetValue(id, out g) ? g : null;
    }
    private Dictionary<Color, Material> materiales = new Dictionary<Color, Material>();
    private bool necesitaRedibujar = false;

    // ============================================================
    void Start()
    {
        if (CargarJSON())
        {
            UsarDeformadaPrecalculada();
            Redibujar();
        }
    }

    // ============================================================
    // CARGAR EL JSON
    // ============================================================
    public bool CargarJSON()
    {
        string ruta = Path.Combine(Application.streamingAssetsPath, nombreArchivo);

        if (!File.Exists(ruta))
        {
            Debug.LogError("No encontre el archivo: " + ruta);
            Debug.LogError("Generalo con 'python generar_json_unity.py' y "
                           + "copialo a Assets/StreamingAssets/");
            return false;
        }

        try
        {
            Modelo = JsonUtility.FromJson<ModeloEstructural>(File.ReadAllText(ruta));
        }
        catch (System.Exception ex)
        {
            Debug.LogError("El JSON no se pudo interpretar: " + ex.Message);
            return false;
        }

        if (Modelo == null || Modelo.nodos == null || Modelo.nodos.Count == 0)
        {
            Debug.LogError("El JSON no trae nodos. Revisa que sea el formato "
                           + "que genera generar_json_unity.py");
            return false;
        }

        Modelo.InvalidarIndice();
        Debug.Log($"Modelo cargado: {Modelo.nodos.Count} nodos, "
                  + $"{Modelo.elementos.Count} elementos, "
                  + $"{(Modelo.casos_de_carga != null ? Modelo.casos_de_carga.Count : 0)} casos.");
        return true;
    }

    // ============================================================
    // DEFORMADA
    // ============================================================

    /// Usa los ux/uy/uz que vienen en el JSON (caso G precalculado).
    /// Permite ver una deformada sin tener el servidor corriendo.
    public void UsarDeformadaPrecalculada()
    {
        deformadaActual.Clear();
        foreach (Nodo n in Modelo.nodos)
        {
            deformadaActual[n.id] = new DespNodo {
                id = n.id, ux = n.ux, uy = n.uy, uz = n.uz
            };
        }
    }

    /// Borra la deformada dibujada. Se llama al editar el modelo: los
    /// desplazamientos anteriores ya no corresponden a esta geometria.
    public void LimpiarDeformada()
    {
        deformadaActual.Clear();
        mostrarDeformada = false;
    }

    /// Recibe los desplazamientos resueltos por el servidor.
    /// Lo llama AnalizadorEstructural cuando llega una respuesta.
    public void AplicarDeformada(List<DespNodo> desplazamientos)
    {
        if (desplazamientos == null) return;
        deformadaActual.Clear();
        foreach (DespNodo d in desplazamientos) deformadaActual[d.id] = d;
        Redibujar();
    }

    /// Posicion de un nodo, deformada o no segun el toggle.
    Vector3 PosicionDe(Nodo n)
    {
        if (!mostrarDeformada) return Ejes.PosicionDe(n);

        DespNodo d;
        if (!deformadaActual.TryGetValue(n.id, out d)) return Ejes.PosicionDe(n);
        return Ejes.PosicionDeformada(n, d.ux, d.uy, d.uz, factorEscala);
    }

    // ============================================================
    // DIBUJO
    // ============================================================
    public void Redibujar()
    {
        if (Modelo == null) return;

        foreach (var go in objetosCreados) if (go != null) Destroy(go);
        objetosCreados.Clear();
        objetoDeNodo.Clear();
        objetoDeElemento.Clear();

        // --- Nodos ---
        if (verNodos)
        {
            foreach (Nodo n in Modelo.nodos)
            {
                if (n.auxiliar && !verNodosAuxiliares) continue;

                GameObject esfera = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                esfera.name = (n.auxiliar ? "NodoAux_" : "Nodo_") + n.id;
                esfera.transform.position = PosicionDe(n);

                // Los auxiliares van mas chicos y en gris: estan para
                // que se vea la curva de la viga, no para leerlos.
                float r = n.auxiliar ? radioNodoAuxiliar : radioNodo;
                esfera.transform.localScale = Vector3.one * r * 2f;

                bool apoyado = n.fijo || TieneAlgunaRestriccion(n);
                Pintar(esfera, n.auxiliar ? colorNodoAuxiliar
                             : (apoyado ? colorApoyo : colorColumna));

                esfera.AddComponent<DatoNodo>().idNodo = n.id;
                objetoDeNodo[n.id] = esfera;
                objetosCreados.Add(esfera);
            }
        }

        // --- Elementos ---
        if (Modelo.elementos == null) return;
        foreach (Elemento e in Modelo.elementos)
        {
            if (!CapaVisible(e.tipo)) continue;

            Nodo a = Modelo.NodoPorId(e.n1);
            Nodo b = Modelo.NodoPorId(e.n2);
            if (a == null || b == null)
            {
                Debug.LogError($"Elemento {e.id} referencia un nodo inexistente "
                               + $"(n1={e.n1}, n2={e.n2}). Se omite.");
                continue;
            }

            GameObject barra;
            if (e.EsMuro && e.largo > 0.01f)
            {
                barra = CrearPlacaMuro(PosicionDe(a), PosicionDe(b), e);
            }
            else if (verPerfiles)
            {
                Seccion sec = Modelo.SeccionPorNombre(e.seccion);
                barra = (sec != null && sec.TienePerfil)
                    ? CrearPerfil(PosicionDe(a), PosicionDe(b), e, sec)
                    : CrearCilindro(PosicionDe(a), PosicionDe(b), grosorBarra);
            }
            else
            {
                barra = CrearCilindro(PosicionDe(a), PosicionDe(b), grosorBarra);
            }
            barra.name = "Elem_" + e.id + "_" + e.tipo;
            Pintar(barra, mostrarDeformada ? colorDeformada : ColorDe(e.tipo));
            barra.AddComponent<DatoElemento>().idElemento = e.id;
            objetoDeElemento[e.id] = barra;
            objetosCreados.Add(barra);
        }
    }

    bool TieneAlgunaRestriccion(Nodo n)
    {
        if (n.restricciones == null) return false;
        foreach (int r in n.restricciones) if (r != 0) return true;
        return false;
    }

    bool CapaVisible(string tipo)
    {
        if (tipo == "columna") return verColumnas;
        if (tipo == "muro") return verMuros;
        return verVigas;   // viga_x, viga_y y cualquier otra
    }

    Color ColorDe(string tipo)
    {
        if (tipo == "columna") return colorColumna;
        if (tipo == "muro") return colorMuro;
        return colorViga;
    }

    // ============================================================
    // PERFILES
    // ============================================================
    /// <summary>
    /// Dibuja la barra con su seccion REAL (b x h), orientada segun sus
    /// EJES LOCALES.
    ///
    /// La orientacion no se adivina: se usan los versores localX/localY/
    /// localZ que vienen calculados desde Python con la misma convencion
    /// de geomTransf que uso OpenSees. Por eso el perfil que se ve es
    /// literalmente el que se calculo: si alguien cambiara vecxz en el
    /// modelo, el dibujo giraria con el.
    ///
    /// Convencion: b va a lo largo del eje local y, h a lo largo del
    /// local z. Para una viga con vecxz=(0,0,1) el local z es el
    /// vertical, asi que h es el CANTO -- que es lo que uno espera ver.
    /// </summary>
    GameObject CrearPerfil(Vector3 desde, Vector3 hasta, Elemento e, Seccion sec)
    {
        GameObject caja = GameObject.CreatePrimitive(PrimitiveType.Cube);
        caja.transform.position = (desde + hasta) / 2f;

        float largo = (hasta - desde).magnitude;

        Vector3 ejeX = (hasta - desde).normalized;          // ya en Unity
        Vector3 ejeZ = VectorUnity(e.localZ, Vector3.up);   // canto

        // Si por lo que sea localZ resultara paralelo al eje de la
        // barra, LookRotation devolveria basura: se usa un respaldo.
        if (Mathf.Abs(Vector3.Dot(ejeX, ejeZ)) > 0.999f)
            ejeZ = Mathf.Abs(ejeX.y) > 0.9f ? Vector3.forward : Vector3.up;

        // forward = eje de la barra, up = canto.
        // Queda: cubo Z = largo, cubo Y = h, cubo X = b.
        caja.transform.rotation = Quaternion.LookRotation(ejeX, ejeZ);
        caja.transform.localScale = new Vector3(sec.b, sec.h, largo);
        return caja;
    }

    /// Pasa un vector en ejes OpenSees (como viene del JSON) a Unity.
    /// Los VECTORES tienen que cruzar el mismo swap Z-Y que las
    /// posiciones; si no, apuntan mal aunque el modelo se vea bien.
    static Vector3 VectorUnity(float[] v, Vector3 porDefecto)
    {
        if (v == null || v.Length < 3) return porDefecto;
        Vector3 r = Ejes.AUnity(v[0], v[1], v[2]);
        return r.sqrMagnitude > 1e-8f ? r.normalized : porDefecto;
    }

    // ============================================================
    // MUROS
    // ============================================================
    /// <summary>
    /// Dibuja un muro con su tamano REAL en planta (largo x espesor),
    /// no como una barra delgada.
    ///
    /// POR QUE
    /// El muro se idealiza como "columna ancha": UNA barra vertical en
    /// su eje baricentrico. Eso es correcto para el calculo, pero si se
    /// dibuja tal cual se ve una columna flaca en medio del vano y es
    /// imposible juzgar si el muro esta donde dice el plano, ni hacia
    /// donde apunta su eje fuerte.
    ///
    /// La orientacion sale de 'vecxz', que en un muro apunta en la
    /// direccion del muro en planta -- el MISMO vector con el que
    /// OpenSees oriento su inercia fuerte. Asi lo que se ve y lo que se
    /// calculo no pueden desincronizarse.
    /// </summary>
    GameObject CrearPlacaMuro(Vector3 desde, Vector3 hasta, Elemento e)
    {
        GameObject caja = GameObject.CreatePrimitive(PrimitiveType.Cube);
        caja.transform.position = (desde + hasta) / 2f;

        float alto = (hasta - desde).magnitude;

        // vecxz viene en ejes OpenSees (x, y de planta): hay que pasarlo
        // por el mismo swap que las posiciones.
        Vector3 dir = Vector3.right;
        if (e.vecxz != null && e.vecxz.Length >= 2)
        {
            Vector3 d = Ejes.AUnity(e.vecxz[0], e.vecxz[1], 0f);
            if (d.sqrMagnitude > 1e-8f) dir = d.normalized;
        }

        // El cubo queda: X = largo del muro, Y = alto de piso,
        // Z = espesor. Rotarlo para que su X apunte a lo largo del muro.
        caja.transform.rotation = Quaternion.LookRotation(
            Vector3.Cross(dir, Vector3.up).normalized, Vector3.up);
        caja.transform.localScale = new Vector3(
            Mathf.Max(e.largo, 0.05f), alto, Mathf.Max(e.espesor, 0.05f));

        return caja;
    }

    // Unity no tiene "linea gruesa 3D": se usa un cilindro estirado.
    GameObject CrearCilindro(Vector3 desde, Vector3 hasta, float grosor)
    {
        GameObject cil = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        cil.transform.position = (desde + hasta) / 2f;

        Vector3 direccion = hasta - desde;
        float largo = direccion.magnitude;

        // El cilindro de Unity mide 2 de alto y apunta en Y.
        cil.transform.localScale = new Vector3(grosor, largo / 2f, grosor);
        if (largo > 1e-6f) cil.transform.up = direccion.normalized;
        return cil;
    }

    // Cachea materiales: crear uno por objeto deja cientos huerfanos
    // que Unity no libera. Con el edificio completo es una fuga real.
    void Pintar(GameObject go, Color color)
    {
        Material mat;
        if (!materiales.TryGetValue(color, out mat))
        {
            mat = new Material(ShaderDelProyecto());
            mat.color = color;
            // URP/HDRP usan _BaseColor. Material.color suele mapearlo
            // solo, pero asignarlo explicito no cuesta nada y evita
            // depender de la version de Unity.
            if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
            materiales[color] = mat;
        }
        go.GetComponent<Renderer>().sharedMaterial = mat;
    }

    // ============================================================
    // El shader depende del RENDER PIPELINE del proyecto.
    // "Standard" solo existe en el Built-in. En URP (que es lo que usa
    // la plantilla 3D de Unity 6) Shader.Find("Standard") devuelve
    // null, y un material sin shader se dibuja MAGENTA.
    // Si toda la estructura se ve rosada, es esto.
    // ============================================================
    static Shader shaderCache;

    /// Version publica: VisorQA necesita el mismo shader para que sus
    /// capas no salgan magenta cuando el proyecto usa URP.
    public static Shader ShaderCompatible()
    {
        return ShaderDelProyecto();
    }

    static Shader ShaderDelProyecto()
    {
        if (shaderCache != null) return shaderCache;

        // currentRenderPipeline != null significa URP o HDRP.
        if (GraphicsSettings.currentRenderPipeline != null)
        {
            shaderCache = Shader.Find("Universal Render Pipeline/Lit");
            if (shaderCache == null) shaderCache = Shader.Find("HDRP/Lit");
        }
        if (shaderCache == null) shaderCache = Shader.Find("Standard");
        if (shaderCache == null) shaderCache = Shader.Find("Unlit/Color");

        if (shaderCache == null)
            Debug.LogError("No encontre ningun shader utilizable. Todo se "
                           + "vera magenta.");
        return shaderCache;
    }

    // ============================================================
    // Permite prender/apagar toggles desde el Inspector en Play.
    // OJO: NO se puede llamar Destroy() desde OnValidate (Unity lo
    // prohibe). Solo levantamos una bandera; se redibuja en Update.
    // ============================================================
    void OnValidate()
    {
        if (Application.isPlaying && Modelo != null) necesitaRedibujar = true;
    }

    void Update()
    {
        if (necesitaRedibujar) { necesitaRedibujar = false; Redibujar(); }
    }
}
