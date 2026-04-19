using System;
using System.Runtime.InteropServices;
using UnityEngine;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestEncoderSurfaceInterop : IDisposable
    {
        private const int BlitEventId = 1;

#if UNITY_ANDROID && !UNITY_EDITOR
        private const string NativeLibraryName = "standaloneencodersurfacebridge";

        [DllImport(NativeLibraryName)]
        private static extern bool SQB_SetEncoderSurface(IntPtr surfaceObject);

        [DllImport(NativeLibraryName)]
        private static extern void SQB_ClearEncoderSurface();

        [DllImport(NativeLibraryName)]
        private static extern void SQB_SetSourceTexture(IntPtr nativeTexture, int width, int height);

        [DllImport(NativeLibraryName)]
        private static extern void SQB_SetOutputSize(int width, int height);

        [DllImport(NativeLibraryName)]
        private static extern void SQB_SetPresentationTimeUs(long presentationTimeUs);

        [DllImport(NativeLibraryName)]
        private static extern IntPtr SQB_GetRenderEventFunc();

        [DllImport(NativeLibraryName)]
        private static extern IntPtr SQB_GetLastError();
#endif

        public bool TryBindEncoderSurface(IntPtr rawSurfaceObject, out string note)
        {
            note = "surface_interop_unavailable";

#if UNITY_ANDROID && !UNITY_EDITOR
            if (rawSurfaceObject == IntPtr.Zero)
            {
                note = "surface_missing";
                return false;
            }

            var ok = SQB_SetEncoderSurface(rawSurfaceObject);
            note = ok ? "surface_bound" : GetLastErrorString();
            return ok;
#else
            note = "android_only";
            return false;
#endif
        }

        public void ClearEncoderSurface()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            SQB_ClearEncoderSurface();
#endif
        }

        public void UpdateSourceTexture(RenderTexture renderTexture)
        {
            if (renderTexture == null)
            {
                return;
            }

#if UNITY_ANDROID && !UNITY_EDITOR
            SQB_SetSourceTexture(renderTexture.GetNativeTexturePtr(), renderTexture.width, renderTexture.height);
#endif
        }

        public void UpdateOutputSize(int width, int height)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            SQB_SetOutputSize(Mathf.Max(1, width), Mathf.Max(1, height));
#endif
        }

        public void UpdatePresentationTimeUs(long presentationTimeUs)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            SQB_SetPresentationTimeUs(Math.Max(0L, presentationTimeUs));
#endif
        }

        public void IssueBlit()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            GL.IssuePluginEvent(SQB_GetRenderEventFunc(), BlitEventId);
#endif
        }

        public string GetLastErrorString()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            var ptr = SQB_GetLastError();
            return ptr == IntPtr.Zero ? string.Empty : Marshal.PtrToStringAnsi(ptr);
#else
            return "android_only";
#endif
        }

        public void Dispose()
        {
            ClearEncoderSurface();
        }
    }
}
