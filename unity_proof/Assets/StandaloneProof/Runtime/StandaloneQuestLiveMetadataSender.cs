using System;
using System.IO;
using System.Net.Sockets;
using System.Text;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestLiveMetadataSender : MonoBehaviour
    {
        [Serializable]
        private sealed class SessionStartEnvelope
        {
            public string kind = "session_start";
            public string session_id;
            public string shot_id;
            public StandaloneSessionMetadata session_metadata;
            public StandaloneLaneLockMetadata lane_lock_metadata;
            public StandaloneShotMetadata shot_metadata;
        }

        [Serializable]
        private sealed class FrameMetadataEnvelope
        {
            public string kind = "frame_metadata";
            public string session_id;
            public string shot_id;
            public StandaloneFrameMetadata frame_metadata;
        }

        [Serializable]
        private sealed class LaneLockRequestEnvelope
        {
            public string kind = "lane_lock_request";
            public string session_id;
            public string shot_id;
            public StandaloneLaneLockRequest lane_lock_request;
        }

        [Serializable]
        private sealed class ShotBoundaryEnvelope
        {
            public string kind = "shot_boundary";
            public string session_id;
            public string shot_id;
            public string boundary_type;
            public long camera_timestamp_us;
            public long pts_us;
            public ulong frame_seq;
            public string reason;
        }

        [Serializable]
        private sealed class SessionEndEnvelope
        {
            public string kind = "session_end";
            public string session_id;
            public string shot_id;
            public string reason;
        }

        [Header("Live Metadata Target")]
        [SerializeField] private string host = "10.235.26.83";
        [SerializeField] private int port = 8767;
        [SerializeField] private bool enabledForAutoRun = true;
        [SerializeField] private bool verboseLogging;

        private TcpClient _client;
        private StreamWriter _writer;
        private string _activeSessionId;
        private string _activeShotId;

        public bool EnabledForAutoRun => enabledForAutoRun;

        public bool TryBeginSession(
            string sessionId,
            string shotId,
            StandaloneSessionMetadata sessionMetadata,
            StandaloneLaneLockMetadata laneLockMetadata,
            StandaloneShotMetadata shotMetadata,
            out string note)
        {
            note = "metadata_sender_failed";

            if (!enabledForAutoRun)
            {
                note = "metadata_sender_disabled";
                return false;
            }

            if (string.IsNullOrWhiteSpace(host) || port <= 0)
            {
                note = "metadata_target_missing";
                return false;
            }

            try
            {
                EnsureConnected();
                var payload = new SessionStartEnvelope
                {
                    session_id = sessionId ?? string.Empty,
                    shot_id = shotId ?? string.Empty,
                    session_metadata = sessionMetadata,
                    lane_lock_metadata = laneLockMetadata,
                    shot_metadata = shotMetadata,
                };
                WriteJsonLine(payload);
                _activeSessionId = payload.session_id;
                _activeShotId = payload.shot_id;
                note = $"metadata_session_started {host}:{port}";
                return true;
            }
            catch (Exception ex)
            {
                note = ex.GetType().Name + ": " + ex.Message;
                AbortSession();
                return false;
            }
        }

        public bool TrySendFrameMetadata(string sessionId, string shotId, StandaloneFrameMetadata frameMetadata, out string note)
        {
            note = "metadata_sender_failed";
            if (!enabledForAutoRun)
            {
                note = "metadata_sender_disabled";
                return false;
            }

            if (_writer == null)
            {
                note = "metadata_stream_not_connected";
                return false;
            }

            try
            {
                var payload = new FrameMetadataEnvelope
                {
                    session_id = sessionId ?? _activeSessionId ?? string.Empty,
                    shot_id = shotId ?? _activeShotId ?? string.Empty,
                    frame_metadata = frameMetadata,
                };
                WriteJsonLine(payload);
                note = "frame_metadata_sent";
                return true;
            }
            catch (Exception ex)
            {
                note = ex.GetType().Name + ": " + ex.Message;
                AbortSession();
                return false;
            }
        }

        public bool TryEndSession(string sessionId, string shotId, string reason, out string note)
        {
            note = "metadata_sender_failed";
            if (!enabledForAutoRun)
            {
                note = "metadata_sender_disabled";
                return false;
            }

            if (_writer == null)
            {
                note = "metadata_stream_not_connected";
                return false;
            }

            try
            {
                var payload = new SessionEndEnvelope
                {
                    session_id = sessionId ?? _activeSessionId ?? string.Empty,
                    shot_id = shotId ?? _activeShotId ?? string.Empty,
                    reason = string.IsNullOrWhiteSpace(reason) ? "session_complete" : reason,
                };
                WriteJsonLine(payload);
                note = "metadata_session_ended";
                return true;
            }
            catch (Exception ex)
            {
                note = ex.GetType().Name + ": " + ex.Message;
                return false;
            }
            finally
            {
                AbortSession();
            }
        }

        public bool TrySendLaneLockRequest(string sessionId, string shotId, StandaloneLaneLockRequest laneLockRequest, out string note)
        {
            note = "metadata_sender_failed";
            if (!enabledForAutoRun)
            {
                note = "metadata_sender_disabled";
                return false;
            }

            if (_writer == null)
            {
                note = "metadata_stream_not_connected";
                return false;
            }

            try
            {
                var payload = new LaneLockRequestEnvelope
                {
                    session_id = sessionId ?? _activeSessionId ?? string.Empty,
                    shot_id = shotId ?? _activeShotId ?? string.Empty,
                    lane_lock_request = laneLockRequest,
                };
                WriteJsonLine(payload);
                note = "lane_lock_request_sent";
                return true;
            }
            catch (Exception ex)
            {
                note = ex.GetType().Name + ": " + ex.Message;
                AbortSession();
                return false;
            }
        }

        public bool TrySendShotBoundary(
            string sessionId,
            string shotId,
            string boundaryType,
            ulong frameSeq,
            long cameraTimestampUs,
            long ptsUs,
            string reason,
            out string note)
        {
            note = "metadata_sender_failed";
            if (!enabledForAutoRun)
            {
                note = "metadata_sender_disabled";
                return false;
            }

            if (_writer == null)
            {
                note = "metadata_stream_not_connected";
                return false;
            }

            try
            {
                var payload = new ShotBoundaryEnvelope
                {
                    session_id = sessionId ?? _activeSessionId ?? string.Empty,
                    shot_id = shotId ?? _activeShotId ?? string.Empty,
                    boundary_type = string.IsNullOrWhiteSpace(boundaryType) ? "unknown" : boundaryType,
                    frame_seq = frameSeq,
                    camera_timestamp_us = cameraTimestampUs,
                    pts_us = ptsUs,
                    reason = string.IsNullOrWhiteSpace(reason) ? "unspecified" : reason,
                };
                WriteJsonLine(payload);
                note = "shot_boundary_sent";
                return true;
            }
            catch (Exception ex)
            {
                note = ex.GetType().Name + ": " + ex.Message;
                AbortSession();
                return false;
            }
        }

        public void AbortSession()
        {
            try
            {
                _writer?.Dispose();
            }
            catch
            {
            }

            try
            {
                _client?.Close();
            }
            catch
            {
            }

            _writer = null;
            _client = null;
            _activeSessionId = null;
            _activeShotId = null;
        }

        private void OnDestroy()
        {
            AbortSession();
        }

        private void EnsureConnected()
        {
            if (_writer != null && _client != null && _client.Connected)
            {
                return;
            }

            AbortSession();
            _client = new TcpClient();
            _client.NoDelay = true;
            _client.Connect(host, port);
            _writer = new StreamWriter(_client.GetStream(), new UTF8Encoding(false))
            {
                NewLine = "\n",
                AutoFlush = true,
            };
            DebugLog($"Connected metadata sender to {host}:{port}");
        }

        private void WriteJsonLine(object payload)
        {
            if (_writer == null)
            {
                throw new InvalidOperationException("Metadata stream is not connected.");
            }

            var json = JsonUtility.ToJson(payload);
            _writer.WriteLine(json);
            _writer.Flush();
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestLiveMetadataSender] {message}");
        }
    }
}
