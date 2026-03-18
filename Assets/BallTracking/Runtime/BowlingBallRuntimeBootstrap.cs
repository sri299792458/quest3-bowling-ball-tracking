using System;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BallTracking.Runtime
{
    internal static class BowlingBallRuntimeBootstrap
    {
        private const string BowlingSceneName = "BowlingBallTracking";
        private const string SampleSceneName = "MultiObjectDetection";

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

            if (!scene.name.Equals(BowlingSceneName, StringComparison.OrdinalIgnoreCase) &&
                !scene.name.Equals(SampleSceneName, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            if (UnityEngine.Object.FindFirstObjectByType<BowlingBallTracker>() != null)
            {
                return;
            }

            var trackerObject = new GameObject(nameof(BowlingBallTracker));
            trackerObject.AddComponent<BowlingBallTracker>();
        }
    }
}
