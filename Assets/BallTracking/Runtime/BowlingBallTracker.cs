using System.Collections;
using System.Collections.Generic;
using PassthroughCameraSamples.MultiObjectDetection;
using UnityEngine;
using UnityEngine.UI;

namespace BallTracking.Runtime
{
    public sealed class BowlingBallTracker : MonoBehaviour
    {
        [Header("Target Selection")]
        [SerializeField] private string targetClassName = "sports_ball";
        [SerializeField] private float maxDetectionAgeSeconds = 0.25f;

        [Header("Motion Smoothing")]
        [SerializeField] private float positionSmoothing = 16f;
        [SerializeField] private float velocitySmoothing = 12f;
        [SerializeField] private float predictionWindowSeconds = 0.2f;

        [Header("Marker")]
        [SerializeField] private float markerScaleMultiplier = 0.35f;
        [SerializeField] private float minimumMarkerScale = 0.04f;
        [SerializeField] private float maximumMarkerScale = 0.18f;
        [SerializeField] private Color markerVisibleColor = new(0.95f, 0.45f, 0.12f, 0.95f);
        [SerializeField] private Color markerPredictedColor = new(1f, 0.85f, 0.15f, 0.8f);
        [SerializeField] private Color targetBoxColor = new(1f, 0.5f, 0.15f, 0.9f);
        [SerializeField] private Color nonTargetBoxColor = new(1f, 1f, 1f, 0.15f);

        [Header("Debug Status")]
        [SerializeField] private Vector3 statusHudLocalPosition = new(0f, -0.14f, 1.1f);
        [SerializeField] private Color statusTextColor = new(1f, 1f, 1f, 0.95f);
        [SerializeField] private float statusLogIntervalSeconds = 3f;

        private SentisInferenceUiManager uiManager;
        private DetectionUiMenuManager menuManager;
        private Transform markerRoot;
        private Renderer markerRenderer;
        private TrailRenderer markerTrail;
        private TextMesh markerText;
        private Material markerMaterial;
        private Transform statusRoot;
        private TextMesh statusText;

        private Vector3 smoothedPosition;
        private Vector3 lastRawPosition;
        private Vector3 smoothedVelocity;
        private float lastSeenTime = float.NegativeInfinity;
        private float nextStatusLogTime;
        private bool hasTrack;
        private bool hadTargetLastFrame;

        private IEnumerator Start()
        {
            while ((uiManager = FindFirstObjectByType<SentisInferenceUiManager>()) == null ||
                   (menuManager = FindFirstObjectByType<DetectionUiMenuManager>()) == null)
            {
                yield return null;
            }

            EnsureMarker();
            EnsureStatusHud();
            StartCoroutine(AutoStartDetectionSession());

            Debug.Log(
                $"[{nameof(BowlingBallTracker)}] Running Meta's sample YOLOv9t COCO detector. " +
                $"Current target class: '{targetClassName}'. Bowling balls are not trained explicitly yet. " +
                "Quick smoke-test classes: person, chair, cup, bottle, sports_ball.");
        }

        private void Update()
        {
            if (uiManager == null)
            {
                return;
            }

            EnsureStatusHud();
            var targetBox = SelectTargetBox();
            UpdateBoxHighlighting(targetBox);
            UpdateStatusDisplay(targetBox);

            if (targetBox != null)
            {
                UpdateFromDetection(targetBox);
                return;
            }

            UpdatePredictionOnly();
        }

        private IEnumerator AutoStartDetectionSession()
        {
            while (menuManager == null)
            {
                menuManager = FindFirstObjectByType<DetectionUiMenuManager>();
                yield return null;
            }

            while (!menuManager.TryStartDetectionSession())
            {
                yield return null;
            }

            Debug.Log($"[{nameof(BowlingBallTracker)}] Detection session auto-started after permissions were granted.");
        }

        private SentisInferenceUiManager.BoundingBoxData SelectTargetBox()
        {
            SentisInferenceUiManager.BoundingBoxData bestBox = null;
            var bestScore = float.NegativeInfinity;

            foreach (var box in uiManager.m_boxDrawn)
            {
                if (!string.Equals(box.ClassName, targetClassName, System.StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                if (Time.time - box.lastUpdateTime > maxDetectionAgeSeconds)
                {
                    continue;
                }

                var worldPosition = box.BoxRectTransform.position;
                var area = box.BoxRectTransform.sizeDelta.x * box.BoxRectTransform.sizeDelta.y;
                var score = area;

                if (hasTrack)
                {
                    var distancePenalty = Vector3.SqrMagnitude(worldPosition - smoothedPosition) * 3f;
                    score -= distancePenalty;
                }

                if (score > bestScore)
                {
                    bestScore = score;
                    bestBox = box;
                }
            }

            return bestBox;
        }

        private void UpdateFromDetection(SentisInferenceUiManager.BoundingBoxData targetBox)
        {
            EnsureMarker();

            var rawPosition = targetBox.BoxRectTransform.position;
            var deltaTime = Mathf.Max(Time.deltaTime, 0.0001f);

            if (!hasTrack)
            {
                smoothedPosition = rawPosition;
                lastRawPosition = rawPosition;
                smoothedVelocity = Vector3.zero;
                hasTrack = true;
            }
            else
            {
                var rawVelocity = (rawPosition - lastRawPosition) / deltaTime;
                smoothedVelocity = Damp(smoothedVelocity, rawVelocity, velocitySmoothing, deltaTime);
                smoothedPosition = Damp(smoothedPosition, rawPosition, positionSmoothing, deltaTime);
                lastRawPosition = rawPosition;
            }

            lastSeenTime = Time.time;
            markerRoot.gameObject.SetActive(true);
            markerRoot.SetPositionAndRotation(smoothedPosition, targetBox.BoxRectTransform.rotation);

            var markerScale = Mathf.Clamp(
                Mathf.Min(targetBox.BoxRectTransform.sizeDelta.x, targetBox.BoxRectTransform.sizeDelta.y) * markerScaleMultiplier,
                minimumMarkerScale,
                maximumMarkerScale);
            markerRoot.localScale = Vector3.one * markerScale;

            SetMarkerColor(markerVisibleColor);
            markerText.text = $"target: {targetClassName}\nworld: {smoothedPosition:F2}\nvel: {smoothedVelocity.magnitude:F2} m/s";
        }

        private void UpdatePredictionOnly()
        {
            if (!hasTrack)
            {
                return;
            }

            var age = Time.time - lastSeenTime;
            if (age > predictionWindowSeconds)
            {
                hasTrack = false;
                markerRoot.gameObject.SetActive(false);
                return;
            }

            smoothedPosition += smoothedVelocity * Time.deltaTime;
            markerRoot.gameObject.SetActive(true);
            markerRoot.position = smoothedPosition;
            SetMarkerColor(markerPredictedColor);
            markerText.text = $"target: {targetClassName}\nstate: predicted\nvel: {smoothedVelocity.magnitude:F2} m/s";
        }

        private void UpdateStatusDisplay(SentisInferenceUiManager.BoundingBoxData targetBox)
        {
            if (statusText == null)
            {
                return;
            }

            var recentLabels = CollectRecentLabels();
            var sessionState = menuManager != null && !menuManager.IsPaused ? "running" : "waiting";
            var visibleLabels = recentLabels.Count == 0 ? "none" : string.Join(", ", recentLabels);
            var targetState = targetBox != null ? "acquired" : hasTrack ? "predicted only" : "none";

            statusText.text =
                "Quest 3 Ball Tracking\n" +
                $"session: {sessionState}\n" +
                "model: sample YOLOv9t COCO\n" +
                $"target: {targetClassName}\n" +
                $"track: {targetState}\n" +
                $"visible: {visibleLabels}\n" +
                "try: person, chair, cup, bottle, sports ball";

            var hasTarget = targetBox != null;
            if (hasTarget != hadTargetLastFrame)
            {
                Debug.Log(
                    hasTarget
                        ? $"[{nameof(BowlingBallTracker)}] Target '{targetClassName}' acquired."
                        : $"[{nameof(BowlingBallTracker)}] Target '{targetClassName}' lost.");
                hadTargetLastFrame = hasTarget;
            }

            if (Time.time < nextStatusLogTime)
            {
                return;
            }

            nextStatusLogTime = Time.time + statusLogIntervalSeconds;
            Debug.Log(
                $"[{nameof(BowlingBallTracker)}] session={sessionState}, target={targetState}, visible={visibleLabels}.");
        }

        private void UpdateBoxHighlighting(SentisInferenceUiManager.BoundingBoxData targetBox)
        {
            foreach (var box in uiManager.m_boxDrawn)
            {
                var isTargetClass = string.Equals(box.ClassName, targetClassName, System.StringComparison.OrdinalIgnoreCase);
                var tint = box == targetBox && isTargetClass ? targetBoxColor : nonTargetBoxColor;

                foreach (var image in box.BoxRectTransform.GetComponentsInChildren<Image>(true))
                {
                    image.color = tint;
                }

                foreach (var text in box.BoxRectTransform.GetComponentsInChildren<Text>(true))
                {
                    if (isTargetClass)
                    {
                        text.text = box == targetBox ? "sports_ball (tracked)" : "sports_ball";
                    }

                    text.color = box == targetBox ? targetBoxColor : Color.white;
                }
            }
        }

        private List<string> CollectRecentLabels()
        {
            var labels = new List<string>();
            if (uiManager == null)
            {
                return labels;
            }

            var recentDetectionWindow = Mathf.Max(maxDetectionAgeSeconds, 1f);
            foreach (var box in uiManager.m_boxDrawn)
            {
                if (Time.time - box.lastUpdateTime > recentDetectionWindow)
                {
                    continue;
                }

                if (labels.Contains(box.ClassName))
                {
                    continue;
                }

                labels.Add(box.ClassName);
                if (labels.Count >= 5)
                {
                    break;
                }
            }

            return labels;
        }

        private void EnsureMarker()
        {
            if (markerRoot != null)
            {
                return;
            }

            var rootObject = new GameObject("BowlingBallMarker");
            markerRoot = rootObject.transform;

            var sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            sphere.name = "MarkerVisual";
            sphere.transform.SetParent(markerRoot, false);
            Destroy(sphere.GetComponent<Collider>());

            markerRenderer = sphere.GetComponent<Renderer>();
            markerMaterial = CreateMarkerMaterial();
            markerRenderer.material = markerMaterial;

            markerTrail = rootObject.AddComponent<TrailRenderer>();
            markerTrail.time = 0.35f;
            markerTrail.startWidth = 0.035f;
            markerTrail.endWidth = 0.005f;
            markerTrail.minVertexDistance = 0.015f;
            markerTrail.material = markerMaterial;
            markerTrail.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            markerTrail.receiveShadows = false;

            var labelObject = new GameObject("MarkerLabel");
            labelObject.transform.SetParent(markerRoot, false);
            labelObject.transform.localPosition = new Vector3(0f, 0.08f, 0f);
            markerText = labelObject.AddComponent<TextMesh>();
            markerText.fontSize = 32;
            markerText.characterSize = 0.01f;
            markerText.anchor = TextAnchor.MiddleCenter;
            markerText.alignment = TextAlignment.Center;
            markerText.color = Color.white;

            markerRoot.gameObject.SetActive(false);
        }

        private void EnsureStatusHud()
        {
            if (statusRoot != null)
            {
                var cameraTransform = GetHudAnchor();
                if (cameraTransform != null && statusRoot.parent != cameraTransform)
                {
                    statusRoot.SetParent(cameraTransform, false);
                    statusRoot.localPosition = statusHudLocalPosition;
                    statusRoot.localRotation = Quaternion.identity;
                }

                return;
            }

            var anchor = GetHudAnchor();
            if (anchor == null)
            {
                return;
            }

            var rootObject = new GameObject("BowlingBallStatusHud");
            statusRoot = rootObject.transform;
            statusRoot.SetParent(anchor, false);
            statusRoot.localPosition = statusHudLocalPosition;
            statusRoot.localRotation = Quaternion.identity;

            statusText = rootObject.AddComponent<TextMesh>();
            statusText.fontSize = 48;
            statusText.characterSize = 0.006f;
            statusText.anchor = TextAnchor.MiddleCenter;
            statusText.alignment = TextAlignment.Center;
            statusText.color = statusTextColor;
        }

        private static Transform GetHudAnchor()
        {
            if (Camera.main != null)
            {
                return Camera.main.transform;
            }

            var anyCamera = UnityEngine.Object.FindFirstObjectByType<Camera>();
            return anyCamera != null ? anyCamera.transform : null;
        }

        private Material CreateMarkerMaterial()
        {
            var shader = Shader.Find("Unlit/Color") ?? Shader.Find("Sprites/Default") ?? Shader.Find("Standard");
            var material = new Material(shader);
            material.color = markerVisibleColor;
            return material;
        }

        private void SetMarkerColor(Color color)
        {
            if (markerMaterial != null)
            {
                markerMaterial.color = color;
            }

            if (markerTrail != null)
            {
                markerTrail.startColor = color;
                markerTrail.endColor = new Color(color.r, color.g, color.b, 0f);
            }
        }

        private static Vector3 Damp(Vector3 current, Vector3 target, float sharpness, float deltaTime)
        {
            var t = 1f - Mathf.Exp(-sharpness * deltaTime);
            return Vector3.Lerp(current, target, t);
        }

        private void OnDestroy()
        {
            if (markerMaterial != null)
            {
                Destroy(markerMaterial);
            }

            if (statusRoot != null)
            {
                Destroy(statusRoot.gameObject);
            }
        }
    }
}
