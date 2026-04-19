using System;
using System.Collections.Generic;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public static class QuestVideoEncoderProbe
    {
        [Serializable]
        public sealed class CodecCapability
        {
            public string mime;
            public bool supported;
            public string preferredEncoderName;
            public bool preferredEncoderHardwareAccelerated;
            public bool preferredEncoderSoftwareOnly;
            public bool preferredEncoderVendor;
            public string[] encoderNames;
            public string note;
        }

        [Serializable]
        public sealed class ProbeResult
        {
            public int androidApiLevel;
            public CodecCapability avc;
            public CodecCapability hevc;
        }

        public static ProbeResult Probe()
        {
            return new ProbeResult
            {
                androidApiLevel = GetAndroidApiLevel(),
                avc = ProbeCodec("video/avc"),
                hevc = ProbeCodec("video/hevc"),
            };
        }

        public static string Summarize(ProbeResult result)
        {
            if (result == null)
            {
                return "video_encoder_probe unavailable";
            }

            var avcNames = result.avc?.encoderNames?.Length ?? 0;
            var hevcNames = result.hevc?.encoderNames?.Length ?? 0;
            return
                $"api {result.androidApiLevel} | " +
                $"avc_supported {(result.avc?.supported == true ? 1 : 0)} | " +
                $"avc_preferred {FormatValue(result.avc?.preferredEncoderName)} | " +
                $"avc_hw {(result.avc?.preferredEncoderHardwareAccelerated == true ? 1 : 0)} | " +
                $"avc_encoders {avcNames} | " +
                $"hevc_supported {(result.hevc?.supported == true ? 1 : 0)} | " +
                $"hevc_preferred {FormatValue(result.hevc?.preferredEncoderName)} | " +
                $"hevc_hw {(result.hevc?.preferredEncoderHardwareAccelerated == true ? 1 : 0)} | " +
                $"hevc_encoders {hevcNames}";
        }

        private static string FormatValue(string value)
        {
            return string.IsNullOrWhiteSpace(value) ? "none" : value;
        }

        private static int GetAndroidApiLevel()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                using var versionClass = new AndroidJavaClass("android.os.Build$VERSION");
                return versionClass.GetStatic<int>("SDK_INT");
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[QuestVideoEncoderProbe] Failed to read SDK_INT: {ex.Message}");
                return -1;
            }
#else
            return -1;
#endif
        }

        private static CodecCapability ProbeCodec(string mime)
        {
            var capability = new CodecCapability
            {
                mime = mime,
                supported = false,
                preferredEncoderName = string.Empty,
                preferredEncoderHardwareAccelerated = false,
                preferredEncoderSoftwareOnly = false,
                preferredEncoderVendor = false,
                encoderNames = Array.Empty<string>(),
                note = string.Empty,
            };

#if UNITY_ANDROID && !UNITY_EDITOR
            var encoderNames = new List<string>();
            try
            {
                using var codecListClass = new AndroidJavaClass("android.media.MediaCodecList");
                var regularCodecs = codecListClass.GetStatic<int>("REGULAR_CODECS");
                using var codecList = new AndroidJavaObject("android.media.MediaCodecList", regularCodecs);
                var codecInfos = codecList.Call<AndroidJavaObject[]>("getCodecInfos");

                if (codecInfos == null || codecInfos.Length == 0)
                {
                    capability.note = "no_codec_infos";
                    return capability;
                }

                foreach (var codecInfo in codecInfos)
                {
                    using (codecInfo)
                    {
                        if (!codecInfo.Call<bool>("isEncoder"))
                        {
                            continue;
                        }

                        var supportedTypes = codecInfo.Call<string[]>("getSupportedTypes");
                        if (supportedTypes == null)
                        {
                            continue;
                        }

                        foreach (var supportedType in supportedTypes)
                        {
                            if (!string.Equals(supportedType, mime, StringComparison.OrdinalIgnoreCase))
                            {
                                continue;
                            }

                            var encoderName = codecInfo.Call<string>("getName");
                            encoderNames.Add(encoderName);
                            capability.supported = true;

                            if (string.IsNullOrWhiteSpace(capability.preferredEncoderName))
                            {
                                capability.preferredEncoderName = encoderName;
                                capability.preferredEncoderHardwareAccelerated = TryGetBool(codecInfo, "isHardwareAccelerated");
                                capability.preferredEncoderSoftwareOnly = TryGetBool(codecInfo, "isSoftwareOnly");
                                capability.preferredEncoderVendor = TryGetBool(codecInfo, "isVendor");
                            }
                        }
                    }
                }

                capability.encoderNames = encoderNames.ToArray();
                if (!capability.supported)
                {
                    capability.note = "unsupported";
                }
            }
            catch (Exception ex)
            {
                capability.note = ex.GetType().Name + ": " + ex.Message;
            }
#else
            capability.note = "android_only";
#endif

            return capability;
        }

        private static bool TryGetBool(AndroidJavaObject codecInfo, string methodName)
        {
            if (codecInfo == null)
            {
                return false;
            }

            try
            {
                return codecInfo.Call<bool>(methodName);
            }
            catch
            {
                return false;
            }
        }
    }
}
