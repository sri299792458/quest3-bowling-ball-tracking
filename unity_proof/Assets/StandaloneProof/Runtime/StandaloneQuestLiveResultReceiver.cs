using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestLiveResultReceiver : MonoBehaviour
    {
        private const string ResultEnvelopeSchemaVersion = "laptop_result_envelope";

        [Serializable]
        private sealed class ResultEnvelopeHeader
        {
            public string schemaVersion;
            public string kind;
            public string session_id;
            public string shot_id;
            public string message_id;
            public long created_unix_ms;
        }

        [Serializable]
        private sealed class ShotResultEnvelope
        {
            public string schemaVersion;
            public string kind;
            public string session_id;
            public string shot_id;
            public string message_id;
            public long created_unix_ms;
            public StandaloneShotResult shot_result;
        }

        [Serializable]
        private sealed class PipelineStatusEnvelope
        {
            public string schemaVersion;
            public string kind;
            public string session_id;
            public string shot_id;
            public string message_id;
            public long created_unix_ms;
            public StandalonePipelineStatus pipeline_status;
        }

        [Header("Laptop Result Channel")]
        [SerializeField] private string host = "";
        [SerializeField] private int port = 8769;
        [SerializeField] private int connectTimeoutMs = 1000;
        [SerializeField] private int reconnectDelayMs = 1000;
        [SerializeField] private bool enabledForAutoRun = true;
        [SerializeField] private bool verboseLogging = true;

        private readonly object _queueLock = new object();
        private readonly Queue<string> _pendingLines = new Queue<string>();
        private readonly HashSet<string> _seenMessageIds = new HashSet<string>();

        private TcpClient _client;
        private Thread _readerThread;
        private volatile bool _stopRequested;
        private volatile bool _isConnected;
        private string _activeSessionId;
        private string _activeShotId;
        private volatile string _threadStatus;
#if UNITY_EDITOR
        private bool _recordedExportConnected;
#endif

        public event Action<StandaloneShotResult> ShotResultReceived;
        public event Action<StandalonePipelineStatus> PipelineStatusReceived;

        public bool EnabledForAutoRun => enabledForAutoRun;
        public bool IsRunning => _readerThread != null && _readerThread.IsAlive;
        public bool IsConnected
        {
            get
            {
#if UNITY_EDITOR
                if (_recordedExportConnected)
                {
                    return true;
                }
#endif
                return enabledForAutoRun && IsRunning && _isConnected;
            }
        }
        public bool IsPipelineReady => LastPipelineStatus != null && LastPipelineStatus.ready;
        public StandaloneShotResult LastShotResult { get; private set; }
        public StandalonePipelineStatus LastPipelineStatus { get; private set; }
        public string LastStatus { get; private set; }

        public void SetEndpoint(string targetHost, int targetPort)
        {
            host = targetHost ?? string.Empty;
            port = targetPort;
        }

#if UNITY_EDITOR
        public void InjectRecordedExportConnectionState(bool connected)
        {
            _recordedExportConnected = connected;
            LastStatus = connected ? "recorded_export_result_connected" : "recorded_export_result_disconnected";
        }
#endif

        public bool TryBeginResultStream(string sessionId, string shotId, out string note)
        {
            note = "result_receiver_failed";

            if (!enabledForAutoRun)
            {
                note = "result_receiver_disabled";
                return false;
            }

            if (string.IsNullOrWhiteSpace(host) || port <= 0)
            {
                note = "result_target_missing";
                return false;
            }

            if (IsRunning)
            {
                note = "result_receiver_already_running";
                return true;
            }

            _activeSessionId = sessionId ?? string.Empty;
            _activeShotId = shotId ?? string.Empty;
            _stopRequested = false;
            _isConnected = false;
            _threadStatus = null;
            lock (_queueLock)
            {
                _pendingLines.Clear();
            }
            _seenMessageIds.Clear();
            LastShotResult = null;
            LastPipelineStatus = null;
            LastStatus = "result_receiver_starting";

            _readerThread = new Thread(ResultReaderLoop)
            {
                IsBackground = true,
                Name = "StandaloneQuestLiveResultReceiver",
            };
            _readerThread.Start();

            note = $"result_receiver_started {host}:{port}";
            return true;
        }

        public void StopResultStream()
        {
            _stopRequested = true;
            try
            {
                _client?.Close();
            }
            catch
            {
            }

            if (_readerThread != null && _readerThread.IsAlive)
            {
                _readerThread.Join(250);
            }

            _client = null;
            _readerThread = null;
            _isConnected = false;
            LastStatus = "result_receiver_stopped";
        }

        private void Update()
        {
            DrainThreadStatus();

            while (TryDequeueLine(out var line))
            {
                ProcessResultLine(line);
            }
        }

        public void InjectRecordedPipelineStatus(StandalonePipelineStatus status)
        {
            if (status == null)
            {
                LastStatus = "recorded_pipeline_status_missing";
                DebugLog(LastStatus);
                return;
            }

            LastPipelineStatus = status;
            LastStatus = status.ready ? "recorded_pipeline_status_ready" : "recorded_pipeline_status_busy";
            DebugLog($"{LastStatus} state={status.state} reason={status.reason} windowId={status.windowId}");
            PipelineStatusReceived?.Invoke(status);
        }

        public void InjectRecordedShotResult(StandaloneShotResult result)
        {
            if (result == null)
            {
                LastStatus = "recorded_shot_result_missing";
                DebugLog(LastStatus);
                return;
            }

            LastShotResult = result;
            LastPipelineStatus = new StandalonePipelineStatus
            {
                state = result.success ? "shot_result_ready" : "shot_result_failed",
                ready = true,
                reason = result.success ? "shot_result_ready" : result.failureReason,
                windowId = result.windowId,
            };
            LastStatus = result.success ? "recorded_shot_result_received" : "recorded_shot_result_failed";
            var pointCount = result.trajectory != null ? result.trajectory.Length : 0;
            DebugLog($"{LastStatus} windowId={result.windowId} trajectoryPoints={pointCount}");
            ShotResultReceived?.Invoke(result);
            PipelineStatusReceived?.Invoke(LastPipelineStatus);
        }

        private void OnDestroy()
        {
            StopResultStream();
        }

        private void ResultReaderLoop()
        {
            while (!_stopRequested)
            {
                try
                {
                    using (var client = new TcpClient())
                    {
                        _client = client;
                        client.NoDelay = true;
                        ConnectWithTimeout(client, host, port, Math.Max(1, connectTimeoutMs));
                        _isConnected = true;
                        SetThreadStatus($"result_receiver_connected {host}:{port}");

                        using (var stream = client.GetStream())
                        using (var reader = new StreamReader(stream, new UTF8Encoding(false)))
                        {
                            while (!_stopRequested)
                            {
                                var line = reader.ReadLine();
                                if (line == null)
                                {
                                    break;
                                }

                                if (line.Length == 0)
                                {
                                    continue;
                                }

                                EnqueueLine(line);
                            }
                        }
                    }

                    SetThreadStatus("result_receiver_disconnected");
                }
                catch (Exception ex)
                {
                    SetThreadStatus(ex.GetType().Name + ": " + ex.Message);
                }
                finally
                {
                    _isConnected = false;
                    _client = null;
                }

                if (!_stopRequested)
                {
                    SleepBeforeReconnect();
                }
            }
        }

        private void SleepBeforeReconnect()
        {
            var remainingMs = Math.Max(50, reconnectDelayMs);
            while (!_stopRequested && remainingMs > 0)
            {
                var sliceMs = Math.Min(remainingMs, 100);
                Thread.Sleep(sliceMs);
                remainingMs -= sliceMs;
            }
        }

        private static void ConnectWithTimeout(TcpClient client, string targetHost, int targetPort, int timeoutMs)
        {
            var asyncResult = client.BeginConnect(targetHost, targetPort, null, null);
            if (!asyncResult.AsyncWaitHandle.WaitOne(timeoutMs))
            {
                throw new TimeoutException($"Timed out connecting to {targetHost}:{targetPort} after {timeoutMs}ms.");
            }

            client.EndConnect(asyncResult);
        }

        private void ProcessResultLine(string line)
        {
            ResultEnvelopeHeader header;
            try
            {
                header = JsonUtility.FromJson<ResultEnvelopeHeader>(line);
            }
            catch (Exception ex)
            {
                LastStatus = ex.GetType().Name + ": invalid_result_json";
                DebugLog(LastStatus);
                return;
            }

            if (header == null || header.schemaVersion != ResultEnvelopeSchemaVersion)
            {
                LastStatus = "unsupported_result_schema";
                DebugLog(LastStatus);
                return;
            }

            if (!string.IsNullOrEmpty(_activeSessionId) && header.session_id != _activeSessionId)
            {
                LastStatus = "ignored_result_session_mismatch";
                DebugLog(LastStatus);
                return;
            }

            if (!string.IsNullOrEmpty(_activeShotId) && header.shot_id != _activeShotId)
            {
                LastStatus = "ignored_result_shot_mismatch";
                DebugLog(LastStatus);
                return;
            }

            if (!string.IsNullOrEmpty(header.message_id) && _seenMessageIds.Contains(header.message_id))
            {
                LastStatus = "ignored_duplicate_result";
                DebugLog(LastStatus);
                return;
            }

            var processed = false;
            if (header.kind == "shot_result")
            {
                processed = ProcessShotResult(line);
            }
            else if (header.kind == "pipeline_status")
            {
                processed = ProcessPipelineStatus(line);
            }
            else
            {
                LastStatus = "unsupported_result_kind:" + header.kind;
                DebugLog(LastStatus);
                return;
            }

            if (processed && !string.IsNullOrEmpty(header.message_id))
            {
                _seenMessageIds.Add(header.message_id);
            }
        }

        private bool ProcessShotResult(string line)
        {
            ShotResultEnvelope envelope;
            try
            {
                envelope = JsonUtility.FromJson<ShotResultEnvelope>(line);
            }
            catch (Exception ex)
            {
                LastStatus = ex.GetType().Name + ": invalid_shot_result_json";
                DebugLog(LastStatus);
                return false;
            }

            if (envelope == null || envelope.shot_result == null)
            {
                LastStatus = "shot_result_missing_payload";
                DebugLog(LastStatus);
                return false;
            }

            if (envelope.shot_result.schemaVersion != "shot_result")
            {
                LastStatus = "unsupported_shot_result_schema";
                DebugLog(LastStatus);
                return false;
            }

            LastShotResult = envelope.shot_result;
            LastPipelineStatus = new StandalonePipelineStatus
            {
                state = envelope.shot_result.success ? "shot_result_ready" : "shot_result_failed",
                ready = true,
                reason = envelope.shot_result.success ? "shot_result_ready" : envelope.shot_result.failureReason,
                windowId = envelope.shot_result.windowId,
            };
            LastStatus = envelope.shot_result.success ? "shot_result_received" : "shot_result_failed";
            var pointCount = envelope.shot_result.trajectory != null ? envelope.shot_result.trajectory.Length : 0;
            DebugLog($"{LastStatus} windowId={envelope.shot_result.windowId} trajectoryPoints={pointCount}");
            ShotResultReceived?.Invoke(envelope.shot_result);
            PipelineStatusReceived?.Invoke(LastPipelineStatus);
            return true;
        }

        private bool ProcessPipelineStatus(string line)
        {
            PipelineStatusEnvelope envelope;
            try
            {
                envelope = JsonUtility.FromJson<PipelineStatusEnvelope>(line);
            }
            catch (Exception ex)
            {
                LastStatus = ex.GetType().Name + ": invalid_pipeline_status_json";
                DebugLog(LastStatus);
                return false;
            }

            if (envelope == null || envelope.pipeline_status == null)
            {
                LastStatus = "pipeline_status_missing_payload";
                DebugLog(LastStatus);
                return false;
            }

            LastPipelineStatus = envelope.pipeline_status;
            LastStatus = envelope.pipeline_status.ready ? "pipeline_status_ready" : "pipeline_status_busy";
            DebugLog(
                $"{LastStatus} state={envelope.pipeline_status.state} " +
                $"reason={envelope.pipeline_status.reason} windowId={envelope.pipeline_status.windowId}");
            PipelineStatusReceived?.Invoke(envelope.pipeline_status);
            return true;
        }

        private void EnqueueLine(string line)
        {
            lock (_queueLock)
            {
                _pendingLines.Enqueue(line);
            }
        }

        private bool TryDequeueLine(out string line)
        {
            lock (_queueLock)
            {
                if (_pendingLines.Count == 0)
                {
                    line = null;
                    return false;
                }

                line = _pendingLines.Dequeue();
                return true;
            }
        }

        private void SetThreadStatus(string status)
        {
            _threadStatus = status;
        }

        private void DrainThreadStatus()
        {
            var status = _threadStatus;
            if (string.IsNullOrEmpty(status))
            {
                return;
            }

            _threadStatus = null;
            LastStatus = status;
            DebugLog(status);
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestLiveResultReceiver] {message}");
        }
    }
}
