using System;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestSessionContext : MonoBehaviour
    {
        [SerializeField] private bool verboseLogging;

        private string _sessionId;

        public string ActiveSessionId => _sessionId ?? string.Empty;

        public string EnsureSessionId()
        {
            if (string.IsNullOrWhiteSpace(_sessionId))
            {
                _sessionId = Guid.NewGuid().ToString("N");
                DebugLog($"Created new sessionId={_sessionId}");
            }

            return _sessionId;
        }

        public void SetSessionId(string sessionId)
        {
            if (string.IsNullOrWhiteSpace(sessionId))
            {
                return;
            }

            _sessionId = sessionId.Trim();
            DebugLog($"Set sessionId={_sessionId}");
        }

        public void ResetSessionId()
        {
            _sessionId = Guid.NewGuid().ToString("N");
            DebugLog($"Reset sessionId={_sessionId}");
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestSessionContext] {message}");
        }
    }
}
