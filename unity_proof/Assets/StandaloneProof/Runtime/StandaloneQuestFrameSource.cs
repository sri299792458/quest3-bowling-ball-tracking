using System;
using Meta.XR;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestFrameSource : MonoBehaviour
    {
        [SerializeField] private PassthroughCameraAccess cameraAccess;
        [SerializeField] private PassthroughCameraAccess.CameraPositionType cameraPosition = PassthroughCameraAccess.CameraPositionType.Left;
        [SerializeField] private Vector2Int targetResolution = new(1280, 960);
        [SerializeField] private int targetFps = 30;
        [SerializeField] private bool verboseLogging;

        private RenderTexture _outputTexture;

        public PassthroughCameraAccess CameraAccess => cameraAccess;
        public string CameraSideName => cameraPosition.ToString();
        public RenderTexture OutputTexture => _outputTexture;
        public IntPtr OutputTextureNativePtr => _outputTexture != null ? _outputTexture.GetNativeTexturePtr() : IntPtr.Zero;

        public Vector2Int CurrentOutputResolution
        {
            get
            {
                if (_outputTexture != null)
                {
                    return new Vector2Int(_outputTexture.width, _outputTexture.height);
                }

                return GetTargetResolution();
            }
        }

        private void Awake()
        {
            ConfigureCameraAccess();
        }

        private void OnEnable()
        {
            ConfigureCameraAccess();
        }

        private void OnDestroy()
        {
            DisposeOutputTexture();
        }

        public bool TryRenderCurrentFrame(out string note)
        {
            note = "frame_source_unavailable";
            if (cameraAccess == null)
            {
                note = "camera_access_missing";
                return false;
            }

            if (!cameraAccess.IsPlaying)
            {
                note = "camera_not_playing";
                return false;
            }

            if (!cameraAccess.IsUpdatedThisFrame)
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

            var resolution = GetTargetResolution();
            EnsureOutputTexture(resolution.x, resolution.y);
            Graphics.Blit(sourceTexture, _outputTexture);
            note = $"rendered {resolution.x}x{resolution.y}";
            return true;
        }

        public bool TryGetIntrinsics(out PassthroughCameraAccess.CameraIntrinsics intrinsics)
        {
            intrinsics = default;
            if (cameraAccess == null || !cameraAccess.IsPlaying)
            {
                return false;
            }

            intrinsics = cameraAccess.Intrinsics;
            return true;
        }

        public bool TryGetActualSourceResolution(out Vector2Int resolution)
        {
            resolution = Vector2Int.zero;
            if (cameraAccess == null || !cameraAccess.IsPlaying)
            {
                return false;
            }

            var sourceTexture = cameraAccess.GetTexture();
            if (sourceTexture == null)
            {
                return false;
            }

            resolution = new Vector2Int(Mathf.Max(1, sourceTexture.width), Mathf.Max(1, sourceTexture.height));
            return true;
        }

        private void ConfigureCameraAccess()
        {
            if (cameraAccess == null)
            {
                return;
            }

            cameraAccess.CameraPosition = cameraPosition;

            var requestedMaxFramerate = Mathf.Max(1, targetFps);
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

            if (verboseLogging)
            {
                Debug.Log($"[StandaloneQuestFrameSource] Requested passthrough max fps {requestedMaxFramerate}");
            }
        }

        private Vector2Int GetTargetResolution()
        {
            var width = MakeEven(Mathf.Max(64, targetResolution.x));
            var height = MakeEven(Mathf.Max(64, targetResolution.y));
            return new Vector2Int(width, height);
        }

        private void EnsureOutputTexture(int width, int height)
        {
            if (_outputTexture != null && _outputTexture.width == width && _outputTexture.height == height)
            {
                return;
            }

            DisposeOutputTexture();
            _outputTexture = new RenderTexture(width, height, 0, RenderTextureFormat.ARGB32)
            {
                name = "StandaloneQuestFrameSource",
                useMipMap = false,
                autoGenerateMips = false,
                antiAliasing = 1,
            };
            _outputTexture.Create();
        }

        private void DisposeOutputTexture()
        {
            if (_outputTexture == null)
            {
                return;
            }

            if (_outputTexture.IsCreated())
            {
                _outputTexture.Release();
            }

            Destroy(_outputTexture);
            _outputTexture = null;
        }

        private static int MakeEven(int value)
        {
            if (value <= 64)
            {
                return 64;
            }

            return (value & 1) == 0 ? value : value - 1;
        }
    }
}
