using System;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestShotReplayRenderer : MonoBehaviour
    {
        [Header("Result Source")]
        [SerializeField] private StandaloneQuestLiveResultReceiver liveResultReceiver;
        [SerializeField] private Transform replayRoot;

        [Header("Replay Shape")]
        [SerializeField] private float lineWidthMeters = 0.035f;
        [SerializeField] private float markerRadiusMeters = 0.11f;
        [SerializeField] private float verticalOffsetMeters = 0.035f;
        [SerializeField] private float calloutVerticalOffsetMeters = 0.34f;
        [SerializeField] private float calloutCharacterSizeMeters = 0.055f;
        [SerializeField] private float ghostLineWidthMeters = 0.018f;
        [SerializeField] private float minReplayDurationSeconds = 0.75f;
        [SerializeField] private float maxReplayDurationSeconds = 3.0f;
        [SerializeField] private bool clearOnFailedShotResult = true;

        [Header("Colors")]
        [SerializeField] private Color trajectoryColor = new Color(0.05f, 0.9f, 1.0f, 1.0f);
        [SerializeField] private Color markerColor = new Color(1.0f, 0.74f, 0.16f, 1.0f);
        [SerializeField] private Color ghostTrajectoryColor = new Color(0.56f, 0.68f, 0.72f, 0.42f);
        [SerializeField] private Color calloutTextColor = new Color(0.96f, 1.0f, 1.0f, 1.0f);
        [SerializeField] private Color calloutShadowColor = new Color(0.0f, 0.0f, 0.0f, 0.92f);

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging;

        private LineRenderer _lineRenderer;
        private LineRenderer _ghostLineRenderer;
        private GameObject _markerObject;
        private GameObject _calloutObject;
        private TextMesh _calloutText;
        private TextMesh _calloutShadowText;
        private Material _lineMaterial;
        private Material _ghostLineMaterial;
        private Material _markerMaterial;
        private Vector3[] _positions = Array.Empty<Vector3>();
        private StandaloneShotStatMilestone[] _milestones = Array.Empty<StandaloneShotStatMilestone>();
        private float _replayStartTime;
        private float _replayDurationSeconds = 1.0f;
        private bool _isReplaying;

        public string LastStatus { get; private set; } = string.Empty;
        public int RenderedPointCount => _positions.Length;
        public bool HasReplay { get; private set; }
        public bool HasGhostReplay { get; private set; }
        public bool IsReplaying => _isReplaying;

        private void Awake()
        {
            if (liveResultReceiver == null)
            {
                liveResultReceiver = FindFirstObjectByType<StandaloneQuestLiveResultReceiver>();
            }

            EnsureRenderObjects();
            ClearReplay("replay_renderer_ready");
        }

        private void OnEnable()
        {
            Subscribe();
        }

        private void OnDisable()
        {
            Unsubscribe();
        }

        private void OnDestroy()
        {
            Unsubscribe();

            if (_lineMaterial != null)
            {
                Destroy(_lineMaterial);
                _lineMaterial = null;
            }

            if (_ghostLineMaterial != null)
            {
                Destroy(_ghostLineMaterial);
                _ghostLineMaterial = null;
            }

            if (_markerMaterial != null)
            {
                Destroy(_markerMaterial);
                _markerMaterial = null;
            }
        }

        private void Update()
        {
            if (!_isReplaying || _positions.Length == 0 || _markerObject == null)
            {
                return;
            }

            if (_positions.Length == 1)
            {
                _markerObject.transform.position = _positions[0];
                _isReplaying = false;
                SetStatus("shot_replay_complete");
                return;
            }

            var elapsed = Time.time - _replayStartTime;
            var t = Mathf.Clamp01(elapsed / Mathf.Max(0.001f, _replayDurationSeconds));
            _markerObject.transform.position = SampleTrajectory(t);
            UpdateCallout(t);

            if (t >= 1.0f)
            {
                _isReplaying = false;
                UpdateCallout(1.0f);
                SetStatus("shot_replay_complete");
            }
        }

        public void RenderShotResult(StandaloneShotResult result)
        {
            if (result == null)
            {
                ClearReplay("shot_result_missing");
                return;
            }

            if (!result.success)
            {
                if (clearOnFailedShotResult)
                {
                    ClearReplay(result.failureReason);
                }

                SetStatus("shot_result_failed:" + (result.failureReason ?? string.Empty));
                return;
            }

            if (result.trajectory == null || result.trajectory.Length == 0)
            {
                ClearReplay("shot_result_empty_trajectory");
                return;
            }

            EnsureRenderObjects();

            _positions = BuildWorldPositions(result);
            _milestones = result.shotStats != null && result.shotStats.milestones != null
                ? result.shotStats.milestones
                : Array.Empty<StandaloneShotStatMilestone>();
            _replayDurationSeconds = ComputeReplayDurationSeconds(result);
            HasReplay = _positions.Length > 0;

            _lineRenderer.positionCount = _positions.Length;
            _lineRenderer.SetPositions(_positions);
            _lineRenderer.enabled = _positions.Length > 1;

            _markerObject.SetActive(true);
            _markerObject.transform.position = _positions[0];
            _markerObject.transform.localScale = Vector3.one * Mathf.Max(0.01f, markerRadiusMeters * 2.0f);

            StartReplay("shot_replay_started");
        }

        public void RenderGhostShotResult(StandaloneShotResult result)
        {
            if (result == null || result.trajectory == null || result.trajectory.Length < 2)
            {
                ClearGhostReplay();
                return;
            }

            EnsureRenderObjects();
            var positions = BuildWorldPositions(result);
            if (positions.Length < 2)
            {
                ClearGhostReplay();
                return;
            }

            _ghostLineRenderer.positionCount = positions.Length;
            _ghostLineRenderer.SetPositions(positions);
            _ghostLineRenderer.enabled = true;
            HasGhostReplay = true;
            SetStatus("shot_ghost_rendered");
        }

        public bool ReplayLatest(out string note)
        {
            note = "shot_replay_unavailable";

            if (!HasReplay || _positions.Length == 0)
            {
                return false;
            }

            StartReplay("shot_replay_restarted");
            note = "shot_replay_restarted";
            return true;
        }

        private void StartReplay(string status)
        {
            if (_positions.Length == 0 || _markerObject == null)
            {
                SetStatus("shot_replay_unavailable");
                return;
            }

            _markerObject.SetActive(true);
            _markerObject.transform.position = _positions[0];
            if (_lineRenderer != null)
            {
                _lineRenderer.enabled = _positions.Length > 1;
            }
            if (_calloutObject != null)
            {
                _calloutObject.SetActive(false);
            }

            _replayStartTime = Time.time;
            _isReplaying = true;
            UpdateCallout(0.0f);
            SetStatus($"{status} points={_positions.Length}");
        }

        public void ClearReplay(string reason)
        {
            _positions = Array.Empty<Vector3>();
            _milestones = Array.Empty<StandaloneShotStatMilestone>();
            _isReplaying = false;
            HasReplay = false;
            ClearGhostReplay();

            if (_lineRenderer != null)
            {
                _lineRenderer.positionCount = 0;
                _lineRenderer.enabled = false;
            }

            if (_markerObject != null)
            {
                _markerObject.SetActive(false);
            }

            if (_calloutObject != null)
            {
                _calloutObject.SetActive(false);
            }

            SetStatus(string.IsNullOrWhiteSpace(reason) ? "shot_replay_cleared" : reason);
        }

        public void ClearGhostReplay()
        {
            HasGhostReplay = false;
            if (_ghostLineRenderer != null)
            {
                _ghostLineRenderer.positionCount = 0;
                _ghostLineRenderer.enabled = false;
            }
        }

        private void Subscribe()
        {
            if (liveResultReceiver == null)
            {
                return;
            }

            liveResultReceiver.ShotResultReceived -= RenderShotResult;
            liveResultReceiver.ShotResultReceived += RenderShotResult;
        }

        private void Unsubscribe()
        {
            if (liveResultReceiver == null)
            {
                return;
            }

            liveResultReceiver.ShotResultReceived -= RenderShotResult;
        }

        private void EnsureRenderObjects()
        {
            var parent = replayRoot != null ? replayRoot : transform;

            if (_lineRenderer == null)
            {
                var lineObject = new GameObject("StandaloneShotReplayTrajectory");
                lineObject.transform.SetParent(parent, false);
                _lineRenderer = lineObject.AddComponent<LineRenderer>();
                _lineRenderer.useWorldSpace = true;
                _lineRenderer.numCornerVertices = 4;
                _lineRenderer.numCapVertices = 4;
                _lineRenderer.textureMode = LineTextureMode.Stretch;
            }

            _lineRenderer.startWidth = Mathf.Max(0.005f, lineWidthMeters);
            _lineRenderer.endWidth = Mathf.Max(0.005f, lineWidthMeters);
            _lineRenderer.startColor = trajectoryColor;
            _lineRenderer.endColor = trajectoryColor;

            if (_lineMaterial == null)
            {
                _lineMaterial = CreateColorMaterial("StandaloneShotReplayLineMaterial", trajectoryColor);
            }

            _lineMaterial.color = trajectoryColor;
            _lineRenderer.sharedMaterial = _lineMaterial;

            if (_ghostLineRenderer == null)
            {
                var ghostLineObject = new GameObject("StandaloneShotReplayGhostTrajectory");
                ghostLineObject.transform.SetParent(parent, false);
                _ghostLineRenderer = ghostLineObject.AddComponent<LineRenderer>();
                _ghostLineRenderer.useWorldSpace = true;
                _ghostLineRenderer.numCornerVertices = 3;
                _ghostLineRenderer.numCapVertices = 3;
                _ghostLineRenderer.textureMode = LineTextureMode.Stretch;
            }

            _ghostLineRenderer.startWidth = Mathf.Max(0.003f, ghostLineWidthMeters);
            _ghostLineRenderer.endWidth = Mathf.Max(0.003f, ghostLineWidthMeters);
            _ghostLineRenderer.startColor = ghostTrajectoryColor;
            _ghostLineRenderer.endColor = ghostTrajectoryColor;

            if (_ghostLineMaterial == null)
            {
                _ghostLineMaterial = CreateColorMaterial("StandaloneShotReplayGhostLineMaterial", ghostTrajectoryColor);
            }

            _ghostLineMaterial.color = ghostTrajectoryColor;
            _ghostLineRenderer.sharedMaterial = _ghostLineMaterial;

            if (_markerObject == null)
            {
                _markerObject = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                _markerObject.name = "StandaloneShotReplayMarker";
                _markerObject.transform.SetParent(parent, false);
                var markerCollider = _markerObject.GetComponent<Collider>();
                if (markerCollider != null)
                {
                    Destroy(markerCollider);
                }
            }

            if (_markerMaterial == null)
            {
                _markerMaterial = CreateColorMaterial("StandaloneShotReplayMarkerMaterial", markerColor);
            }

            _markerMaterial.color = markerColor;
            var renderer = _markerObject.GetComponent<Renderer>();
            if (renderer != null)
            {
                renderer.sharedMaterial = _markerMaterial;
            }

            if (_calloutObject == null)
            {
                _calloutObject = new GameObject("StandaloneShotReplayCallout");
                _calloutObject.transform.SetParent(parent, false);
                _calloutText = _calloutObject.AddComponent<TextMesh>();
                _calloutText.anchor = TextAnchor.MiddleCenter;
                _calloutText.alignment = TextAlignment.Center;
                _calloutText.fontSize = 96;
                _calloutText.characterSize = Mathf.Max(0.01f, calloutCharacterSizeMeters);
                _calloutText.color = calloutTextColor;

                var shadowObject = new GameObject("Shadow");
                shadowObject.transform.SetParent(_calloutObject.transform, false);
                shadowObject.transform.localPosition = new Vector3(0.018f, -0.018f, 0.018f);
                _calloutShadowText = shadowObject.AddComponent<TextMesh>();
                _calloutShadowText.anchor = TextAnchor.MiddleCenter;
                _calloutShadowText.alignment = TextAlignment.Center;
                _calloutShadowText.fontSize = 96;
                _calloutShadowText.characterSize = Mathf.Max(0.01f, calloutCharacterSizeMeters);
                _calloutShadowText.color = calloutShadowColor;
                _calloutObject.SetActive(false);
            }
        }

        private Vector3[] BuildWorldPositions(StandaloneShotResult result)
        {
            var points = result.trajectory;
            var positions = new Vector3[points.Length];
            var offset = Vector3.up * Mathf.Max(0.0f, verticalOffsetMeters);
            for (var i = 0; i < points.Length; i++)
            {
                positions[i] = points[i].worldPoint + offset;
            }

            return positions;
        }

        private float ComputeReplayDurationSeconds(StandaloneShotResult result)
        {
            var minDuration = Mathf.Max(0.05f, minReplayDurationSeconds);
            var maxDuration = Mathf.Max(minDuration, maxReplayDurationSeconds);
            var trajectory = result.trajectory;
            if (trajectory == null || trajectory.Length < 2)
            {
                return minDuration;
            }

            var firstPtsUs = trajectory[0].ptsUs;
            var lastPtsUs = trajectory[trajectory.Length - 1].ptsUs;
            var duration = (lastPtsUs - firstPtsUs) / 1000000.0f;
            return Mathf.Clamp(duration, minDuration, maxDuration);
        }

        private Vector3 SampleTrajectory(float normalizedTime)
        {
            if (_positions.Length == 0)
            {
                return Vector3.zero;
            }

            if (_positions.Length == 1)
            {
                return _positions[0];
            }

            var scaled = Mathf.Clamp01(normalizedTime) * (_positions.Length - 1);
            var startIndex = Mathf.FloorToInt(scaled);
            var endIndex = Mathf.Min(startIndex + 1, _positions.Length - 1);
            var localT = scaled - startIndex;
            return Vector3.Lerp(_positions[startIndex], _positions[endIndex], localT);
        }

        private void UpdateCallout(float normalizedTime)
        {
            if (_calloutObject == null || _calloutText == null || _positions.Length == 0 || _milestones.Length == 0)
            {
                return;
            }

            var milestone = ActiveMilestone(normalizedTime);
            if (milestone == null || string.IsNullOrWhiteSpace(milestone.primaryValue))
            {
                _calloutObject.SetActive(false);
                return;
            }

            var label = string.IsNullOrWhiteSpace(milestone.label) ? string.Empty : milestone.label.Trim();
            var value = milestone.primaryValue.Trim();
            var text = string.IsNullOrWhiteSpace(label) ? value : label + "\n" + value;
            _calloutText.text = text;
            _calloutText.characterSize = Mathf.Max(0.01f, calloutCharacterSizeMeters);
            _calloutText.color = calloutTextColor;
            if (_calloutShadowText != null)
            {
                _calloutShadowText.text = text;
                _calloutShadowText.characterSize = Mathf.Max(0.01f, calloutCharacterSizeMeters);
                _calloutShadowText.color = calloutShadowColor;
            }
            _calloutObject.transform.position = SampleTrajectory(milestone.normalizedReplayTime)
                + Vector3.up * Mathf.Max(0.0f, calloutVerticalOffsetMeters);
            FaceCamera(_calloutObject.transform);
            _calloutObject.SetActive(true);
        }

        private StandaloneShotStatMilestone ActiveMilestone(float normalizedTime)
        {
            StandaloneShotStatMilestone active = null;
            var bestTime = -1.0f;
            var t = Mathf.Clamp01(normalizedTime);
            for (var index = 0; index < _milestones.Length; index++)
            {
                var milestone = _milestones[index];
                if (milestone == null)
                {
                    continue;
                }

                var milestoneTime = Mathf.Clamp01(milestone.normalizedReplayTime);
                if (milestoneTime <= t + 0.025f && milestoneTime >= bestTime)
                {
                    bestTime = milestoneTime;
                    active = milestone;
                }
            }

            return active;
        }

        private void FaceCamera(Transform target)
        {
            if (target == null)
            {
                return;
            }

            var camera = Camera.main;
            if (camera == null)
            {
                return;
            }

            var toCamera = target.position - camera.transform.position;
            if (toCamera.sqrMagnitude <= 0.0001f)
            {
                return;
            }

            target.rotation = Quaternion.LookRotation(toCamera.normalized, Vector3.up);
        }

        private Material CreateColorMaterial(string materialName, Color color)
        {
            var shader = Shader.Find("Unlit/Color");
            if (shader == null)
            {
                shader = Shader.Find("Sprites/Default");
            }

            var material = new Material(shader)
            {
                name = materialName,
                color = color,
            };
            return material;
        }

        private void SetStatus(string status)
        {
            LastStatus = status ?? string.Empty;
            DebugLog(LastStatus);
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestShotReplayRenderer] {message}");
        }
    }
}
