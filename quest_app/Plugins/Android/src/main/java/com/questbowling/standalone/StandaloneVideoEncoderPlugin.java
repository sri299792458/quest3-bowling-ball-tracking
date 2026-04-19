package com.questbowling.standalone;

import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import android.view.Surface;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;

public final class StandaloneVideoEncoderPlugin {
    private static final String MIME_TYPE = "video/avc";

    private final Object gate = new Object();

    private MediaCodec codec;
    private MediaMuxer muxer;
    private Surface inputSurface;
    private MediaCodec.BufferInfo bufferInfo;
    private Thread drainThread;
    private boolean running;
    private boolean stopping;
    private boolean muxerStarted;
    private int trackIndex = -1;
    private long writtenSampleCount;
    private String outputPath = "";
    private String lastError = "";
    private int configuredWidth;
    private int configuredHeight;
    private int configuredFps;
    private int configuredBitrateKbps;

    public boolean startSession(String outputPath, int width, int height, int fps, int bitrateKbps, float iFrameIntervalSeconds) {
        synchronized (gate) {
            if (running) {
                lastError = "already_running";
                return false;
            }

            try {
                prepareOutputPath(outputPath);

                bufferInfo = new MediaCodec.BufferInfo();
                codec = MediaCodec.createEncoderByType(MIME_TYPE);

                MediaFormat format = MediaFormat.createVideoFormat(MIME_TYPE, width, height);
                format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
                format.setInteger(MediaFormat.KEY_BIT_RATE, bitrateKbps * 1000);
                format.setInteger(MediaFormat.KEY_FRAME_RATE, fps);
                format.setFloat(MediaFormat.KEY_I_FRAME_INTERVAL, iFrameIntervalSeconds);

                codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
                inputSurface = codec.createInputSurface();
                codec.start();

                muxer = new MediaMuxer(outputPath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
                trackIndex = -1;
                muxerStarted = false;
                writtenSampleCount = 0L;
                lastError = "";
                configuredWidth = width;
                configuredHeight = height;
                configuredFps = fps;
                configuredBitrateKbps = bitrateKbps;
                this.outputPath = outputPath;
                running = true;
                stopping = false;

                drainThread = new Thread(this::drainEncoderLoop, "StandaloneVideoEncoderDrain");
                drainThread.start();
                return true;
            } catch (Exception ex) {
                lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                releaseAllLocked();
                return false;
            }
        }
    }

    public boolean stopSession() {
        Thread threadToJoin;
        synchronized (gate) {
            if (!running || codec == null) {
                lastError = "not_running";
                return false;
            }

            try {
                stopping = true;
                codec.signalEndOfInputStream();
            } catch (Exception ex) {
                lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
            }

            threadToJoin = drainThread;
        }

        if (threadToJoin != null) {
            try {
                threadToJoin.join(5000L);
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
                synchronized (gate) {
                    lastError = "InterruptedException: " + ex.getMessage();
                }
            }
        }

        synchronized (gate) {
            boolean ok = running == false && lastError.isEmpty();
            if (running) {
                releaseAllLocked();
            }
            return ok;
        }
    }

    public void abortSession() {
        synchronized (gate) {
            lastError = "aborted";
            releaseAllLocked();
        }
    }

    public boolean isRunning() {
        synchronized (gate) {
            return running;
        }
    }

    public Surface getInputSurface() {
        synchronized (gate) {
            return inputSurface;
        }
    }

    public String getStatusJson() {
        synchronized (gate) {
            JSONObject root = new JSONObject();
            try {
                root.put("status", running ? "running" : "idle");
                root.put("mime", MIME_TYPE);
                root.put("output_path", outputPath);
                root.put("width", configuredWidth);
                root.put("height", configuredHeight);
                root.put("fps", configuredFps);
                root.put("bitrate_kbps", configuredBitrateKbps);
                root.put("muxer_started", muxerStarted);
                root.put("written_sample_count", writtenSampleCount);
                root.put("stopping", stopping);
                root.put("last_error", lastError);
            } catch (JSONException ex) {
                return "{\"status\":\"error\",\"message\":\"" + escapeJson(ex.getMessage()) + "\"}";
            }

            return root.toString();
        }
    }

    private void drainEncoderLoop() {
        boolean sawEndOfStream = false;

        while (!sawEndOfStream) {
            MediaCodec localCodec;
            MediaMuxer localMuxer;
            MediaCodec.BufferInfo localBufferInfo;

            synchronized (gate) {
                localCodec = codec;
                localMuxer = muxer;
                localBufferInfo = bufferInfo;
                if (localCodec == null || localMuxer == null || localBufferInfo == null) {
                    return;
                }
            }

            int outputBufferIndex;
            try {
                outputBufferIndex = localCodec.dequeueOutputBuffer(localBufferInfo, 10000L);
            } catch (Exception ex) {
                synchronized (gate) {
                    lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                    releaseAllLocked();
                }
                return;
            }

            if (outputBufferIndex == MediaCodec.INFO_TRY_AGAIN_LATER) {
                synchronized (gate) {
                    if (!running && !stopping) {
                        return;
                    }
                }
                continue;
            }

            if (outputBufferIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                synchronized (gate) {
                    if (muxerStarted) {
                        lastError = "output_format_changed_twice";
                        releaseAllLocked();
                        return;
                    }

                    try {
                        trackIndex = muxer.addTrack(codec.getOutputFormat());
                        muxer.start();
                        muxerStarted = true;
                    } catch (Exception ex) {
                        lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                        releaseAllLocked();
                        return;
                    }
                }
                continue;
            }

            if (outputBufferIndex < 0) {
                continue;
            }

            ByteBuffer outputBuffer;
            try {
                outputBuffer = localCodec.getOutputBuffer(outputBufferIndex);
            } catch (Exception ex) {
                synchronized (gate) {
                    lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                    releaseAllLocked();
                }
                return;
            }

            if (outputBuffer == null) {
                localCodec.releaseOutputBuffer(outputBufferIndex, false);
                continue;
            }

            if ((localBufferInfo.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0) {
                localBufferInfo.size = 0;
            }

            if (localBufferInfo.size > 0) {
                synchronized (gate) {
                    if (!muxerStarted) {
                        lastError = "muxer_not_started_before_sample";
                        releaseAllLocked();
                        return;
                    }

                    try {
                        outputBuffer.position(localBufferInfo.offset);
                        outputBuffer.limit(localBufferInfo.offset + localBufferInfo.size);
                        muxer.writeSampleData(trackIndex, outputBuffer, localBufferInfo);
                        writtenSampleCount++;
                    } catch (Exception ex) {
                        lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                        releaseAllLocked();
                        return;
                    }
                }
            }

            sawEndOfStream = (localBufferInfo.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
            localCodec.releaseOutputBuffer(outputBufferIndex, false);
        }

        synchronized (gate) {
            releaseAllLocked();
        }
    }

    private void prepareOutputPath(String targetPath) throws IOException {
        File targetFile = new File(targetPath);
        File parent = targetFile.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IOException("Failed to create parent directory for output.");
        }

        if (targetFile.exists() && !targetFile.delete()) {
            throw new IOException("Failed to overwrite existing output file.");
        }
    }

    private void releaseAllLocked() {
        running = false;
        stopping = false;
        muxerStarted = false;
        trackIndex = -1;

        if (inputSurface != null) {
            try {
                inputSurface.release();
            } catch (Exception ignored) {
            }
            inputSurface = null;
        }

        if (codec != null) {
            try {
                codec.stop();
            } catch (Exception ignored) {
            }
            try {
                codec.release();
            } catch (Exception ignored) {
            }
            codec = null;
        }

        if (muxer != null) {
            try {
                muxer.stop();
            } catch (Exception ignored) {
            }
            try {
                muxer.release();
            } catch (Exception ignored) {
            }
            muxer = null;
        }

        bufferInfo = null;
        drainThread = null;
    }

    private static String escapeJson(String value) {
        return value == null ? "" : value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
