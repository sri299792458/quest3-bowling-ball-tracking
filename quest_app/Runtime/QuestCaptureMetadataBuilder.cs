using System;
using Meta.XR;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public static class QuestCaptureMetadataBuilder
    {
        public static StandaloneSessionMetadata BuildSessionMetadata(
            string sessionId,
            string deviceName,
            string cameraSide,
            Vector2Int requestedResolution,
            Vector2Int actualResolution,
            float requestedFps,
            float actualSourceFps,
            string videoCodec,
            int targetBitrateKbps,
            PassthroughCameraAccess.CameraIntrinsics intrinsics)
        {
            return new StandaloneSessionMetadata
            {
                sessionId = sessionId ?? string.Empty,
                deviceName = deviceName ?? string.Empty,
                cameraSide = cameraSide ?? string.Empty,
                requestedWidth = requestedResolution.x,
                requestedHeight = requestedResolution.y,
                actualWidth = actualResolution.x,
                actualHeight = actualResolution.y,
                requestedFps = requestedFps,
                actualSourceFps = actualSourceFps,
                videoCodec = videoCodec ?? string.Empty,
                targetBitrateKbps = targetBitrateKbps,
                fx = intrinsics.FocalLength.x,
                fy = intrinsics.FocalLength.y,
                cx = intrinsics.PrincipalPoint.x,
                cy = intrinsics.PrincipalPoint.y,
                sensorWidth = intrinsics.SensorResolution.x,
                sensorHeight = intrinsics.SensorResolution.y,
                lensOffsetPosition = intrinsics.LensOffset.position,
                lensOffsetRotation = intrinsics.LensOffset.rotation,
            };
        }

        public static bool TryBuildFrameMetadata(
            ulong frameSeq,
            long ptsUs,
            bool isKeyframe,
            int width,
            int height,
            PassthroughCameraAccess cameraAccess,
            Transform headTransform,
            StandaloneLaneLockState laneLockState,
            out StandaloneFrameMetadata metadata,
            bool allowSystemUtcFallback = false)
        {
            metadata = null;
            if (cameraAccess == null || !cameraAccess.IsPlaying)
            {
                return false;
            }

            var cameraPose = cameraAccess.GetCameraPose();
            var headPose = ResolveHeadPose(headTransform, cameraPose);
            if (!TryGetFrameTimestampUs(cameraAccess, allowSystemUtcFallback, out var timestampUs, out var timestampSource))
            {
                return false;
            }

            metadata = new StandaloneFrameMetadata
            {
                frameSeq = frameSeq,
                cameraTimestampUs = timestampUs,
                ptsUs = ptsUs,
                isKeyframe = isKeyframe,
                width = width,
                height = height,
                timestampSource = timestampSource,
                cameraPosition = cameraPose.position,
                cameraRotation = cameraPose.rotation,
                headPosition = headPose.position,
                headRotation = headPose.rotation,
                laneLockState = laneLockState,
            };
            return true;
        }

        public static long ToUnixTimeUs(DateTime timestampUtc)
        {
            var utc = timestampUtc.Kind == DateTimeKind.Utc ? timestampUtc : timestampUtc.ToUniversalTime();
            return new DateTimeOffset(utc).ToUnixTimeMilliseconds() * 1000L;
        }

        public static bool TryGetFrameTimestampUs(
            PassthroughCameraAccess cameraAccess,
            bool allowSystemUtcFallback,
            out long timestampUs,
            out StandaloneTimestampSource source)
        {
            timestampUs = 0L;
            source = StandaloneTimestampSource.Unknown;

            if (cameraAccess != null && cameraAccess.IsPlaying)
            {
                var cameraTimestamp = cameraAccess.Timestamp;
                if (cameraTimestamp != default)
                {
                    timestampUs = ToUnixTimeUs(cameraTimestamp);
                    source = StandaloneTimestampSource.PassthroughCamera;
                    return true;
                }
            }

            if (!allowSystemUtcFallback)
            {
                return false;
            }

            timestampUs = ToUnixTimeUs(DateTime.UtcNow);
            source = StandaloneTimestampSource.SystemUtcFallback;
            return true;
        }

        private static Pose ResolveHeadPose(Transform headTransform, Pose cameraPose)
        {
            if (headTransform != null)
            {
                return new Pose(headTransform.position, headTransform.rotation);
            }

            if (Camera.main != null)
            {
                var main = Camera.main.transform;
                return new Pose(main.position, main.rotation);
            }

            return cameraPose;
        }
    }
}
