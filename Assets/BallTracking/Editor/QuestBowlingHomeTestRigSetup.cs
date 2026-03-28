using System.Collections.Generic;
using BallTracking.Runtime;
using Meta.XR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BallTracking.Editor
{
    public static class QuestBowlingHomeTestRigSetup
    {
        private const string RigName = "QuestBowlingHomeTestRig";
        private const string LaneReferenceName = "LaneReference";
        private const string BowlingScenePath = "Assets/BallTracking/Scenes/BowlingBallTracking.unity";
        private const float DefaultLaneDistanceMeters = 2.0f;
        private static readonly string[] LegacySampleObjectNames =
        {
            "ReturnToStartScene",
            "DetectionUiMenuPrefab",
            "DetectionManagerPrefab",
            "SentisInferenceManagerPrefab",
        };

        [MenuItem("Tools/Ball Tracking/Create Or Update Home Test Rig")]
        public static void CreateOrUpdateHomeTestRig()
        {
            var scene = SceneManager.GetActiveScene();
            if (!scene.IsValid() || !scene.isLoaded)
            {
                EditorUtility.DisplayDialog(
                    "Ball Tracking",
                    "Open the BowlingBallTracking scene before creating the home test rig.",
                    "OK");
                return;
            }

            var cameraAccess = Object.FindFirstObjectByType<PassthroughCameraAccess>();
            if (cameraAccess == null)
            {
                EditorUtility.DisplayDialog(
                    "Ball Tracking",
                    "Could not find a PassthroughCameraAccess component in the open scene.",
                    "OK");
                return;
            }

            var rig = FindOrCreateRoot(RigName);
            var centerEyeAnchor = GameObject.Find("CenterEyeAnchor")?.transform;
            var laneReference = FindOrCreateLaneReference(centerEyeAnchor);
            DisableLegacySampleObjects();
            EnsureBowlingSceneIsStartupScene();

            var streamClient = GetOrAddComponent<QuestBowlingStreamClient>(rig);
            var debugController = GetOrAddComponent<QuestBowlingSessionDebugController>(rig);
            var debugView = GetOrAddComponent<QuestBowlingDebugView>(rig);

            AssignStreamClient(streamClient, cameraAccess);
            AssignDebugController(debugController, streamClient, laneReference);
            AssignDebugView(debugView, streamClient, centerEyeAnchor != null ? centerEyeAnchor : rig.transform);

            Selection.activeGameObject = rig;
            EditorSceneManager.MarkSceneDirty(scene);
            EditorUtility.DisplayDialog(
                "Ball Tracking",
                "Home test rig is ready.\n\nThe old sample UI objects were disabled and BowlingBallTracking was moved to build index 0.\n\nNext in the Inspector:\n1. Select QuestBowlingHomeTestRig\n2. Set the laptop IP on QuestBowlingStreamClient\n3. Build to Quest",
                "OK");
        }

        private static GameObject FindOrCreateRoot(string objectName)
        {
            var existing = GameObject.Find(objectName);
            if (existing != null)
            {
                return existing;
            }

            var root = new GameObject(objectName);
            Undo.RegisterCreatedObjectUndo(root, "Create Quest Bowling Home Test Rig");
            return root;
        }

        private static Transform FindOrCreateLaneReference(Transform centerEyeAnchor)
        {
            var existing = GameObject.Find(LaneReferenceName);
            if (existing != null)
            {
                return existing.transform;
            }

            var laneReference = new GameObject(LaneReferenceName);
            Undo.RegisterCreatedObjectUndo(laneReference, "Create Lane Reference");

            if (centerEyeAnchor != null)
            {
                var forward = Vector3.ProjectOnPlane(centerEyeAnchor.forward, Vector3.up);
                if (forward.sqrMagnitude < 0.001f)
                {
                    forward = Vector3.forward;
                }

                laneReference.transform.position = centerEyeAnchor.position + forward.normalized * DefaultLaneDistanceMeters;
                laneReference.transform.rotation = Quaternion.LookRotation(forward.normalized, Vector3.up);
            }
            else
            {
                laneReference.transform.position = new Vector3(0f, 0f, DefaultLaneDistanceMeters);
                laneReference.transform.rotation = Quaternion.identity;
            }

            return laneReference.transform;
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

        private static void DisableLegacySampleObjects()
        {
            foreach (var objectName in LegacySampleObjectNames)
            {
                var target = GameObject.Find(objectName);
                if (target == null || !target.activeSelf)
                {
                    continue;
                }

                Undo.RecordObject(target, $"Disable {objectName}");
                target.SetActive(false);
                EditorUtility.SetDirty(target);
            }
        }

        private static void EnsureBowlingSceneIsStartupScene()
        {
            var scenes = new List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
            var existingIndex = scenes.FindIndex(scene => scene.path == BowlingScenePath);
            if (existingIndex < 0)
            {
                scenes.Insert(0, new EditorBuildSettingsScene(BowlingScenePath, true));
            }
            else
            {
                var scene = scenes[existingIndex];
                scene.enabled = true;
                scenes.RemoveAt(existingIndex);
                scenes.Insert(0, scene);
            }

            EditorBuildSettings.scenes = scenes.ToArray();
        }

        private static void AssignStreamClient(QuestBowlingStreamClient streamClient, PassthroughCameraAccess cameraAccess)
        {
            var serializedObject = new SerializedObject(streamClient);
            serializedObject.FindProperty("cameraAccess").objectReferenceValue = cameraAccess;
            serializedObject.FindProperty("serverPort").intValue = 5799;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(streamClient);
        }

        private static void AssignDebugController(
            QuestBowlingSessionDebugController debugController,
            QuestBowlingStreamClient streamClient,
            Transform laneReference)
        {
            var serializedObject = new SerializedObject(debugController);
            serializedObject.FindProperty("streamClient").objectReferenceValue = streamClient;
            serializedObject.FindProperty("laneReference").objectReferenceValue = laneReference;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(debugController);
        }

        private static void AssignDebugView(
            QuestBowlingDebugView debugView,
            QuestBowlingStreamClient streamClient,
            Transform anchor)
        {
            var serializedObject = new SerializedObject(debugView);
            serializedObject.FindProperty("streamClient").objectReferenceValue = streamClient;
            serializedObject.FindProperty("anchor").objectReferenceValue = anchor;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(debugView);
        }
    }
}
