using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public static class StandaloneQuestCommandGate
    {
        private const float DefaultMinimumSpacingSeconds = 0.15f;

        private static float _lastAcceptedRealtime = -1000.0f;
        public static bool TryAccept(string commandName)
        {
            return TryAccept(commandName, DefaultMinimumSpacingSeconds);
        }

        public static bool TryAccept(string commandName, float minimumSpacingSeconds)
        {
            var now = Time.realtimeSinceStartup;
            var spacing = Mathf.Max(0.0f, minimumSpacingSeconds);
            if (now - _lastAcceptedRealtime < spacing)
            {
                return false;
            }

            _lastAcceptedRealtime = now;
            return true;
        }

        public static void Reset()
        {
            _lastAcceptedRealtime = -1000.0f;
        }
    }
}
