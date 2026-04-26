using System;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public readonly struct StandaloneQuestRaySelection
    {
        public StandaloneQuestRaySelection(
            Vector3 originWorld,
            Vector3 directionWorld,
            float maxDistanceMeters,
            string source,
            float realtimeSeconds)
        {
            OriginWorld = originWorld;
            DirectionWorld = directionWorld.normalized;
            MaxDistanceMeters = maxDistanceMeters;
            Source = source ?? string.Empty;
            RealtimeSeconds = realtimeSeconds;
        }

        public Vector3 OriginWorld { get; }
        public Vector3 DirectionWorld { get; }
        public float MaxDistanceMeters { get; }
        public string Source { get; }
        public float RealtimeSeconds { get; }
    }

    public sealed class StandaloneQuestRayInteractor : MonoBehaviour
    {
        [Header("Ray Source")]
        [SerializeField] private Transform rayTransform;
        [SerializeField] private float maxRayDistanceMeters = 30.0f;

        [Header("Selection Input")]
        [SerializeField] private bool selectWithHandPinch = true;
        [SerializeField] private bool selectWithControllerTrigger = true;
        [SerializeField] private OVRInput.Controller controller = OVRInput.Controller.RTouch;
        [SerializeField] private OVRInput.Button selectButton = OVRInput.Button.PrimaryIndexTrigger;
        [SerializeField] private bool debugKeyboardSelect = true;
        [SerializeField] private KeyCode debugSelectKey = KeyCode.Space;

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging;

        private OVRHand _cachedHand;
        private bool _wasHandPinching;

        public event Action<StandaloneQuestRaySelection> SelectionPerformed;

        public Transform RayTransform => rayTransform;
        public float MaxRayDistanceMeters => Mathf.Max(0.1f, maxRayDistanceMeters);

        private void Awake()
        {
            CacheHandFromRayTransform();
        }

        private void Update()
        {
            if (!WasSelectionPressedThisFrame())
            {
                return;
            }

            if (!TryGetCurrentRay(out var selection, out var note))
            {
                DebugLog($"Selection ignored: {note}");
                return;
            }

            DebugLog($"Selection emitted: source={selection.Source} origin={selection.OriginWorld} direction={selection.DirectionWorld}");
            SelectionPerformed?.Invoke(selection);
        }

        public void SetRayTransform(Transform value)
        {
            rayTransform = value;
            CacheHandFromRayTransform();
        }

        public bool TryGetCurrentRay(out StandaloneQuestRaySelection selection, out string note)
        {
            selection = default;
            note = "ray_unavailable";

            if (rayTransform == null)
            {
                note = "ray_transform_missing";
                return false;
            }

            var direction = rayTransform.forward;
            if (!IsFinite(direction) || direction.sqrMagnitude <= 0.0001f)
            {
                note = "ray_direction_invalid";
                return false;
            }

            selection = new StandaloneQuestRaySelection(
                rayTransform.position,
                direction,
                MaxRayDistanceMeters,
                rayTransform.name,
                Time.realtimeSinceStartup);
            note = "ray_ready";
            return true;
        }

        public bool TryEmitSelectionNow(out string note)
        {
            if (!TryGetCurrentRay(out var selection, out note))
            {
                return false;
            }

            SelectionPerformed?.Invoke(selection);
            note = "selection_emitted";
            DebugLog($"Selection emitted manually: source={selection.Source} origin={selection.OriginWorld} direction={selection.DirectionWorld}");
            return true;
        }

        private bool WasSelectionPressedThisFrame()
        {
            var pressed = false;

            if (selectWithHandPinch)
            {
                var isPinching = IsHandPinching();
                pressed |= isPinching && !_wasHandPinching;
                _wasHandPinching = isPinching;
            }

            if (selectWithControllerTrigger)
            {
                pressed |= OVRInput.GetDown(selectButton, controller);
            }

            if (debugKeyboardSelect)
            {
                pressed |= Input.GetKeyDown(debugSelectKey);
            }

            return pressed;
        }

        private bool IsHandPinching()
        {
            var hand = _cachedHand;
            if (hand == null)
            {
                CacheHandFromRayTransform();
                hand = _cachedHand;
            }

            return hand != null
                && hand.IsTracked
                && hand.GetFingerIsPinching(OVRHand.HandFinger.Index);
        }

        private void CacheHandFromRayTransform()
        {
            _cachedHand = rayTransform != null ? rayTransform.GetComponentInParent<OVRHand>() : null;
        }

        private static bool IsFinite(Vector3 value)
        {
            return IsFinite(value.x) && IsFinite(value.y) && IsFinite(value.z);
        }

        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestRayInteractor] {message}");
        }
    }
}
