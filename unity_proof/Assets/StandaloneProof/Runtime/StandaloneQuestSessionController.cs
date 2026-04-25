using System.Collections;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestSessionController : MonoBehaviour
    {
        [Header("Session Stream")]
        [SerializeField] private StandaloneQuestLocalProofCapture proofCapture;
        [SerializeField] private StandaloneQuestLiveMetadataSender liveMetadataSender;
        [SerializeField] private bool autoStartSession = true;
        [SerializeField] private string streamId = "session-stream";

        [Header("Startup Timing")]
        [SerializeField] private float startupDelaySeconds = 2.0f;
        [SerializeField] private float maxBeginWaitSeconds = 20.0f;
        [SerializeField] private float beginRetryIntervalSeconds = 0.25f;

        [Header("Live Transport")]
        [SerializeField] private bool enableLiveStreaming = true;
        [SerializeField] private string liveStreamHost = "10.235.26.83";
        [SerializeField] private int liveMediaPort = 8766;

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging = true;

        private Coroutine _startupCoroutine;
        private bool _sessionActive;

        public bool IsSessionActive => _sessionActive && proofCapture != null && proofCapture.IsCapturing;
        public string ActiveSessionId => proofCapture != null ? proofCapture.ActiveSessionId : string.Empty;
        public string ActiveStreamId => proofCapture != null ? proofCapture.ActiveStreamId : string.Empty;

        private void OnEnable()
        {
            if (!autoStartSession || _startupCoroutine != null)
            {
                return;
            }

            _startupCoroutine = StartCoroutine(BeginSessionWhenReady());
        }

        private void OnDisable()
        {
            if (_startupCoroutine != null)
            {
                StopCoroutine(_startupCoroutine);
                _startupCoroutine = null;
            }
        }

        private void OnDestroy()
        {
            TryEndSession("destroyed", out _);
        }

        private void OnApplicationQuit()
        {
            TryEndSession("application_quit", out _);
        }

        public bool TryBeginSession(out string note)
        {
            note = "session_start_failed";

            if (_sessionActive)
            {
                note = "session_already_active";
                return false;
            }

            if (proofCapture == null)
            {
                note = "proof_capture_missing";
                return false;
            }

            var started = proofCapture.TryBeginSessionStream(
                string.IsNullOrWhiteSpace(streamId) ? "session-stream" : streamId);
            if (!started)
            {
                note = "capture_start_failed";
                return false;
            }

            if (enableLiveStreaming)
            {
                var mediaStarted = proofCapture.TryStartLiveMediaStream(liveStreamHost, liveMediaPort, out var mediaNote);
                DebugLog($"Begin live media stream: {(mediaStarted ? "ok" : "failed")} | {mediaNote}");
                if (!mediaStarted)
                {
                    proofCapture.CancelProofClip();
                    note = $"live_media_start_failed:{mediaNote}";
                    return false;
                }

                if (liveMetadataSender != null && liveMetadataSender.EnabledForAutoRun)
                {
                    var metadataStarted = liveMetadataSender.TryBeginSession(
                        proofCapture.ActiveSessionId,
                        proofCapture.ActiveStreamId,
                        proofCapture.CurrentSessionMetadata,
                        proofCapture.CurrentLaneLockMetadata,
                        proofCapture.CurrentShotMetadata,
                        out var metadataNote);
                    DebugLog($"Begin live metadata stream: {(metadataStarted ? "ok" : "failed")} | {metadataNote}");
                    if (!metadataStarted)
                    {
                        proofCapture.CancelProofClip();
                        note = $"live_metadata_start_failed:{metadataNote}";
                        return false;
                    }
                }
            }

            _sessionActive = true;
            note = "session_started";
            DebugLog($"Session stream started. sessionId={ActiveSessionId} streamId={ActiveStreamId}");
            return true;
        }

        public bool TryEndSession(string reason, out string note)
        {
            note = "session_end_failed";
            if (!_sessionActive || proofCapture == null)
            {
                note = "session_not_active";
                return false;
            }

            var sessionId = proofCapture.ActiveSessionId;
            var activeStreamId = proofCapture.ActiveStreamId;

            if (liveMetadataSender != null && liveMetadataSender.EnabledForAutoRun)
            {
                var metadataEnded = liveMetadataSender.TryEndSession(
                    sessionId,
                    activeStreamId,
                    string.IsNullOrWhiteSpace(reason) ? "session_complete" : reason,
                    out var metadataNote);
                DebugLog($"End live metadata stream: {(metadataEnded ? "ok" : "failed")} | {metadataNote}");
            }

            var finalized = proofCapture.TryFinalizeSessionStream();
            _sessionActive = false;
            note = finalized ? "session_finalized" : "session_finalize_failed";
            DebugLog($"Finalize session stream: {(finalized ? "ok" : "failed")}");
            return finalized;
        }

        public bool TrySendShotBoundary(string boundaryType, string reason, out string note)
        {
            note = "shot_boundary_failed";
            if (!_sessionActive || proofCapture == null)
            {
                note = "session_not_active";
                return false;
            }

            if (liveMetadataSender == null || !liveMetadataSender.EnabledForAutoRun)
            {
                note = "live_metadata_sender_missing";
                return false;
            }

            var frameMetadata = proofCapture.LastCommittedFrameMetadata;
            if (frameMetadata == null)
            {
                note = "no_committed_frame_metadata";
                return false;
            }

            return liveMetadataSender.TrySendShotBoundary(
                proofCapture.ActiveSessionId,
                proofCapture.ActiveStreamId,
                boundaryType,
                frameMetadata.frameSeq,
                frameMetadata.cameraTimestampUs,
                frameMetadata.ptsUs,
                reason,
                out note);
        }

        private IEnumerator BeginSessionWhenReady()
        {
            yield return new WaitForSeconds(startupDelaySeconds);

            var beginDeadline = Time.realtimeSinceStartup + Mathf.Max(0.0f, maxBeginWaitSeconds);
            var retryInterval = Mathf.Max(0.05f, beginRetryIntervalSeconds);
            var started = false;
            while (!started && Time.realtimeSinceStartup <= beginDeadline)
            {
                started = TryBeginSession(out var beginNote);
                DebugLog($"Begin session attempt: {(started ? "ok" : "failed")} | {beginNote}");
                if (started)
                {
                    break;
                }

                yield return new WaitForSeconds(retryInterval);
            }

            if (!started)
            {
                DebugLog("Giving up on session start because the camera/session stream never became ready.");
            }

            _startupCoroutine = null;
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestSessionController] {message}");
        }
    }
}
