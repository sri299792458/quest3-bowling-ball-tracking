using System.IO;
using Meta.XR;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.XR.OpenXR;
using UnityEngine.XR.OpenXR.Features.Interactions;
using UnityEngine.XR.OpenXR.Features.MetaQuestSupport;

namespace QuestBowlingStandalone.Editor
{
    public static class StandaloneProofBuild
    {
        private const string OutputPath = "Builds/StandaloneProof.apk";

        [MenuItem("Tools/Standalone Proof/Build Android Proof APK")]
        public static void BuildAndroidProofApk()
        {
            StandaloneProofSceneSetup.PrepareSceneForBuild();
            ConfigurePlayerSettings();

            var fullOutputPath = Path.GetFullPath(OutputPath);
            Directory.CreateDirectory(Path.GetDirectoryName(fullOutputPath) ?? "Builds");

            var previousUseDefaultApis = PlayerSettings.GetUseDefaultGraphicsAPIs(BuildTarget.Android);
            var previousApis = PlayerSettings.GetGraphicsAPIs(BuildTarget.Android);
            var xrCompatibility = CaptureAndroidOpenXrCompatibility();

            try
            {
                PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
                PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, new[] { GraphicsDeviceType.OpenGLES3 });
                ApplyAndroidOpenXrCompatibility(xrCompatibility, enableProofCompatibility: true);

                if (File.Exists(fullOutputPath))
                {
                    File.Delete(fullOutputPath);
                }

                Debug.Log($"[StandaloneProofBuild] Building Android proof APK to {fullOutputPath}");

                var buildPlayerOptions = new BuildPlayerOptions
                {
                    scenes = new[] { StandaloneProofSceneSetup.ScenePath },
                    locationPathName = fullOutputPath,
                    target = BuildTarget.Android,
                    options = BuildOptions.Development,
                };

                var report = BuildPipeline.BuildPlayer(buildPlayerOptions);
                if (report.summary.result != BuildResult.Succeeded)
                {
                    throw new System.InvalidOperationException($"Standalone proof Android build failed: {report.summary.result}");
                }

                Debug.Log($"[StandaloneProofBuild] Build succeeded: {report.summary.outputPath}");
            }
            finally
            {
                ApplyAndroidOpenXrCompatibility(xrCompatibility, enableProofCompatibility: false);
                PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, previousUseDefaultApis);
                if (!previousUseDefaultApis && previousApis != null && previousApis.Length > 0)
                {
                    PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, previousApis);
                }

                AssetDatabase.SaveAssets();
            }
        }

        private static void ConfigurePlayerSettings()
        {
            PlayerSettings.companyName = "QuestBowlingStandalone";
            PlayerSettings.productName = "QuestBowlingStandaloneProof";
            PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Android, "com.student.questbowlingstandaloneproof");
            PlayerSettings.SetScriptingBackend(NamedBuildTarget.Android, ScriptingImplementation.IL2CPP);
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel32;
            PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevelAuto;
            PlayerSettings.colorSpace = ColorSpace.Linear;
        }

        private sealed class AndroidOpenXrCompatibilitySnapshot
        {
            public Object[] TouchedObjects;
            public bool? SubsampledLayoutEnabled;
            public bool? MetaFoveationEnabled;
            public bool? OptimizeBufferDiscardsEnabled;
            public bool? OculusTouchControllerProfileEnabled;
        }

        private static AndroidOpenXrCompatibilitySnapshot CaptureAndroidOpenXrCompatibility()
        {
            var snapshot = new AndroidOpenXrCompatibilitySnapshot();
            var settings = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Android);
            if (settings == null)
            {
                return snapshot;
            }

            var touched = new System.Collections.Generic.List<Object>();

            var subsampledLayout = settings.GetFeature<MetaXRSubsampledLayout>();
            if (subsampledLayout != null)
            {
                snapshot.SubsampledLayoutEnabled = subsampledLayout.enabled;
                touched.Add(subsampledLayout);
            }

            var metaFoveation = settings.GetFeature<MetaXRFoveationFeature>();
            if (metaFoveation != null)
            {
                snapshot.MetaFoveationEnabled = metaFoveation.enabled;
                touched.Add(metaFoveation);
            }

            var metaQuestFeature = settings.GetFeature<MetaQuestFeature>();
            if (metaQuestFeature != null)
            {
                var serializedFeature = new SerializedObject(metaQuestFeature);
                var optimizeBufferDiscards = serializedFeature.FindProperty("m_optimizeBufferDiscards");
                if (optimizeBufferDiscards != null)
                {
                    snapshot.OptimizeBufferDiscardsEnabled = optimizeBufferDiscards.boolValue;
                    touched.Add(metaQuestFeature);
                }
            }

            var oculusTouchControllerProfile = settings.GetFeature<OculusTouchControllerProfile>();
            if (oculusTouchControllerProfile != null)
            {
                snapshot.OculusTouchControllerProfileEnabled = oculusTouchControllerProfile.enabled;
                touched.Add(oculusTouchControllerProfile);
            }

            snapshot.TouchedObjects = touched.ToArray();
            return snapshot;
        }

        private static void ApplyAndroidOpenXrCompatibility(AndroidOpenXrCompatibilitySnapshot snapshot, bool enableProofCompatibility)
        {
            if (snapshot == null)
            {
                return;
            }

            var settings = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Android);
            if (settings == null)
            {
                return;
            }

            var subsampledLayout = settings.GetFeature<MetaXRSubsampledLayout>();
            if (subsampledLayout != null && snapshot.SubsampledLayoutEnabled.HasValue)
            {
                SetFeatureEnabled(subsampledLayout, enableProofCompatibility ? false : snapshot.SubsampledLayoutEnabled.Value);
            }

            var metaFoveation = settings.GetFeature<MetaXRFoveationFeature>();
            if (metaFoveation != null && snapshot.MetaFoveationEnabled.HasValue)
            {
                SetFeatureEnabled(metaFoveation, enableProofCompatibility ? false : snapshot.MetaFoveationEnabled.Value);
            }

            var metaQuestFeature = settings.GetFeature<MetaQuestFeature>();
            if (metaQuestFeature != null && snapshot.OptimizeBufferDiscardsEnabled.HasValue)
            {
                SetSerializedBool(metaQuestFeature, "m_optimizeBufferDiscards", enableProofCompatibility ? false : snapshot.OptimizeBufferDiscardsEnabled.Value);
            }

            var oculusTouchControllerProfile = settings.GetFeature<OculusTouchControllerProfile>();
            if (oculusTouchControllerProfile != null && snapshot.OculusTouchControllerProfileEnabled.HasValue)
            {
                SetFeatureEnabled(oculusTouchControllerProfile, enableProofCompatibility ? true : snapshot.OculusTouchControllerProfileEnabled.Value);
            }

            if (snapshot.TouchedObjects != null)
            {
                foreach (var touchedObject in snapshot.TouchedObjects)
                {
                    if (touchedObject != null)
                    {
                        EditorUtility.SetDirty(touchedObject);
                    }
                }
            }

            AssetDatabase.SaveAssets();
        }

        private static void SetFeatureEnabled(ScriptableObject feature, bool enabled)
        {
            var serializedFeature = new SerializedObject(feature);
            var enabledProperty = serializedFeature.FindProperty("m_enabled");
            if (enabledProperty == null)
            {
                return;
            }

            enabledProperty.boolValue = enabled;
            serializedFeature.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void SetSerializedBool(ScriptableObject targetObject, string propertyName, bool value)
        {
            var serializedObject = new SerializedObject(targetObject);
            var property = serializedObject.FindProperty(propertyName);
            if (property == null)
            {
                return;
            }

            property.boolValue = value;
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
        }
    }
}
