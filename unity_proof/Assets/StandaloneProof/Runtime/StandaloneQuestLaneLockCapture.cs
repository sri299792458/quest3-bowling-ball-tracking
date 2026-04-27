using System;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public enum StandaloneLaneLockRequestEventKind
    {
        Started,
        Sent,
        Failed,
    }

    public readonly struct StandaloneLaneLockRequestEvent
    {
        public StandaloneLaneLockRequestEvent(
            StandaloneLaneLockRequestEventKind kind,
            string requestId,
            string note,
            float realtimeSeconds)
        {
            Kind = kind;
            RequestId = requestId ?? string.Empty;
            Note = note ?? string.Empty;
            RealtimeSeconds = realtimeSeconds;
        }

        public StandaloneLaneLockRequestEventKind Kind { get; }
        public string RequestId { get; }
        public string Note { get; }
        public float RealtimeSeconds { get; }
    }

    public sealed class StandaloneQuestLaneLockCapture : MonoBehaviour
    {
        [Header("Lane Lock Stream Input")]
        [SerializeField] private StandaloneQuestLocalProofCapture proofCapture;
        [SerializeField] private StandaloneQuestLiveMetadataSender liveMetadataSender;
        [SerializeField] private StandaloneQuestFloorPlaneSource floorPlaneSource;
        [SerializeField] private float laneWidthMeters = 1.0541f;
        [SerializeField] private float laneLengthMeters = 18.288f;

        [Header("Capture Window")]
        [SerializeField] private int targetFrameCount = 24;
        [SerializeField] private int minimumFrameCount = 12;
        [SerializeField] private float maxCaptureDurationSeconds = 1.0f;

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging;

        private bool _requestActive;
        private string _requestId;
        private float _requestStartedRealtime;
        private int _capturedFrameCount;
        private ulong _frameSeqStart;
        private ulong _frameSeqEnd;
        private string _lastCompletionNote;
        private bool _hasFoulLineSelection;
        private Vector2 _leftFoulLinePointNorm;
        private Vector2 _rightFoulLinePointNorm;
        private ulong _selectionFrameSeq;

        public bool IsRequestActive => _requestActive;
        public string LastCompletionNote => _lastCompletionNote ?? string.Empty;
        public bool HasFoulLineSelection => _hasFoulLineSelection;
        public event Action<StandaloneLaneLockRequestEvent> RequestEvent;

        private void OnEnable()
        {
            SubscribeToProofCapture();
        }

        private void OnDisable()
        {
            UnsubscribeFromProofCapture();
        }

        private void Update()
        {
            if (!_requestActive)
            {
                return;
            }

            if (Time.realtimeSinceStartup - _requestStartedRealtime < Mathf.Max(0.1f, maxCaptureDurationSeconds))
            {
                return;
            }

            FinalizeActiveRequest("timeout_window_complete");
        }

        public void RequestLaneLockNow()
        {
            if (!TryBeginLaneLockRequest(out var note))
            {
                DebugLog($"Lane lock request did not start: {note}");
            }
        }

        public bool TrySetFoulLineSelection(Vector2 leftFoulLinePointNorm, Vector2 rightFoulLinePointNorm, out string note)
        {
            note = "foul_line_selection_failed";

            if (!IsNormalizedPoint(leftFoulLinePointNorm) || !IsNormalizedPoint(rightFoulLinePointNorm))
            {
                note = "foul_line_selection_out_of_range";
                return false;
            }

            if (leftFoulLinePointNorm.x >= rightFoulLinePointNorm.x)
            {
                note = "foul_line_selection_order_invalid";
                return false;
            }

            var frameMetadata = proofCapture != null ? proofCapture.LastCommittedFrameMetadata : null;
            if (frameMetadata == null)
            {
                note = "foul_line_selection_frame_missing";
                return false;
            }

            _leftFoulLinePointNorm = leftFoulLinePointNorm;
            _rightFoulLinePointNorm = rightFoulLinePointNorm;
            _selectionFrameSeq = frameMetadata.frameSeq;
            _hasFoulLineSelection = true;
            _lastCompletionNote = "foul_line_selection_ready";
            note = "foul_line_selection_ready";
            return true;
        }

        public void ClearFoulLineSelection()
        {
            _hasFoulLineSelection = false;
            _leftFoulLinePointNorm = Vector2.zero;
            _rightFoulLinePointNorm = Vector2.zero;
            _selectionFrameSeq = 0UL;
        }

        public bool TryBeginLaneLockRequest(out string note)
        {
            note = "lane_lock_request_failed";

            if (_requestActive)
            {
                note = "lane_lock_request_already_active";
                _lastCompletionNote = note;
                EmitRequestEvent(StandaloneLaneLockRequestEventKind.Failed, string.Empty, note);
                return false;
            }

            if (proofCapture == null)
            {
                note = "proof_capture_missing";
                _lastCompletionNote = note;
                EmitRequestEvent(StandaloneLaneLockRequestEventKind.Failed, string.Empty, note);
                return false;
            }

            if (!proofCapture.IsCapturing)
            {
                note = "session_stream_not_active";
                _lastCompletionNote = note;
                EmitRequestEvent(StandaloneLaneLockRequestEventKind.Failed, string.Empty, note);
                return false;
            }

            if (proofCapture.CurrentSessionMetadata == null)
            {
                note = "session_metadata_missing";
                _lastCompletionNote = note;
                EmitRequestEvent(StandaloneLaneLockRequestEventKind.Failed, string.Empty, note);
                return false;
            }

            if (liveMetadataSender == null || !liveMetadataSender.EnabledForAutoRun)
            {
                note = "live_metadata_sender_missing";
                _lastCompletionNote = note;
                EmitRequestEvent(StandaloneLaneLockRequestEventKind.Failed, string.Empty, note);
                return false;
            }

            if (floorPlaneSource == null)
            {
                note = "floor_plane_source_missing";
                _lastCompletionNote = note;
                EmitRequestEvent(StandaloneLaneLockRequestEventKind.Failed, string.Empty, note);
                return false;
            }

            if (!floorPlaneSource.TryGetFloorPlane(out _, out _, out var floorNote))
            {
                note = $"floor_plane_unavailable:{floorNote}";
                _lastCompletionNote = note;
                EmitRequestEvent(StandaloneLaneLockRequestEventKind.Failed, string.Empty, note);
                return false;
            }

            if (!_hasFoulLineSelection)
            {
                note = "foul_line_selection_missing";
                _lastCompletionNote = note;
                EmitRequestEvent(StandaloneLaneLockRequestEventKind.Failed, string.Empty, note);
                return false;
            }

            ResetActiveRequestState();
            _requestActive = true;
            _requestId = Guid.NewGuid().ToString("N");
            _requestStartedRealtime = Time.realtimeSinceStartup;
            _frameSeqStart = _selectionFrameSeq;
            _frameSeqEnd = _selectionFrameSeq;
            _capturedFrameCount = 1;
            _lastCompletionNote = "lane_lock_request_started";
            note = $"lane_lock_request_started:{_requestId}";
            DebugLog($"Lane lock request started. requestId={_requestId}");
            EmitRequestEvent(StandaloneLaneLockRequestEventKind.Started, _requestId, note);
            return true;
        }

        private void SubscribeToProofCapture()
        {
            if (proofCapture == null)
            {
                return;
            }

            proofCapture.FrameMetadataCommitted -= OnFrameMetadataCommitted;
            proofCapture.FrameMetadataCommitted += OnFrameMetadataCommitted;
        }

        private void UnsubscribeFromProofCapture()
        {
            if (proofCapture == null)
            {
                return;
            }

            proofCapture.FrameMetadataCommitted -= OnFrameMetadataCommitted;
        }

        private void OnFrameMetadataCommitted(StandaloneFrameMetadata frameMetadata)
        {
            if (!_requestActive || frameMetadata == null)
            {
                return;
            }

            if (_capturedFrameCount == 0)
            {
                _frameSeqStart = frameMetadata.frameSeq;
            }

            _capturedFrameCount++;
            _frameSeqEnd = frameMetadata.frameSeq;

            if (_capturedFrameCount >= Mathf.Max(1, targetFrameCount))
            {
                FinalizeActiveRequest("target_frame_count_reached");
            }
        }

        private void FinalizeActiveRequest(string completionReason)
        {
            if (!_requestActive)
            {
                return;
            }

            var currentSessionMetadata = proofCapture != null ? proofCapture.CurrentSessionMetadata : null;
            var sessionId = proofCapture != null ? proofCapture.ActiveSessionId : string.Empty;
            var streamId = proofCapture != null ? proofCapture.ActiveStreamId : string.Empty;
            var captureDurationSeconds = Mathf.Max(0.0f, Time.realtimeSinceStartup - _requestStartedRealtime);

            if (_capturedFrameCount < Mathf.Max(1, minimumFrameCount) || currentSessionMetadata == null)
            {
                var failedRequestId = _requestId ?? string.Empty;
                _lastCompletionNote = _capturedFrameCount <= 0
                    ? "lane_lock_request_failed_no_frames"
                    : "lane_lock_request_failed_low_frame_count";
                DebugLog($"Lane lock request dropped. reason={_lastCompletionNote} frames={_capturedFrameCount}");
                EmitRequestEvent(StandaloneLaneLockRequestEventKind.Failed, failedRequestId, _lastCompletionNote);
                ResetActiveRequestState();
                return;
            }

            if (!floorPlaneSource.TryGetFloorPlane(out var floorPointWorld, out var floorNormalWorld, out var floorNote))
            {
                var failedRequestId = _requestId ?? string.Empty;
                _lastCompletionNote = $"lane_lock_request_failed_floor_plane:{floorNote}";
                DebugLog($"Lane lock request dropped. reason={_lastCompletionNote}");
                EmitRequestEvent(StandaloneLaneLockRequestEventKind.Failed, failedRequestId, _lastCompletionNote);
                ResetActiveRequestState();
                return;
            }

            var request = new StandaloneLaneLockRequest
            {
                sessionId = sessionId ?? string.Empty,
                requestId = _requestId ?? string.Empty,
                frameSeqStart = _frameSeqStart,
                frameSeqEnd = _frameSeqEnd,
                frameCount = _capturedFrameCount,
                captureDurationSeconds = captureDurationSeconds,
                selectionFrameSeq = _selectionFrameSeq,
                leftFoulLinePointNorm = _leftFoulLinePointNorm,
                rightFoulLinePointNorm = _rightFoulLinePointNorm,
                laneWidthMeters = laneWidthMeters,
                laneLengthMeters = laneLengthMeters,
                fx = currentSessionMetadata.fx,
                fy = currentSessionMetadata.fy,
                cx = currentSessionMetadata.cx,
                cy = currentSessionMetadata.cy,
                imageWidth = currentSessionMetadata.actualWidth > 0 ? currentSessionMetadata.actualWidth : currentSessionMetadata.requestedWidth,
                imageHeight = currentSessionMetadata.actualHeight > 0 ? currentSessionMetadata.actualHeight : currentSessionMetadata.requestedHeight,
                floorPlanePointWorld = floorPointWorld,
                floorPlaneNormalWorld = floorNormalWorld.normalized,
                cameraSide = currentSessionMetadata.cameraSide ?? string.Empty,
            };

            var sent = liveMetadataSender.TrySendLaneLockRequest(sessionId, streamId, request, out var note);
            _lastCompletionNote = sent
                ? $"lane_lock_request_sent:{completionReason}"
                : $"lane_lock_request_send_failed:{note}";
            DebugLog(
                $"Lane lock request finalized. sent={sent} requestId={request.requestId} frameRange={request.frameSeqStart}..{request.frameSeqEnd} frames={request.frameCount} note={note}");
            EmitRequestEvent(
                sent ? StandaloneLaneLockRequestEventKind.Sent : StandaloneLaneLockRequestEventKind.Failed,
                request.requestId,
                _lastCompletionNote);
            ResetActiveRequestState();
        }

        private void ResetActiveRequestState()
        {
            _requestActive = false;
            _requestId = null;
            _requestStartedRealtime = 0.0f;
            _capturedFrameCount = 0;
            _frameSeqStart = 0UL;
            _frameSeqEnd = 0UL;
        }

        private static bool IsNormalizedPoint(Vector2 point)
        {
            return !float.IsNaN(point.x)
                && !float.IsNaN(point.y)
                && !float.IsInfinity(point.x)
                && !float.IsInfinity(point.y)
                && point.x >= 0.0f
                && point.x <= 1.0f
                && point.y >= 0.0f
                && point.y <= 1.0f;
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestLaneLockCapture] {message}");
        }

        private void EmitRequestEvent(StandaloneLaneLockRequestEventKind kind, string requestId, string note)
        {
            RequestEvent?.Invoke(new StandaloneLaneLockRequestEvent(
                kind,
                requestId,
                note,
                Time.realtimeSinceStartup));
        }
    }
}
