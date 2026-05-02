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
    public sealed class StandaloneLaneLockConfidenceBreakdown
    {
        public float edgeFit;
        public float selectionAgreement;
        public float markingAgreement;
        public float temporalStability;
        public float candidateMargin;
        public float visibleExtent;
    }

    [Serializable]
    public sealed class StandaloneReleaseCorridor
    {
        public float sStartMeters;
        public float sEndMeters;
        public float halfWidthMeters;
    }

    [Serializable]
    public sealed class StandaloneReprojectionMetrics
    {
        public float meanErrorPx;
        public float p95ErrorPx;
        public float runnerUpMargin;
    }

    [Serializable]
    public sealed class StandaloneSourceFrameRange
    {
        public int start;
        public int end;
    }

    [Serializable]
    public sealed class StandaloneLaneLockResult
    {
        public string schemaVersion = "lane_lock_result";
        public string sessionId;
        public string requestId;
        public bool success;
        public string failureReason;
        public float confidence;
        public StandaloneLaneLockConfidenceBreakdown confidenceBreakdown;
        public string lockState;
        public bool requiresConfirmation;
        public bool userConfirmed;
        public int previewFrameSeq;
        public Vector3 laneOriginWorld;
        public Quaternion laneRotationWorld = Quaternion.identity;
        public float laneWidthMeters;
        public float laneLengthMeters;
        public Vector3 floorPlanePointWorld;
        public Vector3 floorPlaneNormalWorld = Vector3.up;
        public float visibleDownlaneMeters;
        public StandaloneReleaseCorridor releaseCorridor;
        public StandaloneReprojectionMetrics reprojectionMetrics;
        public StandaloneSourceFrameRange sourceFrameRange;
    }

    [Serializable]
    public sealed class StandaloneLanePoint
    {
        public float xMeters;
        public float sMeters;
        public float hMeters;
    }

    [Serializable]
    public sealed class StandaloneLaneSpaceBallPoint
    {
        public string schemaVersion = "lane_space_ball_point";
        public string sessionId;
        public string shotId;
        public ulong frameSeq;
        public long cameraTimestampUs;
        public long ptsUs;
        public Vector2 imagePointPx;
        public string pointDefinition;
        public Vector3 worldPoint;
        public StandaloneLanePoint lanePoint;
        public bool isOnLockedLane;
        public float projectionConfidence;
    }

    [Serializable]
    public sealed class StandaloneShotTrackingSummary
    {
        public string source;
        public bool yoloSuccess;
        public bool sam2Success;
        public int trackedFrames;
        public int trajectoryPoints;
        public float averageProjectionConfidence;
    }

    [Serializable]
    public sealed class StandaloneTrajectoryCoverageStats
    {
        public float startSFeet;
        public float endSFeet;
        public float trackedDistanceFeet;
        public float coverageConfidence;
    }

    [Serializable]
    public sealed class StandaloneShotSpeedStats
    {
        public float averageMph;
        public float earlyMph;
        public float entryMph;
        public float speedLossMph;
        public bool hasAverageSpeed;
        public bool hasEarlySpeed;
        public bool hasEntrySpeed;
        public bool hasSpeedLoss;
    }

    [Serializable]
    public sealed class StandaloneShotPositionStats
    {
        public float arrowsBoard;
        public float breakpointBoard;
        public float breakpointDistanceFeet;
        public float entryBoard;
        public float boardsCrossed;
        public bool hasArrowsBoard;
        public bool hasBreakpoint;
        public bool hasEntryBoard;
    }

    [Serializable]
    public sealed class StandaloneShotAngleStats
    {
        public float launchAngleDegrees;
        public float entryAngleDegrees;
        public float signedEntryAngleDegrees;
        public float breakpointAngleDegrees;
        public bool hasLaunchAngle;
        public bool hasEntryAngle;
        public bool hasBreakpointAngle;
    }

    [Serializable]
    public sealed class StandaloneShotStatMilestone
    {
        public string kind;
        public string label;
        public int frameSeq;
        public float sMeters;
        public float xMeters;
        public float board;
        public float distanceFeet;
        public float normalizedReplayTime;
        public string primaryValue;
    }

    [Serializable]
    public sealed class StandaloneShotStats
    {
        public string schemaVersion = "shot_stats_v1";
        public string pointDefinition;
        public float laneLengthMeters;
        public float laneWidthMeters;
        public int boardCount;
        public StandaloneTrajectoryCoverageStats trajectoryCoverage;
        public StandaloneShotSpeedStats speed;
        public StandaloneShotPositionStats positions;
        public StandaloneShotAngleStats angles;
        public StandaloneShotStatMilestone[] milestones;
    }

    [Serializable]
    public sealed class StandaloneShotResult
    {
        public string schemaVersion = "shot_result";
        public string sessionId;
        public string shotId;
        public string windowId;
        public bool success;
        public string failureReason;
        public string laneLockRequestId;
        public StandaloneSourceFrameRange sourceFrameRange;
        public StandaloneShotTrackingSummary trackingSummary;
        public StandaloneShotStats shotStats;
        public StandaloneLaneSpaceBallPoint[] trajectory;
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
