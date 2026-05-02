using UnityEngine;
using UnityEngine.UI;

namespace QuestBowlingStandalone.QuestApp
{
    public enum StandaloneQuestLaneLockActionKind
    {
        Primary,
        Secondary,
    }

    [RequireComponent(typeof(Button))]
    public sealed class StandaloneQuestLaneLockButton : MonoBehaviour
    {
        [SerializeField] private StandaloneQuestLaneLockStateCoordinator laneLockCoordinator;
        [SerializeField] private StandaloneQuestLaneLockActionKind actionKind = StandaloneQuestLaneLockActionKind.Primary;
        [SerializeField] private Text label;
        [SerializeField] private CanvasGroup canvasGroup;
        [SerializeField] private string coordinatorMissingText = "Lane UI Missing";
        [SerializeField] private float visibleAlpha = 1.0f;
        [SerializeField] private float hiddenAlpha = 0.0f;
        [SerializeField] private bool verboseLogging;

        private Button _button;

        private void Awake()
        {
            _button = GetComponent<Button>();
            _button.onClick.AddListener(OnButtonClicked);

            if (laneLockCoordinator == null)
            {
                laneLockCoordinator = FindFirstObjectByType<StandaloneQuestLaneLockStateCoordinator>();
            }

            if (canvasGroup == null)
            {
                canvasGroup = GetComponent<CanvasGroup>();
            }

            RefreshVisualState();
        }

        private void OnDestroy()
        {
            if (_button != null)
            {
                _button.onClick.RemoveListener(OnButtonClicked);
            }
        }

        private void Update()
        {
            RefreshVisualState();
        }

        private void OnButtonClicked()
        {
            if (!StandaloneQuestCommandGate.TryAccept($"lane_lock_{actionKind}"))
            {
                return;
            }

            if (laneLockCoordinator == null)
            {
                DebugLog("Lane lock button pressed without a coordinator.");
                RefreshVisualState();
                return;
            }

            if (actionKind == StandaloneQuestLaneLockActionKind.Secondary)
            {
                laneLockCoordinator.HandleSecondaryAction();
            }
            else
            {
                laneLockCoordinator.HandlePrimaryAction();
            }

            RefreshVisualState();
        }

        private void RefreshVisualState()
        {
            var visible = IsActionVisible();
            var interactable = laneLockCoordinator != null && visible && IsActionInteractable();
            if (_button != null)
            {
                _button.interactable = interactable;
            }

            if (canvasGroup != null)
            {
                canvasGroup.alpha = visible ? visibleAlpha : hiddenAlpha;
                canvasGroup.interactable = interactable;
                canvasGroup.blocksRaycasts = visible && interactable;
            }

            if (label != null)
            {
                label.text = laneLockCoordinator != null
                    ? ActionLabel()
                    : coordinatorMissingText;
            }
        }

        private bool IsActionVisible()
        {
            return laneLockCoordinator == null
                || (actionKind == StandaloneQuestLaneLockActionKind.Primary
                    ? laneLockCoordinator.PrimaryActionVisible
                    : laneLockCoordinator.SecondaryActionVisible);
        }

        private bool IsActionInteractable()
        {
            return actionKind == StandaloneQuestLaneLockActionKind.Secondary
                ? laneLockCoordinator.SecondaryActionInteractable
                : laneLockCoordinator.PrimaryActionInteractable;
        }

        private string ActionLabel()
        {
            return actionKind == StandaloneQuestLaneLockActionKind.Secondary
                ? laneLockCoordinator.SecondaryActionLabel
                : laneLockCoordinator.PrimaryActionLabel;
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestLaneLockButton] {message}");
        }
    }
}
