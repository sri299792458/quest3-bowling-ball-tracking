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
        private StandaloneProofDiagnostics _proofDiagnostics;
        private StandaloneQuestVideoEncoderBridge _videoEncoderBridge;
        private StandaloneFrameMetadata _preparedFrameMetadata;
        private bool _hasPreparedFrameMetadata;
        private string _sessionId;
        private string _shotId;
        private ulong _nextFrameSeq;
        private long _firstFrameTimestampUs;
        private long _lastFrameTimestampUs;
        private long _lastCommittedPtsUs;
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
            _lastCommittedPtsUs = -1;
            _preparedFrameMetadata = null;
            _hasPreparedFrameMetadata = false;
            _proofDiagnostics = new StandaloneProofDiagnostics
            {
                beginRequested = true,
            };

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
            _proofDiagnostics.activeClipDirectory = _artifactWriter.ClipDirectoryPath;
            if (createEmptyVideoPlaceholder)
            {
                _artifactWriter.EnsureVideoPlaceholder();
            }

            if (startEncoderOnProofClip)
            {
                _videoEncoderBridge ??= new StandaloneQuestVideoEncoderBridge();
                _proofDiagnostics.encoderStartRequested = true;
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

                _proofDiagnostics.encoderStartSucceeded = encoderStarted;
                _proofDiagnostics.encoderStartNote = encoderNote ?? string.Empty;

                DebugLog($"Encoder start: {(encoderStarted ? "ok" : "failed")} | {encoderNote}");
            }

            _artifactWriter.WriteSessionMetadata(_sessionMetadata);
            _artifactWriter.WriteLaneLockMetadata(_laneLockMetadata);
            _artifactWriter.WriteShotMetadata(_shotMetadata);
            _artifactWriter.WriteManifest(_sessionId, _shotId);
            _proofDiagnostics.beginSucceeded = true;
            _proofDiagnostics.beginNote = "proof_clip_started";
            PersistProofDiagnostics();

            DebugLog($"Proof clip started at {ActiveClipDirectory}");
            return true;
        }

        public bool TryPrepareCurrentFrameMetadata(out long ptsUs, out bool isKeyframe, out string note)
        {
            ptsUs = -1L;
            isKeyframe = false;
            note = "proof_clip_inactive";

            if (!IsCapturing)
            {
                return false;
            }

            var actualResolution = cameraAccess != null ? cameraAccess.CurrentResolution : requestedResolution;
            if (actualResolution.x <= 0 || actualResolution.y <= 0)
            {
                actualResolution = requestedResolution;
            }

            if (!QuestCaptureMetadataBuilder.TrySnapshotFrameInputs(
                    cameraAccess,
                    headTransform,
                    allowSystemUtcFallback,
                    out var cameraTimestampUs,
                    out var timestampSource,
                    out var cameraPose,
                    out var headPose))
            {
                note = "frame_inputs_unavailable";
                return false;
            }

            if (_hasFrameRange)
            {
                ptsUs = Math.Max(_lastCommittedPtsUs + 1L, cameraTimestampUs - _firstFrameTimestampUs);
            }
            else
            {
                ptsUs = 0L;
            }

            isKeyframe = _nextFrameSeq == 0;
            _preparedFrameMetadata = new StandaloneFrameMetadata
            {
                frameSeq = _nextFrameSeq,
                cameraTimestampUs = cameraTimestampUs,
                ptsUs = ptsUs,
                isKeyframe = isKeyframe,
                width = actualResolution.x,
                height = actualResolution.y,
                timestampSource = timestampSource,
                cameraPosition = cameraPose.position,
                cameraRotation = cameraPose.rotation,
                headPosition = headPose.position,
                headRotation = headPose.rotation,
                laneLockState = laneLockState,
            };
            _hasPreparedFrameMetadata = true;
            note = "frame_metadata_prepared";
            return true;
        }

        public bool CommitPreparedFrameMetadata()
        {
            if (!_hasPreparedFrameMetadata || _preparedFrameMetadata == null || !IsCapturing)
            {
                return false;
            }

            _artifactWriter.AppendFrameMetadata(_preparedFrameMetadata);

            if (!_hasFrameRange)
            {
                _firstFrameTimestampUs = _preparedFrameMetadata.cameraTimestampUs;
                _hasFrameRange = true;
            }

            _lastFrameTimestampUs = _preparedFrameMetadata.cameraTimestampUs;
            _lastCommittedPtsUs = _preparedFrameMetadata.ptsUs;
            _nextFrameSeq++;
            _preparedFrameMetadata = null;
            _hasPreparedFrameMetadata = false;
            return true;
        }

        public void DiscardPreparedFrameMetadata()
        {
            _preparedFrameMetadata = null;
            _hasPreparedFrameMetadata = false;
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
            _proofDiagnostics.finalizeRequested = true;
            _proofDiagnostics.finalizeNote = "finalizing";

            if (startEncoderOnProofClip && _videoEncoderBridge != null)
            {
                _proofDiagnostics.encoderStopRequested = true;
                var stopped = _videoEncoderBridge.TryStopSession(out var encoderNote);
                _proofDiagnostics.encoderStopSucceeded = stopped;
                _proofDiagnostics.encoderStopNote = encoderNote ?? string.Empty;
                DebugLog($"Encoder stop: {(stopped ? "ok" : "failed")} | {encoderNote}");
            }

            _proofDiagnostics.finalizeSucceeded = true;
            _proofDiagnostics.finalizeNote = "proof_clip_finalized";
            PersistProofDiagnostics();
            DiscardPreparedFrameMetadata();
            _artifactWriter.Dispose();

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

            DiscardPreparedFrameMetadata();
            _artifactWriter.Dispose();
            _artifactWriter = null;
            DebugLog("Proof clip canceled.");
        }

        public void ReportRenderAttempt(bool success, string note)
        {
            if (!IsCapturing || _proofDiagnostics == null)
            {
                return;
            }

            _proofDiagnostics.renderAttemptCount++;
            if (success)
            {
                _proofDiagnostics.renderSuccessCount++;
            }
            else
            {
                _proofDiagnostics.renderSkipCount++;
            }

            _proofDiagnostics.lastRenderNote = note ?? string.Empty;
            PersistProofDiagnostics();
        }

        public void ReportEncoderSurfaceAvailability(bool ready, string note)
        {
            if (!IsCapturing || _proofDiagnostics == null)
            {
                return;
            }

            if (ready)
            {
                _proofDiagnostics.encoderSurfaceReadyCount++;
            }
            else
            {
                _proofDiagnostics.encoderSurfaceMissingCount++;
            }

            _proofDiagnostics.lastEncoderSurfaceNote = note ?? string.Empty;
            PersistProofDiagnostics();
        }

        public void ReportSurfaceBind(bool success, string note)
        {
            if (!IsCapturing || _proofDiagnostics == null)
            {
                return;
            }

            _proofDiagnostics.surfaceBindAttemptCount++;
            if (success)
            {
                _proofDiagnostics.surfaceBindSuccessCount++;
            }
            else
            {
                _proofDiagnostics.surfaceBindFailureCount++;
            }

            _proofDiagnostics.lastSurfaceBindNote = note ?? string.Empty;
            PersistProofDiagnostics();
        }

        public void ReportBlitIssued()
        {
            if (!IsCapturing || _proofDiagnostics == null)
            {
                return;
            }

            _proofDiagnostics.blitIssuedCount++;
            PersistProofDiagnostics();
        }

        public void ReportFrameMetadataAppend(bool success, long ptsUs, bool isKeyframe, string note)
        {
            if (!IsCapturing || _proofDiagnostics == null)
            {
                return;
            }

            if (success)
            {
                _proofDiagnostics.frameMetadataAppendSuccessCount++;
            }
            else
            {
                _proofDiagnostics.frameMetadataAppendFailureCount++;
            }

            _proofDiagnostics.lastPtsUs = ptsUs;
            _proofDiagnostics.lastIsKeyframe = isKeyframe;
            _proofDiagnostics.lastFrameAppendNote = note ?? string.Empty;
            PersistProofDiagnostics();
        }

        public string GetEncoderStatusJson()
        {
            return _videoEncoderBridge?.GetStatusJson() ?? "{\"status\":\"bridge_missing\"}";
        }

        private void OnDestroy()
        {
            DiscardPreparedFrameMetadata();
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

        private void PersistProofDiagnostics()
        {
            if (_artifactWriter == null || _proofDiagnostics == null)
            {
                return;
            }

            _artifactWriter.WriteProofDiagnostics(_proofDiagnostics);
        }
    }
}
