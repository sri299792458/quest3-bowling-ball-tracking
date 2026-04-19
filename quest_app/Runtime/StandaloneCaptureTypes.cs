using System;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public enum StandaloneLaneLockState
    {
        Unknown = 0,
        Locked = 1,
        Suspect = 2,
        Invalid = 3,
    }

    public enum StandaloneTimestampSource
    {
        Unknown = 0,
        PassthroughCamera = 1,
        SystemUtcFallback = 2,
    }

    [Serializable]
    public sealed class StandaloneSessionMetadata
    {
        public string schemaVersion = "capture_metadata_v1";
        public string sessionId;
        public string deviceName;
        public string cameraSide;
        public int requestedWidth;
        public int requestedHeight;
        public int actualWidth;
        public int actualHeight;
        public float requestedFps;
        public float actualSourceFps;
        public string videoCodec;
        public int targetBitrateKbps;
        public float fx;
        public float fy;
        public float cx;
        public float cy;
        public int sensorWidth;
        public int sensorHeight;
        public Vector3 lensOffsetPosition;
        public Quaternion lensOffsetRotation;
    }

    [Serializable]
    public sealed class StandaloneLaneLockMetadata
    {
        public string schemaVersion = "capture_metadata_v1";
        public StandaloneLaneLockState laneLockState = StandaloneLaneLockState.Unknown;
        public long lockedAtUnixMs;
        public float confidence;
        public Vector3 laneOriginWorld;
        public Quaternion laneRotationWorld = Quaternion.identity;
        public float laneWidthMeters;
        public float laneLengthMeters;
    }

    [Serializable]
    public sealed class StandaloneFrameMetadata
    {
        public string schemaVersion = "capture_metadata_v1";
        public ulong frameSeq;
        public long cameraTimestampUs;
        public long ptsUs;
        public bool isKeyframe;
        public int width;
        public int height;
        public StandaloneTimestampSource timestampSource;
        public Vector3 cameraPosition;
        public Quaternion cameraRotation = Quaternion.identity;
        public Vector3 headPosition;
        public Quaternion headRotation = Quaternion.identity;
        public StandaloneLaneLockState laneLockState = StandaloneLaneLockState.Unknown;
    }

    [Serializable]
    public sealed class StandaloneShotMetadata
    {
        public string schemaVersion = "capture_metadata_v1";
        public string shotId;
        public long shotStartTimeUs;
        public long shotEndTimeUs;
        public int preRollMs;
        public int postRollMs;
        public string triggerReason;
        public StandaloneLaneLockState laneLockStateAtShotStart = StandaloneLaneLockState.Unknown;
    }

    [Serializable]
    public sealed class StandaloneLocalClipManifest
    {
        public string schemaVersion = "local_clip_artifact_v1";
        public string sessionId;
        public string shotId;
        public string mediaPath;
        public string sessionMetadataPath;
        public string laneLockMetadataPath;
        public string frameMetadataPath;
        public string shotMetadataPath;
    }
}
