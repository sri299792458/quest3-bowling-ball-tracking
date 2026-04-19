using System;

namespace QuestBowlingStandalone.QuestApp
{
    [Serializable]
    public sealed class StandaloneProofDiagnostics
    {
        public string schemaVersion = "proof_diagnostics_v1";
        public bool beginRequested;
        public bool beginSucceeded;
        public bool finalizeRequested;
        public bool finalizeSucceeded;
        public bool encoderStartRequested;
        public bool encoderStartSucceeded;
        public bool encoderStopRequested;
        public bool encoderStopSucceeded;
        public int renderAttemptCount;
        public int renderSuccessCount;
        public int renderSkipCount;
        public int encoderSurfaceReadyCount;
        public int encoderSurfaceMissingCount;
        public int surfaceBindAttemptCount;
        public int surfaceBindSuccessCount;
        public int surfaceBindFailureCount;
        public int blitIssuedCount;
        public int frameMetadataAppendSuccessCount;
        public int frameMetadataAppendFailureCount;
        public long lastPtsUs = -1;
        public bool lastIsKeyframe;
        public string activeClipDirectory = string.Empty;
        public string beginNote = string.Empty;
        public string finalizeNote = string.Empty;
        public string encoderStartNote = string.Empty;
        public string encoderStopNote = string.Empty;
        public string lastRenderNote = string.Empty;
        public string lastEncoderSurfaceNote = string.Empty;
        public string lastSurfaceBindNote = string.Empty;
        public string lastFrameAppendNote = string.Empty;
    }
}
