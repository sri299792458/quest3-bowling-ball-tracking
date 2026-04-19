#include <jni.h>
#include <android/log.h>
#include <android/native_window_jni.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <cstdint>
#include <mutex>
#include <string>

namespace
{
    constexpr int kBlitEventId = 1;

    std::mutex g_gate;
    ANativeWindow* g_encoderWindow = nullptr;
    EGLSurface g_encoderSurface = EGL_NO_SURFACE;
    EGLConfig g_encoderConfig = nullptr;
    GLuint g_sourceTexture = 0;
    int g_sourceWidth = 0;
    int g_sourceHeight = 0;
    int g_outputWidth = 0;
    int g_outputHeight = 0;
    GLuint g_sourceFbo = 0;
    std::string g_lastError;

    void SetLastError(const std::string& message)
    {
        g_lastError = message;
        __android_log_print(ANDROID_LOG_ERROR, "StandaloneEncoderSurfaceBridge", "%s", message.c_str());
    }

    void ClearEncoderSurfaceLocked(EGLDisplay display)
    {
        if (g_sourceFbo != 0 && eglGetCurrentContext() != EGL_NO_CONTEXT)
        {
            glDeleteFramebuffers(1, &g_sourceFbo);
        }
        g_sourceFbo = 0;

        if (g_encoderSurface != EGL_NO_SURFACE && display != EGL_NO_DISPLAY)
        {
            eglDestroySurface(display, g_encoderSurface);
        }
        g_encoderSurface = EGL_NO_SURFACE;
        g_encoderConfig = nullptr;

        if (g_encoderWindow != nullptr)
        {
            ANativeWindow_release(g_encoderWindow);
            g_encoderWindow = nullptr;
        }
    }

    bool EnsureEncoderSurfaceLocked(EGLDisplay display)
    {
        if (g_encoderWindow == nullptr)
        {
            SetLastError("encoder_window_missing");
            return false;
        }

        if (g_encoderSurface != EGL_NO_SURFACE)
        {
            return true;
        }

        const EGLint configAttribs[] = {
            EGL_SURFACE_TYPE, EGL_WINDOW_BIT,
            EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR,
            EGL_RED_SIZE, 8,
            EGL_GREEN_SIZE, 8,
            EGL_BLUE_SIZE, 8,
            EGL_ALPHA_SIZE, 8,
            EGL_RECORDABLE_ANDROID, 1,
            EGL_NONE
        };

        EGLint numConfigs = 0;
        if (eglChooseConfig(display, configAttribs, &g_encoderConfig, 1, &numConfigs) != EGL_TRUE || numConfigs <= 0)
        {
            SetLastError("eglChooseConfig_failed");
            g_encoderConfig = nullptr;
            return false;
        }

        g_encoderSurface = eglCreateWindowSurface(display, g_encoderConfig, g_encoderWindow, nullptr);
        if (g_encoderSurface == EGL_NO_SURFACE)
        {
            SetLastError("eglCreateWindowSurface_failed");
            return false;
        }

        return true;
    }

    void EnsureSourceFboLocked()
    {
        if (g_sourceFbo != 0)
        {
            return;
        }

        glGenFramebuffers(1, &g_sourceFbo);
    }

    void RenderIntoEncoderSurface()
    {
        std::lock_guard<std::mutex> lock(g_gate);

        if (g_sourceTexture == 0)
        {
            return;
        }

        const EGLDisplay display = eglGetCurrentDisplay();
        const EGLContext context = eglGetCurrentContext();
        const EGLSurface drawSurface = eglGetCurrentSurface(EGL_DRAW);
        const EGLSurface readSurface = eglGetCurrentSurface(EGL_READ);

        if (display == EGL_NO_DISPLAY || context == EGL_NO_CONTEXT || drawSurface == EGL_NO_SURFACE)
        {
            SetLastError("egl_context_unavailable");
            return;
        }

        if (g_outputWidth <= 0 || g_outputHeight <= 0)
        {
            g_outputWidth = g_sourceWidth;
            g_outputHeight = g_sourceHeight;
        }

        if (!EnsureEncoderSurfaceLocked(display))
        {
            return;
        }

        if (eglMakeCurrent(display, g_encoderSurface, g_encoderSurface, context) != EGL_TRUE)
        {
            SetLastError("eglMakeCurrent_encoder_failed");
            return;
        }

        EnsureSourceFboLocked();

        glBindFramebuffer(GL_READ_FRAMEBUFFER, g_sourceFbo);
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, g_sourceTexture, 0);

        if (glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
        {
            SetLastError("source_fbo_incomplete");
            eglMakeCurrent(display, drawSurface, readSurface, context);
            return;
        }

        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
        glViewport(0, 0, g_outputWidth, g_outputHeight);
        glBlitFramebuffer(
            0, 0, g_sourceWidth, g_sourceHeight,
            0, 0, g_outputWidth, g_outputHeight,
            GL_COLOR_BUFFER_BIT,
            GL_LINEAR);

        eglSwapBuffers(display, g_encoderSurface);

        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        eglMakeCurrent(display, drawSurface, readSurface, context);
    }

    void OnRenderEvent(int eventId)
    {
        if (eventId != kBlitEventId)
        {
            return;
        }

        RenderIntoEncoderSurface();
    }
}

extern "C"
{
    bool SQB_SetEncoderSurface(void* surfaceObject)
    {
        std::lock_guard<std::mutex> lock(g_gate);

        const EGLDisplay display = eglGetCurrentDisplay();
        ClearEncoderSurfaceLocked(display);

        if (surfaceObject == nullptr)
        {
            SetLastError("surface_object_null");
            return false;
        }

        JavaVM* javaVm = nullptr;
        JNIEnv* env = nullptr;

        if (JNI_GetCreatedJavaVMs(&javaVm, 1, nullptr) != JNI_OK || javaVm == nullptr)
        {
            SetLastError("java_vm_unavailable");
            return false;
        }

        if (javaVm->AttachCurrentThread(&env, nullptr) != JNI_OK || env == nullptr)
        {
            SetLastError("attach_current_thread_failed");
            return false;
        }

        jobject surface = reinterpret_cast<jobject>(surfaceObject);
        g_encoderWindow = ANativeWindow_fromSurface(env, surface);
        if (g_encoderWindow == nullptr)
        {
            SetLastError("native_window_from_surface_failed");
            return false;
        }

        g_lastError.clear();
        return true;
    }

    void SQB_ClearEncoderSurface()
    {
        std::lock_guard<std::mutex> lock(g_gate);
        const EGLDisplay display = eglGetCurrentDisplay();
        ClearEncoderSurfaceLocked(display);
    }

    void SQB_SetSourceTexture(void* nativeTexture, int width, int height)
    {
        std::lock_guard<std::mutex> lock(g_gate);
        g_sourceTexture = static_cast<GLuint>(reinterpret_cast<uintptr_t>(nativeTexture));
        g_sourceWidth = width;
        g_sourceHeight = height;
    }

    void SQB_SetOutputSize(int width, int height)
    {
        std::lock_guard<std::mutex> lock(g_gate);
        g_outputWidth = width;
        g_outputHeight = height;
    }

    const char* SQB_GetLastError()
    {
        return g_lastError.c_str();
    }

    typedef void (*UnityRenderingEvent)(int eventId);

    UnityRenderingEvent SQB_GetRenderEventFunc()
    {
        return OnRenderEvent;
    }
}
