/*
================================================================
 AnalizadorEstructural.cs
================================================================
 Manda el modelo al servidor OpenSees (Python/Flask) y le entrega
 los desplazamientos al VisorEstructura para que los dibuje.

 No dibuja nada por su cuenta ni define clases de datos: usa
 ModeloEstructural.cs y delega el dibujo en VisorEstructura.cs.

 COMO USAR
  1. Ten corriendo el servidor:  python servidor_opensees.py
  2. Crea un GameObject vacio, llamalo "Analizador".
  3. Arrastra este script sobre el.
  4. En el Inspector, arrastra el objeto "Visor" al campo 'visor'.
  5. Play. Se manda el modelo y se dibuja la deformada.

 Para cambiar de caso (G, Q, EX, EY) usa MostrarCaso("EX"): NO
 vuelve a consultar al servidor, los 4 casos ya estan en memoria.

 ----------------------------------------------------------------
 NOTA: el JSON se serializa con JsonUtility.ToJson sobre el mismo
 objeto que se leyo del archivo. Antes se armaba a mano con un
 StringBuilder, y eso tenia un bug feo: float.ToString() usa la
 cultura del sistema, asi que en un Windows en espanol 0.5 salia
 como "0,5" y el JSON quedaba corrupto. JsonUtility siempre usa
 punto decimal.
 ----------------------------------------------------------------

 REQUIERE: Unity 2020+ (UnityWebRequest) y el servidor en :5000
================================================================
*/

using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

public class AnalizadorEstructural : MonoBehaviour
{
    [Header("Servidor")]
    public string urlServidor = "http://localhost:5000/analizar";
    public float timeoutSegundos = 30f;

    [Header("Referencias")]
    [Tooltip("Arrastra aca el GameObject que tiene VisorEstructura. "
           + "De ahi sale el modelo y ahi se dibuja la deformada.")]
    public VisorEstructura visor;

    [Header("Casos de carga")]
    [Tooltip("Caso a dibujar cuando llega la respuesta. Si no calza "
           + "ninguno se usa el primero.")]
    public string casoActivo = "G";

    [Tooltip("Mandar todos los casos del modelo en una sola peticion. "
           + "Si lo apagas, se manda solo 'casoActivo'.")]
    public bool mandarTodosLosCasos = true;

    [Header("Comportamiento")]
    public bool analizarAlIniciar = true;

    // --- Estado ---
    private List<CasoResultado> ultimosCasos = new List<CasoResultado>();
    private Dictionary<int, DespNodo> ultimosDesp = new Dictionary<int, DespNodo>();
    private Dictionary<int, FuerzaElemento> ultimasFuerzas = new Dictionary<int, FuerzaElemento>();
    private bool enVuelo = false;

    /// true mientras hay una peticion en curso (para no encimar dos).
    public bool Ocupado { get { return enVuelo; } }

    void Start()
    {
        if (visor == null) visor = FindObjectOfType<VisorEstructura>();
        if (visor == null)
        {
            Debug.LogError("No hay VisorEstructura en la escena. Asignalo en "
                           + "el Inspector: de ahi sale el modelo.");
            return;
        }
        if (analizarAlIniciar) EnviarModelo();
    }

    // ------------------------------------------------------------
    // ENVIO
    // ------------------------------------------------------------
    public void EnviarModelo()
    {
        if (enVuelo)
        {
            Debug.LogWarning("Ya hay un analisis en curso; se ignora.");
            return;
        }
        if (visor == null || visor.Modelo == null)
        {
            Debug.LogError("No hay modelo cargado todavia. El Visor tiene que "
                           + "leer el JSON antes de analizar.");
            return;
        }

        ModeloEstructural m = visor.Modelo;

        // Si solo queremos un caso, se manda una copia con ese caso.
        // El modelo original NO se toca.
        string json;
        if (mandarTodosLosCasos || m.casos_de_carga == null
            || m.casos_de_carga.Count <= 1)
        {
            json = JsonUtility.ToJson(m);
        }
        else
        {
            CasoDeCarga uno = m.CasoPorNombre(casoActivo);
            if (uno == null)
            {
                Debug.LogWarning($"No existe el caso '{casoActivo}'; se mandan "
                                 + "todos.");
                json = JsonUtility.ToJson(m);
            }
            else
            {
                List<CasoDeCarga> original = m.casos_de_carga;
                m.casos_de_carga = new List<CasoDeCarga> { uno };
                json = JsonUtility.ToJson(m);
                m.casos_de_carga = original;   // restaurar siempre
            }
        }

        StartCoroutine(EnviarCoroutine(json));
    }

    IEnumerator EnviarCoroutine(string json)
    {
        enVuelo = true;
        using (UnityWebRequest req = new UnityWebRequest(urlServidor, "POST"))
        {
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = Mathf.Max(1, Mathf.RoundToInt(timeoutSegundos));

            yield return req.SendWebRequest();

            if (req.result == UnityWebRequest.Result.Success)
            {
                ProcesarRespuesta(req.downloadHandler.text);
            }
            else if (req.result == UnityWebRequest.Result.ProtocolError)
            {
                // El servidor SI respondio, pero con codigo 4xx/5xx.
                // El cuerpo trae el motivo real (ej: falta "secciones").
                // Sin esto solo veriamos "HTTP/1.1 400 Bad Request".
                Debug.LogError("El servidor rechazo el modelo (HTTP "
                               + req.responseCode + "): "
                               + req.downloadHandler.text);
            }
            else
            {
                Debug.LogError("No pude conectar con el servidor: " + req.error);
                Debug.LogError("Esta corriendo 'python servidor_opensees.py'?");
            }
        }
        enVuelo = false;
    }

    // ------------------------------------------------------------
    // RESPUESTA
    // ------------------------------------------------------------
    void ProcesarRespuesta(string jsonRespuesta)
    {
        RespuestaServidor resp;
        try
        {
            resp = JsonUtility.FromJson<RespuestaServidor>(jsonRespuesta);
        }
        catch (System.Exception ex)
        {
            Debug.LogError("No pude parsear la respuesta: " + ex.Message);
            return;
        }

        if (resp == null)
        {
            Debug.LogError("La respuesta del servidor vino vacia.");
            return;
        }
        if (!resp.ok)
        {
            Debug.LogWarning("El analisis no convergio. Servidor dice: "
                             + resp.error);
            return;
        }

        if (resp.avisos != null)
            foreach (string a in resp.avisos) Debug.LogWarning("[modelo] " + a);

        // ComoCasos() normaliza las dos formas de respuesta (plana y
        // multi-caso) a una sola lista.
        ultimosCasos = resp.ComoCasos();
        if (ultimosCasos.Count == 0)
        {
            Debug.LogWarning("El servidor no devolvio desplazamientos.");
            return;
        }

        Debug.Log($"Respuesta OK: {ultimosCasos.Count} caso(s) "
                  + $"[{string.Join(", ", CasosDisponibles().ToArray())}]");

        if (!MostrarCaso(casoActivo))
            MostrarCaso(ultimosCasos[0].nombre);
    }

    // ------------------------------------------------------------
    // Cambia el caso dibujado SIN volver a consultar al servidor:
    // los resultados de todos los casos ya estan en memoria.
    // ------------------------------------------------------------
    public bool MostrarCaso(string nombre)
    {
        foreach (CasoResultado c in ultimosCasos)
        {
            if (c.nombre != nombre) continue;

            casoActivo = nombre;

            ultimosDesp.Clear();
            if (c.desplazamientos != null)
                foreach (DespNodo d in c.desplazamientos) ultimosDesp[d.id] = d;

            ultimasFuerzas.Clear();
            if (c.fuerzas_elementos != null)
                foreach (FuerzaElemento fe in c.fuerzas_elementos)
                    ultimasFuerzas[fe.id] = fe;

            // El dibujo es responsabilidad del Visor.
            if (visor != null) visor.AplicarDeformada(c.desplazamientos);

            // Verificacion de equilibrio (regla 1 del CLAUDE.md).
            if (c.reacciones != null && c.reacciones.Count > 0)
            {
                float fx = 0f, fy = 0f, fz = 0f;
                foreach (ReacNodo r in c.reacciones)
                {
                    fx += r.fx; fy += r.fy; fz += r.fz;
                }
                Debug.Log($"[{nombre}] Suma de reacciones: "
                          + $"Fx={fx:F4}  Fy={fy:F4}  Fz={fz:F4} kN "
                          + "(deben igualar la carga aplicada)");
            }

            Debug.Log($"[{nombre}] Max desplazamiento = "
                      + $"{c.max_desplazamiento * 1000f:F5} mm");
            return true;
        }
        return false;
    }

    public List<string> CasosDisponibles()
    {
        List<string> n = new List<string>();
        foreach (CasoResultado c in ultimosCasos) n.Add(c.nombre);
        return n;
    }

    // ------------------------------------------------------------
    // Consultas para la UI (clickear un nodo o una barra)
    // ------------------------------------------------------------
    public DespNodo DesplazamientoDe(int idNodo)
    {
        DespNodo d;
        return ultimosDesp.TryGetValue(idNodo, out d) ? d : null;
    }

    public FuerzaElemento FuerzaDe(int idElemento)
    {
        FuerzaElemento f;
        return ultimasFuerzas.TryGetValue(idElemento, out f) ? f : null;
    }
}
