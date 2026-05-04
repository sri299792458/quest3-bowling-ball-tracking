using UnityEngine;
using UnityEngine.UI;

namespace QuestBowlingStandalone.QuestApp
{
    [RequireComponent(typeof(RectTransform))]
    public sealed class StandaloneQuestExperienceStatusStrip : MonoBehaviour
    {
        [SerializeField] private StandaloneQuestSessionController sessionController;
        [SerializeField] private StandaloneQuestLaneLockStateCoordinator laneLockCoordinator;
        [SerializeField] private StandaloneQuestLiveMetadataSender liveMetadataSender;
        [SerializeField] private StandaloneQuestLiveResultReceiver liveResultReceiver;
        [SerializeField] private StandaloneQuestShotReplayList shotReplayList;
        [SerializeField] private StandaloneQuestShotReplayRenderer shotReplayRenderer;
        [SerializeField] private StandaloneQuestSessionReviewPanel sessionReviewPanel;
        [SerializeField] private Image background;
        [SerializeField] private Text label;
        [SerializeField] private Color backgroundColor = new Color(0.055f, 0.066f, 0.072f, 0.58f);
        [SerializeField] private Color readyBackgroundColor = new Color(0.035f, 0.15f, 0.10f, 0.70f);
        [SerializeField] private Color blockedBackgroundColor = new Color(0.12f, 0.095f, 0.045f, 0.70f);
        [SerializeField] private Color reviewBackgroundColor = new Color(0.055f, 0.075f, 0.12f, 0.70f);
        [SerializeField] private Color readyColor = new Color(0.78f, 1.0f, 0.88f, 1.0f);
        [SerializeField] private Color attentionColor = new Color(1.0f, 0.86f, 0.50f, 1.0f);
        [SerializeField] private float refreshIntervalSeconds = 0.20f;

        private float _nextRefreshAt;

        public string LastDisplayText { get; private set; } = string.Empty;
        public string LastReadinessReason { get; private set; } = string.Empty;
        public bool IsShotReady { get; private set; }
        public StandaloneQuestExperienceState LastState { get; private set; }

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

            if (liveMetadataSender == null)
            {
                liveMetadataSender = FindFirstObjectByType<StandaloneQuestLiveMetadataSender>();
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
            rect.offsetMin = new Vector2(18.0f, 8.0f);
            rect.offsetMax = new Vector2(-18.0f, -8.0f);

            label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            label.alignment = TextAnchor.MiddleCenter;
            label.fontSize = 23;
            label.resizeTextForBestFit = true;
            label.resizeTextMinSize = 15;
            label.resizeTextMaxSize = 23;
            label.horizontalOverflow = HorizontalWrapMode.Wrap;
            label.verticalOverflow = VerticalWrapMode.Truncate;
            label.lineSpacing = 0.82f;
            label.raycastTarget = false;
        }

        private void Refresh()
        {
            ResolveReferences();
            EnsureUi();

            var input = BuildStateInput();
            var state = StandaloneQuestExperienceStateGraph.Resolve(input);
            if (!StandaloneQuestExperienceStateGraph.Validate(input, state, out var validationError))
            {
                Debug.LogError("[StandaloneQuestExperienceStatusStrip] Invalid experience state: " + validationError);
            }

            LastState = state;
            IsShotReady = state.ShotReady;
            LastReadinessReason = state.ReasonCode;
            LastDisplayText = state.DisplayText;
            label.text = FormatStatusText(state);
            label.color = state.ShotReady ? readyColor : attentionColor;
            background.color = ResolveBackgroundColor(state);
            ApplySurfaceVisibility(state);
        }

        private string FormatStatusText(StandaloneQuestExperienceState state)
        {
            if (state.ShotReady)
            {
                return "SHOT READY";
            }

            var labelText = string.IsNullOrWhiteSpace(state.BlockerLabel)
                ? "Preparing"
                : state.BlockerLabel.Trim();
            return "NOT READY\n" + labelText;
        }

        private Color ResolveBackgroundColor(StandaloneQuestExperienceState state)
        {
            if (state.ShotReady)
            {
                return readyBackgroundColor;
            }

            return state.Blocker == StandaloneQuestExperienceBlocker.ReviewOpen
                || state.Blocker == StandaloneQuestExperienceBlocker.ReplayPlaying
                ? reviewBackgroundColor
                : blockedBackgroundColor;
        }

        private void ApplySurfaceVisibility(StandaloneQuestExperienceState state)
        {
            if (shotReplayList != null)
            {
                shotReplayList.SetExperienceVisible(state.ShotRailVisible);
            }

            if (sessionReviewPanel != null)
            {
                sessionReviewPanel.SetReviewButtonAllowed(state.ReviewButtonVisible);
            }
        }

        private StandaloneQuestExperienceStateInput BuildStateInput()
        {
            var sessionActive = sessionController != null && sessionController.IsSessionActive;
            var mediaReady = false;
            var mediaReason = "session_not_active";
            if (sessionController != null)
            {
                mediaReady = sessionController.TryGetLiveMediaReadiness(out mediaReason);
            }

            var pipelineReady = false;
            var pipelineReason = "pipeline_status_missing";
            if (liveResultReceiver != null)
            {
                var pipelineStatus = liveResultReceiver.LastPipelineStatus;
                pipelineReady = liveResultReceiver.IsPipelineReady;
                pipelineReason = pipelineStatus != null && !string.IsNullOrWhiteSpace(pipelineStatus.reason)
                    ? pipelineStatus.reason
                    : "pipeline_status_missing";
            }

            return new StandaloneQuestExperienceStateInput(
                sessionActive: sessionActive,
                mediaReady: mediaReady,
                mediaReason: mediaReason,
                metadataConnected: liveMetadataSender != null && liveMetadataSender.IsConnected,
                resultsConnected: liveResultReceiver != null && liveResultReceiver.IsConnected,
                pipelineReady: pipelineReady,
                pipelineReason: pipelineReason,
                replayPlaying: shotReplayRenderer != null && shotReplayRenderer.IsReplaying,
                reviewOpen: sessionReviewPanel != null && sessionReviewPanel.IsVisible,
                successfulShotCount: shotReplayList != null ? shotReplayList.ShotCount : 0,
                laneCoordinatorPresent: laneLockCoordinator != null,
                laneState: laneLockCoordinator != null ? laneLockCoordinator.State : StandaloneQuestLaneLockUiState.Idle,
                laneBlockerLabel: laneLockCoordinator != null ? laneLockCoordinator.ReadinessBlockerLabel : "Lane UI Missing");
        }
    }
}
