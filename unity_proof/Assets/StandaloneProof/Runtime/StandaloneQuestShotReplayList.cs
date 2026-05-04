using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.UI;

namespace QuestBowlingStandalone.QuestApp
{
    [RequireComponent(typeof(RectTransform))]
    public sealed class StandaloneQuestShotReplayList : MonoBehaviour
    {
        [SerializeField] private StandaloneQuestLiveResultReceiver liveResultReceiver;
        [SerializeField] private StandaloneQuestShotReplayRenderer shotReplayRenderer;
        [SerializeField] private StandaloneQuestSessionController sessionController;
        [SerializeField] private StandaloneQuestLaneLockStateCoordinator laneLockCoordinator;
        [SerializeField] private RectTransform listRoot;
        [SerializeField] private Image panelBackground;
        [SerializeField] private Text emptyLabel;
        [SerializeField] private Text sessionSummaryLabel;
        [SerializeField] private int maxVisibleShots = 4;
        [SerializeField] private Vector2 shotButtonSize = new Vector2(164.0f, 96.0f);
        [SerializeField] private float shotButtonSpacing = 10.0f;
        [SerializeField] private float shotButtonRowYOffset = 40.0f;
        [SerializeField] private float transientFailureMessageSeconds = 2.75f;
        [SerializeField] private string emptyText = string.Empty;
        [SerializeField] private string shotLabelPrefix = "Shot ";
        [SerializeField] private Color panelColor = new Color(0.02f, 0.045f, 0.05f, 0.72f);
        [SerializeField] private Color buttonColor = new Color(0.08f, 0.17f, 0.18f, 0.94f);
        [SerializeField] private Color selectedButtonColor = new Color(0.16f, 0.44f, 0.48f, 1.0f);
        [SerializeField] private Color disabledButtonColor = new Color(0.13f, 0.15f, 0.15f, 0.70f);
        [SerializeField] private Color labelColor = new Color(0.94f, 1.0f, 1.0f, 1.0f);
        [SerializeField] private Color mutedLabelColor = new Color(0.72f, 0.84f, 0.84f, 1.0f);
        [SerializeField] private bool verboseLogging;

        private readonly List<ShotRecord> _shots = new List<ShotRecord>();
        private readonly List<Button> _shotButtons = new List<Button>();
        private int _selectedShotIndex = -1;
        private string _activeSessionId = string.Empty;
        private string _transientMessage = string.Empty;
        private float _transientMessageUntil;
        private bool _experienceVisible = true;

        public event Action ShotsChanged;
        public event Action<int, StandaloneShotResult> ShotSelected;

        public string LastStatus { get; private set; } = string.Empty;
        public int ShotCount => _shots.Count;
        public int SelectedShotIndex => _selectedShotIndex;

        private void Awake()
        {
            ResolveReferences();
            EnsureUiObjects();
            TrackSessionIdentity();
            RefreshList();
        }

        private void Update()
        {
            TrackSessionIdentity();
            if (!string.IsNullOrWhiteSpace(_transientMessage) && Time.time >= _transientMessageUntil)
            {
                _transientMessage = string.Empty;
                RefreshList();
            }
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
        }

        private void Subscribe()
        {
            ResolveReferences();

            if (liveResultReceiver != null)
            {
                liveResultReceiver.ShotResultReceived -= OnShotResultReceived;
                liveResultReceiver.ShotResultReceived += OnShotResultReceived;
            }

            if (laneLockCoordinator != null)
            {
                laneLockCoordinator.StateChanged -= OnLaneStateChanged;
                laneLockCoordinator.StateChanged += OnLaneStateChanged;
            }
        }

        private void Unsubscribe()
        {
            if (liveResultReceiver != null)
            {
                liveResultReceiver.ShotResultReceived -= OnShotResultReceived;
            }

            if (laneLockCoordinator != null)
            {
                laneLockCoordinator.StateChanged -= OnLaneStateChanged;
            }
        }

        private void ResolveReferences()
        {
            if (liveResultReceiver == null)
            {
                liveResultReceiver = FindFirstObjectByType<StandaloneQuestLiveResultReceiver>();
            }

            if (shotReplayRenderer == null)
            {
                shotReplayRenderer = FindFirstObjectByType<StandaloneQuestShotReplayRenderer>();
            }

            if (sessionController == null)
            {
                sessionController = FindFirstObjectByType<StandaloneQuestSessionController>();
            }

            if (laneLockCoordinator == null)
            {
                laneLockCoordinator = FindFirstObjectByType<StandaloneQuestLaneLockStateCoordinator>();
            }
        }

        private void TrackSessionIdentity()
        {
            var sessionId = sessionController != null && sessionController.IsSessionActive
                ? sessionController.ActiveSessionId
                : string.Empty;
            if (string.IsNullOrWhiteSpace(sessionId))
            {
                if (!string.IsNullOrWhiteSpace(_activeSessionId))
                {
                    _activeSessionId = string.Empty;
                    ClearShots("session_inactive");
                }

                return;
            }

            if (string.IsNullOrWhiteSpace(_activeSessionId))
            {
                _activeSessionId = sessionId;
                return;
            }

            if (_activeSessionId == sessionId)
            {
                return;
            }

            _activeSessionId = sessionId;
            ClearShots("session_changed");
        }

        private void OnLaneStateChanged(StandaloneQuestLaneLockUiState state, string reason)
        {
            if (state == StandaloneQuestLaneLockUiState.Idle || state == StandaloneQuestLaneLockUiState.PlacingHeads)
            {
                ClearShots("lane_reset:" + (reason ?? string.Empty));
                return;
            }

            RefreshList();
        }

        private void OnShotResultReceived(StandaloneShotResult result)
        {
            if (result == null)
            {
                ShowTransientMessage("No Replay");
                SetStatus("shot_result_missing");
                return;
            }

            if (!result.success)
            {
                ShowTransientMessage(_failureToLabel(result.failureReason));
                SetStatus("shot_result_failed:" + (result.failureReason ?? string.Empty));
                return;
            }

            if (result.trajectory == null || result.trajectory.Length == 0)
            {
                ShowTransientMessage("No Replay");
                SetStatus("shot_result_empty_trajectory");
                return;
            }

            _transientMessage = string.Empty;
            _shots.Add(new ShotRecord(_shots.Count + 1, result));
            _selectedShotIndex = _shots.Count - 1;
            RefreshList();
            NotifyShotsChanged();
            NotifyShotSelected();
            SetStatus($"shot_added index={_shots.Count} points={result.trajectory.Length}");
        }

        public bool SelectShotByIndex(int shotIndex)
        {
            if (shotIndex < 0 || shotIndex >= _shots.Count)
            {
                return false;
            }

            _selectedShotIndex = shotIndex;
            var record = _shots[shotIndex];
            if (shotReplayRenderer != null)
            {
                shotReplayRenderer.RenderShotResult(record.Result);
            }

            RefreshList();
            NotifyShotSelected();
            SetStatus($"shot_selected index={record.DisplayIndex}");
            return true;
        }

        public bool TryGetShotResult(int shotIndex, out StandaloneShotResult result)
        {
            result = null;
            if (shotIndex < 0 || shotIndex >= _shots.Count)
            {
                return false;
            }

            result = _shots[shotIndex].Result;
            return result != null;
        }

        public StandaloneShotResult[] GetShotResultsSnapshot()
        {
            var results = new StandaloneShotResult[_shots.Count];
            for (var index = 0; index < _shots.Count; index++)
            {
                results[index] = _shots[index].Result;
            }

            return results;
        }

        public void SetExperienceVisible(bool visible)
        {
            if (_experienceVisible == visible)
            {
                return;
            }

            _experienceVisible = visible;
            RefreshList();
        }

        public void ClearShots(string reason)
        {
            _shots.Clear();
            _selectedShotIndex = -1;
            _transientMessage = string.Empty;

            if (shotReplayRenderer != null)
            {
                shotReplayRenderer.ClearReplay(reason);
            }

            SetEmptyLabel(emptyText);
            RefreshList();
            NotifyShotsChanged();
            NotifyShotSelected();
            SetStatus("shots_cleared:" + (reason ?? string.Empty));
        }

        private void EnsureUiObjects()
        {
            if (listRoot == null)
            {
                listRoot = GetComponent<RectTransform>();
            }

            if (emptyLabel == null)
            {
                var existing = transform.Find("EmptyLabel");
                if (existing != null)
                {
                    emptyLabel = existing.GetComponent<Text>();
                }
            }

            if (emptyLabel == null)
            {
                var labelObject = new GameObject("EmptyLabel", typeof(RectTransform), typeof(CanvasRenderer), typeof(Text));
                labelObject.transform.SetParent(transform, false);
                labelObject.layer = gameObject.layer;
                emptyLabel = labelObject.GetComponent<Text>();
            }

            if (panelBackground == null)
            {
                panelBackground = GetComponent<Image>();
                if (panelBackground == null)
                {
                    panelBackground = gameObject.AddComponent<Image>();
                }
            }

            panelBackground.color = panelColor;
            panelBackground.raycastTarget = false;

            ConfigureText(emptyLabel, emptyText, 18, 32);
            var emptyRect = emptyLabel.GetComponent<RectTransform>();
            emptyRect.anchorMin = Vector2.zero;
            emptyRect.anchorMax = Vector2.one;
            emptyRect.offsetMin = Vector2.zero;
            emptyRect.offsetMax = Vector2.zero;

            if (sessionSummaryLabel == null)
            {
                var existing = transform.Find("SessionSummary");
                if (existing != null)
                {
                    sessionSummaryLabel = existing.GetComponent<Text>();
                }
            }

            if (sessionSummaryLabel == null)
            {
                var summaryObject = new GameObject("SessionSummary", typeof(RectTransform), typeof(CanvasRenderer), typeof(Text));
                summaryObject.transform.SetParent(transform, false);
                summaryObject.layer = gameObject.layer;
                sessionSummaryLabel = summaryObject.GetComponent<Text>();
            }

            ConfigureText(sessionSummaryLabel, string.Empty, 14, 18);
            sessionSummaryLabel.alignment = TextAnchor.MiddleCenter;
            sessionSummaryLabel.color = mutedLabelColor;
            var summaryRect = sessionSummaryLabel.GetComponent<RectTransform>();
            summaryRect.anchorMin = new Vector2(0.03f, 0.02f);
            summaryRect.anchorMax = new Vector2(0.97f, 0.40f);
            summaryRect.offsetMin = Vector2.zero;
            summaryRect.offsetMax = Vector2.zero;
        }

        private void RefreshList()
        {
            EnsureUiObjects();

            var visibleCount = Mathf.Min(Mathf.Max(1, maxVisibleShots), _shots.Count);
            var visibleStart = Mathf.Max(0, _shots.Count - visibleCount);
            EnsureButtonCount(visibleCount);

            var hasShots = _shots.Count > 0;
            var railVisible = hasShots && _experienceVisible;
            var messageVisible = _experienceVisible && !string.IsNullOrWhiteSpace(_transientMessage);
            if (panelBackground != null)
            {
                panelBackground.enabled = railVisible || messageVisible;
            }

            if (emptyLabel != null)
            {
                emptyLabel.text = messageVisible ? _transientMessage : emptyText;
                emptyLabel.gameObject.SetActive(messageVisible || (!hasShots && _experienceVisible && !string.IsNullOrWhiteSpace(emptyText)));
            }

            for (var index = 0; index < _shotButtons.Count; index++)
            {
                var button = _shotButtons[index];
                var active = railVisible && index < visibleCount;
                button.gameObject.SetActive(active);
                if (!active)
                {
                    continue;
                }

                var shotIndex = visibleStart + index;
                var record = _shots[shotIndex];
                var selected = shotIndex == _selectedShotIndex;
                ConfigureShotButton(button, record, selected);
                PositionShotButton(button.GetComponent<RectTransform>(), index, visibleCount);
            }

            RefreshSessionSummary();
        }

        private void EnsureButtonCount(int count)
        {
            while (_shotButtons.Count < count)
            {
                _shotButtons.Add(CreateShotButton(_shotButtons.Count));
            }
        }

        private Button CreateShotButton(int index)
        {
            var buttonObject = new GameObject($"ShotReplayButton{index + 1}", typeof(RectTransform), typeof(CanvasRenderer), typeof(Image), typeof(Button));
            buttonObject.transform.SetParent(listRoot != null ? listRoot : transform, false);
            buttonObject.layer = gameObject.layer;

            var labelObject = new GameObject("Label", typeof(RectTransform), typeof(CanvasRenderer), typeof(Text));
            labelObject.transform.SetParent(buttonObject.transform, false);
            labelObject.layer = gameObject.layer;
            var label = labelObject.GetComponent<Text>();
            ConfigureText(label, string.Empty, 16, 18);
            var labelRect = label.GetComponent<RectTransform>();
            labelRect.anchorMin = Vector2.zero;
            labelRect.anchorMax = Vector2.one;
            labelRect.offsetMin = Vector2.zero;
            labelRect.offsetMax = Vector2.zero;

            return buttonObject.GetComponent<Button>();
        }

        private void ConfigureShotButton(Button button, ShotRecord record, bool selected)
        {
            if (button == null)
            {
                return;
            }

            var image = button.GetComponent<Image>();
            if (image != null)
            {
                image.color = selected ? selectedButtonColor : buttonColor;
                image.raycastTarget = true;
            }

            var colors = button.colors;
            colors.normalColor = selected ? selectedButtonColor : buttonColor;
            colors.highlightedColor = selectedButtonColor;
            colors.pressedColor = selectedButtonColor;
            colors.disabledColor = disabledButtonColor;
            colors.fadeDuration = 0.05f;
            button.transition = Selectable.Transition.ColorTint;
            button.targetGraphic = image;
            button.colors = colors;
            button.interactable = true;
            button.onClick.RemoveAllListeners();
            var capturedIndex = record.DisplayIndex - 1;
            button.onClick.AddListener(() =>
            {
                if (StandaloneQuestCommandGate.TryAccept("shot_replay_select"))
                {
                    SelectShotByIndex(capturedIndex);
                }
            });

            var label = button.GetComponentInChildren<Text>(true);
            if (label != null)
            {
                label.text = FormatShotLabel(record);
            }
        }

        private string FormatShotLabel(ShotRecord record)
        {
            var result = record.Result;
            var stats = result != null ? result.shotStats : null;
            if (stats == null)
            {
                return shotLabelPrefix + record.DisplayIndex;
            }

            var speed = TryDisplaySpeed(stats, out var displaySpeed)
                ? displaySpeed.ToString("0.0", CultureInfo.InvariantCulture) + " mph"
                : "-- mph";

            var entry = stats.positions != null && stats.positions.hasEntryBoard
                ? "Entry " + stats.positions.entryBoard.ToString("0.0", CultureInfo.InvariantCulture)
                : "Entry --";

            var angle = stats.angles != null && stats.angles.hasEntryAngle
                ? stats.angles.entryAngleDegrees.ToString("0.0", CultureInfo.InvariantCulture) + " deg"
                : "-- deg";

            return shotLabelPrefix + record.DisplayIndex + "\n" + speed + "\n" + entry + "  " + angle;
        }

        private void PositionShotButton(RectTransform rectTransform, int visibleIndex, int visibleCount)
        {
            if (rectTransform == null)
            {
                return;
            }

            var buttonSize = new Vector2(Mathf.Max(40.0f, shotButtonSize.x), Mathf.Max(40.0f, shotButtonSize.y));
            var spacing = Mathf.Max(0.0f, shotButtonSpacing);
            var totalWidth = visibleCount * buttonSize.x + Mathf.Max(0, visibleCount - 1) * spacing;
            var x = -totalWidth * 0.5f + buttonSize.x * 0.5f + visibleIndex * (buttonSize.x + spacing);

            rectTransform.anchorMin = new Vector2(0.5f, 0.5f);
            rectTransform.anchorMax = new Vector2(0.5f, 0.5f);
            rectTransform.pivot = new Vector2(0.5f, 0.5f);
            rectTransform.anchoredPosition = new Vector2(x, shotButtonRowYOffset);
            rectTransform.localRotation = Quaternion.identity;
            rectTransform.localScale = Vector3.one;
            rectTransform.sizeDelta = buttonSize;
        }

        private void RefreshSessionSummary()
        {
            if (sessionSummaryLabel == null)
            {
                return;
            }

            if (_shots.Count == 0 || !_experienceVisible)
            {
                sessionSummaryLabel.gameObject.SetActive(false);
                return;
            }

            sessionSummaryLabel.gameObject.SetActive(true);
            sessionSummaryLabel.text = BuildSessionSummaryLabel();
        }

        private string BuildSessionSummaryLabel()
        {
            var speedValues = new List<float>();
            var entryValues = new List<float>();
            var angleValues = new List<float>();
            var breakpointValues = new List<float>();

            for (var index = 0; index < _shots.Count; index++)
            {
                var stats = _shots[index].Result != null ? _shots[index].Result.shotStats : null;
                if (stats == null)
                {
                    continue;
                }

                if (TryDisplaySpeed(stats, out var displaySpeed))
                {
                    speedValues.Add(displaySpeed);
                }

                if (stats.positions != null)
                {
                    if (stats.positions.hasEntryBoard)
                    {
                        entryValues.Add(stats.positions.entryBoard);
                    }

                    if (stats.positions.hasBreakpoint)
                    {
                        breakpointValues.Add(stats.positions.breakpointBoard);
                    }
                }

                if (stats.angles != null && stats.angles.hasEntryAngle)
                {
                    angleValues.Add(stats.angles.entryAngleDegrees);
                }
            }

            var firstLine = new List<string> { $"{_shots.Count} shots" };
            var secondLine = new List<string>();
            AppendSummaryPart(firstLine, "Speed", speedValues, " mph");
            AppendSummaryPart(firstLine, "Entry", entryValues, string.Empty);
            AppendSummaryPart(secondLine, "Angle", angleValues, " deg");
            AppendSummaryPart(secondLine, "Bkpt", breakpointValues, string.Empty);

            if (secondLine.Count == 0)
            {
                return string.Join("   ", firstLine.ToArray());
            }

            return string.Join("   ", firstLine.ToArray()) + "\n" + string.Join("   ", secondLine.ToArray());
        }

        private static void AppendSummaryPart(List<string> parts, string label, List<float> values, string suffix)
        {
            if (values.Count == 0)
            {
                return;
            }

            ComputeMeanStdDev(values, out var mean, out var stdDev);
            parts.Add(
                label
                + " "
                + mean.ToString("0.0", CultureInfo.InvariantCulture)
                + " +/- "
                + stdDev.ToString("0.0", CultureInfo.InvariantCulture)
                + suffix);
        }

        private static void ComputeMeanStdDev(List<float> values, out float mean, out float stdDev)
        {
            mean = 0.0f;
            stdDev = 0.0f;
            if (values == null || values.Count == 0)
            {
                return;
            }

            for (var index = 0; index < values.Count; index++)
            {
                mean += values[index];
            }

            mean /= values.Count;
            if (values.Count < 2)
            {
                return;
            }

            var variance = 0.0f;
            for (var index = 0; index < values.Count; index++)
            {
                var delta = values[index] - mean;
                variance += delta * delta;
            }

            stdDev = Mathf.Sqrt(variance / values.Count);
        }

        private void ConfigureText(Text text, string value, int minSize, int maxSize)
        {
            if (text == null)
            {
                return;
            }

            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.text = value;
            text.alignment = TextAnchor.MiddleCenter;
            text.fontSize = Mathf.Max(1, maxSize);
            text.resizeTextForBestFit = false;
            text.resizeTextMinSize = minSize;
            text.resizeTextMaxSize = maxSize;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Truncate;
            text.lineSpacing = 0.9f;
            text.color = labelColor;
            text.raycastTarget = false;
        }

        private void SetEmptyLabel(string value)
        {
            EnsureUiObjects();
            if (emptyLabel != null)
            {
                emptyLabel.text = string.IsNullOrWhiteSpace(value) ? emptyText : value;
            }
        }

        private static bool TryDisplaySpeed(StandaloneShotStats stats, out float value)
        {
            value = 0.0f;
            var speed = stats != null ? stats.speed : null;
            if (speed == null)
            {
                return false;
            }

            if (speed.hasEntrySpeed)
            {
                value = speed.entryMph;
                return true;
            }

            if (speed.hasAverageSpeed)
            {
                value = speed.averageMph;
                return true;
            }

            if (speed.hasEarlySpeed)
            {
                value = speed.earlyMph;
                return true;
            }

            return false;
        }

        private void ShowTransientMessage(string value)
        {
            _transientMessage = string.IsNullOrWhiteSpace(value) ? "Replay Unavailable" : value.Trim();
            _transientMessageUntil = Time.time + Mathf.Max(0.5f, transientFailureMessageSeconds);
            RefreshList();
        }

        private string _failureToLabel(string failureReason)
        {
            if (string.IsNullOrWhiteSpace(failureReason))
            {
                return "Replay Unavailable";
            }

            if (failureReason.StartsWith("shot_boundary_lane_lock_request_missing")
                || failureReason.StartsWith("lane_lock_result_missing")
                || failureReason.StartsWith("lane_lock_confirm_missing"))
            {
                return "Relock Lane";
            }

            if (failureReason.StartsWith("yolo_detection_failed")
                || failureReason.StartsWith("shot_start_not_found"))
            {
                return "Ball Not Found";
            }

            if (failureReason.StartsWith("sam2_tracking_failed")
                || failureReason.StartsWith("camera_sam2_track_missing"))
            {
                return "Track Lost";
            }

            if (failureReason.StartsWith("lane_projection_failed"))
            {
                return "Projection Failed";
            }

            return "Replay Unavailable";
        }

        private void SetStatus(string status)
        {
            LastStatus = status ?? string.Empty;
            DebugLog(LastStatus);
        }

        private void NotifyShotsChanged()
        {
            ShotsChanged?.Invoke();
        }

        private void NotifyShotSelected()
        {
            StandaloneShotResult selected = null;
            if (_selectedShotIndex >= 0 && _selectedShotIndex < _shots.Count)
            {
                selected = _shots[_selectedShotIndex].Result;
            }

            ShotSelected?.Invoke(_selectedShotIndex, selected);
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestShotReplayList] {message}");
        }

        private readonly struct ShotRecord
        {
            public ShotRecord(int displayIndex, StandaloneShotResult result)
            {
                DisplayIndex = displayIndex;
                Result = result;
            }

            public int DisplayIndex { get; }
            public StandaloneShotResult Result { get; }
        }
    }
}
