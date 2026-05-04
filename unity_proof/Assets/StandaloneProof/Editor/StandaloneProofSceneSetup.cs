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
        private const string RetryLaneButtonObjectName = "RetryLaneButton";
        private const string ReplayShotListObjectName = "ReplayShotList";
        private const string ExperienceStatusStripObjectName = "ExperienceStatusStrip";
        private const string SessionReviewPanelObjectName = "SessionReviewPanel";
        private const string SessionReviewButtonObjectName = "SessionReviewButton";

        [MenuItem("Tools/Standalone Proof/Create Or Update Proof Scene")]
        public static void CreateOrUpdateProofScene()
        {
            EnsureSceneFolders();

            var scene = OpenOrCreateScene();
            var cameraRig = FindOrCreateCameraRig();
            var trackingSpace = FindTrackingSpace(cameraRig.transform);
            var headAnchor = FindHeadAnchor(cameraRig.transform);
            var rightHandAnchor = FindHandAnchor(cameraRig.transform, "RightHandAnchor");
            var eventCamera = FindEventCamera(headAnchor, cameraRig.transform);
            var cameraAccess = FindOrCreateCameraAccess();
            var proofRig = FindOrCreateProofRig();
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(proofRig);
            var passthroughLayer = FindOrCreatePassthroughLayer();
            DestroyObjectIfPresent("StandaloneProofLeftHand");
            DestroyObjectIfPresent("StandaloneLeftRayHelper");
            var rightHand = FindOrCreateHand(OVRHand.Hand.HandRight, rightHandAnchor);
            var rightRayHelper = FindOrCreateRayHelper("Right", rightHand != null ? rightHand.transform : null);
            var eventSystemObject = FindOrCreateEventSystem();
            var lockLaneCanvas = FindOrCreateLockLaneCanvas(headAnchor);
            DestroyObjectIfPresent("ReplayShotButton");
            var lockLaneButton = FindOrCreateLaneActionButton(LockLaneButtonObjectName, lockLaneCanvas.transform);
            var retryLaneButton = FindOrCreateLaneActionButton(RetryLaneButtonObjectName, lockLaneCanvas.transform);
            var replayShotList = FindOrCreateReplayShotList(lockLaneCanvas.transform);
            var experienceStatusStrip = FindOrCreateExperienceStatusStrip(lockLaneCanvas.transform);
            var sessionReviewPanel = FindOrCreateSessionReviewPanel(lockLaneCanvas.transform);
            var sessionReviewButton = FindOrCreateSessionReviewButton(lockLaneCanvas.transform);
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(lockLaneCanvas);
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(lockLaneButton);
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(retryLaneButton);
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(replayShotList);
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(experienceStatusStrip);
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(sessionReviewPanel);
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(sessionReviewButton);

            var sessionContext = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestSessionContext>(proofRig);
            var frameSource = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestFrameSource>(proofRig);
            var proofCapture = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture>(proofRig);
            var floorPlaneSource = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestFloorPlaneSource>(proofRig);
            var liveMetadataSender = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLiveMetadataSender>(proofRig);
            var liveResultReceiver = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLiveResultReceiver>(proofRig);
            var laptopDiscovery = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLaptopDiscovery>(proofRig);
            var laneLockResultRenderer = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockResultRenderer>(proofRig);
            var shotReplayRenderer = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayRenderer>(proofRig);
            var renderCoordinator = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestProofRenderCoordinator>(proofRig);
            var laneLockStateCoordinator = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockStateCoordinator>(proofRig);
            var sessionController = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestSessionController>(proofRig);
            var eventSystem = GetOrAddComponent<EventSystem>(eventSystemObject);
            var inputModule = GetOrAddComponent<OVRInputModule>(eventSystemObject);

            ConfigureCameraAccess(cameraAccess);
            ConfigureCameraRig(cameraRig);
            ConfigurePassthroughLayer(passthroughLayer);
            var sharedRayTransform = rightRayHelper != null ? rightRayHelper.transform : headAnchor;
            ConfigureEventSystem(eventSystemObject, eventSystem, inputModule, sharedRayTransform);
            ConfigureSessionContext(sessionContext);
            ConfigureFrameSource(frameSource, cameraAccess);
            ConfigureProofCapture(proofCapture, sessionContext, cameraAccess, headAnchor);
            ConfigureFloorPlaneSource(floorPlaneSource, trackingSpace != null ? trackingSpace : cameraRig.transform);
            ConfigureHandRayHelper(rightHand, rightRayHelper, enabled: true);
            ConfigureLaneLockStateCoordinator(laneLockStateCoordinator, floorPlaneSource, proofCapture, sessionController, liveMetadataSender, liveResultReceiver, laneLockResultRenderer, headAnchor, rightHand, proofRig.transform);
            ConfigureLockLaneCanvas(lockLaneCanvas, eventCamera);
            ConfigureLaneActionButton(
                lockLaneButton,
                laneLockStateCoordinator,
                QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockActionKind.Primary,
                new Vector2(-210.0f, 64.0f),
                new Vector2(260.0f, 92.0f),
                "Place Lane",
                new Color(0.055f, 0.18f, 0.23f, 0.94f));
            ConfigureLaneActionButton(
                retryLaneButton,
                laneLockStateCoordinator,
                QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockActionKind.Secondary,
                new Vector2(42.0f, 64.0f),
                new Vector2(150.0f, 92.0f),
                "Retry",
                new Color(0.12f, 0.095f, 0.075f, 0.92f));
            ConfigureReplayShotList(
                replayShotList,
                liveResultReceiver,
                shotReplayRenderer,
                sessionController,
                laneLockStateCoordinator);
            ConfigureSessionReviewPanel(
                sessionReviewPanel,
                sessionReviewButton,
                replayShotList.GetComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayList>(),
                shotReplayRenderer);
            ConfigureExperienceStatusStrip(
                experienceStatusStrip,
                sessionController,
                laneLockStateCoordinator,
                liveMetadataSender,
                liveResultReceiver,
                replayShotList.GetComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayList>(),
                shotReplayRenderer,
                sessionReviewPanel.GetComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestSessionReviewPanel>());
            ConfigureLiveMetadataSender(liveMetadataSender);
            ConfigureLiveResultReceiver(liveResultReceiver);
            ConfigureLaptopDiscovery(laptopDiscovery);
            ConfigureLaneLockResultRenderer(laneLockResultRenderer);
            ConfigureShotReplayRenderer(shotReplayRenderer, liveResultReceiver, laneLockStateCoordinator);
            ConfigureCoordinator(renderCoordinator, frameSource, proofCapture);
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

        private static void DestroyObjectIfPresent(string objectName)
        {
            var existing = GameObject.Find(objectName);
            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing);
            }
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

        private static GameObject FindOrCreateLaneActionButton(string objectName, Transform canvasTransform)
        {
            var existing = GameObject.Find(objectName);
            if (existing != null && existing.GetComponent<RectTransform>() != null)
            {
                return existing;
            }

            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing);
            }

            var button = new GameObject(
                objectName,
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Image),
                typeof(Button),
                typeof(CanvasGroup));
            button.name = objectName;
            Undo.RegisterCreatedObjectUndo(button, $"Create {objectName}");
            if (canvasTransform != null)
            {
                Undo.SetTransformParent(button.transform, canvasTransform, false, $"Parent {objectName}");
            }

            button.layer = 5;
            return button;
        }

        private static GameObject FindOrCreateReplayShotList(Transform canvasTransform)
        {
            var existing = GameObject.Find(ReplayShotListObjectName);
            if (existing != null && existing.GetComponent<RectTransform>() != null)
            {
                return existing;
            }

            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing);
            }

            var button = new GameObject(
                ReplayShotListObjectName,
                typeof(RectTransform));
            button.name = ReplayShotListObjectName;
            Undo.RegisterCreatedObjectUndo(button, "Create Replay Shot List");
            if (canvasTransform != null)
            {
                Undo.SetTransformParent(button.transform, canvasTransform, false, "Parent Replay Shot List");
            }

            button.layer = 5;
            return button;
        }

        private static GameObject FindOrCreateExperienceStatusStrip(Transform canvasTransform)
        {
            var existing = GameObject.Find(ExperienceStatusStripObjectName);
            if (existing != null && existing.GetComponent<RectTransform>() != null)
            {
                return existing;
            }

            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing);
            }

            var strip = new GameObject(
                ExperienceStatusStripObjectName,
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Image));
            strip.name = ExperienceStatusStripObjectName;
            Undo.RegisterCreatedObjectUndo(strip, "Create Experience Status Strip");
            if (canvasTransform != null)
            {
                Undo.SetTransformParent(strip.transform, canvasTransform, false, "Parent Experience Status Strip");
            }

            strip.layer = 5;
            return strip;
        }

        private static GameObject FindOrCreateSessionReviewPanel(Transform canvasTransform)
        {
            var existing = GameObject.Find(SessionReviewPanelObjectName);
            if (existing != null && existing.GetComponent<RectTransform>() != null)
            {
                return existing;
            }

            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing);
            }

            var panel = new GameObject(
                SessionReviewPanelObjectName,
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Image),
                typeof(CanvasGroup));
            panel.name = SessionReviewPanelObjectName;
            Undo.RegisterCreatedObjectUndo(panel, "Create Session Review Panel");
            if (canvasTransform != null)
            {
                Undo.SetTransformParent(panel.transform, canvasTransform, false, "Parent Session Review Panel");
            }

            panel.layer = 5;
            return panel;
        }

        private static GameObject FindOrCreateSessionReviewButton(Transform canvasTransform)
        {
            var existing = GameObject.Find(SessionReviewButtonObjectName);
            if (existing != null && existing.GetComponent<RectTransform>() != null)
            {
                return existing;
            }

            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing);
            }

            var button = new GameObject(
                SessionReviewButtonObjectName,
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Image),
                typeof(Button));
            button.name = SessionReviewButtonObjectName;
            Undo.RegisterCreatedObjectUndo(button, "Create Session Review Button");
            if (canvasTransform != null)
            {
                Undo.SetTransformParent(button.transform, canvasTransform, false, "Parent Session Review Button");
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

        private static void ConfigureHandRayHelper(OVRHand hand, OVRRayHelper rayHelper, bool enabled)
        {
            if (hand == null || rayHelper == null)
            {
                return;
            }

            hand.RayHelper = enabled ? rayHelper : null;
            rayHelper.DefaultLength = 2.0f;
            rayHelper.gameObject.SetActive(enabled);
            EditorUtility.SetDirty(hand);
            EditorUtility.SetDirty(rayHelper);
        }

        private static void ConfigureEventSystem(
            GameObject eventSystemObject,
            EventSystem eventSystem,
            OVRInputModule inputModule,
            Transform rayTransform)
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

            inputModule.rayTransform = rayTransform;
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
            serializedObject.FindProperty("videoPrepShader").objectReferenceValue = Shader.Find("QuestBowling/StandalonePassthroughVideoPrep");
            serializedObject.FindProperty("videoPrepGain").floatValue = 1.10f;
            serializedObject.FindProperty("videoPrepGamma").floatValue = 0.65f;
            serializedObject.FindProperty("videoPrepSaturation").floatValue = 1.0f;
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
            serializedObject.FindProperty("laneLockState").enumValueIndex = 0;
            serializedObject.FindProperty("laneLockConfidence").floatValue = 0.0f;
            serializedObject.FindProperty("laneWidthMeters").floatValue = 1.0541f;
            serializedObject.FindProperty("laneLengthMeters").floatValue = 18.288f;
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
            serializedObject.FindProperty("reconnectDelayMs").intValue = 1000;
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
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockResultRenderer laneLockResultRenderer)
        {
            var serializedObject = new SerializedObject(laneLockResultRenderer);
            serializedObject.FindProperty("visualizationRoot").objectReferenceValue = null;
            serializedObject.FindProperty("renderVisibleDownlaneOnly").boolValue = false;
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
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveResultReceiver liveResultReceiver,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockStateCoordinator laneLockStateCoordinator)
        {
            var serializedObject = new SerializedObject(shotReplayRenderer);
            serializedObject.FindProperty("liveResultReceiver").objectReferenceValue = liveResultReceiver;
            serializedObject.FindProperty("laneLockCoordinator").objectReferenceValue = laneLockStateCoordinator;
            serializedObject.FindProperty("replayRoot").objectReferenceValue = null;
            serializedObject.FindProperty("lineWidthMeters").floatValue = 0.03f;
            serializedObject.FindProperty("markerRadiusMeters").floatValue = 0.10f;
            serializedObject.FindProperty("verticalOffsetMeters").floatValue = 0.035f;
            serializedObject.FindProperty("calloutVerticalOffsetMeters").floatValue = 0.50f;
            serializedObject.FindProperty("calloutHorizontalOffsetMeters").floatValue = 0.34f;
            serializedObject.FindProperty("calloutCharacterSizeMeters").floatValue = 0.040f;
            serializedObject.FindProperty("calloutLeadSeconds").floatValue = 0.10f;
            serializedObject.FindProperty("calloutHoldSeconds").floatValue = 0.55f;
            serializedObject.FindProperty("ghostLineWidthMeters").floatValue = 0.016f;
            serializedObject.FindProperty("minReplayDurationSeconds").floatValue = 0.75f;
            serializedObject.FindProperty("maxReplayDurationSeconds").floatValue = 3.0f;
            serializedObject.FindProperty("minAverageProjectionConfidence").floatValue = 0.20f;
            serializedObject.FindProperty("minOnLanePointFraction").floatValue = 0.80f;
            serializedObject.FindProperty("clearOnFailedShotResult").boolValue = false;
            serializedObject.FindProperty("trajectoryColor").colorValue = new Color(0.02f, 0.82f, 1.0f, 1.0f);
            serializedObject.FindProperty("markerColor").colorValue = new Color(1.0f, 0.74f, 0.16f, 1.0f);
            serializedObject.FindProperty("ghostTrajectoryColor").colorValue = new Color(0.78f, 0.84f, 0.88f, 0.32f);
            serializedObject.FindProperty("calloutTextColor").colorValue = new Color(0.96f, 1.0f, 1.0f, 1.0f);
            serializedObject.FindProperty("calloutShadowColor").colorValue = new Color(0.0f, 0.0f, 0.0f, 0.92f);
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
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(floorPlaneSource);
        }

        private static void ConfigureLaneLockStateCoordinator(
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockStateCoordinator laneLockStateCoordinator,
            QuestBowlingStandalone.QuestApp.StandaloneQuestFloorPlaneSource floorPlaneSource,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLocalProofCapture proofCapture,
            QuestBowlingStandalone.QuestApp.StandaloneQuestSessionController sessionController,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveMetadataSender liveMetadataSender,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveResultReceiver liveResultReceiver,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockResultRenderer laneLockResultRenderer,
            Transform headAnchor,
            OVRHand rightHand,
            Transform visualizationRoot)
        {
            var serializedObject = new SerializedObject(laneLockStateCoordinator);
            serializedObject.FindProperty("floorPlaneSource").objectReferenceValue = floorPlaneSource;
            serializedObject.FindProperty("proofCapture").objectReferenceValue = proofCapture;
            serializedObject.FindProperty("sessionController").objectReferenceValue = sessionController;
            serializedObject.FindProperty("liveMetadataSender").objectReferenceValue = liveMetadataSender;
            serializedObject.FindProperty("liveResultReceiver").objectReferenceValue = liveResultReceiver;
            serializedObject.FindProperty("laneRenderer").objectReferenceValue = laneLockResultRenderer;
            serializedObject.FindProperty("headTransform").objectReferenceValue = headAnchor;
            serializedObject.FindProperty("handPinchSource").objectReferenceValue = rightHand;
            serializedObject.FindProperty("visualizationRoot").objectReferenceValue = visualizationRoot;
            serializedObject.FindProperty("laneWidthMeters").floatValue = 1.0541f;
            serializedObject.FindProperty("headsSectionLengthMeters").floatValue = 4.572f;
            serializedObject.FindProperty("laneLengthMeters").floatValue = 18.288f;
            serializedObject.FindProperty("placementDistanceMeters").floatValue = 0.75f;
            serializedObject.FindProperty("pinchPressThreshold").floatValue = 0.70f;
            serializedObject.FindProperty("pinchReleaseThreshold").floatValue = 0.30f;
            serializedObject.FindProperty("useStabilization").boolValue = true;
            serializedObject.FindProperty("smoothingSeconds").floatValue = 0.16f;
            serializedObject.FindProperty("positionDeadzoneMeters").floatValue = 0.012f;
            serializedObject.FindProperty("angleDeadzoneDegrees").floatValue = 0.45f;
            serializedObject.FindProperty("releaseAverageSeconds").floatValue = 0.35f;
            serializedObject.FindProperty("verticalOffsetMeters").floatValue = 0.025f;
            serializedObject.FindProperty("headsLineWidthMeters").floatValue = 0.03f;
            serializedObject.FindProperty("headsOutlineColor").colorValue = new Color(1.0f, 0.82f, 0.16f, 1.0f);
            serializedObject.FindProperty("headsSurfaceColor").colorValue = new Color(1.0f, 0.82f, 0.16f, 0.16f);
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(laneLockStateCoordinator);
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
            rectTransform.localPosition = new Vector3(0.0f, -0.16f, 0.85f);
            rectTransform.localRotation = Quaternion.identity;
            rectTransform.localScale = Vector3.one * 0.001f;
            rectTransform.anchorMin = new Vector2(0.5f, 0.5f);
            rectTransform.anchorMax = new Vector2(0.5f, 0.5f);
            rectTransform.pivot = new Vector2(0.5f, 0.5f);
            rectTransform.sizeDelta = new Vector2(1320.0f, 720.0f);

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

        private static void ConfigureLaneActionButton(
            GameObject actionButton,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockStateCoordinator laneLockStateCoordinator,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockActionKind actionKind,
            Vector2 anchoredPosition,
            Vector2 size,
            string initialText,
            Color normalColor)
        {
            if (actionButton == null)
            {
                return;
            }

            var rectTransform = actionButton.GetComponent<RectTransform>();
            var image = actionButton.GetComponent<Image>();
            var button = actionButton.GetComponent<Button>();
            var canvasGroup = GetOrAddComponent<CanvasGroup>(actionButton);
            var laneLockButton = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockButton>(actionButton);
            var startsVisible = actionKind == QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockActionKind.Primary;

            actionButton.layer = 5;
            rectTransform.anchorMin = new Vector2(0.5f, 0.5f);
            rectTransform.anchorMax = new Vector2(0.5f, 0.5f);
            rectTransform.pivot = new Vector2(0.5f, 0.5f);
            rectTransform.anchoredPosition = anchoredPosition;
            rectTransform.localRotation = Quaternion.identity;
            rectTransform.localScale = Vector3.one;
            rectTransform.sizeDelta = size;

            image.color = normalColor;
            image.raycastTarget = true;

            var colors = button.colors;
            colors.normalColor = normalColor;
            colors.highlightedColor = new Color(0.03f, 0.46f, 0.68f, 0.98f);
            colors.pressedColor = new Color(0.08f, 0.58f, 0.80f, 1.0f);
            colors.disabledColor = new Color(0.12f, 0.13f, 0.14f, 0.62f);
            colors.fadeDuration = 0.05f;
            button.transition = Selectable.Transition.ColorTint;
            button.targetGraphic = image;
            button.colors = colors;
            canvasGroup.alpha = startsVisible ? 1.0f : 0.0f;
            canvasGroup.interactable = startsVisible;
            canvasGroup.blocksRaycasts = startsVisible;

            var labelTransform = actionButton.transform.Find("Label");
            Text label;
            if (labelTransform == null)
            {
                var labelObject = new GameObject("Label");
                Undo.RegisterCreatedObjectUndo(labelObject, $"Create {actionButton.name} Label");
                Undo.SetTransformParent(labelObject.transform, actionButton.transform, false, $"Parent {actionButton.name} Label");
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
                label.text = initialText;
                label.alignment = TextAnchor.MiddleCenter;
                label.fontSize = 32;
                label.resizeTextForBestFit = true;
                label.resizeTextMinSize = 18;
                label.resizeTextMaxSize = 32;
                label.horizontalOverflow = HorizontalWrapMode.Wrap;
                label.verticalOverflow = VerticalWrapMode.Truncate;
                label.lineSpacing = 0.9f;
                label.color = new Color(0.96f, 0.98f, 1.0f, 1.0f);
                label.raycastTarget = false;
                EditorUtility.SetDirty(label);
            }

            var serializedObject = new SerializedObject(laneLockButton);
            serializedObject.FindProperty("laneLockCoordinator").objectReferenceValue = laneLockStateCoordinator;
            serializedObject.FindProperty("actionKind").enumValueIndex = (int)actionKind;
            serializedObject.FindProperty("label").objectReferenceValue = label;
            serializedObject.FindProperty("canvasGroup").objectReferenceValue = canvasGroup;
            serializedObject.FindProperty("coordinatorMissingText").stringValue = "Lane UI Missing";
            serializedObject.FindProperty("visibleAlpha").floatValue = 1.0f;
            serializedObject.FindProperty("hiddenAlpha").floatValue = 0.0f;
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(laneLockButton);
            EditorUtility.SetDirty(canvasGroup);
            EditorUtility.SetDirty(image);
            EditorUtility.SetDirty(button);
            EditorUtility.SetDirty(actionButton);
        }

        private static void ConfigureReplayShotList(
            GameObject replayShotList,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveResultReceiver liveResultReceiver,
            QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayRenderer shotReplayRenderer,
            QuestBowlingStandalone.QuestApp.StandaloneQuestSessionController sessionController,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockStateCoordinator laneLockStateCoordinator)
        {
            if (replayShotList == null)
            {
                return;
            }

            var rectTransform = replayShotList.GetComponent<RectTransform>();
            var replayList = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayList>(replayShotList);
            var panelImage = GetOrAddComponent<Image>(replayShotList);

            replayShotList.layer = 5;
            rectTransform.anchorMin = new Vector2(0.5f, 0.5f);
            rectTransform.anchorMax = new Vector2(0.5f, 0.5f);
            rectTransform.pivot = new Vector2(0.5f, 0.5f);
            rectTransform.anchoredPosition = new Vector2(270.0f, -58.0f);
            rectTransform.localRotation = Quaternion.identity;
            rectTransform.localScale = Vector3.one;
            rectTransform.sizeDelta = new Vector2(720.0f, 156.0f);

            panelImage.color = new Color(0.055f, 0.066f, 0.072f, 0.62f);
            panelImage.raycastTarget = false;

            var labelTransform = replayShotList.transform.Find("EmptyLabel");
            Text label;
            if (labelTransform == null)
            {
                var labelObject = new GameObject("EmptyLabel");
                Undo.RegisterCreatedObjectUndo(labelObject, "Create Replay List Empty Label");
                Undo.SetTransformParent(labelObject.transform, replayShotList.transform, false, "Parent Replay List Empty Label");
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
                label.text = string.Empty;
                label.alignment = TextAnchor.MiddleCenter;
                label.fontSize = 23;
                label.resizeTextForBestFit = true;
                label.resizeTextMinSize = 15;
                label.resizeTextMaxSize = 23;
                label.horizontalOverflow = HorizontalWrapMode.Wrap;
                label.verticalOverflow = VerticalWrapMode.Truncate;
                label.lineSpacing = 0.84f;
                label.color = new Color(0.94f, 1.0f, 1.0f, 1.0f);
                label.raycastTarget = false;
                EditorUtility.SetDirty(label);
            }

            var summaryTransform = replayShotList.transform.Find("SessionSummary");
            Text summaryLabel;
            if (summaryTransform == null)
            {
                var summaryObject = new GameObject("SessionSummary");
                Undo.RegisterCreatedObjectUndo(summaryObject, "Create Replay List Session Summary");
                Undo.SetTransformParent(summaryObject.transform, replayShotList.transform, false, "Parent Replay List Session Summary");
                summaryObject.layer = 5;
                Undo.AddComponent<RectTransform>(summaryObject);
                Undo.AddComponent<CanvasRenderer>(summaryObject);
                summaryLabel = Undo.AddComponent<Text>(summaryObject);
            }
            else
            {
                summaryLabel = summaryTransform.GetComponent<Text>();
                if (summaryLabel == null)
                {
                    summaryLabel = Undo.AddComponent<Text>(summaryTransform.gameObject);
                }
            }

            if (summaryLabel != null)
            {
                var summaryRect = summaryLabel.GetComponent<RectTransform>();
                summaryRect.anchorMin = new Vector2(0.04f, 0.02f);
                summaryRect.anchorMax = new Vector2(0.96f, 0.34f);
                summaryRect.offsetMin = Vector2.zero;
                summaryRect.offsetMax = Vector2.zero;
                summaryLabel.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                summaryLabel.text = string.Empty;
                summaryLabel.alignment = TextAnchor.MiddleCenter;
                summaryLabel.fontSize = 16;
                summaryLabel.resizeTextForBestFit = true;
                summaryLabel.resizeTextMinSize = 13;
                summaryLabel.resizeTextMaxSize = 16;
                summaryLabel.horizontalOverflow = HorizontalWrapMode.Wrap;
                summaryLabel.verticalOverflow = VerticalWrapMode.Truncate;
                summaryLabel.lineSpacing = 0.84f;
                summaryLabel.color = new Color(0.70f, 0.78f, 0.82f, 1.0f);
                summaryLabel.raycastTarget = false;
                EditorUtility.SetDirty(summaryLabel);
            }

            var serializedObject = new SerializedObject(replayList);
            serializedObject.FindProperty("liveResultReceiver").objectReferenceValue = liveResultReceiver;
            serializedObject.FindProperty("shotReplayRenderer").objectReferenceValue = shotReplayRenderer;
            serializedObject.FindProperty("sessionController").objectReferenceValue = sessionController;
            serializedObject.FindProperty("laneLockCoordinator").objectReferenceValue = laneLockStateCoordinator;
            serializedObject.FindProperty("listRoot").objectReferenceValue = rectTransform;
            serializedObject.FindProperty("panelBackground").objectReferenceValue = panelImage;
            serializedObject.FindProperty("emptyLabel").objectReferenceValue = label;
            serializedObject.FindProperty("sessionSummaryLabel").objectReferenceValue = summaryLabel;
            serializedObject.FindProperty("maxVisibleShots").intValue = 4;
            serializedObject.FindProperty("shotButtonSize").vector2Value = new Vector2(138.0f, 82.0f);
            serializedObject.FindProperty("shotButtonSpacing").floatValue = 8.0f;
            serializedObject.FindProperty("shotButtonRowYOffset").floatValue = 20.0f;
            serializedObject.FindProperty("normalAnchoredPosition").vector2Value = new Vector2(270.0f, -58.0f);
            serializedObject.FindProperty("reviewAnchoredPosition").vector2Value = new Vector2(270.0f, -252.0f);
            serializedObject.FindProperty("transientFailureMessageSeconds").floatValue = 2.75f;
            serializedObject.FindProperty("emptyText").stringValue = string.Empty;
            serializedObject.FindProperty("shotLabelPrefix").stringValue = "Shot ";
            serializedObject.FindProperty("panelColor").colorValue = new Color(0.055f, 0.066f, 0.072f, 0.62f);
            serializedObject.FindProperty("buttonColor").colorValue = new Color(0.075f, 0.095f, 0.11f, 0.92f);
            serializedObject.FindProperty("selectedButtonColor").colorValue = new Color(0.03f, 0.46f, 0.68f, 0.98f);
            serializedObject.FindProperty("disabledButtonColor").colorValue = new Color(0.12f, 0.13f, 0.14f, 0.62f);
            serializedObject.FindProperty("labelColor").colorValue = new Color(0.94f, 1.0f, 1.0f, 1.0f);
            serializedObject.FindProperty("mutedLabelColor").colorValue = new Color(0.70f, 0.78f, 0.82f, 1.0f);
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(replayList);
            EditorUtility.SetDirty(panelImage);
            EditorUtility.SetDirty(replayShotList);
        }

        private static void ConfigureSessionReviewPanel(
            GameObject sessionReviewPanel,
            GameObject sessionReviewButton,
            QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayList replayList,
            QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayRenderer shotReplayRenderer)
        {
            if (sessionReviewPanel == null || sessionReviewButton == null)
            {
                return;
            }

            var panelRect = sessionReviewPanel.GetComponent<RectTransform>();
            var panelImage = GetOrAddComponent<Image>(sessionReviewPanel);
            var panelCanvasGroup = GetOrAddComponent<CanvasGroup>(sessionReviewPanel);
            var presenter = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestSessionReviewPanel>(sessionReviewPanel);

            sessionReviewPanel.layer = 5;
            panelRect.anchorMin = new Vector2(0.5f, 0.5f);
            panelRect.anchorMax = new Vector2(0.5f, 0.5f);
            panelRect.pivot = new Vector2(0.5f, 0.5f);
            panelRect.anchoredPosition = new Vector2(270.0f, 8.0f);
            panelRect.localRotation = Quaternion.identity;
            panelRect.localScale = Vector3.one;
            panelRect.sizeDelta = new Vector2(760.0f, 292.0f);

            panelImage.color = new Color(0.055f, 0.066f, 0.072f, 0.86f);
            panelImage.raycastTarget = false;
            panelCanvasGroup.alpha = 0.0f;
            panelCanvasGroup.interactable = false;
            panelCanvasGroup.blocksRaycasts = false;

            var buttonRect = sessionReviewButton.GetComponent<RectTransform>();
            var buttonImage = GetOrAddComponent<Image>(sessionReviewButton);
            var button = GetOrAddComponent<Button>(sessionReviewButton);
            sessionReviewButton.layer = 5;
            buttonRect.anchorMin = new Vector2(0.5f, 0.5f);
            buttonRect.anchorMax = new Vector2(0.5f, 0.5f);
            buttonRect.pivot = new Vector2(0.5f, 0.5f);
            buttonRect.anchoredPosition = new Vector2(560.0f, 116.0f);
            buttonRect.localRotation = Quaternion.identity;
            buttonRect.localScale = Vector3.one;
            buttonRect.sizeDelta = new Vector2(132.0f, 58.0f);
            buttonImage.color = new Color(0.075f, 0.095f, 0.11f, 0.92f);
            buttonImage.raycastTarget = true;
            button.targetGraphic = buttonImage;

            var label = EnsureTextChild(sessionReviewButton.transform, "Label", "Shots", 18, TextAnchor.MiddleCenter);
            var labelRect = label.GetComponent<RectTransform>();
            labelRect.anchorMin = Vector2.zero;
            labelRect.anchorMax = Vector2.one;
            labelRect.offsetMin = Vector2.zero;
            labelRect.offsetMax = Vector2.zero;

            var serializedObject = new SerializedObject(presenter);
            serializedObject.FindProperty("shotReplayList").objectReferenceValue = replayList;
            serializedObject.FindProperty("shotReplayRenderer").objectReferenceValue = shotReplayRenderer;
            serializedObject.FindProperty("panelCanvasGroup").objectReferenceValue = panelCanvasGroup;
            serializedObject.FindProperty("panelBackground").objectReferenceValue = panelImage;
            serializedObject.FindProperty("toggleButton").objectReferenceValue = button;
            serializedObject.FindProperty("toggleButtonLabel").objectReferenceValue = label;
            serializedObject.FindProperty("hiddenToggleText").stringValue = "Shots";
            serializedObject.FindProperty("visibleToggleText").stringValue = "Hide";
            serializedObject.FindProperty("panelColor").colorValue = new Color(0.055f, 0.066f, 0.072f, 0.86f);
            serializedObject.FindProperty("buttonColor").colorValue = new Color(0.075f, 0.095f, 0.11f, 0.92f);
            serializedObject.FindProperty("selectedButtonColor").colorValue = new Color(0.03f, 0.46f, 0.68f, 0.98f);
            serializedObject.FindProperty("labelColor").colorValue = new Color(0.94f, 1.0f, 1.0f, 1.0f);
            serializedObject.FindProperty("mutedLabelColor").colorValue = new Color(0.70f, 0.78f, 0.82f, 1.0f);
            serializedObject.FindProperty("verboseLogging").boolValue = true;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();

            EditorUtility.SetDirty(label);
            EditorUtility.SetDirty(button);
            EditorUtility.SetDirty(buttonImage);
            EditorUtility.SetDirty(sessionReviewButton);
            EditorUtility.SetDirty(panelCanvasGroup);
            EditorUtility.SetDirty(panelImage);
            EditorUtility.SetDirty(presenter);
            EditorUtility.SetDirty(sessionReviewPanel);
        }

        private static Text EnsureTextChild(Transform parent, string objectName, string text, int fontSize, TextAnchor alignment)
        {
            var child = parent.Find(objectName);
            Text label = null;
            if (child != null)
            {
                label = child.GetComponent<Text>();
            }

            if (label == null)
            {
                GameObject labelObject;
                if (child == null)
                {
                    labelObject = new GameObject(objectName);
                    Undo.RegisterCreatedObjectUndo(labelObject, $"Create {objectName}");
                    Undo.SetTransformParent(labelObject.transform, parent, false, $"Parent {objectName}");
                    labelObject.layer = parent.gameObject.layer;
                    Undo.AddComponent<RectTransform>(labelObject);
                    Undo.AddComponent<CanvasRenderer>(labelObject);
                }
                else
                {
                    labelObject = child.gameObject;
                }

                label = Undo.AddComponent<Text>(labelObject);
            }

            label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            label.text = text;
            label.alignment = alignment;
            label.fontSize = fontSize;
            label.resizeTextForBestFit = true;
            label.resizeTextMinSize = Mathf.Max(10, fontSize - 6);
            label.resizeTextMaxSize = fontSize;
            label.horizontalOverflow = HorizontalWrapMode.Wrap;
            label.verticalOverflow = VerticalWrapMode.Truncate;
            label.lineSpacing = 0.84f;
            label.color = new Color(0.94f, 1.0f, 1.0f, 1.0f);
            label.raycastTarget = false;
            return label;
        }

        private static void ConfigureExperienceStatusStrip(
            GameObject statusStrip,
            QuestBowlingStandalone.QuestApp.StandaloneQuestSessionController sessionController,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLaneLockStateCoordinator laneLockStateCoordinator,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveMetadataSender liveMetadataSender,
            QuestBowlingStandalone.QuestApp.StandaloneQuestLiveResultReceiver liveResultReceiver,
            QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayList replayList,
            QuestBowlingStandalone.QuestApp.StandaloneQuestShotReplayRenderer shotReplayRenderer,
            QuestBowlingStandalone.QuestApp.StandaloneQuestSessionReviewPanel sessionReviewPanel)
        {
            if (statusStrip == null)
            {
                return;
            }

            var rectTransform = statusStrip.GetComponent<RectTransform>();
            var background = GetOrAddComponent<Image>(statusStrip);
            var presenter = GetOrAddComponent<QuestBowlingStandalone.QuestApp.StandaloneQuestExperienceStatusStrip>(statusStrip);

            statusStrip.layer = 5;
            rectTransform.anchorMin = new Vector2(0.5f, 0.5f);
            rectTransform.anchorMax = new Vector2(0.5f, 0.5f);
            rectTransform.pivot = new Vector2(0.5f, 0.5f);
            rectTransform.anchoredPosition = new Vector2(-330.0f, -100.0f);
            rectTransform.localRotation = Quaternion.identity;
            rectTransform.localScale = Vector3.one;
            rectTransform.sizeDelta = new Vector2(300.0f, 86.0f);

            background.color = new Color(0.055f, 0.066f, 0.072f, 0.58f);
            background.raycastTarget = false;

            var labelTransform = statusStrip.transform.Find("StatusLabel");
            Text label;
            if (labelTransform == null)
            {
                var labelObject = new GameObject("StatusLabel");
                Undo.RegisterCreatedObjectUndo(labelObject, "Create Experience Status Label");
                Undo.SetTransformParent(labelObject.transform, statusStrip.transform, false, "Parent Experience Status Label");
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
                labelRect.offsetMin = new Vector2(18.0f, 8.0f);
                labelRect.offsetMax = new Vector2(-18.0f, -8.0f);
                label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                label.text = "NOT READY\nLaptop Connecting";
                label.alignment = TextAnchor.MiddleCenter;
                label.fontSize = 23;
                label.resizeTextForBestFit = true;
                label.resizeTextMinSize = 15;
                label.resizeTextMaxSize = 23;
                label.horizontalOverflow = HorizontalWrapMode.Wrap;
                label.verticalOverflow = VerticalWrapMode.Truncate;
                label.lineSpacing = 0.82f;
                label.color = new Color(1.0f, 0.86f, 0.50f, 1.0f);
                label.raycastTarget = false;
                EditorUtility.SetDirty(label);
            }

            var serializedObject = new SerializedObject(presenter);
            serializedObject.FindProperty("sessionController").objectReferenceValue = sessionController;
            serializedObject.FindProperty("laneLockCoordinator").objectReferenceValue = laneLockStateCoordinator;
            serializedObject.FindProperty("liveMetadataSender").objectReferenceValue = liveMetadataSender;
            serializedObject.FindProperty("liveResultReceiver").objectReferenceValue = liveResultReceiver;
            serializedObject.FindProperty("shotReplayList").objectReferenceValue = replayList;
            serializedObject.FindProperty("shotReplayRenderer").objectReferenceValue = shotReplayRenderer;
            serializedObject.FindProperty("sessionReviewPanel").objectReferenceValue = sessionReviewPanel;
            serializedObject.FindProperty("background").objectReferenceValue = background;
            serializedObject.FindProperty("label").objectReferenceValue = label;
            serializedObject.FindProperty("backgroundColor").colorValue = new Color(0.055f, 0.066f, 0.072f, 0.58f);
            serializedObject.FindProperty("readyBackgroundColor").colorValue = new Color(0.035f, 0.15f, 0.10f, 0.70f);
            serializedObject.FindProperty("blockedBackgroundColor").colorValue = new Color(0.12f, 0.095f, 0.045f, 0.70f);
            serializedObject.FindProperty("reviewBackgroundColor").colorValue = new Color(0.055f, 0.075f, 0.12f, 0.70f);
            serializedObject.FindProperty("readyColor").colorValue = new Color(0.78f, 1.0f, 0.88f, 1.0f);
            serializedObject.FindProperty("attentionColor").colorValue = new Color(1.0f, 0.86f, 0.50f, 1.0f);
            serializedObject.FindProperty("refreshIntervalSeconds").floatValue = 0.20f;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();

            EditorUtility.SetDirty(background);
            EditorUtility.SetDirty(presenter);
            EditorUtility.SetDirty(statusStrip);
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
            serializedObject.FindProperty("abortSessionOnApplicationPause").boolValue = false;
            serializedObject.FindProperty("liveStreamHost").stringValue = string.Empty;
            serializedObject.FindProperty("liveMediaPort").intValue = 8766;
            serializedObject.FindProperty("mediaWatchdogIntervalSeconds").floatValue = 0.5f;
            serializedObject.FindProperty("mediaReconnectIntervalSeconds").floatValue = 1.0f;
            serializedObject.FindProperty("mediaNoProgressTimeoutSeconds").floatValue = 2.0f;
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
