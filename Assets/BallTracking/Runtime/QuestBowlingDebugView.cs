using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace BallTracking.Runtime
{
    public sealed class QuestBowlingDebugView : MonoBehaviour
    {
        [Serializable]
        private sealed class TrackerStatusPayload
        {
            public string kind;
            public string stage;
            public string shot_id;
            public int local_frame_idx;
            public int seed_frame;
            public int current_frame;
            public string message;
        }

        [Serializable]
        private sealed class ShotResultPayload
        {
            public string kind;
            public bool success;
            public string shot_id;
            public string failure_reason;
            public int tracked_frames;
            public int first_frame;
            public int last_frame;
            public PathSample[] path_samples;
        }

        [Serializable]
        private sealed class PathSample
        {
            public int frame_idx;
            public float centroid_x;
            public float centroid_y;
            public float bbox_x1;
            public float bbox_y1;
            public float bbox_x2;
            public float bbox_y2;
            public float area;
        }

        [Header("References")]
        [SerializeField] private QuestBowlingStreamClient streamClient;
        [SerializeField] private Transform anchor;

        [Header("Placement")]
        [SerializeField] private Vector3 localOffset = new(0f, 0.25f, 0.6f);
        [SerializeField] private bool faceMainCamera = true;

        [Header("Text")]
        [SerializeField] private int maxStatusLines = 6;
        [SerializeField] private int fontSize = 42;
        [SerializeField] private float characterSize = 0.008f;
        [SerializeField] private Color statusColor = Color.white;

        [Header("Debug Path")]
        [SerializeField] private bool drawDebugPath = true;
        [SerializeField] private float debugPathWidthMeters = 0.5f;
        [SerializeField] private float debugPathLengthMeters = 1.0f;
        [SerializeField] private float debugPathHeightMeters = 0.05f;
        [SerializeField] private float lineWidth = 0.01f;
        [SerializeField] private Color successPathColor = new(0.2f, 1f, 0.35f, 0.95f);
        [SerializeField] private Color failurePathColor = new(1f, 0.35f, 0.2f, 0.95f);

        private readonly Queue<string> _statusLines = new();
        private Transform _root;
        private TextMesh _textMesh;
        private LineRenderer _lineRenderer;
        private Camera _mainCamera;
        private string _lastMirroredClientStatus;

        public void ConfigureForRuntime(QuestBowlingStreamClient client, Transform runtimeAnchor)
        {
            if (streamClient != null)
            {
                streamClient.TrackerStatusReceived -= HandleTrackerStatus;
                streamClient.ShotResultReceived -= HandleShotResult;
            }

            streamClient = client;
            if (runtimeAnchor != null)
            {
                anchor = runtimeAnchor;
            }

            if (streamClient != null && isActiveAndEnabled)
            {
                streamClient.TrackerStatusReceived += HandleTrackerStatus;
                streamClient.ShotResultReceived += HandleShotResult;
            }

            ShowStartupMessage();
        }

        private void Awake()
        {
            Debug.Log("[QuestBowlingDebugView] Awake");
            if (anchor == null)
            {
                anchor = transform;
            }

            EnsureVisuals();
            ShowStartupMessage();
        }

        private void OnEnable()
        {
            Debug.Log("[QuestBowlingDebugView] OnEnable");
            if (streamClient == null)
            {
                streamClient = FindFirstObjectByType<QuestBowlingStreamClient>();
            }

            if (streamClient != null)
            {
                streamClient.TrackerStatusReceived += HandleTrackerStatus;
                streamClient.ShotResultReceived += HandleShotResult;
            }
        }

        private void OnDisable()
        {
            if (streamClient != null)
            {
                streamClient.TrackerStatusReceived -= HandleTrackerStatus;
                streamClient.ShotResultReceived -= HandleShotResult;
            }
        }

        private void LateUpdate()
        {
            if (_root == null)
            {
                return;
            }

            MirrorClientStatusIfNeeded();
            _root.position = anchor.TransformPoint(localOffset);
            if (!faceMainCamera)
            {
                return;
            }

            _mainCamera ??= Camera.main;
            if (_mainCamera == null)
            {
                return;
            }

            var forward = (_root.position - _mainCamera.transform.position).normalized;
            if (forward.sqrMagnitude > 0.001f)
            {
                _root.rotation = Quaternion.LookRotation(forward, Vector3.up);
            }
        }

        private void HandleTrackerStatus(string json)
        {
            EnsureVisuals();

            TrackerStatusPayload payload = null;
            try
            {
                payload = JsonUtility.FromJson<TrackerStatusPayload>(json);
            }
            catch
            {
            }

            if (payload == null || string.IsNullOrEmpty(payload.stage))
            {
                PushStatus(json);
                return;
            }

            var builder = new StringBuilder();
            builder.Append(payload.stage);
            if (!string.IsNullOrEmpty(payload.shot_id) &&
                !string.Equals(payload.shot_id, "default-shot", StringComparison.OrdinalIgnoreCase))
            {
                builder.Append(" | ").Append(payload.shot_id);
            }
            if (payload.seed_frame > 0)
            {
                builder.Append(" | seed ").Append(payload.seed_frame);
            }
            if (payload.current_frame > 0)
            {
                builder.Append(" | frame ").Append(payload.current_frame);
            }
            if (!string.IsNullOrEmpty(payload.message))
            {
                builder.Append(" | ").Append(payload.message);
            }

            PushStatus(builder.ToString());
        }

        private void HandleShotResult(string json)
        {
            EnsureVisuals();

            ShotResultPayload payload = null;
            try
            {
                payload = JsonUtility.FromJson<ShotResultPayload>(json);
            }
            catch
            {
            }

            if (payload == null)
            {
                PushStatus("shot_result received");
                return;
            }

            PushStatus(
                payload.success
                    ? $"result ok | tracked {payload.tracked_frames} | {payload.first_frame}->{payload.last_frame}"
                    : $"result failed | {payload.failure_reason}");

            if (drawDebugPath)
            {
                DrawDebugPath(payload);
            }
        }

        private void DrawDebugPath(ShotResultPayload payload)
        {
            if (_lineRenderer == null)
            {
                return;
            }

            var samples = payload.path_samples;
            if (samples == null || samples.Length == 0)
            {
                _lineRenderer.positionCount = 0;
                return;
            }

            float minX = samples[0].centroid_x;
            float maxX = samples[0].centroid_x;
            float minY = samples[0].centroid_y;
            float maxY = samples[0].centroid_y;
            for (var i = 1; i < samples.Length; i++)
            {
                minX = Mathf.Min(minX, samples[i].centroid_x);
                maxX = Mathf.Max(maxX, samples[i].centroid_x);
                minY = Mathf.Min(minY, samples[i].centroid_y);
                maxY = Mathf.Max(maxY, samples[i].centroid_y);
            }

            var xRange = Mathf.Max(1f, maxX - minX);
            var yRange = Mathf.Max(1f, maxY - minY);

            _lineRenderer.positionCount = samples.Length;
            _lineRenderer.startColor = payload.success ? successPathColor : failurePathColor;
            _lineRenderer.endColor = payload.success ? successPathColor : failurePathColor;

            for (var i = 0; i < samples.Length; i++)
            {
                var sample = samples[i];
                var x01 = (sample.centroid_x - minX) / xRange;
                var y01 = (sample.centroid_y - minY) / yRange;
                var z01 = samples.Length == 1 ? 0f : i / (float)(samples.Length - 1);

                var localPoint = new Vector3(
                    (x01 - 0.5f) * debugPathWidthMeters,
                    y01 * debugPathHeightMeters,
                    z01 * debugPathLengthMeters);

                _lineRenderer.SetPosition(i, localPoint);
            }
        }

        private void PushStatus(string line)
        {
            if (_statusLines.Count >= maxStatusLines)
            {
                _statusLines.Dequeue();
            }

            _statusLines.Enqueue(line);
            RefreshText();
        }

        private void RefreshText()
        {
            if (_textMesh == null)
            {
                return;
            }

            var builder = new StringBuilder();
            foreach (var line in _statusLines)
            {
                if (builder.Length > 0)
                {
                    builder.Append('\n');
                }
                builder.Append(line);
            }

            _textMesh.text = builder.ToString();
        }

        private void ShowStartupMessage()
        {
            if (_textMesh == null)
            {
                return;
            }

            _statusLines.Clear();
            PushStatus("Bowling Tracker");

            if (streamClient != null)
            {
                PushStatus($"Signal {streamClient.ServerHost}:{streamClient.ServerPort}");
                PushStatus(streamClient.LatestStatusLine);
            }
            else
            {
                PushStatus("Stream client missing");
            }

            PushStatus("Menu: calibrate");
            PushStatus("X: start shot");
            PushStatus("Y: end shot");
            PushStatus("L-stick click: calibrate");
        }

        private void EnsureVisuals()
        {
            if (_root != null)
            {
                return;
            }

            var rootObject = new GameObject("QuestBowlingDebugViewRoot");
            _root = rootObject.transform;
            _root.SetParent(anchor == null ? transform : anchor, false);
            _root.localPosition = localOffset;

            var textObject = new GameObject("StatusText");
            textObject.transform.SetParent(_root, false);
            _textMesh = textObject.AddComponent<TextMesh>();
            _textMesh.fontSize = fontSize;
            _textMesh.characterSize = characterSize;
            _textMesh.anchor = TextAnchor.UpperCenter;
            _textMesh.alignment = TextAlignment.Center;
            _textMesh.color = statusColor;

            var lineObject = new GameObject("DebugPath");
            lineObject.transform.SetParent(_root, false);
            _lineRenderer = lineObject.AddComponent<LineRenderer>();
            _lineRenderer.useWorldSpace = false;
            _lineRenderer.alignment = LineAlignment.View;
            _lineRenderer.widthMultiplier = lineWidth;
            _lineRenderer.material = CreateLineMaterial();
            _lineRenderer.positionCount = 0;
        }

        private void MirrorClientStatusIfNeeded()
        {
            if (streamClient == null)
            {
                return;
            }

            var latest = streamClient.LatestStatusLine;
            if (string.IsNullOrWhiteSpace(latest) || string.Equals(latest, _lastMirroredClientStatus, StringComparison.Ordinal))
            {
                return;
            }

            _lastMirroredClientStatus = latest;
            PushStatus(latest);
        }

        private static Material CreateLineMaterial()
        {
            var shader = Shader.Find("Unlit/Color") ?? Shader.Find("Sprites/Default") ?? Shader.Find("Standard");
            return new Material(shader);
        }
    }
}
