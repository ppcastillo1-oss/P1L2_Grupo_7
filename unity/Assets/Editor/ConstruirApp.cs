/*
================================================================
  ConstruirApp.cs   (Editor)
================================================================
  Compila el visor como aplicacion standalone de Windows, para que
  se pueda lanzar desde el notebook sin abrir el editor de Unity.

  Uso desde la terminal (lo hace src/lanzar_unity.py):

      Unity.exe -batchmode -quit -projectPath <ruta> \
                -executeMethod ConstruirApp.Construir

  La app queda en  build/LaboratorioEstructural.exe

  IMPORTANTE: el JSON del modelo va en StreamingAssets, que Unity
  copia TAL CUAL dentro de la build. Por eso la app lee el mismo
  archivo que genero Python y no una copia embebida: si se
  regenera el modelo, basta con volver a copiarlo y la app ya lo
  muestra, sin recompilar.
================================================================
*/

using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

public static class ConstruirApp
{
    const string ESCENA = "Assets/Scenes/SampleScene.unity";
    const string NOMBRE = "LaboratorioEstructural";

    // Shaders que el visor pide por nombre con Shader.Find(). Hay que
    // declararlos como "always included" o la build los ELIMINA.
    static readonly string[] SHADERS_NECESARIOS = {
        "Universal Render Pipeline/Lit",
        "Universal Render Pipeline/Unlit",
        "Sprites/Default",          // lo usa el TextMesh de los IDs
    };

    [MenuItem("Laboratorio/Construir app standalone")]
    public static void Construir()
    {
        // La escena tiene que estar armada antes de compilarla: si el
        // Visor no tiene sus componentes, la build sale vacia y el
        // error recien se ve al ejecutarla.
        ConfigurarEscena.Configurar();

        AsegurarShadersIncluidos();

        string raiz = Directory.GetParent(Application.dataPath).Parent.FullName;
        string carpeta = Path.Combine(raiz, "build");
        Directory.CreateDirectory(carpeta);

        var opciones = new BuildPlayerOptions
        {
            scenes = new[] { ESCENA },
            locationPathName = Path.Combine(carpeta, NOMBRE + ".exe"),
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.None,
        };

        BuildReport reporte = BuildPipeline.BuildPlayer(opciones);
        //  (el resultado se evalua mas abajo)
        BuildSummary r = reporte.summary;

        if (r.result == BuildResult.Succeeded)
        {
            Debug.Log($"BUILD OK -> {opciones.locationPathName} "
                      + $"({r.totalSize / 1048576} MB, {r.totalTime.TotalSeconds:F0} s)");
        }
        else
        {
            Debug.LogError($"BUILD FALLO: {r.result}, "
                           + $"{r.totalErrors} errores");
            // En batchmode hay que forzar el codigo de salida, si no
            // Unity termina con 0 y el notebook cree que salio bien.
            EditorApplication.Exit(1);
        }
    }

    /// <summary>
    /// Mete los shaders que se piden con Shader.Find() en la lista
    /// "Always Included Shaders" de Graphics Settings.
    ///
    /// POR QUE HACE FALTA
    /// Al compilar, Unity ELIMINA los shaders que no ve referenciados
    /// por ningun material de la escena. El visor no usa materiales de
    /// asset: los crea en runtime con
    ///     new Material(Shader.Find("Universal Render Pipeline/Lit"))
    /// y Shader.Find() en una build solo encuentra lo que quedo dentro.
    ///
    /// Sintoma cuando falta: en el editor se ve todo bien, pero la app
    /// compilada tira
    ///     "No encontre ningun shader utilizable. Todo se vera magenta."
    ///     ArgumentNullException: Value cannot be null
    /// y no dibuja nada. Es un error que SOLO aparece en la build.
    /// </summary>
    static void AsegurarShadersIncluidos()
    {
        var activo = AssetDatabase.LoadAllAssetsAtPath(
            "ProjectSettings/GraphicsSettings.asset");
        if (activo == null || activo.Length == 0)
        {
            Debug.LogWarning("No pude abrir GraphicsSettings.asset; "
                             + "los shaders podrian eliminarse en la build.");
            return;
        }

        var so = new SerializedObject(activo[0]);
        var lista = so.FindProperty("m_AlwaysIncludedShaders");
        if (lista == null) return;

        int agregados = 0;
        foreach (string nombre in SHADERS_NECESARIOS)
        {
            Shader sh = Shader.Find(nombre);
            if (sh == null)
            {
                Debug.LogWarning($"El shader '{nombre}' no existe en este "
                                 + "proyecto; se omite.");
                continue;
            }

            bool ya = false;
            for (int i = 0; i < lista.arraySize; i++)
            {
                if (lista.GetArrayElementAtIndex(i).objectReferenceValue == sh)
                {
                    ya = true;
                    break;
                }
            }
            if (ya) continue;

            lista.InsertArrayElementAtIndex(lista.arraySize);
            lista.GetArrayElementAtIndex(lista.arraySize - 1)
                 .objectReferenceValue = sh;
            agregados++;
            Debug.Log($"Shader incluido en la build: {nombre}");
        }

        if (agregados > 0)
        {
            so.ApplyModifiedProperties();
            AssetDatabase.SaveAssets();
        }
        Debug.Log($"Shaders always-included: {lista.arraySize} "
                  + $"({agregados} agregados ahora)");
    }
}
