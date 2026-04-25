using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestFloorPlaneSource : MonoBehaviour
    {
        [SerializeField] private Transform floorReference;
        [SerializeField] private Vector3 fallbackPlanePointWorld = Vector3.zero;
        [SerializeField] private Vector3 fallbackPlaneNormalWorld = Vector3.up;
        [SerializeField] private bool verboseLogging;

        public bool TryGetFloorPlane(out Vector3 planePointWorld, out Vector3 planeNormalWorld, out string note)
        {
            if (floorReference != null)
            {
                planePointWorld = floorReference.position;
                planeNormalWorld = floorReference.up.sqrMagnitude > 0.0f ? floorReference.up.normalized : Vector3.up;
                note = "floor_reference_transform";
                return true;
            }

            if (fallbackPlaneNormalWorld.sqrMagnitude <= 1e-6f)
            {
                planePointWorld = Vector3.zero;
                planeNormalWorld = Vector3.up;
                note = "floor_plane_normal_missing";
                DebugLog("Fallback floor plane normal was invalid.");
                return false;
            }

            planePointWorld = fallbackPlanePointWorld;
            planeNormalWorld = fallbackPlaneNormalWorld.normalized;
            note = "floor_reference_fallback";
            return true;
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestFloorPlaneSource] {message}");
        }
    }
}
