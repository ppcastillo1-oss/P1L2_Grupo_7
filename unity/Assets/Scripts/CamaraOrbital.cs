/*
================================================================
  CamaraOrbital.cs
================================================================
  Camara que orbita alrededor del modelo, con zoom y paneo.
  Sin esto la camara de Unity queda fija donde la dejaste y no se
  puede inspeccionar nada durante el Play.

  CONTROLES
    Click izquierdo + arrastrar ..... orbitar
    Click derecho / medio + arrastrar  paner
    Rueda ........................... zoom
    F ............................... encuadrar todo el modelo
    (el click izquierdo sobre un objeto lo SELECCIONA; solo orbita
     si arrastras, para que ambas cosas convivan)

  USO
    1. Selecciona la 'Main Camera' de la escena.
    2. Add Component -> CamaraOrbital.
    3. Arrastra el objeto 'Visor' al campo 'visor' (opcional: sirve
       para encuadrar automaticamente el modelo al cargar).
================================================================
*/

using UnityEngine;

[RequireComponent(typeof(Camera))]
public class CamaraOrbital : MonoBehaviour
{
    [Header("Objetivo")]
    public Vector3 centro = Vector3.zero;
    public float distancia = 14f;

    [Tooltip("Opcional: para encuadrar el modelo automaticamente al iniciar.")]
    public VisorEstructura visor;

    [Header("Sensibilidad")]
    public float velocidadOrbita = 4f;
    public float velocidadPaneo = 0.012f;
    public float velocidadZoom = 4f;

    [Header("Limites")]
    public float distanciaMin = 1.5f;
    public float distanciaMax = 300f;

    // Angulos en grados: yaw alrededor del eje vertical, pitch sobre el horizonte.
    private float yaw = 45f;
    private float pitch = 22f;

    // Un arrastre corto se interpreta como click (seleccion), no como orbita.
    private Vector3 posMouseAlPresionar;
    private bool arrastrando = false;
    public const float UMBRAL_ARRASTRE = 5f;   // pixeles

    /// Lo enciende EditorEstructura mientras arrastras un nodo, para que
    /// el mismo boton izquierdo no orbite la camara al mismo tiempo.
    public bool bloqueada = false;

    /// true si el ultimo click fue un arrastre real (y por lo tanto NO
    /// debe tratarse como seleccion). Lo consulta EditorEstructura.
    public bool HuboArrastre { get; private set; }

    void Start()
    {
        // Un frame de espera no hace falta: el Visor carga en su Start,
        // pero si todavia no hay modelo, EncuadrarTodo no hace nada y
        // la F manual siempre queda disponible.
        EncuadrarTodo();
        Aplicar();
    }

    void LateUpdate()
    {
        if (bloqueada)
        {
            Aplicar();
            return;
        }

        // --- Orbitar ---
        if (Input.GetMouseButtonDown(0))
        {
            posMouseAlPresionar = Input.mousePosition;
            arrastrando = false;
            HuboArrastre = false;
        }
        if (Input.GetMouseButton(0))
        {
            if (!arrastrando &&
                Vector3.Distance(Input.mousePosition, posMouseAlPresionar) > UMBRAL_ARRASTRE)
            {
                arrastrando = true;
                HuboArrastre = true;
            }
            if (arrastrando)
            {
                yaw += Input.GetAxis("Mouse X") * velocidadOrbita;
                pitch -= Input.GetAxis("Mouse Y") * velocidadOrbita;
                pitch = Mathf.Clamp(pitch, -85f, 85f);
            }
        }
        if (Input.GetMouseButtonUp(0)) arrastrando = false;

        // --- Paner ---
        if (Input.GetMouseButton(1) || Input.GetMouseButton(2))
        {
            float f = distancia * velocidadPaneo;
            centro -= transform.right * Input.GetAxis("Mouse X") * f;
            centro -= transform.up * Input.GetAxis("Mouse Y") * f;
        }

        // --- Zoom ---
        float rueda = Input.GetAxis("Mouse ScrollWheel");
        if (Mathf.Abs(rueda) > 0.0001f)
        {
            // Proporcional a la distancia: cerca avanza fino, lejos avanza rapido.
            distancia -= rueda * velocidadZoom * Mathf.Max(1f, distancia * 0.25f);
            distancia = Mathf.Clamp(distancia, distanciaMin, distanciaMax);
        }

        if (Input.GetKeyDown(KeyCode.F)) EncuadrarTodo();

        Aplicar();
    }

    void Aplicar()
    {
        Quaternion rot = Quaternion.Euler(pitch, yaw, 0f);
        transform.rotation = rot;
        transform.position = centro - rot * Vector3.forward * distancia;
    }

    /// Centra y aleja la camara para que quepa todo el modelo.
    public void EncuadrarTodo()
    {
        if (visor == null) visor = FindObjectOfType<VisorEstructura>();
        if (visor == null || visor.Modelo == null || visor.Modelo.nodos == null
            || visor.Modelo.nodos.Count == 0) return;

        Bounds b = new Bounds(Ejes.PosicionDe(visor.Modelo.nodos[0]), Vector3.zero);
        foreach (Nodo n in visor.Modelo.nodos) b.Encapsulate(Ejes.PosicionDe(n));

        centro = b.center;
        // Un poco de aire alrededor del modelo.
        float radio = Mathf.Max(b.extents.magnitude, 1f);
        distancia = Mathf.Clamp(radio * 2.6f, distanciaMin, distanciaMax);
    }

    /// Encuadra un punto concreto sin cambiar el zoom (para "ir al nodo N").
    public void MirarA(Vector3 punto)
    {
        centro = punto;
    }
}
