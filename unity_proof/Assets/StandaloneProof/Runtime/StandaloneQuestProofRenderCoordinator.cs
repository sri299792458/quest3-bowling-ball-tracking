using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestProofRenderCoordinator : MonoBehaviour
    {
        [SerializeField] private StandaloneQuestFrameSource frameSource;
        [SerializeField] private StandaloneQuestLocalProofCapture proofCapture;
        [SerializeField] private StandaloneQuestLiveMetadataSender liveMetadataSender;
        [SerializeField] private bool appendFrameMetadata = true;
        [SerializeField] private bool verboseLogging;

        private StandaloneQuestEncoderSurfaceInterop _surfaceInterop;
        private bool _surfaceBound;
        private IntPtrEquality _lastTexturePtr;
        private Vector2Int _lastTextureSize;
        private bool _captureWasActive;

        private void Awake()
        {
            _surfaceInterop = new StandaloneQuestEncoderSurfaceInterop();
        }

        private void LateUpdate()
        {
            if (frameSource == null || proofCapture == null)
            {
                return;
            }

            if (!proofCapture.IsCapturing)
            {
                ResetInteropState();
                _captureWasActive = false;
                return;
            }

            if (!_captureWasActive)
            {
                _captureWasActive = true;
            }

            if (!frameSource.TryRenderCurrentFrame(out var renderNote))
            {
                proofCapture.ReportRenderAttempt(false, renderNote);
                DebugLog($"Render skipped: {renderNote}");
                return;
            }

            proofCapture.ReportRenderAttempt(true, renderNote);

            if (!proofCapture.TryGetEncoderInputSurfaceRawObject(out var surfaceObject) || surfaceObject == System.IntPtr.Zero)
            {
                var encoderStatus = proofCapture.GetEncoderStatusJson();
                proofCapture.ReportEncoderSurfaceAvailability(false, encoderStatus);
                DebugLog($"Encoder surface not ready. {encoderStatus}");
                return;
            }

            proofCapture.ReportEncoderSurfaceAvailability(true, "surface_ready");

            if (!_surfaceBound)
            {
                var bound = _surfaceInterop.TryBindEncoderSurface(surfaceObject, out var bindNote);
                proofCapture.ReportSurfaceBind(bound, bindNote);
                DebugLog($"Surface bind: {(bound ? "ok" : "failed")} | {bindNote}");
                if (!bound)
                {
                    return;
                }

                _surfaceBound = true;
            }

            var outputTexture = frameSource.OutputTexture;
            if (outputTexture == null)
            {
                DebugLog("Frame source output texture missing.");
                return;
            }

            var nativeTexture = outputTexture.GetNativeTexturePtr();
            var size = new Vector2Int(outputTexture.width, outputTexture.height);
            if (_lastTexturePtr.Value != nativeTexture || _lastTextureSize != size)
            {
                _surfaceInterop.UpdateSourceTexture(outputTexture);
                _surfaceInterop.UpdateOutputSize(size.x, size.y);
                _lastTexturePtr = new IntPtrEquality(nativeTexture);
                _lastTextureSize = size;
            }

            if (!proofCapture.TryPrepareCurrentFrameMetadata(out var ptsUs, out var isKeyframe, out var prepareNote))
            {
                proofCapture.ReportFrameMetadataAppend(false, -1L, false, prepareNote);
                DebugLog($"Failed to prepare frame metadata: {prepareNote}");
                return;
            }

            _surfaceInterop.UpdatePresentationTimeUs(ptsUs);
            _surfaceInterop.IssueBlit();
            proofCapture.ReportBlitIssued();

            if (appendFrameMetadata)
            {
                var appended = proofCapture.CommitPreparedFrameMetadata();
                proofCapture.ReportFrameMetadataAppend(appended, ptsUs, isKeyframe, appended ? "frame_metadata_appended" : "frame_metadata_append_failed");
                if (!appended)
                {
                    DebugLog("Failed to append frame metadata.");
                }
                else if (liveMetadataSender != null && liveMetadataSender.EnabledForAutoRun)
                {
                    var sent = liveMetadataSender.TrySendFrameMetadata(
                        proofCapture.ActiveSessionId,
                        proofCapture.ActiveStreamId,
                        proofCapture.LastCommittedFrameMetadata,
                        out var metadataNote);
                    if (!sent)
                    {
                        DebugLog($"Live metadata send failed: {metadataNote}");
                    }
                }
            }
            else
            {
                proofCapture.DiscardPreparedFrameMetadata();
            }
        }

        private void OnDisable()
        {
            ResetInteropState();
        }

        private void OnDestroy()
        {
            _surfaceInterop?.Dispose();
            _surfaceInterop = null;
        }

        private void ResetInteropState()
        {
            if (_surfaceBound)
            {
                _surfaceInterop?.ClearEncoderSurface();
            }

            _surfaceBound = false;
            _lastTexturePtr = default;
            _lastTextureSize = Vector2Int.zero;
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestProofRenderCoordinator] {message}");
        }

        private readonly struct IntPtrEquality
        {
            public readonly System.IntPtr Value;

            public IntPtrEquality(System.IntPtr value)
            {
                Value = value;
            }
        }
    }
}
