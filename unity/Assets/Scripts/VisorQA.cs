/*
================================================================
  VisorQA.cs
================================================================
  Capas de CONTROL DE CALIDAD sobre el modelo que dibuja
  VisorEstructura: apoyos, diafragmas, IDs, ejes locales y areas
  tributarias.

  El viewer no es decoracion. Existe para poder contestar, senalando
  con el mouse:

      - que elemento estoy mirando y que elementTag tiene;
      - que nodos lo definen;
      - como esta apoyado (los 6 GDL, no "se ve empotrado");
      - como esta orientado (sus ejes locales);
      - que area tributaria carga;
      - cuantos kN de losa le llegan.

  ----------------------------------------------------------------
  COMO USARLO
  1. En la escena, el GameObject que tiene VisorEstructura.
  2. Agregarle TAMBIEN este script.
  3. Arrastrar el VisorEstructura al campo 'visor'.
  4. Play. Los toggles estan en el Inspector y se pueden prender y
     apagar en vivo. Click izquierdo sobre una barra para
     seleccionarla.
  ----------------------------------------------------------------

  REGLA QUE NO SE ROMPE: aca no se calcula estructura. Los ejes
  locales, las areas y las cargas vienen calculados de Python en el
  JSON. Este script solo los dibuja y los escribe en pantalla.
================================================================
*/

using System.Collections.Generic;
using System.Text;
using UnityEngine;

[RequireComponent(typeof(VisorEstructura))]
public class VisorQA : MonoBehaviour
{
    [Header("Referencias")]
    public VisorEstructura visor;
    public Camera camara;
    [Tooltip("Se busca sola si no se asigna. Sirve para no seleccionar "
           + "cuando el click fue en realidad un arrastre de camara.")]
    public CamaraOrbital orbital;

    // Rectangulo del panel de la UI, en pixeles de pantalla. Se usa para
    // no dejar que un click sobre la interfaz atraviese al modelo.
    // El alto se ajusta a la pantalla: con muchos controles el panel no
    // cabe en una ventana chica y, sin scroll, los de abajo quedan
    // inalcanzables.
    static Rect RectPanel()
    {
        return new Rect(10, 10, 430, Mathf.Min(Screen.height - 20, 760));
    }

    private Vector2 scroll;

    [Header("Capas QA")]
    public bool verApoyos = true;
    public bool verDiafragmas = false;
    public bool verEjesLocales = false;
    public bool verAreasTributarias = false;
    public bool verIDs = false;

    [Header("Filtro de piso  (-1 = todos)")]
    [Tooltip("Con 1200 elementos, mirar un piso a la vez es la unica "
           + "forma de revisar algo. -1 muestra el edificio completo.")]
    public int soloNivel = -1;

    [Header("Apariencia")]
    public float tamanoApoyo = 0.45f;
    public float largoEje = 1.2f;
    public float grosorLinea = 0.04f;
    [Tooltip("Los IDs son texto 3D: con miles a la vez Unity se arrastra. "
           + "Solo se dibujan los de los elementos mas cercanos a la camara.")]
    public int maxIDs = 120;

    [Header("Colores")]
    public Color colorApoyo = new Color(0.10f, 0.80f, 0.35f);
    public Color colorDiafragma = new Color(1f, 0.85f, 0.15f);
    public Color colorEjeX = new Color(1f, 0.25f, 0.25f);   // rojo
    public Color colorEjeY = new Color(0.25f, 1f, 0.25f);   // verde
    public Color colorEjeZ = new Color(0.35f, 0.55f, 1f);   // azul
    public Color colorTributaria = new Color(1f, 0.55f, 0.10f, 0.85f);
    public Color colorSeleccion = new Color(1f, 0f, 0.85f);

    // --- Estado ---
    private readonly List<GameObject> creados = new List<GameObject>();
    private Elemento seleccionado;
    private Material matLinea;
    private bool refrescar = true;

    // Texto del panel de seleccion (se dibuja con OnGUI).
    private string panel = "";

    // ============================================================
    void Reset()
    {
        visor = GetComponent<VisorEstructura>();
        camara = Camera.main;
    }

    void Start()
    {
        if (visor == null) visor = GetComponent<VisorEstructura>();
        if (camara == null) camara = Camera.main;
        if (orbital == null && camara != null)
            orbital = camara.GetComponent<CamaraOrbital>();
    }

    void OnValidate()
    {
        if (Application.isPlaying) refrescar = true;
    }

    void Update()
    {
        if (visor == null || visor.Modelo == null) return;

        LeerClick();

        if (refrescar)
        {
            refrescar = false;
            Redibujar();
        }
    }

    // ============================================================
    // SELECCION
    // ============================================================
    void LeerClick()
    {
        // Se selecciona al SOLTAR, no al presionar, y solo si no hubo
        // arrastre: el mismo boton izquierdo lo usa CamaraOrbital para
        // orbitar. Si se seleccionara en GetMouseButtonDown, cada vez
        // que giras la vista seleccionarias lo que hubiera debajo del
        // cursor. Es la misma convencion que ya usa EditorEstructura.
        if (!Input.GetMouseButtonUp(0)) return;
        if (camara == null) return;
        if (orbital != null && orbital.HuboArrastre) return;

        // Un click sobre el panel de la UI no debe atravesar y
        // seleccionar la barra que haya detras.
        if (MouseSobrePanel()) return;

        Ray rayo = camara.ScreenPointToRay(Input.mousePosition);
        RaycastHit hit;
        if (!Physics.Raycast(rayo, out hit, 10000f)) return;

        DatoElemento de = hit.collider.GetComponentInParent<DatoElemento>();
        if (de == null) return;

        seleccionado = BuscarElemento(de.idElemento);
        panel = DescribirSeleccion();
        refrescar = true;
    }

    /// El origen de GUI esta arriba-izquierda y el de Input.mousePosition
    /// abajo-izquierda: hay que invertir la Y antes de comparar.
    ///
    /// Se consulta tambien el panel del EDITOR (que vive a la derecha):
    /// un click sobre el no debe atravesar y seleccionar la barra que
    /// haya detras.
    bool MouseSobrePanel()
    {
        Vector2 p = new Vector2(Input.mousePosition.x,
                                Screen.height - Input.mousePosition.y);
        if (RectPanel().Contains(p)) return true;

        if (editor == null) editor = FindAnyObjectByType<EditorEstructura>();
        return editor != null && editor.MouseSobrePanel();
    }

    private EditorEstructura editor;

    Elemento BuscarElemento(int id)
    {
        foreach (Elemento e in visor.Modelo.elementos)
            if (e.id == id) return e;
        return null;
    }

    /// Arma el texto que contesta las preguntas de la defensa.
    string DescribirSeleccion()
    {
        if (seleccionado == null) return "";
        ModeloEstructural m = visor.Modelo;
        Elemento e = seleccionado;

        StringBuilder sb = new StringBuilder();
        sb.AppendLine($"ELEMENTO  {e.id}");
        sb.AppendLine($"tipo      {e.tipo}");
        sb.AppendLine($"seccion   {e.seccion}");
        sb.AppendLine($"nodos     {e.n1} -> {e.n2}");

        Nodo a = m.NodoPorId(e.n1);
        Nodo b = m.NodoPorId(e.n2);
        if (a != null && b != null)
        {
            float L = Mathf.Sqrt((b.x - a.x) * (b.x - a.x)
                               + (b.y - a.y) * (b.y - a.y)
                               + (b.z - a.z) * (b.z - a.z));
            sb.AppendLine($"largo     {L:F3} m");
            sb.AppendLine($"nodo {e.n1}   ({a.x:F2}, {a.y:F2}, {a.z:F2})"
                          + (EsApoyo(a) ? "   APOYO " + Fixity(a) : ""));
            sb.AppendLine($"nodo {e.n2}   ({b.x:F2}, {b.y:F2}, {b.z:F2})"
                          + (EsApoyo(b) ? "   APOYO " + Fixity(b) : ""));
        }

        if (e.localX != null && e.localX.Length == 3)
        {
            sb.AppendLine("--- ejes locales (OpenSees) ---");
            sb.AppendLine($"local x   {Vec(e.localX)}");
            sb.AppendLine($"local y   {Vec(e.localY)}");
            sb.AppendLine($"local z   {Vec(e.localZ)}");
        }

        AreaTributaria t = m.TributariaDe(e.id);
        if (t != null)
        {
            sb.AppendLine("--- area tributaria ---");
            sb.AppendLine($"A_trib    {t.area:F3} m2   ({t.n_poligonos} pano(s))");
            sb.AppendLine($"q_G       {t.qG:F2} kN/m2");
            sb.AppendLine($"carga     {t.carga_total:F2} kN de losa");
            sb.AppendLine($"w         {t.w:F3} kN/m sobre la viga");
            sb.AppendLine($"chequeo   w*L = {(t.w * t.luz):F2} kN  "
                          + $"(= q*A = {(t.qG * t.area):F2})");
        }
        else
        {
            sb.AppendLine("(este elemento no recibe carga de losa)");
        }
        return sb.ToString();
    }

    static string Vec(float[] v)
    {
        if (v == null || v.Length < 3) return "-";
        return $"({v[0]:+0.000;-0.000}, {v[1]:+0.000;-0.000}, {v[2]:+0.000;-0.000})";
    }

    static bool EsApoyo(Nodo n)
    {
        if (n.fijo) return true;
        if (n.restricciones == null) return false;
        foreach (int r in n.restricciones) if (r != 0) return true;
        return false;
    }

    /// Los 6 GDL en el orden [ux,uy,uz,rx,ry,rz]. Un apoyo es una lista
    /// explicita de restricciones, no "lo que parece en el dibujo".
    static string Fixity(Nodo n)
    {
        if (n.restricciones == null || n.restricciones.Length < 6)
            return n.fijo ? "[1 1 1 1 1 1]" : "[0 0 0 0 0 0]";
        return $"[{n.restricciones[0]} {n.restricciones[1]} {n.restricciones[2]} "
             + $"{n.restricciones[3]} {n.restricciones[4]} {n.restricciones[5]}]";
    }

    // ============================================================
    // DIBUJO DE LAS CAPAS
    // ============================================================
    void Redibujar()
    {
        foreach (GameObject g in creados) if (g != null) Destroy(g);
        creados.Clear();

        ModeloEstructural m = visor.Modelo;
        if (m == null) return;

        if (verApoyos) DibujarApoyos(m);
        if (verDiafragmas) DibujarDiafragmas(m);
        if (verEjesLocales) DibujarEjesLocales(m);
        if (verAreasTributarias) DibujarTributarias(m);
        if (verIDs) DibujarIDs(m);
        if (seleccionado != null) Resaltar(seleccionado, m);
    }

    bool NivelVisible(float z)
    {
        return soloNivel < 0 || Mathf.Abs(z - CotaDeNivel(soloNivel)) < 0.01f;
    }

    float CotaDeNivel(int nivel)
    {
        // Las cotas reales viven en el JSON; aca solo se usan para
        // filtrar visualmente. Se toman del primer nodo de esa cota.
        float[] cotas = { 0f, 4f, 7.5f, 11f, 14.5f, 18f, 21.5f, 25f, 28.5f };
        return (nivel >= 0 && nivel < cotas.Length) ? cotas[nivel] : -999f;
    }

    // --- Apoyos ---
    void DibujarApoyos(ModeloEstructural m)
    {
        foreach (Nodo n in m.nodos)
        {
            if (!EsApoyo(n)) continue;
            GameObject c = GameObject.CreatePrimitive(PrimitiveType.Cube);
            c.name = $"Apoyo_{n.id}";
            c.transform.position = Ejes.PosicionDe(n);
            c.transform.localScale = Vector3.one * tamanoApoyo;
            Pintar(c, colorApoyo);
            c.AddComponent<DatoNodo>().idNodo = n.id;
            creados.Add(c);
        }
    }

    // --- Diafragmas ---
    // Se dibuja el nodo maestro y un radio a cada esclavo: se ve de
    // inmediato que piso esta ligado a que maestro, y si algun nodo
    // quedo fuera del diafragma.
    void DibujarDiafragmas(ModeloEstructural m)
    {
        if (m.diafragmas == null) return;
        foreach (Diafragma d in m.diafragmas)
        {
            Nodo maestro = m.NodoPorId(d.nodo_maestro);
            if (maestro == null) continue;
            if (!NivelVisible(maestro.z)) continue;

            Vector3 pm = Ejes.PosicionDe(maestro);
            GameObject e = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            e.name = $"Maestro_{d.nodo_maestro}";
            e.transform.position = pm;
            e.transform.localScale = Vector3.one * tamanoApoyo * 1.6f;
            Pintar(e, colorDiafragma);
            creados.Add(e);

            if (d.nodos == null) continue;
            foreach (int idEsclavo in d.nodos)
            {
                Nodo s = m.NodoPorId(idEsclavo);
                if (s == null) continue;
                creados.Add(Linea(pm, Ejes.PosicionDe(s),
                                  grosorLinea * 0.5f, colorDiafragma,
                                  $"Diaf_{d.nodo_maestro}_{idEsclavo}"));
            }
        }
    }

    // --- Ejes locales ---
    void DibujarEjesLocales(ModeloEstructural m)
    {
        foreach (Elemento e in m.elementos)
        {
            if (e.localX == null || e.localX.Length < 3) continue;
            Nodo a = m.NodoPorId(e.n1);
            Nodo b = m.NodoPorId(e.n2);
            if (a == null || b == null) continue;
            if (!NivelVisible(a.z) && !NivelVisible(b.z)) continue;

            // Centro de la barra, en coordenadas OpenSees -> Unity.
            Vector3 c = (Ejes.PosicionDe(a) + Ejes.PosicionDe(b)) * 0.5f;
            DibujarFlecha(c, e.localX, colorEjeX, $"E{e.id}_x");
            DibujarFlecha(c, e.localY, colorEjeY, $"E{e.id}_y");
            DibujarFlecha(c, e.localZ, colorEjeZ, $"E{e.id}_z");
        }
    }

    void DibujarFlecha(Vector3 origenUnity, float[] dirOpenSees,
                       Color color, string nombre)
    {
        if (dirOpenSees == null || dirOpenSees.Length < 3) return;
        // El vector viene en ejes OpenSees: hay que pasarlo por el
        // MISMO swap que las posiciones, si no las flechas apuntan mal.
        Vector3 d = Ejes.AUnity(dirOpenSees[0], dirOpenSees[1], dirOpenSees[2]);
        creados.Add(Linea(origenUnity, origenUnity + d * largoEje,
                          grosorLinea, color, nombre));
    }

    // --- Areas tributarias ---
    void DibujarTributarias(ModeloEstructural m)
    {
        if (m.areas_tributarias == null) return;
        foreach (AreaTributaria t in m.areas_tributarias)
        {
            if (!NivelVisible(t.z)) continue;
            if (t.vertices == null || t.vertices.Length < 3) continue;
            // Si el filtro esta en "todos", solo se dibuja la del
            // elemento seleccionado: 656 poligonos a la vez no se leen.
            if (soloNivel < 0 &&
                (seleccionado == null || seleccionado.id != t.elemento))
                continue;

            DibujarPoligonos(t);
        }
    }

    void DibujarPoligonos(AreaTributaria t)
    {
        // Cada poligono se cierra sobre SI MISMO. La particion viene de
        // AreaTributaria.Poligonos(), que usa los tamanos reales: antes
        // se dividia vertices.Length entre n_poligonos y, cuando una
        // viga tomaba un trapecio (4 vertices) de un pano y un triangulo
        // (3) del otro, la division entera 7/2 = 3 mezclaba vertices de
        // ambos y aparecian lineas cruzadas inexistentes.
        foreach (int[] rango in t.Poligonos())
        {
            int inicio = rango[0], cuantos = rango[1];
            for (int k = 0; k < cuantos; k++)
            {
                VerticePlanta v1 = t.vertices[inicio + k];
                VerticePlanta v2 = t.vertices[inicio + (k + 1) % cuantos];
                // El poligono esta en PLANTA (x, y de OpenSees) a la
                // cota del piso.
                Vector3 a = Ejes.AUnity(v1.x, v1.y, t.z);
                Vector3 b = Ejes.AUnity(v2.x, v2.y, t.z);
                creados.Add(Linea(a, b, grosorLinea * 0.8f, colorTributaria,
                                  $"Trib_{t.elemento}"));
            }
        }
    }

    // --- IDs ---
    void DibujarIDs(ModeloEstructural m)
    {
        Vector3 cam = (camara != null) ? camara.transform.position : Vector3.zero;

        // Solo los mas cercanos: dibujar miles de TextMesh mata el frame.
        List<KeyValuePair<float, Elemento>> cerca =
            new List<KeyValuePair<float, Elemento>>();

        foreach (Elemento e in m.elementos)
        {
            Nodo a = m.NodoPorId(e.n1);
            Nodo b = m.NodoPorId(e.n2);
            if (a == null || b == null) continue;
            if (!NivelVisible(a.z) && !NivelVisible(b.z)) continue;
            Vector3 c = (Ejes.PosicionDe(a) + Ejes.PosicionDe(b)) * 0.5f;
            cerca.Add(new KeyValuePair<float, Elemento>(
                (c - cam).sqrMagnitude, e));
        }

        cerca.Sort((p, q) => p.Key.CompareTo(q.Key));

        int cuantos = Mathf.Min(maxIDs, cerca.Count);
        for (int i = 0; i < cuantos; i++)
        {
            Elemento e = cerca[i].Value;
            Nodo a = m.NodoPorId(e.n1);
            Nodo b = m.NodoPorId(e.n2);
            Vector3 c = (Ejes.PosicionDe(a) + Ejes.PosicionDe(b)) * 0.5f;
            creados.Add(Etiqueta(c, e.id.ToString(), Color.white));
        }
    }

    GameObject Etiqueta(Vector3 pos, string texto, Color color)
    {
        GameObject go = new GameObject("ID_" + texto);
        go.transform.position = pos;
        TextMesh tm = go.AddComponent<TextMesh>();
        tm.text = texto;
        tm.characterSize = 0.16f;
        tm.fontSize = 60;
        tm.color = color;
        tm.anchor = TextAnchor.MiddleCenter;
        go.AddComponent<MirarCamara>();
        return go;
    }

    // --- Resaltado de la seleccion ---
    void Resaltar(Elemento e, ModeloEstructural m)
    {
        Nodo a = m.NodoPorId(e.n1);
        Nodo b = m.NodoPorId(e.n2);
        if (a == null || b == null) return;
        creados.Add(Linea(Ejes.PosicionDe(a), Ejes.PosicionDe(b),
                          grosorLinea * 3f, colorSeleccion, "Seleccion"));
    }

    // ============================================================
    // PRIMITIVAS
    // ============================================================
    GameObject Linea(Vector3 desde, Vector3 hasta, float grosor,
                     Color color, string nombre)
    {
        GameObject cil = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        cil.name = nombre;
        Collider col = cil.GetComponent<Collider>();
        if (col != null) Destroy(col);   // no debe estorbar al raycast

        Vector3 d = hasta - desde;
        float largo = d.magnitude;
        cil.transform.position = (desde + hasta) * 0.5f;
        cil.transform.localScale = new Vector3(grosor, largo * 0.5f, grosor);
        if (largo > 1e-6f) cil.transform.up = d.normalized;
        Pintar(cil, color);
        return cil;
    }

    private readonly Dictionary<Color, Material> cache =
        new Dictionary<Color, Material>();

    void Pintar(GameObject go, Color color)
    {
        Material mat;
        if (!cache.TryGetValue(color, out mat))
        {
            mat = new Material(VisorEstructura.ShaderCompatible());
            mat.color = color;
            if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
            cache[color] = mat;
        }
        Renderer r = go.GetComponent<Renderer>();
        if (r != null) r.sharedMaterial = mat;
    }

    // ============================================================
    // PANEL EN PANTALLA
    // ============================================================
    void OnGUI()
    {
        if (visor == null || visor.Modelo == null) return;

        GUI.color = Color.white;
        GUILayout.BeginArea(RectPanel(), GUI.skin.box);
        scroll = GUILayout.BeginScrollView(scroll);

        ModeloEstructural m = visor.Modelo;
        GUILayout.Label($"Nodos {m.nodos.Count}   Elementos {m.elementos.Count}");
        if (m.areas_tributarias != null)
            GUILayout.Label($"Areas tributarias: {m.areas_tributarias.Count}");

        GUILayout.Space(4);
        verApoyos = GUILayout.Toggle(verApoyos, "Apoyos");
        verDiafragmas = GUILayout.Toggle(verDiafragmas, "Diafragmas");
        verEjesLocales = GUILayout.Toggle(verEjesLocales, "Ejes locales");
        verAreasTributarias = GUILayout.Toggle(verAreasTributarias,
                                               "Areas tributarias");
        verIDs = GUILayout.Toggle(verIDs, "IDs");

        GUILayout.Space(4);
        GUILayout.Label($"Piso: {(soloNivel < 0 ? "todos" : soloNivel.ToString())}");
        GUILayout.BeginHorizontal();
        if (GUILayout.Button("Todos")) { soloNivel = -1; refrescar = true; }
        if (GUILayout.Button("-")) { soloNivel = Mathf.Max(-1, soloNivel - 1); refrescar = true; }
        if (GUILayout.Button("+")) { soloNivel = Mathf.Min(8, soloNivel + 1); refrescar = true; }
        GUILayout.EndHorizontal();

        // ---------- Capas del modelo ----------
        GUILayout.Space(6);
        GUILayout.Label("--- modelo ---");
        GUILayout.BeginHorizontal();
        bool nod = GUILayout.Toggle(visor.verNodos, "Nodos");
        bool col = GUILayout.Toggle(visor.verColumnas, "Columnas");
        GUILayout.EndHorizontal();
        GUILayout.BeginHorizontal();
        bool vig = GUILayout.Toggle(visor.verVigas, "Vigas");
        bool mur = GUILayout.Toggle(visor.verMuros, "Muros");
        GUILayout.EndHorizontal();

        bool perf = GUILayout.Toggle(visor.verPerfiles,
                                     "Perfiles reales (b x h)");

        if (nod != visor.verNodos || col != visor.verColumnas ||
            vig != visor.verVigas || mur != visor.verMuros ||
            perf != visor.verPerfiles)
        {
            visor.verNodos = nod; visor.verColumnas = col;
            visor.verVigas = vig; visor.verMuros = mur;
            visor.verPerfiles = perf;
            visor.Redibujar();          // el modelo lo redibuja el Visor
            refrescar = true;           // y las capas QA, este script
        }

        // ---------- Deformada ----------
        GUILayout.Space(6);
        GUILayout.Label("--- deformada (caso G) ---");
        bool def = GUILayout.Toggle(visor.mostrarDeformada, "Ver deformada");

        float escala = visor.factorEscala;
        if (def)
        {
            // Los desplazamientos reales son de milimetros sobre un
            // edificio de decenas de metros: sin amplificar no se ve
            // NADA. El factor es puramente GRAFICO, no toca el
            // analisis: la estructura no se deforma mas por subirlo.
            GUILayout.Label($"escala grafica x{escala:F0}");
            escala = GUILayout.HorizontalSlider(escala, 1f, 2000f);
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("x1")) escala = 1f;
            if (GUILayout.Button("x100")) escala = 100f;
            if (GUILayout.Button("x500")) escala = 500f;
            if (GUILayout.Button("x1000")) escala = 1000f;
            GUILayout.EndHorizontal();
            GUILayout.Label("(la escala es solo visual, no cambia el calculo)");
        }

        if (def != visor.mostrarDeformada ||
            !Mathf.Approximately(escala, visor.factorEscala))
        {
            visor.mostrarDeformada = def;
            visor.factorEscala = escala;
            visor.Redibujar();
            refrescar = true;
        }

        GUILayout.Space(6);
        if (string.IsNullOrEmpty(panel))
            GUILayout.Label("Click en una barra para inspeccionarla.");
        else
            GUILayout.Label(panel);

        GUILayout.EndScrollView();
        GUILayout.EndArea();

        // Los toggles del OnGUI cambian los campos directamente, asi que
        // hay que pedir el redibujo cuando el usuario suelta el mouse.
        if (Event.current.type == EventType.MouseUp) refrescar = true;
    }
}


/// Mantiene el texto 3D mirando a la camara; si no, los IDs se leen
/// al reves desde la mitad de los angulos.
public class MirarCamara : MonoBehaviour
{
    void LateUpdate()
    {
        if (Camera.main == null) return;
        transform.rotation = Camera.main.transform.rotation;
    }
}
