using System;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public enum StandaloneQuestLaneLockUiState
    {
        Unknown,
        SelectingLeftFoulLine,
        SelectingRightFoulLine,
        SelectionReady,
        RequestQueued,
        WaitingForCandidate,
        CandidateReceived,
        Confirmed,
        Failed,
    }

    public sealed class StandaloneQuestLaneLockStateCoordinator : MonoBehaviour
    {
        [Header("Lane Components")]
        [SerializeField] private StandaloneQuestLaneLockCapture laneLockCapture;
        [SerializeField] private StandaloneQuestFoulLineRaySelector foulLineSelector;
        [SerializeField] private StandaloneQuestLiveResultReceiver liveResultReceiver;
        [SerializeField] private StandaloneQuestLiveMetadataSender liveMetadataSender;
        [SerializeField] private StandaloneQuestLocalProofCapture proofCapture;
        [SerializeField] private StandaloneQuestLaneLockResultRenderer laneLockResultRenderer;

        [Header("Primary Action Labels")]
        [SerializeField] private string idleText = "Lock Lane";
        [SerializeField] private string selectLeftText = "Select Left Edge";
        [SerializeField] private string selectRightText = "Select Right Edge";
        [SerializeField] private string selectionReadyText = "Lock Lane";
        [SerializeField] private string requestQueuedText = "Capturing...";
        [SerializeField] private string awaitingResultText = "Solving...";
        [SerializeField] private string acceptLaneText = "Accept Lane";
        [SerializeField] private string lockedText = "Lane Locked";
        [SerializeField] private string failedText = "Try Again";
        [SerializeField] private string retryLaneText = "Retry Lane";
        [SerializeField] private string relockLaneText = "Relock Lane";
        [SerializeField] private string resultTimeoutText = "No Result";

        [Header("Flow")]
        [SerializeField] private bool autoSubmitAfterFoulLineSelection = true;
        [SerializeField] private float laneResultTimeoutSeconds = 30.0f;
        [SerializeField] private float selectionErrorDisplaySeconds = 1.5f;

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging;

        private string _lastSelectionStatus = string.Empty;
        private bool _awaitingLaneCandidate;
        private bool _hasPendingLaneCandidate;
        private string _pendingLaneCandidateRequestId = string.Empty;
        private string _awaitingLaneRequestId = string.Empty;
        private float _awaitingLaneCandidateStartedRealtime;
        private bool _laneConfirmed;
        private string _confirmedLaneRequestId = string.Empty;
        private bool _hasFailure;
        private string _failureLabel = string.Empty;
        private float _selectionErrorVisibleUntilRealtime;

        public StandaloneQuestLaneLockUiState LaneState { get; private set; } = StandaloneQuestLaneLockUiState.Unknown;
        public string PrimaryActionLabel { get; private set; } = "Lock Lane";
        public bool PrimaryActionInteractable { get; private set; } = true;
        public string SecondaryActionLabel { get; private set; } = "Retry Lane";
        public bool SecondaryActionVisible { get; private set; }
        public bool SecondaryActionInteractable { get; private set; }
        public string LastStatus { get; private set; } = string.Empty;

        private void Awake()
        {
            ResolveReferences();
            RefreshState(force: true);
        }

        private void OnEnable()
        {
            SubscribeToResults();
            SubscribeToSelector();
            SubscribeToCapture();
        }

        private void OnDisable()
        {
            UnsubscribeFromResults();
            UnsubscribeFromSelector();
            UnsubscribeFromCapture();
        }

        private void Update()
        {
            RefreshState(force: false);
        }

        public void HandlePrimaryAction()
        {
            RefreshState(force: true);

            if (laneLockCapture == null)
            {
                SetFailure("lane_lock_capture_missing");
                return;
            }

            switch (LaneState)
            {
                case StandaloneQuestLaneLockUiState.Unknown:
                case StandaloneQuestLaneLockUiState.Failed:
                    BeginFoulLineSelection();
                    return;

                case StandaloneQuestLaneLockUiState.SelectionReady:
                    BeginLaneLockRequest();
                    return;

                case StandaloneQuestLaneLockUiState.CandidateReceived:
                    ConfirmPendingLaneCandidate();
                    return;

                default:
                    RefreshState(force: true);
                    return;
            }
        }

        public void HandleSecondaryAction()
        {
            RefreshState(force: true);

            switch (LaneState)
            {
                case StandaloneQuestLaneLockUiState.CandidateReceived:
                    RejectPendingLaneCandidateAndReselect();
                    return;

                case StandaloneQuestLaneLockUiState.Confirmed:
                    RejectConfirmedLaneAndReselect();
                    return;

                default:
                    RefreshState(force: true);
                    return;
            }
        }

        private void ResolveReferences()
        {
            if (laneLockCapture == null)
            {
                laneLockCapture = FindFirstObjectByType<StandaloneQuestLaneLockCapture>();
            }

            if (foulLineSelector == null)
            {
                foulLineSelector = FindFirstObjectByType<StandaloneQuestFoulLineRaySelector>();
            }

            if (liveResultReceiver == null)
            {
                liveResultReceiver = FindFirstObjectByType<StandaloneQuestLiveResultReceiver>();
            }

            if (liveMetadataSender == null)
            {
                liveMetadataSender = FindFirstObjectByType<StandaloneQuestLiveMetadataSender>();
            }

            if (proofCapture == null)
            {
                proofCapture = FindFirstObjectByType<StandaloneQuestLocalProofCapture>();
            }

            if (laneLockResultRenderer == null)
            {
                laneLockResultRenderer = FindFirstObjectByType<StandaloneQuestLaneLockResultRenderer>();
            }
        }

        private void RefreshState(bool force)
        {
            ObserveLaneResultTimeout();

            if (force)
            {
                DebugLog($"lane_state={LaneState}");
            }

            PrimaryActionLabel = ComputePrimaryActionLabel();
            PrimaryActionInteractable = ComputePrimaryActionInteractable();
            SecondaryActionLabel = ComputeSecondaryActionLabel();
            SecondaryActionVisible = ComputeSecondaryActionVisible();
            SecondaryActionInteractable = ComputeSecondaryActionInteractable();
        }

        private string ComputePrimaryActionLabel()
        {
            if (_hasFailure
                && !string.IsNullOrWhiteSpace(_failureLabel)
                && LaneState != StandaloneQuestLaneLockUiState.SelectingLeftFoulLine
                && LaneState != StandaloneQuestLaneLockUiState.SelectingRightFoulLine
                && LaneState != StandaloneQuestLaneLockUiState.RequestQueued
                && LaneState != StandaloneQuestLaneLockUiState.WaitingForCandidate)
            {
                return _failureLabel;
            }

            if (IsSelectionError(_lastSelectionStatus)
                && (LaneState == StandaloneQuestLaneLockUiState.SelectingLeftFoulLine
                    || LaneState == StandaloneQuestLaneLockUiState.SelectingRightFoulLine)
                && Time.realtimeSinceStartup < _selectionErrorVisibleUntilRealtime)
            {
                return NoteToLabel(_lastSelectionStatus);
            }

            switch (LaneState)
            {
                case StandaloneQuestLaneLockUiState.SelectingLeftFoulLine:
                    return selectLeftText;
                case StandaloneQuestLaneLockUiState.SelectingRightFoulLine:
                    return selectRightText;
                case StandaloneQuestLaneLockUiState.SelectionReady:
                    return selectionReadyText;
                case StandaloneQuestLaneLockUiState.RequestQueued:
                    return requestQueuedText;
                case StandaloneQuestLaneLockUiState.WaitingForCandidate:
                    return awaitingResultText;
                case StandaloneQuestLaneLockUiState.CandidateReceived:
                    return acceptLaneText;
                case StandaloneQuestLaneLockUiState.Confirmed:
                    return lockedText;
                case StandaloneQuestLaneLockUiState.Failed:
                    return string.IsNullOrWhiteSpace(_failureLabel) ? failedText : _failureLabel;
                default:
                    return idleText;
            }
        }

        private bool ComputePrimaryActionInteractable()
        {
            switch (LaneState)
            {
                case StandaloneQuestLaneLockUiState.SelectingLeftFoulLine:
                case StandaloneQuestLaneLockUiState.SelectingRightFoulLine:
                case StandaloneQuestLaneLockUiState.RequestQueued:
                case StandaloneQuestLaneLockUiState.WaitingForCandidate:
                case StandaloneQuestLaneLockUiState.Confirmed:
                    return false;
                default:
                    return laneLockCapture != null;
            }
        }

        private string ComputeSecondaryActionLabel()
        {
            return LaneState == StandaloneQuestLaneLockUiState.Confirmed ? relockLaneText : retryLaneText;
        }

        private bool ComputeSecondaryActionVisible()
        {
            return LaneState == StandaloneQuestLaneLockUiState.CandidateReceived
                || LaneState == StandaloneQuestLaneLockUiState.Confirmed;
        }

        private bool ComputeSecondaryActionInteractable()
        {
            return ComputeSecondaryActionVisible()
                && liveMetadataSender != null
                && proofCapture != null
                && (!string.IsNullOrWhiteSpace(_pendingLaneCandidateRequestId)
                    || !string.IsNullOrWhiteSpace(_confirmedLaneRequestId));
        }

        private void BeginFoulLineSelection()
        {
            if (foulLineSelector == null)
            {
                SetFailure("foul_line_selector_missing");
                return;
            }

            ClearLocalLaneFacts();
            laneLockResultRenderer?.ClearVisualization("lane_reselect_started");
            foulLineSelector.BeginFoulLineSelection();
            SetLaneState(StandaloneQuestLaneLockUiState.SelectingLeftFoulLine);
            LastStatus = "selecting_foul_line";
            RefreshState(force: true);
        }

        private void RejectConfirmedLaneAndReselect()
        {
            if (!string.IsNullOrWhiteSpace(_confirmedLaneRequestId))
            {
                if (liveMetadataSender == null)
                {
                    SetFailure("live_metadata_sender_missing");
                    return;
                }

                if (proofCapture == null)
                {
                    SetFailure("proof_capture_missing");
                    return;
                }

                var rejected = liveMetadataSender.TrySendLaneLockConfirm(
                    proofCapture.ActiveSessionId,
                    proofCapture.ActiveStreamId,
                    _confirmedLaneRequestId,
                    false,
                    "user_relock_requested",
                    out var rejectNote);
                if (!rejected)
                {
                    SetFailure(rejectNote);
                    return;
                }
            }

            BeginFoulLineSelection();
        }

        private void RejectPendingLaneCandidateAndReselect()
        {
            if (string.IsNullOrWhiteSpace(_pendingLaneCandidateRequestId))
            {
                SetFailure("lane_lock_confirm_request_id_missing");
                return;
            }

            if (liveMetadataSender == null)
            {
                SetFailure("live_metadata_sender_missing");
                return;
            }

            if (proofCapture == null)
            {
                SetFailure("proof_capture_missing");
                return;
            }

            var rejected = liveMetadataSender.TrySendLaneLockConfirm(
                proofCapture.ActiveSessionId,
                proofCapture.ActiveStreamId,
                _pendingLaneCandidateRequestId,
                false,
                "user_reject_lane_candidate",
                out var rejectNote);
            if (!rejected)
            {
                SetFailure(rejectNote);
                return;
            }

            BeginFoulLineSelection();
        }

        private void BeginLaneLockRequest()
        {
            var started = laneLockCapture.TryBeginLaneLockRequest(out var note);
            LastStatus = note;
            DebugLog($"lane_lock_request={(started ? "started" : "ignored")} note={note}");

            RefreshState(force: true);
        }

        private void ConfirmPendingLaneCandidate()
        {
            if (!_hasPendingLaneCandidate)
            {
                return;
            }

            if (liveMetadataSender == null)
            {
                SetFailure("live_metadata_sender_missing");
                return;
            }

            var sessionId = proofCapture != null ? proofCapture.ActiveSessionId : string.Empty;
            var streamId = proofCapture != null ? proofCapture.ActiveStreamId : string.Empty;
            var sent = liveMetadataSender.TrySendLaneLockConfirm(
                sessionId,
                streamId,
                _pendingLaneCandidateRequestId,
                true,
                "user_accept_lane_overlay",
                out var note);
            if (!sent)
            {
                SetFailure(note);
                return;
            }

            _confirmedLaneRequestId = _pendingLaneCandidateRequestId;
            _pendingLaneCandidateRequestId = string.Empty;
            _hasPendingLaneCandidate = false;
            _awaitingLaneCandidate = false;
            _awaitingLaneRequestId = string.Empty;
            _laneConfirmed = true;
            _hasFailure = false;
            LastStatus = note;
            SetLaneState(StandaloneQuestLaneLockUiState.Confirmed);
            RefreshState(force: true);
        }

        private void ObserveLaneResultTimeout()
        {
            if (!_awaitingLaneCandidate)
            {
                return;
            }

            var timeoutSeconds = Mathf.Max(1.0f, laneResultTimeoutSeconds);
            if (Time.realtimeSinceStartup - _awaitingLaneCandidateStartedRealtime < timeoutSeconds)
            {
                return;
            }

            SetFailure("lane_lock_result_timeout", clearFoulLineSelection: true);
        }

        private void OnLaneLockResultReceived(StandaloneLaneLockResult result)
        {
            if (result == null)
            {
                SetFailure("lane_lock_result_missing", clearFoulLineSelection: true);
                return;
            }

            var resultRequestId = result.requestId ?? string.Empty;
            if (!_awaitingLaneCandidate
                || string.IsNullOrWhiteSpace(_awaitingLaneRequestId)
                || !string.Equals(resultRequestId, _awaitingLaneRequestId, StringComparison.Ordinal))
            {
                LastStatus = string.IsNullOrWhiteSpace(resultRequestId)
                    ? "lane_lock_result_ignored_request_missing"
                    : $"lane_lock_result_ignored:{resultRequestId}";
                DebugLog(LastStatus);
                return;
            }

            _awaitingLaneCandidate = false;
            _awaitingLaneRequestId = string.Empty;
            _awaitingLaneCandidateStartedRealtime = 0.0f;
            _hasPendingLaneCandidate = false;
            _pendingLaneCandidateRequestId = string.Empty;
            _laneConfirmed = false;
            _confirmedLaneRequestId = string.Empty;

            if (!result.success)
            {
                SetFailure(result.failureReason, clearFoulLineSelection: true);
                return;
            }

            _hasPendingLaneCandidate = true;
            _pendingLaneCandidateRequestId = result.requestId ?? string.Empty;
            _hasFailure = false;
            LastStatus = "lane_candidate_received";
            SetLaneState(StandaloneQuestLaneLockUiState.CandidateReceived);
            RefreshState(force: true);
        }

        private void SubscribeToResults()
        {
            if (liveResultReceiver == null)
            {
                return;
            }

            liveResultReceiver.LaneLockResultReceived -= OnLaneLockResultReceived;
            liveResultReceiver.LaneLockResultReceived += OnLaneLockResultReceived;
        }

        private void UnsubscribeFromResults()
        {
            if (liveResultReceiver == null)
            {
                return;
            }

            liveResultReceiver.LaneLockResultReceived -= OnLaneLockResultReceived;
        }

        private void SubscribeToSelector()
        {
            if (foulLineSelector == null)
            {
                return;
            }

            foulLineSelector.SelectionEvent -= OnFoulLineSelectionEvent;
            foulLineSelector.SelectionEvent += OnFoulLineSelectionEvent;
        }

        private void UnsubscribeFromSelector()
        {
            if (foulLineSelector == null)
            {
                return;
            }

            foulLineSelector.SelectionEvent -= OnFoulLineSelectionEvent;
        }

        private void SubscribeToCapture()
        {
            if (laneLockCapture == null)
            {
                return;
            }

            laneLockCapture.RequestEvent -= OnLaneLockRequestEvent;
            laneLockCapture.RequestEvent += OnLaneLockRequestEvent;
        }

        private void UnsubscribeFromCapture()
        {
            if (laneLockCapture == null)
            {
                return;
            }

            laneLockCapture.RequestEvent -= OnLaneLockRequestEvent;
        }

        private void OnLaneLockRequestEvent(StandaloneLaneLockRequestEvent requestEvent)
        {
            LastStatus = requestEvent.Note;

            switch (requestEvent.Kind)
            {
                case StandaloneLaneLockRequestEventKind.Started:
                    _awaitingLaneCandidate = true;
                    _awaitingLaneRequestId = requestEvent.RequestId;
                    _awaitingLaneCandidateStartedRealtime = Time.realtimeSinceStartup;
                    _hasFailure = false;
                    SetLaneState(StandaloneQuestLaneLockUiState.RequestQueued);
                    break;

                case StandaloneLaneLockRequestEventKind.Sent:
                    _awaitingLaneCandidate = true;
                    if (!string.IsNullOrWhiteSpace(requestEvent.RequestId))
                    {
                        _awaitingLaneRequestId = requestEvent.RequestId;
                    }

                    _awaitingLaneCandidateStartedRealtime = Time.realtimeSinceStartup;
                    _hasFailure = false;
                    SetLaneState(StandaloneQuestLaneLockUiState.WaitingForCandidate);
                    break;

                case StandaloneLaneLockRequestEventKind.Failed:
                    SetFailure(requestEvent.Note, clearFoulLineSelection: true);
                    return;
            }

            RefreshState(force: true);
        }

        private void OnFoulLineSelectionEvent(StandaloneFoulLineSelectionEvent selectionEvent)
        {
            LastStatus = selectionEvent.Note;

            switch (selectionEvent.Kind)
            {
                case StandaloneFoulLineSelectionEventKind.Started:
                    _hasFailure = false;
                    _lastSelectionStatus = selectionEvent.Note;
                    SetLaneState(StandaloneQuestLaneLockUiState.SelectingLeftFoulLine);
                    break;

                case StandaloneFoulLineSelectionEventKind.PointAccepted:
                    _hasFailure = false;
                    _lastSelectionStatus = selectionEvent.Note;
                    if (selectionEvent.Step == StandaloneFoulLineSelectionStep.Left)
                    {
                        SetLaneState(StandaloneQuestLaneLockUiState.SelectingRightFoulLine);
                    }
                    break;

                case StandaloneFoulLineSelectionEventKind.PointRejected:
                    _lastSelectionStatus = FailureStatusForSelectionEvent(selectionEvent);
                    _selectionErrorVisibleUntilRealtime = Time.realtimeSinceStartup
                        + Mathf.Max(0.1f, selectionErrorDisplaySeconds);
                    SetLaneState(selectionEvent.Step == StandaloneFoulLineSelectionStep.Left
                        ? StandaloneQuestLaneLockUiState.SelectingLeftFoulLine
                        : StandaloneQuestLaneLockUiState.SelectingRightFoulLine);
                    break;

                case StandaloneFoulLineSelectionEventKind.Completed:
                    _hasFailure = false;
                    _lastSelectionStatus = selectionEvent.Note;
                    SetLaneState(StandaloneQuestLaneLockUiState.SelectionReady);
                    if (autoSubmitAfterFoulLineSelection
                        && laneLockCapture != null
                        && laneLockCapture.HasFoulLineSelection
                        && !laneLockCapture.IsRequestActive
                        && !_awaitingLaneCandidate
                        && !_hasPendingLaneCandidate
                        && !_laneConfirmed)
                    {
                        BeginLaneLockRequest();
                        return;
                    }
                    break;

                case StandaloneFoulLineSelectionEventKind.Cancelled:
                    _lastSelectionStatus = selectionEvent.Note;
                    _hasFailure = false;
                    SetLaneState(StandaloneQuestLaneLockUiState.Unknown);
                    break;
            }

            RefreshState(force: true);
        }

        private void ClearLocalLaneFacts()
        {
            _awaitingLaneCandidate = false;
            _awaitingLaneRequestId = string.Empty;
            _hasPendingLaneCandidate = false;
            _pendingLaneCandidateRequestId = string.Empty;
            _laneConfirmed = false;
            _confirmedLaneRequestId = string.Empty;
            _hasFailure = false;
            _failureLabel = string.Empty;
            _lastSelectionStatus = string.Empty;
            _selectionErrorVisibleUntilRealtime = 0.0f;
            laneLockCapture?.ClearFoulLineSelection();
        }

        private void SetFailure(string note)
        {
            SetFailure(note, clearFoulLineSelection: false);
        }

        private void SetFailure(string note, bool clearFoulLineSelection)
        {
            _awaitingLaneCandidate = false;
            _awaitingLaneRequestId = string.Empty;
            _awaitingLaneCandidateStartedRealtime = 0.0f;
            if (clearFoulLineSelection)
            {
                laneLockCapture?.ClearFoulLineSelection();
            }

            _hasFailure = true;
            _failureLabel = NoteToLabel(note);
            LastStatus = string.IsNullOrWhiteSpace(note) ? "lane_lock_failed" : note;
            SetLaneState(StandaloneQuestLaneLockUiState.Failed);
            RefreshState(force: true);
        }

        private void SetLaneState(StandaloneQuestLaneLockUiState nextState)
        {
            if (LaneState == nextState)
            {
                return;
            }

            LaneState = nextState;
            DebugLog($"lane_state={LaneState}");
        }

        private bool IsSelectionError(string note)
        {
            note = NormalizeSelectionFailureNote(note);
            if (string.IsNullOrWhiteSpace(note))
            {
                return false;
            }

            return note.StartsWith("floor_hit_", StringComparison.Ordinal)
                || note.StartsWith("ray_parallel_to_floor", StringComparison.Ordinal)
                || note.StartsWith("selection_frame_metadata_missing", StringComparison.Ordinal)
                || note.StartsWith("floor_plane_unavailable:", StringComparison.Ordinal)
                || note.StartsWith("foul_line_selection_order_invalid", StringComparison.Ordinal);
        }

        private static string NormalizeSelectionFailureNote(string note)
        {
            if (string.IsNullOrWhiteSpace(note))
            {
                return string.Empty;
            }

            const string leftPrefix = "left_foul_line_selection_failed:";
            if (note.StartsWith(leftPrefix, StringComparison.Ordinal))
            {
                return note.Substring(leftPrefix.Length);
            }

            const string rightPrefix = "right_foul_line_selection_failed:";
            if (note.StartsWith(rightPrefix, StringComparison.Ordinal))
            {
                return note.Substring(rightPrefix.Length);
            }

            return note;
        }

        private static string FailureStatusForSelectionEvent(StandaloneFoulLineSelectionEvent selectionEvent)
        {
            var note = selectionEvent.Note ?? string.Empty;
            return selectionEvent.Step == StandaloneFoulLineSelectionStep.Left
                ? $"left_foul_line_selection_failed:{note}"
                : $"right_foul_line_selection_failed:{note}";
        }

        private string NoteToLabel(string note)
        {
            note = NormalizeSelectionFailureNote(note);
            if (string.IsNullOrWhiteSpace(note))
            {
                return failedText;
            }

            if (note.StartsWith("foul_line_selection_missing", StringComparison.Ordinal))
            {
                return "Select Foul Line";
            }

            if (note.StartsWith("floor_hit_outside_camera_image", StringComparison.Ordinal))
            {
                return "Aim In View";
            }

            if (note.StartsWith("floor_hit_too_far", StringComparison.Ordinal))
            {
                return "Aim Closer";
            }

            if (note.StartsWith("ray_parallel_to_floor", StringComparison.Ordinal)
                || note.StartsWith("floor_hit_behind_ray", StringComparison.Ordinal)
                || note.StartsWith("floor_hit_not_visible_to_camera", StringComparison.Ordinal))
            {
                return "Aim At Floor";
            }

            if (note.StartsWith("selection_frame_metadata_missing", StringComparison.Ordinal))
            {
                return "Camera Not Ready";
            }

            if (note.StartsWith("floor_plane_unavailable:", StringComparison.Ordinal))
            {
                return "Floor Not Ready";
            }

            if (note.StartsWith("session_stream_not_active", StringComparison.Ordinal))
            {
                return "Starting Session";
            }

            if (note.StartsWith("lane_lock_request_failed_no_frames", StringComparison.Ordinal))
            {
                return "No Frames";
            }

            if (note.StartsWith("lane_lock_request_failed_low_frame_count", StringComparison.Ordinal))
            {
                return "Hold Steady";
            }

            if (note.StartsWith("lane_lock_request_send_failed", StringComparison.Ordinal))
            {
                return "Send Failed";
            }

            if (note.StartsWith("lane_lock_result_timeout", StringComparison.Ordinal))
            {
                return resultTimeoutText;
            }

            if (note.StartsWith("metadata_stream_not_connected", StringComparison.Ordinal))
            {
                return "Link Missing";
            }

            if (note.StartsWith("lane_lock_confirm_request_id_missing", StringComparison.Ordinal))
            {
                return "No Lane";
            }

            if (note.StartsWith("foul_line_selection_order_invalid", StringComparison.Ordinal))
            {
                return "Right Edge Again";
            }

            return failedText;
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestLaneLockStateCoordinator] {message}");
        }
    }
}
