/*
================================================================
  EditorEstructura.cs
================================================================
  Selecciona y EDITA el modelo dentro de Unity, y le pide al
  servidor que lo vuelva a resolver.

  Sigue la regla del CLAUDE.md: aca no se calcula nada estructural.
  Se editan DATOS (nodos, barras, secciones) y el calculo vuelve a
  OpenSees por HTTP.

  ----------------------------------------------------------------
  CONTROLES
    Click sobre un nodo o barra ..... seleccionar
    Arrastrar el nodo seleccionado .. moverlo en planta (X-Y)
    Shift + arrastrar ............... moverlo en altura (Z)
    Esc ............................. deseleccionar
    Supr ............................ borrar lo seleccionado
    Enter ........................... recalcular en el servidor

  USO
    1. GameObject vacio -> "Editor" -> Add Component -> EditorEstructura
    2. Arrastra 'Visor' y 'Analizador' a sus campos.
    3. Play. El panel aparece a la izquierda.

  ----------------------------------------------------------------
  INTEGRIDAD DEL MODELO
  Borrar cosas deja referencias huerfanas, y algunas son peligrosas
  porque NO fallan: si borras una barra y dejas su carga distribuida,
  OpenSees solo emite un warning por consola y DESCARTA la carga. El
  analisis "funciona" con menos carga de la que crees, y el equilibrio
  cierra igual porque la carga descartada nunca entro.
  Por eso al borrar se limpian tambien las cargas, los diafragmas y
  los brazos rigidos que apuntaban a lo borrado. El servidor ademas
  valida esto y lo rechaza con un mensaje explicito.
================================================================
*/

using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

public class EditorEstructura : MonoBehaviour
{
    [Header("Referencias")]
    public VisorEstructura visor;
    public AnalizadorEstructural analizador;
    public CamaraOrbital camara;

    [Header("Apariencia")]
    public Color colorSeleccion = new Color(1f, 0.85f, 0.15f);
    public float anchoPanel = 310f;

    [Header("Edicion")]
    [Tooltip("Redondea las coordenadas al mover un nodo con el mouse. "
           + "0 = sin redondeo.")]
    public float pasoRejilla = 0.25f;

    // --- Seleccion ---
    private int nodoSel = -1;
    private int elemSel = -1;
    private int nodoAncla = -1;      // primer nodo al crear una barra

    // --- Resalte (material clonado solo para el objeto seleccionado) ---
    private Renderer rendResaltado;
    private Material matClon;
    private Material matOriginal;

    // --- Arrastre de nodo ---
    private bool arrastrandoNodo = false;
    private Plane planoArrastre;
    private Vector3 offsetArrastre;

    // --- Estado ---
    private bool modificado = false;
    private string mensaje = "";
    private float mensajeHasta = 0f;
    private Vector2 scrollPanel;

    // Campos de texto del panel (se editan como string para poder
    // escribir "-" o "0." sin que el parseo los borre a mitad).
    private string campoX = "", campoY = "", campoZ = "";
    private int nodoEnCampos = -1;

    void Start()
    {
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (analizador == null) analizador = FindAnyObjectByType<AnalizadorEstructural>();
        if (camara == null) camara = FindAnyObjectByType<CamaraOrbital>();
        if (visor == null)
            Debug.LogError("EditorEstructura necesita un VisorEstructura en la escena.");
    }

    // ============================================================
    // ENTRADA
    // ============================================================
    void Update()
    {
        if (visor == null || visor.Modelo == null) return;

        ManejarArrastre();
        ManejarClick();
        ManejarTeclas();
    }

    bool MouseSobrePanel()
    {
        return Input.mousePosition.x < anchoPanel;
    }

    void ManejarClick()
    {
        if (arrastrandoNodo) return;
        if (!Input.GetMouseButtonUp(0)) return;
        if (MouseSobrePanel()) return;
        // Si el usuario estaba orbitando, el click no es una seleccion.
        if (camara != null && camara.HuboArrastre) return;

        RaycastHit hit;
        if (!Physics.Raycast(Camera.main.ScreenPointToRay(Input.mousePosition), out hit))
        {
            Deseleccionar();
            return;
        }

        DatoNodo dn = hit.collider.GetComponent<DatoNodo>();
        if (dn != null) { SeleccionarNodo(dn.idNodo); return; }

        DatoElemento de = hit.collider.GetComponent<DatoElemento>();
        if (de != null) { SeleccionarElemento(de.idElemento); return; }

        Deseleccionar();
    }

    void ManejarArrastre()
    {
        // Empezar: presionar sobre el nodo YA seleccionado.
        if (Input.GetMouseButtonDown(0) && nodoSel >= 0 && !MouseSobrePanel())
        {
            RaycastHit hit;
            if (Physics.Raycast(Camera.main.ScreenPointToRay(Input.mousePosition), out hit))
            {
                DatoNodo dn = hit.collider.GetComponent<DatoNodo>();
                if (dn != null && dn.idNodo == nodoSel)
                {
                    Nodo n = visor.Modelo.NodoPorId(nodoSel);
                    if (n != null)
                    {
                        Vector3 pos = Ejes.PosicionDe(n);
                        // Shift = mover en altura: plano vertical de cara a la
                        // camara. Si no, plano horizontal a la cota del nodo.
                        planoArrastre = ShiftPresionado()
                            ? new Plane(-Camera.main.transform.forward, pos)
                            : new Plane(Vector3.up, pos);

                        float d;
                        Ray r = Camera.main.ScreenPointToRay(Input.mousePosition);
                        if (planoArrastre.Raycast(r, out d))
                        {
                            offsetArrastre = pos - r.GetPoint(d);
                            arrastrandoNodo = true;
                            if (camara != null) camara.bloqueada = true;
                        }
                    }
                }
            }
        }

        if (arrastrandoNodo && Input.GetMouseButton(0))
        {
            float d;
            Ray r = Camera.main.ScreenPointToRay(Input.mousePosition);
            if (planoArrastre.Raycast(r, out d))
            {
                Vector3 destino = r.GetPoint(d) + offsetArrastre;
                Nodo n = visor.Modelo.NodoPorId(nodoSel);
                if (n != null)
                {
                    // Unity(x, z_opensees, y_opensees) -> volver a OpenSees
                    float nx = destino.x;
                    float ny = destino.z;
                    float nz = destino.y;

                    if (ShiftPresionado()) { nx = n.x; ny = n.y; }   // solo altura
                    else { nz = n.z; }                        // solo planta

                    n.x = Rejilla(nx); n.y = Rejilla(ny); n.z = Rejilla(nz);
                    MarcarModificado();
                    SincronizarCampos(n);
                    visor.Redibujar();
                    Resaltar(visor.ObjetoDeNodo(nodoSel));
                }
            }
        }

        if (arrastrandoNodo && Input.GetMouseButtonUp(0))
        {
            arrastrandoNodo = false;
            if (camara != null) camara.bloqueada = false;
        }
    }

    bool ShiftPresionado()
    {
        return Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);
    }

    float Rejilla(float v)
    {
        if (pasoRejilla <= 0f) return v;
        return Mathf.Round(v / pasoRejilla) * pasoRejilla;
    }

    void ManejarTeclas()
    {
        if (Input.GetKeyDown(KeyCode.Escape)) Deseleccionar();
        if (Input.GetKeyDown(KeyCode.Delete)) BorrarSeleccion();
        if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter))
            Recalcular();
    }

    // ============================================================
    // SELECCION
    // ============================================================
    void SeleccionarNodo(int id)
    {
        nodoSel = id; elemSel = -1;
        Resaltar(visor.ObjetoDeNodo(id));
        Nodo n = visor.Modelo.NodoPorId(id);
        if (n != null) SincronizarCampos(n);
    }

    void SeleccionarElemento(int id)
    {
        elemSel = id; nodoSel = -1;
        Resaltar(visor.ObjetoDeElemento(id));
    }

    void Deseleccionar()
    {
        nodoSel = -1; elemSel = -1; nodoAncla = -1;
        Resaltar(null);
    }

    // El material esta cacheado y compartido entre objetos del mismo
    // color, asi que NO se le puede cambiar el color directamente:
    // se pintarian todos. Se clona solo para el objeto seleccionado.
    void Resaltar(GameObject go)
    {
        if (rendResaltado != null)
        {
            rendResaltado.sharedMaterial = matOriginal;
            rendResaltado = null;
        }
        if (matClon != null) { Destroy(matClon); matClon = null; }

        if (go == null) return;

        rendResaltado = go.GetComponent<Renderer>();
        if (rendResaltado == null) return;

        matOriginal = rendResaltado.sharedMaterial;
        matClon = new Material(matOriginal);
        matClon.color = colorSeleccion;
        rendResaltado.sharedMaterial = matClon;
    }

    void SincronizarCampos(Nodo n)
    {
        nodoEnCampos = n.id;
        campoX = n.x.ToString("0.###", CultureInfo.InvariantCulture);
        campoY = n.y.ToString("0.###", CultureInfo.InvariantCulture);
        campoZ = n.z.ToString("0.###", CultureInfo.InvariantCulture);
    }

    // ============================================================
    // EDICION DEL MODELO
    // ============================================================
    void MarcarModificado()
    {
        modificado = true;
        // La deformada dibujada ya no corresponde a esta geometria.
        if (visor != null) visor.LimpiarDeformada();
    }

    void Avisar(string txt)
    {
        mensaje = txt;
        mensajeHasta = Time.time + 4f;
        Debug.Log("[editor] " + txt);
    }

    int ProximoIdNodo()
    {
        int m = 0;
        foreach (Nodo n in visor.Modelo.nodos) if (n.id > m) m = n.id;
        return m + 1;
    }

    int ProximoIdElemento()
    {
        int m = 0;
        foreach (Elemento e in visor.Modelo.elementos) if (e.id > m) m = e.id;
        return m + 1;
    }

    void CrearNodo()
    {
        ModeloEstructural M = visor.Modelo;
        // Lo pone en el centro de la vista, a cota 0.
        Vector3 c = camara != null ? camara.centro : Vector3.zero;
        Nodo n = new Nodo {
            id = ProximoIdNodo(),
            x = Rejilla(c.x), y = Rejilla(c.z), z = 0f,
            fijo = false, restricciones = new int[6]
        };
        M.nodos.Add(n);
        M.InvalidarIndice();
        MarcarModificado();
        visor.Redibujar();
        SeleccionarNodo(n.id);
        Avisar($"Nodo {n.id} creado. Arrastralo o edita sus coordenadas.");
    }

    void CrearBarra(int n1, int n2, string seccion, string tipo)
    {
        if (n1 == n2) { Avisar("Una barra necesita dos nodos distintos."); return; }

        foreach (Elemento e in visor.Modelo.elementos)
        {
            if ((e.n1 == n1 && e.n2 == n2) || (e.n1 == n2 && e.n2 == n1))
            {
                Avisar($"Ya existe la barra {e.id} entre esos nodos.");
                return;
            }
        }

        Elemento nuevo = new Elemento {
            id = ProximoIdElemento(), n1 = n1, n2 = n2,
            seccion = seccion, tipo = tipo, vecxz = new float[0]
        };
        visor.Modelo.elementos.Add(nuevo);
        MarcarModificado();
        visor.Redibujar();
        SeleccionarElemento(nuevo.id);
        Avisar($"Barra {nuevo.id} creada ({n1} -> {n2}). Sin carga asignada.");
    }

    void BorrarSeleccion()
    {
        if (elemSel >= 0) BorrarElemento(elemSel);
        else if (nodoSel >= 0) BorrarNodo(nodoSel);
    }

    void BorrarElemento(int id)
    {
        ModeloEstructural M = visor.Modelo;
        M.elementos.RemoveAll(e => e.id == id);
        int cargas = QuitarCargasDeElemento(id);
        Deseleccionar();
        MarcarModificado();
        visor.Redibujar();
        Avisar($"Barra {id} borrada" +
               (cargas > 0 ? $" (y {cargas} carga(s) que la referenciaban)." : "."));
    }

    void BorrarNodo(int id)
    {
        ModeloEstructural M = visor.Modelo;

        // Las barras que llegaban al nodo dejarian de tener extremo.
        List<int> huerfanas = new List<int>();
        foreach (Elemento e in M.elementos)
            if (e.n1 == id || e.n2 == id) huerfanas.Add(e.id);

        int cargas = 0;
        foreach (int idEl in huerfanas)
        {
            M.elementos.RemoveAll(e => e.id == idEl);
            cargas += QuitarCargasDeElemento(idEl);
        }

        M.nodos.RemoveAll(n => n.id == id);
        M.InvalidarIndice();
        cargas += QuitarCargasDeNodo(id);
        LimpiarReferenciasANodo(id);

        Deseleccionar();
        MarcarModificado();
        visor.Redibujar();
        Avisar($"Nodo {id} borrado" +
               (huerfanas.Count > 0 ? $", con {huerfanas.Count} barra(s)" : "") +
               (cargas > 0 ? $" y {cargas} carga(s)." : "."));
    }

    int QuitarCargasDeElemento(int idEl)
    {
        int n = 0;
        if (visor.Modelo.casos_de_carga == null) return 0;
        foreach (CasoDeCarga c in visor.Modelo.casos_de_carga)
        {
            if (c.cargas_distribuidas == null) continue;
            n += c.cargas_distribuidas.RemoveAll(x => x.elemento == idEl);
        }
        return n;
    }

    int QuitarCargasDeNodo(int idNodo)
    {
        int n = 0;
        if (visor.Modelo.casos_de_carga == null) return 0;
        foreach (CasoDeCarga c in visor.Modelo.casos_de_carga)
        {
            if (c.cargas_nodales == null) continue;
            n += c.cargas_nodales.RemoveAll(x => x.nodo == idNodo);
        }
        return n;
    }

    // Diafragmas y brazos rigidos tambien apuntan a nodos por id.
    void LimpiarReferenciasANodo(int idNodo)
    {
        ModeloEstructural M = visor.Modelo;

        if (M.brazos_rigidos != null)
            M.brazos_rigidos.RemoveAll(b => b.maestro == idNodo || b.esclavo == idNodo);

        if (M.diafragmas == null) return;
        M.diafragmas.RemoveAll(d => d.nodo_maestro == idNodo);
        foreach (Diafragma d in M.diafragmas)
        {
            if (d.nodos == null) continue;
            List<int> quedan = new List<int>();
            foreach (int nid in d.nodos) if (nid != idNodo) quedan.Add(nid);
            d.nodos = quedan.ToArray();
        }
    }

    void AplicarCoordenadas()
    {
        Nodo n = visor.Modelo.NodoPorId(nodoEnCampos);
        if (n == null) return;

        float x, y, z;
        bool ok = float.TryParse(campoX, NumberStyles.Float, CultureInfo.InvariantCulture, out x)
                & float.TryParse(campoY, NumberStyles.Float, CultureInfo.InvariantCulture, out y)
                & float.TryParse(campoZ, NumberStyles.Float, CultureInfo.InvariantCulture, out z);
        if (!ok) { Avisar("Coordenadas invalidas. Usa punto decimal."); return; }

        n.x = x; n.y = y; n.z = z;
        MarcarModificado();
        visor.Redibujar();
        Resaltar(visor.ObjetoDeNodo(n.id));
    }

    void Recalcular()
    {
        if (analizador == null)
        {
            Avisar("No hay AnalizadorEstructural en la escena.");
            return;
        }
        if (analizador.Ocupado) { Avisar("Ya hay un analisis en curso."); return; }

        analizador.EnviarModelo();
        modificado = false;
        Avisar("Modelo enviado al servidor. Mira la Console.");
    }

    void GuardarJSON()
    {
        string ruta = Path.Combine(Application.persistentDataPath, "modelo_editado.json");
        File.WriteAllText(ruta, JsonUtility.ToJson(visor.Modelo, true));
        Debug.Log("Modelo guardado en: " + ruta);
        Avisar("Guardado (ruta completa en la Console).");
    }

    // ============================================================
    // PANEL
    // ============================================================
    void OnGUI()
    {
        if (visor == null || visor.Modelo == null) return;
        ModeloEstructural M = visor.Modelo;

        GUILayout.BeginArea(new Rect(10, 10, anchoPanel, Screen.height - 20),
                            GUI.skin.box);
        scrollPanel = GUILayout.BeginScrollView(scrollPanel);

        GUILayout.Label("<b>MODELO</b>" + (modificado ? "  (modificado)" : ""),
                        EstiloRico());
        GUILayout.Label($"{M.nodos.Count} nodos   {M.elementos.Count} barras   "
                        + $"{(M.secciones != null ? M.secciones.Count : 0)} secciones");

        GUILayout.Space(6);
        if (GUILayout.Button("Recalcular en el servidor  (Enter)")) Recalcular();

        GUILayout.BeginHorizontal();
        if (GUILayout.Button("Nodo nuevo")) CrearNodo();
        if (GUILayout.Button("Guardar JSON")) GuardarJSON();
        GUILayout.EndHorizontal();

        GUILayout.Space(4);
        PanelCapas();

        GUILayout.Space(8);
        GUILayout.Label("<b>SELECCION</b>", EstiloRico());

        if (nodoSel >= 0) PanelNodo(M);
        else if (elemSel >= 0) PanelElemento(M);
        else GUILayout.Label("Nada seleccionado.\nHaz click en un nodo o una barra.");

        GUILayout.Space(10);
        GUILayout.Label("<b>CONTROLES</b>", EstiloRico());
        GUILayout.Label("Click izq. arrastrar: orbitar\n"
                      + "Click der.: paner   Rueda: zoom\n"
                      + "F: encuadrar   Esc: deseleccionar\n"
                      + "Arrastrar nodo: mover en planta\n"
                      + "Shift + arrastrar: mover en altura\n"
                      + "Supr: borrar   Enter: recalcular");

        if (Time.time < mensajeHasta && mensaje.Length > 0)
        {
            GUILayout.Space(8);
            GUILayout.Label(mensaje);
        }

        GUILayout.EndScrollView();
        GUILayout.EndArea();
    }

    GUIStyle EstiloRico()
    {
        GUIStyle s = new GUIStyle(GUI.skin.label);
        s.richText = true;
        return s;
    }

    void PanelCapas()
    {
        // GUILayout.Toggle no avisa si cambio: hay que compararlo a mano.
        bool aN = visor.verNodos, aC = visor.verColumnas;
        bool aV = visor.verVigas, aM = visor.verMuros;

        bool aA = visor.verNodosAuxiliares;

        GUILayout.BeginHorizontal();
        visor.verNodos = GUILayout.Toggle(visor.verNodos, "Nodos");
        visor.verNodosAuxiliares = GUILayout.Toggle(visor.verNodosAuxiliares, "Aux.");
        visor.verColumnas = GUILayout.Toggle(visor.verColumnas, "Col.");
        visor.verVigas = GUILayout.Toggle(visor.verVigas, "Vigas");
        visor.verMuros = GUILayout.Toggle(visor.verMuros, "Muros");
        GUILayout.EndHorizontal();

        GUILayout.BeginHorizontal();
        bool def = GUILayout.Toggle(visor.mostrarDeformada, "Deformada");
        if (def != visor.mostrarDeformada)
        {
            visor.mostrarDeformada = def;
            visor.Redibujar();
        }
        GUILayout.Label("x" + visor.factorEscala.ToString("0"), GUILayout.Width(50));
        GUILayout.EndHorizontal();

        if (aN != visor.verNodos || aC != visor.verColumnas
            || aV != visor.verVigas || aM != visor.verMuros
            || aA != visor.verNodosAuxiliares)
        {
            visor.Redibujar();
            // El resalte vive en un objeto que se acaba de destruir.
            if (nodoSel >= 0) Resaltar(visor.ObjetoDeNodo(nodoSel));
            else if (elemSel >= 0) Resaltar(visor.ObjetoDeElemento(elemSel));
        }
    }

    void PanelNodo(ModeloEstructural M)
    {
        Nodo n = M.NodoPorId(nodoSel);
        if (n == null) { Deseleccionar(); return; }

        GUILayout.Label($"Nodo {n.id}");

        if (nodoEnCampos != n.id) SincronizarCampos(n);
        GUILayout.BeginHorizontal();
        GUILayout.Label("X", GUILayout.Width(14));
        campoX = GUILayout.TextField(campoX);
        GUILayout.Label("Y", GUILayout.Width(14));
        campoY = GUILayout.TextField(campoY);
        GUILayout.Label("Z", GUILayout.Width(14));
        campoZ = GUILayout.TextField(campoZ);
        GUILayout.EndHorizontal();
        if (GUILayout.Button("Aplicar coordenadas")) AplicarCoordenadas();

        bool eraFijo = n.fijo;
        n.fijo = GUILayout.Toggle(n.fijo, "Empotrado (los 6 GDL)");
        if (n.fijo != eraFijo)
        {
            n.restricciones = n.fijo ? new int[] {1,1,1,1,1,1} : new int[6];
            MarcarModificado();
            visor.Redibujar();
            Resaltar(visor.ObjetoDeNodo(n.id));
        }

        // Resultado del ultimo analisis, si lo hay.
        if (analizador != null)
        {
            DespNodo d = analizador.DesplazamientoDe(n.id);
            if (d != null)
            {
                GUILayout.Space(4);
                GUILayout.Label($"UX {d.ux*1000f:0.####} mm\n"
                              + $"UY {d.uy*1000f:0.####} mm\n"
                              + $"UZ {d.uz*1000f:0.####} mm");
            }
        }

        GUILayout.Space(4);
        if (nodoAncla < 0)
        {
            if (GUILayout.Button("Empezar barra desde aqui")) nodoAncla = n.id;
        }
        else if (nodoAncla == n.id)
        {
            GUILayout.Label("Ahora selecciona el otro nodo.");
            if (GUILayout.Button("Cancelar")) nodoAncla = -1;
        }
        else
        {
            GUILayout.Label($"Unir {nodoAncla} con {n.id}:");
            GUILayout.BeginHorizontal();
            if (M.secciones != null)
            {
                foreach (Seccion s in M.secciones)
                {
                    if (GUILayout.Button(s.nombre))
                    {
                        CrearBarra(nodoAncla, n.id, s.nombre, TipoSegunGeometria(nodoAncla, n.id));
                        nodoAncla = -1;
                    }
                }
            }
            GUILayout.EndHorizontal();
            if (GUILayout.Button("Cancelar")) nodoAncla = -1;
        }

        GUILayout.Space(4);
        if (GUILayout.Button("Borrar nodo  (Supr)")) BorrarNodo(n.id);
    }

    // Etiqueta sugerida. El servidor igual decide por la GEOMETRIA,
    // no por esta etiqueta; si no calzan, avisa en 'avisos'.
    string TipoSegunGeometria(int a, int b)
    {
        Nodo na = visor.Modelo.NodoPorId(a);
        Nodo nb = visor.Modelo.NodoPorId(b);
        if (na == null || nb == null) return "viga_x";

        float dx = Mathf.Abs(nb.x - na.x);
        float dy = Mathf.Abs(nb.y - na.y);
        float dz = Mathf.Abs(nb.z - na.z);

        if (dz > dx && dz > dy) return "columna";
        return dx >= dy ? "viga_x" : "viga_y";
    }

    void PanelElemento(ModeloEstructural M)
    {
        Elemento e = null;
        foreach (Elemento x in M.elementos) if (x.id == elemSel) { e = x; break; }
        if (e == null) { Deseleccionar(); return; }

        GUILayout.Label($"Barra {e.id}   nodos {e.n1} -> {e.n2}");
        GUILayout.Label($"tipo: {e.tipo}   seccion: {e.seccion}");

        if (M.secciones != null && M.secciones.Count > 1)
        {
            GUILayout.Label("Cambiar seccion:");
            GUILayout.BeginHorizontal();
            foreach (Seccion s in M.secciones)
            {
                if (s.nombre == e.seccion) continue;
                if (GUILayout.Button(s.nombre))
                {
                    e.seccion = s.nombre;
                    MarcarModificado();
                    Avisar($"Barra {e.id} ahora usa '{s.nombre}'.");
                }
            }
            GUILayout.EndHorizontal();
        }

        // Esfuerzos del ultimo analisis, en EJES LOCALES.
        if (analizador != null)
        {
            FuerzaElemento f = analizador.FuerzaDe(e.id);
            if (f != null && f.f != null && f.f.Length >= 12)
            {
                GUILayout.Space(4);
                GUILayout.Label("Esfuerzos (ejes locales):");
                GUILayout.Label($"N  {f.N_i:0.###} kN\n"
                              + $"Vz {f.Vz_i:0.###} kN\n"
                              + $"My {f.My_i:0.###} / {f.My_j:0.###} kN*m");
            }
        }

        GUILayout.Space(4);
        if (GUILayout.Button("Borrar barra  (Supr)")) BorrarElemento(e.id);
    }
}
