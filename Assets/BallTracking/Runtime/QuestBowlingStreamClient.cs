using System;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using BallTracking.Runtime.Transport;
using Meta.XR;
using Unity.Collections;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;

namespace BallTracking.Runtime
{
    public sealed class QuestBowlingStreamClient : MonoBehaviour
    {
        [Serializable]
        public sealed class StringEvent : UnityEvent<string> { }

        [Header("Camera")]
        [SerializeField] private PassthroughCameraAccess cameraAccess;
        [SerializeField] private PassthroughCameraAccess.CameraPositionType cameraPosition = PassthroughCameraAccess.CameraPositionType.Left;

        [Header("Connection")]
        [SerializeField] private string serverHost = "192.168.1.2";
        [SerializeField] private int serverPort = 5799;
        [SerializeField] private float reconnectDelaySeconds = 2f;

        [Header("Streaming")]
        [SerializeField] private int targetSendFps = 15;
        [SerializeField] [Range(30, 95)] private int jpegQuality = 65;
        [SerializeField] private bool autoStreamWhenConnected = true;
        [SerializeField] private bool verboseLogging;

        [Header("Events")]
        [SerializeField] private StringEvent onTrackerStatus = new();
        [SerializeField] private StringEvent onShotResultJson = new();

        public event Action<string> TrackerStatusReceived;
        public event Action<string> ShotResultReceived;

        private readonly object _latestFrameLock = new();
        private readonly SemaphoreSlim _sendSignal = new(0);
        private PendingFrame _latestFrame;

        private TcpClient _tcpClient;
        private NetworkStream _networkStream;
        private CancellationTokenSource _lifetimeCts;
        private Task _connectionTask;
        private Task _sendTask;
        private Task _receiveTask;

        private bool _sessionConfigSent;
        private bool _readbackInFlight;
        private double _lastCaptureTime;
        private ulong _nextFrameId = 1;
        private string _sessionId;
        private string _shotId = "default-shot";
        private BowlingLaneCalibration _laneCalibration;

        public bool IsConnected => _tcpClient != null && _tcpClient.Connected && _networkStream != null;
        public string ServerHost => serverHost;
        public int ServerPort => serverPort;

        public void ConfigureForRuntime(
            PassthroughCameraAccess passthroughCameraAccess,
            string host = null,
            int? port = null)
        {
            cameraAccess = passthroughCameraAccess;
            if (cameraAccess != null)
            {
                cameraAccess.CameraPosition = cameraPosition;
            }

            if (!string.IsNullOrWhiteSpace(host))
            {
                serverHost = host;
            }

            if (port.HasValue)
            {
                serverPort = port.Value;
            }
        }

        private void Awake()
        {
            _sessionId = Guid.NewGuid().ToString("N");
            if (cameraAccess != null)
            {
                cameraAccess.CameraPosition = cameraPosition;
            }
        }

        private void OnEnable()
        {
            _lifetimeCts = new CancellationTokenSource();
            _connectionTask = RunConnectionLoopAsync(_lifetimeCts.Token);
        }

        private void OnDisable()
        {
            _lifetimeCts?.Cancel();
            DisposeLatestFrame();
            CloseSocket();
        }

        private void Update()
        {
            if (!autoStreamWhenConnected || cameraAccess == null || !IsConnected)
            {
                return;
            }

            if (!cameraAccess.IsPlaying)
            {
                return;
            }

            if (!_sessionConfigSent)
            {
                _ = SendSessionConfigAsync();
            }

            if (!_laneCalibration.isValid)
            {
                return;
            }

            if (!cameraAccess.IsUpdatedThisFrame || _readbackInFlight)
            {
                return;
            }

            var minInterval = 1.0 / Mathf.Max(1, targetSendFps);
            if (Time.unscaledTimeAsDouble - _lastCaptureTime < minInterval)
            {
                return;
            }

            QueueLatestFrameReadback();
            _lastCaptureTime = Time.unscaledTimeAsDouble;
        }

        public void SetLaneCalibration(Pose lanePose, float laneWidthMeters, float laneLengthMeters)
        {
            _laneCalibration = new BowlingLaneCalibration
            {
                isValid = true,
                origin = lanePose.position,
                rotation = lanePose.rotation,
                laneWidthMeters = laneWidthMeters,
                laneLengthMeters = laneLengthMeters,
            };

            if (IsConnected)
            {
                _ = SendLaneCalibrationAsync();
            }
        }

        public void SetShotId(string shotId)
        {
            _shotId = string.IsNullOrWhiteSpace(shotId) ? "default-shot" : shotId;
        }

        public void SendShotMarker(BowlingShotMarkerType markerType)
        {
            if (!IsConnected)
            {
                return;
            }

            var payload = BowlingProtocol.EncodeShotMarker(_sessionId, _shotId, markerType);
            _ = BowlingProtocol.WritePacketAsync(_networkStream, BowlingPacketType.ShotMarker, payload, _lifetimeCts.Token);
        }

        private async Task RunConnectionLoopAsync(CancellationToken cancellationToken)
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                try
                {
                    _tcpClient = new TcpClient();
                    await _tcpClient.ConnectAsync(serverHost, serverPort);
                    _tcpClient.NoDelay = true;
                    _networkStream = _tcpClient.GetStream();
                    _sessionConfigSent = false;

                    if (verboseLogging)
                    {
                        Debug.Log($"[QuestBowlingStreamClient] Connected to {serverHost}:{serverPort}");
                    }

                    await BowlingProtocol.WritePacketAsync(
                        _networkStream,
                        BowlingPacketType.Hello,
                        BowlingProtocol.EncodeHello(SystemInfo.deviceName, Application.version),
                        cancellationToken);

                    _sendTask = RunSendLoopAsync(cancellationToken);
                    _receiveTask = RunReceiveLoopAsync(cancellationToken);

                    await Task.WhenAny(_sendTask, _receiveTask);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[QuestBowlingStreamClient] Connection loop error: {ex.Message}");
                }
                finally
                {
                    CloseSocket();
                }

                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(reconnectDelaySeconds), cancellationToken);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
            }
        }

        private async Task RunSendLoopAsync(CancellationToken cancellationToken)
        {
            while (!cancellationToken.IsCancellationRequested && IsConnected)
            {
                await _sendSignal.WaitAsync(cancellationToken);

                PendingFrame frameToSend = null;
                lock (_latestFrameLock)
                {
                    frameToSend = _latestFrame;
                    _latestFrame = null;
                }

                if (frameToSend == null)
                {
                    continue;
                }

                try
                {
                    var payload = BowlingProtocol.EncodeFramePacket(
                        _sessionId,
                        _shotId,
                        frameToSend.frameId,
                        frameToSend.timestampUtc,
                        frameToSend.cameraPose,
                        frameToSend.encodedJpeg);

                    await BowlingProtocol.WritePacketAsync(_networkStream, BowlingPacketType.FramePacket, payload, cancellationToken);
                }
                finally
                {
                    frameToSend.Dispose();
                }
            }
        }

        private async Task RunReceiveLoopAsync(CancellationToken cancellationToken)
        {
            while (!cancellationToken.IsCancellationRequested && IsConnected)
            {
                var packet = await BowlingProtocol.ReadPacketAsync(_networkStream, cancellationToken);
                if (!packet.HasValue)
                {
                    break;
                }

                switch (packet.Value.type)
                {
                    case BowlingPacketType.TrackerStatus:
                        var trackerStatusJson = BowlingProtocol.DecodeUtf8Payload(packet.Value.payload);
                        if (verboseLogging)
                        {
                            Debug.Log($"[QuestBowlingStreamClient] TrackerStatus: {trackerStatusJson}");
                        }
                        onTrackerStatus.Invoke(trackerStatusJson);
                        TrackerStatusReceived?.Invoke(trackerStatusJson);
                        break;
                    case BowlingPacketType.ShotResult:
                        var shotResultJson = BowlingProtocol.DecodeUtf8Payload(packet.Value.payload);
                        if (verboseLogging)
                        {
                            Debug.Log($"[QuestBowlingStreamClient] ShotResult: {shotResultJson}");
                        }
                        onShotResultJson.Invoke(shotResultJson);
                        ShotResultReceived?.Invoke(shotResultJson);
                        break;
                    case BowlingPacketType.Ping:
                        await BowlingProtocol.WritePacketAsync(_networkStream, BowlingPacketType.Pong, Array.Empty<byte>(), cancellationToken);
                        break;
                }
            }
        }

        private async Task SendSessionConfigAsync()
        {
            if (_sessionConfigSent || !IsConnected || cameraAccess == null || !cameraAccess.IsPlaying)
            {
                return;
            }

            var payload = BowlingProtocol.EncodeSessionConfig(
                _sessionId,
                cameraAccess.CameraPosition == PassthroughCameraAccess.CameraPositionType.Left ? 0 : 1,
                cameraAccess.CurrentResolution,
                cameraAccess.Intrinsics,
                targetSendFps,
                BowlingCodec.Jpeg,
                jpegQuality);

            await BowlingProtocol.WritePacketAsync(_networkStream, BowlingPacketType.SessionConfig, payload, _lifetimeCts.Token);
            _sessionConfigSent = true;

            if (_laneCalibration.isValid)
            {
                await SendLaneCalibrationAsync();
            }
        }

        private Task SendLaneCalibrationAsync()
        {
            if (!IsConnected || !_laneCalibration.isValid)
            {
                return Task.CompletedTask;
            }

            var payload = BowlingProtocol.EncodeLaneCalibration(_sessionId, _laneCalibration);
            return BowlingProtocol.WritePacketAsync(_networkStream, BowlingPacketType.LaneCalibration, payload, _lifetimeCts.Token);
        }

        private void QueueLatestFrameReadback()
        {
            var texture = cameraAccess.GetTexture();
            if (texture == null)
            {
                return;
            }

            var cameraPose = cameraAccess.GetCameraPose();
            var timestampUtc = cameraAccess.Timestamp;
            var frameId = _nextFrameId++;
            _readbackInFlight = true;

            AsyncGPUReadback.Request(texture, 0, TextureFormat.RGBA32, request =>
            {
                _readbackInFlight = false;
                if (!this || !enabled)
                {
                    return;
                }

                if (request.hasError)
                {
                    Debug.LogWarning("[QuestBowlingStreamClient] GPU readback failed.");
                    return;
                }

                NativeArray<byte> encodedNative = default;
                try
                {
                    var pixels = request.GetData<Color32>();
                    encodedNative = ImageConversion.EncodeNativeArrayToJPG(
                        pixels,
                        GraphicsFormat.R8G8B8A8_UNorm,
                        (uint)cameraAccess.CurrentResolution.x,
                        (uint)cameraAccess.CurrentResolution.y,
                        0,
                        jpegQuality);

                    var bytes = encodedNative.ToArray();
                    EnqueueLatestFrame(new PendingFrame(frameId, timestampUtc, cameraPose, bytes));
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[QuestBowlingStreamClient] JPEG encode failed: {ex.Message}");
                }
                finally
                {
                    if (encodedNative.IsCreated)
                    {
                        encodedNative.Dispose();
                    }
                }
            });
        }

        private void EnqueueLatestFrame(PendingFrame frame)
        {
            var shouldSignal = false;
            lock (_latestFrameLock)
            {
                shouldSignal = _latestFrame == null;
                _latestFrame?.Dispose();
                _latestFrame = frame;
            }

            if (shouldSignal)
            {
                _sendSignal.Release();
            }
        }

        private void DisposeLatestFrame()
        {
            lock (_latestFrameLock)
            {
                _latestFrame?.Dispose();
                _latestFrame = null;
            }
        }

        private void CloseSocket()
        {
            try { _networkStream?.Dispose(); } catch { }
            try { _tcpClient?.Dispose(); } catch { }
            _networkStream = null;
            _tcpClient = null;
        }

        private sealed class PendingFrame : IDisposable
        {
            public readonly ulong frameId;
            public readonly DateTime timestampUtc;
            public readonly Pose cameraPose;
            public readonly byte[] encodedJpeg;

            public PendingFrame(ulong frameId, DateTime timestampUtc, Pose cameraPose, byte[] encodedJpeg)
            {
                this.frameId = frameId;
                this.timestampUtc = timestampUtc;
                this.cameraPose = cameraPose;
                this.encodedJpeg = encodedJpeg;
            }

            public void Dispose()
            {
            }
        }
    }
}
