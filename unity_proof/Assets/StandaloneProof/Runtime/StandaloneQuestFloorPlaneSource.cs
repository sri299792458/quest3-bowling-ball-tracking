using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestFloorPlaneSource : MonoBehaviour
    {
        [SerializeField] private Transform floorReference;
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

            planePointWorld = Vector3.zero;
            planeNormalWorld = Vector3.up;
            note = "floor_reference_missing";
            DebugLog("Floor reference transform is missing.");
            return false;
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
