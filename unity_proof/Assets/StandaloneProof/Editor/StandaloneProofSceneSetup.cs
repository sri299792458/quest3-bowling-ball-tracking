using Meta.XR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UnityEngine.EventSystems;

namespace QuestBowlingStandalone.Editor
{
    public static class StandaloneProofSceneSetup
    {
        public const string ScenePath = "Assets/StandaloneProof/Scenes/StandaloneProof.unity";

        private const string CameraRigPrefabPath = "Packages/com.meta.xr.sdk.core/Prefabs/OVRCameraRig.prefab";
        private const string HandPrefabPath = "Packages/com.meta.xr.sdk.core/Prefabs/OVRHandPrefab.prefab";
        private const string RayHelperPrefabPath = "Packages/com.meta.xr.sdk.core/Prefabs/OVRRayHelper.prefab";
        private const string CameraAccessObjectName = "PassthroughCameraAccess";
        private const string ProofRigObjectName = "StandaloneProofCaptureRig";
        private const string PassthroughObjectName = "[BuildingBlock] Passthrough";
        private const string LockLaneCanvasObjectName = "LockLaneCanvas";
        private const string LockLaneButtonObjectName = "LockLaneButton";

        [MenuItem("Tools/Standalone Proof/Create Or Update Proof Scene")]
        public static void CreateOrUpdateProofScene()
        {
            EnsureSceneFolders();

            var scene = OpenOrCreateScene();
            var cameraRig = FindOrCreateCameraRig();
            var trackingSpace = FindTrackingSpace(cameraRig.transform);
            var headAnchor = FindHeadAnchor(cameraRig.transform);
            var leftHandAnchor = FindHandAnchor(cameraRig.transform, "LeftHandAnchor");
            var rightHandAnchor = FindHandAnchor(cameraRig.transform, "RightHandAnchor");
            var eventCamera = FindEventCamera(headAnchor, cameraRig.transform);
            var cameraAccess = FindOrCreateCameraAccess();
            var proofRig = FindOrCreateProofRig();
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(proofRig);
            var passthroughLayer = FindOrCreatePassthroughLayer();
            var leftHand = FindOrCreateHand(OVRHand.Hand.HandLeft, leftHandAnchor);
            var rightHand = FindOrCreateHand(OVRHand.Hand.HandRight, rightHandAnchor);
            var leftRayHelper = FindOrCreateRayHelper("Left", leftHand != null ? leftHand.transform : null);
            var rightRayHelper = FindOrCreateRayHelper("Right", rightHand != null ? rightHand.transform : null);
            var eventSystemObject = FindOrCreateEventSystem();
            var lockLaneCanvas = FindOrCreateLockLaneCanvas(headAnchor);
            var lockLaneButton = FindOrCreateLockLaneButton(lockLaneCanvas.transform);
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(lockLaneCanvas);
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(lockLaneButton);

            var sessionContext = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestSessionContext>(proofRig);
            var frameSource = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestFrameSource>(proofRig);
            var proofCapture = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture>(proofRig);
            var floorPlaneSource = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestFloorPlaneSource>(proofRig);
            var laneLockCapture = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockCapture>(proofRig);
            var liveMetadataSender = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLiveMetadataSender>(proofRig);
            var liveResultReceiver = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLiveResultReceiver>(proofRig);
            var laptopDiscovery = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLaptopDiscovery>(proofRig);
            var laneLockResultRenderer = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockResultRenderer>(proofRig);
            var shotReplayRenderer = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayRenderer>(proofRig);
            var rayInteractor = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestRayInteractor>(proofRig);
            var foulLineRaySelector = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestFoulLineRaySelector>(proofRig);
            var coordinator = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestProofRenderCoordinator>(proofRig);
            var sessionController = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestSessionController>(proofRig);
            var eventSystem = GetOrAddComponent<EventSystem>(eventSystemObject);
            var inputModule = GetOrAddComponent<OVRInputModule>(eventSystemObject);

            ConfigureCameraAccess(cameraAccess);
            ConfigureCameraRig(cameraRig);
            ConfigurePassthroughLayer(passthroughLayer);
            ConfigureEventSystem(eventSystemObject, eventSystem, inputModule, headAnchor);
            ConfigureSessionContext(sessionContext);
            ConfigureFrameSource(frameSource, cameraAccess);
            ConfigureProofCapture(proofCapture, sessionContext, cameraAccess, headAnchor);
            ConfigureFloorPlaneSource(floorPlaneSource, trackingSpace != null ? trackingSpace : cameraRig.transform);
            ConfigureLaneLockCapture(laneLockCapture, proofCapture, liveMetadataSender, floorPlaneSource);
            ConfigureHandRayHelper(leftHand, leftRayHelper);
            ConfigureHandRayHelper(rightHand, rightRayHelper);
            ConfigureRayInteractor(rayInteractor, rightRayHelper != null ? rightRayHelper.transform : headAnchor);
            ConfigureFoulLineRaySelector(foulLineRaySelector, rayInteractor, laneLockCapture, proofCapture, floorPlaneSource);
            ConfigureLockLaneCanvas(lockLaneCanvas, eventCamera);
            ConfigureLockLaneButton(lockLaneButton, laneLockCapture, foulLineRaySelector);
            ConfigureLiveMetadataSender(liveMetadataSender);
            ConfigureLiveResultReceiver(liveResultReceiver);
            ConfigureLaptopDiscovery(laptopDiscovery);
            ConfigureLaneLockResultRenderer(laneLockResultRenderer, liveResultReceiver);
            ConfigureShotReplayRenderer(shotReplayRenderer, liveResultReceiver);
            ConfigureCoordinator(coordinator, frameSource, proofCapture);
            ConfigureSessionController(sessionController, proofCapture, liveMetadataSender, liveResultReceiver, laptopDiscovery);

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

        private static GameObject FindOrCreateEventSystem()
        {
            var existing = GameObject.Find("EventSystem");
            if (existing != null)
            {
                return existing;
            }

            var go = new GameObject("EventSystem");
            Undo.RegisterCreatedObjectUndo(go, "Create EventSystem");
            return go;
        }

        private static GameObject FindOrCreateLockLaneCanvas(Transform headAnchor)
        {
            var existing = GameObject.Find(LockLaneCanvasObjectName);
            if (existing != null && existing.GetComponent<RectTransform>() != null)
            {
                return existing;
            }

            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing);
            }

            var canvasObject = new GameObject(
                LockLaneCanvasObjectName,
                typeof(RectTransform),
                typeof(Canvas),
                typeof(CanvasScaler),
                typeof(OVRRaycaster));
            Undo.RegisterCreatedObjectUndo(canvasObject, "Create Lock Lane Canvas");
            if (headAnchor != null)
            {
                Undo.SetTransformParent(canvasObject.transform, headAnchor, false, "Parent Lock Lane Canvas");
            }

            canvasObject.layer = 5;
            return canvasObject;
        }

        private static GameObject FindOrCreateLockLaneButton(Transform canvasTransform)
        {
            var existing = GameObject.Find(LockLaneButtonObjectName);
            if (existing != null && existing.GetComponent<RectTransform>() != null)
            {
                return existing;
            }

            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing);
            }

            var button = new GameObject(
                LockLaneButtonObjectName,
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Image),
                typeof(Button));
            button.name = LockLaneButtonObjectName;
            Undo.RegisterCreatedObjectUndo(button, "Create Lock Lane Button");
            if (canvasTransform != null)
            {
                Undo.SetTransformParent(button.transform, canvasTransform, false, "Parent Lock Lane Button");
            }

            button.layer = 5;
            return button;
        }

        private static OVRRayHelper FindOrCreateRayHelper(string handLabel, Transform parent)
        {
            var helperName = $"Standalone{handLabel}RayHelper";
            var existing = GameObject.Find(helperName);
            if (existing != null)
            {
                return existing.GetComponent<OVRRayHelper>();
            }

            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(RayHelperPrefabPath);
            if (prefab == null)
            {
                throw new System.InvalidOperationException($"Could not load ray helper prefab at {RayHelperPrefabPath}");
            }

            var helperObject = PrefabUtility.InstantiatePrefab(prefab) as GameObject;
            if (helperObject == null)
            {
                throw new System.InvalidOperationException("Failed to instantiate OVRRayHelper prefab.");
            }

            helperObject.name = helperName;
            Undo.RegisterCreatedObjectUndo(helperObject, $"Create {helperName}");
            if (parent != null)
            {
                Undo.SetTransformParent(helperObject.transform, parent, false, $"Parent {helperName}");
            }

            helperObject.transform.localPosition = Vector3.zero;
            helperObject.transform.localRotation = Quaternion.identity;
            helperObject.transform.localScale = Vector3.one;
            return helperObject.GetComponent<OVRRayHelper>();
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

        private static Transform FindTrackingSpace(Transform root)
        {
            if (root == null)
            {
                return null;
            }

            var direct = root.Find("TrackingSpace");
            if (direct != null)
            {
                return direct;
            }

            return FindRecursive(root, "TrackingSpace");
        }

        private static Camera FindEventCamera(Transform headAnchor, Transform root)
        {
            if (headAnchor != null)
            {
                var directCamera = headAnchor.GetComponent<Camera>();
                if (directCamera != null)
                {
                    return directCamera;
                }

                var nestedCamera = headAnchor.GetComponentInChildren<Camera>(true);
                if (nestedCamera != null)
                {
                    return nestedCamera;
                }
            }

            return root != null ? root.GetComponentInChildren<Camera>(true) : null;
        }

        private static Transform FindHandAnchor(Transform root, string anchorName)
        {
            if (root == null)
            {
                return null;
            }

            var trackingSpace = root.Find("TrackingSpace");
            if (trackingSpace != null)
            {
                var anchor = trackingSpace.Find(anchorName);
                if (anchor != null)
                {
                    return anchor;
                }
            }

            return FindRecursive(root, anchorName);
        }

        private static Transform FindRecursive(Transform root, string targetName)
        {
            if (root == null)
            {
                return null;
            }

            if (root.name == targetName)
            {
                return root;
            }

            for (var index = 0; index < root.childCount; index++)
            {
                var result = FindRecursive(root.GetChild(index), targetName);
                if (result != null)
                {
                    return result;
                }
            }

            return null;
        }

        private static OVRHand FindOrCreateHand(OVRHand.Hand handType, Transform parentAnchor)
        {
            if (parentAnchor == null)
            {
                return null;
            }

            var handName = handType == OVRHand.Hand.HandLeft ? "StandaloneProofLeftHand" : "StandaloneProofRightHand";
            var existingHands = parentAnchor.GetComponentsInChildren<OVRHand>(true);
            foreach (var existingHand in existingHands)
            {
                if (existingHand != null && existingHand.gameObject.name == handName)
                {
                    ConfigureHandComponents(existingHand, handType);
                    return existingHand;
                }
            }

            foreach (var existingHand in existingHands)
            {
                if (existingHand == null)
                {
                    continue;
                }

                existingHand.gameObject.name = handName;
                ConfigureHandComponents(existingHand, handType);
                return existingHand;
            }

            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(HandPrefabPath);
            if (prefab == null)
            {
                throw new System.InvalidOperationException($"Could not load hand prefab at {HandPrefabPath}");
            }

            var handObject = PrefabUtility.InstantiatePrefab(prefab) as GameObject;
            if (handObject == null)
            {
                throw new System.InvalidOperationException("Failed to instantiate OVRHandPrefab.");
            }

            handObject.name = handName;
            Undo.RegisterCreatedObjectUndo(handObject, $"Create {handObject.name}");
            Undo.SetTransformParent(handObject.transform, parentAnchor, false, "Parent hand to camera rig.");

            var ovrHand = handObject.GetComponent<OVRHand>();
            if (ovrHand == null)
            {
                throw new System.InvalidOperationException("Instantiated hand prefab is missing OVRHand.");
            }

            ConfigureHandComponents(ovrHand, handType);
            return ovrHand;
        }

        private static void ConfigureHandComponents(OVRHand hand, OVRHand.Hand handType)
        {
            if (hand == null)
            {
                return;
            }

            var skeletonVersion = OVRRuntimeSettings.Instance.HandSkeletonVersion;
            var handSerializedObject = new SerializedObject(hand);
            handSerializedObject.FindProperty("HandType").intValue = (int)handType;
            handSerializedObject.ApplyModifiedPropertiesWithoutUndo();

            var skeleton = hand.GetComponent<OVRSkeleton>();
            if (skeleton != null)
            {
                var skeletonSerializedObject = new SerializedObject(skeleton);
                var skeletonType = skeletonSerializedObject.FindProperty("_skeletonType");
                if (skeletonType != null)
                {
                    skeletonType.intValue = (int)handType.AsSkeletonType(skeletonVersion);
                    skeletonSerializedObject.ApplyModifiedPropertiesWithoutUndo();
                }

                EditorUtility.SetDirty(skeleton);
            }

            var mesh = hand.GetComponent<OVRMesh>();
            if (mesh != null)
            {
                var meshSerializedObject = new SerializedObject(mesh);
                var meshType = meshSerializedObject.FindProperty("_meshType");
                if (meshType != null)
                {
                    meshType.intValue = (int)handType.AsMeshType(skeletonVersion);
                    meshSerializedObject.ApplyModifiedPropertiesWithoutUndo();
                }

                EditorUtility.SetDirty(mesh);
            }

            EditorUtility.SetDirty(hand);
        }

        private static void ConfigureHandRayHelper(OVRHand hand, OVRRayHelper rayHelper)
        {
            if (hand == null || rayHelper == null)
            {
                return;
            }

            hand.RayHelper = rayHelper;
            rayHelper.DefaultLength = 2.0f;
            rayHelper.gameObject.SetActive(true);
            EditorUtility.SetDirty(hand);
            EditorUtility.SetDirty(rayHelper);
        }

        private static void ConfigureEventSystem(
            GameObject eventSystemObject,
            EventSystem eventSystem,
            OVRInputModule inputModule,
            Transform headAnchor)
        {
            if (eventSystemObject == null || eventSystem == null || inputModule == null)
            {
                return;
            }

            var inputModules = eventSystemObject.GetComponents<BaseInputModule>();
            foreach (var module in inputModules)
            {
                if (module == null || module is OVRInputModule)
                {
                    continue;
                }

                Undo.DestroyObjectImmediate(module);
            }

            inputModule.rayTransform = headAnchor;
            inputModule.allowActivationOnMobileDevice = true;
            inputModule.performSphereCastForGazepointer = false;
            EditorUtility.SetDirty(eventSystem);
            EditorUtility.SetDirty(inputModule);
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

        private static void RemoveComponentIfExists<T>(GameObject target) where T : Component
        {
            if (target == null)
            {
                return;
            }

            var existing = target.GetComponent<T>();
            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing);
            }
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

            ovrManager.trackingOriginType = OVRManager.TrackingOrigin.FloorLevel;

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

            var launchSimultaneousHandsControllers = serializedObject.FindProperty("launchSimultaneousHandsControllersOnStartup");
            if (launchSimultaneousHandsControllers != null)
            {
                launchSimultaneousHandsControllers.boolValue = true;
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

        private static void ConfigureSessionContext(QuestBowlingStandalone.QuestApp.StandaloneQuestSessionContext sessionContext)
        {
            var serializedObject = new SerializedObject(sessionContext);
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(sessionContext);
        }

        private static void ConfigureProofCapture(
            QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture proofCapture,
            QuestBowlingStandalone.QuestApp.StandaloneQuestSessionContext sessionContext,
            PassthroughCameraAccess cameraAccess,
            Transform headAnchor)
        {
            var serializedObject = new SerializedObject(proofCapture);
            serializedObject.FindProperty("sessionContext").objectReferenceValue = sessionContext;
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
            serializedObject.FindProperty("host").stringValue = string.Empty;
            serializedObject.FindProperty("port").intValue = 8767;
            serializedObject.FindProperty("connectTimeoutMs").intValue = 1000;
            serializedObject.FindProperty("enabledForAutoRun").boolValue = true;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(liveMetadataSender);
        }

        private static void ConfigureLiveResultReceiver(QuestBowlingStandalone.QuestApp.StandaloneQuestLiveResultReceiver liveResultReceiver)
        {
            var serializedObject = new SerializedObject(liveResultReceiver);
            serializedObject.FindProperty("host").stringValue = string.Empty;
            serializedObject.FindProperty("port").intValue = 8769;
            serializedObject.FindProperty("connectTimeoutMs").intValue = 1000;
            serializedObject.FindProperty("enabledForAutoRun").boolValue = true;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(liveResultReceiver);
        }

        private static void ConfigureLaptopDiscovery(QuestBowlingStandalone.QuestApp.StandaloneQuestLaptopDiscovery laptopDiscovery)
        {
            var serializedObject = new SerializedObject(laptopDiscovery);
            serializedObject.FindProperty("enabledForAutoRun").boolValue = true;
            serializedObject.FindProperty("discoveryPort").intValue = 8765;
            serializedObject.FindProperty("attemptTimeoutSeconds").floatValue = 0.5f;
            serializedObject.FindProperty("maxAttempts").intValue = 8;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(laptopDiscovery);
        }

        private static void ConfigureLaneLockResultRenderer(
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockResultRenderer laneLockResultRenderer,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveResultReceiver liveResultReceiver)
        {
            var serializedObject = new SerializedObject(laneLockResultRenderer);
            serializedObject.FindProperty("liveResultReceiver").objectReferenceValue = liveResultReceiver;
            serializedObject.FindProperty("visualizationRoot").objectReferenceValue = null;
            serializedObject.FindProperty("renderVisibleDownlaneOnly").boolValue = true;
            serializedObject.FindProperty("renderSurface").boolValue = true;
            serializedObject.FindProperty("clearOnFailedLaneResult").boolValue = true;
            serializedObject.FindProperty("verticalOffsetMeters").floatValue = 0.025f;
            serializedObject.FindProperty("lineWidthMeters").floatValue = 0.025f;
            serializedObject.FindProperty("releaseLineWidthMeters").floatValue = 0.02f;
            serializedObject.FindProperty("minimumRenderLengthMeters").floatValue = 1.0f;
            serializedObject.FindProperty("laneSurfaceColor").colorValue = new Color(0.0f, 0.9f, 0.35f, 0.18f);
            serializedObject.FindProperty("outlineColor").colorValue = new Color(0.0f, 1.0f, 0.45f, 1.0f);
            serializedObject.FindProperty("foulLineColor").colorValue = new Color(0.25f, 0.75f, 1.0f, 1.0f);
            serializedObject.FindProperty("centerLineColor").colorValue = new Color(1.0f, 1.0f, 1.0f, 0.85f);
            serializedObject.FindProperty("releaseCorridorColor").colorValue = new Color(1.0f, 0.78f, 0.12f, 1.0f);
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(laneLockResultRenderer);
        }

        private static void ConfigureShotReplayRenderer(
            QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayRenderer shotReplayRenderer,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveResultReceiver liveResultReceiver)
        {
            var serializedObject = new SerializedObject(shotReplayRenderer);
            serializedObject.FindProperty("liveResultReceiver").objectReferenceValue = liveResultReceiver;
            serializedObject.FindProperty("replayRoot").objectReferenceValue = null;
            serializedObject.FindProperty("lineWidthMeters").floatValue = 0.035f;
            serializedObject.FindProperty("markerRadiusMeters").floatValue = 0.11f;
            serializedObject.FindProperty("verticalOffsetMeters").floatValue = 0.035f;
            serializedObject.FindProperty("minReplayDurationSeconds").floatValue = 0.75f;
            serializedObject.FindProperty("maxReplayDurationSeconds").floatValue = 3.0f;
            serializedObject.FindProperty("clearOnFailedShotResult").boolValue = true;
            serializedObject.FindProperty("trajectoryColor").colorValue = new Color(0.05f, 0.9f, 1.0f, 1.0f);
            serializedObject.FindProperty("markerColor").colorValue = new Color(1.0f, 0.74f, 0.16f, 1.0f);
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(shotReplayRenderer);
        }

        private static void ConfigureFloorPlaneSource(
            QuestBowlingStandalone.QuestApp.StandaloneQuestFloorPlaneSource floorPlaneSource,
            Transform floorReference)
        {
            var serializedObject = new SerializedObject(floorPlaneSource);
            serializedObject.FindProperty("floorReference").objectReferenceValue = floorReference;
            serializedObject.FindProperty("fallbackPlanePointWorld").vector3Value = Vector3.zero;
            serializedObject.FindProperty("fallbackPlaneNormalWorld").vector3Value = Vector3.up;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(floorPlaneSource);
        }

        private static void ConfigureLaneLockCapture(
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockCapture laneLockCapture,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture proofCapture,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveMetadataSender liveMetadataSender,
            QuestBowlingStandalone.QuestApp.StandaloneQuestFloorPlaneSource floorPlaneSource)
        {
            var serializedObject = new SerializedObject(laneLockCapture);
            serializedObject.FindProperty("proofCapture").objectReferenceValue = proofCapture;
            serializedObject.FindProperty("liveMetadataSender").objectReferenceValue = liveMetadataSender;
            serializedObject.FindProperty("floorPlaneSource").objectReferenceValue = floorPlaneSource;
            serializedObject.FindProperty("laneWidthMeters").floatValue = 1.0541f;
            serializedObject.FindProperty("laneLengthMeters").floatValue = 18.288f;
            serializedObject.FindProperty("targetFrameCount").intValue = 24;
            serializedObject.FindProperty("minimumFrameCount").intValue = 12;
            serializedObject.FindProperty("maxCaptureDurationSeconds").floatValue = 1.0f;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(laneLockCapture);
        }

        private static void ConfigureRayInteractor(
            QuestBowlingStandalone.QuestApp.StandaloneQuestRayInteractor rayInteractor,
            Transform rayTransform)
        {
            var serializedObject = new SerializedObject(rayInteractor);
            serializedObject.FindProperty("rayTransform").objectReferenceValue = rayTransform;
            serializedObject.FindProperty("maxRayDistanceMeters").floatValue = 30.0f;
            serializedObject.FindProperty("selectWithHandPinch").boolValue = true;
            serializedObject.FindProperty("selectWithControllerTrigger").boolValue = true;
            serializedObject.FindProperty("debugKeyboardSelect").boolValue = true;
            serializedObject.FindProperty("debugSelectKey").intValue = (int)KeyCode.Space;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(rayInteractor);
        }

        private static void ConfigureFoulLineRaySelector(
            QuestBowlingStandalone.QuestApp.StandaloneQuestFoulLineRaySelector foulLineRaySelector,
            QuestBowlingStandalone.QuestApp.StandaloneQuestRayInteractor rayInteractor,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockCapture laneLockCapture,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture proofCapture,
            QuestBowlingStandalone.QuestApp.StandaloneQuestFloorPlaneSource floorPlaneSource)
        {
            var serializedObject = new SerializedObject(foulLineRaySelector);
            serializedObject.FindProperty("rayInteractor").objectReferenceValue = rayInteractor;
            serializedObject.FindProperty("laneLockCapture").objectReferenceValue = laneLockCapture;
            serializedObject.FindProperty("proofCapture").objectReferenceValue = proofCapture;
            serializedObject.FindProperty("floorPlaneSource").objectReferenceValue = floorPlaneSource;
            serializedObject.FindProperty("maxFloorHitDistanceMeters").floatValue = 25.0f;
            serializedObject.FindProperty("minimumCameraDepthMeters").floatValue = 0.05f;
            serializedObject.FindProperty("clearPendingPointOnDisable").boolValue = true;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(foulLineRaySelector);
        }

        private static void ConfigureLockLaneCanvas(GameObject lockLaneCanvas, Camera eventCamera)
        {
            if (lockLaneCanvas == null)
            {
                return;
            }

            var rectTransform = lockLaneCanvas.GetComponent<RectTransform>();
            var canvas = lockLaneCanvas.GetComponent<Canvas>();
            var canvasScaler = lockLaneCanvas.GetComponent<CanvasScaler>();
            var raycaster = lockLaneCanvas.GetComponent<OVRRaycaster>();

            lockLaneCanvas.layer = 5;
            rectTransform.localPosition = new Vector3(0.0f, -0.08f, 0.75f);
            rectTransform.localRotation = Quaternion.identity;
            rectTransform.localScale = Vector3.one * 0.001f;
            rectTransform.anchorMin = new Vector2(0.5f, 0.5f);
            rectTransform.anchorMax = new Vector2(0.5f, 0.5f);
            rectTransform.pivot = new Vector2(0.5f, 0.5f);
            rectTransform.sizeDelta = new Vector2(700.0f, 220.0f);

            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = eventCamera;
            canvas.pixelPerfect = false;

            canvasScaler.uiScaleMode = CanvasScaler.ScaleMode.ConstantPixelSize;
            canvasScaler.dynamicPixelsPerUnit = 10.0f;

            raycaster.blockingObjects = GraphicRaycaster.BlockingObjects.None;
            raycaster.ignoreReversedGraphics = true;

            EditorUtility.SetDirty(rectTransform);
            EditorUtility.SetDirty(canvas);
            EditorUtility.SetDirty(canvasScaler);
            EditorUtility.SetDirty(raycaster);
        }

        private static void ConfigureLockLaneButton(
            GameObject lockLaneButton,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockCapture laneLockCapture,
            QuestBowlingStandalone.QuestApp.StandaloneQuestFoulLineRaySelector foulLineRaySelector)
        {
            if (lockLaneButton == null)
            {
                return;
            }

            var rectTransform = lockLaneButton.GetComponent<RectTransform>();
            var image = lockLaneButton.GetComponent<Image>();
            var button = lockLaneButton.GetComponent<Button>();
            var laneLockButton = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockButton>(lockLaneButton);

            lockLaneButton.layer = 5;
            rectTransform.anchorMin = new Vector2(0.5f, 0.5f);
            rectTransform.anchorMax = new Vector2(0.5f, 0.5f);
            rectTransform.pivot = new Vector2(0.5f, 0.5f);
            rectTransform.anchoredPosition = Vector2.zero;
            rectTransform.localRotation = Quaternion.identity;
            rectTransform.localScale = Vector3.one;
            rectTransform.sizeDelta = new Vector2(520.0f, 120.0f);

            image.color = new Color(0.09f, 0.13f, 0.19f, 0.94f);
            image.raycastTarget = true;

            var colors = button.colors;
            colors.normalColor = new Color(0.09f, 0.13f, 0.19f, 0.94f);
            colors.highlightedColor = new Color(0.19f, 0.30f, 0.46f, 0.98f);
            colors.pressedColor = new Color(0.28f, 0.42f, 0.62f, 1.0f);
            colors.disabledColor = new Color(0.16f, 0.16f, 0.16f, 0.70f);
            colors.fadeDuration = 0.05f;
            button.transition = Selectable.Transition.ColorTint;
            button.targetGraphic = image;
            button.colors = colors;

            var labelTransform = lockLaneButton.transform.Find("Label");
            Text label;
            if (labelTransform == null)
            {
                var labelObject = new GameObject("Label");
                Undo.RegisterCreatedObjectUndo(labelObject, "Create Lock Lane Label");
                Undo.SetTransformParent(labelObject.transform, lockLaneButton.transform, false, "Parent Lock Lane Label");
                labelObject.layer = 5;
                Undo.AddComponent<RectTransform>(labelObject);
                Undo.AddComponent<CanvasRenderer>(labelObject);
                label = Undo.AddComponent<Text>(labelObject);
            }
            else
            {
                label = labelTransform.GetComponent<Text>();
                if (label == null)
                {
                    label = Undo.AddComponent<Text>(labelTransform.gameObject);
                }
            }

            if (label != null)
            {
                var labelRect = label.GetComponent<RectTransform>();
                labelRect.anchorMin = Vector2.zero;
                labelRect.anchorMax = Vector2.one;
                labelRect.offsetMin = Vector2.zero;
                labelRect.offsetMax = Vector2.zero;
                label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                label.text = "Lock Lane";
                label.alignment = TextAnchor.MiddleCenter;
                label.resizeTextForBestFit = true;
                label.resizeTextMinSize = 24;
                label.resizeTextMaxSize = 52;
                label.color = new Color(0.96f, 0.98f, 1.0f, 1.0f);
                label.raycastTarget = false;
                EditorUtility.SetDirty(label);
            }

            var serializedObject = new SerializedObject(laneLockButton);
            serializedObject.FindProperty("laneLockCapture").objectReferenceValue = laneLockCapture;
            serializedObject.FindProperty("foulLineSelector").objectReferenceValue = foulLineRaySelector;
            serializedObject.FindProperty("label").objectReferenceValue = label;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(laneLockButton);
            EditorUtility.SetDirty(image);
            EditorUtility.SetDirty(button);
            EditorUtility.SetDirty(lockLaneButton);
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

        private static void ConfigureSessionController(
            QuestBowlingStandalone.QuestApp.StandaloneQuestSessionController sessionController,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture proofCapture,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveMetadataSender liveMetadataSender,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveResultReceiver liveResultReceiver,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaptopDiscovery laptopDiscovery)
        {
            var serializedObject = new SerializedObject(sessionController);
            serializedObject.FindProperty("proofCapture").objectReferenceValue = proofCapture;
            serializedObject.FindProperty("liveMetadataSender").objectReferenceValue = liveMetadataSender;
            serializedObject.FindProperty("liveResultReceiver").objectReferenceValue = liveResultReceiver;
            serializedObject.FindProperty("laptopDiscovery").objectReferenceValue = laptopDiscovery;
            serializedObject.FindProperty("autoStartSession").boolValue = true;
            serializedObject.FindProperty("streamId").stringValue = "session-stream";
            serializedObject.FindProperty("startupDelaySeconds").floatValue = 2.0f;
            serializedObject.FindProperty("maxBeginWaitSeconds").floatValue = 20.0f;
            serializedObject.FindProperty("beginRetryIntervalSeconds").floatValue = 0.25f;
            serializedObject.FindProperty("enableLiveStreaming").boolValue = true;
            serializedObject.FindProperty("requireLaptopDiscovery").boolValue = true;
            serializedObject.FindProperty("liveStreamHost").stringValue = string.Empty;
            serializedObject.FindProperty("liveMediaPort").intValue = 8766;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(sessionController);
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
