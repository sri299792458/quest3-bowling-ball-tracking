using System.Collections;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestSessionController : MonoBehaviour
    {
        [Header("Session Stream")]
        [SerializeField] private StandaloneQuestLocalProofCapture proofCapture;
        [SerializeField] private StandaloneQuestLiveMetadataSender liveMetadataSender;
        [SerializeField] private StandaloneQuestLiveResultReceiver liveResultReceiver;
        [SerializeField] private StandaloneQuestLaptopDiscovery laptopDiscovery;
        [SerializeField] private bool autoStartSession = true;
        [SerializeField] private string streamId = "session-stream";

        [Header("Startup Timing")]
        [SerializeField] private float startupDelaySeconds = 2.0f;
        [SerializeField] private float maxBeginWaitSeconds = 20.0f;
        [SerializeField] private float beginRetryIntervalSeconds = 0.25f;

        [Header("Live Transport")]
        [SerializeField] private bool enableLiveStreaming = true;
        [SerializeField] private bool requireLaptopDiscovery = true;
        [SerializeField] private string liveStreamHost = "";
        [SerializeField] private int liveMediaPort = 8766;

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging = true;

        private Coroutine _startupCoroutine;
        private bool _sessionActive;
        private bool _isQuitting;

        public bool IsSessionActive => _sessionActive && proofCapture != null && proofCapture.IsCapturing;
        public string ActiveSessionId => proofCapture != null ? proofCapture.ActiveSessionId : string.Empty;
        public string ActiveStreamId => proofCapture != null ? proofCapture.ActiveStreamId : string.Empty;

        private void OnEnable()
        {
            SubscribeToMetadataFailures();

            if (!autoStartSession || _startupCoroutine != null)
            {
                return;
            }

            _startupCoroutine = StartCoroutine(BeginSessionWhenReady());
        }

        private void OnDisable()
        {
            CancelStartupCoroutine();
            AbortSession("disabled");
            UnsubscribeFromMetadataFailures();
        }

        private void OnDestroy()
        {
            AbortSession("destroyed");
            UnsubscribeFromMetadataFailures();
        }

        private void OnApplicationQuit()
        {
            _isQuitting = true;
            AbortSession("application_quit");
        }

        private void OnApplicationPause(bool pauseStatus)
        {
            if (pauseStatus)
            {
                AbortSession("application_pause");
                return;
            }

            if (_isQuitting || !autoStartSession || _sessionActive || _startupCoroutine != null)
            {
                return;
            }

            _startupCoroutine = StartCoroutine(BeginSessionWhenReady());
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

            if (enableLiveStreaming && (string.IsNullOrWhiteSpace(liveStreamHost) || liveMediaPort <= 0))
            {
                note = "live_stream_target_missing";
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

                if (liveResultReceiver != null && liveResultReceiver.EnabledForAutoRun)
                {
                    var resultStarted = liveResultReceiver.TryBeginResultStream(
                        proofCapture.ActiveSessionId,
                        proofCapture.ActiveStreamId,
                        out var resultNote);
                    DebugLog($"Begin live result stream: {(resultStarted ? "ok" : "failed")} | {resultNote}");
                    if (!resultStarted)
                    {
                        proofCapture.CancelProofClip();
                        note = $"live_result_start_failed:{resultNote}";
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

            if (liveResultReceiver != null && liveResultReceiver.EnabledForAutoRun)
            {
                liveResultReceiver.StopResultStream();
                DebugLog("End live result stream: ok");
            }

            var finalized = proofCapture.TryFinalizeSessionStream();
            _sessionActive = false;
            note = finalized ? "session_finalized" : "session_finalize_failed";
            DebugLog($"Finalize session stream: {(finalized ? "ok" : "failed")}");
            return finalized;
        }

        public void AbortSession(string reason)
        {
            CancelStartupCoroutine();

            if (liveMetadataSender != null && liveMetadataSender.EnabledForAutoRun)
            {
                liveMetadataSender.AbortSession();
            }

            if (liveResultReceiver != null && liveResultReceiver.EnabledForAutoRun)
            {
                liveResultReceiver.StopResultStream();
            }

            if (proofCapture != null && proofCapture.IsCapturing)
            {
                proofCapture.CancelProofClip();
            }

            if (_sessionActive)
            {
                DebugLog("Session aborted: " + (string.IsNullOrWhiteSpace(reason) ? "unspecified" : reason));
            }

            _sessionActive = false;
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

            if (enableLiveStreaming && requireLaptopDiscovery)
            {
                if (laptopDiscovery == null || !laptopDiscovery.EnabledForAutoRun)
                {
                    DebugLog("Laptop discovery required but discovery component is missing or disabled.");
                    _startupCoroutine = null;
                    yield break;
                }

                var discoveryComplete = false;
                var discoverySucceeded = false;
                StandaloneQuestLaptopEndpoint endpoint = default;
                string discoveryNote = null;
                yield return laptopDiscovery.Discover((success, resolvedEndpoint, note) =>
                {
                    discoverySucceeded = success;
                    endpoint = resolvedEndpoint;
                    discoveryNote = note;
                    discoveryComplete = true;
                });

                if (!discoveryComplete || !discoverySucceeded || !endpoint.IsValid)
                {
                    DebugLog("Laptop discovery failed; live session will not start. " + (discoveryNote ?? "no_discovery_note"));
                    _startupCoroutine = null;
                    yield break;
                }

                ApplyLaptopEndpoint(endpoint);
            }

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

        private void ApplyLaptopEndpoint(StandaloneQuestLaptopEndpoint endpoint)
        {
            if (!endpoint.IsValid)
            {
                return;
            }

            liveStreamHost = endpoint.Host;
            liveMediaPort = endpoint.MediaPort;
            liveMetadataSender?.SetEndpoint(endpoint.Host, endpoint.MetadataPort);
            liveResultReceiver?.SetEndpoint(endpoint.Host, endpoint.ResultPort);
            DebugLog("Using laptop endpoint: " + endpoint);
        }

        private void CancelStartupCoroutine()
        {
            if (_startupCoroutine == null)
            {
                return;
            }

            StopCoroutine(_startupCoroutine);
            _startupCoroutine = null;
        }

        private void SubscribeToMetadataFailures()
        {
            if (liveMetadataSender == null)
            {
                return;
            }

            liveMetadataSender.MetadataStreamFailed -= OnMetadataStreamFailed;
            liveMetadataSender.MetadataStreamFailed += OnMetadataStreamFailed;
        }

        private void UnsubscribeFromMetadataFailures()
        {
            if (liveMetadataSender == null)
            {
                return;
            }

            liveMetadataSender.MetadataStreamFailed -= OnMetadataStreamFailed;
        }

        private void OnMetadataStreamFailed(string reason)
        {
            if (!_sessionActive)
            {
                return;
            }

            var failureReason = string.IsNullOrWhiteSpace(reason) ? "metadata_stream_failed" : reason;
            DebugLog("Aborting live session because metadata stream failed: " + failureReason);
            AbortSession("metadata_stream_failed:" + failureReason);
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
