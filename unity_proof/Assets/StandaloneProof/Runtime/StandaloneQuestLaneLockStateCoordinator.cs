using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace QuestBowlingStandalone.QuestApp
{
    public enum StandaloneQuestLaneLockUiState
    {
        Idle,
        ArmedForPlacement,
        PlacingHeads,
        FullLanePreview,
        Locked,
        Failed,
    }

    public readonly struct StandaloneQuestLaneLockPresentation
    {
        public StandaloneQuestLaneLockPresentation(
            string primaryLabel,
            bool primaryVisible,
            bool primaryInteractable,
            string secondaryLabel,
            bool secondaryVisible,
            bool secondaryInteractable,
            string readinessBlockerLabel)
        {
            PrimaryLabel = primaryLabel ?? string.Empty;
            PrimaryVisible = primaryVisible;
            PrimaryInteractable = primaryInteractable;
            SecondaryLabel = secondaryLabel ?? string.Empty;
            SecondaryVisible = secondaryVisible;
            SecondaryInteractable = secondaryInteractable;
            ReadinessBlockerLabel = readinessBlockerLabel ?? string.Empty;
        }

        public string PrimaryLabel { get; }
        public bool PrimaryVisible { get; }
        public bool PrimaryInteractable { get; }
        public string SecondaryLabel { get; }
        public bool SecondaryVisible { get; }
        public bool SecondaryInteractable { get; }
        public string ReadinessBlockerLabel { get; }
    }

    public sealed class StandaloneQuestLaneLockStateCoordinator : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private StandaloneQuestFloorPlaneSource floorPlaneSource;
        [SerializeField] private StandaloneQuestLocalProofCapture proofCapture;
        [SerializeField] private StandaloneQuestSessionController sessionController;
        [SerializeField] private StandaloneQuestLiveMetadataSender liveMetadataSender;
        [SerializeField] private StandaloneQuestLiveResultReceiver liveResultReceiver;
        [SerializeField] private StandaloneQuestLaneLockResultRenderer laneRenderer;
        [SerializeField] private Transform headTransform;
        [SerializeField] private OVRHand handPinchSource;
        [SerializeField] private Transform visualizationRoot;

        [Header("Lane Dimensions")]
        [SerializeField] private float laneWidthMeters = 1.0541f;
        [SerializeField] private float headsSectionLengthMeters = 4.572f;
        [SerializeField] private float laneLengthMeters = 18.288f;
        [SerializeField] private float placementDistanceMeters = 0.75f;

        [Header("Input")]
        [SerializeField] private float pinchPressThreshold = 0.70f;
        [SerializeField] private float pinchReleaseThreshold = 0.30f;

        [Header("Stabilization")]
        [SerializeField] private bool useStabilization = true;
        [SerializeField] private float smoothingSeconds = 0.16f;
        [SerializeField] private float positionDeadzoneMeters = 0.012f;
        [SerializeField] private float angleDeadzoneDegrees = 0.45f;
        [SerializeField] private float releaseAverageSeconds = 0.35f;

        [Header("Preview")]
        [SerializeField] private float verticalOffsetMeters = 0.025f;
        [SerializeField] private float headsLineWidthMeters = 0.03f;
        [SerializeField] private Color headsOutlineColor = new Color(1.0f, 0.82f, 0.16f, 1.0f);
        [SerializeField] private Color headsSurfaceColor = new Color(1.0f, 0.82f, 0.16f, 0.16f);

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging;

        private readonly List<PoseSample> _samples = new List<PoseSample>();
        private bool _wasPinching;
        private bool _ignorePinchUntilReleased;
        private bool _hasSmoothedPose;
        private Vector3 _smoothedOrigin;
        private Vector3 _smoothedForward;
        private Vector3 _smoothedOriginVelocity;
        private StandaloneLaneLockResult _pendingResult;
        private GameObject _headsSurfaceObject;
        private MeshFilter _headsSurfaceMeshFilter;
        private MeshRenderer _headsSurfaceMeshRenderer;
        private Mesh _headsSurfaceMesh;
        private LineRenderer _headsOutlineRenderer;
        private Material _headsSurfaceMaterial;
        private Material _headsOutlineMaterial;
        private string _activeSessionId = string.Empty;

        public StandaloneQuestLaneLockUiState State { get; private set; } = StandaloneQuestLaneLockUiState.Idle;
        public string LastStatus { get; private set; } = "pinch_hold_ready";
        public event Action<StandaloneQuestLaneLockUiState, string> StateChanged;

        public string CurrentConfirmedLaneLockRequestId { get; private set; } = string.Empty;
        public StandaloneQuestLaneLockPresentation Presentation => ResolvePresentation();
        public string PrimaryActionLabel => Presentation.PrimaryLabel;
        public bool PrimaryActionVisible => Presentation.PrimaryVisible;
        public bool PrimaryActionInteractable => Presentation.PrimaryInteractable;
        public string SecondaryActionLabel => Presentation.SecondaryLabel;
        public bool SecondaryActionVisible => Presentation.SecondaryVisible;
        public bool SecondaryActionInteractable => Presentation.SecondaryInteractable;
        public string ReadinessBlockerLabel => Presentation.ReadinessBlockerLabel;
        public bool LaneInteractionReady => TryGetLaneInteractionReadiness(out _, out _);
        public bool TryGetCurrentLaneUp(out Vector3 laneUp)
        {
            laneUp = Vector3.up;
            if (State != StandaloneQuestLaneLockUiState.Locked || _pendingResult == null)
            {
                return false;
            }

            laneUp = _pendingResult.floorPlaneNormalWorld.sqrMagnitude > 0.0001f
                ? _pendingResult.floorPlaneNormalWorld.normalized
                : Vector3.up;
            return true;
        }

        public string LaneInteractionBlockerLabel
        {
            get
            {
                TryGetLaneInteractionReadiness(out var blockerLabel, out _);
                return blockerLabel;
            }
        }

        private void Awake()
        {
            ResolveReferences();
            EnsurePreviewObjects();
            ClearHeadsPreview();
        }

        private void Update()
        {
            if (TrackSessionIdentity())
            {
                return;
            }

            var pinching = IsPinching();
            var pinchStarted = pinching && !_wasPinching;
            var pinchReleased = !pinching && _wasPinching;

            if (!LaneInteractionReady &&
                (State == StandaloneQuestLaneLockUiState.ArmedForPlacement ||
                 State == StandaloneQuestLaneLockUiState.PlacingHeads))
            {
                ResetLane("lane_preflight_lost");
                _wasPinching = pinching;
                return;
            }

            if (_ignorePinchUntilReleased)
            {
                if (!pinching)
                {
                    _ignorePinchUntilReleased = false;
                    SetStatus("lane_placement_armed_pinch_hold");
                }

                _wasPinching = pinching;
                return;
            }

            if (State == StandaloneQuestLaneLockUiState.ArmedForPlacement && pinchStarted)
            {
                BeginPlacement();
            }

            if (State == StandaloneQuestLaneLockUiState.PlacingHeads)
            {
                if (pinching)
                {
                    UpdatePlacementPreview();
                }
                else if (pinchReleased)
                {
                    FinishPlacement();
                }
            }

            _wasPinching = pinching;
        }

        private bool TrackSessionIdentity()
        {
            var sessionId = sessionController != null && sessionController.IsSessionActive
                ? sessionController.ActiveSessionId
                : string.Empty;
            if (string.IsNullOrWhiteSpace(sessionId))
            {
                if (!string.IsNullOrWhiteSpace(_activeSessionId))
                {
                    _activeSessionId = string.Empty;
                    ResetLane("session_inactive");
                    return true;
                }

                return false;
            }

            if (string.IsNullOrWhiteSpace(_activeSessionId))
            {
                _activeSessionId = sessionId;
                return false;
            }

            if (_activeSessionId == sessionId)
            {
                return false;
            }

            _activeSessionId = sessionId;
            ResetLane("session_changed");
            return true;
        }

        public void HandlePrimaryAction()
        {
            HandleAction(StandaloneQuestLaneLockActionKind.Primary);
        }

        public void HandleSecondaryAction()
        {
            HandleAction(StandaloneQuestLaneLockActionKind.Secondary);
        }

        public void HandleAction(StandaloneQuestLaneLockActionKind actionKind)
        {
            var presentation = Presentation;
            var visible = actionKind == StandaloneQuestLaneLockActionKind.Primary
                ? presentation.PrimaryVisible
                : presentation.SecondaryVisible;
            var interactable = actionKind == StandaloneQuestLaneLockActionKind.Primary
                ? presentation.PrimaryInteractable
                : presentation.SecondaryInteractable;
            if (!visible || !interactable)
            {
                SetStatus($"ignored_action:{State}:{actionKind}");
                return;
            }

            if (!LaneInteractionReady && !IsLocalCancelAction(actionKind))
            {
                SetStatus($"ignored_action_preflight_not_ready:{State}:{actionKind}:{LaneInteractionBlockerLabel}");
                return;
            }

            switch (State)
            {
                case StandaloneQuestLaneLockUiState.Idle:
                case StandaloneQuestLaneLockUiState.Failed:
                    if (actionKind == StandaloneQuestLaneLockActionKind.Primary)
                    {
                        EnterArmedForPlacement("user_place_lane");
                    }
                    break;

                case StandaloneQuestLaneLockUiState.ArmedForPlacement:
                    if (actionKind == StandaloneQuestLaneLockActionKind.Secondary)
                    {
                        ResetLane("user_cancel_placement");
                    }
                    break;

                case StandaloneQuestLaneLockUiState.FullLanePreview:
                    if (actionKind == StandaloneQuestLaneLockActionKind.Primary)
                    {
                        ConfirmLane();
                    }
                    else
                    {
                        ResetLane("user_retry");
                    }
                    break;

                case StandaloneQuestLaneLockUiState.Locked:
                    if (actionKind == StandaloneQuestLaneLockActionKind.Secondary)
                    {
                        ResetLane("user_relock");
                    }
                    break;
            }
        }

        private StandaloneQuestLaneLockPresentation ResolvePresentation()
        {
            if (!TryGetLaneInteractionReadiness(out var blockerLabel, out _))
            {
                switch (State)
                {
                    case StandaloneQuestLaneLockUiState.ArmedForPlacement:
                    case StandaloneQuestLaneLockUiState.FullLanePreview:
                        return new StandaloneQuestLaneLockPresentation(
                            blockerLabel,
                            primaryVisible: true,
                            primaryInteractable: false,
                            secondaryLabel: "Cancel",
                            secondaryVisible: true,
                            secondaryInteractable: true,
                            readinessBlockerLabel: blockerLabel);

                    case StandaloneQuestLaneLockUiState.PlacingHeads:
                        return new StandaloneQuestLaneLockPresentation(
                            blockerLabel,
                            primaryVisible: true,
                            primaryInteractable: false,
                            secondaryLabel: string.Empty,
                            secondaryVisible: false,
                            secondaryInteractable: false,
                            readinessBlockerLabel: blockerLabel);

                    case StandaloneQuestLaneLockUiState.Locked:
                        return new StandaloneQuestLaneLockPresentation(
                            string.Empty,
                            primaryVisible: false,
                            primaryInteractable: false,
                            secondaryLabel: "Relock",
                            secondaryVisible: true,
                            secondaryInteractable: false,
                            readinessBlockerLabel: blockerLabel);

                    default:
                        return new StandaloneQuestLaneLockPresentation(
                            blockerLabel,
                            primaryVisible: true,
                            primaryInteractable: false,
                            secondaryLabel: string.Empty,
                            secondaryVisible: false,
                            secondaryInteractable: false,
                            readinessBlockerLabel: blockerLabel);
                }
            }

            switch (State)
            {
                case StandaloneQuestLaneLockUiState.ArmedForPlacement:
                    return new StandaloneQuestLaneLockPresentation(
                        _ignorePinchUntilReleased ? "Release First" : "Pinch + Hold",
                        primaryVisible: true,
                        primaryInteractable: false,
                        secondaryLabel: "Cancel",
                        secondaryVisible: true,
                        secondaryInteractable: true,
                        readinessBlockerLabel: _ignorePinchUntilReleased ? "Release First" : "Pinch + Hold Lane");

                case StandaloneQuestLaneLockUiState.PlacingHeads:
                    return new StandaloneQuestLaneLockPresentation(
                        "Release To Preview",
                        primaryVisible: true,
                        primaryInteractable: false,
                        secondaryLabel: string.Empty,
                        secondaryVisible: false,
                        secondaryInteractable: false,
                        readinessBlockerLabel: "Hold To Place Lane");

                case StandaloneQuestLaneLockUiState.FullLanePreview:
                    return new StandaloneQuestLaneLockPresentation(
                        "Lock Lane",
                        primaryVisible: true,
                        primaryInteractable: true,
                        secondaryLabel: "Retry",
                        secondaryVisible: true,
                        secondaryInteractable: true,
                        readinessBlockerLabel: "Confirm Lane");

                case StandaloneQuestLaneLockUiState.Locked:
                    return new StandaloneQuestLaneLockPresentation(
                        string.Empty,
                        primaryVisible: false,
                        primaryInteractable: false,
                        secondaryLabel: "Relock",
                        secondaryVisible: true,
                        secondaryInteractable: true,
                        readinessBlockerLabel: string.Empty);

                case StandaloneQuestLaneLockUiState.Failed:
                    return new StandaloneQuestLaneLockPresentation(
                        "Try Again",
                        primaryVisible: true,
                        primaryInteractable: true,
                        secondaryLabel: string.Empty,
                        secondaryVisible: false,
                        secondaryInteractable: false,
                        readinessBlockerLabel: "Lane Failed - Try Again");

                default:
                    return new StandaloneQuestLaneLockPresentation(
                        "Place Lane",
                        primaryVisible: true,
                        primaryInteractable: true,
                        secondaryLabel: string.Empty,
                        secondaryVisible: false,
                        secondaryInteractable: false,
                        readinessBlockerLabel: "Place Lane");
            }
        }

        public void ResetLane(string reason)
        {
            if (State == StandaloneQuestLaneLockUiState.Locked && _pendingResult != null)
            {
                TryPublishLaneRejection(_pendingResult.requestId, string.IsNullOrWhiteSpace(reason) ? "user_relock" : reason, out _);
            }

            _pendingResult = null;
            CurrentConfirmedLaneLockRequestId = string.Empty;
            _ignorePinchUntilReleased = false;
            SetState(StandaloneQuestLaneLockUiState.Idle, reason);
            ResetStabilization();
            ClearHeadsPreview();
            laneRenderer?.ClearVisualization(reason);
            ClearProofCaptureLaneLock();
            SetStatus("pinch_hold_ready");
        }

        private void EnterArmedForPlacement(string reason)
        {
            _pendingResult = null;
            CurrentConfirmedLaneLockRequestId = string.Empty;
            _ignorePinchUntilReleased = IsPinching();
            SetState(StandaloneQuestLaneLockUiState.ArmedForPlacement, string.IsNullOrWhiteSpace(reason) ? "lane_placement_armed" : reason);
            ResetStabilization();
            ClearHeadsPreview();
            laneRenderer?.ClearVisualization("lane_placement_armed");
            ClearProofCaptureLaneLock();
            SetStatus(_ignorePinchUntilReleased ? "lane_placement_armed_release_then_pinch_hold" : "lane_placement_armed_pinch_hold");
        }

        private void BeginPlacement()
        {
            _pendingResult = null;
            _ignorePinchUntilReleased = false;
            SetState(StandaloneQuestLaneLockUiState.PlacingHeads, "heads_placement_started");
            ResetStabilization();
            laneRenderer?.ClearVisualization("heads_placement_started");
            UpdatePlacementPreview();
            SetStatus("hold_pinch_to_fit_heads_release_to_preview");
        }

        private void UpdatePlacementPreview()
        {
            if (!TryComputePose(out var origin, out var forward, out var floorPoint, out var floorNormal, out var note))
            {
                Fail(note);
                return;
            }

            StabilizePose(ref origin, ref forward);
            RecordPoseSample(origin, forward, floorPoint, floorNormal);
            RenderHeadsPreview(origin, forward, floorNormal);
        }

        private void FinishPlacement()
        {
            if (!TryGetReleasePose(out var origin, out var forward, out var floorPoint, out var floorNormal))
            {
                Fail("release_pose_missing");
                return;
            }

            ClearHeadsPreview();
            _pendingResult = BuildLaneResult(origin, forward, floorPoint, floorNormal, userConfirmed: false);
            laneRenderer?.RenderLaneLockResult(_pendingResult);
            SetState(StandaloneQuestLaneLockUiState.FullLanePreview, "full_lane_preview");
            SetStatus("full_lane_preview_confirm_or_retry");
        }

        private void ConfirmLane()
        {
            if (_pendingResult == null)
            {
                Fail("lane_preview_missing");
                return;
            }

            _pendingResult.userConfirmed = true;
            _pendingResult.requiresConfirmation = false;
            _pendingResult.confidence = Mathf.Max(_pendingResult.confidence, 0.96f);
            _pendingResult.lockState = "Locked";
            _ignorePinchUntilReleased = false;

            if (!TryApplyLaneLockToProofCapture(_pendingResult, out var note))
            {
                Fail(note);
                return;
            }

            if (!TryPublishConfirmedLane(_pendingResult, out var publishNote))
            {
                ClearProofCaptureLaneLock();
                Fail(publishNote);
                return;
            }

            CurrentConfirmedLaneLockRequestId = _pendingResult.requestId ?? string.Empty;
            SetState(StandaloneQuestLaneLockUiState.Locked, "lane_locked");
            laneRenderer?.RenderLaneLockResult(_pendingResult);
            SetStatus("lane_locked");
        }

        private bool TryComputePose(
            out Vector3 origin,
            out Vector3 forward,
            out Vector3 floorPoint,
            out Vector3 floorNormal,
            out string note)
        {
            origin = Vector3.zero;
            forward = Vector3.forward;
            floorPoint = Vector3.zero;
            floorNormal = Vector3.up;
            note = "pose_failed";

            if (headTransform == null)
            {
                note = "head_transform_missing";
                return false;
            }

            if (floorPlaneSource == null || !floorPlaneSource.TryGetFloorPlane(out floorPoint, out floorNormal, out note))
            {
                note = "floor_plane_unavailable:" + note;
                return false;
            }

            floorNormal = floorNormal.sqrMagnitude > 0.0001f ? floorNormal.normalized : Vector3.up;
            forward = Vector3.ProjectOnPlane(headTransform.forward, floorNormal);
            if (forward.sqrMagnitude < 0.0001f)
            {
                forward = _hasSmoothedPose
                    ? _smoothedForward
                    : Vector3.ProjectOnPlane(headTransform.parent != null ? headTransform.parent.forward : Vector3.forward, floorNormal);
            }

            if (forward.sqrMagnitude < 0.0001f)
            {
                note = "forward_direction_unstable";
                return false;
            }

            forward.Normalize();
            origin = ProjectPointToPlane(
                headTransform.position + forward * Mathf.Max(0.2f, placementDistanceMeters),
                floorPoint,
                floorNormal);
            note = "pose_ready";
            return true;
        }

        private void StabilizePose(ref Vector3 origin, ref Vector3 forward)
        {
            if (!useStabilization)
            {
                return;
            }

            if (!_hasSmoothedPose)
            {
                _hasSmoothedPose = true;
                _smoothedOrigin = origin;
                _smoothedForward = forward.normalized;
                _smoothedOriginVelocity = Vector3.zero;
            }
            else
            {
                if (Vector3.Dot(forward, _smoothedForward) < 0.0f)
                {
                    forward = -forward;
                }

                var dt = Mathf.Max(0.001f, Time.deltaTime);
                var smoothTime = Mathf.Max(0.01f, smoothingSeconds);
                if (Vector3.Distance(origin, _smoothedOrigin) >= Mathf.Max(0.0f, positionDeadzoneMeters))
                {
                    _smoothedOrigin = Vector3.SmoothDamp(
                        _smoothedOrigin,
                        origin,
                        ref _smoothedOriginVelocity,
                        smoothTime,
                        Mathf.Infinity,
                        dt);
                }
                else
                {
                    _smoothedOriginVelocity = Vector3.zero;
                }

                if (Vector3.Angle(_smoothedForward, forward) >= Mathf.Max(0.0f, angleDeadzoneDegrees))
                {
                    var t = 1.0f - Mathf.Exp(-dt / smoothTime);
                    _smoothedForward = Vector3.Slerp(_smoothedForward, forward, t).normalized;
                }
            }

            origin = _smoothedOrigin;
            forward = _smoothedForward;
        }

        private void RecordPoseSample(Vector3 origin, Vector3 forward, Vector3 floorPoint, Vector3 floorNormal)
        {
            var now = Time.realtimeSinceStartup;
            _samples.Add(new PoseSample
            {
                time = now,
                origin = origin,
                forward = forward.normalized,
                floorPoint = floorPoint,
                floorNormal = floorNormal.normalized,
            });

            var cutoff = now - Mathf.Max(0.05f, releaseAverageSeconds);
            var removeCount = 0;
            while (removeCount < _samples.Count && _samples[removeCount].time < cutoff)
            {
                removeCount++;
            }

            if (removeCount > 0)
            {
                _samples.RemoveRange(0, removeCount);
            }
        }

        private bool TryGetReleasePose(
            out Vector3 origin,
            out Vector3 forward,
            out Vector3 floorPoint,
            out Vector3 floorNormal)
        {
            origin = Vector3.zero;
            forward = Vector3.forward;
            floorPoint = Vector3.zero;
            floorNormal = Vector3.up;

            if (_samples.Count == 0)
            {
                return false;
            }

            var cutoff = Time.realtimeSinceStartup - Mathf.Max(0.05f, releaseAverageSeconds);
            var originSum = Vector3.zero;
            var forwardSum = Vector3.zero;
            var floorPointSum = Vector3.zero;
            var floorNormalSum = Vector3.zero;
            var referenceForward = Vector3.zero;
            var count = 0;

            for (var index = 0; index < _samples.Count; index++)
            {
                var sample = _samples[index];
                if (sample.time < cutoff)
                {
                    continue;
                }

                var sampleForward = sample.forward;
                if (count == 0)
                {
                    referenceForward = sampleForward;
                }
                else if (Vector3.Dot(sampleForward, referenceForward) < 0.0f)
                {
                    sampleForward = -sampleForward;
                }

                originSum += sample.origin;
                forwardSum += sampleForward;
                floorPointSum += sample.floorPoint;
                floorNormalSum += sample.floorNormal;
                count++;
            }

            if (count <= 0)
            {
                return false;
            }

            origin = originSum / count;
            forward = forwardSum.sqrMagnitude > 0.0001f ? forwardSum.normalized : referenceForward.normalized;
            floorPoint = floorPointSum / count;
            floorNormal = floorNormalSum.sqrMagnitude > 0.0001f ? floorNormalSum.normalized : Vector3.up;
            origin = ProjectPointToPlane(origin, floorPoint, floorNormal);
            forward = Vector3.ProjectOnPlane(forward, floorNormal).normalized;
            return forward.sqrMagnitude > 0.0001f;
        }

        private StandaloneLaneLockResult BuildLaneResult(
            Vector3 origin,
            Vector3 forward,
            Vector3 floorPoint,
            Vector3 floorNormal,
            bool userConfirmed)
        {
            var rotation = Quaternion.LookRotation(forward.normalized, floorNormal.normalized);
            var requestId = "quest_lane_lock_" + DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            return new StandaloneLaneLockResult
            {
                sessionId = proofCapture != null ? proofCapture.ActiveSessionId : string.Empty,
                requestId = requestId,
                success = true,
                failureReason = string.Empty,
                confidence = userConfirmed ? 0.98f : 0.90f,
                lockState = userConfirmed ? "Locked" : "Candidate",
                requiresConfirmation = !userConfirmed,
                userConfirmed = userConfirmed,
                laneOriginWorld = origin,
                laneRotationWorld = rotation,
                laneWidthMeters = laneWidthMeters,
                laneLengthMeters = laneLengthMeters,
                floorPlanePointWorld = floorPoint,
                floorPlaneNormalWorld = floorNormal.normalized,
                visibleDownlaneMeters = laneLengthMeters,
                releaseCorridor = new StandaloneReleaseCorridor
                {
                    sStartMeters = 0.0f,
                    sEndMeters = Mathf.Min(headsSectionLengthMeters, laneLengthMeters),
                    halfWidthMeters = laneWidthMeters * 0.5f,
                },
                confidenceBreakdown = new StandaloneLaneLockConfidenceBreakdown
                {
                    edgeFit = 1.0f,
                    selectionAgreement = 1.0f,
                    markingAgreement = 1.0f,
                    temporalStability = 1.0f,
                    candidateMargin = 1.0f,
                    visibleExtent = 1.0f,
                },
                reprojectionMetrics = new StandaloneReprojectionMetrics
                {
                    meanErrorPx = 0.0f,
                    p95ErrorPx = 0.0f,
                    runnerUpMargin = 1.0f,
                },
                sourceFrameRange = new StandaloneSourceFrameRange { start = 0, end = 0 },
            };
        }

        private void RenderHeadsPreview(Vector3 origin, Vector3 forward, Vector3 floorNormal)
        {
            EnsurePreviewObjects();
            var rotation = Quaternion.LookRotation(forward.normalized, floorNormal.normalized);
            var halfWidth = Mathf.Max(0.01f, laneWidthMeters * 0.5f);
            var length = Mathf.Max(0.1f, headsSectionLengthMeters);
            var lift = Mathf.Max(0.0f, verticalOffsetMeters);

            var leftFoul = origin + rotation * new Vector3(-halfWidth, lift, 0.0f);
            var rightFoul = origin + rotation * new Vector3(halfWidth, lift, 0.0f);
            var rightHeads = origin + rotation * new Vector3(halfWidth, lift, length);
            var leftHeads = origin + rotation * new Vector3(-halfWidth, lift, length);

            UpdateLine(_headsOutlineRenderer, new[] { leftFoul, rightFoul, rightHeads, leftHeads, leftFoul });
            UpdateSurface(leftFoul, rightFoul, leftHeads, rightHeads);
        }

        private void EnsurePreviewObjects()
        {
            var parent = visualizationRoot != null ? visualizationRoot : transform;
            if (_headsSurfaceObject == null)
            {
                _headsSurfaceObject = new GameObject("LaneHeadsSectionSurface");
                _headsSurfaceObject.transform.SetParent(parent, false);
                _headsSurfaceMeshFilter = _headsSurfaceObject.AddComponent<MeshFilter>();
                _headsSurfaceMeshRenderer = _headsSurfaceObject.AddComponent<MeshRenderer>();
                _headsSurfaceMesh = new Mesh { name = "LaneHeadsSectionSurfaceMesh" };
                _headsSurfaceMeshFilter.sharedMesh = _headsSurfaceMesh;
            }

            if (_headsSurfaceMaterial == null)
            {
                _headsSurfaceMaterial = CreateColorMaterial("LaneHeadsSectionSurfaceMaterial", headsSurfaceColor, true);
            }

            _headsSurfaceMaterial.color = headsSurfaceColor;
            _headsSurfaceMeshRenderer.sharedMaterial = _headsSurfaceMaterial;

            if (_headsOutlineRenderer == null)
            {
                var lineObject = new GameObject("LaneHeadsSectionOutline");
                lineObject.transform.SetParent(parent, false);
                _headsOutlineRenderer = lineObject.AddComponent<LineRenderer>();
                _headsOutlineRenderer.useWorldSpace = true;
                _headsOutlineRenderer.numCapVertices = 4;
                _headsOutlineRenderer.numCornerVertices = 4;
            }

            if (_headsOutlineMaterial == null)
            {
                _headsOutlineMaterial = CreateColorMaterial("LaneHeadsSectionOutlineMaterial", headsOutlineColor, false);
            }

            _headsOutlineRenderer.sharedMaterial = _headsOutlineMaterial;
        }

        private void UpdateLine(LineRenderer renderer, Vector3[] points)
        {
            if (renderer == null)
            {
                return;
            }

            renderer.enabled = true;
            renderer.startColor = headsOutlineColor;
            renderer.endColor = headsOutlineColor;
            renderer.startWidth = Mathf.Max(0.004f, headsLineWidthMeters);
            renderer.endWidth = Mathf.Max(0.004f, headsLineWidthMeters);
            renderer.positionCount = points.Length;
            renderer.SetPositions(points);
        }

        private void UpdateSurface(Vector3 leftFoul, Vector3 rightFoul, Vector3 leftHeads, Vector3 rightHeads)
        {
            if (_headsSurfaceObject == null || _headsSurfaceMesh == null)
            {
                return;
            }

            _headsSurfaceObject.SetActive(true);
            var t = _headsSurfaceObject.transform;
            _headsSurfaceMesh.Clear();
            _headsSurfaceMesh.vertices = new[]
            {
                t.InverseTransformPoint(leftFoul),
                t.InverseTransformPoint(rightFoul),
                t.InverseTransformPoint(leftHeads),
                t.InverseTransformPoint(rightHeads),
            };
            _headsSurfaceMesh.triangles = new[] { 0, 2, 1, 1, 2, 3 };
            _headsSurfaceMesh.RecalculateBounds();
        }

        private void ClearHeadsPreview()
        {
            if (_headsOutlineRenderer != null)
            {
                _headsOutlineRenderer.enabled = false;
                _headsOutlineRenderer.positionCount = 0;
            }

            if (_headsSurfaceObject != null)
            {
                _headsSurfaceObject.SetActive(false);
            }
        }

        private bool TryApplyLaneLockToProofCapture(StandaloneLaneLockResult result, out string note)
        {
            note = "proof_capture_missing";
            if (proofCapture == null || result == null)
            {
                return false;
            }

            return proofCapture.TryApplyLaneLockResult(result, out note);
        }

        private void ClearProofCaptureLaneLock()
        {
            if (proofCapture == null)
            {
                return;
            }

            proofCapture.ClearLaneLock();
        }

        private bool TryPublishConfirmedLane(StandaloneLaneLockResult result, out string note)
        {
            note = "lane_metadata_sender_missing";
            if (liveMetadataSender == null)
            {
                return false;
            }

            if (proofCapture == null || string.IsNullOrWhiteSpace(proofCapture.ActiveSessionId))
            {
                note = "lane_session_not_active";
                return false;
            }

            return liveMetadataSender.TrySendLaneLockConfirm(
                proofCapture.ActiveSessionId,
                proofCapture.ActiveStreamId,
                result.requestId,
                true,
                "quest_lane_confirmed",
                result,
                out note);
        }

        private bool TryPublishLaneRejection(string requestId, string reason, out string note)
        {
            note = "lane_metadata_sender_missing";
            if (liveMetadataSender == null)
            {
                return false;
            }

            if (proofCapture == null || string.IsNullOrWhiteSpace(proofCapture.ActiveSessionId))
            {
                note = "lane_session_not_active";
                return false;
            }

            return liveMetadataSender.TrySendLaneLockConfirm(
                proofCapture.ActiveSessionId,
                proofCapture.ActiveStreamId,
                requestId,
                false,
                string.IsNullOrWhiteSpace(reason) ? "user_relock" : reason,
                out note);
        }

        private bool IsPinching()
        {
            var strength = handPinchSource != null && handPinchSource.IsTracked
                ? Mathf.Clamp01(handPinchSource.GetFingerPinchStrength(OVRHand.HandFinger.Index))
                : 0.0f;
            var threshold = _wasPinching
                ? Mathf.Max(0.05f, pinchReleaseThreshold)
                : Mathf.Max(0.05f, pinchPressThreshold);
            return strength >= threshold;
        }

        private void ResolveReferences()
        {
            if (floorPlaneSource == null)
            {
                floorPlaneSource = FindFirstObjectByType<StandaloneQuestFloorPlaneSource>();
            }

            if (proofCapture == null)
            {
                proofCapture = FindFirstObjectByType<StandaloneQuestLocalProofCapture>();
            }

            if (sessionController == null)
            {
                sessionController = FindFirstObjectByType<StandaloneQuestSessionController>();
            }

            if (liveMetadataSender == null)
            {
                liveMetadataSender = FindFirstObjectByType<StandaloneQuestLiveMetadataSender>();
            }

            if (liveResultReceiver == null)
            {
                liveResultReceiver = FindFirstObjectByType<StandaloneQuestLiveResultReceiver>();
            }

            if (laneRenderer == null)
            {
                laneRenderer = FindFirstObjectByType<StandaloneQuestLaneLockResultRenderer>();
            }

            if (headTransform == null && Camera.main != null)
            {
                headTransform = Camera.main.transform;
            }

            if (handPinchSource == null)
            {
                handPinchSource = FindFirstObjectByType<OVRHand>();
            }
        }

        private void ResetStabilization()
        {
            _samples.Clear();
            _hasSmoothedPose = false;
            _smoothedOrigin = Vector3.zero;
            _smoothedForward = Vector3.forward;
            _smoothedOriginVelocity = Vector3.zero;
        }

        private void Fail(string note)
        {
            CurrentConfirmedLaneLockRequestId = string.Empty;
            _ignorePinchUntilReleased = false;
            SetState(StandaloneQuestLaneLockUiState.Failed, note);
            ClearHeadsPreview();
            laneRenderer?.ClearVisualization(note);
            SetStatus("lane_lock_failed:" + note);
        }

        private void SetStatus(string status)
        {
            LastStatus = status ?? string.Empty;
            if (verboseLogging)
            {
                Debug.Log("[StandaloneQuestLaneLockStateCoordinator] " + LastStatus);
            }
        }

        private bool TryGetLaneInteractionReadiness(out string blockerLabel, out string reason)
        {
            blockerLabel = string.Empty;
            reason = "lane_interaction_ready";

            if (sessionController == null || !sessionController.IsSessionActive)
            {
                blockerLabel = "Laptop Connecting";
                reason = "session_not_active";
                return false;
            }

            if (!sessionController.TryGetLiveMediaReadiness(out var mediaReason))
            {
                blockerLabel = "Media Stream Not Ready";
                reason = string.IsNullOrWhiteSpace(mediaReason) ? "media_not_ready" : mediaReason;
                return false;
            }

            if (liveMetadataSender == null || !liveMetadataSender.IsConnected)
            {
                blockerLabel = "Metadata Reconnecting";
                reason = "metadata_not_connected";
                return false;
            }

            if (liveResultReceiver == null || !liveResultReceiver.IsConnected)
            {
                blockerLabel = "Results Reconnecting";
                reason = "results_not_connected";
                return false;
            }

            return true;
        }

        private bool IsLocalCancelAction(StandaloneQuestLaneLockActionKind actionKind)
        {
            return actionKind == StandaloneQuestLaneLockActionKind.Secondary
                && (State == StandaloneQuestLaneLockUiState.ArmedForPlacement ||
                    State == StandaloneQuestLaneLockUiState.FullLanePreview);
        }

        private void SetState(StandaloneQuestLaneLockUiState nextState, string reason)
        {
            if (State == nextState)
            {
                return;
            }

            State = nextState;
            StateChanged?.Invoke(State, string.IsNullOrWhiteSpace(reason) ? string.Empty : reason);
        }

        private static Vector3 ProjectPointToPlane(Vector3 point, Vector3 planePoint, Vector3 planeNormal)
        {
            return point - planeNormal * Vector3.Dot(point - planePoint, planeNormal);
        }

        private static Material CreateColorMaterial(string name, Color color, bool transparent)
        {
            var shader = Shader.Find("Unlit/Color");
            if (shader == null)
            {
                shader = Shader.Find("Sprites/Default");
            }

            var material = new Material(shader)
            {
                name = name,
                color = color,
            };

            if (transparent)
            {
                material.SetInt("_SrcBlend", (int)BlendMode.SrcAlpha);
                material.SetInt("_DstBlend", (int)BlendMode.OneMinusSrcAlpha);
                material.SetInt("_ZWrite", 0);
                material.SetInt("_Cull", (int)CullMode.Off);
                material.EnableKeyword("_ALPHABLEND_ON");
                material.renderQueue = (int)RenderQueue.Transparent;
            }

            return material;
        }

        private struct PoseSample
        {
            public float time;
            public Vector3 origin;
            public Vector3 forward;
            public Vector3 floorPoint;
            public Vector3 floorNormal;
        }
    }
}

