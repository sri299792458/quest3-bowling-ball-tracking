using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.UI;

namespace QuestBowlingStandalone.QuestApp
{
    [RequireComponent(typeof(RectTransform))]
    public sealed class StandaloneQuestSessionReviewPanel : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private StandaloneQuestShotReplayList shotReplayList;
        [SerializeField] private StandaloneQuestShotReplayRenderer shotReplayRenderer;
        [SerializeField] private CanvasGroup panelCanvasGroup;
        [SerializeField] private Image panelBackground;
        [SerializeField] private Button toggleButton;
        [SerializeField] private Text toggleButtonLabel;
        [SerializeField] private Button previousButton;
        [SerializeField] private Text previousButtonLabel;
        [SerializeField] private Button nextButton;
        [SerializeField] private Text nextButtonLabel;
        [SerializeField] private Button closeButton;
        [SerializeField] private Text closeButtonLabel;
        [SerializeField] private Text titleLabel;
        [SerializeField] private Text consistencyLabel;
        [SerializeField] private Text selectedShotLabel;
        [SerializeField] private Text comparisonLabel;
        [SerializeField] private Text bestShotLabel;
        [SerializeField] private Text trendLabel;

        [Header("Presentation")]
        [SerializeField] private string hiddenToggleText = "Review";
        [SerializeField] private string visibleToggleText = "Hide";
        [SerializeField] private Color panelColor = new Color(0.015f, 0.035f, 0.04f, 0.88f);
        [SerializeField] private Color buttonColor = new Color(0.08f, 0.17f, 0.18f, 0.94f);
        [SerializeField] private Color selectedButtonColor = new Color(0.16f, 0.44f, 0.48f, 1.0f);
        [SerializeField] private Color labelColor = new Color(0.94f, 1.0f, 1.0f, 1.0f);
        [SerializeField] private Color mutedLabelColor = new Color(0.70f, 0.82f, 0.84f, 1.0f);
        [SerializeField] private bool verboseLogging;

        private bool _visible;
        private bool _reviewButtonAllowed = true;

        public bool IsVisible => _visible;
        public string LastStatus { get; private set; } = string.Empty;

        private void Awake()
        {
            ResolveReferences();
            EnsureUi();
            SetVisible(false, false);
            Refresh();
        }

        private void OnEnable()
        {
            Subscribe();
            WireButtons();
        }

        private void OnDisable()
        {
            Unsubscribe();
            UnwireButtons();
        }

        private void OnDestroy()
        {
            Unsubscribe();
            UnwireButtons();
        }

        private void Subscribe()
        {
            ResolveReferences();
            if (shotReplayList == null)
            {
                return;
            }

            shotReplayList.ShotsChanged -= OnShotsChanged;
            shotReplayList.ShotsChanged += OnShotsChanged;
            shotReplayList.ShotSelected -= OnShotSelected;
            shotReplayList.ShotSelected += OnShotSelected;
        }

        private void Unsubscribe()
        {
            if (shotReplayList == null)
            {
                return;
            }

            shotReplayList.ShotsChanged -= OnShotsChanged;
            shotReplayList.ShotSelected -= OnShotSelected;
        }

        private void WireButtons()
        {
            EnsureUi();
            if (toggleButton != null)
            {
                toggleButton.onClick.RemoveListener(ToggleReview);
                toggleButton.onClick.AddListener(ToggleReview);
            }

            if (previousButton != null)
            {
                previousButton.onClick.RemoveListener(SelectPreviousShot);
                previousButton.onClick.AddListener(SelectPreviousShot);
            }

            if (nextButton != null)
            {
                nextButton.onClick.RemoveListener(SelectNextShot);
                nextButton.onClick.AddListener(SelectNextShot);
            }

            if (closeButton != null)
            {
                closeButton.onClick.RemoveListener(CloseReview);
                closeButton.onClick.AddListener(CloseReview);
            }
        }

        private void UnwireButtons()
        {
            if (toggleButton != null)
            {
                toggleButton.onClick.RemoveListener(ToggleReview);
            }

            if (previousButton != null)
            {
                previousButton.onClick.RemoveListener(SelectPreviousShot);
            }

            if (nextButton != null)
            {
                nextButton.onClick.RemoveListener(SelectNextShot);
            }

            if (closeButton != null)
            {
                closeButton.onClick.RemoveListener(CloseReview);
            }
        }

        private void ResolveReferences()
        {
            if (shotReplayList == null)
            {
                shotReplayList = FindFirstObjectByType<StandaloneQuestShotReplayList>();
            }

            if (shotReplayRenderer == null)
            {
                shotReplayRenderer = FindFirstObjectByType<StandaloneQuestShotReplayRenderer>();
            }
        }

        private void EnsureUi()
        {
            if (panelCanvasGroup == null)
            {
                panelCanvasGroup = GetComponent<CanvasGroup>();
                if (panelCanvasGroup == null)
                {
                    panelCanvasGroup = gameObject.AddComponent<CanvasGroup>();
                }
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

            var parent = transform.parent != null ? transform.parent : transform;
            toggleButton = EnsureButton(
                toggleButton,
                ref toggleButtonLabel,
                parent,
                "SessionReviewButton",
                hiddenToggleText,
                new Vector2(650.0f, 116.0f),
                new Vector2(150.0f, 62.0f));

            titleLabel = EnsureText(titleLabel, transform, "Title", "Session Review", TextAnchor.MiddleLeft, 24);
            consistencyLabel = EnsureText(consistencyLabel, transform, "Consistency", string.Empty, TextAnchor.UpperLeft, 17);
            selectedShotLabel = EnsureText(selectedShotLabel, transform, "SelectedShot", string.Empty, TextAnchor.UpperLeft, 18);
            comparisonLabel = EnsureText(comparisonLabel, transform, "Comparison", string.Empty, TextAnchor.UpperLeft, 17);
            bestShotLabel = EnsureText(bestShotLabel, transform, "BestShot", string.Empty, TextAnchor.UpperLeft, 17);
            trendLabel = EnsureText(trendLabel, transform, "Trend", string.Empty, TextAnchor.UpperLeft, 16);

            previousButton = EnsureButton(
                previousButton,
                ref previousButtonLabel,
                transform,
                "PreviousShotButton",
                "Prev",
                new Vector2(-106.0f, -118.0f),
                new Vector2(100.0f, 48.0f));
            nextButton = EnsureButton(
                nextButton,
                ref nextButtonLabel,
                transform,
                "NextShotButton",
                "Next",
                new Vector2(10.0f, -118.0f),
                new Vector2(100.0f, 48.0f));
            closeButton = EnsureButton(
                closeButton,
                ref closeButtonLabel,
                transform,
                "CloseButton",
                "Close",
                new Vector2(314.0f, 112.0f),
                new Vector2(110.0f, 48.0f));

            ConfigureRect(titleLabel, new Vector2(0.04f, 0.82f), new Vector2(0.48f, 0.98f));
            ConfigureRect(consistencyLabel, new Vector2(0.04f, 0.16f), new Vector2(0.47f, 0.82f));
            ConfigureRect(selectedShotLabel, new Vector2(0.50f, 0.62f), new Vector2(0.96f, 0.82f));
            ConfigureRect(comparisonLabel, new Vector2(0.50f, 0.42f), new Vector2(0.96f, 0.62f));
            ConfigureRect(bestShotLabel, new Vector2(0.50f, 0.22f), new Vector2(0.96f, 0.42f));
            ConfigureRect(trendLabel, new Vector2(0.50f, 0.04f), new Vector2(0.96f, 0.22f));
        }

        private Text EnsureText(Text text, Transform parent, string objectName, string value, TextAnchor anchor, int fontSize)
        {
            if (text == null)
            {
                var existing = parent.Find(objectName);
                if (existing != null)
                {
                    text = existing.GetComponent<Text>();
                }
            }

            if (text == null)
            {
                var labelObject = new GameObject(objectName, typeof(RectTransform), typeof(CanvasRenderer), typeof(Text));
                labelObject.transform.SetParent(parent, false);
                labelObject.layer = gameObject.layer;
                text = labelObject.GetComponent<Text>();
            }

            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.text = value;
            text.alignment = anchor;
            text.fontSize = fontSize;
            text.resizeTextForBestFit = false;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Truncate;
            text.lineSpacing = 0.88f;
            text.color = anchor == TextAnchor.UpperLeft ? mutedLabelColor : labelColor;
            text.raycastTarget = false;
            return text;
        }

        private Button EnsureButton(
            Button button,
            ref Text label,
            Transform parent,
            string objectName,
            string text,
            Vector2 anchoredPosition,
            Vector2 size)
        {
            if (button == null)
            {
                var existing = parent.Find(objectName);
                if (existing != null)
                {
                    button = existing.GetComponent<Button>();
                }
            }

            if (button == null)
            {
                var buttonObject = new GameObject(objectName, typeof(RectTransform), typeof(CanvasRenderer), typeof(Image), typeof(Button));
                buttonObject.transform.SetParent(parent, false);
                buttonObject.layer = gameObject.layer;
                button = buttonObject.GetComponent<Button>();
            }

            var rect = button.GetComponent<RectTransform>();
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = new Vector2(0.5f, 0.5f);
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = size;

            var image = button.GetComponent<Image>();
            if (image != null)
            {
                image.color = buttonColor;
                image.raycastTarget = true;
            }

            var colors = button.colors;
            colors.normalColor = buttonColor;
            colors.highlightedColor = selectedButtonColor;
            colors.pressedColor = selectedButtonColor;
            colors.fadeDuration = 0.05f;
            button.targetGraphic = image;
            button.colors = colors;

            if (label == null)
            {
                var existingLabel = button.transform.Find("Label");
                if (existingLabel != null)
                {
                    label = existingLabel.GetComponent<Text>();
                }
            }

            if (label == null)
            {
                var labelObject = new GameObject("Label", typeof(RectTransform), typeof(CanvasRenderer), typeof(Text));
                labelObject.transform.SetParent(button.transform, false);
                labelObject.layer = gameObject.layer;
                label = labelObject.GetComponent<Text>();
            }

            var labelRect = label.GetComponent<RectTransform>();
            labelRect.anchorMin = Vector2.zero;
            labelRect.anchorMax = Vector2.one;
            labelRect.offsetMin = Vector2.zero;
            labelRect.offsetMax = Vector2.zero;
            label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            label.text = text;
            label.alignment = TextAnchor.MiddleCenter;
            label.fontSize = 20;
            label.resizeTextForBestFit = false;
            label.horizontalOverflow = HorizontalWrapMode.Wrap;
            label.verticalOverflow = VerticalWrapMode.Truncate;
            label.color = labelColor;
            label.raycastTarget = false;
            return button;
        }

        private void ConfigureRect(Text text, Vector2 anchorMin, Vector2 anchorMax)
        {
            if (text == null)
            {
                return;
            }

            var rect = text.GetComponent<RectTransform>();
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        private void ToggleReview()
        {
            if (!StandaloneQuestCommandGate.TryAccept("session_review_toggle"))
            {
                return;
            }

            if (!_reviewButtonAllowed || shotReplayList == null || shotReplayList.ShotCount == 0)
            {
                return;
            }

            SetVisible(!_visible, true);
        }

        private void CloseReview()
        {
            if (!StandaloneQuestCommandGate.TryAccept("session_review_close"))
            {
                return;
            }

            SetVisible(false, true);
        }

        private void SelectPreviousShot()
        {
            SelectRelative(-1);
        }

        private void SelectNextShot()
        {
            SelectRelative(1);
        }

        private void SelectRelative(int delta)
        {
            if (!StandaloneQuestCommandGate.TryAccept("session_review_select"))
            {
                return;
            }

            if (shotReplayList == null || shotReplayList.ShotCount == 0)
            {
                return;
            }

            var current = shotReplayList.SelectedShotIndex;
            if (current < 0)
            {
                current = shotReplayList.ShotCount - 1;
            }

            var next = Mathf.Clamp(current + delta, 0, shotReplayList.ShotCount - 1);
            shotReplayList.SelectShotByIndex(next);
        }

        public void SetReviewButtonAllowed(bool allowed)
        {
            if (_reviewButtonAllowed == allowed)
            {
                return;
            }

            _reviewButtonAllowed = allowed;
            if (!allowed && _visible)
            {
                SetVisible(false, false);
                return;
            }

            Refresh();
        }

        private void SetVisible(bool visible, bool driveSelection)
        {
            _visible = visible;
            EnsureUi();

            panelCanvasGroup.alpha = visible ? 1.0f : 0.0f;
            panelCanvasGroup.interactable = visible;
            panelCanvasGroup.blocksRaycasts = visible;

            if (toggleButtonLabel != null)
            {
                toggleButtonLabel.text = visible ? visibleToggleText : hiddenToggleText;
            }

            if (visible && driveSelection)
            {
                EnsureSelectedShot();
            }

            if (shotReplayList != null)
            {
                shotReplayList.SetReviewMode(visible);
            }

            RefreshGhost();
            Refresh();
            SetStatus(visible ? "session_review_open" : "session_review_closed");
        }

        private void EnsureSelectedShot()
        {
            if (shotReplayList == null || shotReplayList.ShotCount == 0)
            {
                return;
            }

            if (shotReplayList.SelectedShotIndex < 0)
            {
                shotReplayList.SelectShotByIndex(shotReplayList.ShotCount - 1);
            }
        }

        private void OnShotsChanged()
        {
            if (shotReplayList == null || shotReplayList.ShotCount == 0)
            {
                SetVisible(false, false);
                return;
            }

            RefreshGhost();
            Refresh();
        }

        private void OnShotSelected(int shotIndex, StandaloneShotResult result)
        {
            RefreshGhost();
            Refresh();
        }

        private void RefreshGhost()
        {
            if (shotReplayRenderer == null)
            {
                return;
            }

            if (!_visible || shotReplayList == null || shotReplayList.SelectedShotIndex <= 0)
            {
                shotReplayRenderer.ClearGhostReplay();
                return;
            }

            if (shotReplayList.TryGetShotResult(shotReplayList.SelectedShotIndex - 1, out var previous))
            {
                shotReplayRenderer.RenderGhostShotResult(previous);
            }
            else
            {
                shotReplayRenderer.ClearGhostReplay();
            }
        }

        private void Refresh()
        {
            EnsureUi();

            var shots = shotReplayList != null
                ? shotReplayList.GetShotResultsSnapshot()
                : Array.Empty<StandaloneShotResult>();
            var hasShots = shots.Length > 0;

            SetToggleButtonVisible(hasShots && _reviewButtonAllowed);
            if (toggleButton != null)
            {
                toggleButton.interactable = hasShots && _reviewButtonAllowed;
            }

            if (toggleButtonLabel != null)
            {
                toggleButtonLabel.text = _visible ? visibleToggleText : hiddenToggleText;
            }

            if (!hasShots)
            {
                consistencyLabel.text = "No shots yet.";
                selectedShotLabel.text = string.Empty;
                comparisonLabel.text = string.Empty;
                bestShotLabel.text = string.Empty;
                trendLabel.text = string.Empty;
                SetButtonInteractivity(false, false);
                return;
            }

            var selectedIndex = shotReplayList != null ? shotReplayList.SelectedShotIndex : shots.Length - 1;
            if (selectedIndex < 0 || selectedIndex >= shots.Length)
            {
                selectedIndex = shots.Length - 1;
            }

            var aggregate = BuildAggregate(shots);
            consistencyLabel.text = BuildConsistencyText(shots.Length, aggregate);
            selectedShotLabel.text = BuildSelectedShotText(selectedIndex, shots[selectedIndex]);
            comparisonLabel.text = BuildComparisonText(selectedIndex, shots);
            bestShotLabel.text = BuildBestShotText(aggregate, shots);
            trendLabel.text = BuildTrendText(shots);
            SetButtonInteractivity(selectedIndex > 0, selectedIndex < shots.Length - 1);
        }

        private void SetToggleButtonVisible(bool visible)
        {
            if (toggleButton != null)
            {
                toggleButton.gameObject.SetActive(visible);
            }
        }

        private void SetButtonInteractivity(bool canPrevious, bool canNext)
        {
            if (previousButton != null)
            {
                previousButton.interactable = _visible && canPrevious;
            }

            if (nextButton != null)
            {
                nextButton.interactable = _visible && canNext;
            }

            if (closeButton != null)
            {
                closeButton.interactable = _visible;
            }
        }

        private SessionAggregate BuildAggregate(StandaloneShotResult[] shots)
        {
            var aggregate = new SessionAggregate();
            for (var index = 0; index < shots.Length; index++)
            {
                var stats = shots[index] != null ? shots[index].shotStats : null;
                if (stats == null)
                {
                    continue;
                }

                if (TryAverageSpeed(stats, out var displaySpeed))
                {
                    aggregate.Speed.Add(displaySpeed);
                }

                if (stats.positions != null)
                {
                    if (stats.positions.hasEntryBoard)
                    {
                        aggregate.EntryBoard.Add(stats.positions.entryBoard);
                    }

                    if (stats.positions.hasBreakpoint)
                    {
                        aggregate.BreakpointBoard.Add(stats.positions.breakpointBoard);
                        aggregate.BreakpointDistance.Add(stats.positions.breakpointDistanceFeet);
                    }
                }

                if (stats.angles != null && stats.angles.hasEntryAngle)
                {
                    aggregate.EntryAngle.Add(stats.angles.entryAngleDegrees);
                }
            }

            aggregate.BestShotIndex = FindMostRepeatableShot(shots, aggregate);
            return aggregate;
        }

        private int FindMostRepeatableShot(StandaloneShotResult[] shots, SessionAggregate aggregate)
        {
            if (shots.Length < 2)
            {
                return shots.Length == 1 ? 0 : -1;
            }

            var bestIndex = -1;
            var bestScore = float.PositiveInfinity;
            for (var index = 0; index < shots.Length; index++)
            {
                var stats = shots[index] != null ? shots[index].shotStats : null;
                if (stats == null)
                {
                    continue;
                }

                var score = 0.0f;
                var terms = 0;
                AddScoreTerm(ref score, ref terms, TryAverageSpeed(stats, out var speed), speed, aggregate.Speed, 0.5f);
                AddScoreTerm(ref score, ref terms, TryEntryBoard(stats, out var entry), entry, aggregate.EntryBoard, 1.0f);
                AddScoreTerm(ref score, ref terms, TryEntryAngle(stats, out var angle), angle, aggregate.EntryAngle, 0.5f);
                AddScoreTerm(ref score, ref terms, TryBreakpointBoard(stats, out var breakpoint), breakpoint, aggregate.BreakpointBoard, 1.0f);

                if (terms == 0)
                {
                    continue;
                }

                var normalizedScore = score / terms;
                if (normalizedScore < bestScore)
                {
                    bestScore = normalizedScore;
                    bestIndex = index;
                }
            }

            return bestIndex;
        }

        private void AddScoreTerm(ref float score, ref int terms, bool hasValue, float value, MetricAccumulator aggregate, float minimumSpread)
        {
            if (!hasValue || aggregate.Count == 0)
            {
                return;
            }

            var spread = Mathf.Max(minimumSpread, aggregate.StdDev);
            var delta = (value - aggregate.Mean) / spread;
            score += delta * delta;
            terms++;
        }

        private string BuildConsistencyText(int shotCount, SessionAggregate aggregate)
        {
            var lines = new List<string>
            {
                "Consistency",
                "Shots           " + shotCount.ToString(CultureInfo.InvariantCulture),
            };

            AddAverageAndSpread(lines, "Speed Avg", "Speed Spread", aggregate.Speed, " mph", " mph");
            AddAverageAndSpread(lines, "Entry Board", "Entry Spread", aggregate.EntryBoard, " avg", " boards");
            AddAverageAndSpread(lines, "Entry Angle", "Angle Spread", aggregate.EntryAngle, " deg", " deg");
            if (aggregate.BreakpointBoard.Count > 0)
            {
                var distance = aggregate.BreakpointDistance.Count > 0
                    ? " @ " + aggregate.BreakpointDistance.Mean.ToString("0", CultureInfo.InvariantCulture) + " ft"
                    : string.Empty;
                lines.Add("Breakpoint     " + aggregate.BreakpointBoard.Mean.ToString("0.0", CultureInfo.InvariantCulture) + distance);
                lines.Add("Bkpt Spread    +/- " + aggregate.BreakpointBoard.StdDev.ToString("0.0", CultureInfo.InvariantCulture) + " boards");
            }

            return string.Join("\n", lines.ToArray());
        }

        private void AddAverageAndSpread(
            List<string> lines,
            string averageLabel,
            string spreadLabel,
            MetricAccumulator values,
            string averageSuffix,
            string spreadSuffix)
        {
            if (values.Count == 0)
            {
                return;
            }

            lines.Add(averageLabel.PadRight(16) + values.Mean.ToString("0.0", CultureInfo.InvariantCulture) + averageSuffix);
            lines.Add(spreadLabel.PadRight(16) + "+/- " + values.StdDev.ToString("0.0", CultureInfo.InvariantCulture) + spreadSuffix);
        }

        private string BuildSelectedShotText(int selectedIndex, StandaloneShotResult shot)
        {
            var stats = shot != null ? shot.shotStats : null;
            var lines = new List<string>
            {
                "Selected Shot " + (selectedIndex + 1).ToString(CultureInfo.InvariantCulture) + " of " + (shotReplayList != null ? shotReplayList.ShotCount : 0).ToString(CultureInfo.InvariantCulture),
            };

            var values = new List<string>();
            if (stats != null && TryAverageSpeed(stats, out var speed))
            {
                values.Add(speed.ToString("0.0", CultureInfo.InvariantCulture) + " mph");
            }

            if (stats != null && TryEntryBoard(stats, out var entry))
            {
                values.Add("Entry " + entry.ToString("0.0", CultureInfo.InvariantCulture));
            }

            if (stats != null && TryEntryAngle(stats, out var angle))
            {
                values.Add(angle.ToString("0.0", CultureInfo.InvariantCulture) + " deg");
            }

            if (stats != null && TryBreakpoint(stats, out var breakpointBoard, out var breakpointDistance))
            {
                values.Add("Bkpt " + breakpointBoard.ToString("0.0", CultureInfo.InvariantCulture) + " @ " + breakpointDistance.ToString("0", CultureInfo.InvariantCulture) + " ft");
            }

            lines.Add(values.Count > 0 ? string.Join("   ", values.ToArray()) : "Stats unavailable");
            return string.Join("\n", lines.ToArray());
        }

        private string BuildComparisonText(int selectedIndex, StandaloneShotResult[] shots)
        {
            if (selectedIndex <= 0 || selectedIndex >= shots.Length)
            {
                return "Vs Previous\nSelect a later shot for comparison.";
            }

            var current = shots[selectedIndex] != null ? shots[selectedIndex].shotStats : null;
            var previous = shots[selectedIndex - 1] != null ? shots[selectedIndex - 1].shotStats : null;
            if (current == null || previous == null)
            {
                return "Vs Previous\nComparison unavailable.";
            }

            var values = new List<string>();
            if (TryAverageSpeed(current, out var currentSpeed) && TryAverageSpeed(previous, out var previousSpeed))
            {
                AddDelta(values, "Speed", currentSpeed - previousSpeed, " mph");
            }

            if (TryEntryBoard(current, out var currentEntry) && TryEntryBoard(previous, out var previousEntry))
            {
                AddDelta(values, "Entry", currentEntry - previousEntry, " boards");
            }

            if (TryEntryAngle(current, out var currentAngle) && TryEntryAngle(previous, out var previousAngle))
            {
                AddDelta(values, "Angle", currentAngle - previousAngle, " deg");
            }

            if (TryBreakpointBoard(current, out var currentBreakpoint) && TryBreakpointBoard(previous, out var previousBreakpoint))
            {
                AddDelta(values, "Bkpt", currentBreakpoint - previousBreakpoint, " boards");
            }

            return "Vs Previous\n" + (values.Count > 0 ? string.Join("   ", values.ToArray()) : "Comparison unavailable.");
        }

        private void AddDelta(List<string> values, string label, float delta, string suffix)
        {
            values.Add(label + " " + delta.ToString("+0.0;-0.0;0.0", CultureInfo.InvariantCulture) + suffix);
        }

        private string BuildBestShotText(SessionAggregate aggregate, StandaloneShotResult[] shots)
        {
            if (aggregate.BestShotIndex < 0 || aggregate.BestShotIndex >= shots.Length)
            {
                return "Most Repeatable\nAdd more tracked shots.";
            }

            var shot = shots[aggregate.BestShotIndex];
            var stats = shot != null ? shot.shotStats : null;
            var parts = new List<string>
            {
                "Shot " + (aggregate.BestShotIndex + 1).ToString(CultureInfo.InvariantCulture),
            };

            if (stats != null && TryAverageSpeed(stats, out var speed))
            {
                parts.Add(speed.ToString("0.0", CultureInfo.InvariantCulture) + " mph");
            }

            if (stats != null && TryEntryBoard(stats, out var entry))
            {
                parts.Add("Entry " + entry.ToString("0.0", CultureInfo.InvariantCulture));
            }

            return "Most Repeatable\n" + string.Join("   ", parts.ToArray());
        }

        private string BuildTrendText(StandaloneShotResult[] shots)
        {
            var start = Mathf.Max(0, shots.Length - 3);
            var speedValues = new List<string>();
            var entryValues = new List<string>();
            for (var index = start; index < shots.Length; index++)
            {
                var stats = shots[index] != null ? shots[index].shotStats : null;
                speedValues.Add(stats != null && TryAverageSpeed(stats, out var speed)
                    ? speed.ToString("0.0", CultureInfo.InvariantCulture)
                    : "--");
                entryValues.Add(stats != null && TryEntryBoard(stats, out var entry)
                    ? entry.ToString("0.0", CultureInfo.InvariantCulture)
                    : "--");
            }

            return "Last " + speedValues.Count.ToString(CultureInfo.InvariantCulture) + "\n"
                + "Speed " + string.Join(" -> ", speedValues.ToArray()) + "\n"
                + "Entry " + string.Join(" -> ", entryValues.ToArray());
        }

        private bool TryAverageSpeed(StandaloneShotStats stats, out float value)
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

        private bool TryEntryBoard(StandaloneShotStats stats, out float value)
        {
            value = 0.0f;
            if (stats == null || stats.positions == null || !stats.positions.hasEntryBoard)
            {
                return false;
            }

            value = stats.positions.entryBoard;
            return true;
        }

        private bool TryEntryAngle(StandaloneShotStats stats, out float value)
        {
            value = 0.0f;
            if (stats == null || stats.angles == null || !stats.angles.hasEntryAngle)
            {
                return false;
            }

            value = stats.angles.entryAngleDegrees;
            return true;
        }

        private bool TryBreakpointBoard(StandaloneShotStats stats, out float value)
        {
            value = 0.0f;
            if (stats == null || stats.positions == null || !stats.positions.hasBreakpoint)
            {
                return false;
            }

            value = stats.positions.breakpointBoard;
            return true;
        }

        private bool TryBreakpoint(StandaloneShotStats stats, out float board, out float distanceFeet)
        {
            board = 0.0f;
            distanceFeet = 0.0f;
            if (stats == null || stats.positions == null || !stats.positions.hasBreakpoint)
            {
                return false;
            }

            board = stats.positions.breakpointBoard;
            distanceFeet = stats.positions.breakpointDistanceFeet;
            return true;
        }

        private void SetStatus(string status)
        {
            LastStatus = status ?? string.Empty;
            if (verboseLogging)
            {
                Debug.Log("[StandaloneQuestSessionReviewPanel] " + LastStatus);
            }
        }

        private sealed class SessionAggregate
        {
            public readonly MetricAccumulator Speed = new MetricAccumulator();
            public readonly MetricAccumulator EntryBoard = new MetricAccumulator();
            public readonly MetricAccumulator EntryAngle = new MetricAccumulator();
            public readonly MetricAccumulator BreakpointBoard = new MetricAccumulator();
            public readonly MetricAccumulator BreakpointDistance = new MetricAccumulator();
            public int BestShotIndex = -1;
        }

        private sealed class MetricAccumulator
        {
            private float _sum;
            private float _sumSquares;

            public int Count { get; private set; }
            public float Mean => Count > 0 ? _sum / Count : 0.0f;

            public float StdDev
            {
                get
                {
                    if (Count < 2)
                    {
                        return 0.0f;
                    }

                    var mean = Mean;
                    var variance = Mathf.Max(0.0f, (_sumSquares / Count) - mean * mean);
                    return Mathf.Sqrt(variance);
                }
            }

            public void Add(float value)
            {
                Count++;
                _sum += value;
                _sumSquares += value * value;
            }
        }
    }
}
