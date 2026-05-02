using UnityEngine;
using UnityEngine.UI;

namespace QuestBowlingStandalone.QuestApp
{
    [RequireComponent(typeof(RectTransform))]
    public sealed class StandaloneQuestExperienceStatusStrip : MonoBehaviour
    {
        [SerializeField] private StandaloneQuestSessionController sessionController;
        [SerializeField] private StandaloneQuestLaneLockStateCoordinator laneLockCoordinator;
        [SerializeField] private StandaloneQuestLiveResultReceiver liveResultReceiver;
        [SerializeField] private StandaloneQuestShotReplayList shotReplayList;
        [SerializeField] private StandaloneQuestShotReplayRenderer shotReplayRenderer;
        [SerializeField] private StandaloneQuestSessionReviewPanel sessionReviewPanel;
        [SerializeField] private Image background;
        [SerializeField] private Text label;
        [SerializeField] private Color backgroundColor = new Color(0.015f, 0.035f, 0.04f, 0.62f);
        [SerializeField] private Color readyColor = new Color(0.82f, 1.0f, 0.92f, 1.0f);
        [SerializeField] private Color attentionColor = new Color(1.0f, 0.86f, 0.48f, 1.0f);
        [SerializeField] private float refreshIntervalSeconds = 0.20f;

        private float _nextRefreshAt;

        public string LastDisplayText { get; private set; } = string.Empty;

        private void Awake()
        {
            ResolveReferences();
            EnsureUi();
            Refresh();
        }

        private void Update()
        {
            if (Time.unscaledTime < _nextRefreshAt)
            {
                return;
            }

            _nextRefreshAt = Time.unscaledTime + Mathf.Max(0.05f, refreshIntervalSeconds);
            Refresh();
        }

        private void ResolveReferences()
        {
            if (sessionController == null)
            {
                sessionController = FindFirstObjectByType<StandaloneQuestSessionController>();
            }

            if (laneLockCoordinator == null)
            {
                laneLockCoordinator = FindFirstObjectByType<StandaloneQuestLaneLockStateCoordinator>();
            }

            if (liveResultReceiver == null)
            {
                liveResultReceiver = FindFirstObjectByType<StandaloneQuestLiveResultReceiver>();
            }

            if (shotReplayList == null)
            {
                shotReplayList = FindFirstObjectByType<StandaloneQuestShotReplayList>();
            }

            if (shotReplayRenderer == null)
            {
                shotReplayRenderer = FindFirstObjectByType<StandaloneQuestShotReplayRenderer>();
            }

            if (sessionReviewPanel == null)
            {
                sessionReviewPanel = FindFirstObjectByType<StandaloneQuestSessionReviewPanel>();
            }
        }

        private void EnsureUi()
        {
            if (background == null)
            {
                background = GetComponent<Image>();
                if (background == null)
                {
                    background = gameObject.AddComponent<Image>();
                }
            }

            background.color = backgroundColor;
            background.raycastTarget = false;

            if (label == null)
            {
                var existing = transform.Find("StatusLabel");
                if (existing != null)
                {
                    label = existing.GetComponent<Text>();
                }
            }

            if (label == null)
            {
                var labelObject = new GameObject("StatusLabel", typeof(RectTransform), typeof(CanvasRenderer), typeof(Text));
                labelObject.transform.SetParent(transform, false);
                labelObject.layer = gameObject.layer;
                label = labelObject.GetComponent<Text>();
            }

            var rect = label.GetComponent<RectTransform>();
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.offsetMin = new Vector2(16.0f, 6.0f);
            rect.offsetMax = new Vector2(-16.0f, -6.0f);

            label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            label.alignment = TextAnchor.MiddleLeft;
            label.fontSize = 22;
            label.resizeTextForBestFit = false;
            label.horizontalOverflow = HorizontalWrapMode.Wrap;
            label.verticalOverflow = VerticalWrapMode.Truncate;
            label.lineSpacing = 0.9f;
            label.raycastTarget = false;
        }

        private void Refresh()
        {
            ResolveReferences();
            EnsureUi();

            var connected = sessionController != null && sessionController.IsSessionActive;
            var laneReady = laneLockCoordinator != null && laneLockCoordinator.State == StandaloneQuestLaneLockUiState.Locked;
            var shotCount = shotReplayList != null ? shotReplayList.ShotCount : 0;
            var shotState = ResolveShotState(laneReady);
            var displayText =
                "Laptop  " + (connected ? "Connected" : "Connecting") + "\n"
                + "Lane    " + ResolveLaneState() + "\n"
                + "Shot    " + shotState + "\n"
                + "Shots   " + shotCount;

            LastDisplayText = displayText;
            label.text = displayText;
            label.color = connected && laneReady ? readyColor : attentionColor;
        }

        private string ResolveLaneState()
        {
            if (laneLockCoordinator == null)
            {
                return "Needed";
            }

            switch (laneLockCoordinator.State)
            {
                case StandaloneQuestLaneLockUiState.PlacingHeads:
                    return "Placing";
                case StandaloneQuestLaneLockUiState.FullLanePreview:
                    return "Preview";
                case StandaloneQuestLaneLockUiState.Locked:
                    return "Locked";
                case StandaloneQuestLaneLockUiState.Failed:
                    return "Retry";
                default:
                    return "Needed";
            }
        }

        private string ResolveShotState(bool laneReady)
        {
            if (sessionReviewPanel != null && sessionReviewPanel.IsVisible)
            {
                return "Review";
            }

            if (shotReplayRenderer != null && shotReplayRenderer.IsReplaying)
            {
                return "Replay";
            }

            if (!laneReady)
            {
                return "Lock Lane";
            }

            var result = liveResultReceiver != null ? liveResultReceiver.LastShotResult : null;
            if (result != null && !result.success)
            {
                return FailureToLabel(result.failureReason);
            }

            return "Ready";
        }

        private static string FailureToLabel(string failureReason)
        {
            if (string.IsNullOrWhiteSpace(failureReason))
            {
                return "Try Again";
            }

            if (failureReason.StartsWith("yolo_detection_failed"))
            {
                return "Ball Missing";
            }

            if (failureReason.StartsWith("sam2_tracking_failed"))
            {
                return "Track Lost";
            }

            if (failureReason.StartsWith("lane_lock"))
            {
                return "Lock Lane";
            }

            return "Replay Wait";
        }
    }
}
