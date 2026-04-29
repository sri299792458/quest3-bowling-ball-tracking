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
        private string _activeSessionId;
        private string _activeShotId;
        private volatile string _threadStatus;

        public event Action<StandaloneShotResult> ShotResultReceived;

        public bool EnabledForAutoRun => enabledForAutoRun;
        public bool IsRunning => _readerThread != null && _readerThread.IsAlive;
        public StandaloneShotResult LastShotResult { get; private set; }
        public string LastStatus { get; private set; }

        public void SetEndpoint(string targetHost, int targetPort)
        {
            host = targetHost ?? string.Empty;
            port = targetPort;
        }

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
            _threadStatus = null;
            lock (_queueLock)
            {
                _pendingLines.Clear();
            }
            _seenMessageIds.Clear();
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
            LastStatus = envelope.shot_result.success ? "shot_result_received" : "shot_result_failed";
            var pointCount = envelope.shot_result.trajectory != null ? envelope.shot_result.trajectory.Length : 0;
            DebugLog($"{LastStatus} windowId={envelope.shot_result.windowId} trajectoryPoints={pointCount}");
            ShotResultReceived?.Invoke(envelope.shot_result);
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
