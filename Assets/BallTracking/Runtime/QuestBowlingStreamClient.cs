using System;
using System.Collections;
using System.Collections.Concurrent;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using BallTracking.Runtime.Transport;
using Meta.XR;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.Rendering;
using UnityEngine.Serialization;

namespace BallTracking.Runtime
{
    public sealed class QuestBowlingStreamClient : MonoBehaviour
    {
        private const int UdpFrameHeaderSize = 26;

        public enum StreamSourceMode
        {
            PassthroughCamera = 0,
            SyntheticPattern = 1,
        }

        public enum ConnectionMode
        {
            RemoteLaptop = 0,
            LocalLoopback = 1,
        }

        [Serializable]
        public sealed class StringEvent : UnityEvent<string> { }

        [Serializable]
        private sealed class IncomingEnvelope
        {
            public string kind;
        }

        [Serializable]
        private sealed class HelloMessage
        {
            public string kind;
            public string session_id;
            public string device_name;
            public string app_version;
        }

        [Serializable]
        private sealed class SessionConfigMessage
        {
            public string kind;
            public string session_id;
            public int camera_eye;
            public int width;
            public int height;
            public float fx;
            public float fy;
            public float cx;
            public float cy;
            public int sensor_width;
            public int sensor_height;
            public float lens_position_x;
            public float lens_position_y;
            public float lens_position_z;
            public float lens_rotation_x;
            public float lens_rotation_y;
            public float lens_rotation_z;
            public float lens_rotation_w;
            public int target_send_fps;
            public string transport;
            public string video_codec;
            public int target_bitrate_kbps;
        }

        [Serializable]
        private sealed class LaneCalibrationMessage
        {
            public string kind;
            public string session_id;
            public long timestamp_ms;
            public bool is_valid;
            public float origin_x;
            public float origin_y;
            public float origin_z;
            public float rotation_x;
            public float rotation_y;
            public float rotation_z;
            public float rotation_w;
            public float lane_width_m;
            public float lane_length_m;
        }

        [Serializable]
        private sealed class ShotMarkerMessage
        {
            public string kind;
            public string session_id;
            public string shot_id;
            public int marker_type;
            public long timestamp_ms;
        }

        [Serializable]
        private sealed class PingMessage
        {
            public string kind;
            public long timestamp_ms;
        }

        [Serializable]
        private sealed class LocalTrackerStatusMessage
        {
            public string kind;
            public string stage;
            public string shot_id;
            public string message;
        }

        [Serializable]
        private sealed class ShotResultSummaryMessage
        {
            public string kind;
            public bool success;
            public string shot_id;
            public string failure_reason;
            public int tracked_frames;
            public int first_frame;
            public int last_frame;
        }

        private readonly ConcurrentQueue<QueuedInboundPacket> _inboundPackets = new();
        private readonly ConcurrentQueue<QueuedStatus> _queuedStatuses = new();
        private readonly object _controlSendGate = new();

        [Header("Camera")]
        [SerializeField] private PassthroughCameraAccess cameraAccess;
        [SerializeField] private PassthroughCameraAccess.CameraPositionType cameraPosition = PassthroughCameraAccess.CameraPositionType.Left;

        [Header("Connection")]
        [SerializeField] private ConnectionMode connectionMode = ConnectionMode.RemoteLaptop;
        [SerializeField] private string serverHost = "192.168.1.2";
        [SerializeField] private int serverPort = 5799;
        [SerializeField] private float reconnectDelaySeconds = 2f;
        [FormerlySerializedAs("signalingTimeoutSeconds")]
        [SerializeField] private float connectTimeoutSeconds = 4f;

        [Header("Streaming")]
        [SerializeField] private StreamSourceMode streamSource = StreamSourceMode.PassthroughCamera;
        [SerializeField] private Vector2Int syntheticResolution = new(1280, 960);
        [SerializeField] private Vector2Int passthroughSendResolution = new(960, 720);
        [SerializeField] private int targetSendFps = 30;
        [SerializeField] private int targetBitrateKbps = 3500;
        [SerializeField] private int jpegQuality = 65;
        [SerializeField] private int maxDatagramPayloadBytes = 1400;
        [SerializeField] private bool useAsyncGpuReadback;
        [SerializeField] private bool cameraSourceProbeOnly;
        [SerializeField] private bool autoStreamWhenConnected = true;
        [SerializeField] private bool verboseLogging;

        [Header("Events")]
        [SerializeField] private StringEvent onTrackerStatus = new();
        [SerializeField] private StringEvent onShotResultJson = new();

        public event Action<string> TrackerStatusReceived;
        public event Action<string> ShotResultReceived;

        private Coroutine _connectionLoopCoroutine;
        private TcpClient _controlClient;
        private NetworkStream _controlStream;
        private UdpClient _frameClient;
        private Task _controlReadTask;
        private CancellationTokenSource _connectionCts;
        private RenderTexture _streamTexture;
        private Texture2D _readbackTexture;
        private Camera _syntheticSenderCamera;
        private bool _connecting;
        private bool _controlConnected;
        private bool _helloSent;
        private bool _sessionConfigSent;
        private bool _laneCalibrationSent;
        private bool _permissionsRequested;
        private bool _videoEncoderProbeReported;
        private double _lastFrameSendTime;
        private int _localStreamFrameCount;
        private ulong _nextFrameId;
        private string _sessionId;
        private string _shotId = "default-shot";
        private string _latestStatusLine = "client_not_started";
        private BowlingLaneCalibration _laneCalibration;
        private string _statusLogPath;
        private int _consecutiveFrameSendFailures;
        private string _lastFrameSendFailureNote;
        private Transform _headAnchorTransform;
        private int _captureAttemptCount;
        private int _captureSentCount;
        private int _captureBlockedPassthroughCount;
        private int _captureBlockedOtherCount;
        private double _captureStatsWindowStartTime;
        private double _captureStatsLastSentTime;
        private double _captureStatsSentDeltaSumMs;
        private double _captureStatsMinSentDeltaMs = double.PositiveInfinity;
        private double _captureStatsMaxSentDeltaMs;
        private int _captureCameraUpdateCount;
        private double _captureCameraLastUpdateTime;
        private double _captureCameraUpdateDeltaSumMs;
        private double _captureCameraUpdateMinDeltaMs = double.PositiveInfinity;
        private double _captureCameraUpdateMaxDeltaMs;
        private double _captureRenderSumMs;
        private double _captureReadbackSumMs;
        private double _captureApplySumMs;
        private double _captureJpegSumMs;
        private double _captureEncodeSumMs;
        private double _captureUdpSumMs;
        private double _captureTotalSumMs;
        private double _captureRenderMaxMs;
        private double _captureReadbackMaxMs;
        private double _captureApplyMaxMs;
        private double _captureJpegMaxMs;
        private double _captureEncodeMaxMs;
        private double _captureUdpMaxMs;
        private double _captureTotalMaxMs;
        private AsyncGPUReadbackRequest _pendingReadbackRequest;
        private bool _hasPendingReadbackRequest;
        private ulong _pendingReadbackFrameId;
        private DateTime _pendingReadbackTimestampUtc;
        private Pose _pendingReadbackCameraPose;
        private Pose _pendingReadbackHeadPose;
        private string _pendingReadbackSourceNote;
        private string _pendingReadbackShotId;
        private double _pendingReadbackRenderMs;
        private double _pendingReadbackIssuedAtMs;
        private int _pendingReadbackWidth;
        private int _pendingReadbackHeight;

        public bool IsConnected => _controlConnected && _controlStream != null;
        public string ServerHost => serverHost;
        public int ServerPort => serverPort;
        public string LatestStatusLine => _latestStatusLine;

        public void ConfigureForRuntime(
            PassthroughCameraAccess passthroughCameraAccess,
            string host = null,
            int? port = null)
        {
            cameraAccess = passthroughCameraAccess;
            ConfigurePassthroughCameraAccess();

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
            _statusLogPath = Path.Combine(Application.persistentDataPath, "quest_bowling_status.log");
            _headAnchorTransform = ResolveHeadAnchorTransform();
            ConfigurePassthroughCameraAccess();

            EmitLocalStatus("client_awake", _sessionId);
        }

        private void OnEnable()
        {
            EmitLocalStatus("client_on_enable");
            if (UsesPassthroughCamera())
            {
                RequestCameraPermissionsIfNeeded();
            }

            _connectionLoopCoroutine = StartCoroutine(ConnectionLoop());
        }

        private void OnDisable()
        {
            EmitLocalStatus("client_on_disable");
            if (_connectionLoopCoroutine != null)
            {
                StopCoroutine(_connectionLoopCoroutine);
                _connectionLoopCoroutine = null;
            }

            CleanupConnection();
            ClearPendingAsyncReadback();
            DisposeStreamTexture();
            DisposeReadbackTexture();
            DisposeSyntheticSenderCamera();
            _localStreamFrameCount = 0;
        }

        private void Update()
        {
            DrainQueuedStatuses();
            DrainInboundPackets();
            ObserveCameraUpdateIfNeeded();

            if (cameraSourceProbeOnly)
            {
                EnsureCaptureStatsWindowStarted();
                if (IsConnected)
                {
                    if (!_sessionConfigSent)
                    {
                        TrySendSessionConfig();
                    }

                    if (_laneCalibration.isValid && !_laneCalibrationSent)
                    {
                        TrySendLaneCalibration();
                    }
                }

                MaybeEmitCameraSourcePerfStatus();
                return;
            }

            if (!autoStreamWhenConnected || !IsConnected)
            {
                return;
            }

            EnsureCaptureStatsWindowStarted();
            _captureAttemptCount++;
            var minInterval = 1.0 / Mathf.Max(1, targetSendFps);
            if (Time.unscaledTimeAsDouble - _lastFrameSendTime < minInterval)
            {
                return;
            }

            if (!TrySendCurrentFrame(out var frameNote))
            {
                if (!IsDeferredCaptureState(frameNote))
                {
                    TrackCaptureBlocked(frameNote);
                    ReportFrameSendBlocked(frameNote);
                }
                MaybeEmitCapturePerfStatus();
                return;
            }

            ReportFrameSendResumedIfNeeded(frameNote);
            _lastFrameSendTime = Time.unscaledTimeAsDouble;
            _localStreamFrameCount++;
            if (_localStreamFrameCount == 1 || _localStreamFrameCount % 30 == 0)
            {
                EmitLocalStatus("local_stream_frames", $"{_localStreamFrameCount} | {frameNote}");
            }

            MaybeEmitCapturePerfStatus();

            if (!_sessionConfigSent)
            {
                TrySendSessionConfig();
            }

            if (_laneCalibration.isValid && !_laneCalibrationSent)
            {
                TrySendLaneCalibration();
            }
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

            _laneCalibrationSent = false;
            TrySendLaneCalibration();
        }

        public void SetShotId(string shotId)
        {
            _shotId = string.IsNullOrWhiteSpace(shotId) ? "default-shot" : shotId;
            ResetCapturePerfWindow();
        }

        public bool SendShotMarker(BowlingShotMarkerType markerType)
        {
            if (!CanSendControlMessages())
            {
                EmitLocalStatus("marker_dropped", $"{markerType} while control closed");
                return false;
            }

            return SendControlJsonPacket(
                BowlingPacketType.ShotMarker,
                new ShotMarkerMessage
                {
                    kind = "shot_marker",
                    session_id = _sessionId,
                    shot_id = _shotId,
                    marker_type = (int)markerType,
                    timestamp_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                });
        }

        public void ShowLocalStatus(string stage, string message = null)
        {
            EmitLocalStatus(stage, message);
        }

        private IEnumerator ConnectionLoop()
        {
            while (enabled)
            {
                if (!_connecting && !IsConnected)
                {
                    yield return ConnectOnce();
                }

                if (!IsConnected)
                {
                    yield return new WaitForSecondsRealtime(reconnectDelaySeconds);
                }
                else
                {
                    yield return null;
                }
            }
        }

        private IEnumerator ConnectOnce()
        {
            _connecting = true;
            CleanupConnection();
            EmitLocalStatus("connecting", $"{serverHost}:{serverPort}");

            if (connectionMode == ConnectionMode.LocalLoopback)
            {
                EmitLocalStatus("loopback_unsupported", "UDP transport uses the remote laptop path only.");
                connectionMode = ConnectionMode.RemoteLaptop;
            }

            if (UsesPassthroughCamera() && !AreCameraPermissionsGranted())
            {
                RequestCameraPermissionsIfNeeded();
                EmitLocalStatus("waiting_permissions", "Grant Scene and Passthrough Camera permissions on Quest.");
                _connecting = false;
                yield break;
            }

            if (UsesPassthroughCamera() && cameraAccess == null)
            {
                EmitLocalStatus("camera_missing", "PassthroughCameraAccess is not assigned.");
                _connecting = false;
                yield break;
            }

            if (!TryGetStreamSetup(out var streamWidth, out var streamHeight, out var sourceNote))
            {
                EmitLocalStatus("waiting_camera", sourceNote);
                _connecting = false;
                yield break;
            }

            EmitLocalStatus("stream_source", sourceNote);
            EnsureStreamTexture(streamWidth, streamHeight);
            EmitLocalStatus("stream_texture_ready", $"{streamWidth}x{streamHeight}");

            var tcpClient = new TcpClient
            {
                NoDelay = true,
            };

            var connectTask = tcpClient.ConnectAsync(serverHost, serverPort);
            var deadline = Time.realtimeSinceStartup + Mathf.Max(0.5f, connectTimeoutSeconds);
            while (!connectTask.IsCompleted && Time.realtimeSinceStartup < deadline)
            {
                yield return null;
            }

            if (!connectTask.IsCompleted)
            {
                tcpClient.Dispose();
                EmitLocalStatus("control_connect_timeout", $"{connectTimeoutSeconds:0.0}s");
                _connecting = false;
                yield break;
            }

            if (connectTask.IsFaulted)
            {
                tcpClient.Dispose();
                var message = connectTask.Exception?.GetBaseException().Message ?? "unknown";
                EmitLocalStatus("control_connect_failed", message);
                _connecting = false;
                yield break;
            }

            try
            {
                tcpClient.SendTimeout = 0;
                tcpClient.ReceiveTimeout = 0;
                _controlClient = tcpClient;
                _controlStream = tcpClient.GetStream();
                _frameClient = new UdpClient();
                _frameClient.Connect(serverHost, serverPort);
                _connectionCts = new CancellationTokenSource();
                _controlConnected = true;
                _helloSent = false;
                _sessionConfigSent = false;
                _laneCalibrationSent = false;
                _controlReadTask = Task.Run(() => ControlReadLoop(_connectionCts.Token));
            }
            catch (Exception ex)
            {
                tcpClient.Dispose();
                CleanupConnection();
                EmitLocalStatus("transport_open_failed", ex.GetType().Name + ": " + ex.Message);
                _connecting = false;
                yield break;
            }

            EmitLocalStatus("transport_ready", $"tcp+udp {serverHost}:{serverPort}");
            MaybeEmitVideoEncoderProbeStatus();
            TrySendHello();
            TrySendSessionConfig();
            TrySendLaneCalibration();
            _connecting = false;
        }

        private void ControlReadLoop(CancellationToken cancellationToken)
        {
            try
            {
                while (!cancellationToken.IsCancellationRequested && _controlStream != null)
                {
                    var packet = BowlingProtocol.ReadPacket(_controlStream);
                    if (packet == null)
                    {
                        break;
                    }

                    _inboundPackets.Enqueue(new QueuedInboundPacket
                    {
                        type = packet.Value.type,
                        json = BowlingProtocol.DecodeUtf8Payload(packet.Value.payload),
                    });
                }
            }
            catch (Exception ex)
            {
                if (!cancellationToken.IsCancellationRequested)
                {
                    QueueStatus("control_read_failed", ex.GetType().Name + ": " + ex.Message);
                }
            }
            finally
            {
                _controlConnected = false;
                if (!cancellationToken.IsCancellationRequested)
                {
                    QueueStatus("control_disconnected");
                }
            }
        }

        private void DrainQueuedStatuses()
        {
            while (_queuedStatuses.TryDequeue(out var status))
            {
                EmitLocalStatus(status.stage, status.message);
            }
        }

        private void DrainInboundPackets()
        {
            while (_inboundPackets.TryDequeue(out var packet))
            {
                HandleIncomingPacket(packet.type, packet.json);
            }
        }

        private void HandleIncomingPacket(BowlingPacketType type, string json)
        {
            switch (type)
            {
                case BowlingPacketType.TrackerStatus:
                    HandleTrackerStatusJson(json);
                    break;
                case BowlingPacketType.ShotResult:
                    HandleShotResultJson(json);
                    break;
                case BowlingPacketType.Pong:
                    break;
                case BowlingPacketType.Error:
                    EmitLocalStatus("remote_error", json);
                    break;
                default:
                    if (verboseLogging)
                    {
                        Debug.Log($"[QuestBowlingStreamClient] Ignored inbound packet {type}: {json}");
                    }
                    break;
            }
        }

        private void HandleTrackerStatusJson(string json)
        {
            IncomingEnvelope envelope = null;
            try
            {
                envelope = JsonUtility.FromJson<IncomingEnvelope>(json);
            }
            catch
            {
            }

            if (envelope?.kind == "tracker_status")
            {
                try
                {
                    var status = JsonUtility.FromJson<LocalTrackerStatusMessage>(json);
                    var summary = status != null && !string.IsNullOrWhiteSpace(status.stage)
                        ? status.stage
                        : "tracker_status";
                    if (!string.IsNullOrWhiteSpace(status?.message))
                    {
                        summary += $" | {status.message}";
                    }

                    EmitLocalStatus("remote_tracker_status", summary);
                }
                catch
                {
                    EmitLocalStatus("remote_tracker_status", "parse_failed");
                }
            }

            onTrackerStatus.Invoke(json);
            TrackerStatusReceived?.Invoke(json);
        }

        private void HandleShotResultJson(string json)
        {
            try
            {
                var result = JsonUtility.FromJson<ShotResultSummaryMessage>(json);
                if (result == null)
                {
                    EmitLocalStatus("shot_result_received", "null");
                }
                else if (result.success)
                {
                    EmitLocalStatus(
                        "shot_result_received",
                        $"ok | tracked {result.tracked_frames} | {result.first_frame}->{result.last_frame}");
                }
                else
                {
                    EmitLocalStatus("shot_result_received", $"failed | {result.failure_reason}");
                }
            }
            catch
            {
                EmitLocalStatus("shot_result_received", "parse_failed");
            }

            onShotResultJson.Invoke(json);
            ShotResultReceived?.Invoke(json);
        }

        private void TrySendHello()
        {
            if (_helloSent || !CanSendControlMessages())
            {
                return;
            }

            if (SendControlJsonPacket(
                    BowlingPacketType.Hello,
                    new HelloMessage
                    {
                        kind = "hello",
                        session_id = _sessionId,
                        device_name = SystemInfo.deviceName,
                        app_version = Application.version,
                    }))
            {
                _helloSent = true;
                EmitLocalStatus("hello_sent");
            }
        }

        private void TrySendSessionConfig()
        {
            if (_sessionConfigSent || !CanSendControlMessages())
            {
                return;
            }

            if (!TryGetStreamSetup(out var streamWidth, out var streamHeight, out _))
            {
                return;
            }

            var passthroughSourceWidth = streamWidth;
            var passthroughSourceHeight = streamHeight;
            float fx = 0f;
            float fy = 0f;
            float cx = streamWidth * 0.5f;
            float cy = streamHeight * 0.5f;
            int sensorWidth = streamWidth;
            int sensorHeight = streamHeight;
            float lensPositionX = 0f;
            float lensPositionY = 0f;
            float lensPositionZ = 0f;
            float lensRotationX = 0f;
            float lensRotationY = 0f;
            float lensRotationZ = 0f;
            float lensRotationW = 1f;

            if (UsesPassthroughCamera() && cameraAccess != null && cameraAccess.IsPlaying)
            {
                var intrinsics = cameraAccess.Intrinsics;
                var sourceTexture = cameraAccess.GetTexture();
                if (sourceTexture != null)
                {
                    passthroughSourceWidth = Mathf.Max(1, sourceTexture.width);
                    passthroughSourceHeight = Mathf.Max(1, sourceTexture.height);
                }

                var widthScale = (float)streamWidth / Mathf.Max(1, passthroughSourceWidth);
                var heightScale = (float)streamHeight / Mathf.Max(1, passthroughSourceHeight);
                fx = intrinsics.FocalLength.x * widthScale;
                fy = intrinsics.FocalLength.y * heightScale;
                cx = intrinsics.PrincipalPoint.x * widthScale;
                cy = intrinsics.PrincipalPoint.y * heightScale;
                sensorWidth = streamWidth;
                sensorHeight = streamHeight;
                lensPositionX = intrinsics.LensOffset.position.x;
                lensPositionY = intrinsics.LensOffset.position.y;
                lensPositionZ = intrinsics.LensOffset.position.z;
                lensRotationX = intrinsics.LensOffset.rotation.x;
                lensRotationY = intrinsics.LensOffset.rotation.y;
                lensRotationZ = intrinsics.LensOffset.rotation.z;
                lensRotationW = intrinsics.LensOffset.rotation.w;
            }

            if (SendControlJsonPacket(
                    BowlingPacketType.SessionConfig,
                    new SessionConfigMessage
                    {
                        kind = "session_config",
                        session_id = _sessionId,
                        camera_eye = cameraAccess != null && cameraAccess.CameraPosition == PassthroughCameraAccess.CameraPositionType.Left ? 0 : 1,
                        width = streamWidth,
                        height = streamHeight,
                        fx = fx,
                        fy = fy,
                        cx = cx,
                        cy = cy,
                        sensor_width = sensorWidth,
                        sensor_height = sensorHeight,
                        lens_position_x = lensPositionX,
                        lens_position_y = lensPositionY,
                        lens_position_z = lensPositionZ,
                        lens_rotation_x = lensRotationX,
                        lens_rotation_y = lensRotationY,
                        lens_rotation_z = lensRotationZ,
                        lens_rotation_w = lensRotationW,
                        target_send_fps = targetSendFps,
                        transport = "udp",
                        video_codec = "jpeg",
                        target_bitrate_kbps = targetBitrateKbps,
                    }))
            {
                _sessionConfigSent = true;
                EmitLocalStatus("session_config_sent", $"{streamWidth}x{streamHeight}");
            }
        }

        private void TrySendLaneCalibration()
        {
            if (_laneCalibrationSent || !CanSendControlMessages() || !_laneCalibration.isValid)
            {
                return;
            }

            if (SendControlJsonPacket(
                    BowlingPacketType.LaneCalibration,
                    new LaneCalibrationMessage
                    {
                        kind = "lane_calibration",
                        session_id = _sessionId,
                        timestamp_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                        is_valid = _laneCalibration.isValid,
                        origin_x = _laneCalibration.origin.x,
                        origin_y = _laneCalibration.origin.y,
                        origin_z = _laneCalibration.origin.z,
                        rotation_x = _laneCalibration.rotation.x,
                        rotation_y = _laneCalibration.rotation.y,
                        rotation_z = _laneCalibration.rotation.z,
                        rotation_w = _laneCalibration.rotation.w,
                        lane_width_m = _laneCalibration.laneWidthMeters,
                        lane_length_m = _laneCalibration.laneLengthMeters,
                    }))
            {
                _laneCalibrationSent = true;
                EmitLocalStatus("lane_calibration_sent");
            }
        }

        private bool SendControlJsonPacket(BowlingPacketType type, object payload)
        {
            if (!CanSendControlMessages())
            {
                return false;
            }

            try
            {
                var json = JsonUtility.ToJson(payload);
                var bytes = Encoding.UTF8.GetBytes(json);
                lock (_controlSendGate)
                {
                    if (_controlStream == null)
                    {
                        return false;
                    }

                    BowlingProtocol.WritePacket(_controlStream, type, bytes);
                }

                return true;
            }
            catch (Exception ex)
            {
                _controlConnected = false;
                QueueStatus("control_send_failed", ex.GetType().Name + ": " + ex.Message);
                return false;
            }
        }

        private bool CanSendControlMessages()
        {
            return _controlConnected && _controlStream != null;
        }

        private bool TrySendCurrentFrame(out string note)
        {
            note = "unknown";
            if (!CanSendControlMessages() || _frameClient == null)
            {
                note = "transport_not_ready";
                return false;
            }

            if (useAsyncGpuReadback && SystemInfo.supportsAsyncGPUReadback)
            {
                return TrySendCurrentFrameAsync(out note);
            }

            var frameStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            double renderMs = 0.0;
            double readbackMs = 0.0;
            double applyMs = 0.0;
            double jpegMs = 0.0;
            double encodeMs = 0.0;
            double udpMs = 0.0;

            var renderStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            if (!TryRenderStreamFrame(out var sourceNote))
            {
                renderMs = Time.realtimeSinceStartupAsDouble * 1000.0 - renderStartMs;
                note = $"{sourceNote} | render_ms {renderMs:F1}";
                return false;
            }
            renderMs = Time.realtimeSinceStartupAsDouble * 1000.0 - renderStartMs;

            var encodeStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            if (!TryEncodeCurrentFrame(out var encodedJpeg, out var encodeNote, out readbackMs, out applyMs, out jpegMs))
            {
                encodeMs = Time.realtimeSinceStartupAsDouble * 1000.0 - encodeStartMs;
                note = $"{encodeNote} | render_ms {renderMs:F1} | readback_ms {readbackMs:F1} | apply_ms {applyMs:F1} | jpeg_ms {jpegMs:F1} | encode_ms {encodeMs:F1}";
                return false;
            }
            encodeMs = Time.realtimeSinceStartupAsDouble * 1000.0 - encodeStartMs;

            var frameId = _nextFrameId++;
            var headPose = GetHeadPose();
            var cameraPose = GetCameraPose(headPose);
            var frameTimestampUtc = GetFrameTimestampUtc();
            var framePayload = BowlingProtocol.EncodeFramePacket(
                _sessionId,
                _shotId,
                frameId,
                frameTimestampUtc,
                cameraPose,
                headPose,
                encodedJpeg);

            var udpStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            if (!TrySendUdpFrame(frameId, framePayload, out var udpNote))
            {
                udpMs = Time.realtimeSinceStartupAsDouble * 1000.0 - udpStartMs;
                var totalMsFailed = Time.realtimeSinceStartupAsDouble * 1000.0 - frameStartMs;
                note = $"{udpNote} | render_ms {renderMs:F1} | readback_ms {readbackMs:F1} | apply_ms {applyMs:F1} | jpeg_ms {jpegMs:F1} | encode_ms {encodeMs:F1} | udp_ms {udpMs:F1} | total_ms {totalMsFailed:F1}";
                return false;
            }
            udpMs = Time.realtimeSinceStartupAsDouble * 1000.0 - udpStartMs;

            var totalMs = Time.realtimeSinceStartupAsDouble * 1000.0 - frameStartMs;
            TrackCaptureSent(renderMs, readbackMs, applyMs, jpegMs, encodeMs, udpMs, totalMs);
            MaybeEmitSlowFrameStatus(frameId, renderMs, readbackMs, applyMs, jpegMs, encodeMs, udpMs, totalMs, encodedJpeg.Length);

            note = $"frame {frameId} | {sourceNote} | jpeg {encodedJpeg.Length} | {udpNote} | render_ms {renderMs:F1} | readback_ms {readbackMs:F1} | apply_ms {applyMs:F1} | jpeg_ms {jpegMs:F1} | encode_ms {encodeMs:F1} | udp_ms {udpMs:F1} | total_ms {totalMs:F1}";
            return true;
        }

        private bool TrySendCurrentFrameAsync(out string note)
        {
            note = "async_readback_unavailable";
            if (_hasPendingReadbackRequest)
            {
                if (!_pendingReadbackRequest.done)
                {
                    note = "async_readback_pending";
                    return false;
                }

                return TryFinalizePendingAsyncFrame(out note);
            }

            var renderStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            if (!TryRenderStreamFrame(out var sourceNote))
            {
                var renderMsFailed = Time.realtimeSinceStartupAsDouble * 1000.0 - renderStartMs;
                note = $"{sourceNote} | render_ms {renderMsFailed:F1}";
                return false;
            }

            var renderMs = Time.realtimeSinceStartupAsDouble * 1000.0 - renderStartMs;
            var frameId = _nextFrameId++;
            var headPose = GetHeadPose();
            var cameraPose = GetCameraPose(headPose);
            var frameTimestampUtc = GetFrameTimestampUtc();
            var issuedAtMs = Time.realtimeSinceStartupAsDouble * 1000.0;

            try
            {
                _pendingReadbackRequest = AsyncGPUReadback.Request(_streamTexture, 0, TextureFormat.RGB24);
                _hasPendingReadbackRequest = true;
                _pendingReadbackFrameId = frameId;
                _pendingReadbackTimestampUtc = frameTimestampUtc;
                _pendingReadbackCameraPose = cameraPose;
                _pendingReadbackHeadPose = headPose;
                _pendingReadbackSourceNote = sourceNote;
                _pendingReadbackShotId = _shotId;
                _pendingReadbackRenderMs = renderMs;
                _pendingReadbackIssuedAtMs = issuedAtMs;
                _pendingReadbackWidth = _streamTexture.width;
                _pendingReadbackHeight = _streamTexture.height;
                note = $"async_readback_started | frame {frameId} | {sourceNote} | render_ms {renderMs:F1}";
                return false;
            }
            catch (Exception ex)
            {
                note = $"async_readback_start_failed | render_ms {renderMs:F1}";
                QueueStatus("frame_encode_failed", ex.GetType().Name + ": " + ex.Message);
                ClearPendingAsyncReadback();
                return false;
            }
        }

        private bool TryFinalizePendingAsyncFrame(out string note)
        {
            note = "async_readback_missing";
            if (!_hasPendingReadbackRequest)
            {
                return false;
            }

            var renderMs = _pendingReadbackRenderMs;
            var readbackMs = Math.Max(0.0, Time.realtimeSinceStartupAsDouble * 1000.0 - _pendingReadbackIssuedAtMs);
            double applyMs = 0.0;
            double jpegMs = 0.0;
            byte[] encodedJpeg = null;
            ulong frameId = _pendingReadbackFrameId;
            string sourceNote = _pendingReadbackSourceNote;
            DateTime timestampUtc = _pendingReadbackTimestampUtc;
            Pose cameraPose = _pendingReadbackCameraPose;
            Pose headPose = _pendingReadbackHeadPose;
            string shotId = _pendingReadbackShotId;
            int width = _pendingReadbackWidth;
            int height = _pendingReadbackHeight;

            try
            {
                if (_pendingReadbackRequest.hasError)
                {
                    note = $"async_readback_error | render_ms {renderMs:F1} | readback_ms {readbackMs:F1}";
                    return false;
                }

                EnsureReadbackTexture(width, height);
                var data = _pendingReadbackRequest.GetData<byte>();

                var applyStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
                _readbackTexture.LoadRawTextureData(data);
                _readbackTexture.Apply(false, false);
                applyMs = Time.realtimeSinceStartupAsDouble * 1000.0 - applyStartMs;

                var jpegStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
                encodedJpeg = ImageConversion.EncodeToJPG(_readbackTexture, Mathf.Clamp(jpegQuality, 1, 100));
                jpegMs = Time.realtimeSinceStartupAsDouble * 1000.0 - jpegStartMs;
                if (encodedJpeg == null || encodedJpeg.Length == 0)
                {
                    note = $"jpeg_encode_failed | render_ms {renderMs:F1} | readback_ms {readbackMs:F1} | apply_ms {applyMs:F1} | jpeg_ms {jpegMs:F1}";
                    return false;
                }
            }
            catch (Exception ex)
            {
                note = $"async_readback_encode_exception | render_ms {renderMs:F1} | readback_ms {readbackMs:F1} | apply_ms {applyMs:F1} | jpeg_ms {jpegMs:F1}";
                QueueStatus("frame_encode_failed", ex.GetType().Name + ": " + ex.Message);
                return false;
            }
            finally
            {
                ClearPendingAsyncReadback();
            }

            var encodeMs = readbackMs + applyMs + jpegMs;
            var framePayload = BowlingProtocol.EncodeFramePacket(
                _sessionId,
                shotId,
                frameId,
                timestampUtc,
                cameraPose,
                headPose,
                encodedJpeg);

            var udpStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            if (!TrySendUdpFrame(frameId, framePayload, out var udpNote))
            {
                var udpMsFailed = Time.realtimeSinceStartupAsDouble * 1000.0 - udpStartMs;
                var totalMsFailed = renderMs + encodeMs + udpMsFailed;
                note = $"{udpNote} | render_ms {renderMs:F1} | readback_ms {readbackMs:F1} | apply_ms {applyMs:F1} | jpeg_ms {jpegMs:F1} | encode_ms {encodeMs:F1} | udp_ms {udpMsFailed:F1} | total_ms {totalMsFailed:F1}";
                return false;
            }

            var udpMs = Time.realtimeSinceStartupAsDouble * 1000.0 - udpStartMs;
            var totalMs = renderMs + encodeMs + udpMs;
            TrackCaptureSent(renderMs, readbackMs, applyMs, jpegMs, encodeMs, udpMs, totalMs);
            MaybeEmitSlowFrameStatus(frameId, renderMs, readbackMs, applyMs, jpegMs, encodeMs, udpMs, totalMs, encodedJpeg.Length);
            note = $"frame {frameId} | {sourceNote} | async_jpeg {encodedJpeg.Length} | {udpNote} | render_ms {renderMs:F1} | readback_ms {readbackMs:F1} | apply_ms {applyMs:F1} | jpeg_ms {jpegMs:F1} | encode_ms {encodeMs:F1} | udp_ms {udpMs:F1} | total_ms {totalMs:F1}";
            return true;
        }

        private bool TryEncodeCurrentFrame(out byte[] encodedJpeg, out string note, out double readbackMs, out double applyMs, out double jpegMs)
        {
            encodedJpeg = null;
            note = "readback_unavailable";
            readbackMs = 0.0;
            applyMs = 0.0;
            jpegMs = 0.0;

            if (_streamTexture == null)
            {
                note = "stream_texture_missing";
                return false;
            }

            EnsureReadbackTexture(_streamTexture.width, _streamTexture.height);
            var previousActive = RenderTexture.active;
            try
            {
                RenderTexture.active = _streamTexture;
                var readbackStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
                _readbackTexture.ReadPixels(new Rect(0, 0, _streamTexture.width, _streamTexture.height), 0, 0, false);
                readbackMs = Time.realtimeSinceStartupAsDouble * 1000.0 - readbackStartMs;

                var applyStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
                _readbackTexture.Apply(false, false);
                applyMs = Time.realtimeSinceStartupAsDouble * 1000.0 - applyStartMs;

                var jpegStartMs = Time.realtimeSinceStartupAsDouble * 1000.0;
                encodedJpeg = ImageConversion.EncodeToJPG(_readbackTexture, Mathf.Clamp(jpegQuality, 1, 100));
                jpegMs = Time.realtimeSinceStartupAsDouble * 1000.0 - jpegStartMs;
                if (encodedJpeg == null || encodedJpeg.Length == 0)
                {
                    note = "jpeg_encode_failed";
                    return false;
                }

                note = $"jpeg {encodedJpeg.Length}";
                return true;
            }
            catch (Exception ex)
            {
                note = "jpeg_encode_exception";
                QueueStatus("frame_encode_failed", ex.GetType().Name + ": " + ex.Message);
                return false;
            }
            finally
            {
                RenderTexture.active = previousActive;
            }
        }

        private bool TrySendUdpFrame(ulong frameId, byte[] payload, out string note)
        {
            note = "udp_send_failed";
            if (_frameClient == null)
            {
                note = "udp_client_missing";
                return false;
            }

            payload ??= Array.Empty<byte>();
            var datagramLimit = Mathf.Max(UdpFrameHeaderSize + 256, maxDatagramPayloadBytes);
            var chunkPayloadSize = datagramLimit - UdpFrameHeaderSize;
            var chunkCount = Math.Max(1, (payload.Length + chunkPayloadSize - 1) / chunkPayloadSize);
            if (chunkCount > ushort.MaxValue)
            {
                note = $"frame_too_large {payload.Length}";
                return false;
            }

            try
            {
                for (var chunkIndex = 0; chunkIndex < chunkCount; chunkIndex++)
                {
                    var payloadOffset = chunkIndex * chunkPayloadSize;
                    var payloadLength = Math.Min(chunkPayloadSize, payload.Length - payloadOffset);
                    var datagram = new byte[UdpFrameHeaderSize + payloadLength];
                    WriteUInt32(datagram, 0, BowlingProtocol.Magic);
                    WriteUInt16(datagram, 4, BowlingProtocol.Version);
                    WriteUInt16(datagram, 6, (ushort)BowlingPacketType.FramePacket);
                    WriteUInt64(datagram, 8, frameId);
                    WriteUInt16(datagram, 16, (ushort)chunkIndex);
                    WriteUInt16(datagram, 18, (ushort)chunkCount);
                    WriteUInt16(datagram, 20, (ushort)payloadLength);
                    WriteUInt32(datagram, 22, (uint)payload.Length);
                    Buffer.BlockCopy(payload, payloadOffset, datagram, UdpFrameHeaderSize, payloadLength);
                    _frameClient.Send(datagram, datagram.Length);
                }

                note = $"{payload.Length} bytes | {chunkCount} udp | chunk {chunkPayloadSize}";
                return true;
            }
            catch (Exception ex)
            {
                _controlConnected = false;
                QueueStatus("udp_send_failed", ex.GetType().Name + ": " + ex.Message);
                return false;
            }
        }

        private Pose GetHeadPose()
        {
            var anchor = ResolveHeadAnchorTransform();
            if (anchor == null)
            {
                return new Pose(transform.position, transform.rotation);
            }

            return new Pose(anchor.position, anchor.rotation);
        }

        private Pose GetCameraPose(Pose fallbackPose)
        {
            if (UsesPassthroughCamera() && cameraAccess != null && cameraAccess.IsPlaying)
            {
                return cameraAccess.GetCameraPose();
            }

            if (_syntheticSenderCamera != null)
            {
                return new Pose(_syntheticSenderCamera.transform.position, _syntheticSenderCamera.transform.rotation);
            }

            if (Camera.main != null)
            {
                return new Pose(Camera.main.transform.position, Camera.main.transform.rotation);
            }

            return fallbackPose;
        }

        private DateTime GetFrameTimestampUtc()
        {
            if (UsesPassthroughCamera() && cameraAccess != null && cameraAccess.IsPlaying)
            {
                var cameraTimestamp = cameraAccess.Timestamp;
                if (cameraTimestamp != default)
                {
                    return cameraTimestamp.Kind == DateTimeKind.Utc ? cameraTimestamp : cameraTimestamp.ToUniversalTime();
                }
            }

            return DateTime.UtcNow;
        }

        private Transform ResolveHeadAnchorTransform()
        {
            if (_headAnchorTransform != null)
            {
                return _headAnchorTransform;
            }

            _headAnchorTransform = GameObject.Find("CenterEyeAnchor")?.transform;
            if (_headAnchorTransform == null && Camera.main != null)
            {
                _headAnchorTransform = Camera.main.transform;
            }

            return _headAnchorTransform;
        }

        private void ConfigurePassthroughCameraAccess()
        {
            if (cameraAccess == null)
            {
                return;
            }

            cameraAccess.CameraPosition = cameraPosition;

            var requestedMaxFramerate = Mathf.Max(1, targetSendFps);
            if (cameraAccess.MaxFramerate == requestedMaxFramerate)
            {
                return;
            }

            var wasEnabled = cameraAccess.enabled;
            if (wasEnabled)
            {
                cameraAccess.enabled = false;
            }

            cameraAccess.MaxFramerate = requestedMaxFramerate;

            if (wasEnabled)
            {
                cameraAccess.enabled = true;
            }

            EmitLocalStatus("camera_max_fps_requested", requestedMaxFramerate.ToString());
        }

        private void EnsureCaptureStatsWindowStarted()
        {
            if (_captureStatsWindowStartTime <= 0.0)
            {
                _captureStatsWindowStartTime = Time.unscaledTimeAsDouble;
            }
        }

        private void ObserveCameraUpdateIfNeeded()
        {
            if (!UsesPassthroughCamera() || cameraAccess == null || !cameraAccess.IsPlaying)
            {
                return;
            }

            EnsureCaptureStatsWindowStarted();
            if (!cameraAccess.IsUpdatedThisFrame)
            {
                return;
            }

            var now = Time.unscaledTimeAsDouble;
            if (_captureCameraLastUpdateTime > 0.0)
            {
                var deltaMs = (now - _captureCameraLastUpdateTime) * 1000.0;
                _captureCameraUpdateDeltaSumMs += deltaMs;
                _captureCameraUpdateMinDeltaMs = Math.Min(_captureCameraUpdateMinDeltaMs, deltaMs);
                _captureCameraUpdateMaxDeltaMs = Math.Max(_captureCameraUpdateMaxDeltaMs, deltaMs);
            }

            _captureCameraLastUpdateTime = now;
            _captureCameraUpdateCount++;
        }

        private void MaybeEmitCameraSourcePerfStatus()
        {
            if (_captureCameraUpdateCount <= 0 || _captureCameraUpdateCount % 15 != 0)
            {
                return;
            }

            var now = Time.unscaledTimeAsDouble;
            var windowSeconds = Math.Max(0.001, now - _captureStatsWindowStartTime);
            var cameraUpdateFps = _captureCameraUpdateCount / windowSeconds;
            var avgCameraDeltaMs = _captureCameraUpdateCount > 1 ? _captureCameraUpdateDeltaSumMs / (_captureCameraUpdateCount - 1) : 0.0;
            var minCameraDeltaMs = double.IsPositiveInfinity(_captureCameraUpdateMinDeltaMs) ? 0.0 : _captureCameraUpdateMinDeltaMs;

            EmitLocalStatus(
                "camera_source_perf",
                $"requested {targetSendFps} | camera_update_fps {cameraUpdateFps:F1} | avg_camera_gap_ms {avgCameraDeltaMs:F1} | min_camera_gap_ms {minCameraDeltaMs:F1} | max_camera_gap_ms {_captureCameraUpdateMaxDeltaMs:F1} | camera_updates {_captureCameraUpdateCount} | probe_only 1");
        }

        private static bool IsDeferredCaptureState(string note)
        {
            return note != null &&
                   (note.StartsWith("async_readback_started", StringComparison.Ordinal) ||
                    note.StartsWith("async_readback_pending", StringComparison.Ordinal));
        }

        private void ClearPendingAsyncReadback()
        {
            _hasPendingReadbackRequest = false;
            _pendingReadbackRequest = default;
            _pendingReadbackFrameId = 0;
            _pendingReadbackTimestampUtc = default;
            _pendingReadbackCameraPose = default;
            _pendingReadbackHeadPose = default;
            _pendingReadbackSourceNote = null;
            _pendingReadbackShotId = null;
            _pendingReadbackRenderMs = 0.0;
            _pendingReadbackIssuedAtMs = 0.0;
            _pendingReadbackWidth = 0;
            _pendingReadbackHeight = 0;
        }

        private void MaybeEmitVideoEncoderProbeStatus()
        {
            if (_videoEncoderProbeReported)
            {
                return;
            }

            var result = QuestVideoEncoderProbe.Probe();
            EmitLocalStatus("video_encoder_probe", QuestVideoEncoderProbe.Summarize(result));
            _videoEncoderProbeReported = true;
        }

        private void TrackCaptureBlocked(string note)
        {
            if (note != null && note.StartsWith("passthrough_not_updated", StringComparison.Ordinal))
            {
                _captureBlockedPassthroughCount++;
                return;
            }

            _captureBlockedOtherCount++;
        }

        private void TrackCaptureSent(double renderMs, double readbackMs, double applyMs, double jpegMs, double encodeMs, double udpMs, double totalMs)
        {
            var now = Time.unscaledTimeAsDouble;
            EnsureCaptureStatsWindowStarted();

            if (_captureStatsLastSentTime > 0.0)
            {
                var deltaMs = (now - _captureStatsLastSentTime) * 1000.0;
                _captureStatsSentDeltaSumMs += deltaMs;
                _captureStatsMinSentDeltaMs = Math.Min(_captureStatsMinSentDeltaMs, deltaMs);
                _captureStatsMaxSentDeltaMs = Math.Max(_captureStatsMaxSentDeltaMs, deltaMs);
            }

            _captureStatsLastSentTime = now;
            _captureSentCount++;
            _captureRenderSumMs += renderMs;
            _captureReadbackSumMs += readbackMs;
            _captureApplySumMs += applyMs;
            _captureJpegSumMs += jpegMs;
            _captureEncodeSumMs += encodeMs;
            _captureUdpSumMs += udpMs;
            _captureTotalSumMs += totalMs;
            _captureRenderMaxMs = Math.Max(_captureRenderMaxMs, renderMs);
            _captureReadbackMaxMs = Math.Max(_captureReadbackMaxMs, readbackMs);
            _captureApplyMaxMs = Math.Max(_captureApplyMaxMs, applyMs);
            _captureJpegMaxMs = Math.Max(_captureJpegMaxMs, jpegMs);
            _captureEncodeMaxMs = Math.Max(_captureEncodeMaxMs, encodeMs);
            _captureUdpMaxMs = Math.Max(_captureUdpMaxMs, udpMs);
            _captureTotalMaxMs = Math.Max(_captureTotalMaxMs, totalMs);
        }

        private void MaybeEmitCapturePerfStatus()
        {
            if (_captureSentCount <= 0 || _captureSentCount % 5 != 0)
            {
                return;
            }

            var now = Time.unscaledTimeAsDouble;
            var windowSeconds = Math.Max(0.001, now - _captureStatsWindowStartTime);
            var effectiveFps = _captureSentCount / windowSeconds;
            var cameraUpdateFps = _captureCameraUpdateCount / windowSeconds;
            var avgDeltaMs = _captureSentCount > 1 ? _captureStatsSentDeltaSumMs / (_captureSentCount - 1) : 0.0;
            var minDeltaMs = double.IsPositiveInfinity(_captureStatsMinSentDeltaMs) ? 0.0 : _captureStatsMinSentDeltaMs;
            var avgCameraDeltaMs = _captureCameraUpdateCount > 1 ? _captureCameraUpdateDeltaSumMs / (_captureCameraUpdateCount - 1) : 0.0;
            var minCameraDeltaMs = double.IsPositiveInfinity(_captureCameraUpdateMinDeltaMs) ? 0.0 : _captureCameraUpdateMinDeltaMs;
            var avgRenderMs = _captureRenderSumMs / _captureSentCount;
            var avgReadbackMs = _captureReadbackSumMs / _captureSentCount;
            var avgApplyMs = _captureApplySumMs / _captureSentCount;
            var avgJpegMs = _captureJpegSumMs / _captureSentCount;
            var avgEncodeMs = _captureEncodeSumMs / _captureSentCount;
            var avgUdpMs = _captureUdpSumMs / _captureSentCount;
            var avgTotalMs = _captureTotalSumMs / _captureSentCount;

            EmitLocalStatus(
                "capture_perf",
                $"target {targetSendFps} | effective {effectiveFps:F1} | camera_update_fps {cameraUpdateFps:F1} | avg_gap_ms {avgDeltaMs:F1} | min_gap_ms {minDeltaMs:F1} | max_gap_ms {_captureStatsMaxSentDeltaMs:F1} | avg_camera_gap_ms {avgCameraDeltaMs:F1} | min_camera_gap_ms {minCameraDeltaMs:F1} | max_camera_gap_ms {_captureCameraUpdateMaxDeltaMs:F1} | avg_render_ms {avgRenderMs:F1} | avg_readback_ms {avgReadbackMs:F1} | avg_apply_ms {avgApplyMs:F1} | avg_jpeg_ms {avgJpegMs:F1} | avg_encode_ms {avgEncodeMs:F1} | avg_udp_ms {avgUdpMs:F1} | avg_total_ms {avgTotalMs:F1} | max_render_ms {_captureRenderMaxMs:F1} | max_readback_ms {_captureReadbackMaxMs:F1} | max_apply_ms {_captureApplyMaxMs:F1} | max_jpeg_ms {_captureJpegMaxMs:F1} | max_encode_ms {_captureEncodeMaxMs:F1} | max_udp_ms {_captureUdpMaxMs:F1} | max_total_ms {_captureTotalMaxMs:F1} | camera_updates {_captureCameraUpdateCount} | blocked_passthrough {_captureBlockedPassthroughCount} | blocked_other {_captureBlockedOtherCount} | attempts {_captureAttemptCount}");
        }

        private void MaybeEmitSlowFrameStatus(ulong frameId, double renderMs, double readbackMs, double applyMs, double jpegMs, double encodeMs, double udpMs, double totalMs, int jpegBytes)
        {
            if (totalMs < 250.0)
            {
                return;
            }

            EmitLocalStatus(
                "capture_slow_frame",
                $"frame {frameId} | jpeg {jpegBytes} | render_ms {renderMs:F1} | readback_ms {readbackMs:F1} | apply_ms {applyMs:F1} | jpeg_ms {jpegMs:F1} | encode_ms {encodeMs:F1} | udp_ms {udpMs:F1} | total_ms {totalMs:F1}");
        }

        private void ResetCapturePerfWindow()
        {
            _captureAttemptCount = 0;
            _captureSentCount = 0;
            _captureBlockedPassthroughCount = 0;
            _captureBlockedOtherCount = 0;
            _captureStatsWindowStartTime = 0.0;
            _captureStatsLastSentTime = 0.0;
            _captureStatsSentDeltaSumMs = 0.0;
            _captureStatsMinSentDeltaMs = double.PositiveInfinity;
            _captureStatsMaxSentDeltaMs = 0.0;
            _captureCameraUpdateCount = 0;
            _captureCameraLastUpdateTime = 0.0;
            _captureCameraUpdateDeltaSumMs = 0.0;
            _captureCameraUpdateMinDeltaMs = double.PositiveInfinity;
            _captureCameraUpdateMaxDeltaMs = 0.0;
            _captureRenderSumMs = 0.0;
            _captureReadbackSumMs = 0.0;
            _captureApplySumMs = 0.0;
            _captureJpegSumMs = 0.0;
            _captureEncodeSumMs = 0.0;
            _captureUdpSumMs = 0.0;
            _captureTotalSumMs = 0.0;
            _captureRenderMaxMs = 0.0;
            _captureReadbackMaxMs = 0.0;
            _captureApplyMaxMs = 0.0;
            _captureJpegMaxMs = 0.0;
            _captureEncodeMaxMs = 0.0;
            _captureUdpMaxMs = 0.0;
            _captureTotalMaxMs = 0.0;
        }

        private bool UsesPassthroughCamera()
        {
            return streamSource == StreamSourceMode.PassthroughCamera;
        }

        private bool TryGetStreamSetup(out int width, out int height, out string note)
        {
            if (UsesPassthroughCamera())
            {
                width = 0;
                height = 0;
                if (cameraAccess == null)
                {
                    note = "PassthroughCameraAccess is not assigned.";
                    return false;
                }

                if (!cameraAccess.IsPlaying)
                {
                    note = "Passthrough camera is not playing yet.";
                    return false;
                }

                var sourceTexture = cameraAccess.GetTexture();
                if (sourceTexture == null)
                {
                    note = "Passthrough camera texture is still null.";
                    return false;
                }

                GetPassthroughSendResolution(sourceTexture.width, sourceTexture.height, out width, out height);
                note = $"passthrough {sourceTexture.width}x{sourceTexture.height}->{width}x{height}";
                return true;
            }

            width = Mathf.Max(64, syntheticResolution.x);
            height = Mathf.Max(64, syntheticResolution.y);
            note = "synthetic";
            return true;
        }

        private bool TryRenderStreamFrame(out string note)
        {
            note = "unknown";
            if (!TryGetStreamSetup(out var width, out var height, out var sourceNote))
            {
                note = sourceNote;
                return false;
            }

            EnsureStreamTexture(width, height);

            if (UsesPassthroughCamera())
            {
                if (cameraAccess == null || !cameraAccess.IsUpdatedThisFrame)
                {
                    note = "passthrough_not_updated";
                    return false;
                }

                var sourceTexture = cameraAccess.GetTexture();
                if (sourceTexture == null)
                {
                    note = "passthrough_texture_null";
                    return false;
                }

                Graphics.Blit(sourceTexture, _streamTexture);
                note = sourceNote;
                return true;
            }

            EnsureSyntheticSenderCamera(width, height);
            var hue = Mathf.Repeat(_localStreamFrameCount / 90f, 1f);
            _syntheticSenderCamera.backgroundColor = Color.HSVToRGB(hue, 0.85f, 1f);
            _syntheticSenderCamera.targetTexture = _streamTexture;
            _syntheticSenderCamera.Render();
            note = "synthetic_camera";
            return true;
        }

        private void GetPassthroughSendResolution(int sourceWidth, int sourceHeight, out int width, out int height)
        {
            sourceWidth = Mathf.Max(64, sourceWidth);
            sourceHeight = Mathf.Max(64, sourceHeight);

            var configuredWidth = passthroughSendResolution.x;
            var configuredHeight = passthroughSendResolution.y;
            if (configuredWidth <= 0 && configuredHeight <= 0)
            {
                width = sourceWidth;
                height = sourceHeight;
                return;
            }

            if (configuredWidth <= 0)
            {
                configuredWidth = Mathf.RoundToInt(sourceWidth * (configuredHeight / (float)Mathf.Max(1, sourceHeight)));
            }
            else if (configuredHeight <= 0)
            {
                configuredHeight = Mathf.RoundToInt(sourceHeight * (configuredWidth / (float)Mathf.Max(1, sourceWidth)));
            }

            configuredWidth = Mathf.Max(64, configuredWidth);
            configuredHeight = Mathf.Max(64, configuredHeight);

            var scale = Mathf.Min(
                1f,
                Mathf.Min(
                    configuredWidth / (float)Mathf.Max(1, sourceWidth),
                    configuredHeight / (float)Mathf.Max(1, sourceHeight)));

            width = Mathf.Clamp(MakeEven(Mathf.RoundToInt(sourceWidth * scale)), 64, sourceWidth);
            height = Mathf.Clamp(MakeEven(Mathf.RoundToInt(sourceHeight * scale)), 64, sourceHeight);
        }

        private static int MakeEven(int value)
        {
            if (value <= 64)
            {
                return 64;
            }

            return (value & 1) == 0 ? value : value - 1;
        }

        private void EnsureStreamTexture(int width, int height)
        {
            if (_streamTexture != null && _streamTexture.width == width && _streamTexture.height == height)
            {
                return;
            }

            DisposeStreamTexture();
            _streamTexture = new RenderTexture(width, height, 0, RenderTextureFormat.ARGB32)
            {
                name = "QuestBowlingUdpStream",
                useMipMap = false,
                autoGenerateMips = false,
                antiAliasing = 1,
            };
            _streamTexture.Create();
            if (_syntheticSenderCamera != null)
            {
                _syntheticSenderCamera.targetTexture = _streamTexture;
            }
        }

        private void EnsureReadbackTexture(int width, int height)
        {
            if (_readbackTexture != null && _readbackTexture.width == width && _readbackTexture.height == height)
            {
                return;
            }

            DisposeReadbackTexture();
            _readbackTexture = new Texture2D(width, height, TextureFormat.RGB24, false);
        }

        private void EnsureSyntheticSenderCamera(int width, int height)
        {
            if (_syntheticSenderCamera != null)
            {
                _syntheticSenderCamera.aspect = width > 0 && height > 0 ? (float)width / height : 1f;
                return;
            }

            var go = new GameObject("QuestBowlingSyntheticSenderCamera");
            go.hideFlags = HideFlags.HideAndDontSave;
            go.transform.SetParent(transform, false);
            go.transform.localPosition = Vector3.zero;
            go.transform.localRotation = Quaternion.identity;

            _syntheticSenderCamera = go.AddComponent<Camera>();
            _syntheticSenderCamera.enabled = false;
            _syntheticSenderCamera.clearFlags = CameraClearFlags.SolidColor;
            _syntheticSenderCamera.backgroundColor = Color.black;
            _syntheticSenderCamera.cullingMask = 0;
            _syntheticSenderCamera.orthographic = true;
            _syntheticSenderCamera.nearClipPlane = 0.01f;
            _syntheticSenderCamera.farClipPlane = 10f;
            _syntheticSenderCamera.allowHDR = false;
            _syntheticSenderCamera.allowMSAA = false;
            _syntheticSenderCamera.aspect = width > 0 && height > 0 ? (float)width / height : 1f;
            _syntheticSenderCamera.targetTexture = _streamTexture;
        }

        private void DisposeSyntheticSenderCamera()
        {
            if (_syntheticSenderCamera == null)
            {
                return;
            }

            _syntheticSenderCamera.targetTexture = null;
            Destroy(_syntheticSenderCamera.gameObject);
            _syntheticSenderCamera = null;
        }

        private void DisposeReadbackTexture()
        {
            if (_readbackTexture == null)
            {
                return;
            }

            Destroy(_readbackTexture);
            _readbackTexture = null;
        }

        private void DisposeStreamTexture()
        {
            if (_streamTexture == null)
            {
                return;
            }

            if (_streamTexture.IsCreated())
            {
                _streamTexture.Release();
            }

            Destroy(_streamTexture);
            _streamTexture = null;
        }

        private void CleanupConnection()
        {
            _controlConnected = false;
            _connectionCts?.Cancel();
            _connectionCts?.Dispose();
            _connectionCts = null;

            try
            {
                _controlStream?.Dispose();
            }
            catch
            {
            }

            try
            {
                _controlClient?.Close();
            }
            catch
            {
            }

            try
            {
                _frameClient?.Close();
            }
            catch
            {
            }

            _controlStream = null;
            _controlClient = null;
            _frameClient = null;
            _controlReadTask = null;
            _helloSent = false;
            _sessionConfigSent = false;
            _laneCalibrationSent = false;
            _videoEncoderProbeReported = false;
            ClearPendingAsyncReadback();
        }

        private static bool AreCameraPermissionsGranted()
        {
            return OVRPermissionsRequester.IsPermissionGranted(OVRPermissionsRequester.Permission.Scene) &&
                   OVRPermissionsRequester.IsPermissionGranted(OVRPermissionsRequester.Permission.PassthroughCameraAccess);
        }

        private void RequestCameraPermissionsIfNeeded()
        {
            if (_permissionsRequested || AreCameraPermissionsGranted())
            {
                return;
            }

            _permissionsRequested = true;
            OVRPermissionsRequester.Request(new[]
            {
                OVRPermissionsRequester.Permission.Scene,
                OVRPermissionsRequester.Permission.PassthroughCameraAccess,
            });
        }

        private void QueueStatus(string stage, string message = null)
        {
            _queuedStatuses.Enqueue(new QueuedStatus
            {
                stage = stage,
                message = message,
            });
        }

        private void ReportFrameSendBlocked(string note)
        {
            note = string.IsNullOrWhiteSpace(note) ? "unknown" : note;
            _consecutiveFrameSendFailures++;
            var shouldEmit =
                _consecutiveFrameSendFailures == 1 ||
                _consecutiveFrameSendFailures == 15 ||
                _consecutiveFrameSendFailures % 60 == 0 ||
                !string.Equals(note, _lastFrameSendFailureNote, StringComparison.Ordinal);

            _lastFrameSendFailureNote = note;
            if (shouldEmit)
            {
                EmitLocalStatus("frame_send_blocked", $"{note} | consecutive {_consecutiveFrameSendFailures}");
            }
        }

        private void ReportFrameSendResumedIfNeeded(string note)
        {
            if (_consecutiveFrameSendFailures > 0)
            {
                EmitLocalStatus("frame_send_resumed", $"{note} | after {_consecutiveFrameSendFailures} blocked");
            }

            _consecutiveFrameSendFailures = 0;
            _lastFrameSendFailureNote = null;
        }

        private void EmitLocalStatus(string stage, string message = null)
        {
            var payload = new LocalTrackerStatusMessage
            {
                kind = "tracker_status",
                stage = stage,
                shot_id = _shotId,
                message = message,
            };

            _latestStatusLine = string.IsNullOrWhiteSpace(message) ? stage : $"{stage} | {message}";
            var json = JsonUtility.ToJson(payload);
            onTrackerStatus.Invoke(json);
            TrackerStatusReceived?.Invoke(json);
            Debug.Log($"[QuestBowlingStreamClient] status={stage} message={message}");
            AppendStatusLog(stage, message);
            MirrorLocalStatusToLaptop(stage, payload);
        }

        private void MirrorLocalStatusToLaptop(string stage, LocalTrackerStatusMessage payload)
        {
            if (!_controlConnected || _controlStream == null || payload == null)
            {
                return;
            }

            if (stage != null && (stage.StartsWith("remote_", StringComparison.Ordinal) || string.Equals(stage, "shot_result_received", StringComparison.Ordinal)))
            {
                return;
            }

            try
            {
                var json = JsonUtility.ToJson(payload);
                var bytes = Encoding.UTF8.GetBytes(json);
                lock (_controlSendGate)
                {
                    if (_controlStream == null)
                    {
                        return;
                    }

                    BowlingProtocol.WritePacket(_controlStream, BowlingPacketType.TrackerStatus, bytes);
                }
            }
            catch
            {
            }
        }

        private void AppendStatusLog(string stage, string message)
        {
            try
            {
                if (string.IsNullOrWhiteSpace(_statusLogPath))
                {
                    _statusLogPath = Path.Combine(Application.persistentDataPath, "quest_bowling_status.log");
                }

                var line = $"{DateTimeOffset.UtcNow:O} | {stage}";
                if (!string.IsNullOrWhiteSpace(message))
                {
                    line += $" | {message}";
                }

                File.AppendAllText(_statusLogPath, line + Environment.NewLine);
            }
            catch
            {
            }
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

        private static void WriteUInt64(byte[] buffer, int offset, ulong value)
        {
            buffer[offset + 0] = (byte)(value & 0xFF);
            buffer[offset + 1] = (byte)((value >> 8) & 0xFF);
            buffer[offset + 2] = (byte)((value >> 16) & 0xFF);
            buffer[offset + 3] = (byte)((value >> 24) & 0xFF);
            buffer[offset + 4] = (byte)((value >> 32) & 0xFF);
            buffer[offset + 5] = (byte)((value >> 40) & 0xFF);
            buffer[offset + 6] = (byte)((value >> 48) & 0xFF);
            buffer[offset + 7] = (byte)((value >> 56) & 0xFF);
        }

        private sealed class QueuedInboundPacket
        {
            public BowlingPacketType type;
            public string json;
        }

        private sealed class QueuedStatus
        {
            public string stage;
            public string message;
        }
    }
}
