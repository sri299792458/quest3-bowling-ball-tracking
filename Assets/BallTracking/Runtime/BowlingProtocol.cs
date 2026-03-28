using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace BallTracking.Runtime.Transport
{
    public enum BowlingPacketType : ushort
    {
        Hello = 1,
        SessionConfig = 2,
        LaneCalibration = 3,
        FramePacket = 4,
        ShotMarker = 5,
        TrackerStatus = 6,
        ShotResult = 7,
        Ping = 8,
        Pong = 9,
        Error = 10,
    }

    public enum BowlingCodec : ushort
    {
        Jpeg = 1,
        H264 = 2,
        H265 = 3,
    }

    public enum BowlingShotMarkerType : ushort
    {
        SessionStarted = 0,
        Armed = 1,
        ShotStarted = 2,
        ShotEnded = 3,
        TrackerReset = 4,
    }

    [Serializable]
    public struct BowlingLaneCalibration
    {
        public bool isValid;
        public Vector3 origin;
        public Quaternion rotation;
        public float laneWidthMeters;
        public float laneLengthMeters;
    }

    public static class BowlingProtocol
    {
        public const uint Magic = 0x424F574C;
        public const ushort Version = 1;

        public static void WritePacket(Stream stream, BowlingPacketType type, byte[] payload)
        {
            payload ??= Array.Empty<byte>();
            var header = new byte[12];
            WriteUInt32(header, 0, Magic);
            WriteUInt16(header, 4, Version);
            WriteUInt16(header, 6, (ushort)type);
            WriteUInt32(header, 8, (uint)payload.Length);

            stream.Write(header, 0, header.Length);
            if (payload.Length > 0)
            {
                stream.Write(payload, 0, payload.Length);
            }

            stream.Flush();
        }

        public static async Task WritePacketAsync(Stream stream, BowlingPacketType type, byte[] payload, CancellationToken cancellationToken)
        {
            payload ??= Array.Empty<byte>();
            var header = new byte[12];
            WriteUInt32(header, 0, Magic);
            WriteUInt16(header, 4, Version);
            WriteUInt16(header, 6, (ushort)type);
            WriteUInt32(header, 8, (uint)payload.Length);

            await stream.WriteAsync(header, 0, header.Length, cancellationToken);
            if (payload.Length > 0)
            {
                await stream.WriteAsync(payload, 0, payload.Length, cancellationToken);
            }

            await stream.FlushAsync(cancellationToken);
        }

        public static (BowlingPacketType type, byte[] payload)? ReadPacket(Stream stream)
        {
            var header = ReadExact(stream, 12);
            if (header == null)
            {
                return null;
            }

            var magic = ReadUInt32(header, 0);
            if (magic != Magic)
            {
                throw new InvalidDataException($"Invalid packet magic 0x{magic:X8}");
            }

            var version = ReadUInt16(header, 4);
            if (version != Version)
            {
                throw new InvalidDataException($"Unsupported protocol version {version}");
            }

            var type = (BowlingPacketType)ReadUInt16(header, 6);
            var payloadLength = ReadUInt32(header, 8);
            var payload = payloadLength > 0
                ? ReadExact(stream, (int)payloadLength)
                : Array.Empty<byte>();

            if (payload == null)
            {
                return null;
            }

            return (type, payload);
        }

        public static async Task<(BowlingPacketType type, byte[] payload)?> ReadPacketAsync(Stream stream, CancellationToken cancellationToken)
        {
            var header = await ReadExactAsync(stream, 12, cancellationToken);
            if (header == null)
            {
                return null;
            }

            var magic = ReadUInt32(header, 0);
            if (magic != Magic)
            {
                throw new InvalidDataException($"Invalid packet magic 0x{magic:X8}");
            }

            var version = ReadUInt16(header, 4);
            if (version != Version)
            {
                throw new InvalidDataException($"Unsupported protocol version {version}");
            }

            var type = (BowlingPacketType)ReadUInt16(header, 6);
            var payloadLength = ReadUInt32(header, 8);
            var payload = payloadLength > 0
                ? await ReadExactAsync(stream, (int)payloadLength, cancellationToken)
                : Array.Empty<byte>();

            if (payload == null)
            {
                return null;
            }

            return (type, payload);
        }

        public static byte[] EncodeHello(string deviceName, string appVersion)
        {
            using var stream = new MemoryStream();
            using var writer = new BinaryWriter(stream, Encoding.UTF8, true);
            writer.Write(deviceName ?? string.Empty);
            writer.Write(appVersion ?? string.Empty);
            return stream.ToArray();
        }

        public static byte[] EncodeSessionConfig(
            string sessionId,
            int cameraEye,
            Vector2Int resolution,
            Meta.XR.PassthroughCameraAccess.CameraIntrinsics intrinsics,
            int targetSendFps,
            BowlingCodec codec,
            int quality)
        {
            using var stream = new MemoryStream();
            using var writer = new BinaryWriter(stream, Encoding.UTF8, true);
            writer.Write(sessionId ?? string.Empty);
            writer.Write(cameraEye);
            writer.Write(resolution.x);
            writer.Write(resolution.y);
            writer.Write(intrinsics.FocalLength.x);
            writer.Write(intrinsics.FocalLength.y);
            writer.Write(intrinsics.PrincipalPoint.x);
            writer.Write(intrinsics.PrincipalPoint.y);
            writer.Write(intrinsics.SensorResolution.x);
            writer.Write(intrinsics.SensorResolution.y);
            WriteVector3(writer, intrinsics.LensOffset.position);
            WriteQuaternion(writer, intrinsics.LensOffset.rotation);
            writer.Write(targetSendFps);
            writer.Write((ushort)codec);
            writer.Write(quality);
            return stream.ToArray();
        }

        public static byte[] EncodeLaneCalibration(string sessionId, BowlingLaneCalibration calibration)
        {
            using var stream = new MemoryStream();
            using var writer = new BinaryWriter(stream, Encoding.UTF8, true);
            writer.Write(sessionId ?? string.Empty);
            writer.Write(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            writer.Write(calibration.isValid);
            WriteVector3(writer, calibration.origin);
            WriteQuaternion(writer, calibration.rotation);
            writer.Write(calibration.laneWidthMeters);
            writer.Write(calibration.laneLengthMeters);
            return stream.ToArray();
        }

        public static byte[] EncodeShotMarker(string sessionId, string shotId, BowlingShotMarkerType markerType)
        {
            using var stream = new MemoryStream();
            using var writer = new BinaryWriter(stream, Encoding.UTF8, true);
            writer.Write(sessionId ?? string.Empty);
            writer.Write(shotId ?? string.Empty);
            writer.Write((ushort)markerType);
            writer.Write(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            return stream.ToArray();
        }

        public static byte[] EncodeFramePacket(
            string sessionId,
            string shotId,
            ulong frameId,
            DateTime timestampUtc,
            Pose cameraPose,
            byte[] encodedBytes)
        {
            encodedBytes ??= Array.Empty<byte>();
            using var stream = new MemoryStream(128 + encodedBytes.Length);
            using var writer = new BinaryWriter(stream, Encoding.UTF8, true);
            writer.Write(sessionId ?? string.Empty);
            writer.Write(shotId ?? string.Empty);
            writer.Write(frameId);
            writer.Write(new DateTimeOffset(timestampUtc).ToUnixTimeMilliseconds() * 1000);
            WriteVector3(writer, cameraPose.position);
            WriteQuaternion(writer, cameraPose.rotation);
            writer.Write(encodedBytes.Length);
            writer.Write(encodedBytes);
            return stream.ToArray();
        }

        public static string DecodeUtf8Payload(byte[] payload)
            => payload == null || payload.Length == 0 ? string.Empty : Encoding.UTF8.GetString(payload);

        private static byte[] ReadExact(Stream stream, int count)
        {
            var buffer = new byte[count];
            var offset = 0;
            while (offset < count)
            {
                var read = stream.Read(buffer, offset, count - offset);
                if (read <= 0)
                {
                    return null;
                }

                offset += read;
            }

            return buffer;
        }

        private static async Task<byte[]> ReadExactAsync(Stream stream, int count, CancellationToken cancellationToken)
        {
            var buffer = new byte[count];
            var offset = 0;
            while (offset < count)
            {
                var read = await stream.ReadAsync(buffer, offset, count - offset, cancellationToken);
                if (read <= 0)
                {
                    return null;
                }

                offset += read;
            }

            return buffer;
        }

        private static void WriteUInt16(byte[] buffer, int offset, ushort value)
        {
            buffer[offset + 0] = (byte)(value & 0xFF);
            buffer[offset + 1] = (byte)((value >> 8) & 0xFF);
        }

        private static void WriteUInt32(byte[] buffer, int offset, uint value)
        {
            buffer[offset + 0] = (byte)(value & 0xFF);
            buffer[offset + 1] = (byte)((value >> 8) & 0xFF);
            buffer[offset + 2] = (byte)((value >> 16) & 0xFF);
            buffer[offset + 3] = (byte)((value >> 24) & 0xFF);
        }

        private static ushort ReadUInt16(byte[] buffer, int offset)
            => (ushort)(buffer[offset + 0] | (buffer[offset + 1] << 8));

        private static uint ReadUInt32(byte[] buffer, int offset)
            => (uint)(
                buffer[offset + 0]
                | (buffer[offset + 1] << 8)
                | (buffer[offset + 2] << 16)
                | (buffer[offset + 3] << 24));

        private static void WriteVector3(BinaryWriter writer, Vector3 value)
        {
            writer.Write(value.x);
            writer.Write(value.y);
            writer.Write(value.z);
        }

        private static void WriteQuaternion(BinaryWriter writer, Quaternion value)
        {
            writer.Write(value.x);
            writer.Write(value.y);
            writer.Write(value.z);
            writer.Write(value.w);
        }
    }
}
