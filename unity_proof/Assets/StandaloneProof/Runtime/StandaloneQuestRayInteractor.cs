using System;
using Oculus.Interaction;
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
        [Header("Interaction SDK")]
        [SerializeField] private RayInteractor interactionRayInteractor;
        [SerializeField] private UnityEngine.Object interactionSelector;
        [SerializeField] private bool selectWithInteractionSdk = true;

        [Header("Ray Source")]
        [SerializeField] private Transform rayTransform;
        [SerializeField] private float maxRayDistanceMeters = 30.0f;

        [Header("Diagnostics")]
        [SerializeField] private bool debugKeyboardSelect;
        [SerializeField] private KeyCode debugSelectKey = KeyCode.Space;
        [SerializeField] private bool verboseLogging;

        private ISelector _cachedInteractionSelector;

        public event Action<StandaloneQuestRaySelection> SelectionPerformed;

        public RayInteractor InteractionRayInteractor => interactionRayInteractor;
        public Transform RayTransform => rayTransform;
        public float MaxRayDistanceMeters => Mathf.Max(0.1f, maxRayDistanceMeters);

        private void Awake()
        {
            CacheInteractionSelector();
        }

        private void OnEnable()
        {
            SubscribeInteractionSelector();
        }

        private void OnDisable()
        {
            UnsubscribeInteractionSelector();
        }

        private void Update()
        {
            if (!debugKeyboardSelect || !Input.GetKeyDown(debugSelectKey))
            {
                return;
            }

            EmitSelection("debug_keyboard_select");
        }

        public void SetRayTransform(Transform value)
        {
            rayTransform = value;
        }

        public void SetInteractionRaySource(
            RayInteractor rayInteractor,
            UnityEngine.Object selector,
            Transform rayOrigin)
        {
            UnsubscribeInteractionSelector();
            interactionRayInteractor = rayInteractor;
            interactionSelector = selector;
            rayTransform = rayOrigin;
            CacheInteractionSelector();
            SubscribeInteractionSelector();
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
                interactionRayInteractor != null ? interactionRayInteractor.name : rayTransform.name,
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
            return true;
        }

        private void CacheInteractionSelector()
        {
            _cachedInteractionSelector = interactionSelector as ISelector;
        }

        private void SubscribeInteractionSelector()
        {
            if (!selectWithInteractionSdk)
            {
                return;
            }

            if (_cachedInteractionSelector == null)
            {
                CacheInteractionSelector();
            }

            if (_cachedInteractionSelector == null)
            {
                DebugLog("Interaction SDK selector missing.");
                return;
            }

            _cachedInteractionSelector.WhenSelected -= OnInteractionSdkSelected;
            _cachedInteractionSelector.WhenSelected += OnInteractionSdkSelected;
        }

        private void UnsubscribeInteractionSelector()
        {
            if (_cachedInteractionSelector == null)
            {
                return;
            }

            _cachedInteractionSelector.WhenSelected -= OnInteractionSdkSelected;
        }

        private void OnInteractionSdkSelected()
        {
            EmitSelection("interaction_sdk_select");
        }

        private void EmitSelection(string reason)
        {
            if (!TryGetCurrentRay(out var selection, out var note))
            {
                DebugLog($"Selection ignored ({reason}): {note}");
                return;
            }

            SelectionPerformed?.Invoke(selection);
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
