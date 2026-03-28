using System;
using Meta.XR;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BallTracking.Runtime
{
    internal static class BowlingBallRuntimeBootstrap
    {
        private const string BowlingSceneName = "BowlingBallTracking";
        private const string SampleSceneName = "MultiObjectDetection";
        private const string RigName = "QuestBowlingHomeTestRig";
        private const string LaneReferenceName = "LaneReference";
        private const float DefaultLaneDistanceMeters = 2.0f;

        private static readonly string[] LegacySampleObjectNames =
        {
            "ReturnToStartScene",
            "DetectionUiMenuPrefab",
            "DetectionManagerPrefab",
            "SentisInferenceManagerPrefab",
        };

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Register()
        {
            SceneManager.sceneLoaded -= OnSceneLoaded;
            SceneManager.sceneLoaded += OnSceneLoaded;
            TryInstall(SceneManager.GetActiveScene());
        }

        private static void OnSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            TryInstall(scene);
        }

        private static void TryInstall(Scene scene)
        {
            if (!scene.IsValid() || !scene.isLoaded)
            {
                return;
            }

            var isBowlingScene = scene.name.Equals(BowlingSceneName, StringComparison.OrdinalIgnoreCase);
            var isSampleScene = scene.name.Equals(SampleSceneName, StringComparison.OrdinalIgnoreCase);

            if (!isBowlingScene && !isSampleScene)
            {
                return;
            }

            DisableLegacySampleObjects();

            if (isBowlingScene)
            {
                EnsureQuestBowlingRig();
                return;
            }

            if (UnityEngine.Object.FindFirstObjectByType<BowlingBallTracker>() == null)
            {
                var trackerObject = new GameObject(nameof(BowlingBallTracker));
                trackerObject.AddComponent<BowlingBallTracker>();
            }
        }

        private static void DisableLegacySampleObjects()
        {
            foreach (var objectName in LegacySampleObjectNames)
            {
                var target = GameObject.Find(objectName);
                if (target != null && target.activeSelf)
                {
                    target.SetActive(false);
                }
            }
        }

        private static void EnsureQuestBowlingRig()
        {
            var cameraAccess = UnityEngine.Object.FindFirstObjectByType<PassthroughCameraAccess>(FindObjectsInactive.Include);
            if (cameraAccess == null)
            {
                return;
            }

            var rig = GameObject.Find(RigName);
            if (rig == null)
            {
                rig = new GameObject(RigName);
            }

            var laneReference = GameObject.Find(LaneReferenceName);
            if (laneReference == null)
            {
                laneReference = new GameObject(LaneReferenceName);
                var centerEye = GameObject.Find("CenterEyeAnchor")?.transform;
                if (centerEye != null)
                {
                    var forward = Vector3.ProjectOnPlane(centerEye.forward, Vector3.up);
                    if (forward.sqrMagnitude < 0.001f)
                    {
                        forward = Vector3.forward;
                    }

                    laneReference.transform.position = centerEye.position + forward.normalized * DefaultLaneDistanceMeters;
                    laneReference.transform.rotation = Quaternion.LookRotation(forward.normalized, Vector3.up);
                }
                else
                {
                    laneReference.transform.position = new Vector3(0f, 0f, DefaultLaneDistanceMeters);
                    laneReference.transform.rotation = Quaternion.identity;
                }
            }

            var streamClient = rig.GetComponent<QuestBowlingStreamClient>();
            if (streamClient == null)
            {
                streamClient = rig.AddComponent<QuestBowlingStreamClient>();
            }

            var debugController = rig.GetComponent<QuestBowlingSessionDebugController>();
            if (debugController == null)
            {
                debugController = rig.AddComponent<QuestBowlingSessionDebugController>();
            }

            var debugView = rig.GetComponent<QuestBowlingDebugView>();
            if (debugView == null)
            {
                debugView = rig.AddComponent<QuestBowlingDebugView>();
            }

            var anchor = GameObject.Find("CenterEyeAnchor")?.transform;
            if (anchor == null && Camera.main != null)
            {
                anchor = Camera.main.transform;
            }

            streamClient.ConfigureForRuntime(cameraAccess);
            debugController.ConfigureForRuntime(streamClient, laneReference.transform);
            debugView.ConfigureForRuntime(streamClient, anchor != null ? anchor : rig.transform);
        }
    }
}
