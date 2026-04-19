using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestProofRenderCoordinator : MonoBehaviour
    {
        [SerializeField] private StandaloneQuestFrameSource frameSource;
        [SerializeField] private StandaloneQuestLocalProofCapture proofCapture;
        [SerializeField] private bool verboseLogging;

        private StandaloneQuestEncoderSurfaceInterop _surfaceInterop;
        private bool _surfaceBound;
        private IntPtrEquality _lastTexturePtr;
        private Vector2Int _lastTextureSize;

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
                return;
            }

            if (!frameSource.TryRenderCurrentFrame(out var renderNote))
            {
                DebugLog($"Render skipped: {renderNote}");
                return;
            }

            if (!proofCapture.TryGetEncoderInputSurfaceRawObject(out var surfaceObject) || surfaceObject == System.IntPtr.Zero)
            {
                DebugLog("Encoder surface not ready.");
                return;
            }

            if (!_surfaceBound)
            {
                var bound = _surfaceInterop.TryBindEncoderSurface(surfaceObject, out var bindNote);
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

            _surfaceInterop.IssueBlit();
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
