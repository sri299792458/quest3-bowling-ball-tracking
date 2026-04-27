using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace QuestBowlingStandalone.QuestApp
{
    [RequireComponent(typeof(RectTransform))]
    public sealed class StandaloneQuestShotReplayList : MonoBehaviour
    {
        [SerializeField] private StandaloneQuestLiveResultReceiver liveResultReceiver;
        [SerializeField] private StandaloneQuestShotReplayRenderer shotReplayRenderer;
        [SerializeField] private RectTransform listRoot;
        [SerializeField] private Text emptyLabel;
        [SerializeField] private int maxVisibleShots = 4;
        [SerializeField] private Vector2 shotButtonSize = new Vector2(110.0f, 92.0f);
        [SerializeField] private float shotButtonSpacing = 10.0f;
        [SerializeField] private string emptyText = "Waiting Shot";
        [SerializeField] private string shotLabelPrefix = "Shot ";
        [SerializeField] private Color buttonColor = new Color(0.08f, 0.17f, 0.18f, 0.94f);
        [SerializeField] private Color selectedButtonColor = new Color(0.16f, 0.44f, 0.48f, 1.0f);
        [SerializeField] private Color disabledButtonColor = new Color(0.13f, 0.15f, 0.15f, 0.70f);
        [SerializeField] private Color labelColor = new Color(0.94f, 1.0f, 1.0f, 1.0f);
        [SerializeField] private bool verboseLogging;

        private readonly List<ShotRecord> _shots = new List<ShotRecord>();
        private readonly List<Button> _shotButtons = new List<Button>();
        private int _selectedShotIndex = -1;

        public string LastStatus { get; private set; } = string.Empty;
        public int ShotCount => _shots.Count;

        private void Awake()
        {
            if (liveResultReceiver == null)
            {
                liveResultReceiver = FindFirstObjectByType<StandaloneQuestLiveResultReceiver>();
            }

            if (shotReplayRenderer == null)
            {
                shotReplayRenderer = FindFirstObjectByType<StandaloneQuestShotReplayRenderer>();
            }

            EnsureUiObjects();
            RefreshList();
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
            if (liveResultReceiver == null)
            {
                return;
            }

            liveResultReceiver.ShotResultReceived -= OnShotResultReceived;
            liveResultReceiver.ShotResultReceived += OnShotResultReceived;
        }

        private void Unsubscribe()
        {
            if (liveResultReceiver == null)
            {
                return;
            }

            liveResultReceiver.ShotResultReceived -= OnShotResultReceived;
        }

        private void OnShotResultReceived(StandaloneShotResult result)
        {
            if (result == null)
            {
                SetEmptyLabel("No Replay");
                SetStatus("shot_result_missing");
                return;
            }

            if (!result.success)
            {
                if (_shots.Count == 0)
                {
                    SetEmptyLabel(_failureToLabel(result.failureReason));
                }

                SetStatus("shot_result_failed:" + (result.failureReason ?? string.Empty));
                return;
            }

            if (result.trajectory == null || result.trajectory.Length == 0)
            {
                if (_shots.Count == 0)
                {
                    SetEmptyLabel("No Replay");
                }

                SetStatus("shot_result_empty_trajectory");
                return;
            }

            _shots.Add(new ShotRecord(_shots.Count + 1, result));
            _selectedShotIndex = _shots.Count - 1;
            RefreshList();
            SetStatus($"shot_added index={_shots.Count} points={result.trajectory.Length}");
        }

        private void SelectShot(int shotIndex)
        {
            if (shotIndex < 0 || shotIndex >= _shots.Count)
            {
                return;
            }

            _selectedShotIndex = shotIndex;
            var record = _shots[shotIndex];
            if (shotReplayRenderer != null)
            {
                shotReplayRenderer.RenderShotResult(record.Result);
            }

            RefreshList();
            SetStatus($"shot_selected index={record.DisplayIndex}");
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

            ConfigureText(emptyLabel, emptyText, 18, 38);
            var emptyRect = emptyLabel.GetComponent<RectTransform>();
            emptyRect.anchorMin = Vector2.zero;
            emptyRect.anchorMax = Vector2.one;
            emptyRect.offsetMin = Vector2.zero;
            emptyRect.offsetMax = Vector2.zero;
        }

        private void RefreshList()
        {
            EnsureUiObjects();

            var visibleCount = Mathf.Min(Mathf.Max(1, maxVisibleShots), _shots.Count);
            var visibleStart = Mathf.Max(0, _shots.Count - visibleCount);
            EnsureButtonCount(visibleCount);

            var hasShots = _shots.Count > 0;
            if (emptyLabel != null)
            {
                emptyLabel.gameObject.SetActive(!hasShots);
                if (!hasShots && string.IsNullOrWhiteSpace(emptyLabel.text))
                {
                    emptyLabel.text = emptyText;
                }
            }

            for (var index = 0; index < _shotButtons.Count; index++)
            {
                var button = _shotButtons[index];
                var active = index < visibleCount;
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
            ConfigureText(label, string.Empty, 18, 34);
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
                    SelectShot(capturedIndex);
                }
            });

            var label = button.GetComponentInChildren<Text>(true);
            if (label != null)
            {
                label.text = shotLabelPrefix + record.DisplayIndex;
            }
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
            rectTransform.anchoredPosition = new Vector2(x, 0.0f);
            rectTransform.localRotation = Quaternion.identity;
            rectTransform.localScale = Vector3.one;
            rectTransform.sizeDelta = buttonSize;
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
            text.resizeTextForBestFit = true;
            text.resizeTextMinSize = minSize;
            text.resizeTextMaxSize = maxSize;
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

        private string _failureToLabel(string failureReason)
        {
            if (string.IsNullOrWhiteSpace(failureReason))
            {
                return "No Replay";
            }

            if (failureReason.StartsWith("lane_lock_result_missing") || failureReason.StartsWith("lane_lock_confirm_missing"))
            {
                return "Lock Lane First";
            }

            if (failureReason.StartsWith("yolo_detection_failed"))
            {
                return "Ball Not Found";
            }

            if (failureReason.StartsWith("sam2_tracking_failed"))
            {
                return "Track Failed";
            }

            return "Replay Failed";
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
