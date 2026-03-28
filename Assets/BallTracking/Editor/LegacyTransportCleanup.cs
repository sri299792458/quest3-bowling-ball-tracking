using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace BallTracking.Editor
{
    public static class LegacyTransportCleanup
    {
        private static readonly string[] LegacyBuildScenePaths =
        {
            "Assets/RenderStreamingOfficialSample/Broadcast/Broadcast.unity",
            "Assets/BallTracking/Scenes/RenderStreamingOfficialControl.unity",
            "Assets/BallTracking/Scenes/WebRtcSmokeTest.unity",
        };

        private static readonly string[] LegacyAssetPaths =
        {
            "Assets/RenderStreamingOfficialSample",
            "Assets/BallTracking/Scenes/RenderStreamingOfficialControl.unity",
            "Assets/BallTracking/Scenes/WebRtcSmokeTest.unity",
            "Assets/BallTracking/Runtime/RenderStreamingOfficialControlBootstrap.cs",
            "Assets/BallTracking/Runtime/RenderStreamingOfficialSpinner.cs",
            "Assets/BallTracking/Runtime/WebRtcSmokeTestClient.cs",
            "Assets/BallTracking/Runtime/WebRtcSmokeTestHud.cs",
            "Assets/BallTracking/Editor/RenderStreamingOfficialControlSetup.cs",
            "Assets/BallTracking/Editor/WebRtcSmokeTestSceneSetup.cs",
        };

        private static readonly string[] LegacyProjectFilePaths =
        {
            "ProjectSettings/RenderStreamingProjectSettings.asset",
        };

        private static readonly string[] LegacyPackageKeys =
        {
            "\"com.unity.renderstreaming\"",
            "\"com.unity.webrtc\"",
        };

        [MenuItem("Tools/Ball Tracking/Clean Up Legacy Transport Artifacts")]
        public static void CleanUpLegacyTransportArtifacts()
        {
            var summary = new List<string>();

            if (StripLegacyBuildScenes())
            {
                summary.Add("Removed legacy transport scenes from Build Settings");
            }

            if (DeleteLegacyAssetPaths())
            {
                summary.Add("Deleted legacy WebRTC / Render Streaming assets");
            }

            if (DeleteLegacyProjectFiles())
            {
                summary.Add("Removed legacy project settings");
            }

            if (RemoveLegacyPackagesFromManifest())
            {
                summary.Add("Removed legacy transport packages from Packages/manifest.json");
            }

            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();

            var message = summary.Count == 0
                ? "No legacy transport artifacts were found."
                : string.Join("\n", summary);
            Debug.Log($"[LegacyTransportCleanup] {message.Replace('\n', ' ')}");
            EditorUtility.DisplayDialog("Ball Tracking", message, "OK");
        }

        internal static void StripLegacySceneAndBuildArtifacts()
        {
            if (StripLegacyBuildScenes())
            {
                AssetDatabase.SaveAssets();
            }
        }

        private static bool StripLegacyBuildScenes()
        {
            var scenes = new List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
            var filtered = scenes
                .Where(scene => !LegacyBuildScenePaths.Contains(scene.path, StringComparer.OrdinalIgnoreCase))
                .ToList();

            if (filtered.Count == scenes.Count)
            {
                return false;
            }

            EditorBuildSettings.scenes = filtered.ToArray();
            return true;
        }

        private static bool DeleteLegacyAssetPaths()
        {
            var changed = false;
            foreach (var assetPath in LegacyAssetPaths)
            {
                if (AssetDatabase.LoadMainAssetAtPath(assetPath) == null && !AssetDatabase.IsValidFolder(assetPath))
                {
                    continue;
                }

                changed |= AssetDatabase.DeleteAsset(assetPath);
            }

            return changed;
        }

        private static bool DeleteLegacyProjectFiles()
        {
            var changed = false;
            foreach (var relativePath in LegacyProjectFilePaths)
            {
                var absolutePath = Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), relativePath));
                if (!File.Exists(absolutePath))
                {
                    continue;
                }

                FileUtil.DeleteFileOrDirectory(absolutePath);
                changed = true;
            }

            return changed;
        }

        private static bool RemoveLegacyPackagesFromManifest()
        {
            var manifestPath = Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), "Packages/manifest.json"));
            if (!File.Exists(manifestPath))
            {
                return false;
            }

            var originalLines = File.ReadAllLines(manifestPath);
            var filteredLines = originalLines
                .Where(line => !LegacyPackageKeys.Any(packageKey => line.Contains(packageKey, StringComparison.Ordinal)))
                .ToArray();

            if (filteredLines.Length == originalLines.Length)
            {
                return false;
            }

            File.WriteAllText(manifestPath, string.Join(Environment.NewLine, filteredLines) + Environment.NewLine);
            return true;
        }
    }
}
