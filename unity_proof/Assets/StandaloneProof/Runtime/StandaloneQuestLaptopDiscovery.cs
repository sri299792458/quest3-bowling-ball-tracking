using System;
using System.Collections;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    [Serializable]
    public struct StandaloneQuestLaptopEndpoint
    {
        public string Host;
        public int MediaPort;
        public int MetadataPort;
        public int ResultPort;
        public int HealthPort;

        public bool IsValid => !string.IsNullOrWhiteSpace(Host) && MediaPort > 0 && MetadataPort > 0 && ResultPort > 0;

        public override string ToString()
        {
            return $"{Host} media={MediaPort} metadata={MetadataPort} result={ResultPort} health={HealthPort}";
        }
    }

    public sealed class StandaloneQuestLaptopDiscovery : MonoBehaviour
    {
        private const string DiscoverySchemaVersion = "quest_bowling_laptop_discovery_v1";
        private const string RequestKind = "quest_bowling_laptop_discovery_request";
        private const string ResponseKind = "quest_bowling_laptop_discovery_response";

        [Serializable]
        private sealed class DiscoveryRequestEnvelope
        {
            public string schemaVersion = DiscoverySchemaVersion;
            public string kind = RequestKind;
            public string client = "quest";
            public long created_unix_ms;
        }

        [Serializable]
        private sealed class DiscoveryResponseEnvelope
        {
            public string schemaVersion;
            public string kind;
            public string host;
            public int mediaPort;
            public int metadataPort;
            public int resultPort;
            public int healthPort;
        }

        [Header("Laptop Discovery")]
        [SerializeField] private bool enabledForAutoRun = true;
        [SerializeField] private int discoveryPort = 8765;
        [SerializeField] private float attemptTimeoutSeconds = 0.5f;
        [SerializeField] private int maxAttempts = 8;
        [SerializeField] private bool verboseLogging = true;

        public bool EnabledForAutoRun => enabledForAutoRun;
        public StandaloneQuestLaptopEndpoint LastEndpoint { get; private set; }
        public string LastStatus { get; private set; }

        public IEnumerator Discover(Action<bool, StandaloneQuestLaptopEndpoint, string> completed)
        {
            if (!enabledForAutoRun)
            {
                LastStatus = "laptop_discovery_disabled";
                completed?.Invoke(false, default, LastStatus);
                yield break;
            }

            var request = new DiscoveryRequestEnvelope
            {
                created_unix_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };
            var requestJson = JsonUtility.ToJson(request);
            var timeoutMs = Mathf.Max(100, Mathf.RoundToInt(attemptTimeoutSeconds * 1000.0f));
            var attempts = Mathf.Max(1, maxAttempts);
            var port = Mathf.Max(1, discoveryPort);

            var done = 0;
            string responseJson = null;
            string remoteHost = null;
            string threadError = null;

            LastStatus = "laptop_discovery_starting";
            DebugLog($"Discovering laptop on udp broadcast port {port}...");

            var discoveryThread = new Thread(() =>
            {
                try
                {
                    responseJson = RunDiscoveryRequest(requestJson, port, timeoutMs, attempts, out remoteHost);
                    if (string.IsNullOrWhiteSpace(responseJson))
                    {
                        threadError = "laptop_discovery_timeout";
                    }
                }
                catch (Exception ex)
                {
                    threadError = ex.GetType().Name + ": " + ex.Message;
                }
                finally
                {
                    Interlocked.Exchange(ref done, 1);
                }
            })
            {
                IsBackground = true,
                Name = "StandaloneQuestLaptopDiscovery",
            };
            discoveryThread.Start();

            while (Interlocked.CompareExchange(ref done, 0, 0) == 0)
            {
                yield return null;
            }

            if (string.IsNullOrWhiteSpace(responseJson))
            {
                LastStatus = string.IsNullOrWhiteSpace(threadError) ? "laptop_discovery_timeout" : threadError;
                DebugLog(LastStatus);
                completed?.Invoke(false, default, LastStatus);
                yield break;
            }

            DiscoveryResponseEnvelope response;
            try
            {
                response = JsonUtility.FromJson<DiscoveryResponseEnvelope>(responseJson);
            }
            catch (Exception ex)
            {
                LastStatus = ex.GetType().Name + ": invalid_laptop_discovery_response";
                DebugLog(LastStatus);
                completed?.Invoke(false, default, LastStatus);
                yield break;
            }

            if (response == null || response.schemaVersion != DiscoverySchemaVersion || response.kind != ResponseKind)
            {
                LastStatus = "unsupported_laptop_discovery_response";
                DebugLog(LastStatus);
                completed?.Invoke(false, default, LastStatus);
                yield break;
            }

            var endpoint = new StandaloneQuestLaptopEndpoint
            {
                Host = string.IsNullOrWhiteSpace(response.host) ? remoteHost : response.host.Trim(),
                MediaPort = response.mediaPort,
                MetadataPort = response.metadataPort,
                ResultPort = response.resultPort,
                HealthPort = response.healthPort,
            };

            if (!endpoint.IsValid)
            {
                LastStatus = "invalid_laptop_discovery_endpoint";
                DebugLog(LastStatus);
                completed?.Invoke(false, default, LastStatus);
                yield break;
            }

            LastEndpoint = endpoint;
            LastStatus = "laptop_discovered " + endpoint;
            DebugLog(LastStatus);
            completed?.Invoke(true, endpoint, LastStatus);
        }

        private static string RunDiscoveryRequest(
            string requestJson,
            int port,
            int timeoutMs,
            int attempts,
            out string remoteHost)
        {
            remoteHost = null;
            var requestBytes = Encoding.UTF8.GetBytes(requestJson);
            var broadcastEndpoint = new IPEndPoint(IPAddress.Broadcast, port);

            using (var client = new UdpClient())
            {
                client.EnableBroadcast = true;
                client.Client.ReceiveTimeout = timeoutMs;

                for (var attempt = 0; attempt < attempts; attempt++)
                {
                    client.Send(requestBytes, requestBytes.Length, broadcastEndpoint);

                    try
                    {
                        var remoteEndpoint = new IPEndPoint(IPAddress.Any, 0);
                        var responseBytes = client.Receive(ref remoteEndpoint);
                        var responseText = Encoding.UTF8.GetString(responseBytes);
                        if (responseText.Contains(ResponseKind))
                        {
                            remoteHost = remoteEndpoint.Address.ToString();
                            return responseText;
                        }
                    }
                    catch (SocketException ex) when (ex.SocketErrorCode == SocketError.TimedOut || ex.SocketErrorCode == SocketError.WouldBlock)
                    {
                    }
                }
            }

            return null;
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestLaptopDiscovery] {message}");
        }
    }
}
