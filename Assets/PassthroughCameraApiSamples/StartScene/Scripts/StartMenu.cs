// Copyright (c) Meta Platforms, Inc. and affiliates.
// Original Source code from Oculus Starter Samples (https://github.com/oculus-samples/Unity-StarterSamples)

using System;
using System.Collections.Generic;
using System.IO;
using Meta.XR.Samples;
using PassthroughCameraSamples.MultiObjectDetection;
using Unity.InferenceEngine;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace PassthroughCameraSamples.StartScene
{
    // Create menu of all scenes included in the build.
    [MetaCodeSample("PassthroughCameraApiSamples-StartScene")]
    public class StartMenu : MonoBehaviour
    {
        private const string LogPrefix = "[StartMenu]";

        public OVROverlay Overlay;
        public OVROverlay Text;
        public OVRCameraRig VrRig;
        [SerializeField] private ModelAsset m_objectDetectionModel;
        private OVRManager m_ovrManager;
        private OVRPassthroughLayer[] m_passthroughLayers;

        private void Awake()
        {
            CachePassthroughObjects();
            DisableLauncherPassthrough();

            try
            {
                SentisInferenceRunManager.PreloadModel(m_objectDetectionModel);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"{LogPrefix} Model preload failed, continuing without preload: {ex.Message}");
            }
        }

        private void Start()
        {
            DisableLauncherPassthrough();

            var generalScenes = new List<Tuple<int, string>>();
            var passthroughScenes = new List<Tuple<int, string>>();
            var proControllerScenes = new List<Tuple<int, string>>();

            var n = UnityEngine.SceneManagement.SceneManager.sceneCountInBuildSettings;
            for (var sceneIndex = 1; sceneIndex < n; ++sceneIndex)
            {
                var path = UnityEngine.SceneManagement.SceneUtility.GetScenePathByBuildIndex(sceneIndex);

                if (path.Contains("Passthrough"))
                {
                    passthroughScenes.Add(new Tuple<int, string>(sceneIndex, path));
                }
                else if (path.Contains("TouchPro"))
                {
                    proControllerScenes.Add(new Tuple<int, string>(sceneIndex, path));
                }
                else
                {
                    generalScenes.Add(new Tuple<int, string>(sceneIndex, path));
                }
            }

            var uiBuilder = DebugUIBuilder.Instance;
            if (passthroughScenes.Count > 0)
            {
                _ = uiBuilder.AddLabel("Passthrough Sample Scenes", DebugUIBuilder.DEBUG_PANE_LEFT);
                foreach (var scene in passthroughScenes)
                {
                    _ = uiBuilder.AddButton(Path.GetFileNameWithoutExtension(scene.Item2), () => LoadScene(scene.Item1), -1, DebugUIBuilder.DEBUG_PANE_LEFT);
                }
            }

            if (proControllerScenes.Count > 0)
            {
                _ = uiBuilder.AddLabel("Pro Controller Sample Scenes", DebugUIBuilder.DEBUG_PANE_RIGHT);
                foreach (var scene in proControllerScenes)
                {
                    _ = uiBuilder.AddButton(Path.GetFileNameWithoutExtension(scene.Item2), () => LoadScene(scene.Item1), -1, DebugUIBuilder.DEBUG_PANE_RIGHT);
                }
            }

            _ = uiBuilder.AddLabel("Press ☰ at any time to return to scene selection", DebugUIBuilder.DEBUG_PANE_CENTER);
            if (generalScenes.Count > 0)
            {
                _ = uiBuilder.AddDivider(DebugUIBuilder.DEBUG_PANE_CENTER);
                _ = uiBuilder.AddLabel("Sample Scenes", DebugUIBuilder.DEBUG_PANE_CENTER);
                foreach (var scene in generalScenes)
                {
                    _ = uiBuilder.AddButton(Path.GetFileNameWithoutExtension(scene.Item2), () => LoadScene(scene.Item1), -1, DebugUIBuilder.DEBUG_PANE_CENTER);
                }
            }

            uiBuilder.Show();
        }

        private void Update()
        {
            if (!SceneManager.GetActiveScene().name.Equals("StartScene", StringComparison.Ordinal))
            {
                return;
            }

            DisableLauncherPassthrough();
        }

        private void CachePassthroughObjects()
        {
            m_ovrManager ??= VrRig != null ? VrRig.GetComponent<OVRManager>() : FindFirstObjectByType<OVRManager>();
            m_passthroughLayers = FindObjectsByType<OVRPassthroughLayer>(FindObjectsInactive.Include, FindObjectsSortMode.None);
        }

        private void DisableLauncherPassthrough()
        {
            CachePassthroughObjects();

            if (m_ovrManager != null)
            {
                m_ovrManager.isInsightPassthroughEnabled = false;
            }

            if (m_passthroughLayers == null)
            {
                return;
            }

            foreach (var passthroughLayer in m_passthroughLayers)
            {
                if (passthroughLayer == null)
                {
                    continue;
                }

                passthroughLayer.hidden = true;
                passthroughLayer.enabled = false;
            }
        }

        private static void LoadScene(int idx)
        {
            DebugUIBuilder.Instance.Hide();
            Debug.Log("Load scene: " + idx);
            SceneManager.LoadScene(idx);
        }
    }
}
