using Meta.XR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace QuestBowlingStandalone.Editor
{
    public static class StandaloneProofSceneSetup
    {
        public const string ScenePath = "Assets/StandaloneProof/Scenes/StandaloneProof.unity";

        private const string CameraRigPrefabPath = "Packages/com.meta.xr.sdk.core/Prefabs/OVRCameraRig.prefab";
        private const string CameraAccessObjectName = "PassthroughCameraAccess";
        private const string ProofRigObjectName = "StandaloneProofCaptureRig";
        private const string PassthroughObjectName = "[BuildingBlock] Passthrough";

        [MenuItem("Tools/Standalone Proof/Create Or Update Proof Scene")]
        public static void CreateOrUpdateProofScene()
        {
            EnsureSceneFolders();

            var scene = OpenOrCreateScene();
            var cameraRig = FindOrCreateCameraRig();
            var headAnchor = FindHeadAnchor(cameraRig.transform);
            var cameraAccess = FindOrCreateCameraAccess();
            var proofRig = FindOrCreateProofRig();
            var passthroughLayer = FindOrCreatePassthroughLayer();

            var frameSource = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestFrameSource>(proofRig);
            var proofCapture = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture>(proofRig);
            var liveMetadataSender = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLiveMetadataSender>(proofRig);
            var coordinator = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestProofRenderCoordinator>(proofRig);
            var autoRun = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneProofAutoRun>(proofRig);

            ConfigureCameraAccess(cameraAccess);
            ConfigureCameraRig(cameraRig);
            ConfigurePassthroughLayer(passthroughLayer);
            ConfigureFrameSource(frameSource, cameraAccess);
            ConfigureProofCapture(proofCapture, cameraAccess, headAnchor);
            ConfigureLiveMetadataSender(liveMetadataSender);
            ConfigureCoordinator(coordinator, frameSource, proofCapture);
            ConfigureAutoRun(autoRun, proofCapture, liveMetadataSender);

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            ConfigureBuildConfigObjects();
            AssetDatabase.SaveAssets();
            Selection.activeGameObject = proofRig;
        }

        public static void PrepareSceneForBuild()
        {
            CreateOrUpdateProofScene();
        }

        private static void EnsureSceneFolders()
        {
            if (!AssetDatabase.IsValidFolder("Assets/StandaloneProof/Scenes"))
            {
                AssetDatabase.CreateFolder("Assets/StandaloneProof", "Scenes");
            }
        }

        private static Scene OpenOrCreateScene()
        {
            if (System.IO.File.Exists(ScenePath))
            {
                return EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            }

            return EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        }

        private static GameObject FindOrCreateCameraRig()
        {
            var existing = GameObject.Find("OVRCameraRig");
            if (existing != null)
            {
                return existing;
            }

            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(CameraRigPrefabPath);
            if (prefab == null)
            {
                throw new System.InvalidOperationException($"Could not load camera rig prefab at {CameraRigPrefabPath}");
            }

            var instance = PrefabUtility.InstantiatePrefab(prefab) as GameObject;
            if (instance == null)
            {
                throw new System.InvalidOperationException("Failed to instantiate OVRCameraRig prefab.");
            }

            instance.name = "OVRCameraRig";
            Undo.RegisterCreatedObjectUndo(instance, "Create OVRCameraRig");
            return instance;
        }

        private static PassthroughCameraAccess FindOrCreateCameraAccess()
        {
            var existing = Object.FindFirstObjectByType<PassthroughCameraAccess>(FindObjectsInactive.Include);
            if (existing != null)
            {
                return existing;
            }

            var go = new GameObject(CameraAccessObjectName);
            Undo.RegisterCreatedObjectUndo(go, "Create Passthrough Camera Access");
            return Undo.AddComponent<PassthroughCameraAccess>(go);
        }

        private static GameObject FindOrCreateProofRig()
        {
            var existing = GameObject.Find(ProofRigObjectName);
            if (existing != null)
            {
                return existing;
            }

            var go = new GameObject(ProofRigObjectName);
            Undo.RegisterCreatedObjectUndo(go, "Create Standalone Proof Rig");
            return go;
        }

        private static OVRPassthroughLayer FindOrCreatePassthroughLayer()
        {
            var existing = Object.FindFirstObjectByType<OVRPassthroughLayer>(FindObjectsInactive.Include);
            if (existing != null)
            {
                return existing;
            }

            var go = new GameObject(PassthroughObjectName);
            Undo.RegisterCreatedObjectUndo(go, "Create Passthrough Layer");
            return Undo.AddComponent<OVRPassthroughLayer>(go);
        }

        private static Transform FindHeadAnchor(Transform root)
        {
            if (root == null)
            {
                return null;
            }

            var trackingSpace = root.Find("TrackingSpace");
            if (trackingSpace != null)
            {
                var centerEye = trackingSpace.Find("CenterEyeAnchor");
                if (centerEye != null)
                {
                    return centerEye;
                }
            }

            return root.Find("CenterEyeAnchor");
        }

        private static T GetOrAddComponent<T>(GameObject target) where T : Component
        {
            var existing = target.GetComponent<T>();
            if (existing != null)
            {
                return existing;
            }

            return Undo.AddComponent<T>(target);
        }

        private static void ConfigureCameraAccess(PassthroughCameraAccess cameraAccess)
        {
            var serializedObject = new SerializedObject(cameraAccess);
            serializedObject.FindProperty("CameraPosition").enumValueIndex = (int)PassthroughCameraAccess.CameraPositionType.Left;
            serializedObject.FindProperty("RequestedResolution").vector2IntValue = new Vector2Int(1280, 960);
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(cameraAccess);
        }

        private static void ConfigureCameraRig(GameObject cameraRig)
        {
            if (cameraRig == null)
            {
                return;
            }

            var ovrManager = cameraRig.GetComponent<OVRManager>();
            if (ovrManager == null)
            {
                return;
            }

            var serializedObject = new SerializedObject(ovrManager);
            var insightPassthroughEnabled = serializedObject.FindProperty("isInsightPassthroughEnabled");
            var requestPassthroughPermission = serializedObject.FindProperty("requestPassthroughCameraAccessPermissionOnStartup");
            if (insightPassthroughEnabled != null)
            {
                insightPassthroughEnabled.boolValue = true;
            }

            if (requestPassthroughPermission != null)
            {
                requestPassthroughPermission.boolValue = true;
            }

            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(ovrManager);

            var rigCameras = cameraRig.GetComponentsInChildren<Camera>(true);
            foreach (var rigCamera in rigCameras)
            {
                if (rigCamera == null)
                {
                    continue;
                }

                rigCamera.clearFlags = CameraClearFlags.SolidColor;
                rigCamera.backgroundColor = new Color(0f, 0f, 0f, 0f);
                EditorUtility.SetDirty(rigCamera);
            }
        }

        private static void ConfigurePassthroughLayer(OVRPassthroughLayer passthroughLayer)
        {
            if (passthroughLayer == null)
            {
                return;
            }

            var serializedObject = new SerializedObject(passthroughLayer);
            var hiddenProperty = serializedObject.FindProperty("hidden");
            var overlayTypeProperty = serializedObject.FindProperty("overlayType");
            var textureOpacityProperty = serializedObject.FindProperty("textureOpacity_");

            if (hiddenProperty != null)
            {
                hiddenProperty.boolValue = false;
            }

            if (overlayTypeProperty != null)
            {
                overlayTypeProperty.enumValueIndex = 1; // Underlay
            }

            if (textureOpacityProperty != null)
            {
                textureOpacityProperty.floatValue = 1.0f;
            }

            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(passthroughLayer);
        }

        private static void ConfigureFrameSource(QuestBowlingStandalone.QuestApp.StandaloneQuestFrameSource frameSource, PassthroughCameraAccess cameraAccess)
        {
            var serializedObject = new SerializedObject(frameSource);
            serializedObject.FindProperty("cameraAccess").objectReferenceValue = cameraAccess;
            serializedObject.FindProperty("cameraPosition").enumValueIndex = (int)PassthroughCameraAccess.CameraPositionType.Left;
            serializedObject.FindProperty("targetResolution").vector2IntValue = new Vector2Int(1280, 960);
            serializedObject.FindProperty("targetFps").intValue = 30;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(frameSource);
        }

        private static void ConfigureProofCapture(
            QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture proofCapture,
            PassthroughCameraAccess cameraAccess,
            Transform headAnchor)
        {
            var serializedObject = new SerializedObject(proofCapture);
            serializedObject.FindProperty("cameraAccess").objectReferenceValue = cameraAccess;
            serializedObject.FindProperty("cameraPosition").enumValueIndex = (int)PassthroughCameraAccess.CameraPositionType.Left;
            serializedObject.FindProperty("headTransform").objectReferenceValue = headAnchor;
            serializedObject.FindProperty("requestedResolution").vector2IntValue = new Vector2Int(1280, 960);
            serializedObject.FindProperty("targetFps").intValue = 30;
            serializedObject.FindProperty("targetBitrateKbps").intValue = 3500;
            serializedObject.FindProperty("videoCodec").stringValue = "h264";
            serializedObject.FindProperty("allowSystemUtcFallback").boolValue = false;
            serializedObject.FindProperty("outputFolderName").stringValue = "standalone_local_clips";
            serializedObject.FindProperty("createEmptyVideoPlaceholder").boolValue = true;
            serializedObject.FindProperty("startEncoderOnProofClip").boolValue = true;
            serializedObject.FindProperty("iFrameIntervalSeconds").floatValue = 1.0f;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.FindProperty("laneLockState").enumValueIndex = 1;
            serializedObject.FindProperty("laneLockConfidence").floatValue = 1.0f;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(proofCapture);
        }

        private static void ConfigureLiveMetadataSender(QuestBowlingStandalone.QuestApp.StandaloneQuestLiveMetadataSender liveMetadataSender)
        {
            var serializedObject = new SerializedObject(liveMetadataSender);
            serializedObject.FindProperty("host").stringValue = "10.235.26.83";
            serializedObject.FindProperty("port").intValue = 8767;
            serializedObject.FindProperty("enabledForAutoRun").boolValue = true;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(liveMetadataSender);
        }

        private static void ConfigureCoordinator(
            QuestBowlingStandalone.QuestApp.StandaloneQuestProofRenderCoordinator coordinator,
            QuestBowlingStandalone.QuestApp.StandaloneQuestFrameSource frameSource,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture proofCapture)
        {
            var serializedObject = new SerializedObject(coordinator);
            serializedObject.FindProperty("frameSource").objectReferenceValue = frameSource;
            serializedObject.FindProperty("proofCapture").objectReferenceValue = proofCapture;
            serializedObject.FindProperty("liveMetadataSender").objectReferenceValue =
                coordinator.GetComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLiveMetadataSender>();
            serializedObject.FindProperty("appendFrameMetadata").boolValue = true;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(coordinator);
        }

        private static void ConfigureAutoRun(
            QuestBowlingStandalone.QuestApp.StandaloneProofAutoRun autoRun,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture proofCapture,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveMetadataSender liveMetadataSender)
        {
            var serializedObject = new SerializedObject(autoRun);
            serializedObject.FindProperty("proofCapture").objectReferenceValue = proofCapture;
            serializedObject.FindProperty("liveMetadataSender").objectReferenceValue = liveMetadataSender;
            serializedObject.FindProperty("startupDelaySeconds").floatValue = 2.0f;
            serializedObject.FindProperty("maxBeginWaitSeconds").floatValue = 20.0f;
            serializedObject.FindProperty("beginRetryIntervalSeconds").floatValue = 0.25f;
            serializedObject.FindProperty("captureDurationSeconds").floatValue = 6.0f;
            serializedObject.FindProperty("preRollMs").intValue = 0;
            serializedObject.FindProperty("postRollMs").intValue = 0;
            serializedObject.FindProperty("shotId").stringValue = "standalone-proof";
            serializedObject.FindProperty("enableLiveStreaming").boolValue = true;
            serializedObject.FindProperty("liveStreamHost").stringValue = "10.235.26.83";
            serializedObject.FindProperty("liveMediaPort").intValue = 8766;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(autoRun);
        }

        private static void ConfigureBuildConfigObjects()
        {
            var xrGeneralSettings = AssetDatabase.LoadAssetAtPath<Object>("Assets/XR/XRGeneralSettingsPerBuildTarget.asset");
            var openXrPackageSettings = AssetDatabase.LoadAssetAtPath<Object>("Assets/XR/Settings/OpenXR Package Settings.asset");

            if (xrGeneralSettings != null)
            {
                EditorBuildSettings.AddConfigObject("com.unity.xr.management.loader_settings", xrGeneralSettings, true);
            }

            if (openXrPackageSettings != null)
            {
                EditorBuildSettings.AddConfigObject("com.unity.xr.openxr.settings4", openXrPackageSettings, true);
            }
        }
    }
}
