using System;
using System.IO;
using Meta.XR;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestLocalProofCapture : MonoBehaviour
    {
        [Header("Camera")]
        [SerializeField] private PassthroughCameraAccess cameraAccess;
        [SerializeField] private PassthroughCameraAccess.CameraPositionType cameraPosition = PassthroughCameraAccess.CameraPositionType.Left;
        [SerializeField] private Transform headTransform;

        [Header("Media Target")]
        [SerializeField] private Vector2Int requestedResolution = new(1280, 960);
        [SerializeField] private int targetFps = 30;
        [SerializeField] private int targetBitrateKbps = 3500;
        [SerializeField] private string videoCodec = "h264";
        [SerializeField] private bool allowSystemUtcFallback;

        [Header("Artifact Output")]
        [SerializeField] private string outputFolderName = "standalone_local_clips";
        [SerializeField] private bool createEmptyVideoPlaceholder = true;
        [SerializeField] private bool startEncoderOnProofClip;
        [SerializeField] private float iFrameIntervalSeconds = 1.0f;
        [SerializeField] private bool verboseLogging;

        [Header("Lane Lock Snapshot")]
        [SerializeField] private StandaloneLaneLockState laneLockState = StandaloneLaneLockState.Unknown;
        [SerializeField] private float laneLockConfidence;
        [SerializeField] private Vector3 laneOriginWorld;
        [SerializeField] private Quaternion laneRotationWorld = Quaternion.identity;
        [SerializeField] private float laneWidthMeters = 1.0668f;
        [SerializeField] private float laneLengthMeters = 18.288f;

        private StandaloneLocalClipArtifactWriter _artifactWriter;
        private StandaloneSessionMetadata _sessionMetadata;
        private StandaloneLaneLockMetadata _laneLockMetadata;
        private StandaloneShotMetadata _shotMetadata;
        private StandaloneQuestVideoEncoderBridge _videoEncoderBridge;
        private string _sessionId;
        private string _shotId;
        private ulong _nextFrameSeq;
        private long _firstFrameTimestampUs;
        private long _lastFrameTimestampUs;
        private bool _hasFrameRange;

        public bool IsCapturing => _artifactWriter != null;
        public string ActiveClipDirectory => _artifactWriter?.ClipDirectoryPath ?? string.Empty;

        public bool TryGetEncoderInputSurfaceRawObject(out IntPtr surfaceObject)
        {
            surfaceObject = IntPtr.Zero;
            if (_videoEncoderBridge == null)
            {
                return false;
            }

            surfaceObject = _videoEncoderBridge.GetInputSurfaceRawObject();
            return surfaceObject != IntPtr.Zero;
        }

        public bool TryBeginProofClip(string shotId, int preRollMs = 0, int postRollMs = 0, string triggerReason = "manual_proof_capture")
        {
            if (IsCapturing)
            {
                DebugLog("Proof clip already active.");
                return false;
            }

            if (cameraAccess == null || !cameraAccess.IsPlaying)
            {
                DebugLog("Cannot begin proof clip without an active passthrough camera.");
                return false;
            }

            _sessionId = Guid.NewGuid().ToString("N");
            _shotId = string.IsNullOrWhiteSpace(shotId) ? "proof-shot" : shotId.Trim();
            _nextFrameSeq = 0;
            _hasFrameRange = false;
            _firstFrameTimestampUs = 0;
            _lastFrameTimestampUs = 0;

            var actualResolution = cameraAccess.CurrentResolution;
            if (actualResolution.x <= 0 || actualResolution.y <= 0)
            {
                actualResolution = requestedResolution;
            }

            var intrinsics = cameraAccess.Intrinsics;
            _sessionMetadata = QuestCaptureMetadataBuilder.BuildSessionMetadata(
                _sessionId,
                SystemInfo.deviceName,
                cameraPosition.ToString(),
                requestedResolution,
                actualResolution,
                targetFps,
                targetFps,
                videoCodec,
                targetBitrateKbps,
                intrinsics);

            _laneLockMetadata = BuildLaneLockMetadata();
            _shotMetadata = new StandaloneShotMetadata
            {
                shotId = _shotId,
                preRollMs = Mathf.Max(0, preRollMs),
                postRollMs = Mathf.Max(0, postRollMs),
                triggerReason = string.IsNullOrWhiteSpace(triggerReason) ? "manual_proof_capture" : triggerReason,
                laneLockStateAtShotStart = laneLockState,
            };

            var outputRootPath = Path.Combine(Application.persistentDataPath, outputFolderName);
            _artifactWriter = new StandaloneLocalClipArtifactWriter(outputRootPath, _sessionId, _shotId);
            if (createEmptyVideoPlaceholder)
            {
                _artifactWriter.EnsureVideoPlaceholder();
            }

            if (startEncoderOnProofClip)
            {
                _videoEncoderBridge ??= new StandaloneQuestVideoEncoderBridge();
                var encoderStarted = _videoEncoderBridge.TryStartSession(
                    new StandaloneQuestVideoEncoderBridge.SessionConfig
                    {
                        width = actualResolution.x,
                        height = actualResolution.y,
                        fps = targetFps,
                        bitrateKbps = targetBitrateKbps,
                        iFrameIntervalSeconds = iFrameIntervalSeconds,
                    },
                    _artifactWriter.VideoPath,
                    out var encoderNote);

                DebugLog($"Encoder start: {(encoderStarted ? "ok" : "failed")} | {encoderNote}");
            }

            _artifactWriter.WriteSessionMetadata(_sessionMetadata);
            _artifactWriter.WriteLaneLockMetadata(_laneLockMetadata);
            _artifactWriter.WriteShotMetadata(_shotMetadata);
            _artifactWriter.WriteManifest(_sessionId, _shotId);

            DebugLog($"Proof clip started at {ActiveClipDirectory}");
            return true;
        }

        public bool TryAppendCurrentFrameMetadata(long ptsUs, bool isKeyframe)
        {
            if (!IsCapturing)
            {
                DebugLog("No active proof clip.");
                return false;
            }

            var actualResolution = cameraAccess != null ? cameraAccess.CurrentResolution : requestedResolution;
            if (actualResolution.x <= 0 || actualResolution.y <= 0)
            {
                actualResolution = requestedResolution;
            }

            if (!QuestCaptureMetadataBuilder.TryBuildFrameMetadata(
                    _nextFrameSeq,
                    ptsUs,
                    isKeyframe,
                    actualResolution.x,
                    actualResolution.y,
                    cameraAccess,
                    headTransform,
                    laneLockState,
                    out var frameMetadata,
                    allowSystemUtcFallback))
            {
                DebugLog("Failed to build frame metadata.");
                return false;
            }

            _artifactWriter.AppendFrameMetadata(frameMetadata);
            _nextFrameSeq++;

            if (!_hasFrameRange)
            {
                _firstFrameTimestampUs = frameMetadata.cameraTimestampUs;
                _hasFrameRange = true;
            }

            _lastFrameTimestampUs = frameMetadata.cameraTimestampUs;
            return true;
        }

        public bool TryFinalizeProofClip()
        {
            if (!IsCapturing)
            {
                DebugLog("No active proof clip to finalize.");
                return false;
            }

            if (_hasFrameRange)
            {
                _shotMetadata.shotStartTimeUs = _firstFrameTimestampUs;
                _shotMetadata.shotEndTimeUs = _lastFrameTimestampUs;
            }

            _laneLockMetadata = BuildLaneLockMetadata();

            _artifactWriter.WriteLaneLockMetadata(_laneLockMetadata);
            _artifactWriter.WriteShotMetadata(_shotMetadata);
            _artifactWriter.WriteManifest(_sessionId, _shotId);
            _artifactWriter.Dispose();

            if (startEncoderOnProofClip && _videoEncoderBridge != null)
            {
                var stopped = _videoEncoderBridge.TryStopSession(out var encoderNote);
                DebugLog($"Encoder stop: {(stopped ? "ok" : "failed")} | {encoderNote}");
            }

            DebugLog($"Proof clip finalized at {ActiveClipDirectory}");
            _artifactWriter = null;
            return true;
        }

        public void CancelProofClip()
        {
            if (!IsCapturing)
            {
                return;
            }

            if (startEncoderOnProofClip && _videoEncoderBridge != null)
            {
                _videoEncoderBridge.AbortSession();
            }

            _artifactWriter.Dispose();
            _artifactWriter = null;
            DebugLog("Proof clip canceled.");
        }

        private void OnDestroy()
        {
            _videoEncoderBridge?.Dispose();
            _videoEncoderBridge = null;
        }

        private StandaloneLaneLockMetadata BuildLaneLockMetadata()
        {
            return new StandaloneLaneLockMetadata
            {
                laneLockState = laneLockState,
                lockedAtUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                confidence = Mathf.Clamp01(laneLockConfidence),
                laneOriginWorld = laneOriginWorld,
                laneRotationWorld = laneRotationWorld,
                laneWidthMeters = laneWidthMeters,
                laneLengthMeters = laneLengthMeters,
            };
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestLocalProofCapture] {message}");
        }
    }
}
