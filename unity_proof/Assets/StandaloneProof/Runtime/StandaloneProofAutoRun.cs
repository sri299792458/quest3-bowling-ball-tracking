using System.Collections;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneProofAutoRun : MonoBehaviour
    {
        [SerializeField] private StandaloneQuestLocalProofCapture proofCapture;
        [SerializeField] private StandaloneQuestLiveMetadataSender liveMetadataSender;
        [SerializeField] private float startupDelaySeconds = 2.0f;
        [SerializeField] private float maxBeginWaitSeconds = 20.0f;
        [SerializeField] private float beginRetryIntervalSeconds = 0.25f;
        [SerializeField] private float captureDurationSeconds = 6.0f;
        [SerializeField] private int preRollMs = 0;
        [SerializeField] private int postRollMs = 0;
        [SerializeField] private string shotId = "standalone-proof";
        [SerializeField] private bool enableLiveStreaming = true;
        [SerializeField] private string liveStreamHost = "10.235.26.83";
        [SerializeField] private int liveMediaPort = 8766;
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

            if (enableLiveStreaming)
            {
                var liveMediaStarted = proofCapture.TryStartLiveMediaStream(liveStreamHost, liveMediaPort, out var liveMediaNote);
                DebugLog($"Begin live media stream: {(liveMediaStarted ? "ok" : "failed")} | {liveMediaNote}");

                if (liveMetadataSender != null && liveMetadataSender.EnabledForAutoRun)
                {
                    var liveMetadataStarted = liveMetadataSender.TryBeginSession(
                        proofCapture.ActiveSessionId,
                        proofCapture.ActiveShotId,
                        proofCapture.CurrentSessionMetadata,
                        proofCapture.CurrentLaneLockMetadata,
                        proofCapture.CurrentShotMetadata,
                        out var liveMetadataNote);
                    DebugLog($"Begin live metadata stream: {(liveMetadataStarted ? "ok" : "failed")} | {liveMetadataNote}");
                }
            }

            yield return new WaitForSeconds(captureDurationSeconds);

            var finalized = proofCapture.TryFinalizeProofClip();
            DebugLog($"Finalize proof clip: {(finalized ? "ok" : "failed")}");

            if (enableLiveStreaming && liveMetadataSender != null && liveMetadataSender.EnabledForAutoRun)
            {
                var ended = liveMetadataSender.TryEndSession(
                    proofCapture.ActiveSessionId,
                    proofCapture.ActiveShotId,
                    finalized ? "proof_capture_finalized" : "proof_capture_finalize_failed",
                    out var endNote);
                DebugLog($"End live metadata stream: {(ended ? "ok" : "failed")} | {endNote}");
            }

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
