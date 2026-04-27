using System;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public enum StandaloneFoulLineSelectionStep
    {
        Left,
        Right,
    }

    public enum StandaloneFoulLineSelectionEventKind
    {
        Started,
        PointAccepted,
        PointRejected,
        Completed,
        Cancelled,
    }

    public readonly struct StandaloneFoulLineSelectionEvent
    {
        public StandaloneFoulLineSelectionEvent(
            StandaloneFoulLineSelectionEventKind kind,
            StandaloneFoulLineSelectionStep step,
            string note,
            Vector3 pointWorld,
            ulong frameSeq,
            float realtimeSeconds)
        {
            Kind = kind;
            Step = step;
            Note = note ?? string.Empty;
            PointWorld = pointWorld;
            FrameSeq = frameSeq;
            RealtimeSeconds = realtimeSeconds;
        }

        public StandaloneFoulLineSelectionEventKind Kind { get; }
        public StandaloneFoulLineSelectionStep Step { get; }
        public string Note { get; }
        public Vector3 PointWorld { get; }
        public ulong FrameSeq { get; }
        public float RealtimeSeconds { get; }
    }

    public sealed class StandaloneQuestFoulLineRaySelector : MonoBehaviour
    {
        [Header("Shared Selection Input")]
        [SerializeField] private StandaloneQuestRayInteractor rayInteractor;

        [Header("Lane Lock Target")]
        [SerializeField] private StandaloneQuestLaneLockCapture laneLockCapture;
        [SerializeField] private StandaloneQuestLocalProofCapture proofCapture;
        [SerializeField] private StandaloneQuestFloorPlaneSource floorPlaneSource;

        [Header("Floor Hit")]
        [SerializeField] private float maxFloorHitDistanceMeters = 25.0f;
        [SerializeField] private float armInputDebounceSeconds = 0.2f;
        [SerializeField] private bool clearPendingPointOnDisable = true;

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging;

        private bool _selectionActive;
        private bool _hasPendingLeftPoint;
        private Vector3 _pendingLeftPointWorld;
        private ulong _pendingLeftFrameSeq;
        private float _ignoreSelectionsUntilRealtime;

        public string LastStatus { get; private set; } = string.Empty;
        public event Action<StandaloneFoulLineSelectionEvent> SelectionEvent;

        private void OnEnable()
        {
            Subscribe();
        }

        private void OnDisable()
        {
            Unsubscribe();
            if (clearPendingPointOnDisable)
            {
                ClearPendingSelection();
            }
        }

        public void ClearPendingSelection()
        {
            _hasPendingLeftPoint = false;
            _pendingLeftPointWorld = Vector3.zero;
            _pendingLeftFrameSeq = 0UL;
        }

        public void BeginFoulLineSelection()
        {
            ClearPendingSelection();
            laneLockCapture?.ClearFoulLineSelection();
            _selectionActive = true;
            _ignoreSelectionsUntilRealtime = Time.realtimeSinceStartup + Mathf.Max(0.0f, armInputDebounceSeconds);
            SetStatus("select_left_foul_line_point");
            EmitSelectionEvent(
                StandaloneFoulLineSelectionEventKind.Started,
                StandaloneFoulLineSelectionStep.Left,
                "select_left_foul_line_point",
                Vector3.zero,
                0UL);
        }

        public void CancelFoulLineSelection()
        {
            _selectionActive = false;
            ClearPendingSelection();
            SetStatus("foul_line_selection_cancelled");
            EmitSelectionEvent(
                StandaloneFoulLineSelectionEventKind.Cancelled,
                StandaloneFoulLineSelectionStep.Left,
                "foul_line_selection_cancelled",
                Vector3.zero,
                0UL);
        }

        private void Subscribe()
        {
            if (rayInteractor == null)
            {
                return;
            }

            rayInteractor.SelectionPerformed -= OnSelectionPerformed;
            rayInteractor.SelectionPerformed += OnSelectionPerformed;
        }

        private void Unsubscribe()
        {
            if (rayInteractor == null)
            {
                return;
            }

            rayInteractor.SelectionPerformed -= OnSelectionPerformed;
        }

        private void OnSelectionPerformed(StandaloneQuestRaySelection selection)
        {
            if (!_selectionActive)
            {
                return;
            }

            if (selection.RealtimeSeconds < _ignoreSelectionsUntilRealtime)
            {
                return;
            }

            var selectingRightPoint = _hasPendingLeftPoint;
            if (!TryMapSelectionToWorldPoint(selection, out var pointWorld, out var frameSeq, out var note))
            {
                var step = selectingRightPoint
                    ? StandaloneFoulLineSelectionStep.Right
                    : StandaloneFoulLineSelectionStep.Left;
                if (selectingRightPoint)
                {
                    SetStatus($"right_foul_line_selection_failed:{note}");
                }
                else
                {
                    ClearPendingSelection();
                    SetStatus($"left_foul_line_selection_failed:{note}");
                }

                EmitSelectionEvent(
                    StandaloneFoulLineSelectionEventKind.PointRejected,
                    step,
                    note,
                    Vector3.zero,
                    0UL);
                return;
            }

            if (!_hasPendingLeftPoint)
            {
                _pendingLeftPointWorld = pointWorld;
                _pendingLeftFrameSeq = frameSeq;
                _hasPendingLeftPoint = true;
                laneLockCapture?.ClearFoulLineSelection();
                SetStatus("left_foul_line_point_selected");
                EmitSelectionEvent(
                    StandaloneFoulLineSelectionEventKind.PointAccepted,
                    StandaloneFoulLineSelectionStep.Left,
                    "left_foul_line_point_selected",
                    pointWorld,
                    frameSeq);
                return;
            }

            if (laneLockCapture == null)
            {
                ClearPendingSelection();
                SetStatus("lane_lock_capture_missing");
                EmitSelectionEvent(
                    StandaloneFoulLineSelectionEventKind.PointRejected,
                    StandaloneFoulLineSelectionStep.Right,
                    "lane_lock_capture_missing",
                    Vector3.zero,
                    0UL);
                return;
            }

            var accepted = laneLockCapture.TrySetFoulLineSelection(
                _pendingLeftPointWorld,
                _pendingLeftFrameSeq,
                pointWorld,
                frameSeq,
                out note);
            if (accepted)
            {
                _selectionActive = false;
                ClearPendingSelection();
                SetStatus("foul_line_selection_ready");
                EmitSelectionEvent(
                    StandaloneFoulLineSelectionEventKind.Completed,
                    StandaloneFoulLineSelectionStep.Right,
                    "foul_line_selection_ready",
                    pointWorld,
                    frameSeq);
                return;
            }

            SetStatus($"right_foul_line_selection_failed:{note}");
            EmitSelectionEvent(
                StandaloneFoulLineSelectionEventKind.PointRejected,
                StandaloneFoulLineSelectionStep.Right,
                note,
                Vector3.zero,
                0UL);
        }

        private bool TryMapSelectionToWorldPoint(
            StandaloneQuestRaySelection selection,
            out Vector3 pointWorld,
            out ulong frameSeq,
            out string note)
        {
            pointWorld = Vector3.zero;
            frameSeq = 0UL;
            note = "foul_line_selection_failed";

            if (proofCapture == null)
            {
                note = "proof_capture_missing";
                return false;
            }

            if (floorPlaneSource == null)
            {
                note = "floor_plane_source_missing";
                return false;
            }

            var frameMetadata = proofCapture.LastCommittedFrameMetadata;
            if (frameMetadata == null)
            {
                note = "selection_frame_metadata_missing";
                return false;
            }
            frameSeq = frameMetadata.frameSeq;

            if (!floorPlaneSource.TryGetFloorPlane(out var planePointWorld, out var planeNormalWorld, out var floorNote))
            {
                note = $"floor_plane_unavailable:{floorNote}";
                return false;
            }

            if (!TryIntersectFloor(selection, planePointWorld, planeNormalWorld, out var hitWorld, out note))
            {
                return false;
            }

            pointWorld = hitWorld;
            note = "foul_line_world_point_ready";
            return true;
        }

        private bool TryIntersectFloor(
            StandaloneQuestRaySelection selection,
            Vector3 planePointWorld,
            Vector3 planeNormalWorld,
            out Vector3 hitWorld,
            out string note)
        {
            hitWorld = Vector3.zero;
            note = "floor_intersection_failed";

            var normal = planeNormalWorld.normalized;
            var denominator = Vector3.Dot(normal, selection.DirectionWorld);
            if (Mathf.Abs(denominator) < 0.0001f)
            {
                note = "ray_parallel_to_floor";
                return false;
            }

            var distance = Vector3.Dot(planePointWorld - selection.OriginWorld, normal) / denominator;
            if (distance <= 0.0f)
            {
                note = "floor_hit_behind_ray";
                return false;
            }

            var maxDistance = Mathf.Min(
                Mathf.Max(0.1f, maxFloorHitDistanceMeters),
                Mathf.Max(0.1f, selection.MaxDistanceMeters));
            if (distance > maxDistance)
            {
                note = "floor_hit_too_far";
                return false;
            }

            hitWorld = selection.OriginWorld + selection.DirectionWorld * distance;
            note = "floor_hit_ready";
            return true;
        }

        private void SetStatus(string status)
        {
            LastStatus = status ?? string.Empty;
            DebugLog(LastStatus);
        }

        private void EmitSelectionEvent(
            StandaloneFoulLineSelectionEventKind kind,
            StandaloneFoulLineSelectionStep step,
            string note,
            Vector3 pointWorld,
            ulong frameSeq)
        {
            SelectionEvent?.Invoke(new StandaloneFoulLineSelectionEvent(
                kind,
                step,
                note,
                pointWorld,
                frameSeq,
                Time.realtimeSinceStartup));
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestFoulLineRaySelector] {message}");
        }
    }
}
