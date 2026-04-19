using System.Collections;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneProofAutoRun : MonoBehaviour
    {
        [SerializeField] private StandaloneQuestLocalProofCapture proofCapture;
        [SerializeField] private float startupDelaySeconds = 2.0f;
        [SerializeField] private float maxBeginWaitSeconds = 20.0f;
        [SerializeField] private float beginRetryIntervalSeconds = 0.25f;
        [SerializeField] private float captureDurationSeconds = 6.0f;
        [SerializeField] private int preRollMs = 0;
        [SerializeField] private int postRollMs = 0;
        [SerializeField] private string shotId = "standalone-proof";
        [SerializeField] private bool verboseLogging = true;

        private Coroutine _runCoroutine;

        private void OnEnable()
        {
            if (_runCoroutine == null)
            {
                _runCoroutine = StartCoroutine(RunProofCapture());
            }
        }

        private void OnDisable()
        {
            if (_runCoroutine != null)
            {
                StopCoroutine(_runCoroutine);
                _runCoroutine = null;
            }
        }

        private IEnumerator RunProofCapture()
        {
            yield return new WaitForSeconds(startupDelaySeconds);

            if (proofCapture == null)
            {
                DebugLog("Proof capture component missing.");
                yield break;
            }

            var started = false;
            var beginDeadline = Time.realtimeSinceStartup + Mathf.Max(0.0f, maxBeginWaitSeconds);
            var retryInterval = Mathf.Max(0.05f, beginRetryIntervalSeconds);
            while (!started && Time.realtimeSinceStartup <= beginDeadline)
            {
                started = proofCapture.TryBeginProofClip(shotId, preRollMs, postRollMs, "auto_proof_capture");
                if (started)
                {
                    break;
                }

                yield return new WaitForSeconds(retryInterval);
            }

            DebugLog($"Begin proof clip: {(started ? "ok" : "failed")}");
            if (!started)
            {
                DebugLog("Giving up on proof clip start because the camera never became ready.");
                yield break;
            }

            yield return new WaitForSeconds(captureDurationSeconds);

            var finalized = proofCapture.TryFinalizeProofClip();
            DebugLog($"Finalize proof clip: {(finalized ? "ok" : "failed")}");
            _runCoroutine = null;
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneProofAutoRun] {message}");
        }
    }
}
