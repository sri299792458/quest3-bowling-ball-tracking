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
            Vector2 pointNorm,
            float realtimeSeconds)
        {
            Kind = kind;
            Step = step;
            Note = note ?? string.Empty;
            PointNorm = pointNorm;
            RealtimeSeconds = realtimeSeconds;
        }

        public StandaloneFoulLineSelectionEventKind Kind { get; }
        public StandaloneFoulLineSelectionStep Step { get; }
        public string Note { get; }
        public Vector2 PointNorm { get; }
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

        [Header("Projection")]
        [SerializeField] private float maxFloorHitDistanceMeters = 25.0f;
        [SerializeField] private float minimumCameraDepthMeters = 0.05f;
        [SerializeField] private float armInputDebounceSeconds = 0.2f;
        [SerializeField] private bool clearPendingPointOnDisable = true;

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging;

        private bool _selectionActive;
        private bool _hasPendingLeftPoint;
        private Vector2 _pendingLeftPointNorm;
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
            _pendingLeftPointNorm = Vector2.zero;
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
                Vector2.zero);
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
                Vector2.zero);
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
            if (!TryMapSelectionToImagePoint(selection, out var pointNorm, out var note))
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
                    Vector2.zero);
                return;
            }

            if (!_hasPendingLeftPoint)
            {
                _pendingLeftPointNorm = pointNorm;
                _hasPendingLeftPoint = true;
                laneLockCapture?.ClearFoulLineSelection();
                SetStatus("left_foul_line_point_selected");
                EmitSelectionEvent(
                    StandaloneFoulLineSelectionEventKind.PointAccepted,
                    StandaloneFoulLineSelectionStep.Left,
                    "left_foul_line_point_selected",
                    pointNorm);
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
                    Vector2.zero);
                return;
            }

            var accepted = laneLockCapture.TrySetFoulLineSelection(_pendingLeftPointNorm, pointNorm, out note);
            if (accepted)
            {
                _selectionActive = false;
                ClearPendingSelection();
                SetStatus("foul_line_selection_ready");
                EmitSelectionEvent(
                    StandaloneFoulLineSelectionEventKind.Completed,
                    StandaloneFoulLineSelectionStep.Right,
                    "foul_line_selection_ready",
                    pointNorm);
                return;
            }

            SetStatus($"right_foul_line_selection_failed:{note}");
            EmitSelectionEvent(
                StandaloneFoulLineSelectionEventKind.PointRejected,
                StandaloneFoulLineSelectionStep.Right,
                note,
                Vector2.zero);
        }

        private bool TryMapSelectionToImagePoint(
            StandaloneQuestRaySelection selection,
            out Vector2 pointNorm,
            out string note)
        {
            pointNorm = Vector2.zero;
            note = "foul_line_projection_failed";

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
            var sessionMetadata = proofCapture.CurrentSessionMetadata;
            if (frameMetadata == null || sessionMetadata == null)
            {
                note = "selection_frame_metadata_missing";
                return false;
            }

            if (!floorPlaneSource.TryGetFloorPlane(out var planePointWorld, out var planeNormalWorld, out var floorNote))
            {
                note = $"floor_plane_unavailable:{floorNote}";
                return false;
            }

            if (!TryIntersectFloor(selection, planePointWorld, planeNormalWorld, out var hitWorld, out note))
            {
                return false;
            }

            return TryProjectWorldPointToImage(hitWorld, frameMetadata, sessionMetadata, out pointNorm, out note);
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

        private bool TryProjectWorldPointToImage(
            Vector3 worldPoint,
            StandaloneFrameMetadata frameMetadata,
            StandaloneSessionMetadata sessionMetadata,
            out Vector2 pointNorm,
            out string note)
        {
            pointNorm = Vector2.zero;
            note = "image_projection_failed";

            var width = frameMetadata.width > 0
                ? frameMetadata.width
                : (sessionMetadata.actualWidth > 0 ? sessionMetadata.actualWidth : sessionMetadata.requestedWidth);
            var height = frameMetadata.height > 0
                ? frameMetadata.height
                : (sessionMetadata.actualHeight > 0 ? sessionMetadata.actualHeight : sessionMetadata.requestedHeight);

            if (width <= 0 || height <= 0 || sessionMetadata.fx <= 0.0f || sessionMetadata.fy <= 0.0f)
            {
                note = "camera_intrinsics_missing";
                return false;
            }

            var cameraPoint = Quaternion.Inverse(frameMetadata.cameraRotation) * (worldPoint - frameMetadata.cameraPosition);
            if (!IsFinite(cameraPoint) || cameraPoint.z <= Mathf.Max(0.001f, minimumCameraDepthMeters))
            {
                note = "floor_hit_not_visible_to_camera";
                return false;
            }

            var pixelX = sessionMetadata.fx * (cameraPoint.x / cameraPoint.z) + sessionMetadata.cx;
            var pixelY = sessionMetadata.cy - sessionMetadata.fy * (cameraPoint.y / cameraPoint.z);
            pointNorm = new Vector2(pixelX / width, pixelY / height);

            if (!IsNormalizedPoint(pointNorm))
            {
                note = "floor_hit_outside_camera_image";
                return false;
            }

            note = "image_point_ready";
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
            Vector2 pointNorm)
        {
            SelectionEvent?.Invoke(new StandaloneFoulLineSelectionEvent(
                kind,
                step,
                note,
                pointNorm,
                Time.realtimeSinceStartup));
        }

        private static bool IsNormalizedPoint(Vector2 point)
        {
            return IsFinite(point)
                && point.x >= 0.0f
                && point.x <= 1.0f
                && point.y >= 0.0f
                && point.y <= 1.0f;
        }

        private static bool IsFinite(Vector2 value)
        {
            return IsFinite(value.x) && IsFinite(value.y);
        }

        private static bool IsFinite(Vector3 value)
        {
            return IsFinite(value.x) && IsFinite(value.y) && IsFinite(value.z);
        }

        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
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
