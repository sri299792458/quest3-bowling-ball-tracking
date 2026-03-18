using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace BallTracking.Editor
{
    public static class BowlingBallProjectSetup
    {
        private const string SourceScenePath = "Assets/PassthroughCameraApiSamples/MultiObjectDetection/MultiObjectDetection.unity";
        private const string RootFolder = "Assets/BallTracking";
        private const string SceneFolder = RootFolder + "/Scenes";
        private const string TargetScenePath = SceneFolder + "/BowlingBallTracking.unity";

        [MenuItem("Tools/Ball Tracking/Create Or Update Project Assets")]
        public static void CreateOrUpdateProjectAssets()
        {
            EnsureFolder(RootFolder);
            EnsureFolder(SceneFolder);

            if (AssetDatabase.LoadAssetAtPath<SceneAsset>(TargetScenePath) == null)
            {
                if (!AssetDatabase.CopyAsset(SourceScenePath, TargetScenePath))
                {
                    throw new System.InvalidOperationException($"Failed to copy {SourceScenePath} to {TargetScenePath}.");
                }
            }

            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();

            AddSceneToBuildSettings(TargetScenePath);
            Debug.Log($"Ball tracking scene ready at {TargetScenePath}");
        }

        private static void EnsureFolder(string folderPath)
        {
            var parts = folderPath.Split('/');
            var current = parts[0];
            for (var i = 1; i < parts.Length; i++)
            {
                var next = $"{current}/{parts[i]}";
                if (!AssetDatabase.IsValidFolder(next))
                {
                    AssetDatabase.CreateFolder(current, parts[i]);
                }

                current = next;
            }
        }

        private static void AddSceneToBuildSettings(string scenePath)
        {
            var scenes = new List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
            if (scenes.All(scene => scene.path != scenePath))
            {
                scenes.Add(new EditorBuildSettingsScene(scenePath, true));
                EditorBuildSettings.scenes = scenes.ToArray();
            }
        }
    }
}
