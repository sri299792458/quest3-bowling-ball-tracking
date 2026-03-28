using System;
using System.Collections;
using System.Text;
using BallTracking.Runtime.Transport;
using Meta.XR;
using Unity.WebRTC;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.Networking;

namespace BallTracking.Runtime
{
    public sealed class QuestBowlingStreamClient : MonoBehaviour
    {
        [Serializable]
        public sealed class StringEvent : UnityEvent<string> { }

        [Serializable]
        private sealed class IncomingEnvelope
        {
            public string kind;
        }

        [Serializable]
        private sealed class OfferRequest
        {
            public string session_id;
            public string type;
            public string sdp;
            public string app_version;
            public string device_name;
        }

        [Serializable]
        private sealed class AnswerResponse
        {
            public string type;
            public string sdp;
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

        [Header("Camera")]
        [SerializeField] private PassthroughCameraAccess cameraAccess;
        [SerializeField] private PassthroughCameraAccess.CameraPositionType cameraPosition = PassthroughCameraAccess.CameraPositionType.Left;

        [Header("Signaling")]
        [SerializeField] private string serverHost = "192.168.1.2";
        [SerializeField] private int serverPort = 5799;
        [SerializeField] private string signalingPath = "/api/webrtc/session";
        [SerializeField] private float reconnectDelaySeconds = 2f;
        [SerializeField] private float iceGatherTimeoutSeconds = 3f;
        [SerializeField] private bool useGoogleStun = false;
        [SerializeField] private string stunServerUrl = "stun:stun.l.google.com:19302";

        [Header("Streaming")]
        [SerializeField] private int targetSendFps = 15;
        [SerializeField] private int targetBitrateKbps = 3500;
        [SerializeField] private bool autoStreamWhenConnected = true;
        [SerializeField] private bool verboseLogging;

        [Header("Events")]
        [SerializeField] private StringEvent onTrackerStatus = new();
        [SerializeField] private StringEvent onShotResultJson = new();

        public event Action<string> TrackerStatusReceived;
        public event Action<string> ShotResultReceived;

        private Coroutine _webrtcUpdateCoroutine;
        private Coroutine _connectionLoopCoroutine;
        private RTCPeerConnection _peerConnection;
        private RTCDataChannel _controlChannel;
        private VideoStreamTrack _videoTrack;
        private RTCRtpSender _videoSender;
        private RenderTexture _streamTexture;
        private bool _connecting;
        private bool _helloSent;
        private bool _sessionConfigSent;
        private bool _laneCalibrationSent;
        private double _lastBlitTime;
        private string _sessionId;
        private string _shotId = "default-shot";
        private BowlingLaneCalibration _laneCalibration;

        public bool IsConnected =>
            _peerConnection != null &&
            _peerConnection.ConnectionState == RTCPeerConnectionState.Connected &&
            _controlChannel != null &&
            _controlChannel.ReadyState == RTCDataChannelState.Open;

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
            _webrtcUpdateCoroutine = StartCoroutine(WebRTC.Update());
            _connectionLoopCoroutine = StartCoroutine(ConnectionLoop());
        }

        private void OnDisable()
        {
            if (_connectionLoopCoroutine != null)
            {
                StopCoroutine(_connectionLoopCoroutine);
                _connectionLoopCoroutine = null;
            }

            if (_webrtcUpdateCoroutine != null)
            {
                StopCoroutine(_webrtcUpdateCoroutine);
                _webrtcUpdateCoroutine = null;
            }

            CleanupPeerConnection();
            DisposeStreamTexture();
        }

        private void Update()
        {
            if (!autoStreamWhenConnected || !IsConnected || cameraAccess == null || !cameraAccess.IsPlaying)
            {
                return;
            }

            var sourceTexture = cameraAccess.GetTexture();
            if (sourceTexture == null)
            {
                return;
            }

            EnsureStreamTexture(sourceTexture.width, sourceTexture.height);

            var minInterval = 1.0 / Mathf.Max(1, targetSendFps);
            if (!cameraAccess.IsUpdatedThisFrame || Time.unscaledTimeAsDouble - _lastBlitTime < minInterval)
            {
                return;
            }

            Graphics.Blit(sourceTexture, _streamTexture);
            _lastBlitTime = Time.unscaledTimeAsDouble;

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
        }

        public void SendShotMarker(BowlingShotMarkerType markerType)
        {
            if (!CanSendControlMessages())
            {
                return;
            }

            SendJsonMessage(new ShotMarkerMessage
            {
                kind = "shot_marker",
                session_id = _sessionId,
                shot_id = _shotId,
                marker_type = (int)markerType,
                timestamp_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            });
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

            if (cameraAccess == null)
            {
                Debug.LogWarning("[QuestBowlingStreamClient] Missing PassthroughCameraAccess.");
                _connecting = false;
                yield break;
            }

            if (!cameraAccess.IsPlaying || cameraAccess.GetTexture() == null)
            {
                if (verboseLogging)
                {
                    Debug.Log("[QuestBowlingStreamClient] Waiting for passthrough camera before WebRTC connect.");
                }
                _connecting = false;
                yield break;
            }

            var sourceTexture = cameraAccess.GetTexture();
            EnsureStreamTexture(sourceTexture.width, sourceTexture.height);
            CleanupPeerConnection();
            CreatePeerConnection();

            var offerOp = _peerConnection.CreateOffer();
            yield return offerOp;
            if (offerOp.IsError)
            {
                Debug.LogWarning($"[QuestBowlingStreamClient] CreateOffer failed: {offerOp.Error.message}");
                CleanupPeerConnection();
                _connecting = false;
                yield break;
            }

            var offer = offerOp.Desc;
            var setLocalOp = _peerConnection.SetLocalDescription(ref offer);
            yield return setLocalOp;
            if (setLocalOp.IsError)
            {
                Debug.LogWarning($"[QuestBowlingStreamClient] SetLocalDescription failed: {setLocalOp.Error.message}");
                CleanupPeerConnection();
                _connecting = false;
                yield break;
            }

            yield return WaitForIceGatheringComplete();

            var answerRequest = new OfferRequest
            {
                session_id = _sessionId,
                type = _peerConnection.LocalDescription.type.ToString().ToLowerInvariant(),
                sdp = _peerConnection.LocalDescription.sdp,
                app_version = Application.version,
                device_name = SystemInfo.deviceName,
            };

            var signalingUrl = BuildSignalingUrl();
            var body = Encoding.UTF8.GetBytes(JsonUtility.ToJson(answerRequest));
            var request = new UnityWebRequest(signalingUrl, UnityWebRequest.kHttpVerbPOST)
            {
                uploadHandler = new UploadHandlerRaw(body),
                downloadHandler = new DownloadHandlerBuffer(),
            };
            request.SetRequestHeader("Content-Type", "application/json");

            if (verboseLogging)
            {
                Debug.Log($"[QuestBowlingStreamClient] Posting WebRTC offer to {signalingUrl}");
            }

            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[QuestBowlingStreamClient] Signaling failed: {request.error}");
                request.Dispose();
                CleanupPeerConnection();
                _connecting = false;
                yield break;
            }

            var answer = JsonUtility.FromJson<AnswerResponse>(request.downloadHandler.text);
            request.Dispose();
            if (answer == null || string.IsNullOrWhiteSpace(answer.sdp))
            {
                Debug.LogWarning("[QuestBowlingStreamClient] Signaling returned an empty WebRTC answer.");
                CleanupPeerConnection();
                _connecting = false;
                yield break;
            }

            var remoteDescription = new RTCSessionDescription
            {
                type = ParseSdpType(answer.type),
                sdp = answer.sdp,
            };

            var setRemoteOp = _peerConnection.SetRemoteDescription(ref remoteDescription);
            yield return setRemoteOp;
            if (setRemoteOp.IsError)
            {
                Debug.LogWarning($"[QuestBowlingStreamClient] SetRemoteDescription failed: {setRemoteOp.Error.message}");
                CleanupPeerConnection();
                _connecting = false;
                yield break;
            }

            _connecting = false;
        }

        private void CreatePeerConnection()
        {
            RTCConfiguration configuration = default;
            configuration.bundlePolicy = RTCBundlePolicy.BundlePolicyMaxBundle;
            configuration.iceTransportPolicy = RTCIceTransportPolicy.All;

            if (useGoogleStun && !string.IsNullOrWhiteSpace(stunServerUrl))
            {
                configuration.iceServers = new[]
                {
                    new RTCIceServer
                    {
                        urls = new[] { stunServerUrl },
                    },
                };
            }

            _peerConnection = new RTCPeerConnection(ref configuration);
            _peerConnection.OnConnectionStateChange = state =>
            {
                if (verboseLogging)
                {
                    Debug.Log($"[QuestBowlingStreamClient] Peer state: {state}");
                }

                if (state is RTCPeerConnectionState.Failed or RTCPeerConnectionState.Disconnected or RTCPeerConnectionState.Closed)
                {
                    _helloSent = false;
                    _sessionConfigSent = false;
                    _laneCalibrationSent = false;
                }
            };
            _peerConnection.OnIceConnectionChange = state =>
            {
                if (verboseLogging)
                {
                    Debug.Log($"[QuestBowlingStreamClient] ICE state: {state}");
                }
            };
            _peerConnection.OnIceGatheringStateChange = state =>
            {
                if (verboseLogging)
                {
                    Debug.Log($"[QuestBowlingStreamClient] ICE gathering: {state}");
                }
            };
            _peerConnection.OnDataChannel = BindControlChannel;

            var dataChannelInit = new RTCDataChannelInit
            {
                ordered = true,
                protocol = "bowling-control",
            };
            _controlChannel = _peerConnection.CreateDataChannel("bowling-control", dataChannelInit);
            BindControlChannel(_controlChannel);

            _videoTrack = new VideoStreamTrack(_streamTexture);
            _videoSender = _peerConnection.AddTrack(_videoTrack);
            _videoSender.SyncApplicationFramerate = true;
            var parameters = _videoSender.GetParameters();
            if (parameters.encodings != null && parameters.encodings.Length > 0)
            {
                parameters.encodings[0].maxFramerate = (uint)Mathf.Max(1, targetSendFps);
                parameters.encodings[0].maxBitrate = (ulong)Mathf.Max(250_000, targetBitrateKbps * 1000);
                var error = _videoSender.SetParameters(parameters);
                if (error.errorType != RTCErrorType.None)
                {
                    Debug.LogWarning($"[QuestBowlingStreamClient] Failed to set RTP parameters: {error.message}");
                }
            }

            _helloSent = false;
            _sessionConfigSent = false;
            _laneCalibrationSent = false;
        }

        private void BindControlChannel(RTCDataChannel channel)
        {
            _controlChannel = channel;
            _controlChannel.OnOpen = () =>
            {
                if (verboseLogging)
                {
                    Debug.Log("[QuestBowlingStreamClient] Control channel open.");
                }

                TrySendHello();
                TrySendSessionConfig();
                TrySendLaneCalibration();
            };
            _controlChannel.OnClose = () =>
            {
                if (verboseLogging)
                {
                    Debug.Log("[QuestBowlingStreamClient] Control channel closed.");
                }
            };
            _controlChannel.OnError = error =>
            {
                Debug.LogWarning($"[QuestBowlingStreamClient] Control channel error: {error.message}");
            };
            _controlChannel.OnMessage = bytes =>
            {
                var json = Encoding.UTF8.GetString(bytes);
                if (verboseLogging)
                {
                    Debug.Log($"[QuestBowlingStreamClient] Control message: {json}");
                }
                HandleIncomingJson(json);
            };
        }

        private void HandleIncomingJson(string json)
        {
            IncomingEnvelope envelope = null;
            try
            {
                envelope = JsonUtility.FromJson<IncomingEnvelope>(json);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[QuestBowlingStreamClient] Failed to parse inbound JSON: {ex.Message}");
            }

            switch (envelope?.kind)
            {
                case "tracker_status":
                    onTrackerStatus.Invoke(json);
                    TrackerStatusReceived?.Invoke(json);
                    break;
                case "shot_result":
                    onShotResultJson.Invoke(json);
                    ShotResultReceived?.Invoke(json);
                    break;
                case "pong":
                    break;
                default:
                    if (verboseLogging)
                    {
                        Debug.Log($"[QuestBowlingStreamClient] Ignored inbound message: {json}");
                    }
                    break;
            }
        }

        private void TrySendHello()
        {
            if (_helloSent || !CanSendControlMessages())
            {
                return;
            }

            SendJsonMessage(new HelloMessage
            {
                kind = "hello",
                session_id = _sessionId,
                device_name = SystemInfo.deviceName,
                app_version = Application.version,
            });
            _helloSent = true;
        }

        private void TrySendSessionConfig()
        {
            if (_sessionConfigSent || !CanSendControlMessages() || cameraAccess == null || !cameraAccess.IsPlaying)
            {
                return;
            }

            var intrinsics = cameraAccess.Intrinsics;
            var resolution = cameraAccess.CurrentResolution;
            if (resolution.x <= 0 || resolution.y <= 0)
            {
                return;
            }

            SendJsonMessage(new SessionConfigMessage
            {
                kind = "session_config",
                session_id = _sessionId,
                camera_eye = cameraAccess.CameraPosition == PassthroughCameraAccess.CameraPositionType.Left ? 0 : 1,
                width = resolution.x,
                height = resolution.y,
                fx = intrinsics.FocalLength.x,
                fy = intrinsics.FocalLength.y,
                cx = intrinsics.PrincipalPoint.x,
                cy = intrinsics.PrincipalPoint.y,
                sensor_width = intrinsics.SensorResolution.x,
                sensor_height = intrinsics.SensorResolution.y,
                lens_position_x = intrinsics.LensOffset.position.x,
                lens_position_y = intrinsics.LensOffset.position.y,
                lens_position_z = intrinsics.LensOffset.position.z,
                lens_rotation_x = intrinsics.LensOffset.rotation.x,
                lens_rotation_y = intrinsics.LensOffset.rotation.y,
                lens_rotation_z = intrinsics.LensOffset.rotation.z,
                lens_rotation_w = intrinsics.LensOffset.rotation.w,
                target_send_fps = targetSendFps,
                transport = "webrtc",
                video_codec = "vp8",
                target_bitrate_kbps = targetBitrateKbps,
            });

            _sessionConfigSent = true;
        }

        private void TrySendLaneCalibration()
        {
            if (_laneCalibrationSent || !CanSendControlMessages() || !_laneCalibration.isValid)
            {
                return;
            }

            SendJsonMessage(new LaneCalibrationMessage
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
            });

            _laneCalibrationSent = true;
        }

        private void SendJsonMessage(object payload)
        {
            if (!CanSendControlMessages())
            {
                return;
            }

            var json = JsonUtility.ToJson(payload);
            _controlChannel.Send(Encoding.UTF8.GetBytes(json));
        }

        private bool CanSendControlMessages()
        {
            return _controlChannel != null && _controlChannel.ReadyState == RTCDataChannelState.Open;
        }

        private IEnumerator WaitForIceGatheringComplete()
        {
            var deadline = Time.realtimeSinceStartup + iceGatherTimeoutSeconds;
            while (_peerConnection != null &&
                   _peerConnection.IceGatheringState != RTCIceGatheringState.Complete &&
                   Time.realtimeSinceStartup < deadline)
            {
                yield return null;
            }
        }

        private string BuildSignalingUrl()
        {
            var trimmedPath = string.IsNullOrWhiteSpace(signalingPath) ? "/api/webrtc/session" : signalingPath.Trim();
            if (!trimmedPath.StartsWith("/"))
            {
                trimmedPath = "/" + trimmedPath;
            }
            return $"http://{serverHost}:{serverPort}{trimmedPath}";
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
                name = "QuestBowlingWebRtcStream",
            };
            _streamTexture.Create();
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

        private void CleanupPeerConnection()
        {
            try
            {
                _controlChannel?.Close();
            }
            catch
            {
            }

            _controlChannel?.Dispose();
            _controlChannel = null;

            _videoTrack?.Dispose();
            _videoTrack = null;
            _videoSender = null;

            _peerConnection?.Close();
            _peerConnection?.Dispose();
            _peerConnection = null;

            _helloSent = false;
            _sessionConfigSent = false;
            _laneCalibrationSent = false;
        }

        private static RTCSdpType ParseSdpType(string value)
        {
            return value?.ToLowerInvariant() switch
            {
                "answer" => RTCSdpType.Answer,
                "pranswer" => RTCSdpType.Pranswer,
                "rollback" => RTCSdpType.Rollback,
                _ => RTCSdpType.Offer,
            };
        }
    }
}
