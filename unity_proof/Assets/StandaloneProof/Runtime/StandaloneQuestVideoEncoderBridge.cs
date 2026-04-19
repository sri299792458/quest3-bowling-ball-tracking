using System;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestVideoEncoderBridge : IDisposable
    {
        public const string DefaultPluginClassName = "com.questbowling.standalone.StandaloneVideoEncoderPlugin";

        [Serializable]
        public sealed class SessionConfig
        {
            public int width = 1280;
            public int height = 960;
            public int fps = 30;
            public int bitrateKbps = 3500;
            public float iFrameIntervalSeconds = 1.0f;
        }

        private readonly string _pluginClassName;

#if UNITY_ANDROID && !UNITY_EDITOR
        private AndroidJavaObject _plugin;
        private AndroidJavaObject _inputSurface;
#endif

        public StandaloneQuestVideoEncoderBridge(string pluginClassName = DefaultPluginClassName)
        {
            _pluginClassName = string.IsNullOrWhiteSpace(pluginClassName) ? DefaultPluginClassName : pluginClassName;
        }

        public bool TryStartSession(SessionConfig config, string outputPath, out string note)
        {
            config ??= new SessionConfig();
            note = "encoder_unavailable";

#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                EnsurePlugin();
                var started = _plugin.Call<bool>(
                    "startSession",
                    outputPath ?? string.Empty,
                    Math.Max(1, config.width),
                    Math.Max(1, config.height),
                    Math.Max(1, config.fps),
                    Math.Max(1, config.bitrateKbps),
                    Mathf.Max(0.1f, config.iFrameIntervalSeconds));

                _inputSurface = _plugin.Call<AndroidJavaObject>("getInputSurface");
                note = _plugin.Call<string>("getStatusJson");
                return started;
            }
            catch (Exception ex)
            {
                note = ex.GetType().Name + ": " + ex.Message;
                return false;
            }
#else
            note = "android_only";
            return false;
#endif
        }

        public bool TryStopSession(out string note)
        {
            note = "encoder_unavailable";

#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                if (_plugin == null)
                {
                    note = "plugin_missing";
                    return false;
                }

                var stopped = _plugin.Call<bool>("stopSession");
                note = _plugin.Call<string>("getStatusJson");
                _inputSurface?.Dispose();
                _inputSurface = null;
                return stopped;
            }
            catch (Exception ex)
            {
                note = ex.GetType().Name + ": " + ex.Message;
                return false;
            }
#else
            note = "android_only";
            return false;
#endif
        }

        public bool TryStartLiveStream(string host, int port, string sessionId, string shotId, out string note)
        {
            note = "encoder_unavailable";

#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                EnsurePlugin();
                var started = _plugin.Call<bool>(
                    "connectLiveStream",
                    host ?? string.Empty,
                    Math.Max(1, port),
                    sessionId ?? string.Empty,
                    shotId ?? string.Empty);
                note = _plugin.Call<string>("getStatusJson");
                return started;
            }
            catch (Exception ex)
            {
                note = ex.GetType().Name + ": " + ex.Message;
                return false;
            }
#else
            note = "android_only";
            return false;
#endif
        }

        public bool TryStopLiveStream(out string note)
        {
            note = "encoder_unavailable";

#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                if (_plugin == null)
                {
                    note = "plugin_missing";
                    return false;
                }

                var stopped = _plugin.Call<bool>("disconnectLiveStream");
                note = _plugin.Call<string>("getStatusJson");
                return stopped;
            }
            catch (Exception ex)
            {
                note = ex.GetType().Name + ": " + ex.Message;
                return false;
            }
#else
            note = "android_only";
            return false;
#endif
        }

        public void AbortSession()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                _plugin?.Call("abortSession");
            }
            catch
            {
                // Best-effort cleanup path.
            }
            finally
            {
                _inputSurface?.Dispose();
                _inputSurface = null;
            }
#endif
        }

        public string GetStatusJson()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                EnsurePlugin();
                return _plugin.Call<string>("getStatusJson");
            }
            catch (Exception ex)
            {
                return "{\"status\":\"error\",\"message\":\"" + EscapeJson(ex.Message) + "\"}";
            }
#else
            return "{\"status\":\"android_only\"}";
#endif
        }

        public IntPtr GetInputSurfaceRawObject()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_inputSurface == null)
            {
                return IntPtr.Zero;
            }

            return _inputSurface.GetRawObject();
#else
            return IntPtr.Zero;
#endif
        }

        public void Dispose()
        {
            AbortSession();

#if UNITY_ANDROID && !UNITY_EDITOR
            _plugin?.Dispose();
            _plugin = null;
#endif
        }

#if UNITY_ANDROID && !UNITY_EDITOR
        private void EnsurePlugin()
        {
            if (_plugin != null)
            {
                return;
            }

            _plugin = new AndroidJavaObject(_pluginClassName);
        }
#endif

        private static string EscapeJson(string value)
        {
            return (value ?? string.Empty).Replace("\\", "\\\\").Replace("\"", "\\\"");
        }
    }
}
