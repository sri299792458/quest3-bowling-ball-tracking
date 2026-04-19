using System;
using System.IO;
using System.Text;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneLocalClipArtifactWriter : IDisposable
    {
        public const string ManifestFileName = "artifact_manifest.json";
        public const string VideoFileName = "video.mp4";
        public const string SessionMetadataFileName = "session_metadata.json";
        public const string LaneLockMetadataFileName = "lane_lock_metadata.json";
        public const string FrameMetadataFileName = "frame_metadata.jsonl";
        public const string ShotMetadataFileName = "shot_metadata.json";
        public const string ProofDiagnosticsFileName = "proof_diagnostics.json";

        private readonly string _videoFileName;
        private readonly StreamWriter _frameMetadataWriter;
        private bool _disposed;

        public string ClipDirectoryPath { get; }
        public string VideoPath => Path.Combine(ClipDirectoryPath, _videoFileName);

        public StandaloneLocalClipArtifactWriter(string outputRootPath, string sessionId, string shotId, string videoFileName = VideoFileName)
        {
            if (string.IsNullOrWhiteSpace(outputRootPath))
            {
                throw new ArgumentException("Output root path is required.", nameof(outputRootPath));
            }

            _videoFileName = string.IsNullOrWhiteSpace(videoFileName) ? VideoFileName : videoFileName;
            ClipDirectoryPath = Path.Combine(outputRootPath, BuildClipDirectoryName(sessionId, shotId));
            Directory.CreateDirectory(ClipDirectoryPath);

            var frameMetadataPath = Path.Combine(ClipDirectoryPath, FrameMetadataFileName);
            _frameMetadataWriter = new StreamWriter(frameMetadataPath, append: false, new UTF8Encoding(false));
        }

        public void EnsureVideoPlaceholder()
        {
            if (!File.Exists(VideoPath))
            {
                using var stream = File.Create(VideoPath);
            }
        }

        public void WriteSessionMetadata(StandaloneSessionMetadata metadata)
        {
            WriteJsonFile(SessionMetadataFileName, metadata);
        }

        public void WriteLaneLockMetadata(StandaloneLaneLockMetadata metadata)
        {
            WriteJsonFile(LaneLockMetadataFileName, metadata);
        }

        public void WriteShotMetadata(StandaloneShotMetadata metadata)
        {
            WriteJsonFile(ShotMetadataFileName, metadata);
        }

        public void AppendFrameMetadata(StandaloneFrameMetadata metadata)
        {
            ThrowIfDisposed();
            if (metadata == null)
            {
                throw new ArgumentNullException(nameof(metadata));
            }

            _frameMetadataWriter.WriteLine(JsonUtility.ToJson(metadata));
            _frameMetadataWriter.Flush();
        }

        public void WriteManifest(string sessionId, string shotId)
        {
            var manifest = new StandaloneLocalClipManifest
            {
                sessionId = sessionId ?? string.Empty,
                shotId = shotId ?? string.Empty,
                mediaPath = _videoFileName,
                sessionMetadataPath = SessionMetadataFileName,
                laneLockMetadataPath = LaneLockMetadataFileName,
                frameMetadataPath = FrameMetadataFileName,
                shotMetadataPath = ShotMetadataFileName,
            };

            WriteJsonFile(ManifestFileName, manifest);
        }

        public void WriteProofDiagnostics(StandaloneProofDiagnostics diagnostics)
        {
            WriteJsonFile(ProofDiagnosticsFileName, diagnostics);
        }

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _frameMetadataWriter.Dispose();
            _disposed = true;
        }

        private void WriteJsonFile(string fileName, object value)
        {
            ThrowIfDisposed();
            var path = Path.Combine(ClipDirectoryPath, fileName);
            var json = value == null ? "{}" : JsonUtility.ToJson(value, true);
            File.WriteAllText(path, json, new UTF8Encoding(false));
        }

        private void ThrowIfDisposed()
        {
            if (_disposed)
            {
                throw new ObjectDisposedException(nameof(StandaloneLocalClipArtifactWriter));
            }
        }

        private static string BuildClipDirectoryName(string sessionId, string shotId)
        {
            return $"clip_{SanitizeFilePart(sessionId)}_{SanitizeFilePart(shotId)}";
        }

        private static string SanitizeFilePart(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return "unknown";
            }

            var invalid = Path.GetInvalidFileNameChars();
            var chars = value.ToCharArray();
            for (var index = 0; index < chars.Length; index++)
            {
                if (Array.IndexOf(invalid, chars[index]) >= 0)
                {
                    chars[index] = '_';
                }
            }

            return new string(chars).Trim();
        }
    }
}
