using System;
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
        [SerializeField] private bool abortSessionOnApplicationPause = false;
        [SerializeField] private string liveStreamHost = "";
        [SerializeField] private int liveMediaPort = 8766;

        [Header("Media Watchdog")]
        [SerializeField] private float mediaWatchdogIntervalSeconds = 0.5f;
        [SerializeField] private float mediaReconnectIntervalSeconds = 1.0f;
        [SerializeField] private float mediaNoProgressTimeoutSeconds = 2.0f;

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging = true;

        private Coroutine _startupCoroutine;
        private bool _sessionActive;
        private bool _isQuitting;
        private float _nextMediaWatchdogAt;
        private float _nextMediaReconnectAt;
        private float _lastMediaProgressAt;
        private long _lastLiveMediaSampleCount = -1L;

#if UNITY_EDITOR
        private bool _recordedExportSessionActive;
        private string _recordedExportSessionId = string.Empty;
        private string _recordedExportStreamId = string.Empty;
        private bool _recordedExportMediaReady;
        private string _recordedExportMediaNote = "recorded_export_media_ready";
#endif

        public bool IsSessionActive
        {
            get
            {
#if UNITY_EDITOR
                if (_recordedExportSessionActive)
                {
                    return true;
                }
#endif
                return _sessionActive && proofCapture != null && proofCapture.IsCapturing;
            }
        }

        public string ActiveSessionId
        {
            get
            {
#if UNITY_EDITOR
                if (_recordedExportSessionActive)
                {
                    return _recordedExportSessionId;
                }
#endif
                return proofCapture != null ? proofCapture.ActiveSessionId : string.Empty;
            }
        }

        public string ActiveStreamId
        {
            get
            {
#if UNITY_EDITOR
                if (_recordedExportSessionActive)
                {
                    return _recordedExportStreamId;
                }
#endif
                return proofCapture != null ? proofCapture.ActiveStreamId : string.Empty;
            }
        }

        public bool TryGetLiveMediaReadiness(out string note)
        {
            note = "live_media_not_ready";
#if UNITY_EDITOR
            if (_recordedExportSessionActive)
            {
                note = string.IsNullOrWhiteSpace(_recordedExportMediaNote)
                    ? "recorded_export_media_ready"
                    : _recordedExportMediaNote;
                return _recordedExportMediaReady;
            }
#endif
            if (!IsSessionActive)
            {
                note = "session_not_active";
                return false;
            }

            if (!enableLiveStreaming)
            {
                note = "live_streaming_disabled";
                return false;
            }

            if (!TryReadEncoderStatus(out var status))
            {
                note = "media_status_unavailable";
                return false;
            }

            if (!status.live_stream_connected)
            {
                note = string.IsNullOrWhiteSpace(status.live_stream_last_error)
                    ? "media_stream_disconnected"
                    : "media_stream_disconnected:" + status.live_stream_last_error;
                return false;
            }

            if (status.live_stream_sent_sample_count <= 0)
            {
                note = "media_stream_waiting_for_first_frame";
                return false;
            }

            var noProgressTimeout = Mathf.Max(0.5f, mediaNoProgressTimeoutSeconds);
            if (_lastMediaProgressAt > 0.0f && Time.realtimeSinceStartup - _lastMediaProgressAt >= noProgressTimeout)
            {
                note = "media_stream_no_recent_frames";
                return false;
            }

            note = "media_stream_ready";
            return true;
        }

#if UNITY_EDITOR
        public void InjectRecordedExportSessionState(
            string sessionId,
            string streamId,
            bool mediaReady,
            string mediaNote)
        {
            _recordedExportSessionActive = true;
            _recordedExportSessionId = string.IsNullOrWhiteSpace(sessionId) ? "recorded-session" : sessionId.Trim();
            _recordedExportStreamId = string.IsNullOrWhiteSpace(streamId) ? "session-stream" : streamId.Trim();
            _recordedExportMediaReady = mediaReady;
            _recordedExportMediaNote = string.IsNullOrWhiteSpace(mediaNote)
                ? "recorded_export_media_ready"
                : mediaNote.Trim();
        }
#endif

        [Serializable]
        private sealed class EncoderStatusSnapshot
        {
            public string status;
            public bool live_stream_connected;
            public long live_stream_sent_sample_count;
            public long live_stream_queued_packet_count;
            public long live_stream_dropped_packet_count;
            public string live_stream_last_error;
            public string last_error;
        }

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
                if (abortSessionOnApplicationPause)
                {
                    AbortSession("application_pause");
                }
                else
                {
                    DebugLog("Application pause observed; keeping live session active.");
                }
                return;
            }

            if (_isQuitting || !autoStartSession || _sessionActive || _startupCoroutine != null)
            {
                return;
            }

            _startupCoroutine = StartCoroutine(BeginSessionWhenReady());
        }

        private void Update()
        {
            RunMediaWatchdog();
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
                    proofCapture.CancelProofClip("live_media_start_failed:" + mediaNote);
                    note = $"live_media_start_failed:{mediaNote}";
                    return false;
                }

                ResetMediaWatchdog();

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
                        proofCapture.CancelProofClip("live_metadata_start_failed:" + metadataNote);
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
                        proofCapture.CancelProofClip("live_result_start_failed:" + resultNote);
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
            ResetMediaWatchdog();
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
                proofCapture.CancelProofClip(string.IsNullOrWhiteSpace(reason) ? "session_abort" : reason);
            }

            if (_sessionActive)
            {
                DebugLog("Session aborted: " + (string.IsNullOrWhiteSpace(reason) ? "unspecified" : reason));
            }

            _sessionActive = false;
            ResetMediaWatchdog();
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

        private void RunMediaWatchdog()
        {
            if (!_sessionActive || !enableLiveStreaming || proofCapture == null || !proofCapture.IsCapturing)
            {
                return;
            }

            var now = Time.realtimeSinceStartup;
            if (now < _nextMediaWatchdogAt)
            {
                return;
            }

            _nextMediaWatchdogAt = now + Mathf.Max(0.1f, mediaWatchdogIntervalSeconds);
            if (!TryReadEncoderStatus(out var status))
            {
                return;
            }

            var sampleCount = status.live_stream_sent_sample_count;
            if (status.live_stream_connected && sampleCount != _lastLiveMediaSampleCount)
            {
                _lastLiveMediaSampleCount = sampleCount;
                _lastMediaProgressAt = now;
                return;
            }

            if (_lastMediaProgressAt <= 0.0f)
            {
                _lastMediaProgressAt = now;
                return;
            }

            var noProgress = status.live_stream_connected &&
                now - _lastMediaProgressAt >= Mathf.Max(0.5f, mediaNoProgressTimeoutSeconds);
            var disconnected = !status.live_stream_connected;
            if (!disconnected && !noProgress)
            {
                return;
            }

            if (now < _nextMediaReconnectAt)
            {
                return;
            }

            _nextMediaReconnectAt = now + Mathf.Max(0.25f, mediaReconnectIntervalSeconds);
            var reason = disconnected ? "disconnected" : "no_progress";
            var error = string.IsNullOrWhiteSpace(status.live_stream_last_error)
                ? status.last_error
                : status.live_stream_last_error;
            var reconnected = proofCapture.TryStartLiveMediaStream(liveStreamHost, liveMediaPort, out var note);
            DebugLog(
                $"Media watchdog reconnect {reason}: {(reconnected ? "ok" : "failed")} | {note} | " +
                $"samples={sampleCount} queued={status.live_stream_queued_packet_count} " +
                $"dropped={status.live_stream_dropped_packet_count} error={error}");
            if (reconnected)
            {
                _lastLiveMediaSampleCount = -1L;
                _lastMediaProgressAt = now;
            }
        }

        private bool TryReadEncoderStatus(out EncoderStatusSnapshot status)
        {
            status = null;
            if (proofCapture == null)
            {
                return false;
            }

            var json = proofCapture.GetEncoderStatusJson();
            if (string.IsNullOrWhiteSpace(json))
            {
                return false;
            }

            try
            {
                status = JsonUtility.FromJson<EncoderStatusSnapshot>(json);
            }
            catch (Exception ex)
            {
                DebugLog("Failed to parse encoder status: " + ex.Message + " | " + json);
                return false;
            }

            return status != null;
        }

        private void ResetMediaWatchdog()
        {
            var now = Time.realtimeSinceStartup;
            _nextMediaWatchdogAt = now + Mathf.Max(0.1f, mediaWatchdogIntervalSeconds);
            _nextMediaReconnectAt = 0.0f;
            _lastMediaProgressAt = now;
            _lastLiveMediaSampleCount = -1L;
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
