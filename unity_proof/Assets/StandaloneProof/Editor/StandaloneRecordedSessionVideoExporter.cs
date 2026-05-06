using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace QuestBowlingStandalone.Editor
{
    public static class StandaloneRecordedSessionVideoExporter
    {
        private const int DefaultResultDelayFrames = 30;
        private const int QuestRecordingRenderWidth = 1920;
        private const int QuestRecordingRenderHeight = 1440;
        private const int DefaultMaxFrames = 0;
        private const float DefaultFps = 30.0f;

        [Serializable]
        private sealed class MetadataEnvelope
        {
            public string kind;
            public QuestApp.StandaloneSessionMetadata session_metadata;
            public QuestApp.StandaloneFrameMetadata frame_metadata;
        }

        [Serializable]
        private sealed class MediaSample
        {
            public long pts_us;
        }

        [Serializable]
        private sealed class LaneLockConfirmEnvelope
        {
            public bool accepted;
            public QuestApp.StandaloneLaneLockResult lane_lock_result;
        }

        [Serializable]
        private sealed class ShotResultEnvelope
        {
            public string kind;
            public long created_unix_ms;
            public QuestApp.StandaloneShotResult shot_result;
        }

        private sealed class ShotPlayback
        {
            public QuestApp.StandaloneShotResult Result;
            public int StartFrameSeq;
            public int EndFrameSeq;
            public int RevealFrameSeq;
            public string RevealSource;
            public bool Published;
        }

        private sealed class LiveSceneObjects
        {
            public Camera Camera;
            public QuestApp.StandaloneQuestLaneLockResultRenderer LaneRenderer;
            public QuestApp.StandaloneQuestLaneLockStateCoordinator LaneCoordinator;
            public QuestApp.StandaloneQuestShotReplayRenderer ReplayRenderer;
            public QuestApp.StandaloneQuestShotReplayList ShotReplayList;
            public QuestApp.StandaloneQuestSessionReviewPanel ReviewPanel;
            public QuestApp.StandaloneQuestExperienceStatusStrip StatusStrip;
            public QuestApp.StandaloneQuestLiveResultReceiver ResultReceiver;
            public QuestApp.StandaloneQuestLiveMetadataSender MetadataSender;
            public QuestApp.StandaloneQuestSessionController SessionController;
        }

        private readonly struct Intrinsics
        {
            public Intrinsics(float fx, float fy, float cx, float cy)
            {
                Fx = fx;
                Fy = fy;
                Cx = cx;
                Cy = cy;
            }

            public float Fx { get; }
            public float Fy { get; }
            public float Cx { get; }
            public float Cy { get; }
        }

        public static void ExportLatest()
        {
            var repoRoot = ResolveRepoRoot();
            var sessionDir = GetCommandLineValue("-sessionDir");
            if (string.IsNullOrWhiteSpace(sessionDir))
            {
                sessionDir = ResolveLatestSessionDirectory(Path.Combine(repoRoot, "data", "incoming_live_streams"));
            }
            else if (!Path.IsPathRooted(sessionDir))
            {
                sessionDir = Path.GetFullPath(Path.Combine(repoRoot, sessionDir));
            }

            var output = GetCommandLineValue("-output");
            if (string.IsNullOrWhiteSpace(output))
            {
                output = Path.Combine(repoRoot, "Temp", "unity_recorded_session_overlay.mp4");
            }
            else if (!Path.IsPathRooted(output))
            {
                output = Path.GetFullPath(Path.Combine(repoRoot, output));
            }

            var startSample = GetCommandLineInt("-startSample", 0);
            var maxFrames = GetCommandLineInt("-maxFrames", DefaultMaxFrames);
            var resultDelayFrames = GetCommandLineInt("-resultDelayFrames", DefaultResultDelayFrames);
            var fps = GetCommandLineFloat("-fps", DefaultFps);
            var frameStep = Mathf.Max(1, GetCommandLineInt("-frameStep", 1));
            var questRecordingLook = GetCommandLineBool("-questRecordingLook", false);
            var openReviewAtFrameSeq = GetCommandLineInt("-openReviewAtFrameSeq", -1);

            Export(
                sessionDir,
                output,
                startSample,
                maxFrames,
                resultDelayFrames,
                fps,
                frameStep,
                questRecordingLook,
                openReviewAtFrameSeq);
        }

        private static void Export(
            string sessionDir,
            string output,
            int startSample,
            int maxFrames,
            int resultDelayFrames,
            float fps,
            int frameStep,
            bool questRecordingLook,
            int openReviewAtFrameSeq)
        {
            if (string.IsNullOrWhiteSpace(sessionDir) || !Directory.Exists(sessionDir))
            {
                throw new DirectoryNotFoundException("Recorded session directory not found: " + sessionDir);
            }

            var streamPath = Path.Combine(sessionDir, "stream.h264");
            if (!File.Exists(streamPath))
            {
                throw new FileNotFoundException("Recorded stream missing.", streamPath);
            }

            var sessionId = new DirectoryInfo(sessionDir).Name;
            var workRoot = Path.Combine(ResolveRepoRoot(), "Temp", "unity_recorded_video_export", sessionId);
            var rawFramesDir = Path.Combine(workRoot, "raw_frames");
            var renderedFramesDir = Path.Combine(workRoot, "rendered_frames");
            Directory.CreateDirectory(workRoot);
            if (!HasDecodedFrames(rawFramesDir))
            {
                EnsureCleanDirectory(rawFramesDir);
                DecodeFrames(streamPath, rawFramesDir);
            }
            EnsureCleanDirectory(renderedFramesDir);
            Directory.CreateDirectory(Path.GetDirectoryName(output) ?? ResolveRepoRoot());

            var sessionMetadata = LoadMetadata(
                sessionDir,
                out var frameMetadataByPts,
                out var frameMetadata,
                out var firstLockedFrameSeq);
            var mediaSamples = LoadMediaSamples(sessionDir);
            var laneLock = LoadConfirmedLaneLock(sessionDir);
            var shots = LoadShotResults(sessionDir, resultDelayFrames, frameMetadata);
            UnityEngine.Debug.Log($"[StandaloneRecordedSessionVideoExporter] loaded {shots.Count} shot results from {sessionDir}");

            StandaloneProofSceneSetup.CreateOrUpdateProofScene();
            var rawFrameFiles = Directory.GetFiles(rawFramesDir, "frame_*.jpg");
            Array.Sort(rawFrameFiles, StringComparer.OrdinalIgnoreCase);
            if (rawFrameFiles.Length == 0)
            {
                throw new InvalidOperationException("ffmpeg decoded no frames from stream.h264.");
            }

            var sourceWidth = sessionMetadata.actualWidth > 0 ? sessionMetadata.actualWidth : 1280;
            var sourceHeight = sessionMetadata.actualHeight > 0 ? sessionMetadata.actualHeight : 960;
            var renderWidth = questRecordingLook ? QuestRecordingRenderWidth : sourceWidth;
            var renderHeight = questRecordingLook ? QuestRecordingRenderHeight : sourceHeight;
            var sourceIntrinsics = ResolveIntrinsics(sessionMetadata, sourceWidth, sourceHeight);
            var renderIntrinsics = ScaleIntrinsics(sourceIntrinsics, sourceWidth, sourceHeight, renderWidth, renderHeight);
            var endSample = maxFrames > 0
                ? Math.Min(rawFrameFiles.Length, Math.Min(mediaSamples.Count, startSample + maxFrames))
                : Math.Min(rawFrameFiles.Length, mediaSamples.Count);
            startSample = Mathf.Clamp(startSample, 0, Math.Max(0, endSample - 1));

            var renderTexture = new RenderTexture(renderWidth, renderHeight, 24, RenderTextureFormat.ARGB32)
            {
                antiAliasing = 4,
                name = "RecordedSessionExportRenderTexture",
            };
            renderTexture.Create();

            var frameTexture = new Texture2D(2, 2, TextureFormat.RGB24, false);
            var outputTexture = new Texture2D(renderWidth, renderHeight, TextureFormat.RGB24, false);
            var liveScene = PrepareLiveSceneForExport(sessionMetadata, laneLock, renderWidth, renderHeight, renderIntrinsics);
            var camera = liveScene.Camera;

            liveScene.ResultReceiver.InjectRecordedPipelineStatus(new QuestApp.StandalonePipelineStatus
            {
                state = "recorded_export_ready",
                ready = true,
                reason = "recorded_export_ready",
                windowId = string.Empty,
            });

            var exportedFrames = 0;
            QuestApp.StandaloneFrameMetadata lastMetadata = null;
            ShotPlayback currentShot = null;
            var laneApplied = false;
            var reviewOpened = false;
            frameStep = Mathf.Max(1, frameStep);
            for (var sampleIndex = startSample; sampleIndex < endSample; sampleIndex += frameStep)
            {
                var mediaSample = mediaSamples[sampleIndex];
                if (frameMetadataByPts.TryGetValue(mediaSample.pts_us, out var metadata))
                {
                    lastMetadata = metadata;
                }
                else
                {
                    metadata = lastMetadata;
                }

                if (metadata == null)
                {
                    continue;
                }

                LoadFrameTexture(frameTexture, rawFrameFiles[sampleIndex]);
                ApplyCameraPose(camera, renderIntrinsics, metadata, renderWidth, renderHeight);

                var frameSeq = SafeFrameSeq(metadata);
                if (!laneApplied && (firstLockedFrameSeq < 0 || frameSeq >= firstLockedFrameSeq))
                {
                    if (!liveScene.LaneCoordinator.ApplyRecordedLaneLock(laneLock, out var laneNote))
                    {
                        throw new InvalidOperationException("Failed to apply recorded lane: " + laneNote);
                    }

                    laneApplied = true;
                }

                var laneVisible = laneApplied && IsLaneVisibleInFrame(laneLock, metadata, renderIntrinsics, renderWidth, renderHeight);
                if (laneVisible)
                {
                    liveScene.LaneRenderer.RenderLaneLockResult(laneLock);
                }
                else
                {
                    liveScene.LaneRenderer.ClearVisualization("recorded_lane_not_locked_yet");
                }

                var processingShot = false;
                for (var shotIndex = 0; shotIndex < shots.Count; shotIndex++)
                {
                    var shot = shots[shotIndex];
                    if (!shot.Published && frameSeq >= shot.StartFrameSeq && frameSeq < shot.RevealFrameSeq)
                    {
                        processingShot = true;
                    }

                    if (!shot.Published && frameSeq >= shot.RevealFrameSeq)
                    {
                        UnityEngine.Debug.Log(
                            $"[StandaloneRecordedSessionVideoExporter] injecting shot result {shot.Result.windowId} "
                            + $"at frameSeq={frameSeq} revealFrameSeq={shot.RevealFrameSeq} "
                            + $"revealSource={shot.RevealSource} "
                            + $"trajectoryPoints={(shot.Result.trajectory != null ? shot.Result.trajectory.Length : 0)}");
                        liveScene.ResultReceiver.InjectRecordedShotResult(shot.Result);
                        liveScene.ReplayRenderer.RenderShotResult(shot.Result);
                        UnityEngine.Debug.Log(
                            $"[StandaloneRecordedSessionVideoExporter] replay renderer status={liveScene.ReplayRenderer.LastStatus} "
                            + $"hasReplay={liveScene.ReplayRenderer.HasReplay}");
                        shot.Published = true;
                        currentShot = shot;
                    }
                }

                if (!reviewOpened
                    && openReviewAtFrameSeq >= 0
                    && frameSeq >= openReviewAtFrameSeq
                    && liveScene.ShotReplayList.ShotCount > 0)
                {
                    InvokeUnityMessage(liveScene.ReviewPanel, "ToggleReview");
                    reviewOpened = true;
                }

                if (currentShot != null && currentShot.Published)
                {
                    var replayFrames = Mathf.Max(1, Mathf.RoundToInt(fps * 3.0f));
                    var holdFrames = Mathf.Max(0, Mathf.RoundToInt(fps * 4.0f));
                    var replayElapsedFrames = frameSeq - currentShot.RevealFrameSeq;
                    if (replayElapsedFrames <= replayFrames)
                    {
                        var t = Mathf.Clamp01(replayElapsedFrames / (float)Mathf.Max(1, replayFrames));
                        liveScene.ReplayRenderer.SetReplayPreviewTime(t);
                    }
                    else if (replayElapsedFrames <= replayFrames + holdFrames)
                    {
                        liveScene.ReplayRenderer.SetReplayPreviewTime(1.0f);
                    }
                    else
                    {
                        liveScene.ReplayRenderer.ClearReplay("recorded_export_replay_hold_complete");
                        currentShot = null;
                    }
                }

                liveScene.ResultReceiver.InjectRecordedPipelineStatus(new QuestApp.StandalonePipelineStatus
                {
                    state = processingShot ? "recorded_export_processing_shot" : "recorded_export_ready",
                    ready = !processingShot,
                    reason = processingShot ? "processing_shot" : "recorded_export_ready",
                    windowId = currentShot != null ? currentShot.Result.windowId : string.Empty,
                });
                RefreshLiveSceneUi(liveScene);
                Graphics.Blit(frameTexture, renderTexture);
                camera.targetTexture = renderTexture;
                camera.Render();

                RenderTexture.active = renderTexture;
                outputTexture.ReadPixels(new Rect(0, 0, renderWidth, renderHeight), 0, 0);
                outputTexture.Apply(false);
                var renderedPath = Path.Combine(renderedFramesDir, $"frame_{exportedFrames + 1:000000}.jpg");
                File.WriteAllBytes(renderedPath, outputTexture.EncodeToJPG(96));
                exportedFrames++;

                if (exportedFrames % 300 == 0)
                {
                    UnityEngine.Debug.Log($"[StandaloneRecordedSessionVideoExporter] rendered {exportedFrames} frames...");
                }
            }

            UnityEngine.Object.DestroyImmediate(frameTexture);
            UnityEngine.Object.DestroyImmediate(outputTexture);
            camera.targetTexture = null;
            RenderTexture.active = null;
            renderTexture.Release();
            UnityEngine.Object.DestroyImmediate(renderTexture);

            EncodeVideo(renderedFramesDir, output, Mathf.Max(1.0f, fps / frameStep), questRecordingLook);
            UnityEngine.Debug.Log(
                $"[StandaloneRecordedSessionVideoExporter] exported {exportedFrames} frames to {output}");
        }

        private static LiveSceneObjects PrepareLiveSceneForExport(
            QuestApp.StandaloneSessionMetadata sessionMetadata,
            QuestApp.StandaloneLaneLockResult laneLock,
            int width,
            int height,
            Intrinsics intrinsics)
        {
            var liveScene = new LiveSceneObjects
            {
                Camera = ResolveSceneCamera(),
                LaneRenderer = FindRequired<QuestApp.StandaloneQuestLaneLockResultRenderer>(),
                LaneCoordinator = FindRequired<QuestApp.StandaloneQuestLaneLockStateCoordinator>(),
                ReplayRenderer = FindRequired<QuestApp.StandaloneQuestShotReplayRenderer>(),
                ShotReplayList = FindRequired<QuestApp.StandaloneQuestShotReplayList>(),
                ReviewPanel = FindRequired<QuestApp.StandaloneQuestSessionReviewPanel>(),
                StatusStrip = FindRequired<QuestApp.StandaloneQuestExperienceStatusStrip>(),
                ResultReceiver = FindRequired<QuestApp.StandaloneQuestLiveResultReceiver>(),
                MetadataSender = FindRequired<QuestApp.StandaloneQuestLiveMetadataSender>(),
                SessionController = FindRequired<QuestApp.StandaloneQuestSessionController>(),
            };

            DisableVerboseSceneLogging();
            ConfigureSceneCamera(liveScene.Camera, width, height, intrinsics);
            ConfigureSceneCanvases(liveScene.Camera);
            DisableEditorOnlySceneClutter(liveScene.Camera);
            liveScene.ReplayRenderer.SetViewCamera(liveScene.Camera);

            var sessionId = !string.IsNullOrWhiteSpace(sessionMetadata.sessionId)
                ? sessionMetadata.sessionId
                : !string.IsNullOrWhiteSpace(laneLock.sessionId)
                    ? laneLock.sessionId
                    : "recorded-session";
            liveScene.SessionController.InjectRecordedExportSessionState(
                sessionId,
                "session-stream",
                mediaReady: true,
                mediaNote: "media_stream_ready");
            liveScene.MetadataSender.InjectRecordedExportConnectionState(true);
            liveScene.ResultReceiver.InjectRecordedExportConnectionState(true);

            InvokeUnityMessage(liveScene.LaneRenderer, "Awake");
            InvokeUnityMessage(liveScene.LaneCoordinator, "Awake");
            InvokeUnityMessage(liveScene.ReplayRenderer, "Awake");
            InvokeUnityMessage(liveScene.ReplayRenderer, "OnEnable");
            InvokeUnityMessage(liveScene.ShotReplayList, "Awake");
            InvokeUnityMessage(liveScene.ShotReplayList, "OnEnable");
            InvokeUnityMessage(liveScene.ReviewPanel, "Awake");
            InvokeUnityMessage(liveScene.ReviewPanel, "OnEnable");
            InvokeUnityMessage(liveScene.StatusStrip, "Awake");

            foreach (var button in UnityEngine.Object.FindObjectsByType<QuestApp.StandaloneQuestLaneLockButton>(
                         FindObjectsInactive.Include,
                         FindObjectsSortMode.None))
            {
                InvokeUnityMessage(button, "Awake");
                InvokeUnityMessage(button, "Update");
            }

            RefreshLiveSceneUi(liveScene);
            return liveScene;
        }

        private static void DisableVerboseSceneLogging()
        {
            foreach (var behaviour in UnityEngine.Object.FindObjectsByType<MonoBehaviour>(
                         FindObjectsInactive.Include,
                         FindObjectsSortMode.None))
            {
                if (behaviour == null)
                {
                    continue;
                }

                var serialized = new SerializedObject(behaviour);
                var property = serialized.FindProperty("verboseLogging");
                if (property == null || property.propertyType != SerializedPropertyType.Boolean)
                {
                    continue;
                }

                property.boolValue = false;
                serialized.ApplyModifiedPropertiesWithoutUndo();
            }
        }

        private static T FindRequired<T>() where T : UnityEngine.Object
        {
            var value = UnityEngine.Object.FindFirstObjectByType<T>(FindObjectsInactive.Include);
            if (value == null)
            {
                throw new InvalidOperationException("StandaloneProof scene is missing " + typeof(T).Name);
            }

            return value;
        }

        private static Camera ResolveSceneCamera()
        {
            var centerEye = GameObject.Find("CenterEyeAnchor");
            var camera = centerEye != null ? centerEye.GetComponent<Camera>() : null;
            if (camera == null)
            {
                camera = Camera.main;
            }

            if (camera == null)
            {
                camera = UnityEngine.Object.FindFirstObjectByType<Camera>(FindObjectsInactive.Include);
            }

            if (camera == null)
            {
                throw new InvalidOperationException("StandaloneProof scene does not contain an export camera.");
            }

            return camera;
        }

        private static void ConfigureSceneCamera(Camera camera, int width, int height, Intrinsics intrinsics)
        {
            foreach (var sceneCamera in UnityEngine.Object.FindObjectsByType<Camera>(
                         FindObjectsInactive.Include,
                         FindObjectsSortMode.None))
            {
                if (sceneCamera != camera)
                {
                    sceneCamera.enabled = false;
                }
            }

            camera.enabled = false;
            camera.clearFlags = CameraClearFlags.Depth;
            camera.backgroundColor = Color.clear;
            camera.nearClipPlane = 0.01f;
            camera.farClipPlane = 80.0f;
            camera.allowHDR = false;
            camera.allowMSAA = true;
            camera.aspect = (float)width / Mathf.Max(1, height);
            camera.cullingMask = ~0;
            camera.projectionMatrix = BuildProjectionMatrix(intrinsics, width, height, camera.nearClipPlane, camera.farClipPlane);
        }

        private static void ConfigureSceneCanvases(Camera camera)
        {
            foreach (var canvas in UnityEngine.Object.FindObjectsByType<Canvas>(
                         FindObjectsInactive.Include,
                         FindObjectsSortMode.None))
            {
                if (canvas.renderMode == RenderMode.WorldSpace)
                {
                    canvas.worldCamera = camera;
                }
            }
        }

        private static void DisableEditorOnlySceneClutter(Camera exportCamera)
        {
            foreach (var candidateName in new[]
                     {
                         "StandaloneProofLeftHand",
                         "StandaloneLeftRayHelper",
                         "OVRLeftHandPrefab",
                         "OVRRightHandPrefab",
                         "LeftHandAnchor",
                         "RightHandAnchor",
                     })
            {
                var obj = GameObject.Find(candidateName);
                if (obj != null && obj.transform != exportCamera.transform)
                {
                    obj.SetActive(false);
                }
            }
        }

        private static void RefreshLiveSceneUi(LiveSceneObjects liveScene)
        {
            if (liveScene == null)
            {
                return;
            }

            InvokeUnityMessage(liveScene.ShotReplayList, "Update");
            InvokeUnityMessage(liveScene.StatusStrip, "Refresh");
            foreach (var button in UnityEngine.Object.FindObjectsByType<QuestApp.StandaloneQuestLaneLockButton>(
                         FindObjectsInactive.Include,
                         FindObjectsSortMode.None))
            {
                InvokeUnityMessage(button, "Update");
            }
        }

        private static void InvokeUnityMessage(UnityEngine.Object target, string methodName)
        {
            if (target == null || string.IsNullOrWhiteSpace(methodName))
            {
                return;
            }

            var method = target.GetType().GetMethod(
                methodName,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            method?.Invoke(target, null);
        }

        private static void ApplyCameraPose(
            Camera camera,
            Intrinsics intrinsics,
            QuestApp.StandaloneFrameMetadata frameMetadata,
            int width,
            int height)
        {
            camera.transform.SetPositionAndRotation(frameMetadata.cameraPosition, frameMetadata.cameraRotation);
            camera.projectionMatrix = BuildProjectionMatrix(
                intrinsics,
                width,
                height,
                camera.nearClipPlane,
                camera.farClipPlane);
        }

        private static Intrinsics ResolveIntrinsics(
            QuestApp.StandaloneSessionMetadata metadata,
            int width,
            int height)
        {
            var fx = metadata.fx > 0.0f ? metadata.fx : width;
            var fy = metadata.fy > 0.0f ? metadata.fy : width;
            var cx = metadata.cx > 0.0f ? metadata.cx : width * 0.5f;
            var cy = metadata.cy > 0.0f ? metadata.cy : height * 0.5f;
            var sensorWidth = metadata.sensorWidth > 0 ? metadata.sensorWidth : width;
            var sensorHeight = metadata.sensorHeight > 0 ? metadata.sensorHeight : height;
            if (width > 0 && height > 0 && sensorWidth > 0 && sensorHeight > 0)
            {
                var scaleX = (float)width / sensorWidth;
                var scaleY = (float)height / sensorHeight;
                var cropScale = Mathf.Max(scaleX, scaleY);
                if (cropScale > 0.0f)
                {
                    var cropWidth = width / cropScale;
                    var cropHeight = height / cropScale;
                    var cropX = (sensorWidth - cropWidth) * 0.5f;
                    var cropY = (sensorHeight - cropHeight) * 0.5f;
                    if (cropWidth > 0.0f && cropHeight > 0.0f)
                    {
                        var xScale = width / cropWidth;
                        var yScale = height / cropHeight;
                        fx *= xScale;
                        fy *= yScale;
                        cx = (cx - cropX) * xScale;
                        cy = height - (cy - cropY) * yScale;
                    }
                }
            }

            return new Intrinsics(fx, fy, cx, cy);
        }

        private static Intrinsics ScaleIntrinsics(
            Intrinsics intrinsics,
            int sourceWidth,
            int sourceHeight,
            int targetWidth,
            int targetHeight)
        {
            var scaleX = (float)targetWidth / Mathf.Max(1, sourceWidth);
            var scaleY = (float)targetHeight / Mathf.Max(1, sourceHeight);
            return new Intrinsics(
                intrinsics.Fx * scaleX,
                intrinsics.Fy * scaleY,
                intrinsics.Cx * scaleX,
                intrinsics.Cy * scaleY);
        }

        private static Matrix4x4 BuildProjectionMatrix(
            Intrinsics intrinsics,
            int width,
            int height,
            float near,
            float far)
        {
            var projection = new Matrix4x4();
            projection[0, 0] = 2.0f * intrinsics.Fx / width;
            projection[0, 1] = 0.0f;
            projection[0, 2] = 1.0f - 2.0f * intrinsics.Cx / width;
            projection[0, 3] = 0.0f;
            projection[1, 0] = 0.0f;
            projection[1, 1] = 2.0f * intrinsics.Fy / height;
            projection[1, 2] = 2.0f * intrinsics.Cy / height - 1.0f;
            projection[1, 3] = 0.0f;
            projection[2, 0] = 0.0f;
            projection[2, 1] = 0.0f;
            projection[2, 2] = -(far + near) / (far - near);
            projection[2, 3] = -(2.0f * far * near) / (far - near);
            projection[3, 0] = 0.0f;
            projection[3, 1] = 0.0f;
            projection[3, 2] = -1.0f;
            projection[3, 3] = 0.0f;
            return projection;
        }

        private static QuestApp.StandaloneSessionMetadata LoadMetadata(
            string sessionDir,
            out Dictionary<long, QuestApp.StandaloneFrameMetadata> frameMetadataByPts,
            out List<QuestApp.StandaloneFrameMetadata> frameMetadata,
            out int firstLockedFrameSeq)
        {
            frameMetadataByPts = new Dictionary<long, QuestApp.StandaloneFrameMetadata>();
            frameMetadata = new List<QuestApp.StandaloneFrameMetadata>();
            firstLockedFrameSeq = -1;
            QuestApp.StandaloneSessionMetadata sessionMetadata = null;
            foreach (var line in ReadSharedLines(Path.Combine(sessionDir, "metadata_stream.jsonl")))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                var envelope = JsonUtility.FromJson<MetadataEnvelope>(line);
                if (envelope == null)
                {
                    continue;
                }

                if (envelope.kind == "session_start" && envelope.session_metadata != null)
                {
                    sessionMetadata = envelope.session_metadata;
                }
                else if (envelope.kind == "frame_metadata" && envelope.frame_metadata != null)
                {
                    frameMetadataByPts[envelope.frame_metadata.ptsUs] = envelope.frame_metadata;
                    frameMetadata.Add(envelope.frame_metadata);
                    if (firstLockedFrameSeq < 0 && envelope.frame_metadata.laneLockState == QuestApp.StandaloneLaneLockState.Locked)
                    {
                        firstLockedFrameSeq = SafeFrameSeq(envelope.frame_metadata);
                    }
                }
            }

            if (sessionMetadata == null)
            {
                throw new InvalidOperationException("metadata_stream.jsonl did not contain a session_start envelope.");
            }

            frameMetadata.Sort((left, right) => left.cameraTimestampUs.CompareTo(right.cameraTimestampUs));
            return sessionMetadata;
        }

        private static bool IsLaneVisibleInFrame(
            QuestApp.StandaloneLaneLockResult laneLock,
            QuestApp.StandaloneFrameMetadata metadata,
            Intrinsics intrinsics,
            int width,
            int height)
        {
            if (laneLock == null || metadata == null)
            {
                return false;
            }

            var halfWidth = Mathf.Max(0.01f, laneLock.laneWidthMeters * 0.5f);
            var laneLength = Mathf.Max(0.01f, laneLock.laneLengthMeters);
            var lift = 0.025f;
            var points = new[]
            {
                LaneWorldPoint(laneLock, -halfWidth, 0.0f, lift),
                LaneWorldPoint(laneLock, halfWidth, 0.0f, lift),
                LaneWorldPoint(laneLock, halfWidth, laneLength, lift),
                LaneWorldPoint(laneLock, -halfWidth, laneLength, lift),
            };

            var anyVisible = false;
            for (var index = 0; index < points.Length; index++)
            {
                if (!TryProjectWorldToImage(points[index], metadata, intrinsics, out var imagePoint))
                {
                    return false;
                }

                const float margin = 240.0f;
                if (imagePoint.x >= -margin
                    && imagePoint.x <= width + margin
                    && imagePoint.y >= -margin
                    && imagePoint.y <= height + margin)
                {
                    anyVisible = true;
                }
            }

            return anyVisible;
        }

        private static Vector3 LaneWorldPoint(
            QuestApp.StandaloneLaneLockResult laneLock,
            float xMeters,
            float sMeters,
            float liftMeters)
        {
            var rotation = Normalize(laneLock.laneRotationWorld);
            return laneLock.laneOriginWorld + rotation * new Vector3(xMeters, liftMeters, sMeters);
        }

        private static bool TryProjectWorldToImage(
            Vector3 worldPoint,
            QuestApp.StandaloneFrameMetadata metadata,
            Intrinsics intrinsics,
            out Vector2 imagePoint)
        {
            var rotationCameraFromWorld = Quaternion.Inverse(Normalize(metadata.cameraRotation));
            var pointCamera = rotationCameraFromWorld * (worldPoint - metadata.cameraPosition);
            if (pointCamera.z <= 1e-5f)
            {
                imagePoint = Vector2.zero;
                return false;
            }

            imagePoint = new Vector2(
                intrinsics.Fx * pointCamera.x / pointCamera.z + intrinsics.Cx,
                -intrinsics.Fy * pointCamera.y / pointCamera.z + intrinsics.Cy);
            return IsFinite(imagePoint.x) && IsFinite(imagePoint.y);
        }

        private static Quaternion Normalize(Quaternion rotation)
        {
            var magnitude = Mathf.Sqrt(
                rotation.x * rotation.x
                + rotation.y * rotation.y
                + rotation.z * rotation.z
                + rotation.w * rotation.w);
            if (magnitude <= 0.0001f)
            {
                return Quaternion.identity;
            }

            return new Quaternion(
                rotation.x / magnitude,
                rotation.y / magnitude,
                rotation.z / magnitude,
                rotation.w / magnitude);
        }

        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        private static List<MediaSample> LoadMediaSamples(string sessionDir)
        {
            var rows = new List<MediaSample>();
            foreach (var line in ReadSharedLines(Path.Combine(sessionDir, "media_samples.jsonl")))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                var row = JsonUtility.FromJson<MediaSample>(line);
                if (row != null)
                {
                    rows.Add(row);
                }
            }

            return rows;
        }

        private static QuestApp.StandaloneLaneLockResult LoadConfirmedLaneLock(string sessionDir)
        {
            QuestApp.StandaloneLaneLockResult laneLock = null;
            foreach (var line in ReadSharedLines(Path.Combine(sessionDir, "lane_lock_confirms.jsonl")))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                var envelope = JsonUtility.FromJson<LaneLockConfirmEnvelope>(line);
                if (envelope != null && envelope.accepted && envelope.lane_lock_result != null)
                {
                    laneLock = envelope.lane_lock_result;
                }
            }

            if (laneLock == null)
            {
                throw new InvalidOperationException("No accepted lane lock found in lane_lock_confirms.jsonl.");
            }

            return laneLock;
        }

        private static List<ShotPlayback> LoadShotResults(
            string sessionDir,
            int resultDelayFrames,
            IReadOnlyList<QuestApp.StandaloneFrameMetadata> frameMetadata)
        {
            var shots = new List<ShotPlayback>();
            var root = Path.Combine(sessionDir, "analysis_shot_tracking");
            if (!Directory.Exists(root))
            {
                return shots;
            }

            var revealFramesByWindowId = LoadShotRevealFrameSeqs(sessionDir, frameMetadata);
            var paths = Directory.GetFiles(root, "shot_result.json", SearchOption.AllDirectories);
            Array.Sort(paths, StringComparer.OrdinalIgnoreCase);
            foreach (var path in paths)
            {
                var result = JsonUtility.FromJson<QuestApp.StandaloneShotResult>(File.ReadAllText(path));
                if (result == null || !result.success || result.trajectory == null || result.trajectory.Length == 0)
                {
                    continue;
                }

                var start = result.sourceFrameRange != null ? result.sourceFrameRange.start : 0;
                var end = result.sourceFrameRange != null ? result.sourceFrameRange.end : start;
                var fallbackReveal = end + Math.Max(0, resultDelayFrames);
                var reveal = fallbackReveal;
                var revealSource = "fallback_delay_frames";
                if (!string.IsNullOrWhiteSpace(result.windowId)
                    && revealFramesByWindowId.TryGetValue(result.windowId, out var outboundReveal))
                {
                    reveal = Math.Max(end, outboundReveal);
                    revealSource = "outbound_results_created_unix_ms";
                }

                shots.Add(new ShotPlayback
                {
                    Result = result,
                    StartFrameSeq = start,
                    EndFrameSeq = end,
                    RevealFrameSeq = reveal,
                    RevealSource = revealSource,
                });
            }

            shots.Sort((left, right) => left.StartFrameSeq.CompareTo(right.StartFrameSeq));
            return shots;
        }

        private static Dictionary<string, int> LoadShotRevealFrameSeqs(
            string sessionDir,
            IReadOnlyList<QuestApp.StandaloneFrameMetadata> frameMetadata)
        {
            var revealFramesByWindowId = new Dictionary<string, int>(StringComparer.Ordinal);
            var path = Path.Combine(sessionDir, "outbound_results.jsonl");
            if (!File.Exists(path) || frameMetadata == null || frameMetadata.Count == 0)
            {
                return revealFramesByWindowId;
            }

            foreach (var line in ReadSharedLines(path))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                var envelope = JsonUtility.FromJson<ShotResultEnvelope>(line);
                if (envelope == null
                    || envelope.kind != "shot_result"
                    || envelope.created_unix_ms <= 0
                    || envelope.shot_result == null
                    || string.IsNullOrWhiteSpace(envelope.shot_result.windowId))
                {
                    continue;
                }

                var revealFrameSeq = FindFrameSeqAtOrAfterUnixMs(frameMetadata, envelope.created_unix_ms);
                revealFramesByWindowId[envelope.shot_result.windowId] = revealFrameSeq;
            }

            return revealFramesByWindowId;
        }

        private static int FindFrameSeqAtOrAfterUnixMs(
            IReadOnlyList<QuestApp.StandaloneFrameMetadata> frameMetadata,
            long unixMs)
        {
            var targetUs = unixMs * 1000L;
            var left = 0;
            var right = frameMetadata.Count - 1;
            var best = right;
            while (left <= right)
            {
                var middle = left + ((right - left) / 2);
                if (frameMetadata[middle].cameraTimestampUs >= targetUs)
                {
                    best = middle;
                    right = middle - 1;
                }
                else
                {
                    left = middle + 1;
                }
            }

            return SafeFrameSeq(frameMetadata[Mathf.Clamp(best, 0, frameMetadata.Count - 1)]);
        }

        private static int SafeFrameSeq(QuestApp.StandaloneFrameMetadata metadata)
        {
            return metadata == null ? 0 : unchecked((int)Math.Min(int.MaxValue, metadata.frameSeq));
        }

        private static void LoadFrameTexture(Texture2D texture, string path)
        {
            if (!texture.LoadImage(File.ReadAllBytes(path), false))
            {
                throw new InvalidOperationException("Failed to load decoded frame: " + path);
            }
        }

        private static void DecodeFrames(string streamPath, string outputDir)
        {
            var outputPattern = Path.Combine(outputDir, "frame_%06d.jpg");
            RunProcess(
                "ffmpeg",
                $"-y -hide_banner -loglevel error -i \"{streamPath}\" -q:v 3 \"{outputPattern}\"");
        }

        private static bool HasDecodedFrames(string path)
        {
            return Directory.Exists(path) && Directory.GetFiles(path, "frame_*.jpg").Length > 0;
        }

        private static void EncodeVideo(string framesDir, string output, float fps, bool questRecordingLook)
        {
            var inputPattern = Path.Combine(framesDir, "frame_%06d.jpg");
            var videoFilter = questRecordingLook
                ? " -vf \"crop=1920:1080,eq=contrast=1.035:brightness=-0.012:saturation=0.94\" "
                : " ";
            RunProcess(
                "ffmpeg",
                "-y -hide_banner -loglevel error "
                + "-framerate " + fps.ToString("0.###", CultureInfo.InvariantCulture)
                + " -i \"" + inputPattern + "\" "
                + videoFilter
                + "-c:v libx264 -pix_fmt yuv420p -crf 18 \"" + output + "\"");
        }

        private static void RunProcess(string fileName, string arguments)
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            };
            using (var process = Process.Start(startInfo))
            {
                if (process == null)
                {
                    throw new InvalidOperationException("Failed to start process: " + fileName);
                }

                var stdout = process.StandardOutput.ReadToEnd();
                var stderr = process.StandardError.ReadToEnd();
                process.WaitForExit();
                if (process.ExitCode != 0)
                {
                    throw new InvalidOperationException(
                        fileName + " failed with exit code " + process.ExitCode + "\n" + stdout + "\n" + stderr);
                }
            }
        }

        private static string[] ReadSharedLines(string path)
        {
            using (var stream = new FileStream(
                       path,
                       FileMode.Open,
                       FileAccess.Read,
                       FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(stream))
            {
                return reader.ReadToEnd().Split(new[] { "\r\n", "\n" }, StringSplitOptions.None);
            }
        }

        private static string ResolveRepoRoot()
        {
            return Path.GetFullPath(Path.Combine(Application.dataPath, "..", ".."));
        }

        private static string ResolveLatestSessionDirectory(string incomingRoot)
        {
            if (!Directory.Exists(incomingRoot))
            {
                throw new DirectoryNotFoundException("Incoming live stream root not found: " + incomingRoot);
            }

            var candidates = Directory.GetDirectories(incomingRoot, "live_*_session-stream");
            if (candidates.Length == 0)
            {
                throw new DirectoryNotFoundException("No live session directories found under: " + incomingRoot);
            }

            Array.Sort(candidates, (left, right) =>
                Directory.GetLastWriteTimeUtc(right).CompareTo(Directory.GetLastWriteTimeUtc(left)));
            return candidates[0];
        }

        private static string GetCommandLineValue(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (var index = 0; index < args.Length - 1; index++)
            {
                if (args[index] == name)
                {
                    return args[index + 1];
                }
            }

            return string.Empty;
        }

        private static int GetCommandLineInt(string name, int fallback)
        {
            return int.TryParse(GetCommandLineValue(name), NumberStyles.Integer, CultureInfo.InvariantCulture, out var value)
                ? value
                : fallback;
        }

        private static float GetCommandLineFloat(string name, float fallback)
        {
            return float.TryParse(GetCommandLineValue(name), NumberStyles.Float, CultureInfo.InvariantCulture, out var value)
                ? value
                : fallback;
        }

        private static bool GetCommandLineBool(string name, bool fallback)
        {
            var raw = GetCommandLineValue(name);
            if (string.IsNullOrWhiteSpace(raw))
            {
                return fallback;
            }

            return raw.Equals("1", StringComparison.OrdinalIgnoreCase)
                || raw.Equals("true", StringComparison.OrdinalIgnoreCase)
                || raw.Equals("yes", StringComparison.OrdinalIgnoreCase);
        }

        private static void EnsureCleanDirectory(string path)
        {
            var fullPath = Path.GetFullPath(path);
            var tempRoot = Path.GetFullPath(Path.Combine(ResolveRepoRoot(), "Temp"));
            if (!fullPath.StartsWith(tempRoot, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("Refusing to clean path outside repo Temp: " + fullPath);
            }

            if (Directory.Exists(fullPath))
            {
                Directory.Delete(fullPath, true);
            }

            Directory.CreateDirectory(fullPath);
        }
    }
}
