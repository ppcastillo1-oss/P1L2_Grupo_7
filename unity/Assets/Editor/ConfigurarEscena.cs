/*
================================================================
  ConfigurarEscena.cs   (Editor)
================================================================
  Arma la escena del laboratorio: deja el Visor, las capas de QA y
  la camara orbital conectados entre si.

  Existe para que el montaje de la escena sea REPRODUCIBLE. Si la
  escena se pierde o alguien la deja a medias, se rehace con un
  comando en vez de a mano arrastrando componentes:

      Unity -> menu  Laboratorio / Configurar escena

  o desde la terminal, sin abrir el editor:

      Unity.exe -batchmode -quit -projectPath <ruta> \
                -executeMethod ConfigurarEscena.Configurar

  Es idempotente: correrlo dos veces no duplica nada.
================================================================
*/

using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class ConfigurarEscena
{
    const string RUTA_ESCENA = "Assets/Scenes/SampleScene.unity";

    [MenuItem("Laboratorio/Configurar escena")]
    public static void Configurar()
    {
        var escena = EditorSceneManager.OpenScene(RUTA_ESCENA,
                                                  OpenSceneMode.Single);

        // --- Visor ---
        GameObject goVisor = GameObject.Find("Visor");
        if (goVisor == null)
        {
            goVisor = new GameObject("Visor");
            Debug.Log("Se creo el GameObject 'Visor'.");
        }

        VisorEstructura visor = Obtener<VisorEstructura>(goVisor);
        VisorQA qa = Obtener<VisorQA>(goVisor);

        // --- Analizador + Editor (modificar el modelo en vivo) ---
        // Necesitan el servidor Flask corriendo:
        //     python src/servidor_opensees.py
        // Sin el, el visor funciona igual: solo no se puede reanalizar.
        GameObject goAnalizador = GameObject.Find("Analizador");
        if (goAnalizador == null) goAnalizador = new GameObject("Analizador");
        AnalizadorEstructural analizador = Obtener<AnalizadorEstructural>(goAnalizador);
        EditorEstructura editor = Obtener<EditorEstructura>(goAnalizador);

        // --- Camara ---
        Camera cam = Camera.main;
        if (cam == null)
        {
            GameObject goCam = new GameObject("Main Camera");
            goCam.tag = "MainCamera";
            cam = goCam.AddComponent<Camera>();
            Debug.Log("Se creo la Main Camera.");
        }

        CamaraOrbital orbital = Obtener<CamaraOrbital>(cam.gameObject);

        // --- Cableado ---
        // Se hace por codigo y no arrastrando en el Inspector para que
        // quede registrado que apunta a que.
        qa.visor = visor;
        qa.camara = cam;
        qa.orbital = orbital;
        orbital.visor = visor;

        analizador.visor = visor;
        // Al iniciar NO se consulta al servidor: la app tiene que abrir
        // igual aunque el servidor no este corriendo. El reanalisis se
        // dispara a mano desde el panel del editor.
        analizador.analizarAlIniciar = false;

        editor.visor = visor;
        editor.analizador = analizador;
        editor.camara = orbital;

        EditorUtility.SetDirty(qa);
        EditorUtility.SetDirty(orbital);
        EditorUtility.SetDirty(analizador);
        EditorUtility.SetDirty(editor);
        EditorSceneManager.MarkSceneDirty(escena);
        EditorSceneManager.SaveScene(escena);

        Debug.Log("Escena configurada: Visor + VisorQA + CamaraOrbital "
                  + "conectados y guardados.");
    }

    /// Devuelve el componente, agregandolo solo si falta. Asi la
    /// funcion se puede correr las veces que sea sin duplicar.
    static T Obtener<T>(GameObject go) where T : Component
    {
        T c = go.GetComponent<T>();
        if (c == null)
        {
            c = go.AddComponent<T>();
            Debug.Log($"Se agrego {typeof(T).Name} a '{go.name}'.");
        }
        return c;
    }
}
