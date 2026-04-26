using UnityEngine;
using UnityEngine.UI;

namespace QuestBowlingStandalone.QuestApp
{
    [RequireComponent(typeof(Button))]
    public sealed class StandaloneQuestLaneLockButton : MonoBehaviour
    {
        [SerializeField] private StandaloneQuestLaneLockCapture laneLockCapture;
        [SerializeField] private StandaloneQuestFoulLineRaySelector foulLineSelector;
        [SerializeField] private Text label;
        [SerializeField] private string idleText = "Lock Lane";
        [SerializeField] private string selectLeftText = "Select Left Edge";
        [SerializeField] private string selectRightText = "Select Right Edge";
        [SerializeField] private string activeText = "Locking...";
        [SerializeField] private float statusHoldSeconds = 2.0f;
        [SerializeField] private bool verboseLogging;

        private Button _button;
        private bool _lastActiveState;
        private string _lastObservedNote = string.Empty;
        private string _lastObservedSelectionStatus = string.Empty;
        private string _transientStatusText = string.Empty;
        private float _transientStatusUntilRealtime;

        private void Awake()
        {
            _button = GetComponent<Button>();
            _button.onClick.AddListener(OnButtonClicked);
            RefreshVisualState(force: true);
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
            RefreshVisualState(force: false);
        }

        private void OnButtonClicked()
        {
            if (laneLockCapture == null)
            {
                DebugLog("Lane lock button pressed without a capture target.");
                return;
            }

            if (laneLockCapture.IsRequestActive)
            {
                RefreshVisualState(force: true);
                return;
            }

            if (!laneLockCapture.HasFoulLineSelection)
            {
                if (foulLineSelector == null)
                {
                    ShowTransientStatus("Selector Missing");
                    RefreshVisualState(force: true);
                    return;
                }

                if (!foulLineSelector.IsSelectionActive)
                {
                    foulLineSelector.BeginFoulLineSelection();
                }

                RefreshVisualState(force: true);
                return;
            }

            var started = laneLockCapture.TryBeginLaneLockRequest(out var note);
            DebugLog($"Lane lock button pressed: {(started ? "started" : "ignored")} | {note}");
            if (!started)
            {
                ShowTransientStatus(_noteToLabel(note));
            }
            RefreshVisualState(force: true);
        }

        private void RefreshVisualState(bool force)
        {
            var isActive = laneLockCapture != null && laneLockCapture.IsRequestActive;
            var isSelectingFoulLine = foulLineSelector != null && foulLineSelector.IsSelectionActive;
            var latestNote = laneLockCapture != null ? laneLockCapture.LastCompletionNote : string.Empty;
            if (!string.IsNullOrWhiteSpace(latestNote) && latestNote != _lastObservedNote)
            {
                _lastObservedNote = latestNote;
                if (!isActive && !isSelectingFoulLine)
                {
                    ShowTransientStatus(_noteToLabel(latestNote));
                }
            }

            var latestSelectionStatus = foulLineSelector != null ? foulLineSelector.LastStatus : string.Empty;
            if (!string.IsNullOrWhiteSpace(latestSelectionStatus) && latestSelectionStatus != _lastObservedSelectionStatus)
            {
                _lastObservedSelectionStatus = latestSelectionStatus;
                if (!isActive && !isSelectingFoulLine)
                {
                    ShowTransientStatus(_noteToLabel(latestSelectionStatus));
                }
            }

            _lastActiveState = isActive;

            if (_button != null)
            {
                _button.interactable = laneLockCapture != null && !isActive;
            }

            if (label != null)
            {
                if (isActive)
                {
                    label.text = activeText;
                }
                else if (isSelectingFoulLine)
                {
                    label.text = _selectionStatusToPersistentLabel(latestSelectionStatus);
                }
                else if (!string.IsNullOrEmpty(_transientStatusText) && Time.realtimeSinceStartup <= _transientStatusUntilRealtime)
                {
                    label.text = _transientStatusText;
                }
                else
                {
                    label.text = idleText;
                }
            }
        }

        private void ShowTransientStatus(string statusText)
        {
            if (string.IsNullOrWhiteSpace(statusText))
            {
                return;
            }

            _transientStatusText = statusText;
            _transientStatusUntilRealtime = Time.realtimeSinceStartup + Mathf.Max(0.25f, statusHoldSeconds);
        }

        private string _noteToLabel(string note)
        {
            if (string.IsNullOrWhiteSpace(note))
            {
                return idleText;
            }

            if (note.StartsWith("foul_line_selection_missing"))
            {
                return "Select Foul Line";
            }

            if (note.StartsWith("foul_line_selection"))
            {
                return "Foul Line Ready";
            }

            if (note.StartsWith("left_foul_line_point_selected"))
            {
                return "Select Right Edge";
            }

            if (note.StartsWith("floor_hit_outside_camera_image"))
            {
                return "Aim In View";
            }

            if (note.StartsWith("floor_hit_too_far"))
            {
                return "Aim Closer";
            }

            if (note.StartsWith("ray_parallel_to_floor") || note.StartsWith("floor_hit_behind_ray"))
            {
                return "Aim At Floor";
            }

            if (note.StartsWith("selection_frame_metadata_missing"))
            {
                return "Camera Not Ready";
            }

            if (note.StartsWith("floor_plane_unavailable:"))
            {
                return "Floor Not Ready";
            }

            if (note.StartsWith("session_stream_not_active"))
            {
                return "Starting Session";
            }

            if (note.StartsWith("lane_lock_request_started"))
            {
                return activeText;
            }

            if (note.StartsWith("lane_lock_request_sent"))
            {
                return "Analyzing...";
            }

            if (note.StartsWith("lane_lock_request_failed_no_frames"))
            {
                return "No Frames";
            }

            if (note.StartsWith("lane_lock_request_failed_low_frame_count"))
            {
                return "Hold Steady";
            }

            if (note.StartsWith("lane_lock_request_send_failed"))
            {
                return "Send Failed";
            }

            if (note.StartsWith("lane_lock_request_already_active"))
            {
                return activeText;
            }

            return "Try Again";
        }

        private string _selectionStatusToPersistentLabel(string note)
        {
            if (foulLineSelector != null && foulLineSelector.HasPendingLeftPoint)
            {
                return selectRightText;
            }

            if (string.IsNullOrWhiteSpace(note) || note.StartsWith("select_left_foul_line_point"))
            {
                return selectLeftText;
            }

            if (note.StartsWith("left_foul_line_point_selected"))
            {
                return selectRightText;
            }

            if (note.StartsWith("selection_frame_metadata_missing"))
            {
                return "Camera Not Ready";
            }

            if (note.StartsWith("floor_plane_unavailable:"))
            {
                return "Floor Not Ready";
            }

            if (note.StartsWith("floor_hit_outside_camera_image"))
            {
                return "Aim In View";
            }

            if (note.StartsWith("floor_hit_too_far"))
            {
                return "Aim Closer";
            }

            if (note.StartsWith("ray_parallel_to_floor") || note.StartsWith("floor_hit_behind_ray"))
            {
                return "Aim At Floor";
            }

            if (note.StartsWith("foul_line_selection_order_invalid"))
            {
                return "Right Edge Again";
            }

            return selectLeftText;
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
